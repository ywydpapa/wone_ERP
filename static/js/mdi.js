(function() {
    var MAX = 12;
    var root = document.documentElement;
    var framed = window.top !== window;
    var host = framed ? window.parent.mdi : null;

    function popup(url, name) {
        var w = Math.min(1180, screen.availWidth - 40), h = Math.min(820, screen.availHeight - 60);
        var left = window.screenX + Math.max(0, (window.outerWidth - w) / 2);
        var top = window.screenY + Math.max(0, (window.outerHeight - h) / 2);
        var win = window.open(url, 'erp-pop-' + name, 'popup,width=' + w + ',height=' + h + ',left=' + left + ',top=' + top);
        if (win) win.focus();
        return win;
    }

    function modified(e) {
        return e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button !== 0;
    }

    function enabled() {
        var def = document.body.dataset.mdi;
        if (def === 'never') return false;
        var v = null;
        try { v = localStorage.getItem('erp_mdi'); } catch (e) {}
        return (v || (def === 'on' ? '1' : '0')) === '1';
    }

    function setEnabled(on) {
        try { localStorage.setItem('erp_mdi', on ? '1' : '0'); } catch (e) {}
    }

    // 팝업은 탭 안에서 열렸을 수 있음. opener의 최상위 창 기준
    function target() {
        if (host) return host;
        try {
            if (window.opener && window.opener.top.mdi) return window.opener.top.mdi;
        } catch (e) {}
        return null;
    }

    document.addEventListener('click', function(e) {
        var a = e.target.closest('a[data-pop], a[data-tab]');
        if (!a || modified(e)) return;
        if (a.hasAttribute('data-pop')) {
            if (document.body.dataset.mdi === 'never') return;
            e.preventDefault();
            popup(a.getAttribute('href'), a.dataset.pop || 'view');
            return;
        }
        var t = target();
        if (!t) return;
        e.preventDefault();
        t.open(a.getAttribute('href'), a.dataset.tab || a.textContent.trim());
        if (t !== host) t.focus();
    });

    // 새 창 사전 고지(KWCAG 사용자 요구에 따른 실행). 쉬운 모드는 같은 창 이동 방식. 제외
    if (document.body.dataset.mdi !== 'never') {
        document.querySelectorAll('a[data-pop]').forEach(function(a) {
            a.title = '새 창으로 열림';
            a.insertAdjacentHTML('beforeend', '<span class="visually-hidden"> (새 창)</span>');
        });
    }

    // 다크모드 전환은 상위 창에서만 발생. storage 이벤트로 동기화
    window.addEventListener('storage', function(e) {
        if (e.key === 'theme_dark') document.body.classList.toggle('theme-dark', e.newValue === '1');
    });

    if (host) {
        document.addEventListener('keydown', function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                host.find();
            }
        });
        return;
    }

    /* 메뉴 검색. 작업창에서는 탭으로 열림 */
    var findEl = document.getElementById('menuFind');
    var listEl = document.getElementById('menuFindList');
    var menus = [], hits = [], pos = 0, openTab = null;
    var back = function() { document.getElementById('main').focus(); };

    document.querySelectorAll('.sidebar-nav a.sidebar-link[href^="/"]:not(.fav-link)').forEach(function(a) {
        var href = a.getAttribute('href');
        if (href === '/' || href === '/workspace') return;
        var sub = a.closest('.sidebar-subgroup-body');
        var dom = a.closest('.sidebar-domain-body');
        var path = [dom, sub].filter(Boolean).map(function(el) {
            return el.previousElementSibling.textContent.trim();
        }).join(' > ');
        menus.push({ href: href, name: a.textContent.trim(), path: path, mdi: !!a.closest('[data-mdi]') });
    });

    function renderFind() {
        var q = findEl.value.trim().toLowerCase().replace(/\s+/g, '');
        hits = !q ? [] : menus.filter(function(m) {
            return (m.name + m.path).toLowerCase().replace(/\s+/g, '').indexOf(q) >= 0;
        }).slice(0, 12);
        pos = 0;
        if (!q) { listEl.hidden = true; return; }
        listEl.innerHTML = hits.length ? hits.map(function(m, i) {
            return '<button type="button" class="menu-find-item' + (i === 0 ? ' on' : '') + '" data-idx="' + i + '"><span></span><small></small></button>';
        }).join('') : '<div class="menu-find-none">일치하는 메뉴가 없습니다</div>';
        listEl.querySelectorAll('.menu-find-item').forEach(function(btn, i) {
            btn.querySelector('span').textContent = hits[i].name;
            btn.querySelector('small').textContent = hits[i].path;
        });
        listEl.hidden = false;
    }

    function pickFind(i) {
        var m = hits[i];
        if (!m) return;
        findEl.value = '';
        listEl.hidden = true;
        if (openTab) {
            var t = openTab(m.href, m.name);
            if (t) t.frame.focus();
        } else if (m.mdi && enabled()) {
            location.href = '/workspace?open=' + encodeURIComponent(m.href);
        } else {
            location.href = m.href;
        }
    }

    function find() {
        if (document.body.classList.contains('sidebar-collapsed')) document.querySelector('.sidebar-toggle').click();
        findEl.focus();
        findEl.select();
    }

    if (findEl) {
        findEl.addEventListener('input', renderFind);
        findEl.addEventListener('keydown', function(e) {
            if (e.isComposing) return;
            var items = listEl.querySelectorAll('.menu-find-item');
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                if (!items.length) return;
                e.preventDefault();
                pos = (pos + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
                items.forEach(function(b, i) { b.classList.toggle('on', i === pos); });
            } else if (e.key === 'Enter') {
                e.preventDefault();
                pickFind(pos);
            } else if (e.key === 'Escape') {
                findEl.value = '';
                listEl.hidden = true;
                back();
            }
        });
        listEl.addEventListener('click', function(e) {
            var btn = e.target.closest('.menu-find-item');
            if (btn) pickFind(+btn.dataset.idx);
        });
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.menu-find')) listEl.hidden = true;
        });
        document.addEventListener('keydown', function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); find(); }
        });
    }

    var ws = document.getElementById('mdi');
    if (!ws) {
        // 일반 화면에서 회계 메뉴 진입 시 탭 작업창으로 전환
        document.addEventListener('click', function(e) {
            var a = e.target.closest('[data-mdi] a.sidebar-link');
            if (!a || modified(e) || !enabled()) return;
            e.preventDefault();
            location.href = '/workspace?open=' + encodeURIComponent(a.getAttribute('href'));
        });
        return;
    }

    /* 탭 작업창 */
    var params = new URLSearchParams(location.search);
    var first = params.get('open');
    // 쉬운 모드/머리로 조작 사용자는 보던 탭 화면을 일반 페이지로 전환
    if (document.body.dataset.mdi === 'never') {
        location.replace(safe(first) ? first : lastUrl());
        return;
    }
    setEnabled(true);

    var tabsEl = document.getElementById('mdiTabs');
    var panes = document.getElementById('mdiPanes');
    var empty = document.getElementById('mdiEmpty');
    var note = document.getElementById('mdiNote');
    var menu = document.getElementById('mdiMenu');
    var tabs = [], cur = null, seq = 0, noteTimer = null;

    function lastUrl() {
        try {
            var d = JSON.parse(sessionStorage.getItem('mdi_tabs') || 'null');
            var t = d && d.tabs[d.active];
            if (t && safe(t.url)) return t.url;
        } catch (e) {}
        return '/';
    }

    function safe(url) {
        return typeof url === 'string' && url.charAt(0) === '/' && url.charAt(1) !== '/' && url.charAt(1) !== '\\';
    }

    function save() {
        var data = {
            tabs: tabs.map(function(t) { return { origin: t.origin, url: t.url, title: t.title }; }),
            active: tabs.indexOf(cur)
        };
        try { sessionStorage.setItem('mdi_tabs', JSON.stringify(data)); } catch (e) {}
    }

    var live = document.getElementById('srLive');
    function say(msg) {
        live.textContent = '';
        setTimeout(function() { live.textContent = msg; }, 50);
    }

    function flash(msg) {
        note.textContent = msg;
        note.hidden = false;
        clearTimeout(noteTimer);
        noteTimer = setTimeout(function() { note.hidden = true; }, 3000);
    }

    // 복원 탭은 처음 선택될 때 로드
    function create(origin, url, title, lazy) {
        var t = { id: ++seq, origin: origin, url: url, title: title || '불러오는 중', lazy: !!lazy };
        t.el = document.createElement('div');
        t.el.className = 'mdi-tab' + (lazy ? '' : ' loading');
        t.el.setAttribute('role', 'tab');
        t.el.id = 'mdiTab' + t.id;
        t.el.setAttribute('aria-controls', 'mdiPane' + t.id);
        t.el.tabIndex = -1;
        t.el.innerHTML = '<span class="mdi-tab-title"></span><button type="button" class="mdi-tab-x" tabindex="-1" aria-label="탭 닫기"><i class="fas fa-times" aria-hidden="true"></i></button>';
        t.el.querySelector('.mdi-tab-title').textContent = t.title;
        t.el.title = t.title;
        t.el._tab = t;
        tabsEl.appendChild(t.el);

        t.frame = document.createElement('iframe');
        t.frame.className = 'mdi-pane';
        t.frame.id = 'mdiPane' + t.id;
        t.frame.title = t.title;
        t.frame.addEventListener('load', function() { loaded(t); });
        if (!lazy) t.frame.src = url;
        panes.appendChild(t.frame);
        tabs.push(t);
        empty.hidden = true;
        return t;
    }

    function loaded(t) {
        if (t.lazy) return;
        t.el.classList.remove('loading');
        var doc;
        try { doc = t.frame.contentDocument; } catch (e) { return; }
        if (!doc || !doc.body) return;
        t.url = t.frame.contentWindow.location.pathname + t.frame.contentWindow.location.search;
        var h1 = doc.querySelector('.page-toolbar h1');
        var title = (h1 && h1.textContent.trim()) || (doc.title !== 'WONE ERP' && doc.title) || t.title;
        t.title = title;
        t.el.querySelector('.mdi-tab-title').textContent = title;
        t.el.title = title;
        t.frame.title = title;
        if (t === cur) {
            document.title = title + ' - WONE ERP';
            mark();
        }
        save();
    }

    function mark() {
        var path = cur ? cur.origin.split('?')[0] : '';
        document.querySelectorAll('.sidebar a.sidebar-link').forEach(function(a) {
            a.classList.toggle('active', !!path && a.getAttribute('href') === path);
        });
    }

    function activate(t) {
        if (!t) return;
        cur = t;
        if (t.lazy) {
            t.lazy = false;
            t.el.classList.add('loading');
            t.frame.src = t.url;
        }
        tabs.forEach(function(x) {
            var on = x === t;
            x.el.classList.toggle('on', on);
            x.el.setAttribute('aria-selected', on ? 'true' : 'false');
            x.el.tabIndex = on ? 0 : -1;
            x.frame.classList.toggle('on', on);
        });
        t.el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        say(t.title + ' 탭');
        document.title = t.title + ' - WONE ERP';
        mark();
        save();
    }

    function open(url, title, fresh) {
        if (!safe(url)) return;
        if (!fresh) {
            var hit = tabs.find(function(t) { return t.origin === url; });
            if (hit) { activate(hit); return hit; }
        }
        if (!title) {
            var m = menus.find(function(x) { return x.href === url; });
            title = m && m.name;
        }
        if (tabs.length >= MAX) {
            flash('탭은 ' + MAX + '개까지 열 수 있습니다. 쓰지 않는 탭을 닫아 주세요.');
            return null;
        }
        var t = create(url, url, title);
        activate(t);
        return t;
    }

    function dirty(t) {
        try {
            var fk = t.frame.contentWindow.formKit;
            return !!(fk && fk.isDirty());
        } catch (e) {
            return false;
        }
    }

    function close(t, force) {
        if (!force && dirty(t) && !confirm('[' + t.title + '] 저장하지 않은 입력 내용이 있습니다. 탭을 닫을까요?')) return false;
        var idx = tabs.indexOf(t);
        tabs.splice(idx, 1);
        say(t.title + ' 탭 닫힘');
        t.el.remove();
        t.frame.remove();
        if (cur === t) {
            cur = null;
            activate(tabs[idx] || tabs[idx - 1]);
        }
        if (!tabs.length) {
            empty.hidden = false;
            document.title = '탭 작업창 - WONE ERP';
            mark();
        }
        save();
        return true;
    }

    function closeMany(list) {
        var bad = list.filter(dirty);
        if (bad.length && !confirm('저장하지 않은 탭이 ' + bad.length + '개 있습니다. 모두 닫을까요?')) return;
        list.forEach(function(t) { close(t, true); });
    }

    function detach(t) {
        if (dirty(t) && !confirm('[' + t.title + '] 새 창으로 옮기면 입력 중인 내용은 사라집니다. 계속할까요?')) return;
        popup(t.url, 'tab' + t.id);
        close(t, true);
    }

    /* 탭 바 */
    tabsEl.addEventListener('click', function(e) {
        var el = e.target.closest('.mdi-tab');
        if (!el) return;
        if (e.target.closest('.mdi-tab-x')) close(el._tab);
        else activate(el._tab);
    });
    tabsEl.addEventListener('auxclick', function(e) {
        var el = e.target.closest('.mdi-tab');
        if (el && e.button === 1) { e.preventDefault(); close(el._tab); }
    });
    tabsEl.addEventListener('keydown', function(e) {
        var el = e.target.closest('.mdi-tab');
        if (!el) return;
        var i = tabs.indexOf(el._tab), next = null;
        if (e.key === 'ArrowRight') next = tabs[i + 1];
        else if (e.key === 'ArrowLeft') next = tabs[i - 1];
        else if (e.key === 'Delete') { close(el._tab); if (cur) cur.el.focus(); return; }
        else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(el._tab); return; }
        if (next) { e.preventDefault(); activate(next); next.el.focus(); }
    });

    // 탭 우클릭 메뉴
    var menuTab = null;
    tabsEl.addEventListener('contextmenu', function(e) {
        var el = e.target.closest('.mdi-tab');
        if (!el) return;
        e.preventDefault();
        menuTab = el._tab;
        menu.style.left = Math.min(e.clientX, window.innerWidth - 200) + 'px';
        menu.style.top = e.clientY + 'px';
        menu.classList.add('show');
        menu.querySelector('button').focus();
    });
    function hideMenu() {
        menu.classList.remove('show');
        menuTab = null;
    }
    menu.addEventListener('click', function(e) {
        var btn = e.target.closest('[data-cmd]');
        if (!btn || !menuTab) return;
        var t = menuTab, i = tabs.indexOf(t);
        hideMenu();
        switch (btn.dataset.cmd) {
            case 'reload':
                if (!dirty(t) || confirm('입력 중인 내용이 사라집니다. 새로고침할까요?')) t.frame.contentWindow.location.reload();
                break;
            case 'detach': detach(t); break;
            case 'others': closeMany(tabs.filter(function(x) { return x !== t; })); break;
            case 'right': closeMany(tabs.slice(i + 1)); break;
            case 'all': closeMany(tabs.slice()); break;
        }
    });
    document.addEventListener('click', function(e) {
        if (!e.target.closest('#mdiMenu')) hideMenu();
    });
    window.addEventListener('blur', hideMenu);

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') hideMenu();
    });

    // 작업창 안에서는 메뉴/통합검색/바로가기를 모두 탭으로 처리
    document.addEventListener('click', function(e) {
        var a = e.target.closest('.sidebar a.sidebar-link, #searchResults a, .mdi-quick a');
        if (!a || modified(e)) return;
        var href = a.getAttribute('href');
        if (!safe(href) || href === '/' || href === '/workspace') return;
        e.preventDefault();
        document.getElementById('searchResults').classList.remove('active');
        open(href, a.textContent.trim());
    });

    document.getElementById('mdiExit').addEventListener('click', function() {
        var bad = tabs.filter(dirty);
        if (bad.length && !confirm('저장하지 않은 탭이 ' + bad.length + '개 있습니다. 탭 작업창을 닫을까요?')) return;
        setEnabled(false);
        try { sessionStorage.removeItem('mdi_tabs'); } catch (e) {}
        location.href = cur ? cur.url : '/';
    });

    // 위젯의 설정 변경은 상위 창 클래스만 변경. 탭 문서에 복사하고 쉬운 모드면 작업창 해제
    var A11Y = ['theme-high-contrast', 'large-target', 'easy-mode'];
    var sync = new MutationObserver(function() {
        if (document.body.classList.contains('easy-mode')) {
            location.href = cur ? cur.url : '/';
            return;
        }
        tabs.forEach(function(t) {
            var doc;
            try { doc = t.frame.contentDocument; } catch (e) { return; }
            if (!doc || !doc.body) return;
            A11Y.forEach(function(c) { doc.body.classList.toggle(c, document.body.classList.contains(c)); });
            ['font-lg', 'font-xl'].forEach(function(c) { doc.documentElement.classList.toggle(c, root.classList.contains(c)); });
        });
    });
    sync.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    sync.observe(root, { attributes: true, attributeFilter: ['class'] });

    window.addEventListener('beforeunload', function(e) {
        if (tabs.some(dirty)) { e.preventDefault(); e.returnValue = ''; }
    });

    /* 복원 */
    var saved = null;
    try { saved = JSON.parse(sessionStorage.getItem('mdi_tabs') || 'null'); } catch (e) {}
    if (saved && saved.tabs) {
        saved.tabs.forEach(function(s) {
            if (safe(s.origin) && safe(s.url) && tabs.length < MAX) create(s.origin, s.url, s.title, true);
        });
        activate(tabs[saved.active] || tabs[0]);
    }
    if (safe(first)) {
        open(first);
        history.replaceState(null, '', '/workspace');
    }

    openTab = open;
    back = function() { if (cur) cur.frame.focus(); };
    window.mdi = { open: open, find: find, focus: function() { window.focus(); } };
})();
