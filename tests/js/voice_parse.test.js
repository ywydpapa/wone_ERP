const test = require('node:test');
const assert = require('node:assert');
const V = require('../../static/js/voice-parse.js');

const today = new Date(2026, 8, 28);

test('웨이크워드', () => {
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

test('라벨 값 분리', () => {
    const names = ['날짜', '금액', '거래처', '용도', '메모'];
    assert.deepStrictEqual(V.splitLabel('거래처는 스타벅스', names), { idx: 2, value: '스타벅스' });
    assert.deepStrictEqual(V.splitLabel('거래처 이마트', names), { idx: 2, value: '이마트' });
    assert.deepStrictEqual(V.splitLabel('날짜 어제로 해줘', names), { idx: 0, value: '어제' });
    assert.strictEqual(V.splitLabel('출근부', names), null);
    assert.strictEqual(V.splitLabel('메모', names), null);
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
