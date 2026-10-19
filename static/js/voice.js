(function() {
    const V = window.VoiceParse;
    const SS_ON = 'voice_on';
    const LS_GUIDED = 'voice_guided';
    const SS_SLIP = 'voice_slip';
    const SLIP_URL = '/new_slip_simple';
    const MAX_VAD_SAMPLES = 16000 * 60;
    const HELP = '잘 못 알아들었어요. 메뉴 이름이나 화면 읽어줘라고 말씀해 주세요';
    const HELP_ALL = '이렇게 말해 보세요. 출근, 퇴근, 근태 관리 열어줘, 전표입력, 연차 10월 20일부터 22일까지 신청, '
        + '세 번째 열어줘, 세 번째 읽어줘, 반려, 뒤로 가기, 아래로, 다음 페이지, 화면 읽어줘, 그만';
    const TTS_CACHE_MAX = 50;
    // 명령 후 후속 발화 대기 시간임. 인식 지연을 고려하여 발화 시작 시각 기준으로 계산함
    const FOLLOW_MS = 10000;
    const CHAT = /(니다|네요|네|어요|아요|요|죠|까|야)$/;
    const ROW_GROUP_SEL = '#main [role=group][aria-label]';

    const cfg = JSON.parse(document.getElementById('a11yInit').textContent);
    const statusEl = document.getElementById('voiceStatus');
    const onBtn = document.getElementById('a11yVoiceOn');
    const mic = document.getElementById('a11yMic');

    ort.env.wasm.numThreads = 1;

    let playing = false;
    let audioEl = null, endPlay = null;
    let ttsDown = false; // 기기 음성과 /api/tts가 모두 실패하면 해당 페이지에서는 글자로만 안내함
    let ttsCache = new Map();
    let speakGen = 0;

    let micVad = null, actx = null, micP = null;
    let alwaysOn = false;
    let muted = false;
    let inflight = false;
    let talking = false;
    let speechAt = 0;
    let armedUntil = 0; // 이 시각 이전 발화는 호출어(하이원) 없이 처리함
    let armedQuiet = false;
    let waiter = null;
    let flow = 0;
    let dict = null; // { el, btn, stack, queue }
    const pageCmds = [];
    const freeCmds = [];

    // mode: speak(안내 중, 마이크 꺼짐) / listen(발화 가능)
    function setStatus(msg, mode) {
        statusEl.dataset.mode = mode || '';
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

    const MALE_RE = /InJoon|Hyunsu|BongJin|GookMin|Minsu/i;
    const RATES = { slow: 0.85, normal: 1, fast: 1.2 };

    // 크롬 초기 로드 시 getVoices()가 빈 배열 반환. voiceschanged 1회 대기함
    function koVoices() {
        const synth = window.speechSynthesis;
        if (!synth) return Promise.resolve([]);
        const list = () => synth.getVoices().filter(v => v.lang.replace('_', '-') === 'ko-KR');
        if (synth.getVoices().length) return Promise.resolve(list());
        return new Promise(res => {
            synth.addEventListener('voiceschanged', () => res(list()), { once: true });
            setTimeout(() => res(list()), 1000);
        });
    }

    // 온라인 음성은 읽는 글이 MS/구글 서버로 전송됨. 기기에 설치된 음성만 사용함
    async function pickVoice() {
        const vs = (await koVoices()).filter(v => v.localService);
        if (!vs.length) return null;
        const male = cfg.tts_voice === 'M1';
        const rank = v => (MALE_RE.test(v.name) === male ? 0 : 10) + (/Natural/.test(v.name) ? 0 : /Google/.test(v.name) ? 1 : 2);
        return vs.sort((a, b) => rank(a) - rank(b))[0];
    }

    // 크롬은 한 번에 15초 넘게 읽으면 중단됨. 문장 단위로 나누어 읽음
    async function speakBrowser(text, voice, gen) {
        for (const s of V.sentences(text)) {
            if (gen !== speakGen) return;
            await new Promise(res => {
                const u = new SpeechSynthesisUtterance(s);
                u.lang = 'ko-KR';
                u.voice = voice;
                u.rate = RATES[cfg.tts_speed] || 1;
                u.onend = res;
                u.onerror = e => {
                    if (e.error === 'not-allowed') needGesture();
                    res();
                };
                window.speechSynthesis.speak(u);
            });
        }
    }

    // 재생 중 promise도 함께 해제해야 speak 대기 측이 멈추지 않음
    function cutAudio() {
        if (audioEl) audioEl.pause();
        if (endPlay) endPlay();
        if (window.speechSynthesis) window.speechSynthesis.cancel();
    }

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
                    ttsDown = true;
                    return;
                }
                // 400 등 해당 문장만 실패한 경우 건너뛰고 계속 진행함
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

    // 읽는 중에도 중지 명령은 수신함 (헤드셋 사용 전제)
    // 스크린리더 모드는 소리 대신 말풍선(role=status)만 갱신하고, 스크린리더가 읽는 동안 마이크를 일시 중지함
    async function speak(text, bargeIn) {
        setStatus(text, 'speak');
        if (!cfg.sr_mode) document.getElementById('srLive').textContent = text;
        if (!text) return;
        const gen = ++speakGen;
        cutAudio();
        muted = !bargeIn;
        if (muted && micVad) await micVad.pause();
        playing = true;
        if (cfg.sr_mode) {
            await new Promise(res => setTimeout(res, Math.min(text.length * 60, 5000)));
        } else {
            const voice = await pickVoice();
            if (voice) await speakBrowser(text, voice, gen);
            else if (!ttsDown) await speakSentences(text, gen);
        }
        if (gen === speakGen) {
            playing = false;
            muted = false;
            if (micVad) await micVad.start();
            if (dict) setStatus('듣는 중', 'listen');
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
                // 문장마다 트랙을 다시 잡지 않도록 스트림을 유지함
                pauseStream: async () => {},
                resumeStream: async s => s,
                onSpeechStart: onVadSpeechStart,
                onSpeechEnd: onVadSpeechEnd,
                onVADMisfire: () => { talking = false; },
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
            const msg = e && e.name === 'NotAllowedError' ? '마이크를 쓸 수 없어요' : '음성 인식을 준비하지 못했어요';
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
        talking = true;
        speechAt = Date.now();
        if (listening()) setStatus('듣는 중', 'listen');
        if (dict) resetDictTimer();
    }

    async function onVadSpeechEnd(pcm) {
        talking = false;
        if (document.hidden) return;
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
        setStatus('알아듣는 중. 잠시만요', 'busy');
        const id = flow;
        const at = speechAt;
        let text;
        try {
            text = await stt(toWav(pcm));
        } catch (e) {
            inflight = false;
            drainDictQueue();
            if (id !== flow) return;
            if (e.status === 503) {
                await speak(e.msg || '지금은 음성 인식을 쓸 수 없어요');
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
        heard(text.trim(), at);
    }

    function follow(cmd, quiet) {
        armedUntil = 0;
        start(async () => {
            if (await run(cmd, quiet) === false || !alwaysOn) return;
            armedUntil = Date.now() + FOLLOW_MS;
            armedQuiet = true;
        });
    }

    function heard(text, at) {
        if (waiter) return resolveWaiter(text);
        if (dict) return dictHeard(text);
        if (at < armedUntil) {
            const cmd = V.stripWake(text);
            if (cmd) return follow(cmd);
            if (cmd === null && V.squash(text).length > 1 && !V.isJunk(text)) return follow(text, armedQuiet);
            if (cmd === null) return setStatus(alwaysOn ? '대기 중' : '');
        }
        const cmd = V.stripWake(text);
        if (cmd === null) {
            // 읽는 중에는 호출어 없이 중지 명령만 수신함
            if (playing && V.classify(text).kind === 'stop') return stop();
            // 확인된 명령은 호출어 없이 처리하고, 그 외는 무시함
            if (alwaysOn && !V.isJunk(text) && !CHAT.test(V.squash(text)) && known(text)) return follow(text, true);
            setStatus(alwaysOn ? '대기 중' : '');
            return;
        }
        if (!cmd) {
            armedUntil = Date.now() + 5000;
            armedQuiet = false;
            speak('네');
            return;
        }
        follow(cmd);
    }

    function resolveWaiter(text) {
        const w = waiter;
        waiter = null;
        w(text);
    }

    function listen(msg) {
        return new Promise(res => {
            let timer;
            const done = text => {
                clearTimeout(timer);
                res(text);
            };
            // CPU 인식에 약 7초 소요. 발화 중이거나 인식 중이면 결과를 기다림
            const tick = () => {
                if (waiter !== done) return;
                if (talking || inflight) timer = setTimeout(tick, 1000);
                else resolveWaiter('');
            };
            timer = setTimeout(tick, 10000);
            waiter = done;
            setStatus(msg || '듣는 중. 말씀하세요', 'listen');
        });
    }

    // enterYes이면 Enter도 긍정 응답으로 처리함
    async function ask(q, enterYes) {
        const id = flow;
        let yes = false;
        const onKey = e => {
            if (e.key !== 'Enter' || e.isComposing) return;
            e.preventDefault();
            e.stopPropagation();
            yes = true;
            cutAudio();
            if (waiter) resolveWaiter('네');
        };
        if (enterYes) document.addEventListener('keydown', onKey, true);
        try {
            for (let i = 0; i < 3; i++) {
                await speak(i ? '잘 못 들었어요. ' + q : q);
                if (yes) return '네';
                if (id !== flow || !await ensureMic()) return null;
                const raw = await listen(enterYes && '듣는 중. 말씀하시거나 Enter를 누르세요');
                if (id !== flow) return null;
                if (!raw) continue;
                const t = V.stripWake(raw) ?? raw;
                const k = V.classify(t).kind;
                return k === 'stop' || k === 'cancel' ? null : t;
            }
        } finally {
            document.removeEventListener('keydown', onKey, true);
        }
        await speak('음성 입력을 끝낼게요');
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

    async function readScreen() {
        const id = flow;
        const lines = window.ScreenRead.lines(document.getElementById('main'));
        if (!lines.length) return speak('읽을 내용이 없어요');
        for (const line of lines) {
            if (id !== flow) return;
            await speak(line, true);
        }
    }

    // 중첩 도메인 메뉴(회계, 인사/급여)는 도메인명을 앞에 붙이고, 일반 섹션은 섹션명을 붙임
    function whereText() {
        const link = document.querySelector('#sidebar a.sidebar-link.active');
        const h1 = document.querySelector('#main .page-toolbar h1');
        const parts = [];
        if (link) {
            const body = link.closest('.sidebar-domain-body');
            const domain = body && body.previousElementSibling.querySelector('span');
            if (domain) {
                parts.push(domain.textContent.trim());
            } else {
                let sec = link.previousElementSibling;
                while (sec && !sec.classList.contains('sidebar-section')) sec = sec.previousElementSibling;
                if (sec && sec.textContent.trim()) parts.push(sec.textContent.trim());
            }
            parts.push(link.textContent.trim());
        }
        if (h1 && (!link || h1.textContent.trim() !== link.textContent.trim())) parts.push(h1.textContent.trim());
        return (parts.length ? parts.join(', ') : document.title) + ' 화면이에요';
    }

    function setField(el, v) {
        el.value = v;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function optLabel(o) {
        return o.textContent.trim().replace(/\s*\(.*\)$/, '');
    }

    function linkLabel(a) {
        return (a.querySelector('span:not(.sidebar-badge)') || a).textContent.trim();
    }

    function btnLabel(b) {
        return (b.tagName === 'INPUT' ? b.value : b.textContent.trim()) || b.getAttribute('aria-label') || b.title || '';
    }

    // 후보가 여럿이면 3개까지 번호로 다시 물음. q가 null이면 후보 전체로 다시 물음
    async function pick(q, els, labelOf, exact) {
        const idxs = q === null ? els.map((_, i) => i) : V.match(q, els.map(labelOf), exact);
        if (idxs.length <= 1) return idxs.length ? els[idxs[0]] : null;
        const opts = idxs.slice(0, 3).map(i => els[i]);
        const names = opts.map(labelOf);
        const ans = await ask(names.map((n, i) => (i + 1) + '번 ' + n).join(', ') + '. 몇 번이요?');
        if (!ans) return null;
        const s = ans.replace(/번.*$/, '').trim();
        const n = V.ORD[s] || V.money(s);
        if (n >= 1 && n <= opts.length) return opts[n - 1];
        const again = V.match(ans, names);
        return again.length === 1 ? opts[again[0]] : null;
    }

    function navLinks() {
        return [...document.querySelectorAll('#sidebar a.sidebar-link[href]:not(.fav-link)')].map(a => ({ href: a.href, label: linkLabel(a) }));
    }

    // 별칭이면 메뉴명을 말한 것과 동일하게 보고 바로 이동함
    async function nav(q, exact, confirm) {
        const alias = V.navAlias(q);
        const l = await pick(alias || q, navLinks(), l => l.label, exact || !!alias);
        if (!l) return false;
        if (confirm && !alias) {
            const ans = await ask(l.label + ' 화면으로 갈까요?', true);
            if (!ans || V.yesno(ans) !== 'yes') {
                await speak('이동하지 않았어요');
                return true;
            }
        }
        await speak(l.label + ' 화면으로 갈게요');
        location.href = l.href;
        return true;
    }

    function clickables() {
        const root = document.querySelector('.modal.show') || document.getElementById('main');
        return [...root.querySelectorAll('button, a.btn, input[type=submit]')].filter(b => !b.disabled && visible(b));
    }

    function hiddenClickables() {
        const root = document.querySelector('.modal.show') || document.getElementById('main');
        return [...root.querySelectorAll('button, a.btn, input[type=submit]')].filter(b => !b.disabled && !visible(b));
    }

    async function press(q, exact) {
        let el = await pick(q, clickables(), btnLabel, exact);
        if (!el) {
            const hidden = await pick(q, hiddenClickables(), btnLabel, exact);
            const sec = hidden && hidden.closest('.d-none');
            const toggle = sec && document.querySelector('.section-toggle-btn[data-target="' + sec.id + '"]');
            if (toggle) {
                toggle.click();
                el = hidden;
            }
        }
        if (!el) return false;
        const risky = (el.type === 'submit' && el.form) || /\bbtn-(outline-)?danger\b/.test(el.className)
            || el.hasAttribute('data-confirm') || /삭제|제출|상신|취소|승인|반려|탈퇴|철회|비활성화|전달/.test(btnLabel(el));
        if (risky) {
            const ans = await ask(btnLabel(el) + ' 버튼을 누를까요?', true);
            if (!ans || V.yesno(ans) !== 'yes') {
                await speak('누르지 않았어요');
                return true;
            }
            // 음성으로 이미 확인함. 네이티브 confirm/prompt와 확인 모달은 음성으로 응답 불가하므로 생략함
            if (el.hasAttribute('data-confirm')) el.dataset.confirmSkip = '1';
            const [cf, pr] = [window.confirm, window.prompt];
            window.confirm = () => true;
            window.prompt = (m, def) => def || '';
            try {
                el.click();
            } finally {
                window.confirm = cf;
                window.prompt = pr;
            }
            return true;
        }
        el.click();
        return true;
    }

    // role=group[aria-label]이 섹션명 숫자 형태라는 전제로 파싱함
    function rowGroups() {
        return [...document.querySelectorAll(ROW_GROUP_SEL)].filter(visible).map(g => {
            const m = g.getAttribute('aria-label').match(/^(.+?)\s*([0-9]+)$/);
            return m ? { section: m[1], n: Number(m[2]), el: g } : null;
        }).filter(Boolean);
    }

    function fieldGroup(el, groups) {
        const g = el.closest('[role=group][aria-label]');
        return g ? groups.find(x => x.el === g) : null;
    }

    // 같은 라벨이 행마다 반복되면 접두어, 포커스, 마지막 행 순으로 선택함
    function pickRowField(cands, groups, prefix) {
        if (prefix) {
            const hit = cands.find(f => {
                const g = fieldGroup(f.el, groups);
                return g && g.section === prefix.section && g.n === prefix.ord;
            });
            if (hit) return hit;
        }
        const cur = document.activeElement && document.activeElement.closest('[role=group]');
        const active = cur && cands.find(f => f.el.closest('[role=group]') === cur);
        return active || cands[cands.length - 1];
    }

    function known(text) {
        const c = V.classify(text);
        if (['where', 'read', 'help', 'back', 'page', 'scroll', 'voiceoff', 'search', 'clockin', 'clockout'].includes(c.kind)) return true;
        const q = c.arg || text;
        if (V.navAlias(q) || V.match(q, navLinks().map(l => l.label), true).length) return true;
        if (V.match(q, clickables().map(btnLabel), true).length) return true;
        return !!V.splitLabel(text, labelNames()) || freeCmds.some(f => f(text));
    }

    // for 없는 라벨은 같은 부모 안 첫 입력칸과 연결함. 모달이 열려 있으면 모달 기준
    function labeled() {
        const root = document.querySelector('.modal.show') || document.getElementById('main');
        return [...root.querySelectorAll('label')].filter(visible)
            .map(l => ({
                name: labelText(l),
                el: l.htmlFor ? document.getElementById(l.htmlFor)
                    : l.parentElement.querySelector('input:not([type=hidden]):not([type=file]):not([type=radio]):not([type=checkbox]), select, textarea'),
            }))
            .filter(f => f.el && f.name && !f.el.disabled && !f.el.readOnly);
    }

    function labelNames() {
        return labeled().flatMap(f => f.name.split('/').map(n => n.trim()));
    }

    async function fill(text) {
        const groups = rowGroups();
        const sections = [...new Set(groups.map(g => g.section))];
        const prefix = V.rowPrefix(text, sections);
        const body = prefix ? prefix.rest : text;

        const all = labeled();
        const byName = new Map();
        all.forEach(f => {
            if (!byName.has(f.name)) byName.set(f.name, []);
            byName.get(f.name).push(f);
        });
        const fields = [...byName.values()].map(cands => cands.length > 1 ? pickRowField(cands, groups, prefix) : cands[0]);

        // 복수 라벨은 각각 인식함
        const alts = fields.flatMap(f => [f, ...(f.name.includes('/') ? f.name.split('/').map(n => ({ ...f, name: n.trim() })) : [])]);
        const hit = V.splitLabel(body, alts.map(f => f.name));
        if (!hit) return false;
        const { name, el } = alts[hit.idx];
        let val = hit.value;
        // 라벨만 호출한 경우 다음 발화를 값으로 입력함
        if (!val) {
            el.focus();
            const ans = await ask(V.josa(name, '을', '를') + ' 말씀하세요');
            val = ans && V.valueText(ans);
            if (!val) return true;
        }
        let said = val;
        const g = fieldGroup(el, groups);
        const ctx = g ? g.section + ' ' + g.n + ', ' : '';

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
        } else if (el.type === 'month') {
            const d = V.month(val, new Date());
            if (!d) {
                await speak('월을 못 알아들었어요. 예를 들어 2020년 3월처럼 말해 주세요');
                return true;
            }
            if (el.max && d > el.max) {
                await speak(V.monthText(el.max) + ' 이후는 넣을 수 없어요');
                return true;
            }
            setField(el, d);
            said = V.monthText(d);
        } else if (el.type === 'time') {
            const t = V.time(val);
            if (!t) {
                await speak('시각을 못 알아들었어요. 예를 들어 오후 2시 반처럼 말해 주세요');
                return true;
            }
            setField(el, t);
            said = val;
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
                await speak(name + ' 항목에 ' + V.josa(val, '은', '는') + ' 없어요');
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
            said = el.list ? V.closest(val, [...el.list.options].map(o => o.value)) : val;
            setField(el, said);
        }
        await speak(said === null ? ctx + name + ' 입력했어요' : ctx + name + ', ' + said);
        return true;
    }

    function fieldName(el) {
        if (el.dataset.voiceName) return el.dataset.voiceName;
        const lab = el.id && document.querySelector('label[for="' + el.id + '"]') || el.parentElement.querySelector('label:not([for])');
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
        // 메모는 생각하며 말하는 특성상 무음 허용 시간을 길게 둠
        dict.timer = setTimeout(() => endDict('받아쓰기를 끝낼게요'), 30000);
    }

    function endDict(msg, keepMic) {
        if (!dict) return;
        clearTimeout(dict.timer);
        dict.el.classList.remove('dictating');
        dict.el.removeEventListener('input', onManualEdit);
        dict.el.removeEventListener('keydown', onDictKey);
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
        el.addEventListener('keydown', onDictKey);
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
        if (dict && dict.el === el) return endDict('받아쓰기를 끝낼게요');
        if (dict) endDict();
        return start(() => beginDict(el, btn));
    }

    function injectDictButtons() {
        if (!cfg.head_mouse && !alwaysOn && sessionStorage.getItem(SS_ON) !== '1') return;
        dictTargets().forEach(el => {
            const next = el.nextElementSibling;
            if (next && next.classList.contains('dict-btn')) return;
            makeDictBtn(el);
        });
    }

    function removeDictButtons() {
        document.querySelectorAll('.dict-btn').forEach(btn => {
            if (dict && btn === dict.btn) return;
            btn.remove();
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

    async function dictFix() {
        clearTimeout(dict.timer);
        setField(dict.el, V.dropSentence(dict.el.value));
        dict.stack = [];
        await speak('마지막 문장을 지웠어요. 다시 말씀하세요');
        resetDictTimer();
    }

    // 띄어쓰기가 달라도 찾을 수 있도록 글자 사이 공백을 허용함. 여러 곳이 일치하면 마지막 항목을 대상으로 함
    function dictReplace(from, to) {
        const pat = from.replace(/\s+/g, '').split('').map(c => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s*');
        const hits = [...dict.el.value.matchAll(new RegExp(pat, 'g'))];
        if (!hits.length) {
            resetDictTimer();
            return speak(V.josa(from, '을', '를') + ' 못 찾았어요');
        }
        const h = hits[hits.length - 1];
        const v = dict.el.value;
        setField(dict.el, v.slice(0, h.index) + to + v.slice(h.index + h[0].length));
        dict.stack = [];
        resetDictTimer();
        return speak(V.josa(from, '을', '를') + ' ' + V.josa(to, '으로', '로') + ' 바꿨어요', true);
    }

    // 한 줄 입력칸에서 엔터는 다음 칸 이동 처리. 한글 조합 중 엔터 제외
    function onDictKey(e) {
        if (e.key !== 'Enter' || e.isComposing || dict.el.tagName === 'TEXTAREA') return;
        e.preventDefault();
        dictMove();
    }

    // 대상 미지정 시 다음 받아쓰기 칸으로 이동
    function dictMove(to) {
        const all = dictTargets();
        const next = to || all[all.indexOf(dict.el) + 1];
        if (!next) return endDict('마지막 칸이에요. 받아쓰기를 끝낼게요');
        const own = next.nextElementSibling;
        const btn = own && own.classList.contains('dict-btn') ? own : dict.btn;
        endDict(null, true);
        return start(() => beginDict(next, btn));
    }

    // 행마다 칸 이름 중복. 같은 묶음 내 칸으로 한정
    function dictSwitchTarget(raw) {
        const m = V.squash(raw).match(/^(.+?)(을|를|은|는)?(말할[게께]|말하기|입력할[게께]|쓸[게께]|적을게|작성할게)(요)?$/);
        if (!m) return null;
        const g = dict.el.closest('[role=group]') || document;
        return dictTargets().find(el => el !== dict.el && g.contains(el) && V.squash(fieldName(el)) === m[1]) || null;
    }

    function dictNewline() {
        if (dict.el.tagName !== 'TEXTAREA') return dictMove();
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
            await speak('보내지 않았어요');
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
        if (c === 'end') return endDict('받아쓰기를 끝낼게요');
        if (c === 'fix') return dictFix();
        if (c === 'next') return dictMove();
        const to = dictSwitchTarget(raw);
        if (to) return dictMove(to);
        const r = V.replaceCmd(raw);
        if (r) return dictReplace(r.from, r.to);
        if (V.cmdLike(raw)) {
            endDict(null, true);
            return start(() => run(raw));
        }
        dictInsert(raw);
    }

    function scrollPage(dir) {
        const h = innerHeight * 0.8;
        if (dir === 'top') scrollTo({ top: 0, behavior: 'smooth' });
        else if (dir === 'bottom') scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
        else scrollBy({ top: dir === 'up' ? -h : h, behavior: 'smooth' });
        setStatus(alwaysOn ? '대기 중' : '');
    }

    // 목록 페이지를 이동함. 목록이 없는 화면에서 이전 페이지 명령은 뒤로 가기로 처리함
    async function pageMove(dir) {
        const a = document.querySelector('.pagination a[aria-label="' + (dir === 'next' ? '다음' : '이전') + ' 페이지"]');
        if (a && !a.closest('.disabled')) {
            await speak(dir === 'next' ? '다음 페이지로 갈게요' : '이전 페이지로 갈게요');
            location.href = a.href;
        } else if (dir === 'prev' && !a) {
            await speak('이전 화면으로 갈게요');
            history.back();
        } else {
            speak(dir === 'next' ? '마지막 페이지예요' : '첫 페이지예요');
        }
    }

    async function search(q) {
        if (await nav(q, true)) return;
        const box = document.querySelector('#main input[type=search], #main input[name=q]');
        if (!box || !box.form) return speak('검색할 곳이 없어요');
        box.value = q;
        await speak(q + ' 검색할게요');
        box.form.requestSubmit();
    }

    async function logout() {
        const a = await ask('로그아웃할까요?', true);
        if (a && V.yesno(a) === 'yes') location.href = '/logout';
        else speak('로그아웃하지 않았어요');
    }

    // 숫자패드 입력이 1.5초 멈추면 입력 종료로 처리
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
            await speak('간편전표 화면으로 갈게요');
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
                if (a === null) return speak('전표 입력을 멈출게요. 입력한 값은 그대로 둬요');
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
            if (a === null) return speak('전표 입력을 멈출게요. 입력한 값은 그대로 둬요');
            const vis = opts.filter(o => !o.hidden);
            const o = await pick(a, vis, optLabel);
            if (o) setField(sel, o.value);
            else await speak('용도 중에 ' + vis.slice(0, 3).map(optLabel).join(', ') + ' 같은 게 있어요');
        }

        for (const [name, role] of [['reviewer_id', '검토자'], ['approver_id', '승인자']]) {
            const el = form.querySelector('select[name=' + name + ']');
            while (!el.value) {
                const a = await ask(role + '는 누구로 할까요?');
                if (a === null) return speak('전표 입력을 멈출게요. 입력한 값은 그대로 둬요');
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
        else await speak('전표 입력을 멈출게요. 입력한 값은 그대로 둬요');
    }

    // 직원 기록이 없으면 서버에서 무시함
    async function clock(dir) {
        const label = dir === 'in' ? '출근' : '퇴근';
        const ans = await ask(label + '할까요?', true);
        if (!ans || V.yesno(ans) !== 'yes') return speak('취소했어요');
        await speak(label + ' 처리할게요');
        const form = document.createElement('form');
        form.method = 'post';
        form.action = '/mypage/attendance/clock-' + dir;
        form.hidden = true;
        const csrf = document.createElement('input');
        csrf.type = 'hidden';
        csrf.name = 'csrf_token';
        csrf.value = document.querySelector('meta[name="csrf-token"]').content;
        form.appendChild(csrf);
        document.body.appendChild(form);
        form.submit();
    }

    // quiet: 호출어 없는 발화임. 인식하지 못한 경우 안내를 생략함
    async function run(cmd, quiet) {
        setStatus('"' + cmd + '"');
        const c = V.classify(cmd);
        if (c.kind === 'stop' || c.kind === 'cancel') return stop();
        for (const fn of pageCmds) {
            if (await fn(cmd)) return;
        }
        if (c.kind === 'where') return speak(whereText());
        if (c.kind === 'help') return speak(HELP_ALL);
        if (c.kind === 'voiceoff') return setAlways(false);
        if (c.kind === 'back') {
            await speak('이전 화면으로 갈게요');
            return history.back();
        }
        if (c.kind === 'reload') return location.reload();
        if (c.kind === 'logout') return logout();
        if (c.kind === 'clockin') return clock('in');
        if (c.kind === 'clockout') return clock('out');
        if (c.kind === 'page') return pageMove(c.arg);
        if (c.kind === 'scroll') return scrollPage(c.arg);
        if (c.kind === 'slip') return slip(c.rest);
        // 메뉴명과 일치하면 메뉴 이동을 우선함
        if (c.kind === 'search') return await nav(cmd, true) || search(c.arg);
        if (c.kind === 'read') return readScreen();
        if (c.kind === 'dictate') return dictateCmd(c.arg);
        // 입력칸 이름이면 해당 칸으로 이동함
        if (c.kind === 'nav') return await fill(c.arg) || await nav(c.arg) || speak(c.arg + ' 메뉴를 못 찾았어요');
        if (c.kind === 'click') return await press(c.arg) || speak(c.arg + ' 버튼을 못 찾았어요');
        // 동사 없는 문장은 메뉴명 완전일치, 버튼 라벨 완전일치, 라벨 값 순으로 처리함
        if (await nav(c.arg, true) || await press(c.arg, true) || await fill(c.arg)) return;
        // 값만 말한 경우 커서가 있는 칸에 입력함
        const cur = document.activeElement;
        const val = V.valueText(c.arg);
        const chat = quiet && CHAT.test(V.squash(val));
        if (val && !chat && cur && cur.closest('#main') && cur.matches('input[type=text], input:not([type]), input[type=search]')) {
            const said = cur.list ? V.closest(val, [...cur.list.options].map(o => o.value)) : val;
            setField(cur, said);
            return speak(fieldName(cur) + ', ' + said);
        }
        if (quiet) {
            setStatus(alwaysOn ? '대기 중' : '');
            return false;
        }
        // 메뉴명과 부분적으로만 일치하면 확인 후 이동함
        if (await nav(c.arg, false, true)) return;
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
        mic.setAttribute('aria-pressed', String(on));
        mic.firstElementChild.className = 'fas ' + (on ? 'fa-microphone' : 'fa-microphone-slash');
        if (!on) {
            armedUntil = 0;
            if (!waiter && !dict) closeMic();
            if (!cfg.head_mouse) removeDictButtons();
        }
        if (!actx || actx.state !== 'suspended') setStatus(on ? '대기 중' : '');
        injectDictButtons();
        if (silent) return;
        const first = on && !localStorage.getItem(LS_GUIDED);
        if (first) localStorage.setItem(LS_GUIDED, '1');
        await speak(!on ? '음성을 껐어요' : first ? '음성을 켰어요. 하이원이라고 먼저 불러 주세요' : '음성을 켰어요');
        // 켠 직후 첫 발화는 호출어 없이 수신함
        if (on) {
            armedUntil = Date.now() + 8000;
            armedQuiet = false;
        }
    }

    onBtn.addEventListener('click', () => setAlways(!alwaysOn));
    mic.addEventListener('click', () => setAlways(!alwaysOn));
    document.getElementById('a11yVoiceTalk').addEventListener('click', talk);
    document.getElementById('a11yVoiceRead').addEventListener('click', () => start(readScreen));

    document.addEventListener('keydown', e => {
        if (e.altKey && e.code === 'KeyV') {
            e.preventDefault();
            setAlways(!alwaysOn);
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

    // 응시한 글 한 덩어리 읽음 (헤드마우스 응시용)
    function readBox(el) {
        if (waiter || inflight) return;
        if (!el || el.closest('#a11yWidget, #a11yPanel, #a11yFab, .a11y-dropdown')) return;
        if (el.closest('input, select, textarea')) return;
        const text = window.ScreenRead ? window.ScreenRead.blockText(el) : (el.innerText || el.textContent || '').trim();
        if (text) speak(text.slice(0, 300), true);
    }

    // 글씨 위를 마우스로 클릭하면 즉시 읽어줌
    function readClick(e) {
        if (!cfg.click_read) return;
        if (waiter || inflight) return;
        const target = e.target;
        if (!(target instanceof Element)) return;

        // 접근성 위젯 컨트롤 자체는 내부 announce가 있으므로 중복 낭독 방지
        if (target.closest('#a11yWidget, #a11yPanel, #a11yFab, .a11y-dropdown')) return;
        if (target.closest('script, style, noscript, audio, video')) return;

        // 클릭된 좌표의 텍스트 노드가 존재하면 그 부모 엘리먼트 우선 탐색
        let el = target;
        try {
            if (document.caretPositionFromPoint) {
                const pos = document.caretPositionFromPoint(e.clientX, e.clientY);
                if (pos && pos.offsetNode && pos.offsetNode.nodeType === 3 && pos.offsetNode.parentElement) {
                    el = pos.offsetNode.parentElement;
                }
            } else if (document.caretRangeFromPoint) {
                const range = document.caretRangeFromPoint(e.clientX, e.clientY);
                if (range && range.startContainer && range.startContainer.nodeType === 3 && range.startContainer.parentElement) {
                    el = range.startContainer.parentElement;
                }
            }
        } catch (_) {}

        // 텍스트 선택이 되어 있는 경우 선택 텍스트 우선 낭독
        const sel = window.getSelection ? window.getSelection().toString().trim() : '';
        if (sel && sel.length <= 300) {
            speak(sel, true);
            return;
        }

        const text = window.ScreenRead ? window.ScreenRead.blockText(el) : (el.innerText || el.textContent || '').trim();
        if (text) {
            speak(text.slice(0, 300), true);
        }
    }

    window.addEventListener('hm:dwell', e => {
        if (cfg.dwell_read) readBox(e.detail);
    });

    document.addEventListener('click', readClick);

    window.addEventListener('pagehide', () => {
        closeMic();
        cutAudio();
    });

    window.Voice = {
        ask: (q, enterYes) => new Promise(res => start(async () => res(await ask(q, enterYes)))),
        dictate: toggleDict,
        speak,
        stop,
        run: cmd => start(() => run(cmd)),
        // free: 호출어 없이 처리할 발화를 판별함
        onCommand: (fn, free) => {
            pageCmds.push(fn);
            if (free) freeCmds.push(free);
        },
    };

    if (sessionStorage.getItem(SS_ON) === '1') setAlways(true, true);

    // 페이지 넘어가면서 남은 전표입력 명령. 30초 지나면 폐기
    const pending = JSON.parse(sessionStorage.getItem(SS_SLIP) || 'null');
    sessionStorage.removeItem(SS_SLIP);
    if (pending && Date.now() - pending.at < 30000 && location.pathname === SLIP_URL) {
        start(() => slip(pending.rest));
    }

    // 다른 화면에서 받은 명령을 이어서 실행함. 화면별 명령 등록 후 실행하고, 새로고침 시 재실행되지 않도록 주소에서 제거함
    window.addEventListener('DOMContentLoaded', () => {
        const q = new URLSearchParams(location.search);
        const said = q.get('cmd');
        if (!said) return;
        q.delete('cmd');
        history.replaceState(null, '', location.pathname + (q.toString() ? '?' + q : ''));
        start(() => run(said));
    });

    let dictScanTimer = null;
    new MutationObserver(muts => {
        if (muts.every(m => statusEl.contains(m.target))) return;
        clearTimeout(dictScanTimer);
        dictScanTimer = setTimeout(injectDictButtons, 300);
    }).observe(document.body, { childList: true, subtree: true });
    injectDictButtons();
})();
