from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from core.deps import get_db, require_login, templates

router = APIRouter()


class VoiceInput(BaseModel):
    text: str


@router.post("/api/text")
async def receive_voice_text(request: Request, data: VoiceInput, u: dict = Depends(require_login)):
    return {"status": "success", "received_text": data.text}


@router.get("/eyemouse", response_class=HTMLResponse)
async def eyemouse(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="worker/eyemouse.html", context={
        "request": request, "page_title": "아이 마우스",
        "user_name": u["user_name"],
    })


@router.get("/real_trans", response_class=HTMLResponse)
async def real_trans(request: Request, requested: str = "", u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="worker/realtime_trans.html", context={
        "request": request, "page_title": "실시간 자막",
        "user_name": u["user_name"],
        "requested": requested == "1",
    })


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
    user_id = u["user_id"]
    conn.execute(
        """INSERT INTO trans_requests
           (user_id, translator_name, service_type, request_date, request_time, duration, meeting_link, details)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, translator_name, service_type, request_date, request_time, duration, meeting_link, details),
    )
    conn.commit()
    return RedirectResponse(url="/real_trans?requested=1", status_code=303)
