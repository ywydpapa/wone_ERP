(function() {
    var POS_ORDER = ['br', 'bl', 'tl', 'tr'];
    var LS_POS = 'a11y_fab_pos';
    var LS_OPEN = 'a11y_fab_open';
    var NAMES = { high_contrast: '고대비', large_target: '큰 조작 영역', easy_mode: '쉬운 모드', head_mouse: '머리로 조작', voice_amount: '금액 음성', dwell_read: '응시 읽기', click_read: '클릭 읽기', sr_mode: '스크린리더 모드' };
    var OPT_LABELS = {
        font_size: { 100: '보통 글자 크기', 150: '글자 크기 150%', 200: '글자 크기 200%' },
        tts_voice: { F1: '여성 보이스', M1: '남성 보이스' },
        tts_speed: { slow: '느리게', normal: '보통 속도', fast: '빠르게' }
    };

    var state = JSON.parse(document.getElementById('a11yInit').textContent);

    function announce(msg) {
        document.getElementById('srLive').textContent = msg;
    }

    function applyClasses() {
        document.body.classList.toggle('theme-high-contrast', state.high_contrast);
        document.documentElement.classList.remove('font-lg', 'font-xl');
        if (state.font_size === 150) document.documentElement.classList.add('font-lg');
        if (state.font_size === 200) document.documentElement.classList.add('font-xl');
        document.body.classList.toggle('large-target', state.large_target);
        document.body.classList.toggle('easy-mode', state.easy_mode);
    }

    function syncControls() {
        document.getElementById('a11yHighContrast').checked = state.high_contrast;
        document.getElementById('a11yFontSize').value = String(state.font_size);
        document.getElementById('a11yLargeTarget').checked = state.large_target;
        document.getElementById('a11yEasyMode').checked = state.easy_mode;
        document.getElementById('a11yHeadMouse').checked = state.head_mouse;

        document.getElementById('a11yWHighContrast').setAttribute('aria-pressed', String(state.high_contrast));
        document.getElementById('a11yWLargeTarget').setAttribute('aria-pressed', String(state.large_target));
        document.getElementById('a11yWEasyMode').setAttribute('aria-pressed', String(state.easy_mode));
        document.getElementById('a11yWHeadMouse').setAttribute('aria-pressed', String(state.head_mouse));
        document.getElementById('a11yWVoiceAmount').setAttribute('aria-pressed', String(state.voice_amount));
        document.getElementById('a11yWDwellRead').setAttribute('aria-pressed', String(state.dwell_read));
        document.getElementById('a11yWClickRead').setAttribute('aria-pressed', String(state.click_read));
        document.getElementById('a11yWSrMode').setAttribute('aria-pressed', String(!!state.sr_mode));

        document.querySelectorAll('.a11y-size-btn').forEach(function(btn) {
            btn.setAttribute('aria-pressed', String(Number(btn.dataset.size) === state.font_size));
        });
        document.getElementById('a11yTtsVoice').value = state.tts_voice || 'F1';
        document.getElementById('a11yTtsSpeed').value = state.tts_speed || 'normal';
    }

    function save(key, val) {
        state[key] = val;
        applyClasses();
        syncControls();
        var label = OPT_LABELS[key] ? OPT_LABELS[key][val] : NAMES[key] + (val ? ' 켜짐' : ' 꺼짐');
        announce(label);
        document.dispatchEvent(new CustomEvent('a11y:change', { detail: { key: key, val: val } }));
        var req = fetch('/api/accessibility', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content
            },
            body: JSON.stringify(state)
        });
        if (key === 'head_mouse') req.then(function() { location.reload(); });
    }

    // ax, ay 없으면 CSS 기본값
    function applyPos(widget, p) {
        widget.classList.remove('a11y-pos-br', 'a11y-pos-bl', 'a11y-pos-tl', 'a11y-pos-tr');
        widget.classList.add('a11y-pos-' + p.pos);
        if (p.ax != null) {
            widget.style.setProperty('--ax', p.ax + 'px');
            widget.style.setProperty('--ay', p.ay + 'px');
        } else {
            widget.style.removeProperty('--ax');
            widget.style.removeProperty('--ay');
        }
    }

    function posFromPoint(cx, cy, size) {
        var right = cx > innerWidth / 2;
        var bottom = cy > innerHeight / 2;
        var half = size / 2;
        var ax = right ? innerWidth - cx - half : cx - half;
        var ay = bottom ? innerHeight - cy - half : cy - half;
        return {
            pos: (bottom ? 'b' : 't') + (right ? 'r' : 'l'),
            ax: Math.round(Math.max(8, Math.min(ax, innerWidth - size - 8))),
            ay: Math.round(Math.max(8, Math.min(ay, innerHeight - size - 8)))
        };
    }

    function initWidget() {
        var widget = document.getElementById('a11yWidget');
        var fab = document.getElementById('a11yFab');
        var panel = document.getElementById('a11yPanel');
        var pos = { pos: 'br' };
        try {
            var saved = JSON.parse(localStorage.getItem(LS_POS));
            if (saved && saved.pos) pos = saved;
        } catch (e) {}
        applyPos(widget, pos);

        function setOpen(open) {
            panel.hidden = !open;
            fab.setAttribute('aria-expanded', String(open));
            localStorage.setItem(LS_OPEN, open ? '1' : '0');
        }
        function collapse(focusFab) {
            setOpen(false);
            if (focusFab) fab.focus();
        }
        setOpen(localStorage.getItem(LS_OPEN) === '1');

        // 드래그 끝나고 click 한 번 더 들어옴
        var drag = null;
        var dragged = false;
        fab.addEventListener('pointerdown', function(e) {
            if (e.button !== 0) return;
            var r = fab.getBoundingClientRect();
            drag = { sx: e.clientX, sy: e.clientY, ox: e.clientX - (r.left + r.width / 2), oy: e.clientY - (r.top + r.height / 2), size: r.width, moving: false };
            fab.setPointerCapture(e.pointerId);
        });
        fab.addEventListener('pointermove', function(e) {
            if (!drag) return;
            if (!drag.moving && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < 5) return;
            drag.moving = true;
            widget.classList.add('a11y-dragging');
            pos = posFromPoint(e.clientX - drag.ox, e.clientY - drag.oy, drag.size);
            applyPos(widget, pos);
        });
        fab.addEventListener('pointerup', function() {
            if (!drag) return;
            dragged = drag.moving;
            if (dragged) {
                widget.classList.remove('a11y-dragging');
                localStorage.setItem(LS_POS, JSON.stringify(pos));
            }
            drag = null;
        });
        fab.addEventListener('pointercancel', function() {
            widget.classList.remove('a11y-dragging');
            drag = null;
        });
        fab.addEventListener('click', function() {
            if (dragged) {
                dragged = false;
                return;
            }
            setOpen(panel.hidden);
        });
        panel.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') collapse(true);
        });

        document.getElementById('a11yMoveBtn').addEventListener('click', function() {
            pos = { pos: POS_ORDER[(POS_ORDER.indexOf(pos.pos) + 1) % POS_ORDER.length] };
            applyPos(widget, pos);
            localStorage.setItem(LS_POS, JSON.stringify(pos));
            announce('위젯 위치를 옮겼습니다.');
        });
        document.getElementById('a11yCollapseBtn').addEventListener('click', function() {
            collapse(true);
        });

        var btns = { a11yWHighContrast: 'high_contrast', a11yWLargeTarget: 'large_target', a11yWEasyMode: 'easy_mode', a11yWHeadMouse: 'head_mouse', a11yWVoiceAmount: 'voice_amount', a11yWDwellRead: 'dwell_read', a11yWClickRead: 'click_read', a11yWSrMode: 'sr_mode' };
        Object.keys(btns).forEach(function(id) {
            var key = btns[id];
            document.getElementById(id).addEventListener('click', function() {
                save(key, !state[key]);
            });
        });
        document.querySelectorAll('.a11y-size-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                save('font_size', Number(btn.dataset.size));
            });
        });
        document.getElementById('a11yTtsVoice').addEventListener('change', function(e) {
            save('tts_voice', e.target.value);
        });
        document.getElementById('a11yTtsSpeed').addEventListener('change', function(e) {
            save('tts_speed', e.target.value);
        });
    }

    function bindTopbar() {
        var boxes = { a11yHighContrast: 'high_contrast', a11yLargeTarget: 'large_target', a11yEasyMode: 'easy_mode', a11yHeadMouse: 'head_mouse' };
        Object.keys(boxes).forEach(function(id) {
            var box = document.getElementById(id);
            box.addEventListener('change', function() {
                save(boxes[id], box.checked);
            });
        });
        var fs = document.getElementById('a11yFontSize');
        fs.addEventListener('change', function() {
            save('font_size', parseInt(fs.value));
        });
    }

    initWidget();
    bindTopbar();
})();
