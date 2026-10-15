(function() {
    const V = window.VoiceParse;
    const LEAVE_URL = '/mypage/leave';
    const LEAVE_NAMES = { annual: '연차', half_day: '반차', sick: '병가', family_event: '경조사', official: '공가', other: '기타' };
    const NONE = /^(없|상관없|아니|아뇨)/;

    // 빈 목록 안내 행(colspan 단일 셀) 제외
    function rows() {
        const marked = [...document.querySelectorAll('#main [data-voice-item]')];
        const all = marked.length ? marked : [...document.querySelectorAll('#main table tbody tr')];
        return all.filter(tr => tr.getClientRects().length > 0 && !(tr.cells && tr.cells.length === 1 && tr.cells[0].colSpan > 1));
    }

    function pickRow(ord) {
        const all = rows();
        if (ord === -1) return all[all.length - 1] || null;
        return all[ord - 1] || null;
    }

    function rowText(tr) {
        if (tr.dataset.voiceText) return tr.dataset.voiceText;
        const ths = tr.closest('table') ? [...tr.closest('table').querySelectorAll('thead th')] : [];
        const out = [];
        [...tr.cells].forEach((td, i) => {
            const v = td.textContent.replace(/\s+/g, ' ').trim();
            if (!v) return;
            const h = ths[i] ? ths[i].textContent.replace(/\s+/g, ' ').trim() : '';
            out.push(h ? h + ' ' + v : v);
        });
        return out.join(', ');
    }

    async function rowCmd(r) {
        const all = rows();
        const tr = pickRow(r.ord);
        if (!tr) return Voice.speak(all.length ? '해당 순서의 항목이 없어요. 모두 ' + all.length + '건이에요' : '이 화면에는 목록이 없어요');
        if (r.act === 'read') return Voice.speak(rowText(tr) || '내용이 없어요');
        const link = tr.dataset.href || (tr.matches('a[href]') ? tr : tr.querySelector('a[href]:not([href^="#"])') || {}).href;
        if (!link) return Voice.speak('열 수 있는 항목이 아니에요');
        await Voice.speak('열게요', true);
        location.href = link;
    }

    // 반려 모달은 사유 입력 필수. 사유를 먼저 받고 모달을 채워 제출함
    async function reject() {
        const opener = document.querySelector('#main [data-bs-target="#rejectModal"]');
        if (!opener) return false;
        const why = await Voice.ask('반려 사유를 말씀해 주세요');
        if (!why) return Voice.speak('반려하지 않았어요');
        const modal = document.getElementById('rejectModal');
        bootstrap.Modal.getOrCreateInstance(modal).show();
        const box = modal.querySelector('textarea');
        box.value = why;
        box.dispatchEvent(new Event('input', { bubbles: true }));
        const ans = await Voice.ask('반려 사유, ' + why + '. 반려할까요?', true);
        if (!ans || V.yesno(ans) !== 'yes') {
            bootstrap.Modal.getOrCreateInstance(modal).hide();
            return Voice.speak('반려하지 않았어요');
        }
        await Voice.speak('반려할게요', true);
        modal.querySelector('form').requestSubmit();
        return true;
    }

    async function askLeaveType() {
        const ans = await Voice.ask('어떤 휴가인가요? 연차, 반차, 병가, 경조사, 공가, 기타 중에 말씀해 주세요');
        return ans && V.leaveCmd(ans + ' 신청', new Date());
    }

    async function leave(lv) {
        if (location.pathname !== LEAVE_URL) {
            await Voice.speak('휴가 신청 화면으로 갈게요', true);
            location.href = LEAVE_URL + '?cmd=' + encodeURIComponent(lv.raw);
            return;
        }
        const today = new Date();
        if (!lv.type) {
            const t = await askLeaveType();
            if (!t || !t.type) return Voice.speak('휴가 종류를 못 알아들었어요. 신청하지 않았어요');
            lv.type = t.type;
            lv.half = lv.half || t.half;
        }
        if (lv.type === 'half_day' && !lv.half) {
            const ans = await Voice.ask('오전 반차인가요, 오후 반차인가요?');
            if (!ans || !/오전|오후/.test(ans)) return Voice.speak('신청하지 않았어요');
            lv.half = ans.includes('오전') ? 'am' : 'pm';
        }
        if (!lv.start) {
            const ans = await Voice.ask('언제 쉬시나요? 날짜를 말씀해 주세요');
            // 되물은 답의 월 없는 N일은 날짜로 봄
            const said = ans && ans.trim() + (/부터|까지/.test(ans) ? '' : '에') + (lv.dur > 1 ? ' ' + lv.dur + '일간' : '');
            const d = said && V.leaveCmd('연차 ' + said + ' 신청', today);
            if (!d || !d.start) return Voice.speak('날짜를 못 알아들었어요. 신청하지 않았어요');
            lv.start = d.start;
            lv.end = d.end;
        }
        if (lv.type === 'half_day') lv.end = lv.start;
        const days = lv.type === 'half_day' ? 0.5 : V.workDays(lv.start, lv.end);

        const modal = document.getElementById('leaveModal');
        const form = modal.querySelector('form');
        bootstrap.Modal.getOrCreateInstance(modal).show();
        const set = (name, v) => {
            const el = form.elements[name];
            el.value = v;
            el.dispatchEvent(new Event('change', { bubbles: true }));
        };
        set('leave_type', lv.type);
        if (lv.half) set('half_day_period', lv.half);
        set('start_date', lv.start);
        set('end_date', lv.end);
        set('days', days);

        const why = await Voice.ask('사유를 말씀해 주세요. 없으면 없다고 말씀해 주세요');
        if (why === null) return Voice.speak('신청하지 않았어요');
        if (!NONE.test(V.squash(why))) form.elements.reason.value = why;

        const name = lv.type === 'half_day' ? (lv.half === 'am' ? '오전 반차' : '오후 반차') : LEAVE_NAMES[lv.type];
        const when = lv.start === lv.end ? V.dateText(lv.start) : V.dateText(lv.start) + '부터 ' + V.dateText(lv.end) + '까지';
        const ans = await Voice.ask(name + ', ' + when + ', ' + days + '일. 신청할까요?', true);
        if (!ans || V.yesno(ans) !== 'yes') return Voice.speak('신청하지 않았어요. 화면에서 고칠 수 있어요');
        await Voice.speak('신청할게요', true);
        form.requestSubmit();
    }

    async function run(cmd) {
        const r = V.rowCmd(cmd);
        if (r) {
            await rowCmd(r);
            return true;
        }
        const lv = V.leaveCmd(cmd, new Date());
        if (lv) {
            lv.raw = cmd;
            await leave(lv);
            return true;
        }
        if (V.rejectCmd(cmd) && await reject() !== false) return true;
        return false;
    }

    Voice.onCommand(run);
})();
