const test = require('node:test');
const assert = require('node:assert');
const V = require('../../static/js/voice-parse.js');

const today = new Date(2026, 8, 28);

test('웨이크워드 미인식', () => {
    assert.strictEqual(V.stripWake('하이 ERP 출근부 열어줘'), null);
    assert.strictEqual(V.stripWake('오늘 점심 뭐 먹지'), null);
});

test('금액', () => {
    assert.strictEqual(V.money('3만원'), 30000);
    assert.strictEqual(V.money('삼만원'), 30000);
    assert.strictEqual(V.money('3만 5천원'), 35000);
    assert.strictEqual(V.money('35,000원'), 35000);
    assert.strictEqual(V.money('만 이천'), 12000);
    assert.strictEqual(V.money('십만'), 100000);
    assert.strictEqual(V.money('백오십만'), 1500000);
    assert.strictEqual(V.money('1억 2천만'), 120000000);
    assert.strictEqual(V.money('스타벅스'), null);
    assert.strictEqual(V.money(''), null);
});

test('날짜', () => {
    assert.strictEqual(V.date('오늘', today), '2026-09-28');
    assert.strictEqual(V.date('어제로', today), '2026-09-27');
    assert.strictEqual(V.date('그저께', today), '2026-09-26');
    assert.strictEqual(V.date('9월 3일', today), '2026-09-03');
    assert.strictEqual(V.date('3일', today), '2026-09-03');
    assert.strictEqual(V.date('구월 십일일', today), '2026-09-11');
    assert.strictEqual(V.date('2월 30일', today), null);
    assert.strictEqual(V.date('내일', today), null);
    assert.strictEqual(V.dateText('2026-09-03'), '9월 3일');
});

test('연월', () => {
    assert.strictEqual(V.month('2020년 3월', today), '2020-03');
    assert.strictEqual(V.month('2020 3', today), '2020-03');
    assert.strictEqual(V.month('20년 3월', today), '2020-03');
    assert.strictEqual(V.month('40년 3월', today), '1940-03');
    assert.strictEqual(V.month('올해 3월', today), '2026-03');
    assert.strictEqual(V.month('작년 3월', today), '2025-03');
    assert.strictEqual(V.month('재작년 3월', today), '2024-03');
    assert.strictEqual(V.month('3월', today), '2026-03');
    assert.strictEqual(V.month('내일', today), null);
    assert.strictEqual(V.month('13월', today), null);
    assert.strictEqual(V.monthText('2020-03'), '2020년 3월');
});

test('매칭', () => {
    const menus = ['근태 관리', '일일 입력', '출근부', '근로자 관리'];
    assert.deepStrictEqual(V.match('근태', menus), [0]);
    assert.deepStrictEqual(V.match('관리', menus), [0, 3]);
    assert.deepStrictEqual(V.match('출근부', menus, true), [2]);
    assert.deepStrictEqual(V.match('출근', menus, true), []);
    assert.deepStrictEqual(V.match('회의 비', ['소모품', '회의비']), [1]);
});

test('예 아니오', () => {
    assert.strictEqual(V.yesno('네 맞아요'), 'yes');
    assert.strictEqual(V.yesno('제출'), 'yes');
    assert.strictEqual(V.yesno('아니요'), 'no');
    assert.strictEqual(V.yesno('글쎄'), null);
});

test('명령 분류', () => {
    assert.deepStrictEqual(V.classify('그만'), { kind: 'stop' });
    assert.deepStrictEqual(V.classify('취소'), { kind: 'cancel' });
    assert.deepStrictEqual(V.classify('지금 어디야?'), { kind: 'where' });
    assert.deepStrictEqual(V.classify('화면 읽어줘'), { kind: 'read' });
    assert.deepStrictEqual(V.classify('근태 관리 열어줘'), { kind: 'nav', arg: '근태 관리' });
    assert.deepStrictEqual(V.classify('근태 관리로 가줘'), { kind: 'nav', arg: '근태 관리' });
    assert.deepStrictEqual(V.classify('임시저장 눌러줘'), { kind: 'click', arg: '임시저장' });
    assert.deepStrictEqual(V.classify('거래처 스타벅스'), { kind: 'any', arg: '거래처 스타벅스' });
    assert.deepStrictEqual(V.classify('전표입력 3만원 지출'), { kind: 'slip', rest: '3만원 지출' });
    assert.deepStrictEqual(V.classify('전표 입력해줘'), { kind: 'slip', rest: '' });
});

test('공통 명령', () => {
    const cases = {
        '뒤로 가기': ['back'], '이전 화면으로': ['back'], '돌아가': ['back'],
        '다음 페이지': ['page', 'next'], '이전 페이지로 가줘': ['page', 'prev'],
        '아래로': ['scroll', 'down'], '스크롤 내려줘': ['scroll', 'down'], '위로 올려줘': ['scroll', 'up'],
        '맨 위로': ['scroll', 'top'], '맨 아래로 가줘': ['scroll', 'bottom'],
        '새로고침': ['reload'], '로그아웃 해줘': ['logout'], '도움말': ['help'], '뭐라고 말해야 돼': ['help'],
        '거래처 검색해줘': ['search', '거래처'], '스타벅스를 찾아줘': ['search', '스타벅스'],
        '화면 읽어줘': ['read'], '화면을 읽어 줘': ['read'], '지금 어디야': ['where'],
    };
    for (const [said, [kind, arg]] of Object.entries(cases)) {
        const c = V.classify(said);
        assert.strictEqual(c.kind, kind, said);
        if (arg) assert.strictEqual(c.arg, arg, said);
    }
});

test('출퇴근', () => {
    for (const t of ['출근', '출근하기', '출근해줘', '출근해주세요', '출근할게요', '출근처리']) {
        assert.strictEqual(V.classify(t).kind, 'clockin', t);
    }
    for (const t of ['퇴근', '퇴근하기', '퇴근해줘', '퇴근 처리', '퇴근 처리해줘', '퇴근할래']) {
        assert.strictEqual(V.classify(t).kind, 'clockout', t);
    }
    // 메뉴명(출근부)과는 구분되어야 함
    assert.strictEqual(V.classify('출근부').kind, 'any');
    assert.strictEqual(V.classify('출근부 열어줘').kind, 'nav');
});

test('음성 끄기', () => {
    for (const t of ['음성 꺼', '음성 꺼줘', '듣기 그만', '마이크 꺼', '항상 듣기 꺼줘']) assert.strictEqual(V.classify(t).kind, 'voiceoff', t);
    assert.strictEqual(V.classify('그만').kind, 'stop');
});

test('라벨 값 분리', () => {
    const names = ['날짜', '금액', '거래처', '용도', '메모'];
    assert.deepStrictEqual(V.splitLabel('거래처는 스타벅스', names), { idx: 2, value: '스타벅스' });
    assert.deepStrictEqual(V.splitLabel('거래처 이마트', names), { idx: 2, value: '이마트' });
    assert.deepStrictEqual(V.splitLabel('날짜 어제로 해줘', names), { idx: 0, value: '어제' });
    assert.strictEqual(V.splitLabel('출근부', names), null);
    // 라벨만 호출한 경우 다음 발화를 값으로 받도록 빈 값을 반환
    assert.deepStrictEqual(V.splitLabel('메모', names), { idx: 4, value: '' });
});

test('입력칸 말하기', () => {
    const names = ['회사명', '부서', '직책/직위', '직책', '직위', '입사일'];
    const cases = {
        '부서': [1, ''], '부서 입력': [1, ''], '부서입력': [1, ''], '부서 입력해줘': [1, ''], '부서 칸': [1, ''],
        '부서는 인사': [1, '인사'], '부서: 양산기술': [1, '양산기술'], '부서 프로': [1, '프로'],
        '회사명은 삼성전자로 해줘': [0, '삼성전자'], '회사명 삼성전자로 입력해줘': [0, '삼성전자'],
        '직책 책임으로': [3, '책임'], '직책책임': [3, '책임'], '입사일 2019년 3월': [5, '2019년 3월'],
    };
    for (const [said, [idx, value]] of Object.entries(cases)) assert.deepStrictEqual(V.splitLabel(said, names), { idx, value }, said);
    assert.strictEqual(V.valueText('삼성전자로 입력해줘'), '삼성전자');
    assert.strictEqual(V.valueText('동해'), '동해');
    assert.strictEqual(V.valueText('입력'), '');
    assert.deepStrictEqual(V.splitLabel('회사명, 서울우유.', names), { idx: 0, value: '서울우유' });
    assert.deepStrictEqual(V.splitLabel('회사명 입력하기', names), { idx: 0, value: '' });
});

test('간편전표 슬롯', () => {
    const purposes = [
        { label: '회의비', expense: true },
        { label: '소모품', expense: true },
        { label: '매출', expense: false },
        { label: '이자수익', expense: false },
    ];
    assert.deepStrictEqual(V.parseSlip('3만원 지출 스타벅스 회의비', purposes, today),
        { direction: '지출', amount: 30000, date: null, purpose: 0, partner: '스타벅스' });
    assert.deepStrictEqual(V.parseSlip('어제 이마트에서 소모품 만 이천원', purposes, today),
        { direction: null, amount: 12000, date: '2026-09-27', purpose: 1, partner: '이마트' });
    // 방향과 용도가 안 맞으면 용도는 비워서 되묻게 함
    assert.deepStrictEqual(V.parseSlip('3만원 수입 스타벅스 회의비', purposes, today),
        { direction: '수입', amount: 30000, date: null, purpose: null, partner: '스타벅스 회의비' });
    assert.deepStrictEqual(V.parseSlip('', purposes, today),
        { direction: null, amount: null, date: null, purpose: null, partner: '' });
});

test('웨이크워드 하이원', () => {
    assert.strictEqual(V.stripWake('하이원 출근부 열어줘'), '출근부 열어줘');
    assert.strictEqual(V.stripWake('하이 원, 근태 관리'), '근태 관리');
    assert.strictEqual(V.stripWake('Hi wone 출근부 열어줘'), '출근부 열어줘');
    assert.strictEqual(V.stripWake('High one 출근부 열어줘'), '출근부 열어줘');
    assert.strictEqual(V.stripWake('하이원'), '');
    assert.strictEqual(V.stripWake('오늘 점심 뭐 먹지'), null);
});

test('호출어 오인식', () => {
    assert.strictEqual(V.stripWake('하의원 근태 관리'), '근태 관리');
    assert.strictEqual(V.stripWake('아이원 출근부'), '출근부');
    assert.strictEqual(V.stripWake('출근부 열어줘'), null);
});

test('화면 이동 별칭', () => {
    const cases = {
        '홈으로 가줘': '대시보드', '메인으로 가줘': '대시보드', '첫화면': '대시보드',
        '전표 열어줘': '간편전표입력', '간편전표 보여줘': '간편전표입력', '전표입력': '간편전표입력',
        '근태 열어줘': '근태 관리', '내 업무 보여줘': '업무', '캘린더': '일정',
        '내정보로 가줘': '마이페이지', '게시판 보여줘': '커뮤니티',
        '오늘 날씨': null,
    };
    for (const [said, want] of Object.entries(cases)) assert.strictEqual(V.navAlias(said), want, said);
});

test('조사, 동사 떼고 같은 말', () => {
    assert.strictEqual(V.key('근태관리'), V.key('근태관리로가줘'));
    assert.strictEqual(V.key('전표입력으로 이동해줘'), V.key('전표입력'));
    assert.strictEqual(V.key('보기'), '보기');
    assert.deepStrictEqual(V.match('문의해줘', ['문의하기', '메시지'], true), [0]);
});

test('받아쓰기 명령', () => {
    assert.strictEqual(V.dictCmd('지우기'), 'undo');
    assert.strictEqual(V.dictCmd('방금거지워'), 'undo');
    assert.strictEqual(V.dictCmd('방금지워'), 'undo');
    assert.strictEqual(V.dictCmd('문장지우기'), 'sentence');
    assert.strictEqual(V.dictCmd('마지막 문장 지우기'), 'sentence');
    assert.strictEqual(V.dictCmd('전부지우기'), 'clear');
    assert.strictEqual(V.dictCmd('다 지우기'), 'clear');
    assert.strictEqual(V.dictCmd('줄바꿈'), 'newline');
    assert.strictEqual(V.dictCmd('엔터'), 'newline');
    assert.strictEqual(V.dictCmd('다음줄'), 'newline');
    assert.strictEqual(V.dictCmd('다시 읽어줘'), 'read');
    assert.strictEqual(V.dictCmd('읽어줘'), 'read');
    assert.strictEqual(V.dictCmd('전송'), 'send');
    assert.strictEqual(V.dictCmd('보내줘'), 'send');
    assert.strictEqual(V.dictCmd('보내기'), 'send');
    assert.strictEqual(V.dictCmd('제출'), 'send');
    assert.strictEqual(V.dictCmd('끝'), 'end');
    assert.strictEqual(V.dictCmd('받아쓰기끝'), 'end');
    assert.strictEqual(V.dictCmd('그만'), 'end');
    assert.strictEqual(V.dictCmd('멈춰'), 'end');
    assert.strictEqual(V.dictCmd('안녕하세요'), null);
});

test('받아쓰기 고치기', () => {
    const cases = {
        '삭제': 'undo', '삭제하기': 'undo', '지워줘': 'undo', '방금 거 삭제해줘': 'undo',
        '마지막 문장 삭제': 'sentence', '문장 지워줘': 'sentence',
        '전부 삭제해줘': 'clear', '모두 지워': 'clear',
        '수정하기': 'fix', '고쳐줘': 'fix', '다시': 'fix', '다시 말할게': 'fix', '틀렸어': 'fix',
    };
    for (const [said, want] of Object.entries(cases)) assert.strictEqual(V.dictCmd(said), want, said);
    assert.deepStrictEqual(V.replaceCmd('돈을 일로 바꿔줘'), { from: '돈', to: '일' });
    assert.deepStrictEqual(V.replaceCmd('많이 벌고를 적게 벌고로 고쳐줘.'), { from: '많이 벌고', to: '적게 벌고' });
    assert.strictEqual(V.replaceCmd('저는 일을 열심히 했습니다'), null);
    assert.ok(V.cmdLike('메모 삭제'));
    assert.ok(V.cmdLike('메모 수정해줘'));
});

test('받아쓰기 중 명령 구분', () => {
    for (const t of ['메모 저장하기', '두번째 항목 작성', '뒤로 가기', '다음 페이지', '근태 관리 열어줘', '거래처 수정해줘', '아래로']) {
        assert.ok(V.cmdLike(t), t);
    }
    for (const t of ['이번 달은 외부 영업이 많아서 거래처 방문이 늘었습니다.', '그래서 소모품 지출도 함께 늘었습니다.',
        '꾸준히 처리하고 있습니다', '전표 검토를 맡았습니다', '화면 읽어줘']) {
        assert.ok(!V.cmdLike(t), t);
    }
});

test('문장부호 치환', () => {
    assert.strictEqual(V.punct('안녕 하세요 마침표 저는 학생 입니다'), '안녕 하세요. 저는 학생 입니다');
    assert.strictEqual(V.punct('정말요 물음표'), '정말요?');
    assert.strictEqual(V.punct('좋아요 느낌표 다음 문장 쉼표 이어서'), '좋아요! 다음 문장, 이어서');
    assert.strictEqual(V.punct('그냥 문장'), '그냥 문장');
});

test('마지막 문장 삭제', () => {
    assert.strictEqual(V.dropSentence('안녕하세요. 반갑습니다'), '안녕하세요.');
    assert.strictEqual(V.dropSentence('그냥한문장'), '');
    assert.strictEqual(V.dropSentence('첫줄\n둘째줄'), '첫줄\n');
    assert.strictEqual(V.dropSentence('안녕하세요. 반갑습니다   '), '안녕하세요.');
    assert.strictEqual(V.dropSentence('안녕하세요. 반갑습니다. '), '안녕하세요.');
});

test('헛소리 필터', () => {
    assert.strictEqual(V.isJunk('시청해 주셔서 감사합니다'), true);
    assert.strictEqual(V.isJunk('구독과 좋아요 부탁드려요'), true);
    assert.strictEqual(V.isJunk('좋아요와 구독 부탁드려요'), true);
    assert.strictEqual(V.isJunk('감사합니다'), false);
    assert.strictEqual(V.isJunk('네 알겠습니다'), false);
    assert.ok(V.isJunk('외자구매, 외자구매, 등으로 등으로 등으로 등으로.'));
    assert.ok(!V.isJunk('거래처 삼다수'));
});

test('TTS 문장 분할', () => {
    assert.deepStrictEqual(V.sentences('안녕하세요. 반갑습니다!\n오늘은 맑아요'),
        ['안녕하세요.', '반갑습니다!', '오늘은 맑아요']);
    const long = 'ㄱ'.repeat(350) + '.';
    const parts = V.sentences(long);
    assert.strictEqual(parts.length, 2);
    assert.strictEqual(parts[0].length, 300);
    assert.strictEqual(parts[1].length, 51);
});

test('받아쓰기 분류', () => {
    assert.deepStrictEqual(V.classify('받아쓰기'), { kind: 'dictate', arg: '' });
    assert.deepStrictEqual(V.classify('메모 받아쓰기'), { kind: 'dictate', arg: '메모' });
});

test('조사', () => {
    assert.strictEqual(V.josa('경력', '을', '를'), '경력을');
    assert.strictEqual(V.josa('거래처', '을', '를'), '거래처를');
    assert.strictEqual(V.josa('용도', '은', '는'), '용도는');
    assert.strictEqual(V.josa('서울', '으로', '로'), '서울로');
    assert.strictEqual(V.josa('사무직', '으로', '로'), '사무직으로');
});

test('목록 칸 보정', () => {
    const titles = ['사원', '대리', '과장', '차장', '부장', '선임', '책임', '수석', '팀장', '파트장', 'TL', 'PM'];
    const titleCases = { 화장: '과장', 사님: '선임', 채김: '책임', 수성: '수석', 팀짱: '팀장', 대리님: '대리', 티엘: 'TL', tl: 'TL', 파트장: '파트장' };
    for (const [said, want] of Object.entries(titleCases)) assert.strictEqual(V.closest(said, titles), want, said);
    assert.strictEqual(V.closest('삼성전자', titles), '삼성전자');

    const depts = ['인사', 'HR', 'HRD', '외자구매', '정보보안', '양산기술', 'MLCC', 'NAND', 'eSSD'];
    const deptCases = { 의자구매: '외자구매', 엠엘씨씨: 'MLCC', 에이치알디: 'HRD', 이에스에스디: 'eSSD', 정보보완: '정보보안', 양산기술: '양산기술' };
    for (const [said, want] of Object.entries(deptCases)) assert.strictEqual(V.closest(said, depts), want, said);
    for (const t of ['인사팀', '메모리사업부', '반도체연구소']) assert.strictEqual(V.closest(t, depts), t, t);
});
