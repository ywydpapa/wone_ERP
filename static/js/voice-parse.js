(function(root) {
    const WAKE = ['하이원', 'hiwone', 'highone', '하이won', '하이원아'];
    const PUNCT = /[\s.,!?]/;
    const DIGIT = { 영: 0, 공: 0, 일: 1, 이: 2, 삼: 3, 사: 4, 오: 5, 육: 6, 칠: 7, 팔: 8, 구: 9 };
    const SMALL = { 십: 10, 백: 100, 천: 1000 };
    const BIG = { 만: 10000, 억: 100000000 };
    const REL = { 오늘: 0, 어제: 1, 그제: 2, 그저께: 2 };
    const KNUM = '[0-9영공일이삼사오육칠팔구십]+';
    const MD = new RegExp('^(?:(' + KNUM + ')월)?(' + KNUM + ')일$');
    const CLICK_TAIL = /\s*(을|를)?\s*(눌러\s*줘|눌러\s*주세요|눌러|클릭\s*해\s*줘|클릭)$/;
    const NAV_TAIL = /\s*(으로|로|을|를)?\s*(열어\s*줘|열어\s*주세요|열어|가\s*줘|가자|이동\s*해\s*줘|이동|보여\s*줘|화면)$/;
    const DICT_CMD = {
        undo: ['지우기', '방금거지워', '방금지워'],
        sentence: ['마지막문장지우기', '문장지우기'],
        clear: ['전부지우기', '다지우기'],
        newline: ['줄바꿈', '엔터', '다음줄'],
        read: ['다시읽어', '읽어'],
        send: ['전송', '보내기', '보내', '제출'],
        end: ['끝', '받아쓰기끝', '그만', '멈춰'],
    };
    const DICT_TAIL = /(해줘|해|줘)$/;
    const PUNCT_WORD = { 마침표: '.', 온점: '.', 쉼표: ',', 콤마: ',', 물음표: '?', 느낌표: '!' };
    const JUNK = ['시청해주셔서감사합니다', '구독과좋아요', '좋아요와구독', '알림설정', 'mbc뉴스'];

    function squash(s) {
        return s.replace(/[\s.,!?]/g, '').toLowerCase();
    }

    // 공백, 문장부호 빼고 앞에서 n글자 떼기
    function dropChars(raw, n) {
        let i = 0;
        while (n > 0 && i < raw.length) {
            if (!PUNCT.test(raw[i])) n--;
            i++;
        }
        return raw.slice(i).replace(/^[\s.,!?]+/, '').trim();
    }

    function stripWake(text) {
        const flat = squash(text);
        const w = WAKE.find(k => flat.startsWith(k));
        return w ? dropChars(text.trim(), w.length) : null;
    }

    function money(text) {
        const s = text.replace(/[\s,원]/g, '');
        if (!/^[0-9영공일이삼사오육칠팔구십백천만억]+$/.test(s)) return null;
        let total = 0, sect = 0, num = null;
        for (let i = 0; i < s.length; i++) {
            const c = s[i];
            if (/[0-9]/.test(c)) {
                let j = i;
                while (j < s.length && /[0-9]/.test(s[j])) j++;
                num = Number(s.slice(i, j));
                i = j - 1;
            } else if (c in DIGIT) {
                num = DIGIT[c];
            } else if (c in SMALL) {
                sect += (num === null ? 1 : num) * SMALL[c];
                num = null;
            } else {
                sect += num === null ? 0 : num;
                total += (sect || 1) * BIG[c];
                sect = 0;
                num = null;
            }
        }
        total += sect + (num === null ? 0 : num);
        return total > 0 ? total : null;
    }

    function ymd(d) {
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }

    function dateText(s) {
        return Number(s.slice(5, 7)) + '월 ' + Number(s.slice(8, 10)) + '일';
    }

    function date(text, today) {
        const s = squash(text).replace(/(으로|로|이요|요)$/, '');
        if (s in REL) {
            const d = new Date(today);
            d.setDate(d.getDate() - REL[s]);
            return ymd(d);
        }
        const m = s.match(MD);
        if (!m) return null;
        const mon = m[1] ? money(m[1]) : today.getMonth() + 1;
        const day = money(m[2]);
        const d = new Date(today.getFullYear(), mon - 1, day);
        return d.getMonth() === mon - 1 && d.getDate() === day ? ymd(d) : null;
    }

    function score(q, label) {
        if (!q || !label) return 0;
        if (q === label) return 1000;
        if (q.includes(label) || label.includes(q)) return 100 + Math.min(q.length, label.length);
        const pool = label.split('');
        let hit = 0;
        for (const c of q) {
            const k = pool.indexOf(c);
            if (k >= 0) {
                hit++;
                pool.splice(k, 1);
            }
        }
        return hit >= 2 && hit * 2 >= label.length ? hit : 0;
    }

    // exact면 완전일치만
    function match(q, labels, exact) {
        const sq = squash(q);
        let best = exact ? 999 : 0;
        let idxs = [];
        labels.forEach((l, i) => {
            const sc = score(sq, squash(l));
            if (sc > best) {
                best = sc;
                idxs = [i];
            } else if (sc === best && sc > 0) {
                idxs.push(i);
            }
        });
        return idxs;
    }

    function yesno(text) {
        const s = squash(text);
        if (/^(아니|아뇨|노|싫어)/.test(s)) return 'no';
        if (/^(네|넵|예|응|맞아|그래|좋아|저장|제출)/.test(s)) return 'yes';
        return null;
    }

    // squash 후 끝의 해줘/해/줘 떼고 완전일치
    function dictCmd(text) {
        const s = squash(text).replace(DICT_TAIL, '');
        for (const k of Object.keys(DICT_CMD)) {
            if (DICT_CMD[k].includes(s)) return k;
        }
        return null;
    }

    // 독립된 단어만 치환, 부호 앞 공백은 제거
    function punct(text) {
        let out = '';
        text.split(/\s+/).filter(Boolean).forEach(w => {
            if (w in PUNCT_WORD) out += PUNCT_WORD[w];
            else out += (out ? ' ' : '') + w;
        });
        return out;
    }

    // 끝 공백 무시하고 직전 .?!\n까지 남김
    function dropSentence(text) {
        const s = text.replace(/[\s.?!]+$/, '');
        const m = s.match(/^([\s\S]*[.?!\n])[^.?!\n]*$/);
        return m ? m[1] : '';
    }

    function isJunk(text) {
        const s = squash(text);
        return JUNK.some(j => s.includes(j));
    }

    // TTS용: .?!\n로 쪼개고 300자 넘으면 자름
    function sentences(text) {
        const out = [];
        text.split(/(?<=[.?!])|\n/).forEach(part => {
            let s = part.trim();
            while (s.length > 300) {
                out.push(s.slice(0, 300));
                s = s.slice(300);
            }
            if (s) out.push(s);
        });
        return out;
    }

    function classify(cmd) {
        const s = cmd.replace(/[.!?]+$/, '').trim();
        const f = squash(s);
        if (/^(그만|멈춰|중지|스톱)/.test(f)) return { kind: 'stop' };
        if (/^취소/.test(f)) return { kind: 'cancel' };
        if (/어디야|어디예요|어디지|어디에있/.test(f)) return { kind: 'where' };
        if (/^(화면)?읽어/.test(f)) return { kind: 'read' };
        if (f.startsWith('전표입력')) return { kind: 'slip', rest: dropChars(s, 4).replace(/^해\s*줘\s*/, '') };
        if (/받아쓰기$/.test(s)) return { kind: 'dictate', arg: s.replace(/받아쓰기$/, '').trim() };
        if (CLICK_TAIL.test(s)) return { kind: 'click', arg: s.replace(CLICK_TAIL, '').trim() };
        if (NAV_TAIL.test(s)) return { kind: 'nav', arg: s.replace(NAV_TAIL, '').trim() };
        return { kind: 'any', arg: s };
    }

    // 가장 긴 라벨로 시작하면 {idx, value}
    function splitLabel(text, names) {
        const f = squash(text);
        let idx = -1, len = 0;
        names.forEach((n, i) => {
            const sn = squash(n);
            if (sn.length > len && f.startsWith(sn)) {
                idx = i;
                len = sn.length;
            }
        });
        if (idx < 0) return null;
        const value = dropChars(text.trim(), len)
            .replace(/^(은|는|을|를|이|가|에|:)\s+/, '')
            .replace(/\s*(으로|로)?\s*(해\s*줘|넣어\s*줘|입력\s*해\s*줘)$/, '')
            .trim();
        return value ? { idx, value } : null;
    }

    function parseSlip(rest, purposes, today) {
        const toks = rest.split(/\s+/).filter(Boolean);
        const out = { direction: null, amount: null, date: null, purpose: null, partner: '' };

        let i = toks.findIndex(t => /^(수입|지출)/.test(t));
        if (i >= 0) {
            out.direction = toks[i].slice(0, 2);
            toks.splice(i, 1);
        }

        // "9월 3일"처럼 두 토큰짜리 먼저
        for (let n = 2; n >= 1 && !out.date; n--) {
            for (i = 0; i + n <= toks.length; i++) {
                const d = date(toks.slice(i, i + n).join(''), today);
                if (d) {
                    out.date = d;
                    toks.splice(i, n);
                    break;
                }
            }
        }

        let best = null;
        for (i = 0; i < toks.length; i++) {
            for (let j = i + 1; j <= toks.length; j++) {
                const s = toks.slice(i, j).join('');
                const v = /[0-9십백천만억]|원$/.test(s) ? money(s) : null;
                if (v && (!best || j - i > best.n)) best = { i, n: j - i, v };
            }
        }
        if (best) {
            out.amount = best.v;
            toks.splice(best.i, best.n);
        }

        const expense = out.direction !== '수입';
        const cands = purposes.map((p, k) => k).filter(k => purposes[k].expense === expense);
        for (i = 0; i < toks.length; i++) {
            const t = squash(toks[i]);
            if (t.length < 2) continue;
            const hits = cands.filter(k => {
                const l = squash(purposes[k].label);
                return l.includes(t) || t.includes(l);
            });
            if (hits.length) {
                out.purpose = hits[match(toks[i], hits.map(k => purposes[k].label))[0]];
                toks.splice(i, 1);
                break;
            }
        }

        out.partner = toks.join(' ').replace(/에서$/, '');
        return out;
    }

    const api = {
        squash, stripWake, money, date, ymd, dateText, match, yesno, classify, splitLabel, parseSlip,
        dictCmd, punct, dropSentence, isJunk, sentences,
    };
    if (typeof module !== 'undefined') module.exports = api;
    else root.VoiceParse = api;
})(this);
