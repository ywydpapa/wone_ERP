from fastapi import Depends, Request

from core.constants import COMPANY_INFO
from core.deps import AuthRedirect, get_db, require_login
from core.erp_log import log_activity
from core.tz import now_kst

INTERNAL = 0

# 앞에서부터 첫 매칭
GROUPS = [
    ("120", "130", "재고자산"),
    ("101", "199", "당좌자산"),
    ("201", "250", "유형자산"),
    ("251", "290", "유동부채"),
    ("291", "330", "비유동부채"),
    ("331", "340", "자본금"),
    ("341", "400", "이익잉여금"),
    ("401", "450", "매출"),
    ("451", "800", "매출원가"),
    ("801", "900", "판매관리비"),
    ("901", "950", "영업외수익"),
    ("951", "999", "영업외비용"),
]


def acct_group(code):
    for lo, hi, name in GROUPS:
        if lo <= code <= hi:
            return name
    return ""


def book_of(conn, u):
    if u["role"] == "platform_staff":
        return INTERNAL
    if u["role"] == "client":
        row = conn.execute("SELECT company_id FROM client_users WHERE user_id=?", (u["id"],)).fetchone()
    else:
        row = conn.execute("SELECT company_id FROM employees WHERE user_id=?", (u["id"],)).fetchone()
    return row["company_id"] if row and row["company_id"] else None


def require_book(request: Request, conn=Depends(get_db)):
    u = require_login(request)
    book = book_of(conn, u)
    if book is None:
        raise AuthRedirect("/")
    return {**u, "book": book}


def period_closed(conn, book, slip_date):
    if not slip_date or len(slip_date) < 7:
        return False
    row = conn.execute(
        "SELECT 1 FROM fi_closings WHERE company_id=? AND year=? AND month=? AND status='closed'",
        (book, int(slip_date[:4]), int(slip_date[5:7])),
    ).fetchone()
    return bool(row)


def next_slip_no(conn, book, slip_date):
    conn.execute(
        """INSERT INTO slip_seqs (company_id, slip_date, last_no) VALUES (?,?,1)
           ON CONFLICT(company_id, slip_date) DO UPDATE SET last_no = last_no + 1""",
        (book, slip_date),
    )
    no = conn.execute(
        "SELECT last_no FROM slip_seqs WHERE company_id=? AND slip_date=?", (book, slip_date)
    ).fetchone()[0]
    return f"{slip_date.replace('-', '')}-{no:05d}"


def check_lines(conn, book, lines):
    if len(lines) < 2:
        return "전표는 2줄 이상이어야 합니다."
    dr = cr = 0
    for l in lines:
        d, c = l.get("debit", 0), l.get("credit", 0)
        if d < 0 or c < 0 or (d and c) or not (d or c):
            return "각 줄은 차변 또는 대변 중 하나만 입력해야 합니다."
        acct = conn.execute(
            "SELECT name, is_active, req_partner, req_dept FROM accounts WHERE company_id=? AND code=?",
            (book, l["code"]),
        ).fetchone()
        if not acct or not acct["is_active"]:
            return f"사용할 수 없는 계정입니다: {l['code']}"
        pid = l.get("partner_id")
        if acct["req_partner"] and not pid:
            return f"{acct['name']} 계정은 거래처가 필요합니다."
        if pid and not conn.execute(
            "SELECT 1 FROM partners WHERE id=? AND company_id=?", (pid, book)
        ).fetchone():
            return "거래처를 찾을 수 없습니다."
        if acct["req_dept"] and not l.get("dept"):
            return f"{acct['name']} 계정은 부서가 필요합니다."
        dr += d
        cr += c
    if dr != cr:
        return "차변과 대변 합계가 일치하지 않습니다."
    return None


def write_lines(conn, doc_id, book, lines):
    conn.execute("DELETE FROM slip_lines WHERE doc_id=?", (doc_id,))
    for no, l in enumerate(lines, 1):
        name = conn.execute(
            "SELECT name FROM accounts WHERE company_id=? AND code=?", (book, l["code"])
        ).fetchone()["name"]
        pname = ""
        if l.get("partner_id"):
            pname = conn.execute("SELECT name FROM partners WHERE id=?", (l["partner_id"],)).fetchone()["name"]
        conn.execute(
            """INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit,
                   partner, partner_id, summary, dept, project_code)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, no, f"[{l['code']}] {name}", l["code"], l.get("debit", 0), l.get("credit", 0),
             pname, l.get("partner_id"), l.get("summary", ""), l.get("dept", ""), l.get("project_code", "")),
        )


def post(conn, book, uid, slip_date, lines, title, source, source_id=None, content="", slip_type="대체"):
    if period_closed(conn, book, slip_date):
        raise ValueError("마감된 회계기간입니다.")
    err = check_lines(conn, book, lines)
    if err:
        raise ValueError(err)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    slip_no = next_slip_no(conn, book, slip_date)
    total = sum(l.get("debit", 0) for l in lines)
    doc_id = conn.execute(
        """INSERT INTO erp_docs (user_id, doc_type, title, content, status, slip_type, slip_date, slip_total,
               company_id, slip_no, doc_number, source_type, source_id, posted_at)
           VALUES (?,'expense',?,?,'done',?,?,?,?,?,?,?,?,?)""",
        (uid, title, content, slip_type, slip_date, total, book, slip_no, slip_no, source, source_id, now),
    ).lastrowid
    write_lines(conn, doc_id, book, lines)
    name = conn.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()["name"]
    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (doc_id, uid, name, "자동전기", title),
    )
    log_activity(conn, uid, "create", "slip", doc_id, slip_no, f"자동전표 {slip_no} {title}")
    return doc_id


def reverse(conn, doc_id, uid, slip_date):
    doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
    if doc["status"] != "done":
        raise ValueError("전기된 전표만 역분개할 수 있습니다.")
    if doc["reversal_of"]:
        raise ValueError("역분개 전표는 다시 역분개할 수 없습니다.")
    if conn.execute("SELECT 1 FROM erp_docs WHERE reversal_of=?", (doc_id,)).fetchone():
        raise ValueError("이미 역분개된 전표입니다.")
    lines = [
        {"code": r["account_code"], "debit": r["credit"], "credit": r["debit"], "partner_id": r["partner_id"],
         "summary": r["summary"], "dept": r["dept"] or "", "project_code": r["project_code"] or ""}
        for r in conn.execute("SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,))
    ]
    new_id = post(conn, doc["company_id"], uid, slip_date, lines, f"[역분개] {doc['title']}", "reverse", doc_id)
    conn.execute("UPDATE erp_docs SET reversal_of=? WHERE id=?", (doc_id, new_id))
    return new_id


def seed_accounts(conn, company_id):
    conn.execute(
        """INSERT OR IGNORE INTO accounts (company_id, code, name, category, is_debit, is_active, req_partner, req_dept)
           SELECT ?, code, name, category, is_debit, 1, req_partner, req_dept FROM accounts
           WHERE company_id=0 AND is_active=1""",
        (company_id,),
    )


def company_info(conn, book):
    if book == INTERNAL:
        return COMPANY_INFO
    c = conn.execute(
        "SELECT name, business_no, representative, address, biz_type, biz_item FROM client_companies WHERE id=?",
        (book,),
    ).fetchone()
    return {"name": c["name"], "biz_no": c["business_no"] or "", "representative": c["representative"] or "",
            "address": c["address"] or "", "biz_type": c["biz_type"] or "", "biz_item": c["biz_item"] or ""}
