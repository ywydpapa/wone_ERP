(function(root) {
    // 호출어(하이원) 목록임. 오인식 표기를 포함함
    const WAKE = ['하이원', 'hiwone', 'highone', '하이won', '하이원아', '하의원', '아이원', '하이웜'];
    const PUNCT = /[\s.,!?]/;
    const DIGIT = { 영: 0, 공: 0, 일: 1, 이: 2, 삼: 3, 사: 4, 오: 5, 육: 6, 칠: 7, 팔: 8, 구: 9 };
    const SMALL = { 십: 10, 백: 100, 천: 1000 };
    const BIG = { 만: 10000, 억: 100000000 };
    const REL = { 오늘: 0, 어제: 1, 그제: 2, 그저께: 2 };
    const NEXT = { 내일: 1, 모레: 2, 글피: 3 };
    const KNUM = '[0-9영공일이삼사오육칠팔구십]+';
    const MD = new RegExp('^(?:(' + KNUM + ')월)?(' + KNUM + ')일$');
    const YM = new RegExp('^(?:(' + KNUM + ')년)?(' + KNUM + ')월$');
    const YREL = { 올해: 0, 작년: 1, 재작년: 2 };
    const ORD = { 첫: 1, 한: 1, 하나: 1, 두: 2, 둘: 2, 세: 3, 셋: 3, 네: 4, 넷: 4, 다섯: 5 };
    const CLICK_TAIL = /\s*(을|를)?\s*(눌러\s*줘|눌러\s*주세요|눌러|클릭\s*해\s*줘|클릭)$/;
    const NAV_TAIL = /\s*(메뉴|화면|페이지)?\s*(으로|로|을|를)?\s*(열어\s*줘|열어\s*주세요|열어|펼쳐\s*줘|펼쳐\s*주세요|펼쳐|가\s*줘|가자|이동\s*해\s*줘|이동|보여\s*줘|화면)$/;
    const CLOCK_TAIL = '(하기|해줘|해주세요|해|할게요?|할래|처리(해줘|할게요?)?)?';
    const CLOCKIN_RE = new RegExp('^출근' + CLOCK_TAIL + '$');
    const CLOCKOUT_RE = new RegExp('^퇴근' + CLOCK_TAIL + '$');
    const DICT_CMD = {
        undo: ['지우기', '지워', '방금거지워', '방금지워', '삭제', '방금거삭제', '방금삭제', '되돌려', '실행취소'],
        sentence: ['마지막문장지우기', '문장지우기', '마지막문장지워', '문장지워', '문장삭제', '마지막문장삭제'],
        clear: ['전부지우기', '다지우기', '전부지워', '다지워', '모두지워', '전부삭제', '다삭제', '모두삭제', '전체삭제'],
        fix: ['수정', '고쳐', '다시', '다시말할게', '다시쓰기', '마지막문장수정', '마지막문장다시', '틀렸어', '잘못됐어'],
        newline: ['줄바꿈', '엔터', '다음줄'],
        next: ['다음칸', '다음칸으로', '다음칸으로가', '다음입력칸'],
        read: ['다시읽어', '읽어'],
        send: ['전송', '보내기', '보내', '제출'],
        end: ['끝', '받아쓰기끝', '그만', '멈춰', '완료', '종료', '끝내기', '끝내', '끝내줘', '다썼어', '끝났어'],
    };
    const DICT_TAIL = /(해줘|해주세요|하기|해|줘)$/;
    // 받아쓰기 중 짧은 지시를 판별함. 전표 메모는 대체로 길고 ~습니다로 끝남
    const CMD_LIKE = /(해줘|해주세요|하기|작성|저장|삭제|지워|수정|고쳐|바꿔|눌러줘|눌러|열어줘|열어|이동해줘|이동|가기|가줘|보여줘|검색|찾아줘)$/;
    // 끝의 조사와 동사를 제거한 후 비교함
    const KEY_TAIL = /(으로|로|을|를|에|좀)?(화면|페이지|메뉴)?(으로|로|을|를|에)?(가줘|가자|가기|가|이동해줘|이동|열어줘|열어주세요|열어|보여줘|보여주세요|보기|볼래|들어가줘|들어가|해줘|해주세요|하기|할래|해|줘|주세요)$/;
    // 메뉴명 대신 흔히 쓰는 표현임. 화면에 해당 메뉴가 있을 때만 적용함
    const NAV_ALIAS = {
        '대시보드': ['홈', '메인', '처음', '첫화면'],
        '간편전표입력': ['전표입력', '전표', '전표쓰기', '전표작성', '간편전표'],
        '전표조회': ['전표목록', '전표내역'],
        '근태 관리': ['근태', '근태현황'],
        '출근부': ['출퇴근기록'],
        '마이페이지': ['내정보', '계정', '내계정'],
        '업무': ['내업무', '할일', '할일목록'],
        '일정': ['캘린더', '달력'],
        '커뮤니티': ['게시판'],
        '급여 관리': ['급여'],
        '품목 관리': ['품목', '상품'],
        '거래처 관리': ['거래처'],
        '재고 현황': ['재고'],
        '견적 목록': ['견적', '견적서'],
        '작업지시 목록': ['작업지시'],
        '구매요청 현황': ['구매요청'],
        '발주 현황': ['발주', '발주서'],
        '세금계산서': ['전자세금계산서', '계산서'],
        '결재 문서함': ['전자결재', '결재문서함', '결재문서', '문서함'],
        '근로자 관리': ['직원', '직원목록', '근로자목록', '사원관리'],
    };

    const DOMAIN_ALIAS = {
        '회계': ['회계', '재무', '재무회계', '회계관리', 'fi'],
        '인사/급여': ['인사급여', '인사/급여', '인사', '급여관리', '인사관리', 'hr'],
        '구매/재고': ['구매재고', '구매/재고', '구매', '재고', '자재', 'mm'],
        '생산/영업': ['생산영업', '생산/영업', '생산', '영업', 'sales'],
        '업무': ['업무', 'work'],
    };

    function domainAlias(q) {
        if (!q) return null;
        const s = squash(q);
        for (const [target, aliases] of Object.entries(DOMAIN_ALIAS)) {
            if (aliases.some(a => squash(a) === s)) return target;
        }
        return null;
    }

    const FIELD_ALIAS = {
        '내용': ['글내용', '본문', '상세내용', '내용', '글'],
        '메모': ['비고', '메모'],
        '제목': ['글제목', '제목'],
    };

    function fieldAlias(q) {
        if (!q) return null;
        const s = squash(q);
        for (const [target, aliases] of Object.entries(FIELD_ALIAS)) {
            if (aliases.some(a => squash(a) === s)) return target;
        }
        return null;
    }
    // 알파벳 발음표임. 긴 발음부터 비교함
    const LETTERS = [['더블유', 'W'], ['에이치', 'H'], ['에이', 'A'], ['에프', 'F'], ['에스', 'S'], ['엑스', 'X'],
        ['와이', 'Y'], ['제트', 'Z'], ['브이', 'V'], ['케이', 'K'], ['제이', 'J'], ['아이', 'I'], ['엘', 'L'], ['엠', 'M'],
        ['엔', 'N'], ['알', 'R'], ['큐', 'Q'], ['비', 'B'], ['씨', 'C'], ['디', 'D'], ['이', 'E'], ['지', 'G'], ['오', 'O'],
        ['피', 'P'], ['티', 'T'], ['유', 'U'], ['앤', '&']];
    const PUNCT_WORD = { 마침표: '.', 온점: '.', 쉼표: ',', 콤마: ',', 물음표: '?', 느낌표: '!' };
    const JUNK = ['시청해주셔서감사합니다', '구독과좋아요', '좋아요와구독', '알림설정', 'mbc뉴스'];

    function squash(s) {
        return s.replace(/[\s.,!?]/g, '').toLowerCase();
    }

    // 공백과 문장부호를 제외하고 앞에서 n글자를 제거함
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

    function ym(y, m) {
        return y + '-' + String(m).padStart(2, '0');
    }

    function monthText(s) {
        return Number(s.slice(0, 4)) + '년 ' + Number(s.slice(5, 7)) + '월';
    }

    function month(text, today) {
        const raw = text.trim();
        const yearNow = today.getFullYear();
        const bare = raw.match(/^([0-9]{4})\s+([0-9]{1,2})$/);
        if (bare) {
            const mon = Number(bare[2]);
            return mon >= 1 && mon <= 12 ? ym(Number(bare[1]), mon) : null;
        }
        const s = squash(raw).replace(/(으로|로|이요|요)$/, '');
        for (const k in YREL) {
            if (!s.startsWith(k)) continue;
            const mm = s.slice(k.length).match(new RegExp('^(' + KNUM + ')월$'));
            if (!mm) return null;
            const mon = money(mm[1]);
            return mon >= 1 && mon <= 12 ? ym(yearNow - YREL[k], mon) : null;
        }
        const m = s.match(YM);
        if (!m) return null;
        const mon = money(m[2]);
        if (!mon || mon < 1 || mon > 12) return null;
        if (!m[1]) return ym(yearNow, mon);
        if (/^[0-9]{1,2}$/.test(m[1])) {
            const yy = yearNow % 100;
            const yraw = Number(m[1]);
            return ym(yraw <= yy ? 2000 + yraw : 1900 + yraw, mon);
        }
        return ym(money(m[1]), mon);
    }

    function parseOrd(s) {
        for (const k in ORD) {
            if (s.startsWith(k)) {
                const rest = s.slice(k.length).replace(/^\s+/, '').replace(/^번째\s*/, '');
                return [ORD[k], rest];
            }
        }
        const m = s.match(/^([0-9]+)\s*번째\s*/);
        return m ? [Number(m[1]), s.slice(m[0].length)] : null;
    }

    // 앞부분의 서수와 섹션명을 제거함
    function rowPrefix(text, sections) {
        const s = text.trim();
        const o = parseOrd(s);
        if (o) {
            const rest = o[1].replace(/^\s+/, '');
            for (const sec of sections) {
                if (rest.startsWith(sec)) {
                    return { ord: o[0], section: sec, rest: rest.slice(sec.length).replace(/^\s+/, '') };
                }
            }
        }
        for (const sec of sections) {
            if (!s.startsWith(sec)) continue;
            const after = s.slice(sec.length);
            const m = after.match(/^\s*([0-9]+)번?째?\s*/);
            if (m && m[1]) return { ord: Number(m[1]), section: sec, rest: after.slice(m[0].length) };
        }
        return null;
    }

    function score(q, label) {
        if (!q || !label) return 0;
        if (q === label || key(q) === key(label)) return 1000;
        if (q.includes(label) || label.includes(q)) return 100 + Math.min(q.length, label.length);
        const pool = label.split('');
        let hit = 0;
        // 동사 꼬리를 제외하고 계산함. 동사 끝 글자가 다른 메뉴명에 잘못 매칭되는 것을 방지함
        for (const c of key(q)) {
            const k = pool.indexOf(c);
            if (k >= 0) {
                hit++;
                pool.splice(k, 1);
            }
        }
        return hit >= 2 && hit * 2 >= label.length ? hit : 0;
    }

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

    function cmdLike(text) {
        const n = text.trim().split(/\s+/).length;
        if (n > 4) return false;
        return CMD_LIKE.test(squash(text)) || (n <= 3 && !['any', 'read'].includes(classify(text).kind));
    }

    // A를 B로 바꾸는 명령을 파싱함
    function replaceCmd(text) {
        const m = text.trim().replace(/[.!?]+$/, '').match(/^(.+?)\s*(을|를)\s*(.+?)\s*(으로|로)\s*(바꿔|고쳐|수정)/);
        return m ? { from: m[1], to: m[3] } : null;
    }

    function key(text) {
        const s = squash(text);
        return s.replace(KEY_TAIL, '') || s;
    }

    function navAlias(text) {
        const k = key(text);
        return Object.keys(NAV_ALIAS).find(l => key(l) === k || NAV_ALIAS[l].includes(k)) || null;
    }

    function dictCmd(text) {
        const s = squash(text).replace(DICT_TAIL, '');
        for (const k of Object.keys(DICT_CMD)) {
            if (DICT_CMD[k].includes(s)) return k;
        }
        return null;
    }

    function punct(text) {
        let out = '';
        text.split(/\s+/).filter(Boolean).forEach(w => {
            if (w in PUNCT_WORD) out += PUNCT_WORD[w];
            else out += (out ? ' ' : '') + w;
        });
        return out;
    }

    function dropSentence(text) {
        const s = text.replace(/[\s.?!]+$/, '');
        const m = s.match(/^([\s\S]*[.?!\n])[^.?!\n]*$/);
        return m ? m[1] : '';
    }

    function isJunk(text) {
        const s = squash(text);
        // 무음 구간에서 반복 출력되는 결과를 제외함
        const words = text.replace(/[.,!?]/g, ' ').split(/\s+/).filter(Boolean);
        return JUNK.some(j => s.includes(j)) || words.some(w => words.filter(x => x === w).length >= 3);
    }

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

    function classify(cmd) {
        const s = cmd.replace(/[.!?]+$/, '').trim();
        const f = squash(s);
        if (/^(음성|듣기|마이크|항상듣기)(꺼|끄기|끄자|그만|종료|중지)/.test(f)) return { kind: 'voiceoff' };
        if (/^(그만|멈춰|중지|스톱)/.test(f)) return { kind: 'stop' };
        if (/^취소/.test(f)) return { kind: 'cancel' };
        if (/어디야|어디예요|어디지|어디에있/.test(f)) return { kind: 'where' };
        // STT 오인식 표기(일거)를 포함함
        if (/^(화면(을|를)?)?(좀)?(읽어|일거)/.test(f)) return { kind: 'read' };
        if (/^(도움말|명령어|사용법|뭐라고말해|뭐할수있)/.test(f)) return { kind: 'help' };
        if (/^(뒤로|이전화면|전화면|돌아가)/.test(f)) return { kind: 'back' };
        if (/^새로고침/.test(f)) return { kind: 'reload' };
        if (/^로그아웃/.test(f)) return { kind: 'logout' };
        if (/^(사이드바|주\s*메뉴|메뉴창|네비게이션|메뉴)(를|을)?\s*(열어|열어줘|열어주세요|펼쳐|펼쳐줘|펼쳐주세요|보여줘|열기)/.test(f)) return { kind: 'sidebar', arg: 'open' };
        if (/^(사이드바|주\s*메뉴|메뉴창|네비게이션|메뉴)(를|을)?\s*(닫아|닫아줘|닫아주세요|접어|접어줘|접어주세요|숨겨|숨겨줘|닫기|접기)/.test(f)) return { kind: 'sidebar', arg: 'close' };
        if (/^(사이드바|주\s*메뉴|메뉴)\s*(토글|접기펼치기)/.test(f)) return { kind: 'sidebar', arg: 'toggle' };
        if (/^(메뉴\s*(검색|찾기|찾아))/.test(f)) return { kind: 'menu_find' };
        if (CLOCKIN_RE.test(f)) return { kind: 'clockin' };
        if (CLOCKOUT_RE.test(f)) return { kind: 'clockout' };
        if (/^다음페이지/.test(f)) return { kind: 'page', arg: 'next' };
        if (/^(이전페이지|앞페이지)/.test(f)) return { kind: 'page', arg: 'prev' };
        if (/^(맨위|제일위|맨처음으로)/.test(f)) return { kind: 'scroll', arg: 'top' };
        if (/^(맨아래|맨밑|제일아래|맨끝)/.test(f)) return { kind: 'scroll', arg: 'bottom' };
        if (/^(아래로|밑으로|내려|스크롤내려|스크롤다운)/.test(f)) return { kind: 'scroll', arg: 'down' };
        if (/^(위로|올려|스크롤올려|스크롤업)/.test(f)) return { kind: 'scroll', arg: 'up' };
        const dm = s.match(/^(.+?)\s*(을|를)?\s*(받아쓰기|받아써|입력\s*해\s*줘|입력\s*해\s*주세요|입력|작성\s*해\s*줘|작성\s*해\s*주세요|작성|적어\s*줘|적어\s*주세요|적어|써\s*줘|써\s*주세요|써)$/);
        if (dm) {
            const target = dm[1].trim();
            if (/^(글\s*내용|내용|본문|메모|글|의견|사유|설명|비고|댓글|답장|후기)$/.test(target) || /받아쓰기|받아써/.test(s)) {
                return { kind: 'dictate', arg: target };
            }
        }
        if (/^받아쓰기$/.test(f)) return { kind: 'dictate', arg: '' };
        if (/받아쓰기$/.test(s)) return { kind: 'dictate', arg: s.replace(/받아쓰기$/, '').trim() };
        if (f.startsWith('전표입력')) return { kind: 'slip', rest: dropChars(s, 4).replace(/^해\s*줘\s*/, '') };
        if (CLICK_TAIL.test(s)) return { kind: 'click', arg: s.replace(CLICK_TAIL, '').trim() };
        if (NAV_TAIL.test(s)) return { kind: 'nav', arg: s.replace(NAV_TAIL, '').trim() };
        const sm = s.match(/^(.+?)\s*(을|를)?\s*(검색|찾아|찾기)(\s*(해|줘|주세요|봐))*$/);
        if (sm) return { kind: 'search', arg: sm[1].trim() };
        return { kind: 'any', arg: s };
    }

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
        // 값이 비어 있으면 라벨만 호출한 것으로 처리함
        return { idx, value: valueText(dropChars(text.trim(), len).replace(/^(은|는|을|를|이|가|에|:)\s+/, '')) };
    }

    function valueText(v) {
        const s = v.trim().replace(/[.,!?]+$/, '')
            .replace(/\s*(으로|로)\s*(해|넣어|바꿔|입력\s*해|적어|써)\s*(줘|주세요)?$/, '')
            .replace(/\s*(을|를)?\s*(입력|작성)\s*(해)?\s*(줘|주세요|하기|할게)?$/, '')
            .replace(/\s*으로$/, '')
            .trim();
        return /^(입력|작성|칸|란|쓰기|적기|선택)?$/.test(s) ? '' : s;
    }

    const CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
    const JUNG = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ';
    const JONG = ['', 'ㄱ', 'ㄲ', 'ㄱㅅ', 'ㄴ', 'ㄴㅈ', 'ㄴㅎ', 'ㄷ', 'ㄹ', 'ㄹㄱ', 'ㄹㅁ', 'ㄹㅂ', 'ㄹㅅ', 'ㄹㅌ', 'ㄹㅍ', 'ㄹㅎ',
        'ㅁ', 'ㅂ', 'ㅂㅅ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ'];

    // 발음 비교용 자모열임. 초성 ㅇ은 제외함
    function jamo(s) {
        let out = '';
        for (const ch of s.replace(/\s/g, '').toUpperCase()) {
            const c = ch.charCodeAt(0) - 0xAC00;
            if (c < 0 || c > 11171) {
                out += ch;
                continue;
            }
            const cho = CHO[Math.floor(c / 588)];
            out += (cho === 'ㅇ' ? '' : cho) + JUNG[Math.floor(c % 588 / 28)] + JONG[c % 28];
        }
        return out;
    }

    function dist(a, b) {
        let prev = [...Array(b.length + 1).keys()];
        for (let i = 1; i <= a.length; i++) {
            const cur = [i];
            for (let j = 1; j <= b.length; j++) {
                cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
            }
            prev = cur;
        }
        return prev[b.length];
    }

    function spell(k) {
        let out = '';
        while (k) {
            const l = LETTERS.find(([r]) => k.startsWith(r));
            if (!l) return null;
            out += l[1];
            k = k.slice(l[0].length);
        }
        return out;
    }

    // 목록 중 발음이 가장 가까운 항목으로 보정함
    function closest(v, opts) {
        const k = squash(v).replace(/(.{2,})님$/, '$1');
        const sp = spell(k);
        const same = opts.find(o => squash(o) === k || (sp && o.toUpperCase() === sp));
        if (same) return same;
        const j = jamo(k);
        let best = v, bd = Math.max(1, Math.floor(j.length / 3)) + 1;
        for (const o of opts) {
            const d = dist(j, jamo(o));
            if (d < bd) {
                best = o;
                bd = d;
            }
        }
        return best;
    }

    const ROW_RE = /^(.+?)(번째)?(거|것|항목|문서|행|줄|메시지|메세지|업무)?(을|를)?(열어|열기|읽어|읽기|선택)/;

    function rowCmd(text) {
        const m = squash(text).match(ROW_RE);
        if (!m) return null;
        let ord = null;
        if (/^(마지막|맨끝|맨아래)$/.test(m[1])) ord = -1;
        else if (m[2] && m[1] in ORD) ord = ORD[m[1]];
        else if (m[2] && /^[0-9]+$/.test(m[1])) ord = Number(m[1]);
        if (!ord) return null;
        return { ord, act: /^읽/.test(m[5]) ? 'read' : 'open' };
    }

    const LEAVE_TYPES = [['반차', 'half_day'], ['연차', 'annual'], ['병가', 'sick'], ['경조', 'family_event'], ['공가', 'official'], ['기타휴가', 'other'], ['휴가', null]];
    // 메뉴 이동 발화와 구분하기 위해 신청 동사 필수
    const LEAVE_VERB = /(신청|쓸[게께래]|써줘|써요|쓰고싶|쓸래|낼[게께래]|내줘|내고싶|올려줘)/;
    const DATE_TOK = new RegExp('오늘|내일|모레|글피|(?:' + KNUM + '월)?' + KNUM + '일', 'g');

    // 월 생략 날짜가 지났으면 다음 달, 월 지정 날짜가 지났으면 내년으로 봄
    function ahead(tok, today) {
        if (tok in NEXT) {
            const dt = new Date(today);
            dt.setDate(dt.getDate() + NEXT[tok]);
            return ymd(dt);
        }
        const d = date(tok, today);
        if (!d) return null;
        if (d >= ymd(today) || tok in REL) return d;
        const dt = new Date(d);
        if (tok.includes('월')) dt.setFullYear(dt.getFullYear() + 1);
        else dt.setMonth(dt.getMonth() + 1);
        return ymd(dt);
    }

    function leaveCmd(text, today) {
        const s = squash(text);
        if (!LEAVE_VERB.test(s) || /(열어|보여|가줘|이동)/.test(s)) return null;
        const t = LEAVE_TYPES.find(([k]) => s.includes(k));
        if (!t) return null;
        // 월 없는 N일은 뒤에 부터/까지/에가 붙어야 날짜. 나머지는 일수로 봄
        const toks = [];
        let dur = null;
        for (const m of s.matchAll(DATE_TOK)) {
            const tail = s.slice(m.index + m[0].length);
            if (m[0] in REL || m[0] in NEXT || m[0].includes('월') || /^(부터|까지|에|날)/.test(tail)) toks.push(m[0]);
            else dur = money(m[0].replace(/일$/, ''));
        }
        const start = toks[0] ? ahead(toks[0], today) : null;
        let end = toks[1] ? ahead(toks[1], today) : start;
        // 종료일 월 생략 시 시작일 기준으로 해석함
        if (start && toks[1] && !toks[1].includes('월') && !(toks[1] in REL) && !(toks[1] in NEXT)) {
            const dt = new Date(start.slice(0, 8) + '01');
            const day = money(toks[1].replace(/일$/, ''));
            dt.setDate(day);
            if (ymd(dt) < start) dt.setMonth(dt.getMonth() + 1, day);
            end = ymd(dt);
        }
        if (start && !toks[1] && dur > 1) {
            const dt = new Date(start);
            dt.setDate(dt.getDate() + dur - 1);
            end = ymd(dt);
        }
        const half = /오전/.test(s) ? 'am' : /오후/.test(s) ? 'pm' : null;
        return { type: t[1], half, start, end, dur };
    }

    // 주말 제외 일수. 공휴일은 화면에서 수정함
    function workDays(a, b) {
        let n = 0;
        for (const d = new Date(a); ymd(d) <= b; d.setDate(d.getDate() + 1)) {
            if (d.getDay() % 6) n++;
        }
        return n;
    }

    function rejectCmd(text) {
        return /^반려(해|처리|할|하자|하기|$)/.test(squash(text));
    }

    // 받침에 따라 조사를 선택함. ㄹ받침 뒤에서는 으로 대신 로를 사용함
    function josa(w, a, b) {
        const c = w.charCodeAt(w.length - 1) - 0xAC00;
        if (c < 0 || c > 11171) return w + b;
        const jong = c % 28;
        return w + (jong && !(a === '으로' && jong === 8) ? a : b);
    }

    // 고유어 시각 표현임. 긴 표현부터 비교함
    const HOUR_WORD = [['열한', 11], ['열두', 12], ['다섯', 5], ['여섯', 6], ['일곱', 7], ['여덟', 8], ['아홉', 9],
        ['한', 1], ['두', 2], ['세', 3], ['네', 4], ['열', 10]];
    const TIME_RE = new RegExp('(오전|오후|아침|저녁|밤)?((?:[0-9]+)|' + HOUR_WORD.map(h => h[0]).join('|') + '|' + KNUM + ')시(반|(' + KNUM + ')분)?');

    function hourNum(s) {
        if (/^[0-9]+$/.test(s)) return Number(s);
        const w = HOUR_WORD.find(h => h[0] === s);
        return w ? w[1] : money(s);
    }

    // 오전/오후 생략 시 1~6시는 오후로 봄. 근무 시간 기준
    function timeAt(m) {
        let h = hourNum(m[2]);
        const min = m[3] === '반' ? 30 : m[4] ? money(m[4]) : 0;
        if (h === null || h > 24 || min === null || min > 59) return null;
        if (/오후|저녁|밤/.test(m[1] || '') && h < 12) h += 12;
        else if (!m[1] && h >= 1 && h <= 6) h += 12;
        return String(h % 24).padStart(2, '0') + ':' + String(min).padStart(2, '0');
    }

    function time(text) {
        const s = squash(text);
        const hm = s.match(/^([0-9]{1,2}):([0-9]{2})$/);
        if (hm) return Number(hm[1]) < 24 && Number(hm[2]) < 60 ? hm[1].padStart(2, '0') + ':' + hm[2] : null;
        const m = s.match(TIME_RE);
        return m ? timeAt(m) : null;
    }

    function timeRange(text) {
        const s = squash(text);
        const m = s.match(new RegExp(TIME_RE.source + '(?:부터|에서)' + TIME_RE.source + '까지'));
        if (!m) return null;
        return [timeAt(m.slice(0, 5)), timeAt([m[0], ...m.slice(5, 9)])];
    }

    // 본인 확인용. 숫자 6자리/8자리 또는 년월일 표현
    function birthDate(text) {
        let s = squash(text).replace(/(이요|요|입니다|이에요|예요)$/, '');
        if (/^[영공일이삼사오육칠팔구]+$/.test(s)) s = [...s].map(c => DIGIT[c]).join('');
        let y, mo, d;
        const dig = s.match(/^([0-9]{2}|[0-9]{4})([0-9]{2})([0-9]{2})$/);
        const ko = s.match(new RegExp('^(' + KNUM + ')년(' + KNUM + ')월(' + KNUM + ')일$'));
        if (dig) [y, mo, d] = [Number(dig[1]), Number(dig[2]), Number(dig[3])];
        else if (ko) [y, mo, d] = [money(ko[1]), money(ko[2]), money(ko[3])];
        else return null;
        if (y === null || mo === null || d === null) return null;
        if (y < 100) y += y <= new Date().getFullYear() % 100 ? 2000 : 1900;
        const dt = new Date(y, mo - 1, d);
        return dt.getMonth() === mo - 1 && dt.getDate() === d ? ymd(dt) : null;
    }

    const LOOK_VERB = /(조회|보여|읽어|알려|얼마|확인|볼래|보기|열어)/;

    function payslipCmd(text, today) {
        const s = squash(text);
        if (!/(급여명세서|명세서|월급|급여)/.test(s) || !LOOK_VERB.test(s) || /(관리|대장|원천)/.test(s)) return null;
        const m = s.match(new RegExp('(?:(' + KNUM + ')년)?(' + KNUM + ')월'));
        return { ym: m ? month((m[1] ? m[1] + '년' : '') + m[2] + '월', today) : null };
    }

    function withholdCmd(text) {
        const s = squash(text);
        return /원천징수/.test(s) && LOOK_VERB.test(s);
    }

    const JOURNAL_CAT = [['데이터', 'data_entry'], ['입력', 'data_entry'], ['개발', 'development'], ['유지보수', 'development'],
        ['디자인', 'design'], ['기획', 'design'], ['고객', 'support'], ['운영', 'support'], ['회의', 'meeting'], ['미팅', 'meeting'],
        ['모니터링', 'monitoring'], ['문서', 'document'], ['기타', 'other']];
    const VOL_RE = new RegExp('(' + KNUM + '|[0-9]+)(건|페이지|개|시간|장)');

    function journalStatus(text) {
        const s = squash(text);
        if (/(지연|보류|밀렸|못끝)/.test(s)) return 'delay';
        if (/(진행중|하는중|진행|덜)/.test(s)) return 'progress';
        if (/(완료|끝났|끝냈|다했)/.test(s)) return 'done';
        return null;
    }

    function journalCat(text) {
        const s = squash(text);
        const c = JOURNAL_CAT.find(([k]) => s.includes(k));
        return c ? c[1] : null;
    }

    function journalCmd(text) {
        const s = squash(text);
        const m = s.match(/(업무일지|일지|업무보고|일일보고)(를|을)?(써|작성|쓸|등록|남겨|쓰기|적어)/);
        if (!m) return null;
        const rest = s.replace(m[0], '');
        const range = timeRange(rest);
        const span = range && rest.match(new RegExp(TIME_RE.source + '(?:부터|에서)' + TIME_RE.source + '까지'))[0];
        const left = span ? rest.replace(span, '') : rest;
        const vol = left.match(VOL_RE);
        return {
            cat: journalCat(left),
            vol: vol ? money(vol[1]) : null,
            unit: vol ? vol[2] : null,
            start: range ? range[0] : null,
            end: range ? range[1] : null,
            status: journalStatus(left),
        };
    }

    const MSG_RE = /(메시지|메세지|쪽지|문자)/;
    const MANAGER_RE = /^(담당자|담당|매니저|담당매니저|관리자|팀장|팀장님|선생님|담당자님|매니저님|관리자님)$/;

    // 대상 생략 시 to는 null. 보내기 동사 또는 대상 지목이 있어야 보내기로 봄
    function messageCmd(text) {
        const s = squash(text);
        if (!MSG_RE.test(s) || /(메시지함|읽어|열어|있어|왔어|확인)/.test(s)) return null;
        const to = s.match(/^(.+?)(한테|에게|께)/);
        if (!to && !/(보내|전송|남겨|남길|쓸래|쓸게|써줘)/.test(s)) return null;
        if (!to) return { to: null };
        return { to: MANAGER_RE.test(to[1]) ? 'manager' : to[1].replace(/님$/, '') };
    }

    function inboxCmd(text) {
        const s = squash(text);
        return /^(새|안읽은|받은)?(메시지|메세지|쪽지)(가|이|를|을)?(있어|있나|왔어|읽어|확인)/.test(s);
    }

    function replyCmd(text) {
        return /^답장(을|를)?(해|보내|쓸|할|하기|작성|써|$)/.test(squash(text));
    }

    function taskSubmitCmd(text) {
        return /^(검토요청|업무완료|작업완료|완료했어|다했어|완료처리|업무끝)/.test(squash(text));
    }

    function helpCmd(text) {
        return /(도움요청|도와줘|도와주세요|도움이필요|도움필요|도움요청해)/.test(squash(text));
    }

    function commentCmd(text) {
        const s = squash(text);
        return /(댓글|소통)/.test(s) && /(남겨|달아|쓸|등록|작성|써)/.test(s);
    }

    const CERT_TYPES = [['재직', '재직증명서'], ['경력', '경력증명서'], ['소득', '소득금액증명']];
    const CERT_PURPOSE = [['은행', '은행제출용'], ['관공서', '관공서제출용'], ['주민센터', '관공서제출용'], ['공공기관', '관공서제출용'],
        ['개인', '개인보관용'], ['보관', '개인보관용'], ['기타', '기타']];

    function certType(text) {
        const s = squash(text);
        const t = CERT_TYPES.find(([k]) => s.includes(k));
        return t ? t[1] : null;
    }

    function certPurpose(text) {
        const s = squash(text);
        const p = CERT_PURPOSE.find(([k]) => s.includes(k));
        return p ? p[1] : null;
    }

    function certCmd(text) {
        const s = squash(text);
        if (!/증명/.test(s) || !/(발급|떼|뽑|신청|출력)/.test(s) || /(내역|목록|현황)/.test(s)) return null;
        return { type: certType(s), purpose: certPurpose(s.replace(/(재직|경력|소득금액)증명서?/, '')) };
    }

    const ACCOM_CAT = [['보조', '보조공학기기'], ['기기', '보조공학기기'], ['근로지원', '근로지원인'], ['지원인', '근로지원인'],
        ['작업환경', '작업환경 조정'], ['환경', '작업환경 조정']];

    function accomCat(text) {
        const s = squash(text);
        const c = ACCOM_CAT.find(([k]) => s.includes(k));
        return c ? c[1] : null;
    }

    function accomCmd(text) {
        const s = squash(text);
        if (!/(편의지원|보조공학|보조기기|근로지원인|작업환경)/.test(s) || !/(신청|요청)/.test(s) || /(내역|목록|현황)/.test(s)) return null;
        return { cat: accomCat(s), urgency: /(긴급|급해|급하|빨리)/.test(s) ? 'urgent' : null };
    }

    const api = {
        squash, stripWake, money, date, ymd, dateText, match, yesno, classify, splitLabel, parseSlip,
        dictCmd, cmdLike, replaceCmd, key, navAlias, domainAlias, fieldAlias, punct, dropSentence, isJunk, sentences, month, monthText, rowPrefix, ORD, josa, valueText, closest,
        rowCmd, leaveCmd, workDays, rejectCmd,
        time, timeRange, birthDate, payslipCmd, withholdCmd, journalCmd, journalCat, journalStatus, messageCmd, inboxCmd, replyCmd,
        taskSubmitCmd, helpCmd, commentCmd, certCmd, certType, certPurpose, accomCmd, accomCat,
    };
    if (typeof module !== 'undefined') module.exports = api;
    else root.VoiceParse = api;
})(this);
