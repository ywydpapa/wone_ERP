(function() {
    var data = JSON.parse(document.getElementById('helpData').textContent);
    var main = document.getElementById('main');
    var LS_READ = 'help_read';
    var bar = null, pinned = null, seq = 0;
    var items = [];

    function store(k, v) {
        try {
            if (v === undefined) return localStorage.getItem(k);
            localStorage.setItem(k, v);
        } catch (e) { return null; }
    }

    // 버튼명의 단축키 표기, 기호 제외 기준으로 비교
    function norm(s) {
        return (s || '').replace(/\(.*?\)|\+/g, '').replace(/\s+/g, ' ').trim();
    }

    function visible(el) {
        return el.getClientRects().length > 0;
    }

    // 모달, 탭은 열릴 때 해당 영역만 재탐색
    function scan(root, fn) {
        data.fields.forEach(function(f) {
            // 표 입력 행은 name 끝 번호가 행마다 다르므로 앞부분 기준 매칭
            var rx = f.name.indexOf('{') > 0 ? new RegExp('^' + f.name.replace(/\{\w+\}/, '\\d+') + '$') : null;
            var sel = f.name.charAt(0) === '#' ? f.name
                : rx ? '[name^="' + f.name.split('{')[0] + '"]' : '[name="' + f.name + '"]';
            root.querySelectorAll(sel).forEach(function(el) {
                if (rx && !rx.test(el.name)) return;
                // 코드 찾기 입력은 name이 숨은 칸에 있으므로 묶음 기준
                if (el.type === 'hidden' && !el.closest('.lookup')) return;
                // 일자 입력은 원본 숨김이므로 분리 입력 묶음 기준. 체크박스는 라벨 포함
                var box = el.closest('.input-group, .dt-split, .form-check, .lookup') || el;
                fn(box, f.label + (f.required ? ' (필수)' : ''), f.desc, true, f.options);
            });
        });
        var btns = root.querySelectorAll('button, a.btn, input[type=submit]');
        data.buttons.forEach(function(b) {
            var names = norm(b.label).split(/\s*[\/,]\s*/);
            btns.forEach(function(el) {
                var keys = [norm(el.textContent || el.value), norm(el.getAttribute('aria-label')), norm(el.title)];
                if (keys.some(function(k) { return k && names.indexOf(k) >= 0; })) fn(el, b.label, b.desc, false);
            });
        });
    }

    function body(desc, opts) {
        var box = document.createElement('div');
        box.append(desc);
        if (!opts) return box;
        var ul = document.createElement('ul');
        ul.className = 'help-opts';
        opts.forEach(function(o) {
            var li = document.createElement('li');
            var b = document.createElement('b');
            b.textContent = o.label;
            li.append(b, ' ' + o.desc);
            ul.appendChild(li);
        });
        box.appendChild(ul);
        return box;
    }

    function add(el, title, desc, field, opts) {
        if (el.helpItem || !visible(el) || el.closest('.help-bar')) return;
        var d = body(desc, opts);
        d.id = 'helpDesc' + (++seq);
        d.className = 'help-desc';
        // 스크린리더용 설명 연결. 종료 시 원래 값 복원
        var focusEl = field ? (el.matches('input, select, textarea') ? el : el.querySelector('input:not([type=hidden]), select, textarea')) : el;
        var it = { el: el, focusEl: focusEl, title: title, desc: desc, field: field, d: d, prev: focusEl.getAttribute('aria-describedby') };
        focusEl.setAttribute('aria-describedby', ((it.prev || '') + ' ' + d.id).trim());
        // 항목 옆 삽입 시 화면 배치 깨짐. 설명은 안내줄에 보관
        bar.appendChild(d);
        el.classList.add('help-target');
        it.tip = new bootstrap.Popover(el, {
            title: title, content: body(desc, opts), html: true, trigger: 'manual', placement: 'auto', container: 'body', customClass: 'help-tip'
        });
        el.helpItem = it;
        items.push(it);
    }

    function show(it, pin) {
        if (pinned && pinned !== it) hide(pinned);
        if (pin) pinned = it;
        tipOn(it);
    }

    function hide(it) {
        if (pinned === it) pinned = null;
        tipOff(it);
    }

    // 전체 표시 시 화면이 산만하므로 설명 중인 항목만 표시
    // 부트스트랩 5.3.0은 표시 중 show 재호출 시 말풍선이 사라짐. 포커스와 클릭이 연달아 호출하므로 상태 확인
    function tipOn(it) {
        if (it.open) return;
        it.open = true;
        it.tip.show();
        it.el.classList.add('help-on');
    }

    function tipOff(it) {
        if (!it.open) return;
        it.open = false;
        it.tip.hide();
        it.el.classList.remove('help-on');
    }

    function read(it) {
        if (store(LS_READ) === '1' && window.Voice) window.Voice.speak(it.title + '. ' + it.desc, true);
    }

    function itemOf(node) {
        var el = node && node.closest && node.closest('.help-target');
        return el && el.helpItem;
    }

    function onOver(e) {
        var it = itemOf(e.target);
        if (it && !pinned) tipOn(it);
    }

    function onOut(e) {
        var it = itemOf(e.target);
        if (it && it !== pinned && !it.el.contains(e.relatedTarget)) tipOff(it);
    }

    function onFocus(e) {
        var it = itemOf(e.target);
        if (!it) return;
        show(it, false);
        read(it);
    }

    function onBlur(e) {
        var it = itemOf(e.target);
        if (it && it !== pinned && !it.el.contains(e.relatedTarget)) tipOff(it);
    }

    // 저장, 상신 등 실제 동작 차단. 모달, 탭 여는 버튼은 내부 항목 확인용으로 허용
    // 헤드마우스, 손 떨림 사용자 기준 클릭 시 고정. 다른 곳 클릭 시 해제
    function onClick(e) {
        if (e.target.closest('.help-bar, .help-tip')) return;
        var it = itemOf(e.target);
        if (!it) {
            if (pinned) hide(pinned);
            return;
        }
        var toggle = it.el.matches('[data-bs-toggle]');
        if (!toggle && !it.field) {
            e.preventDefault();
            e.stopPropagation();
        }
        if (pinned === it && !it.field) hide(it);
        else {
            show(it, true);
            read(it);
        }
    }

    // 입력칸 Enter 전송 차단
    function onSubmit(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    function onShown(e) {
        if (e.target.matches('.modal, .tab-pane, .collapse, .offcanvas:not(#helpPanel)')) scan(e.target, add);
        else if (e.target.matches('[data-bs-toggle=tab], [data-bs-toggle=pill]')) scan(main, add);
    }

    function render() {
        var r = bar.querySelector('[data-act=read]');
        var on = store(LS_READ) === '1';
        r.setAttribute('aria-pressed', on ? 'true' : 'false');
        r.classList.toggle('active', on);
        if (pinned) hide(pinned);
    }

    function on() {
        // 첫 사용 시 음성 사용 중이면 설명 읽기 기본 켬
        if (store(LS_READ) === null && sessionStorage.getItem('voice_on') === '1') store(LS_READ, '1');
        document.body.classList.add('help-mode');
        bar = document.createElement('div');
        bar.className = 'help-bar alert alert-secondary py-2';
        bar.innerHTML = '<span class="help-msg" role="status">버튼 설명이 켜졌습니다. 궁금한 버튼이나 입력칸을 누르면 설명이 나오고, 다른 곳을 누르면 닫힙니다.</span>'
            + '<button type="button" class="btn btn-sm btn-outline-secondary" data-act="read">소리로 듣기</button>'
            + '<button type="button" class="btn btn-sm btn-outline-secondary" data-act="off">끄기 (Esc)</button>';
        bar.addEventListener('click', function(e) {
            var act = e.target.closest('[data-act]');
            if (!act) return;
            if (act.dataset.act === 'off') return off();
            store(LS_READ, store(LS_READ) === '1' ? '0' : '1');
            render();
        });
        // 키보드 사용자 기준 Tab 다음 순서가 작업 화면이 되도록 main 맨 앞에 배치
        main.prepend(bar);
        scan(main, add);
        render();
        main.addEventListener('mouseover', onOver);
        main.addEventListener('mouseout', onOut);
        document.addEventListener('focusin', onFocus);
        document.addEventListener('focusout', onBlur);
        document.addEventListener('click', onClick, true);
        document.addEventListener('submit', onSubmit, true);
        document.addEventListener('shown.bs.modal', onShown);
        document.addEventListener('shown.bs.tab', onShown);
        document.addEventListener('shown.bs.collapse', onShown);
        // 패널 닫힘 처리 후 포커스 이동
        setTimeout(function() { if (bar) bar.querySelector('button').focus(); }, 400);
    }

    function off() {
        items.forEach(function(it) {
            it.tip.dispose();
            it.d.remove();
            it.el.classList.remove('help-target', 'help-on');
            if (it.prev) it.focusEl.setAttribute('aria-describedby', it.prev);
            else it.focusEl.removeAttribute('aria-describedby');
            delete it.el.helpItem;
        });
        items = [];
        pinned = null;
        main.removeEventListener('mouseover', onOver);
        main.removeEventListener('mouseout', onOut);
        document.removeEventListener('focusin', onFocus);
        document.removeEventListener('focusout', onBlur);
        document.removeEventListener('click', onClick, true);
        document.removeEventListener('submit', onSubmit, true);
        document.removeEventListener('shown.bs.modal', onShown);
        document.removeEventListener('shown.bs.tab', onShown);
        document.removeEventListener('shown.bs.collapse', onShown);
        document.body.classList.remove('help-mode');
        bar.remove();
        bar = null;
        if (window.Voice) window.Voice.stop();
    }

    function toggle() {
        if (bar) off();
        else on();
    }

    /* 사용법 안내 */
    var tour = null;

    function tourStart() {
        if (tour) return;
        if (bar) off();
        var list = [];
        scan(main, function(el, title, desc, field, opts) {
            if (!visible(el) || list.some(function(t) { return t.el === el; })) return;
            list.push({ el: el, title: title, desc: desc, opts: opts });
        });
        if (!list.length) {
            bootstrap.Offcanvas.getOrCreateInstance(document.getElementById('helpPanel')).show();
            return;
        }
        list.sort(function(a, b) {
            return a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
        });
        tour = { list: list, idx: 0, tip: null };
        document.body.classList.add('tour-on');
        document.addEventListener('click', tourClick, true);
        document.addEventListener('keydown', tourKey, true);
        tourShow();
    }

    function tourShow() {
        var t = tour.list[tour.idx], n = tour.list.length, last = tour.idx === n - 1;
        t.el.classList.add('tour-cur');
        t.el.scrollIntoView({ block: 'center' });
        var box = body(t.desc, t.opts);
        var nav = document.createElement('div');
        nav.className = 'tour-nav';
        nav.innerHTML = '<span class="tour-cnt">' + (tour.idx + 1) + ' / ' + n + '</span>'
            + '<button type="button" class="btn btn-sm btn-outline-secondary" data-act="end">그만 보기</button>'
            + (tour.idx ? '<button type="button" class="btn btn-sm btn-outline-primary" data-act="prev">이전</button>' : '')
            + '<button type="button" class="btn btn-sm btn-primary" data-act="next">' + (last ? '마침' : '다음') + '</button>';
        box.appendChild(nav);
        tour.tip = new bootstrap.Popover(t.el, {
            title: t.title, content: box, html: true, trigger: 'manual', placement: 'auto',
            container: 'body', customClass: 'help-tip tour-tip'
        });
        t.el.addEventListener('shown.bs.popover', function() {
            var tip = document.querySelector('.tour-tip');
            tip.setAttribute('role', 'dialog');
            tip.setAttribute('aria-label', t.title);
            tip.querySelector('[data-act=next]').focus();
        }, { once: true });
        tour.tip.show();
        if (store(LS_READ) === '1' && window.Voice) window.Voice.speak(t.title + '. ' + t.desc, true);
    }

    function tourClear() {
        tour.tip.dispose();
        tour.list[tour.idx].el.classList.remove('tour-cur');
    }

    function tourGo(step) {
        var next = tour.idx + step;
        if (next < 0) return;
        if (next >= tour.list.length) return tourEnd();
        tourClear();
        tour.idx = next;
        tourShow();
    }

    function tourEnd() {
        var el = tour.list[tour.idx].el;
        tourClear();
        tour = null;
        document.body.classList.remove('tour-on');
        document.removeEventListener('click', tourClick, true);
        document.removeEventListener('keydown', tourKey, true);
        if (window.Voice) window.Voice.stop();
        el.focus();
    }

    // 사용법 안내 중 화면 동작 차단. 안내창 버튼만 허용
    function tourClick(e) {
        var act = e.target.closest('.tour-tip [data-act]');
        e.preventDefault();
        e.stopPropagation();
        if (!act) return;
        if (act.dataset.act === 'end') tourEnd();
        else tourGo(act.dataset.act === 'next' ? 1 : -1);
    }

    function tourKey(e) {
        if (e.key === 'Escape') tourEnd();
        else if (e.key === 'ArrowRight') tourGo(1);
        else if (e.key === 'ArrowLeft') tourGo(-1);
        else return;
        e.preventDefault();
        e.stopPropagation();
    }

    window.HelpMode = { toggle: toggle, tour: tourStart };

    document.getElementById('helpModeBtn').addEventListener('click', function() {
        if (!bar) on();
    });
    document.querySelectorAll('[data-help-mode]').forEach(function(el) {
        el.addEventListener('click', toggle);
    });
    document.querySelectorAll('[data-help-tour]').forEach(function(el) {
        el.addEventListener('click', tourStart);
    });

    // Esc는 고정된 설명 먼저 닫고, 없으면 버튼 설명 종료
    window.addEventListener('keydown', function(e) {
        if (!bar || e.key !== 'Escape' || document.querySelector('.modal.show')) return;
        e.stopPropagation();
        if (pinned) hide(pinned);
        else off();
    }, true);
})();
