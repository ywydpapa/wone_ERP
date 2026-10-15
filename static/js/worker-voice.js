(function() {
    const V = window.VoiceParse;
    const NONE = /^(없|상관없|아니|아뇨)/;
    // 본인 확인을 거치는 동안 보관하는 명령. 30초 지나면 폐기
    const SS_CMD = 'workerVoiceCmd';
    const STOPPED = '멈출게요. 입력한 값은 그대로 둬요';

    const csrf = () => document.querySelector('meta[name="csrf-token"]').content;
    const on = re => re.test(location.pathname);

    async function go(url, cmd, msg) {
        await Voice.speak(msg, true);
        location.href = url + (url.includes('?') ? '&' : '?') + 'cmd=' + encodeURIComponent(cmd);
    }

    // 취소 시 null. 인식 실패 시 1회 재질문
    async function askSlot(q, parse) {
        for (let i = 0; i < 2; i++) {
            const a = await Voice.ask(i ? '잘 못 알아들었어요. ' + q : q);
            if (a === null) return null;
            const v = parse(a);
            if (v) return v;
        }
        return null;
    }

    async function agree(q) {
        const a = await Voice.ask(q, true);
        return !!a && V.yesno(a) === 'yes';
    }

    function set(el, v) {
        el.value = v;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function showModal(id) {
        const modal = document.getElementById(id);
        return new Promise(res => {
            if (modal.classList.contains('show')) return res(modal);
            modal.addEventListener('shown.bs.modal', () => res(modal), { once: true });
            bootstrap.Modal.getOrCreateInstance(modal).show();
        });
    }

    const won = n => Number(n).toLocaleString() + '원';

    async function verify(cmd) {
        const form = document.querySelector('form[action="/mypage/payslip/verify"]');
        const prev = JSON.parse(sessionStorage.getItem(SS_CMD) || 'null');
        const tries = prev && prev.cmd === cmd ? prev.tries + 1 : 1;
        if (tries > 2) {
            sessionStorage.removeItem(SS_CMD);
            return Voice.speak('본인 확인에 실패했어요. 생년월일을 다시 확인해 주세요');
        }
        const lead = tries > 1 ? '생년월일이 맞지 않아요. ' : '본인 확인이 필요해요. ';
        const d = await askSlot(lead + '생년월일을 말씀해 주세요', V.birthDate);
        if (!d) return Voice.speak('본인 확인을 멈출게요');
        sessionStorage.setItem(SS_CMD, JSON.stringify({ cmd, at: Date.now(), tries }));
        form.elements.birth_date.value = d;
        await Voice.speak('확인할게요', true);
        form.submit();
    }

    function readPayslip() {
        const doc = document.getElementById('payslipDoc');
        if (!doc) {
            const sel = document.getElementById('payslipMonthSel');
            return Voice.speak(sel ? '해당 월 급여명세서가 없어요' : '아직 받은 급여명세서가 없어요');
        }
        const d = doc.dataset;
        return Voice.speak(V.monthText(d.payYm) + ' 급여명세서예요. 지급총액 ' + won(d.gross)
            + ', 공제총액 ' + won(d.deduct) + ', 실지급액 ' + won(d.net) + '이에요');
    }

    async function payslip(p, cmd) {
        const q = new URLSearchParams(location.search);
        const want = p.ym ? '?year=' + Number(p.ym.slice(0, 4)) + '&month=' + Number(p.ym.slice(5, 7)) : '';
        const here = !p.ym || (q.get('year') === String(Number(p.ym.slice(0, 4))) && q.get('month') === String(Number(p.ym.slice(5, 7))));
        if (!on(/^\/mypage\/payslip$/) || !here) return go('/mypage/payslip' + want, cmd, '급여명세서를 열게요');
        if (document.querySelector('form[action="/mypage/payslip/verify"]')) return verify(cmd);
        sessionStorage.removeItem(SS_CMD);
        await readPayslip();
    }

    async function withhold(cmd) {
        if (!on(/^\/mypage\/withholding$/)) return go('/mypage/withholding', cmd, '원천징수부를 열게요');
        if (document.querySelector('form[action="/mypage/payslip/verify"]')) return verify(cmd);
        sessionStorage.removeItem(SS_CMD);
        await Voice.speak('원천징수부를 열었어요. 화면 읽어줘라고 하면 읽어 드려요');
    }

    async function journal(j, cmd) {
        if (!on(/^\/job_diary$/)) return go('/job_diary', cmd, '업무일지 작성 화면으로 갈게요');
        const form = document.querySelector('form[action="/api/jobs"]');
        const f = form.elements;
        if (!f.workDate.value) set(f.workDate, V.ymd(new Date()));
        if (j.start) set(f.startTime, j.start);
        if (j.end) set(f.endTime, j.end);
        if (j.vol) set(f.workVolume, j.vol);
        if (j.unit) set(f.volumeUnit, j.unit);

        const cat = j.cat || await askSlot('업무 분류를 말씀해 주세요. 데이터 입력, 문서 작성, 회의, 개발, 디자인, 운영, 모니터링, 기타 중에서요', V.journalCat);
        if (!cat) return Voice.speak('업무일지 작성을 ' + STOPPED);
        set(f.workCategory, cat);
        const title = await Voice.ask('업무 제목을 말씀해 주세요');
        if (!title) return Voice.speak('업무일지 작성을 ' + STOPPED);
        set(f.workTitle, title.trim());
        const detail = await Voice.ask('상세 업무 내용을 말씀해 주세요');
        if (!detail) return Voice.speak('업무일지 작성을 ' + STOPPED);
        set(f.workDetails, detail.trim());
        const status = j.status || await askSlot('진행 상태는 완료, 진행중, 지연 중 무엇인가요?', V.journalStatus);
        if (!status) return Voice.speak('업무일지 작성을 ' + STOPPED);
        const radio = form.querySelector('input[name=progressStatus][value=' + status + ']');
        radio.checked = true;
        const issue = await Voice.ask('특이사항이 있으면 말씀해 주세요. 없으면 없어요라고 하세요');
        if (issue === null) return Voice.speak('업무일지 작성을 ' + STOPPED);
        if (!NONE.test(V.squash(issue))) set(f.workIssues, issue.trim());

        const sel = f.workCategory;
        const parts = [V.dateText(f.workDate.value), sel.options[sel.selectedIndex].textContent.trim(), '제목 ' + f.workTitle.value,
            '내용 ' + f.workDetails.value, radio.labels[0].textContent.trim()];
        if (j.start && j.end) parts.push(j.start + '부터 ' + j.end + '까지');
        if (j.vol) parts.push('처리량 ' + j.vol + (j.unit || ''));
        if (f.workIssues.value) parts.push('특이사항 ' + f.workIssues.value);
        if (!await agree(parts.join(', ') + '. 제출할까요?')) return Voice.speak('제출하지 않았어요. 화면에서 고칠 수 있어요');
        await Voice.speak('제출할게요', true);
        form.requestSubmit();
    }

    async function recipient(to) {
        let name = null;
        if (to !== null && to !== 'manager') name = to;
        else {
            const r = await fetch('/api/messages/manager');
            if (r.ok) return (await r.json()).name;
            if (to === 'manager') await Voice.speak('아직 배정된 담당자가 없어요', true);
        }
        const res = await fetch('/api/messages/contacts');
        const names = res.ok ? await res.json() : [];
        for (let i = 0; i < 2; i++) {
            if (!name) name = await Voice.ask('누구에게 보낼까요? 이름을 말씀해 주세요');
            if (!name) return null;
            const hit = V.match(name.replace(/(님|한테|에게|께)+$/, ''), names);
            if (hit.length === 1) return names[hit[0]];
            await Voice.speak(name + '님을 찾지 못했어요', true);
            name = null;
        }
        return null;
    }

    async function message(m, cmd) {
        if (!on(/^\/(newarrived_jobs|message\/[0-9]+)$/)) return go('/newarrived_jobs', cmd, '메시지함으로 갈게요');
        const to = await recipient(m.to);
        if (!to) return Voice.speak('메시지를 보내지 않았어요');
        const body = await Voice.ask(to + '님께 전송할 말을 해주세요');
        if (!body) return Voice.speak('메시지를 보내지 않았어요');
        if (!await agree(to + '님께 보낼 내용이에요. ' + body + '. 보낼까요?')) return Voice.speak('메시지를 보내지 않았어요');
        const fd = new FormData();
        fd.append('to_name', to);
        fd.append('body', body.trim());
        fd.append('csrf_token', csrf());
        const res = await fetch('/api/messages/send', { method: 'POST', body: fd });
        if (!res.ok) return Voice.speak('메시지를 보내지 못했어요');
        await Voice.speak('보냈어요');
        location.reload();
    }

    async function inbox(cmd) {
        if (!on(/^\/newarrived_jobs$/)) return go('/newarrived_jobs', cmd, '메시지함에서 읽어 드릴게요');
        const items = [...document.querySelectorAll('#tab-inbox [data-voice-item]')];
        if (!items.length) return Voice.speak('받은 메시지가 없어요');
        const unread = items.filter(el => el.dataset.voiceText.startsWith('새 메시지')).length;
        const lines = items.slice(0, 3).map((el, i) => (i + 1) + '번 ' + el.dataset.voiceText);
        await Voice.speak('안 읽은 메시지 ' + unread + '건이에요. ' + lines.join('. '));
    }

    // 글 한 칸을 받아 읽어 주고 확인 후 제출함. verb는 보낼/등록할 형태
    async function sendText(form, box, q, check, verb) {
        const no = verb === '보낼' ? '보내지 않았어요' : '등록하지 않았어요';
        const said = await Voice.ask(q);
        if (!said) return Voice.speak(no);
        set(box, said.trim());
        if (!await agree(check + ', ' + said + '. ' + verb + '까요?')) return Voice.speak(no);
        form.requestSubmit();
    }

    function reply() {
        const form = document.querySelector('#main form[action$="/reply"]');
        if (!form) return false;
        return sendText(form, form.elements.body, '답장할 말을 해주세요', '답장 내용', '보낼');
    }

    function comment() {
        const form = document.querySelector('#main form[action$="/comments"]');
        if (!form) return false;
        return sendText(form, form.elements.content, '남길 말을 해주세요', '소통 댓글', '등록할');
    }

    async function help() {
        if (!document.getElementById('helpModal')) return false;
        const modal = await showModal('helpModal');
        const form = modal.querySelector('form');
        return sendText(form, form.elements.reason, '어떤 부분이 어려운지 말씀해 주세요', '도움 요청 내용', '보낼');
    }

    async function taskSubmit() {
        const form = document.querySelector('#main form[action$="/submit"][action^="/task/"]');
        if (!form) return false;
        const vol = form.elements.completed_volume;
        let msg = '검토 요청할까요?';
        if (vol) {
            const n = await askSlot('완료 수량은 몇 건인가요?', a => V.money(a.replace(/(건|개|장|페이지)/g, '')));
            if (!n) return Voice.speak('검토 요청을 ' + STOPPED);
            set(vol, n);
            msg = '완료 수량 ' + n + '건으로 ' + msg;
        }
        if (!await agree(msg)) return Voice.speak('검토 요청하지 않았어요');
        await Voice.speak('검토 요청할게요', true);
        form.requestSubmit();
    }

    async function cert(c, cmd) {
        if (!on(/^\/mypage\/certificates$/)) return go('/mypage/certificates', cmd, '증명서 발급 화면으로 갈게요');
        const type = c.type || await askSlot('어떤 증명서인가요? 재직증명서, 경력증명서, 소득금액증명 중에 말씀해 주세요', V.certType);
        if (!type) return Voice.speak('증명서 발급을 멈출게요');
        const card = document.querySelector('[data-cert="' + type + '"]');
        const shown = new Promise(res => document.getElementById('certModal').addEventListener('shown.bs.modal', res, { once: true }));
        card.click();
        await shown;
        const purpose = c.purpose || await askSlot('용도를 말씀해 주세요. 은행 제출용, 관공서 제출용, 개인 보관용, 기타 중에서요', V.certPurpose);
        if (!purpose) return Voice.speak('증명서 발급을 멈출게요');
        const form = document.querySelector('#certModal form');
        set(form.elements.purpose, purpose);
        if (!await agree(type + ', ' + purpose + '. 발급할까요?')) return Voice.speak('발급하지 않았어요');
        await Voice.speak('발급할게요', true);
        form.requestSubmit();
    }

    async function accom(a, cmd) {
        if (!on(/^\/mypage\/accommodation$/)) return go('/mypage/accommodation', cmd, '편의지원 신청 화면으로 갈게요');
        const modal = await showModal('accomModal');
        const form = modal.querySelector('form');
        const f = form.elements;
        const cat = a.cat || await askSlot('지원 유형을 말씀해 주세요. 보조공학기기, 근로지원인, 작업환경 조정 중에서요', V.accomCat);
        if (!cat) return Voice.speak('편의지원 신청을 ' + STOPPED);
        set(f.category, cat);
        const title = await Voice.ask('신청 제목을 말씀해 주세요');
        if (!title) return Voice.speak('편의지원 신청을 ' + STOPPED);
        set(f.title, title.trim().slice(0, 100));
        const desc = await Voice.ask('필요한 이유나 자세한 내용을 말씀해 주세요. 없으면 없어요라고 하세요');
        if (desc === null) return Voice.speak('편의지원 신청을 ' + STOPPED);
        if (!NONE.test(V.squash(desc))) set(f.description, desc.trim());
        if (a.urgency) set(f.urgency, a.urgency);
        const urg = f.urgency.options[f.urgency.selectedIndex].textContent.trim();
        const parts = [cat, '제목 ' + f.title.value, f.description.value ? '내용 ' + f.description.value : '', '긴급도 ' + urg].filter(Boolean);
        if (!await agree(parts.join(', ') + '. 신청할까요?')) return Voice.speak('신청하지 않았어요. 화면에서 고칠 수 있어요');
        await Voice.speak('신청할게요', true);
        form.requestSubmit();
    }

    async function run(cmd) {
        const p = V.payslipCmd(cmd, new Date());
        if (p) {
            await payslip(p, cmd);
            return true;
        }
        if (V.withholdCmd(cmd)) {
            await withhold(cmd);
            return true;
        }
        const j = V.journalCmd(cmd);
        if (j) {
            await journal(j, cmd);
            return true;
        }
        if (V.inboxCmd(cmd)) {
            await inbox(cmd);
            return true;
        }
        const m = V.messageCmd(cmd);
        if (m) {
            await message(m, cmd);
            return true;
        }
        if (V.replyCmd(cmd) && await reply() !== false) return true;
        if (V.commentCmd(cmd) && await comment() !== false) return true;
        if (V.helpCmd(cmd) && await help() !== false) return true;
        if (V.taskSubmitCmd(cmd) && await taskSubmit() !== false) return true;
        const c = V.certCmd(cmd);
        if (c) {
            await cert(c, cmd);
            return true;
        }
        const a = V.accomCmd(cmd);
        if (a) {
            await accom(a, cmd);
            return true;
        }
        return false;
    }

    Voice.onCommand(run, cmd => !!(V.payslipCmd(cmd, new Date()) || V.withholdCmd(cmd) || V.journalCmd(cmd) || V.inboxCmd(cmd)
        || V.messageCmd(cmd) || V.certCmd(cmd) || V.accomCmd(cmd)));

    // 본인 확인 후 남은 명령을 이어서 실행함. 주소로 받은 명령이 있으면 그쪽 우선
    const pending = JSON.parse(sessionStorage.getItem(SS_CMD) || 'null');
    if (pending && Date.now() - pending.at < 30000) {
        if (!new URLSearchParams(location.search).has('cmd')) Voice.run(pending.cmd);
    } else {
        sessionStorage.removeItem(SS_CMD);
    }
})();
