import io
import json
import logging
import os
import wave
import numpy as np

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from core.deps import get_db, require_login, templates
from core.db import get_sqlite
from core.tts_text import ko_text

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None
try:
    import av
    _orig_av_open = av.open
    def _safe_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _safe_av_open
except Exception:
    pass

try:
    from supertonic import TTS
    import soundfile as sf
except Exception as e:
    TTS = None
    sf = None
    logging.getLogger(__name__).warning("TTS / soundfile 임포트 실패: %s", e)

router = APIRouter()
log = logging.getLogger(__name__)

MAX_AUDIO = 2 * 1024 * 1024
TTS_DIR = os.getenv("TTS_DIR", "models/supertonic")
TTS_VOICES = {"F1", "M1"}
TTS_SPEEDS = {"slow": 0.9, "normal": 1.05, "fast": 1.25}
MENU_FONTS = (100, 115, 130, 150, 175, 200)
_whisper = None
_tts = None
_tts_styles = {}


@router.get("/eyemouse", response_class=HTMLResponse)
async def eyemouse(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="worker/eyemouse.html", context={
        "request": request, "page_title": "아이 마우스",
        "user_name": u["name"],
    })


@router.get("/real_trans", response_class=HTMLResponse)
async def real_trans(request: Request, requested: str = "", u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="worker/realtime_trans.html", context={
        "request": request, "page_title": "실시간 자막",
        "user_name": u["name"],
        "requested": requested == "1",
    })


def get_whisper():
    global _whisper
    if _whisper is None:
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper


# 서버 VAD(onnxruntime) 실패 시 VAD 없이 재시도. 브라우저 VAD에서 이미 발화 구간 절단
def wav_to_numpy(data: bytes):
    try:
        with io.BytesIO(data) as bio:
            with wave.open(bio, "rb") as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                frames = wf.readframes(wf.getnframes())
                if sample_width == 2:
                    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                elif sample_width == 4:
                    audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
                else:
                    audio = np.frombuffer(frames, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0
                if channels > 1:
                    audio = audio[::channels]
                return audio
    except Exception:
        return None


def transcribe(model, data):
    audio_input = wav_to_numpy(data)
    if audio_input is None:
        audio_input = io.BytesIO(data)
    try:
        segs, _ = model.transcribe(audio_input, language="ko", beam_size=1, vad_filter=True)
        return "".join(s.text for s in segs).strip()
    except Exception as e:
        log.warning("서버 VAD 실패, VAD 없이 재시도: %s: %s", type(e).__name__, e)
    segs, _ = model.transcribe(audio_input, language="ko", beam_size=1, vad_filter=False)
    return "".join(s.text for s in segs).strip()

# 녹음은 메모리에서만 처리, 인식 결과는 로그 금지
@router.post("/api/stt")
async def stt(audio: UploadFile = File(...), u: dict = Depends(require_login)):
    data = await audio.read(MAX_AUDIO + 1)
    if len(data) > MAX_AUDIO:
        return JSONResponse({"error": "음성이 너무 깁니다"}, status_code=413)
    try:
        model = await run_in_threadpool(get_whisper)
    except Exception:
        log.exception("whisper 모델 로드 실패")
        return JSONResponse({"error": "음성 인식 모델을 사용할 수 없습니다"}, status_code=503)
    try:
        text = await run_in_threadpool(transcribe, model, data)
    except Exception as e:
        log.warning("음성 디코딩 실패: %s: %s", type(e).__name__, e)
        return JSONResponse({"error": "음성을 처리할 수 없습니다"}, status_code=400)
    return {"text": text}


def get_tts():
    global _tts
    if _tts is None:
        if TTS is None:
            raise RuntimeError("supertonic 또는 soundfile 모듈이 설치되지 않았습니다")
        auto_dl = os.getenv("TTS_AUTO_DOWNLOAD", "1").lower() in ("1", "true", "yes")
        try:
            _tts = TTS(model="supertonic-3", model_dir=TTS_DIR, auto_download=False)
        except Exception:
            if auto_dl:
                log.info("supertonic 로컬 모델 없음 -> 자동 다운로드 시도")
                _tts = TTS(model="supertonic-3", model_dir=TTS_DIR, auto_download=True)
            else:
                raise
    return _tts


def get_voice_style(model, voice):
    if voice not in _tts_styles:
        _tts_styles[voice] = model.get_voice_style(voice)
    return _tts_styles[voice]


def synth_wav(model, text, voice, speed):
    style = get_voice_style(model, voice)
    wav, _ = model.synthesize(ko_text(text), voice_style=style, lang="ko", total_steps=4, speed=speed)
    buf = io.BytesIO()
    sf.write(buf, wav.squeeze(), model.sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# 텍스트는 로그에 남기지 않음
@router.post("/api/tts")
async def tts(
    text: str = Form(""),
    voice: str = Form(...),
    speed: str = Form(...),
    u: dict = Depends(require_login),
):
    text = text.strip()
    if not text or len(text) > 300:
        return JSONResponse({"error": "내용이 없거나 너무 깁니다"}, status_code=400)
    if voice not in TTS_VOICES:
        return JSONResponse({"error": "지원하지 않는 보이스입니다"}, status_code=400)
    if speed not in TTS_SPEEDS:
        return JSONResponse({"error": "지원하지 않는 속도입니다"}, status_code=400)
    try:
        model = await run_in_threadpool(get_tts)
    except Exception:
        log.exception("supertonic 모델 로드 실패")
        return JSONResponse({"error": "음성 합성 모델을 사용할 수 없습니다"}, status_code=503)
    try:
        wav = await run_in_threadpool(synth_wav, model, text, voice, TTS_SPEEDS[speed])
    except Exception as e:
        log.warning("tts 합성 실패: %s", type(e).__name__)
        return JSONResponse({"error": "읽을 수 없는 글자가 있습니다"}, status_code=400)
    return Response(wav, media_type="audio/wav")


@router.post("/api/accessibility")
async def save_accessibility(request: Request, user=Depends(require_login)):
    body = await request.json()
    tts_voice = body.get("tts_voice", "F1")
    tts_speed = body.get("tts_speed", "normal")
    menu_font = body.get("menu_font", 100)
    settings = json.dumps({
        "high_contrast": bool(body.get("high_contrast", False)),
        "font_size": int(body.get("font_size", 100)),
        "menu_font": menu_font if menu_font in MENU_FONTS else 100,
        "large_target": bool(body.get("large_target", False)),
        "easy_mode": bool(body.get("easy_mode", False)),
        "head_mouse": bool(body.get("head_mouse", False)),
        "voice_amount": bool(body.get("voice_amount", False)),
        "dwell_read": bool(body.get("dwell_read", False)),
        "click_read": bool(body.get("click_read", False)),
        "tts_voice": tts_voice if tts_voice in TTS_VOICES else "F1",
        "tts_speed": tts_speed if tts_speed in TTS_SPEEDS else "normal",
        "sr_mode": bool(body.get("sr_mode", False)),
        "menu_code": bool(body.get("menu_code", False)),
    })
    conn = get_sqlite()
    try:
        conn.execute(
            "UPDATE users SET accessibility_settings=? WHERE id=?",
            (settings, user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/api/trans_request")
async def trans_request(
    request: Request,
    translator_name: str = Form(...),
    service_type: str = Form(""),
    request_date: str = Form(""),
    request_time: str = Form(""),
    duration: str = Form(""),
    meeting_link: str = Form(""),
    details: str = Form(""),
    u: dict = Depends(require_login),
    conn = Depends(get_db),
):
    user_id = u["id"]
    conn.execute(
        """INSERT INTO trans_requests
           (user_id, translator_name, service_type, request_date, request_time, duration, meeting_link, details)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, translator_name, service_type, request_date, request_time, duration, meeting_link, details),
    )
    conn.commit()
    return RedirectResponse(url="/real_trans?requested=1", status_code=303)
