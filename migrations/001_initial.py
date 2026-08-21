
import hashlib


CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT UNIQUE NOT NULL,
    password   TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    dept       TEXT NOT NULL DEFAULT '경영지원팀',
    role       TEXT NOT NULL DEFAULT 'employee',
    created_at TEXT DEFAULT (datetime('now','localtime'))
)
"""

CREATE_ERP_DOCS = """
CREATE TABLE IF NOT EXISTS erp_docs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    doc_type   TEXT NOT NULL DEFAULT 'draft',
    title      TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
)
"""

CREATE_DOCUMENT_TYPES = """
CREATE TABLE IF NOT EXISTS document_types (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    code  TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL
)
"""

SEED_DOCUMENT_TYPES = [
    ("draft",         "결재 기안"),
    ("hr_task",       "HR 업무"),
    ("stock_move",    "입출고"),
    ("work_order",    "작업 지시"),
    ("po",            "구매 발주"),
    ("activity",      "영업 활동"),
    ("expense",       "자금관리"),
    ("leave",         "휴가신청"),
    ("business_trip", "출장신청"),
    ("trip_report",   "출장보고"),
    ("weekly_report", "주간업무보고"),
    ("overtime",      "초과근무"),
]

SEED_USERS = [
    ("admin", "1234", "관리자", "경영지원팀", "admin"),
    ("user1", "1234", "홍길동", "개발팀",     "employee"),
    ("user2", "1234", "김영희", "영업팀",     "employee"),
]

SEED_DOCS = [
    (1, "draft",         "2024년 하반기 사업계획 기안",    "하반기 전략 방향 및 예산안 포함",     "approved"),
    (1, "hr_task",       "신규 입사자 온보딩 절차",        "개발팀 신입 3명 온보딩 일정",         "approved"),
    (2, "stock_move",    "원자재 A-100 입고",             "수량 500개, 창고 B동 배치",           "approved"),
    (2, "work_order",    "8월 생산 작업지시 #2024-08",     "제품코드 P-200, 목표 수량 1,000개",   "in_progress"),
    (3, "po",            "거래처 (주)한국부품 발주",        "부품 B-300 x 200개, 납기 9/15",      "pending"),
    (3, "activity",      "고객사 미팅 - (주)세원테크",      "신규 계약 논의, 견적서 전달 완료",     "approved"),
    (1, "expense",       "8월 법인카드 사용내역 정산",      "마케팅비 320만원, 접대비 45만원",     "pending"),
    (2, "leave",         "연차휴가 신청 (8/25~8/27)",      "개인 사유, 3일간",                   "approved"),
    (3, "business_trip", "부산 출장 신청 (9/1~9/3)",       "고객사 방문 및 현장 점검",            "pending"),
    (1, "trip_report",   "서울 본사 출장 보고서",           "7/20~7/22 본사 회의 참석 결과",      "approved"),
    (2, "weekly_report", "개발팀 주간업무보고 (8/12~8/16)", "API 개발 완료, QA 진행중",           "approved"),
    (3, "overtime",      "8월 초과근무 신청",              "프로젝트 마감 대응, 주말근무 포함",    "in_progress"),
    (1, "draft",         "사무실 이전 관련 기안",           "9월 중 사무실 이전 계획안",           "draft"),
    (2, "po",            "사무용품 구매 발주",             "A4용지 외 5건, 총 23만원",            "approved"),
    (1, "stock_move",    "완제품 P-200 출고",             "수량 300개, (주)세원테크 납품",        "approved"),
]


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def up(conn):
    conn.execute(CREATE_USERS)
    conn.execute(CREATE_ERP_DOCS)
    conn.execute(CREATE_DOCUMENT_TYPES)
    conn.commit()

    for code, label in SEED_DOCUMENT_TYPES:
        try:
            conn.execute(
                "INSERT INTO document_types (code, label) VALUES (?,?)", (code, label)
            )
        except Exception:
            pass
    conn.commit()

    for username, password, name, dept, role in SEED_USERS:
        try:
            conn.execute(
                "INSERT INTO users (username, password, name, dept, role) VALUES (?,?,?,?,?)",
                (username, _hash(password), name, dept, role),
            )
            print(f"  유저 생성: {username}")
        except Exception:
            print(f"  유저 있음(skip): {username}")

    for user_id, doc_type, title, content, status in SEED_DOCS:
        try:
            conn.execute(
                "INSERT INTO erp_docs (user_id, doc_type, title, content, status) VALUES (?,?,?,?,?)",
                (user_id, doc_type, title, content, status),
            )
        except Exception:
            pass
    conn.commit()
