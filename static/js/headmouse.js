// 폐쇄망이면 static/vendor로
const VISION_ESM_URL = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/vision_bundle.mjs';
const VISION_WASM_BASE = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm';
const MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';

const NOSE_IDX = 1;
// 코 이동량 0.1이면 화면 끝까지
const SENS = 0.10;

const NEUTRAL_MS = 2000;
const NO_FACE_MS = 3000;
const MAGNET_RADIUS = 60;
// 대상 고정: 반경 1.5배, 전환 150ms, 이탈 250ms
const STICKY_RADIUS = MAGNET_RADIUS * 1.5;
const SWITCH_GAP = 20;
const SWITCH_MS = 150;
const LEAVE_MS = 250;
const CAND_REFRESH_MS = 400;
const DWELL_OPTS = [1000, 1500, 2000, 3000];
const DEFAULT_DWELL = 1500;
const SCROLL_BAND = 60;
const SCROLL_SPEED = 14;
const ONEEURO_MIN_CUTOFF = 0.5;
const ONEEURO_BETA = 0.007;
const ONEEURO_DCUTOFF = 1.0;

const CAND_SEL = 'a[href], button, input, select, textarea, [role=button], [role=link], .tr-link, label[for]';

const LS_NEUTRAL = 'hm_neutral';
const LS_DWELL = 'hm_dwell';

const DEBUG = new URLSearchParams(location.search).get('hm_debug') === '1';

function lowPassAlpha(cutoff, dt) {
    const tau = 1 / (2 * Math.PI * cutoff);
    return 1 / (1 + tau / dt);
}

function LowPass() {
    this.y = 0;
    this.init = false;
}
LowPass.prototype.filter = function(x, a) {
    const out = this.init ? a * x + (1 - a) * this.y : x;
    this.y = out;
    this.init = true;
    return out;
};

function OneEuro(minCutoff, beta, dCutoff) {
    this.minCutoff = minCutoff;
    this.beta = beta;
    this.dCutoff = dCutoff;
    this.xFilt = new LowPass();
    this.dxFilt = new LowPass();
    this.lastT = null;
    this.lastX = null;
}
OneEuro.prototype.filter = function(x, t) {
    if (this.lastT == null) {
        this.lastT = t;
        this.lastX = x;
        this.xFilt.filter(x, 1);
        this.dxFilt.filter(0, 1);
        return x;
    }
    const dt = Math.max((t - this.lastT) / 1000, 1 / 120);
    this.lastT = t;
    const dx = (x - this.lastX) / dt;
    this.lastX = x;
    const edx = this.dxFilt.filter(dx, lowPassAlpha(this.dCutoff, dt));
    const cutoff = this.minCutoff + this.beta * Math.abs(edx);
    return this.xFilt.filter(x, lowPassAlpha(cutoff, dt));
};

const state = {
    paused: false,
    debug: DEBUG,
    dwellMs: Number(localStorage.getItem(LS_DWELL)) || DEFAULT_DWELL,
    neutral: null,
    calibrating: false,
    calibSamples: [],
    calibStart: 0,
    noFaceSince: 0,
    faceLost: false,
    mouseX: innerWidth / 2,
    mouseY: innerHeight / 2,
    cands: [],
    curTgt: null,
    lockTgt: null,
    switchTgt: null,
    switchSince: 0,
    leaveSince: 0,
    dwellStart: 0,
    restX: -1000,
    restY: -1000,
    restStart: 0,
    restFired: false,
};

let video, faceLandmarker;
let cursorEl, msgEl, calibEl, calibTextEl, bandTop, bandBottom;
let widgetEl, fabEl, fabLabelEl, panelHeaderEl, hmSectionEl, pauseBtn, dwellBtn;
let filtX, filtY;

function announce(msg) {
    document.getElementById('srLive').textContent = msg;
}

function showMsg(text) {
    msgEl.textContent = text;
    msgEl.hidden = !text;
}

function buildUI() {
    video = document.createElement('video');
    video.className = 'hm-video';
    video.setAttribute('playsinline', '');
    video.muted = true;
    document.body.appendChild(video);

    cursorEl = document.createElement('div');
    cursorEl.className = 'hm-cursor';
    cursorEl.setAttribute('aria-hidden', 'true');
    const dot = document.createElement('div');
    dot.className = 'hm-cursor-dot';
    cursorEl.appendChild(dot);
    document.body.appendChild(cursorEl);

    bandTop = document.createElement('div');
    bandTop.className = 'hm-band hm-band-top';
    bandTop.setAttribute('aria-hidden', 'true');
    bandTop.textContent = '▲';
    bandBottom = document.createElement('div');
    bandBottom.className = 'hm-band hm-band-bottom';
    bandBottom.setAttribute('aria-hidden', 'true');
    bandBottom.textContent = '▼';
    document.body.appendChild(bandTop);
    document.body.appendChild(bandBottom);

    msgEl = document.createElement('div');
    msgEl.className = 'hm-msg';
    msgEl.setAttribute('role', 'status');
    msgEl.hidden = true;
    document.body.appendChild(msgEl);

    calibEl = document.createElement('div');
    calibEl.className = 'hm-calib';
    calibEl.hidden = true;
    calibTextEl = document.createElement('p');
    calibTextEl.textContent = '화면 가운데를 보고 편하게 앉으세요';
    calibEl.appendChild(calibTextEl);
    document.body.appendChild(calibEl);

    bindWidget();
}

function bindWidget() {
    widgetEl = document.getElementById('a11yWidget');
    fabEl = document.getElementById('a11yFab');
    fabLabelEl = document.getElementById('a11yFabLabel');
    panelHeaderEl = document.getElementById('a11yPanelHeader');
    hmSectionEl = document.getElementById('a11yHmSection');
    pauseBtn = document.getElementById('a11yHmPause');
    dwellBtn = document.getElementById('a11yHmDwell');
    const centerBtn = document.getElementById('a11yHmCenter');

    // select는 머리로 못 고름
    if (DWELL_OPTS.indexOf(state.dwellMs) < 0) state.dwellMs = DEFAULT_DWELL;
    dwellBtn.textContent = '응시 ' + (state.dwellMs / 1000) + '초';

    pauseBtn.addEventListener('click', togglePause);
    centerBtn.addEventListener('click', function() {
        if (state.debug) return;
        startCalibration();
    });
    dwellBtn.addEventListener('click', function() {
        const idx = (DWELL_OPTS.indexOf(state.dwellMs) + 1) % DWELL_OPTS.length;
        state.dwellMs = DWELL_OPTS[idx];
        localStorage.setItem(LS_DWELL, String(state.dwellMs));
        dwellBtn.textContent = '응시 ' + (state.dwellMs / 1000) + '초';
        announce('응시 시간 ' + (state.dwellMs / 1000) + '초');
    });

    hmSectionEl.hidden = false;
    panelHeaderEl.hidden = false;
    panelHeaderEl.textContent = state.debug ? '디버그 모드' : '카메라 사용 중';
    const dot = document.createElement('span');
    dot.className = 'a11y-cam-dot';
    panelHeaderEl.prepend(dot);
    updatePauseUI();
}

function updatePauseUI() {
    fabEl.classList.toggle('hm-run', !state.paused);
    fabEl.classList.toggle('hm-paused', state.paused);
    fabLabelEl.hidden = false;
    fabLabelEl.textContent = state.paused ? '일시정지' : '작동 중';
}

function togglePause() {
    state.paused = !state.paused;
    pauseBtn.textContent = state.paused ? '재개' : '일시정지';
    pauseBtn.setAttribute('aria-pressed', String(state.paused));
    cursorEl.classList.toggle('hm-paused', state.paused);
    updatePauseUI();
    if (state.paused && state.curTgt) {
        state.curTgt.classList.remove('hm-target');
        state.curTgt = null;
        state.lockTgt = null;
        setRing(0);
    }
    announce(state.paused ? '헤드마우스 일시정지' : '헤드마우스 재개');
}

function setRing(pct) {
    cursorEl.style.setProperty('--p', pct);
}

function isSelectable(el) {
    if (el.disabled) return false;
    if (el.closest('[hidden]')) return false;
    // display:none은 rect 0에서 걸림
    if (getComputedStyle(el).visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return false;
    return true;
}

function refreshCands() {
    // 모달 떠 있으면 뒤 화면 제외
    const modal = document.querySelector('.modal.show');
    const els = modal
        ? Array.from(modal.querySelectorAll(CAND_SEL)).concat(Array.from(widgetEl.querySelectorAll(CAND_SEL)))
        : Array.from(document.querySelectorAll(CAND_SEL));
    state.cands = els.filter(isSelectable);
}

function distToRect(x, y, r) {
    const dx = Math.max(r.left - x, 0, x - r.right);
    const dy = Math.max(r.top - y, 0, y - r.bottom);
    return Math.hypot(dx, dy);
}

function candList() {
    if (state.paused) return state.cands.filter(el => widgetEl.contains(el));
    return state.cands;
}

function findTarget(x, y) {
    const list = candList();
    let best = null;
    let bestDist = MAGNET_RADIUS;
    for (const el of list) {
        const d = distToRect(x, y, el.getBoundingClientRect());
        if (d <= bestDist) {
            bestDist = d;
            best = el;
        }
    }
    return best;
}

function pickTarget(x, y) {
    const now = performance.now();
    const cur = state.curTgt;
    const best = findTarget(x, y);
    if (!cur || !cur.isConnected) return best;
    const curDist = distToRect(x, y, cur.getBoundingClientRect());
    if (curDist > STICKY_RADIUS) {
        if (!state.leaveSince) state.leaveSince = now;
        return now - state.leaveSince < LEAVE_MS ? cur : best;
    }
    state.leaveSince = 0;
    if (!best || best === cur || distToRect(x, y, best.getBoundingClientRect()) + SWITCH_GAP > curDist) {
        state.switchTgt = null;
        return cur;
    }
    if (state.switchTgt !== best) {
        state.switchTgt = best;
        state.switchSince = now;
    }
    return now - state.switchSince >= SWITCH_MS ? best : cur;
}

function activate(el) {
    const tag = el.tagName;
    if (tag === 'SELECT' || tag === 'TEXTAREA') {
        el.focus();
        return;
    }
    if (tag === 'INPUT') {
        const type = (el.type || 'text').toLowerCase();
        if (type === 'checkbox' || type === 'radio') el.click();
        else el.focus();
        return;
    }
    el.click();
}

function doMagnetDwell(x, y) {
    const tgt = pickTarget(x, y);
    if (tgt !== state.curTgt) {
        if (state.curTgt) state.curTgt.classList.remove('hm-target');
        state.lockTgt = null;
        state.switchTgt = null;
        state.leaveSince = 0;
        state.curTgt = tgt;
        state.dwellStart = performance.now();
        if (tgt) tgt.classList.add('hm-target');
        setRing(0);
    }
    if (!tgt) {
        restDwell(x, y);
        return;
    }
    if (state.lockTgt === tgt) {
        setRing(100);
        return;
    }
    const elapsed = performance.now() - state.dwellStart;
    setRing(Math.min(100, elapsed / state.dwellMs * 100));
    if (elapsed >= state.dwellMs) {
        activate(tgt);
        state.lockTgt = tgt;
    }
}

// 클릭 대상 없는 자리에 머물면 읽기용 이벤트
function restDwell(x, y) {
    const now = performance.now();
    if (Math.hypot(x - state.restX, y - state.restY) > MAGNET_RADIUS) {
        state.restX = x;
        state.restY = y;
        state.restStart = now;
        state.restFired = false;
        return;
    }
    if (state.paused || state.restFired || now - state.restStart < state.dwellMs) return;
    state.restFired = true;
    const el = document.elementFromPoint(x, y);
    if (el) window.dispatchEvent(new CustomEvent('hm:dwell', { detail: el }));
}

function updateCursor(x, y) {
    let cx = x, cy = y;
    if (state.curTgt) {
        const r = state.curTgt.getBoundingClientRect();
        cx = r.left + r.width / 2;
        cy = r.top + r.height / 2;
    }
    cursorEl.style.left = cx + 'px';
    cursorEl.style.top = cy + 'px';
}

function getScrollTarget() {
    const modal = document.querySelector('.modal.show');
    if (modal) return modal.querySelector('.modal-body') || modal;
    return document.scrollingElement || document.documentElement;
}

function updateScrollBands(x, y, hasTarget) {
    let dir = 0;
    if (!hasTarget && !state.paused) {
        if (y <= SCROLL_BAND) dir = -1;
        else if (y >= innerHeight - SCROLL_BAND) dir = 1;
    }
    bandTop.classList.toggle('hm-band-active', dir === -1);
    bandBottom.classList.toggle('hm-band-active', dir === 1);
    if (dir !== 0) getScrollTarget().scrollTop += dir * SCROLL_SPEED;
}

function startCalibration() {
    state.calibrating = true;
    state.calibSamples = [];
    state.calibStart = performance.now();
    calibEl.hidden = false;
    showMsg('');
    announce('중립 자세를 저장합니다. 화면 가운데를 보고 편하게 앉으세요.');
}

function finishCalibration() {
    const n = state.calibSamples.length;
    state.calibrating = false;
    calibEl.hidden = true;
    if (n === 0) return;
    const nx = state.calibSamples.reduce((s, p) => s + p.x, 0) / n;
    const ny = state.calibSamples.reduce((s, p) => s + p.y, 0) / n;
    state.neutral = { x: nx, y: ny };
    localStorage.setItem(LS_NEUTRAL, JSON.stringify(state.neutral));
    announce('가운데 맞추기 완료');
}

function noseToScreen(nx, ny) {
    const dxNorm = state.neutral.x - nx;
    const dyNorm = ny - state.neutral.y;
    const x = innerWidth / 2 + (dxNorm / SENS) * (innerWidth / 2);
    const y = innerHeight / 2 + (dyNorm / SENS) * (innerHeight / 2);
    return {
        x: Math.min(innerWidth, Math.max(0, x)),
        y: Math.min(innerHeight, Math.max(0, y)),
    };
}

function stepCamera(ts) {
    if (video.readyState < 2) return null;
    const res = faceLandmarker.detectForVideo(video, ts);
    const found = res && res.faceLandmarks && res.faceLandmarks.length > 0;

    if (!found) {
        if (!state.noFaceSince) state.noFaceSince = ts;
        if (ts - state.noFaceSince > NO_FACE_MS && !state.faceLost) {
            state.faceLost = true;
            showMsg('얼굴이 보이지 않습니다. 카메라 앞에 앉아주세요.');
            announce('얼굴이 보이지 않습니다.');
        }
        return null;
    }
    state.noFaceSince = 0;
    if (state.faceLost) {
        state.faceLost = false;
        showMsg('');
    }

    const nose = res.faceLandmarks[0][NOSE_IDX];

    if (state.calibrating) {
        state.calibSamples.push({ x: nose.x, y: nose.y });
        if (ts - state.calibStart >= NEUTRAL_MS) finishCalibration();
        return null;
    }

    if (!state.neutral) return null;
    return noseToScreen(nose.x, nose.y);
}

function tick(ts) {
    const pt = state.debug ? { x: state.mouseX, y: state.mouseY } : stepCamera(ts);
    if (pt) {
        const now = performance.now();
        const fx = filtX.filter(pt.x, now);
        const fy = filtY.filter(pt.y, now);
        const cx = Math.min(innerWidth, Math.max(0, fx));
        const cy = Math.min(innerHeight, Math.max(0, fy));
        doMagnetDwell(cx, cy);
        updateCursor(cx, cy);
        updateScrollBands(cx, cy, !!state.curTgt);
        cursorEl.classList.add('hm-visible');
    }
    requestAnimationFrame(tick);
}

async function startCameraMode() {
    let stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
    } catch (e) {
        showMsg('카메라 권한이 거부되어 헤드마우스를 사용할 수 없습니다. 접근성 설정에서 머리로 조작을 꺼주세요.');
        announce('카메라 권한이 거부되었습니다.');
        return;
    }
    video.srcObject = stream;
    await video.play();

    showMsg('얼굴 인식 준비 중...');
    try {
        const vision = await import(VISION_ESM_URL);
        const fileset = await vision.FilesetResolver.forVisionTasks(VISION_WASM_BASE);
        const opts = function(delegate) {
            return { baseOptions: { modelAssetPath: MODEL_URL, delegate: delegate }, runningMode: 'VIDEO', numFaces: 1 };
        };
        try {
            faceLandmarker = await vision.FaceLandmarker.createFromOptions(fileset, opts('GPU'));
        } catch (e) {
            faceLandmarker = await vision.FaceLandmarker.createFromOptions(fileset, opts('CPU'));
        }
    } catch (e) {
        showMsg('얼굴 인식을 불러오지 못했습니다. 인터넷 연결을 확인하고 새로고침해주세요.');
        announce('얼굴 인식을 불러오지 못했습니다.');
        return;
    }
    showMsg('');

    const saved = localStorage.getItem(LS_NEUTRAL);
    if (saved) {
        try { state.neutral = JSON.parse(saved); } catch (e) { state.neutral = null; }
    }
    if (!state.neutral) startCalibration();

    announce('헤드마우스가 켜졌습니다.');
    requestAnimationFrame(tick);
}

function startDebugMode() {
    document.addEventListener('mousemove', function(e) {
        state.mouseX = e.clientX;
        state.mouseY = e.clientY;
    });
    requestAnimationFrame(tick);
}

function bindEvents() {
    document.addEventListener('keydown', function(e) {
        if (e.key.toLowerCase() !== 'c') return;
        const tag = document.activeElement.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || document.activeElement.isContentEditable) return;
        if (state.debug) return;
        e.preventDefault();
        startCalibration();
    });
    // 스크롤 밴드가 매 프레임 스크롤시킴. 프레임당 한 번만
    let queued = false;
    const queueRefresh = function() {
        if (queued) return;
        queued = true;
        requestAnimationFrame(function() {
            queued = false;
            refreshCands();
        });
    };
    window.addEventListener('resize', queueRefresh);
    window.addEventListener('scroll', queueRefresh, true);
    document.addEventListener('shown.bs.modal', refreshCands);
    document.addEventListener('hidden.bs.modal', refreshCands);
}

function init() {
    filtX = new OneEuro(ONEEURO_MIN_CUTOFF, ONEEURO_BETA, ONEEURO_DCUTOFF);
    filtY = new OneEuro(ONEEURO_MIN_CUTOFF, ONEEURO_BETA, ONEEURO_DCUTOFF);
    buildUI();
    refreshCands();
    setInterval(refreshCands, CAND_REFRESH_MS);
    bindEvents();
    if (state.debug) startDebugMode();
    else startCameraMode();
}

init();
