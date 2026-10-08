(function() {
    /* 금액 입력 */
    function num(v) {
        var s = String(v == null ? '' : v).replace(/[^\d-]/g, '');
        return parseInt(s, 10) || 0;
    }
    function fmt(n) {
        return Number(n || 0).toLocaleString('ko-KR');
    }

    function formatAmt(el) {
        var raw = el.value;
        var pos = el.selectionStart == null ? raw.length : el.selectionStart;
        var digitsBefore = raw.slice(0, pos).replace(/[^\d]/g, '').length;
        var neg = /^\s*-/.test(raw);
        var digits = raw.replace(/[^\d]/g, '').replace(/^0+(?=\d)/, '');
        el.value = (neg ? '-' : '') + digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        if (document.activeElement !== el) return;
        var cnt = 0, i = neg ? 1 : 0;
        while (i < el.value.length && cnt < digitsBefore) {
            if (/\d/.test(el.value[i])) cnt++;
            i++;
        }
        el.setSelectionRange(i, i);
    }

    window.amt = {
        val: function(el) { return num(el.value); },
        set: function(el, n) { el.value = n ? fmt(n) : '0'; },
        fmt: fmt
    };

    document.addEventListener('input', function(e) {
        if (e.target.classList.contains('amt')) formatAmt(e.target);
    });
    // 클릭 포커스 시 mouseup이 선택 해제. 1회 차단
    var picked = null;
    document.addEventListener('focusin', function(e) {
        if (!e.target.classList.contains('amt')) return;
        e.target.select();
        picked = e.target;
    });
    document.addEventListener('mouseup', function(e) {
        if (e.target === picked) e.preventDefault();
        picked = null;
    });
    // 폼 자체 검증이 막으면 콤마 유지
    document.addEventListener('submit', function(e) {
        if (e.defaultPrevented) return;
        e.target.querySelectorAll('.amt').forEach(function(el) {
            el.value = el.value.replace(/,/g, '');
        });
    });
    // bfcache 복귀 시 다시 콤마
    window.addEventListener('pageshow', function() {
        document.querySelectorAll('.amt').forEach(formatAmt);
    });
    document.querySelectorAll('.amt').forEach(formatAmt);

    /* 코드 조회 */
    var SRC = {
        partner: { url: '/api/partners', title: '거래처', key: 'id', sub: 'biz_no', subLabel: '사업자번호' },
        account: { url: '/api/accounts', title: '계정과목', key: 'code', sub: 'category', subLabel: '분류' },
        bank: { url: '/api/bank_accounts', title: '계좌', key: 'id', sub: 'bank', subLabel: '은행' },
        memo: { url: '/api/memo_codes', title: '적요', key: 'id', sub: 'account_code', subLabel: '연결계정' }
    };
    var data = {}, reqs = {};

    function load(type) {
        if (!reqs[type]) {
            reqs[type] = fetch(SRC[type].url).then(function(r) { return r.json(); }).then(function(rows) {
                data[type] = rows;
                return rows;
            });
        }
        return reqs[type];
    }

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : s;
        return d.innerHTML;
    }

    function scope(el) {
        return el.closest('.lookup') || el.closest('tr') || el.parentNode;
    }

    function fill(input, row) {
        // 적요는 코드를 남기지 않고 본문 내용으로 바로 치환함
        if (input.dataset.lookup === 'memo') {
            input.value = row ? row.name : input.value;
            input.dispatchEvent(new CustomEvent('lookup', { bubbles: true, detail: row }));
            return;
        }
        var box = scope(input);
        var name = box.querySelector('.lk-name');
        var id = box.querySelector('.lk-id');
        input.value = row ? row.code : input.value;
        if (name) name.value = row ? row.name : '';
        if (id) id.value = row ? row[SRC[input.dataset.lookup].key] : '';
        input.classList.toggle('is-invalid', !row && !!input.value.trim());
        input.dispatchEvent(new CustomEvent('lookup', { bubbles: true, detail: row }));
    }

    function match(rows, q) {
        q = q.trim().toLowerCase();
        if (!q) return rows;
        return rows.filter(function(r) {
            return String(r.code).toLowerCase().indexOf(q) >= 0 || String(r.name).toLowerCase().indexOf(q) >= 0;
        });
    }

    // 코드 일치 또는 이름 1건 일치면 확정, 아니면 모달
    function resolve(input) {
        var q = input.value.trim();
        var rows = data[input.dataset.lookup];
        if (!q) { fill(input, null); return true; }
        if (!rows) {
            load(input.dataset.lookup).then(function() { resolve(input); });
            return true;
        }
        var exact = rows.find(function(r) { return String(r.code) === q; });
        if (exact) { fill(input, exact); return true; }
        if (input.dataset.lookup === 'memo') return true;
        var found = match(rows, q);
        if (found.length === 1) { fill(input, found[0]); return true; }
        openModal(input, q);
        return false;
    }

    var modal, modalEl, target, hits = [];

    function buildModal() {
        modalEl = document.createElement('div');
        modalEl.className = 'modal fade lk-modal';
        modalEl.tabIndex = -1;
        modalEl.setAttribute('aria-labelledby', 'lkTitle');
        modalEl.innerHTML =
            '<div class="modal-dialog modal-dialog-scrollable"><div class="modal-content">' +
            '<div class="modal-header py-2"><h6 class="modal-title" id="lkTitle"></h6>' +
            '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="닫기"></button></div>' +
            '<div class="modal-body"><input type="text" class="form-control form-control-sm lk-filter" placeholder="코드 또는 이름">' +
            '<div class="lk-list"><table class="grid-table"><thead><tr><th>코드</th><th>이름</th><th class="lk-sub"></th></tr></thead>' +
            '<tbody></tbody></table></div></div></div></div>';
        document.body.appendChild(modalEl);
        modal = new bootstrap.Modal(modalEl);

        var filter = modalEl.querySelector('.lk-filter');
        filter.addEventListener('input', function() { renderList(filter.value); });
        filter.addEventListener('keydown', function(e) {
            var trs = Array.from(modalEl.querySelectorAll('tbody tr[data-idx]'));
            var idx = trs.findIndex(function(tr) { return tr.classList.contains('active'); });
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                idx = e.key === 'ArrowDown' ? Math.min(trs.length - 1, idx + 1) : Math.max(0, idx - 1);
                trs.forEach(function(tr, i) { tr.classList.toggle('active', i === idx); });
                if (trs[idx]) trs[idx].scrollIntoView({ block: 'nearest' });
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (trs[idx]) pick(trs[idx]);
            }
        });
        modalEl.querySelector('tbody').addEventListener('click', function(e) {
            var tr = e.target.closest('tr[data-idx]');
            if (tr) pick(tr);
        });
        // base.html 공통 포커스 처리 뒤에 필터 적용
        modalEl.addEventListener('shown.bs.modal', function() { setTimeout(function() { filter.focus(); }); });
    }

    function renderList(q) {
        var src = SRC[target.dataset.lookup];
        hits = match(data[target.dataset.lookup], q).slice(0, 200);
        modalEl.querySelector('tbody').innerHTML = hits.length ? hits.map(function(r, i) {
            return '<tr data-idx="' + i + '"' + (i === 0 ? ' class="active"' : '') + '><td>' + esc(r.code) + '</td><td>' +
                esc(r.name) + '</td><td>' + esc(r[src.sub]) + '</td></tr>';
        }).join('') : '<tr><td colspan="3" class="lk-empty">검색 결과가 없습니다</td></tr>';
    }

    function pick(tr) {
        fill(target, hits[+tr.dataset.idx]);
        modal.hide();
    }

    function openModal(input, q) {
        target = input;
        load(input.dataset.lookup).then(function() {
            if (!modal) buildModal();
            var src = SRC[input.dataset.lookup];
            modalEl.querySelector('.modal-title').textContent = src.title + ' 검색';
            modalEl.querySelector('.lk-sub').textContent = src.subLabel;
            modalEl.querySelector('.lk-filter').value = q || '';
            renderList(q || '');
            modal.show();
        });
    }

    // 그리드 Enter 이동보다 먼저 처리. capture 사용
    document.addEventListener('keydown', function(e) {
        var el = e.target;
        if (!el.classList || !el.classList.contains('lk-code')) return;
        if (e.key === 'F2') {
            e.preventDefault();
            openModal(el, el.value);
        } else if (e.key === 'Enter' && !e.isComposing) {
            // 비고 textarea는 Shift+Enter만 줄바꿈 허용
            if (el.tagName === 'TEXTAREA' && e.shiftKey) return;
            e.preventDefault();
            if (!resolve(el)) e.stopPropagation();
        }
    }, true);
    document.addEventListener('change', function(e) {
        if (e.target.classList.contains('lk-code')) resolve(e.target);
    });
    document.addEventListener('click', function(e) {
        var btn = e.target.closest('.lk-btn');
        if (!btn) return;
        var input = scope(btn).querySelector('.lk-code');
        openModal(input, '');
    });

    var types = {};
    document.querySelectorAll('.lk-code[data-lookup]').forEach(function(el) { types[el.dataset.lookup] = 1; });
    Object.keys(types).forEach(load);
    window.lookup = {
        load: load,
        resolve: resolve,
        reload: function(type) { reqs[type] = null; return load(type); }
    };

    // 검증 실패 시 서버가 JSON 반환. 페이지 이동 없이 입력값 유지
    function ajaxSubmit(form, opts) {
        opts = opts || {};
        var msgEl = opts.msgEl || form.querySelector('.ab-msg');
        form.addEventListener('submit', function(e) {
            if (e.defaultPrevented) return;
            e.preventDefault();
            if (form.dataset.busy) return;
            form.dataset.busy = '1';
            if (msgEl) msgEl.textContent = '';
            var fd = new FormData(form);
            if (e.submitter && e.submitter.name) fd.set(e.submitter.name, e.submitter.value);
            fetch(form.action, { method: 'POST', body: fd })
                .then(function(r) {
                    if (r.redirected || r.ok) {
                        if (opts.dirty) opts.dirty.clear();
                        if (opts.onSuccess) opts.onSuccess();
                        location.href = r.url;
                        return;
                    }
                    delete form.dataset.busy;
                    return r.json().catch(function() { return {}; }).then(function(data) {
                        var text = data.error || data.detail || '처리 중 오류가 발생했습니다.';
                        if (msgEl) msgEl.textContent = text; else alert(text);
                    });
                })
                .catch(function() {
                    delete form.dataset.busy;
                    if (msgEl) msgEl.textContent = '네트워크 오류가 발생했습니다. 다시 시도해 주세요.';
                });
        });
    }

    var trackers = [];

    function trackDirty(form) {
        var dirty = false;
        form.addEventListener('input', function() { dirty = true; });
        form.addEventListener('change', function() { dirty = true; });
        window.addEventListener('beforeunload', function(e) {
            if (!dirty) return;
            e.preventDefault();
            e.returnValue = '';
        });
        var t = { clear: function() { dirty = false; }, isDirty: function() { return dirty; } };
        trackers.push(t);
        return t;
    }

    // BroadcastChannel 미지원 브라우저는 storage 이벤트로 대체
    var masterCh = ('BroadcastChannel' in window) ? new BroadcastChannel('erp_master') : null;

    function notifyMaster(kind) {
        if (masterCh) {
            masterCh.postMessage({ kind: kind, t: Date.now() });
        } else {
            try { localStorage.setItem('erp_master_' + kind, String(Date.now())); } catch (e) {}
        }
    }

    function onMasterChange(kind, cb) {
        if (masterCh) {
            masterCh.addEventListener('message', function(e) {
                if (e.data && e.data.kind === kind) cb();
            });
        } else {
            window.addEventListener('storage', function(e) {
                if (e.key === 'erp_master_' + kind) cb();
            });
        }
    }

    // 다른 창의 전표 변경 시 새로고침 안내. 스크린리더 고지를 위해 빈 영역 선배치
    var watch = document.body.dataset.watch;
    if (watch) {
        var bar = document.createElement('div');
        bar.className = 'watch-bar';
        bar.setAttribute('role', 'status');
        var main = document.getElementById('main');
        main.insertBefore(bar, main.firstChild);
        onMasterChange(watch, function() {
            if (bar.firstChild) return;
            bar.innerHTML = '<span>다른 화면에서 전표가 변경되었습니다.</span><button type="button" class="btn btn-sm btn-primary">새로고침</button>';
            bar.querySelector('button').addEventListener('click', function() { location.reload(); });
        });
    }

    // 회계연도 설정이 없으면 당기는 1월~12월 기준
    function ymd(d) {
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }
    document.addEventListener('click', function(e) {
        var btn = e.target.closest('[data-preset]');
        if (!btn) return;
        var now = new Date(), y = now.getFullYear(), m = now.getMonth(), q = m - m % 3;
        var range = {
            month: [new Date(y, m, 1), new Date(y, m + 1, 0)],
            prev: [new Date(y, m - 1, 1), new Date(y, m, 0)],
            quarter: [new Date(y, q, 1), new Date(y, q + 3, 0)],
            year: [new Date(y, 0, 1), new Date(y, 11, 31)]
        }[btn.dataset.preset];
        var form = btn.closest('form');
        form.elements.date_from.value = ymd(range[0]);
        form.elements.date_to.value = ymd(range[1]);
        form.requestSubmit();
    });

    // 이카운트 기준 F8 저장, Esc 팝업 닫기. 미저장 확인은 beforeunload 처리
    document.addEventListener('keydown', function(e) {
        if (e.defaultPrevented || e.isComposing) return;
        if (e.key === 'F8') {
            var btn = document.querySelector('[data-key="F8"]:not([disabled])');
            if (!btn) return;
            e.preventDefault();
            btn.click();
        } else if (e.key === 'Escape' && window.name.indexOf('erp-pop-') === 0 && !document.querySelector('.modal.show')) {
            window.close();
        }
    });

    window.formKit = {
        ajaxSubmit: ajaxSubmit,
        trackDirty: trackDirty,
        notifyMaster: notifyMaster,
        onMasterChange: onMasterChange,
        isDirty: function() { return trackers.some(function(t) { return t.isDirty(); }); }
    };
})();
