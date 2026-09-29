(function() {
    const V = window.VoiceParse;
    const SS_ON = 'voice_on';
    const SS_SLIP = 'voice_slip';
    const SLIP_URL = '/new_slip_simple';
    const MAX_VAD_SAMPLES = 16000 * 60;
    const HELP = '잘 모르겠어요. 지금 어디야, 화면 읽어줘, 또는 메뉴 이름을 말해 보세요';
    const ORD = { 첫: 1, 한: 1, 하나: 1, 두: 2, 둘: 2, 세: 3, 셋: 3 };
    const TTS_CACHE_MAX = 50;

    const cfg = JSON.parse(document.getElementById('a11yInit').textContent);
    const statusEl = document.getElementById('voiceStatus');
    const onBtn = document.getElementById('a11yVoiceOn');
    const fab = document.getElementById('a11yFab');

    ort.env.wasm.numThreads = 1;

    let playing = false;
    let audioEl = null, endPlay = null;
    let ttsFallback = false; // /api/tts 실패하면 이 페이지 동안 계속 폴백
    let ttsCache = new Map();
    let speakGen = 0;

    let micVad = null, actx = null, micP = null;
    let alwaysOn = false;
    let muted = false;
    let inflight = false;
    let armedUntil = 0; // "하이원"만 들었을 때 다음 문장을 명령으로 받는 기한
    let waiter = null;
    let flow = 0;
    let dict = null; // { el, btn, stack, queue }

    function setStatus(msg) {
        statusEl.textContent = msg;
        statusEl.hidden = !msg;
    }

    function needGesture() {
        setStatus('화면을 한 번 눌러 주세요');
        document.addEventListener('pointerdown', () => {
            if (actx) actx.resume();
            if (audioEl) audioEl.play().catch(() => {});
            setStatus('');
        }, { once: true });
    }

    async function fetchTts(text) {
        const key = cfg.tts_voice + cfg.tts_speed + text;
        const cached = ttsCache.get(key);
        if (cached) return cached;
        const fd = new FormData();
        fd.append('text', text);
        fd.append('voice', cfg.tts_voice || 'F1');
        fd.append('speed', cfg.tts_speed || 'normal');
        fd.append('csrf_token', document.querySelector('meta[name="csrf-token"]').content);
        const res = await fetch('/api/tts', { method: 'POST', body: fd });
        if (res.redirected) {
            location.href = res.url;
            throw new Error('redirected');
        }
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw { status: res.status, msg: body.error };
        }
        const url = URL.createObjectURL(await res.blob());
        if (text.length <= 20) {
            if (ttsCache.size >= TTS_CACHE_MAX) {
                const first = ttsCache.keys().next().value;
                URL.revokeObjectURL(ttsCache.get(first));
                ttsCache.delete(first);
            }
            ttsCache.set(key, url);
        }
        return url;
    }

    function playUrl(url) {
        return new Promise(res => {
            endPlay = res;
            audioEl = new Audio(url);
            audioEl.onended = res;
            audioEl.onerror = res;
            audioEl.play().catch(e => {
                if (e.name === 'NotAllowedError') needGesture();
                res();
            });
        });
    }

    function localVoice() {
        const synth = window.speechSynthesis;
        return synth ? synth.getVoices().find(v => v.lang === 'ko-KR' && v.localService) : null;
    }

    function speakFallback(text) {
        const synth = window.speechSynthesis;
        const voice = localVoice();
        if (!voice) return Promise.resolve();
        return new Promise(res => {
            const u = new SpeechSynthesisUtterance(text);
            u.lang = 'ko-KR';
            u.voice = voice;
            u.onend = res;
            u.onerror = e => {
                if (e.error === 'not-allowed') needGesture();
                res();
            };
            synth.speak(u);
        });
    }

    // 재생 중이던 promise도 같이 풀어야 speak를 기다리던 쪽이 안 멈춤
    function cutAudio() {
        if (audioEl) audioEl.pause();
        if (endPlay) endPlay();
        if (window.speechSynthesis) window.speechSynthesis.cancel();
    }

    // 버린 prefetch는 blob URL만 회수
    function dropPrefetch(p) {
        p.then(url => {
            if (![...ttsCache.values()].includes(url)) URL.revokeObjectURL(url);
        }, () => {});
    }

    async function speakSentences(text, gen) {
        const parts = V.sentences(text);
        if (!parts.length) return;
        let next = fetchTts(parts[0]);
        for (let i = 0; i < parts.length; i++) {
            if (gen !== speakGen) {
                dropPrefetch(next);
                return;
            }
            let url;
            try {
                url = await next;
            } catch (e) {
                if (e.status === 503 || e instanceof TypeError) {
                    ttsFallback = true;
                    return speakFallback(parts.slice(i).join(' '));
                }
                // 400 등 이 문장만 못 읽는 경우는 건너뛰고 계속
                if (i + 1 < parts.length) next = fetchTts(parts[i + 1]);
                continue;
            }
            if (i + 1 < parts.length) next = fetchTts(parts[i + 1]);
            if (gen !== speakGen) {
                dropPrefetch(next);
                return;
            }
            await playUrl(url);
            if (![...ttsCache.values()].includes(url)) URL.revokeObjectURL(url);
        }
    }

    // 읽는 중에도 "그만"은 받음 (헤드셋 전제)
    async function speak(text, bargeIn) {
        setStatus(text);
        document.getElementById('srLive').textContent = text;
        if (!text) return;
        const gen = ++speakGen;
        cutAudio();
        muted = !bargeIn;
        if (muted && micVad) await micVad.pause();
        playing = true;
        await (ttsFallback ? speakFallback(text) : speakSentences(text, gen));
        if (gen === speakGen) {
            playing = false;
            muted = false;
            if (micVad) await micVad.start();
        }
    }

    async function openMic() {
        actx = new AudioContext();
        if (actx.state === 'suspended') needGesture();
        try {
            micVad = await vad.MicVAD.new({
                audioContext: actx,
                model: 'v5',
                baseAssetPath: '/static/vendor/vad/',
                onnxWASMBasePath: '/static/vendor/vad/',
                redemptionMs: 1000,
                preSpeechPadMs: 300,
                minSpeechMs: 300,
                startOnLoad: false,
                // 문장마다 트랙 다시 잡지 말고 스트림 유지
                pauseStream: async () => {},
                resumeStream: async s => s,
                onSpeechStart: onVadSpeechStart,
                onSpeechEnd: onVadSpeechEnd,
            });
        } catch (e) {
            actx.close();
            actx = null;
            throw e;
        }
        await micVad.start();
    }

    function closeMic() {
        if (!micVad) return;
        micVad.destroy();
        actx.close();
        micVad = actx = null;
        micP = null;
    }

    function ensureMic() {
        micP ||= openMic().then(() => true, async e => {
            micP = null;
            micVad = null;
            const msg = e && e.name === 'NotAllowedError' ? '마이크를 사용할 수 없습니다' : '음성 인식을 준비하지 못했습니다';
            await speak(msg);
            setAlways(false, true);
            return false;
        });
        return micP;
    }

    function listening() {
        return !muted && !inflight && (alwaysOn || waiter || dict || Date.now() < armedUntil);
    }

    function onVadSpeechStart() {
        if (listening()) setStatus('듣는 중');
        if (dict) resetDictTimer();
    }

    async function onVadSpeechEnd(pcm) {
        if (!listening()) {
            if (dict && inflight) dict.queue.push(pcm);
            return;
        }
        if (pcm.length > MAX_VAD_SAMPLES) {
            await speak('너무 길어요. 나눠서 말해 주세요');
            return;
        }
        recognize(pcm);
    }

    function toWav(pcm) {
        const n = pcm.length;
        const view = new DataView(new ArrayBuffer(44 + n * 2));
        const str = (o, s) => {
            for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i));
        };
        str(0, 'RIFF');
        view.setUint32(4, 36 + n * 2, true);
        str(8, 'WAVE');
        str(12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, 16000, true);
        view.setUint32(28, 32000, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        str(36, 'data');
        view.setUint32(40, n * 2, true);
        let o = 44;
        for (let i = 0; i < n; i++) {
            view.setInt16(o, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
            o += 2;
        }
        return new Blob([view], { type: 'audio/wav' });
    }

    async function stt(wav) {
        const fd = new FormData();
        fd.append('audio', wav, 'voice.wav');
        fd.append('csrf_token', document.querySelector('meta[name="csrf-token"]').content);
        const res = await fetch('/api/stt', { method: 'POST', body: fd });
        if (res.redirected) {
            location.href = res.url;
            return '';
        }
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw { status: res.status, msg: body.error };
        return body.text || '';
    }

    function drainDictQueue() {
        if (!dict || !dict.queue.length) return;
        recognize(dict.queue.shift());
    }

    async function recognize(pcm) {
        inflight = true;
        setStatus('인식 중');
        const id = flow;
        let text;
        try {
            text = await stt(toWav(pcm));
        } catch (e) {
            inflight = false;
            drainDictQueue();
            if (id !== flow) return;
            if (e.status === 503) {
                await speak(e.msg || '음성 인식 모델을 사용할 수 없습니다');
                setAlways(false, true);
                stop();
            } else if (dict) {
                await speak('잘 못 들었어요');
                resetDictTimer();
            } else {
                await speak('잠시 후 다시 시도해 주세요');
                if (waiter) resolveWaiter('');
            }
            return;
        }
        inflight = false;
        drainDictQueue();
        if (id !== flow) return;
        heard(text.trim());
    }

    function heard(text) {
        if (waiter) return resolveWaiter(text);
        if (dict) return dictHeard(text);
        if (Date.now() < armedUntil) {
            const armed = V.stripWake(text) ?? text;
            if (!armed) return;
            armedUntil = 0;
            return start(() => run(armed));
        }
        const cmd = V.stripWake(text);
        if (cmd === null) {
            // 읽는 중에는 웨이크워드 없이 "그만"만 받음
            if (playing && V.classify(text).kind === 'stop') stop();
            else setStatus(alwaysOn ? '대기 중' : '');
            return;
        }
        if (!cmd) {
            armedUntil = Date.now() + 5000;
            speak('네');
            return;
        }
        start(() => run(cmd));
    }

    function resolveWaiter(text) {
        const w = waiter;
        waiter = null;
        w(text);
    }

    function listen() {
        return new Promise(res => {
            const done = text => {
                clearTimeout(timer);
                res(text);
            };
            const timer = setTimeout(() => {
                if (waiter === done) resolveWaiter('');
            }, 10000);
            waiter = done;
            setStatus('듣는 중');
        });
    }

    // 빈 응답은 3번까지 다시 물음. 그만/취소면 null
    async function ask(q) {
        const id = flow;
        for (let i = 0; i < 3; i++) {
            await speak(i ? '잘 못 들었어요. ' + q : q);
            if (id !== flow || !await ensureMic()) return null;
            const raw = await listen();
            if (id !== flow) return null;
            if (!raw) continue;
            const t = V.stripWake(raw) ?? raw;
            const k = V.classify(t).kind;
            return k === 'stop' || k === 'cancel' ? null : t;
        }
        await speak('음성 입력을 마칩니다');
        return null;
    }

    async function start(fn) {
        flow++;
        try {
            await fn();
        } finally {
            if (!alwaysOn && !waiter && !dict) closeMic();
        }
    }

    function stop() {
        flow++;
        speakGen++;
        armedUntil = 0;
        cutAudio();
        playing = false;
        muted = false;
        if (micVad) micVad.start();
        if (waiter) resolveWaiter('');
        setStatus(alwaysOn ? '대기 중' : '');
    }

    function visible(el) {
        return el.getClientRects().length > 0;
    }

    function labelText(l) {
        return l.textContent.replace(/\*/g, '').replace(/\(.*?\)/g, '').replace(/\s+/g, ' ').trim();
    }

    function fieldValue(el) {
        if (!el) return '';
        if (el.tagName === 'SELECT') return el.value ? el.options[el.selectedIndex].textContent.trim() : '선택 안 함';
        if (el.type === 'checkbox' || el.type === 'radio') return el.checked ? '선택됨' : '선택 안 됨';
        if (el.type === 'file') return el.files.length ? '파일 있음' : '파일 없음';
        return el.value || '비어 있음';
    }

    function tableLines(t) {
        const heads = [...t.querySelectorAll('thead th')].map(th => th.textContent.trim());
        const rows = [...t.querySelectorAll('tbody tr')].filter(visible);
        const lines = [];
        if (t.caption) lines.push(t.caption.textContent.trim());
        rows.slice(0, 20).forEach((tr, i) => {
            const cells = [...tr.children].map((td, k) => {
                const v = td.textContent.replace(/\s+/g, ' ').trim();
                return v ? (heads[k] ? heads[k] + ' ' : '') + v : '';
            }).filter(Boolean);
            lines.push((i + 1) + '행, ' + cells.join(', '));
        });
        if (rows.length > 20) lines.push('이하 ' + (rows.length - 20) + '행 생략');
        return lines;
    }

    // main 안만, 문서 순서대로
    function screenLines() {
        const lines = [];
        document.querySelectorAll('#main h1, #main h2, #main h3, #main h4, #main label[for], #main table').forEach(el => {
            if (!visible(el) || (el.tagName !== 'TABLE' && el.closest('table'))) return;
            if (el.tagName === 'TABLE') lines.push(...tableLines(el));
            else if (el.tagName === 'LABEL') lines.push(labelText(el) + ', ' + fieldValue(document.getElementById(el.htmlFor)));
            else lines.push(el.textContent.replace(/\s+/g, ' ').trim());
        });
        return lines.filter(Boolean);
    }

    async function readScreen() {
        const id = flow;
        const lines = screenLines();
        if (!lines.length) return speak('읽을 내용이 없습니다');
        for (const line of lines) {
            if (id !== flow) return;
            await speak(line, true);
        }
    }

    function whereText() {
        const link = document.querySelector('#sidebar a.sidebar-link.active');
        const h1 = document.querySelector('#main .page-toolbar h1');
        const parts = [];
        if (link) {
            const body = link.closest('.sidebar-domain-body');
            const domain = body && body.previousElementSibling.querySelector('span');
            if (domain) parts.push(domain.textContent.trim());
            parts.push(link.textContent.trim());
        }
        if (h1 && (!link || h1.textContent.trim() !== link.textContent.trim())) parts.push(h1.textContent.trim());
        return (parts.length ? parts.join(', ') : document.title) + ' 화면입니다';
    }

    function setField(el, v) {
        el.value = v;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // "회의비 (접대비)" -> "회의비"
    function optLabel(o) {
        return o.textContent.trim().replace(/\s*\(.*\)$/, '');
    }

    function linkLabel(a) {
        return (a.querySelector('span:not(.sidebar-badge)') || a).textContent.trim();
    }

    function btnLabel(b) {
        return (b.tagName === 'INPUT' ? b.value : b.textContent.trim()) || b.getAttribute('aria-label') || b.title || '';
    }

    // 후보 여럿이면 3개까지 번호로 되물음. q가 null이면 무조건 후보 전체로 되물음
    async function pick(q, els, labelOf, exact) {
        const idxs = q === null ? els.map((_, i) => i) : V.match(q, els.map(labelOf), exact);
        if (idxs.length <= 1) return idxs.length ? els[idxs[0]] : null;
        const opts = idxs.slice(0, 3).map(i => els[i]);
        const names = opts.map(labelOf);
        const ans = await ask(names.map((n, i) => (i + 1) + '번 ' + n).join(', ') + '. 몇 번이요?');
        if (!ans) return null;
        const s = ans.replace(/번.*$/, '').trim();
        const n = ORD[s] || V.money(s);
        if (n >= 1 && n <= opts.length) return opts[n - 1];
        const again = V.match(ans, names);
        return again.length === 1 ? opts[again[0]] : null;
    }

    async function nav(q, exact) {
        const el = await pick(q, [...document.querySelectorAll('#sidebar a.sidebar-link[href]')], linkLabel, exact);
        if (!el) return false;
        await speak(linkLabel(el) + ' 화면으로 이동합니다');
        location.href = el.href;
        return true;
    }

    function clickables() {
        const root = document.querySelector('.modal.show') || document.getElementById('main');
        return [...root.querySelectorAll('button, a.btn, input[type=submit]')].filter(b => !b.disabled && visible(b));
    }

    async function press(q, exact) {
        const el = await pick(q, clickables(), btnLabel, exact);
        if (!el) return false;
        const risky = (el.type === 'submit' && el.form) || /\bbtn-(outline-)?danger\b/.test(el.className)
            || el.hasAttribute('data-confirm') || /삭제|제출|상신|취소|승인|반려/.test(btnLabel(el));
        if (risky) {
            const ans = await ask(btnLabel(el) + ' 버튼을 누를까요?');
            if (!ans || V.yesno(ans) !== 'yes') {
                await speak('누르지 않았습니다');
                return true;
            }
        }
        el.click();
        return true;
    }

    async function fill(text) {
        const fields = [...document.querySelectorAll('#main label[for]')].filter(visible)
            .map(l => ({ name: labelText(l), el: document.getElementById(l.htmlFor) }))
            .filter(f => f.el && f.name && !f.el.disabled && !f.el.readOnly);
        const hit = V.splitLabel(text, fields.map(f => f.name));
        if (!hit) return false;
        const { name, el } = fields[hit.idx];
        const val = hit.value;
        let said = val;

        if (el.type === 'date') {
            const d = V.date(val, new Date());
            if (!d) {
                await speak('날짜를 못 알아들었어요. 예를 들어 어제, 9월 3일처럼 말해 주세요');
                return true;
            }
            if (el.max && d > el.max) {
                await speak(V.dateText(el.max) + ' 이후 날짜는 넣을 수 없어요');
                return true;
            }
            setField(el, d);
            said = V.dateText(d);
        } else if (/금액/.test(name) || el.inputMode === 'numeric') {
            const n = V.money(val);
            if (!n) {
                await speak('금액을 못 알아들었어요. 예를 들어 3만 5천원처럼 말해 주세요');
                return true;
            }
            setField(el, String(n));
            said = cfg.voice_amount ? n.toLocaleString() + '원' : null;
        } else if (el.tagName === 'SELECT') {
            const o = await pick(val, [...el.options].filter(o => o.value && !o.hidden), optLabel);
            if (!o) {
                await speak(name + ' 항목에 ' + val + ' 없어요');
                return true;
            }
            setField(el, o.value);
            said = optLabel(o);
        } else if (el.type === 'checkbox' || el.type === 'radio') {
            const yn = V.yesno(val);
            if (!yn) return false;
            if (el.checked !== (yn === 'yes')) el.click();
            said = yn === 'yes' ? '선택' : '해제';
        } else {
            setField(el, val);
        }
        await speak(said === null ? name + ' 입력했습니다' : name + ', ' + said);
        return true;
    }

    // 숫자패드 입력이 1.5초 멈추면 끝난 걸로 봄
    function waitTyped(el, id) {
        return new Promise(res => {
            let last = el.value, still = 0;
            const t = setInterval(() => {
                if (id !== flow) {
                    clearInterval(t);
                    return res(false);
                }
                still = el.value && el.value === last ? still + 300 : 0;
                last = el.value;
                if (still >= 1500) {
                    clearInterval(t);
                    res(true);
                }
            }, 300);
        });
    }

    async function slip(rest) {
        if (location.pathname !== SLIP_URL) {
            sessionStorage.setItem(SS_SLIP, JSON.stringify({ rest, at: Date.now() }));
            await speak('간편전표 화면으로 이동합니다');
            location.href = SLIP_URL;
            return;
        }
        const id = flow;
        const form = document.getElementById('simpleSlipForm');
        const sel = document.getElementById('purposeSelect');
        const amt = document.getElementById('amountInput');
        const dateEl = document.getElementById('slipDate');
        const opts = [...sel.options].filter(o => o.value);
        const today = V.ymd(new Date());
        const s = V.parseSlip(rest, opts.map(o => ({ label: optLabel(o), expense: o.dataset.expense === 'true' })), new Date());

        if (s.direction) document.getElementById(s.direction === '수입' ? 'btnIncome' : 'btnExpense').click();
        if (s.date && s.date > today) {
            await speak('미래 날짜는 안 돼서 오늘로 넣었어요');
            s.date = null;
        }
        setField(dateEl, s.date || today);
        if (s.partner) setField(document.getElementById('partnerInput'), s.partner);
        if (s.amount) setField(amt, String(s.amount));
        if (s.purpose !== null) setField(sel, opts[s.purpose].value);

        while (!amt.value) {
            if (cfg.voice_amount) {
                const a = await ask('금액은 얼마인가요?');
                if (a === null) return speak('전표 입력을 멈춥니다. 입력한 값은 그대로 둡니다');
                const n = V.money(a);
                if (n) setField(amt, String(n));
                else await speak('금액을 못 알아들었어요');
            } else {
                await speak('금액은 숫자패드로 입력해 주세요');
                if (!await waitTyped(amt, id)) return;
            }
        }

        while (!sel.value) {
            const a = await ask('용도는 무엇인가요?');
            if (a === null) return speak('전표 입력을 멈춥니다. 입력한 값은 그대로 둡니다');
            const vis = opts.filter(o => !o.hidden);
            const o = await pick(a, vis, optLabel);
            if (o) setField(sel, o.value);
            else await speak('용도 중에 ' + vis.slice(0, 3).map(optLabel).join(', ') + ' 같은 게 있어요');
        }

        for (const [name, role] of [['reviewer_id', '검토자'], ['approver_id', '승인자']]) {
            const el = form.querySelector('select[name=' + name + ']');
            while (!el.value) {
                const a = await ask(role + '는 누구로 할까요?');
                if (a === null) return speak('전표 입력을 멈춥니다. 입력한 값은 그대로 둡니다');
                const o = await pick(a, [...el.options].filter(o => o.value), optLabel);
                if (o) setField(el, o.value);
                else await speak(role + ' 이름을 못 찾았어요');
            }
        }

        const partner = document.getElementById('partnerInput').value;
        const parts = [
            document.getElementById('directionInput').value,
            V.dateText(dateEl.value),
            cfg.voice_amount ? amt.value + '원' : '금액은 화면에서 확인',
            partner || '거래처 없음',
            optLabel(sel.options[sel.selectedIndex]),
        ];
        const a = await ask(parts.join(', ') + '. 임시저장할까요, 제출할까요?');
        if (a && /제출/.test(a)) form.querySelector('button[name=save_mode][value=submit]').click();
        else if (a && /임시|저장/.test(a)) form.querySelector('button[name=save_mode][value=draft]').click();
        else await speak('전표 입력을 멈춥니다. 입력한 값은 그대로 둡니다');
    }

    function fieldName(el) {
        const lab = el.id && document.querySelector('label[for="' + el.id + '"]');
        if (lab) return labelText(lab);
        return el.placeholder || el.getAttribute('aria-label') || '입력칸';
    }

    function dictRoots() {
        const roots = [document.getElementById('main')];
        const modal = document.querySelector('.modal.show');
        if (modal) roots.push(modal);
        return roots;
    }

    function dictTargets() {
        const sel = 'textarea, input[type=text], input[type=search], input:not([type])';
        const seen = new Set();
        const out = [];
        dictRoots().forEach(root => {
            root.querySelectorAll(sel).forEach(el => {
                if (seen.has(el) || el.inputMode === 'numeric' || el.disabled || el.readOnly || !visible(el)) return;
                seen.add(el);
                out.push(el);
            });
        });
        return out;
    }

    function onManualEdit(e) {
        if (e.isTrusted && dict) dict.stack = [];
    }

    function resetDictTimer() {
        if (!dict) return;
        clearTimeout(dict.timer);
        dict.timer = setTimeout(() => endDict('받아쓰기를 마칩니다'), 15000);
    }

    function endDict(msg, keepMic) {
        if (!dict) return;
        clearTimeout(dict.timer);
        dict.el.classList.remove('dictating');
        dict.el.removeEventListener('input', onManualEdit);
        dict.btn.classList.remove('dictating');
        dict.btn.setAttribute('aria-pressed', 'false');
        dict = null;
        armedUntil = 0;
        if (!keepMic && !alwaysOn && !waiter) closeMic();
        if (msg) speak(msg);
        else setStatus(alwaysOn ? '대기 중' : '');
    }

    async function beginDict(el, btn) {
        if (!await ensureMic()) return;
        if (dict) endDict();
        dict = { el, btn, stack: [], queue: [] };
        el.classList.add('dictating');
        btn.classList.add('dictating');
        btn.setAttribute('aria-pressed', 'true');
        el.focus();
        el.setSelectionRange(el.value.length, el.value.length);
        el.addEventListener('input', onManualEdit);
        resetDictTimer();
        await speak(fieldName(el) + ', 말씀하세요');
    }

    function makeDictBtn(el) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'dict-btn';
        btn.setAttribute('aria-label', '받아쓰기');
        btn.setAttribute('aria-pressed', 'false');
        btn.innerHTML = '<i class="fas fa-microphone" aria-hidden="true"></i>';
        btn.addEventListener('click', () => toggleDict(el, btn));
        el.after(btn);
        return btn;
    }

    function toggleDict(el, btn) {
        if (dict && dict.el === el) return endDict('받아쓰기를 마칩니다');
        if (dict) endDict();
        start(() => beginDict(el, btn));
    }

    function injectDictButtons() {
        if (!cfg.head_mouse && !alwaysOn) return;
        dictTargets().forEach(el => {
            const next = el.nextElementSibling;
            if (next && next.classList.contains('dict-btn')) return;
            makeDictBtn(el);
        });
    }

    async function dictateCmd(arg) {
        const targets = dictTargets();
        if (!targets.length) return speak('받아쓸 칸이 없어요');
        let el;
        if (arg) {
            el = await pick(arg, targets, fieldName);
            if (!el) return speak(arg + ' 칸을 못 찾았어요');
        } else if (targets.includes(document.activeElement)) {
            el = document.activeElement;
        } else if (targets.length === 1) {
            el = targets[0];
        } else {
            el = await pick(null, targets, fieldName);
            if (!el) return;
        }
        const next = el.nextElementSibling;
        const btn = (next && next.classList.contains('dict-btn')) ? next : makeDictBtn(el);
        return beginDict(el, btn);
    }

    function dictInsert(text) {
        const t = V.punct(text);
        if (!t.trim()) return;
        const el = dict.el;
        const cur = el.value;
        const piece = (!cur || /[\s\n]$/.test(cur) ? '' : ' ') + t;
        setField(el, cur + piece);
        dict.stack.push(piece);
        setStatus(t);
        resetDictTimer();
    }

    function dictUndo() {
        if (!dict.stack.length) return speak('지울 게 없어요');
        const piece = dict.stack.pop();
        const el = dict.el;
        setField(el, el.value.slice(0, el.value.length - piece.length));
        resetDictTimer();
    }

    function dictClearSentence() {
        setField(dict.el, V.dropSentence(dict.el.value));
        dict.stack = [];
        resetDictTimer();
    }

    async function dictClearAll() {
        clearTimeout(dict.timer);
        const a = await ask('전부 지울까요?');
        if (!dict) return;
        if (a && V.yesno(a) === 'yes') {
            setField(dict.el, '');
            dict.stack = [];
        }
        resetDictTimer();
    }

    function dictNewline() {
        if (dict.el.tagName !== 'TEXTAREA') return speak('한 줄 입력칸이에요');
        setField(dict.el, dict.el.value + '\n');
        dict.stack.push('\n');
        resetDictTimer();
    }

    async function dictRead() {
        clearTimeout(dict.timer);
        const v = dict.el.value;
        await speak(v || '비어 있어요', true);
        if (!dict) return;
        resetDictTimer();
    }

    async function pickSendButton(el) {
        const form = el.form;
        let cands;
        if (form) {
            cands = [...form.querySelectorAll('button, input[type=submit]')]
                .filter(b => !b.disabled && visible(b) && (b.tagName === 'INPUT' || !b.type || b.type === 'submit'));
        } else {
            cands = [];
            let node = el.parentElement;
            while (node && !cands.length && !node.matches('.modal, #main')) {
                const btn = [...node.children].find(c => c.tagName === 'BUTTON' && !c.classList.contains('dict-btn') && !c.disabled && visible(c));
                if (btn) cands.push(btn);
                node = node.parentElement;
            }
        }
        return pick(null, cands, btnLabel);
    }

    async function dictSend() {
        const el = dict.el;
        if (!el.value.trim()) return speak('내용이 없어요');
        clearTimeout(dict.timer);
        const btn = await pickSendButton(el);
        if (!dict) return;
        if (!btn) {
            resetDictTimer();
            return speak('보낼 버튼을 못 찾았어요');
        }
        const label = btnLabel(btn);
        const q = el.value + '. ' + (label ? label + ' 할까요?' : '보낼까요?');
        const a = await ask(q);
        if (!dict) return;
        if (a && V.yesno(a) === 'yes') {
            endDict();
            btn.click();
        } else {
            await speak('보내지 않았습니다');
            resetDictTimer();
        }
    }

    async function dictHeard(raw) {
        if (!document.body.contains(dict.el) || !visible(dict.el)) {
            endDict();
            return heard(raw);
        }
        if (V.isJunk(raw)) return;
        const wake = V.stripWake(raw);
        if (wake !== null) {
            endDict(null, true);
            return heard(raw);
        }
        const c = V.dictCmd(raw);
        if (c === 'undo') return dictUndo();
        if (c === 'sentence') return dictClearSentence();
        if (c === 'clear') return dictClearAll();
        if (c === 'newline') return dictNewline();
        if (c === 'read') return dictRead();
        if (c === 'send') return dictSend();
        if (c === 'end') return endDict('받아쓰기를 마칩니다');
        dictInsert(raw);
    }

    async function run(cmd) {
        setStatus('"' + cmd + '"');
        const c = V.classify(cmd);
        if (c.kind === 'stop' || c.kind === 'cancel') return stop();
        if (c.kind === 'where') return speak(whereText());
        if (c.kind === 'read') return readScreen();
        if (c.kind === 'slip') return slip(c.rest);
        if (c.kind === 'dictate') return dictateCmd(c.arg);
        if (c.kind === 'nav') return await nav(c.arg) || speak(c.arg + ' 메뉴를 못 찾았어요');
        if (c.kind === 'click') return await press(c.arg) || speak(c.arg + ' 버튼을 못 찾았어요');
        // 동사 없는 문장: 메뉴명 완전일치 > 버튼 라벨 완전일치 > 라벨 값
        if (await nav(c.arg, true) || await press(c.arg, true) || await fill(c.arg)) return;
        return speak(HELP);
    }

    function talk() {
        if (waiter) return;
        start(async () => {
            const t = await ask('말씀하세요');
            if (t) await run(t);
        });
    }

    async function setAlways(on, silent) {
        if (on && !await ensureMic()) {
            sessionStorage.removeItem(SS_ON);
            return;
        }
        alwaysOn = on;
        sessionStorage.setItem(SS_ON, on ? '1' : '');
        onBtn.setAttribute('aria-pressed', String(on));
        fab.classList.toggle('voice-on', on);
        if (!on) {
            armedUntil = 0;
            if (!waiter && !dict) closeMic();
        }
        if (!actx || actx.state !== 'suspended') setStatus(on ? '대기 중' : '');
        injectDictButtons();
        if (!silent) await speak(on ? '항상 듣기를 켰습니다. 하이원 하고 불러 주세요' : '항상 듣기를 껐습니다');
    }

    onBtn.addEventListener('click', () => setAlways(!alwaysOn));
    document.getElementById('a11yVoiceTalk').addEventListener('click', talk);
    document.getElementById('a11yVoiceRead').addEventListener('click', () => start(readScreen));

    document.addEventListener('keydown', e => {
        if (e.altKey && e.code === 'KeyV') {
            e.preventDefault();
            talk();
        } else if (e.altKey && e.code === 'KeyR') {
            e.preventDefault();
            start(readScreen);
        } else if (e.key === 'Escape') {
            stop();
        }
    });

    document.addEventListener('a11y:change', e => {
        cfg[e.detail.key] = e.detail.val;
        if (e.detail.key === 'voice_amount' && e.detail.val) speak('헤드셋을 사용해 주세요');
    });

    // 응시/클릭한 글 한 덩어리만 읽음. 버튼, 링크는 원래 동작
    function readBox(el) {
        if (waiter || inflight) return;
        if (!el.closest('#main') || el.closest('a, button, input, select, textarea, label, [role=button]')) return;
        const box = el.closest('p, li, td, th, h1, h2, h3, h4, h5, dd, dt') || el;
        const text = box.textContent.replace(/\s+/g, ' ').trim();
        if (text) speak(text.slice(0, 200), true);
    }

    window.addEventListener('hm:dwell', e => {
        if (cfg.dwell_read) readBox(e.detail);
    });

    document.addEventListener('click', e => {
        if (cfg.click_read && e.target instanceof Element) readBox(e.target);
    });

    window.addEventListener('pagehide', () => {
        closeMic();
        cutAudio();
    });

    if (sessionStorage.getItem(SS_ON) === '1') setAlways(true, true);

    // 페이지 넘어가면서 남은 명령. 30초 지나면 버림
    const pending = JSON.parse(sessionStorage.getItem(SS_SLIP));
    sessionStorage.removeItem(SS_SLIP);
    if (pending && Date.now() - pending.at < 30000 && location.pathname === SLIP_URL) {
        start(() => slip(pending.rest));
    }

    let dictScanTimer = null;
    new MutationObserver(muts => {
        if (muts.every(m => statusEl.contains(m.target))) return;
        clearTimeout(dictScanTimer);
        dictScanTimer = setTimeout(injectDictButtons, 300);
    }).observe(document.body, { childList: true, subtree: true });
    injectDictButtons();
})();
