from fastapi import Depends, HTTPException, Request

from core import audit
from core.constants import COMPANY_INFO
from core.deps import AuthRedirect, get_db, require_login
from core.erp_log import log_activity
from core.tz import now_kst, today_kst

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


def book_users(conn, book):
    # 결재선 후보. 고객사는 담당자+소속 근로자, 원 내부는 스태프
    if book is None:
        return []
    if book:
        return [dict(r) for r in conn.execute(
            """SELECT id, name, dept, position, role FROM users WHERE id IN (
                   SELECT user_id FROM client_users WHERE company_id=?
                   UNION SELECT user_id FROM employees WHERE company_id=?)
               ORDER BY dept, name""", (book, book)
        )]
    return [dict(r) for r in conn.execute(
        "SELECT id, name, dept, position, role FROM users WHERE role='platform_staff' ORDER BY dept, name"
    )]


def require_book(request: Request, conn=Depends(get_db)):
    u = require_login(request)
    book = book_of(conn, u)
    if book is None:
        raise HTTPException(status_code=403, detail="no_book")
    return {**u, "book": book}


def emp_book(book):
    # employees.company_id는 client_companies FK. book 0(원 내부)은 NULL로 저장
    return book or None


def book_emp(conn, book, emp_id):
    row = conn.execute(
        "SELECT * FROM employees WHERE id=? AND company_id IS ?", (emp_id, emp_book(book))
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    return dict(row)


def hr_book_ok(conn, u, book):
    # 급여 대행 계약 조건이 바뀌면 여기만 수정
    if u["role"] == "client":
        if u.get("client_role") not in ("hr", "all"):
            return False
        row = conn.execute("SELECT company_id FROM client_users WHERE user_id=?", (u["id"],)).fetchone()
        return bool(row) and row["company_id"] == book
    if u["role"] == "platform_staff":
        if book == INTERNAL:
            return True
        row = conn.execute(
            "SELECT payroll_delegated, status FROM client_companies WHERE id=?", (book,)
        ).fetchone()
        return bool(row and row["payroll_delegated"] and row["status"] == "active")
    return False


def require_hr_book(request: Request, conn=Depends(get_db)):
    u = require_login(request)
    u["client_role"] = request.session.get("client_role", "all")
    if u["role"] == "client":
        book = book_of(conn, u)
        if book is None or not hr_book_ok(conn, u, book):
            raise AuthRedirect("/")
        return {**u, "book": book}
    if u["role"] == "platform_staff":
        book = int(request.session.get("hr_book", 0))
        if not hr_book_ok(conn, u, book):
            # 위탁 해제 등으로 더 이상 못 보는 book이면 다음 요청부터 내부로 복귀 처리
            request.session["hr_book"] = 0
            book = 0
        return {**u, "book": book}
    raise AuthRedirect("/")


# 공단 제출용 주민번호 원본 다운로드 권한. client_role 중 "all"(전체 권한)이 가장 상위이고
# "hr"은 인사 모듈로 한정된 위임 역할이므로 책임자급으로 보지 않음. platform_staff는 제외
def require_hr_chief(request: Request, conn=Depends(get_db)):
    u = require_login(request)
    if u["role"] != "client":
        raise AuthRedirect("/")
    u["client_role"] = request.session.get("client_role", "all")
    if u["client_role"] != "all":
        raise HTTPException(status_code=403, detail="HR 책임자만 이용할 수 있습니다.")
    book = book_of(conn, u)
    if book is None:
        raise AuthRedirect("/")
    return {**u, "book": book}


def period_closed(conn, book, slip_date):
    if not slip_date or len(slip_date) < 7:
        return False
    y = int(slip_date[:4])
    row = conn.execute(
        """SELECT 1 FROM fi_closings WHERE company_id=? AND year=? AND month=? AND status='closed'
           UNION ALL SELECT 1 FROM fiscal_closings WHERE company_id=? AND year=? AND status='closed'""",
        (book, y, int(slip_date[5:7]), book, y),
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
        # 사용중지 부서 포함. 과거 전표 역분개 허용 목적
        if l.get("dept") and not conn.execute(
            "SELECT 1 FROM depts WHERE company_id=? AND name=?", (book, l["dept"])
        ).fetchone():
            return f"등록되지 않은 부서입니다: {l['dept']}"
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


# 활성 계좌 1개면 금융거래처 자동 채움, 2개 이상이면 선택 강제
def fill_bank(conn, book, lines):
    bank_codes = {r["account_code"] for r in conn.execute(
        "SELECT account_code FROM bank_accounts WHERE company_id=? AND is_active=1", (book,))}
    for l in lines:
        if l["code"] not in bank_codes:
            continue
        accts = conn.execute(
            "SELECT partner_id FROM bank_accounts WHERE company_id=? AND account_code=? AND is_active=1",
            (book, l["code"]),
        ).fetchall()
        pids = {a["partner_id"] for a in accts}
        if l.get("partner_id") in pids:
            continue
        if len(accts) == 1:
            l["partner_id"] = accts[0]["partner_id"]
            continue
        name = conn.execute("SELECT name FROM accounts WHERE company_id=? AND code=?", (book, l["code"])).fetchone()["name"]
        return f"{name} 계정은 계좌를 선택해 주세요."
    return None


# 일반전표 거래처 검색 전환용. 계좌 1개인 계정은 자동 채움 대상
def bank_ctx(conn, book):
    rows = conn.execute(
        """SELECT account_code, COUNT(*) AS cnt, MAX(partner_id) AS pid FROM bank_accounts
           WHERE company_id=? AND is_active=1 GROUP BY account_code""", (book,)
    ).fetchall()
    codes = [r["account_code"] for r in rows]
    single = {r["account_code"]: r["pid"] for r in rows if r["cnt"] == 1}
    return codes, single


# select 값은 코드 또는 코드:계좌id 형식
def parse_pay(val):
    code, sep, bid = val.partition(":")
    return code, int(bid) if sep and bid.isdigit() else None


def bank_partner(conn, book, code, bank_id):
    row = conn.execute(
        "SELECT partner_id FROM bank_accounts WHERE id=? AND company_id=? AND account_code=? AND is_active=1",
        (bank_id, book, code),
    ).fetchone()
    return row["partner_id"] if row else None


# 계좌 계정은 계좌마다 option 분리
def pay_options(conn, book, rows):
    bcodes = {r["account_code"] for r in conn.execute(
        "SELECT account_code FROM bank_accounts WHERE company_id=? AND is_active=1", (book,))}
    opts = []
    for r in rows:
        if r["code"] not in bcodes:
            opts.append({"value": r["code"], "label": f"{r['code']} {r['name']}"})
            continue
        for b in conn.execute(
            "SELECT id, bank, account_no FROM bank_accounts WHERE company_id=? AND account_code=? AND is_active=1 ORDER BY id",
            (book, r["code"]),
        ):
            opts.append({"value": f"{r['code']}:{b['id']}", "label": f"{r['code']} {r['name']} {b['bank']} {b['account_no']}"})
    return opts


def post(conn, book, uid, slip_date, lines, title, source, source_id=None, content="", slip_type="대체", keep_lines=False):
    if period_closed(conn, book, slip_date):
        raise ValueError("마감된 회계기간입니다.")
    if not keep_lines:
        err = fill_bank(conn, book, lines)
        if err:
            raise ValueError(err)
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
    audit.log(conn, uid, "post", "slip", doc_id, f"{slip_no} {title}", company_id=book)
    return doc_id


def create_payroll_slip(conn, book, payslip, employee_name, uid):
    year = payslip["pay_year"]
    month = payslip["pay_month"]
    gross = payslip["gross_pay"]
    net = payslip["net_pay"]
    income_tax = payslip["income_tax"] + payslip["resident_tax"]
    pension = payslip["national_pension"]
    health = payslip["health_insurance"] + (payslip.get("long_care") or 0)
    employment = payslip["employment_insurance"]

    emp_id = payslip.get("employee_id")
    emp = conn.execute("SELECT dept FROM employees WHERE id=?", (emp_id,)).fetchone() if emp_id else None
    dept = emp["dept"] or "" if emp else ""
    if dept and not conn.execute("SELECT 1 FROM depts WHERE company_id=? AND name=?", (book, dept)).fetchone():
        dept = ""

    summary = f"{employee_name} {month}월 급여"
    lines = [
        {"code": "801", "debit": gross, "credit": 0, "summary": summary, "dept": dept},
        {"code": "254", "debit": 0, "credit": net, "summary": summary},
    ]
    if income_tax > 0:
        lines.append({"code": "261", "debit": 0, "credit": income_tax, "summary": summary})
    if pension > 0:
        lines.append({"code": "262", "debit": 0, "credit": pension, "summary": summary})
    if health > 0:
        lines.append({"code": "263", "debit": 0, "credit": health, "summary": summary})
    if employment > 0:
        lines.append({"code": "264", "debit": 0, "credit": employment, "summary": summary})

    # 사측 부담분
    er_pension = payslip.get("employer_pension") or 0
    er_health = payslip.get("employer_health") or 0
    er_ei = (payslip.get("employer_employment") or 0) + (payslip.get("employer_accident") or 0)
    er_summary = f"{summary} 사측부담"
    if er_pension > 0:
        lines.append({"code": "815", "debit": er_pension, "credit": 0, "summary": er_summary, "dept": dept})
    if er_health > 0:
        lines.append({"code": "804", "debit": er_health, "credit": 0, "summary": er_summary, "dept": dept})
    if er_ei > 0:
        lines.append({"code": "818", "debit": er_ei, "credit": 0, "summary": er_summary, "dept": dept})
    er_total = er_pension + er_health + er_ei
    if er_total > 0:
        lines.append({"code": "256", "debit": 0, "credit": er_total, "summary": er_summary})

    title = f"급여 전표 ({employee_name} {year}.{month:02d})"
    slip_date = payslip.get("pay_date") or f"{year}-{month:02d}-25"
    content = f"{employee_name} {year}년 {month}월 급여 자동 전표"
    payslip_id = payslip["id"]
    doc_id = post(conn, book, uid, slip_date, lines, title, "payroll", payslip_id, content=content)
    conn.execute("UPDATE erp_docs SET payslip_id=? WHERE id=?", (payslip_id, doc_id))
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
    new_id = post(conn, doc["company_id"], uid, slip_date, lines, f"[역분개] {doc['title']}", "reverse", doc_id,
                  keep_lines=True)
    conn.execute("UPDATE erp_docs SET reversal_of=? WHERE id=?", (doc_id, new_id))
    audit.log(conn, uid, "reverse", "slip", doc_id, f"{doc['slip_no']} {doc['title']} 역분개",
              company_id=doc["company_id"])
    return new_id


def seed_accounts(conn, company_id):
    conn.execute(
        """INSERT OR IGNORE INTO accounts (company_id, code, name, category, is_debit, is_active, req_partner, req_dept)
           SELECT ?, code, name, category, is_debit, 1, req_partner, req_dept FROM accounts
           WHERE company_id=0 AND is_active=1""",
        (company_id,),
    )


def book_label(conn, book):
    if book == INTERNAL:
        return "원 (내부)"
    row = conn.execute("SELECT name FROM client_companies WHERE id=?", (book,)).fetchone()
    return row["name"] if row else ""


def company_info(conn, book):
    if book == INTERNAL:
        return COMPANY_INFO
    c = conn.execute(
        "SELECT name, business_no, representative, address, biz_type, biz_item, contact_email FROM client_companies WHERE id=?",
        (book,),
    ).fetchone()
    return {"name": c["name"], "biz_no": c["business_no"] or "", "representative": c["representative"] or "",
            "address": c["address"] or "", "biz_type": c["biz_type"] or "", "biz_item": c["biz_item"] or "",
            "email": c["contact_email"] or ""}


def dept_names(conn, book):
    return [r["name"] for r in conn.execute(
        "SELECT name FROM depts WHERE company_id=? AND is_active=1 ORDER BY sort, name", (book,)).fetchall()]


def cost_accts(conn, book):
    return [dict(r) for r in conn.execute(
        "SELECT code, name FROM accounts WHERE company_id=? AND category='비용' AND is_active=1 ORDER BY code",
        (book,)).fetchall()]


def acct_opts(conn, book):
    return conn.execute(
        "SELECT code, name FROM accounts WHERE company_id=? AND is_active=1 ORDER BY code", (book,)).fetchall()


def wh_opts(conn, book):
    return [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code", (book,)).fetchall()]


def partner_opts(conn, book):
    return conn.execute(
        "SELECT id, name FROM partners WHERE company_id=? AND is_active=1 ORDER BY name", (book,)).fetchall()


def cost_ok(conn, book, code):
    return bool(code) and conn.execute(
        "SELECT 1 FROM accounts WHERE company_id=? AND code=? AND category='비용' AND is_active=1", (book, code)
    ).fetchone() is not None


def income_statement_data(conn, book, date_from, date_to):
    today = today_kst()
    if not date_from:
        date_from = f"{today.year}-01-01"
    if not date_to:
        date_to = today.isoformat()

    rows = conn.execute(
        """SELECT a.code, a.name, a.category, a.is_debit,
                  COALESCE(SUM(CASE WHEN ed.id IS NOT NULL THEN sl.debit ELSE 0 END),0) as d,
                  COALESCE(SUM(CASE WHEN ed.id IS NOT NULL THEN sl.credit ELSE 0 END),0) as c
           FROM accounts a
           LEFT JOIN slip_lines sl ON sl.account_code = a.code
           LEFT JOIN erp_docs ed ON sl.doc_id = ed.id AND ed.company_id = ? AND ed.status = 'done'
                AND ed.slip_date BETWEEN ? AND ?
           WHERE a.company_id = ? AND a.category IN ('수익','비용')
           GROUP BY a.code, a.name, a.category, a.is_debit""",
        (book, date_from, date_to, book),
    ).fetchall()

    sections = {"매출": [], "매출원가": [], "판매관리비": [], "영업외수익": [], "영업외비용": []}
    for r in rows:
        bal = (r["c"] - r["d"]) if not r["is_debit"] else (r["d"] - r["c"])
        if bal == 0:
            continue
        grp = acct_group(r["code"])
        if grp in sections:
            sections[grp].append({"code": r["code"], "name": r["name"], "balance": bal})

    def total(key):
        return sum(x["balance"] for x in sections[key])

    revenue = total("매출")
    cogs = total("매출원가")
    gross_profit = revenue - cogs
    sga = total("판매관리비")
    operating_income = gross_profit - sga
    other_income = total("영업외수익")
    other_expense = total("영업외비용")
    net_income = operating_income + other_income - other_expense

    return date_from, date_to, sections, {
        "revenue": revenue, "cogs": cogs, "gross_profit": gross_profit,
        "sga": sga, "operating_income": operating_income,
        "other_income": other_income, "other_expense": other_expense,
        "net_income": net_income,
    }


def balance_sheet_data(conn, book, as_of):
    if not as_of:
        as_of = today_kst().isoformat()

    rows = conn.execute("""
        SELECT a.code, a.name, a.category, a.is_debit,
               COALESCE(SUM(CASE WHEN d.id IS NOT NULL THEN sl.debit ELSE 0 END),0) as total_debit,
               COALESCE(SUM(CASE WHEN d.id IS NOT NULL THEN sl.credit ELSE 0 END),0) as total_credit
        FROM accounts a
        LEFT JOIN slip_lines sl ON sl.account_code = a.code
        LEFT JOIN erp_docs d ON sl.doc_id = d.id AND d.slip_date <= ? AND d.company_id = ? AND d.status = 'done'
        WHERE a.company_id = ? AND a.category NOT IN ('수익','비용')
        GROUP BY a.code, a.name, a.category, a.is_debit
        HAVING total_debit > 0 OR total_credit > 0
        ORDER BY a.code
    """, [as_of, book, book]).fetchall()

    assets, liabilities, equity = [], [], []
    asset_total = liability_total = equity_total = 0

    for r in rows:
        bal = r["total_debit"] - r["total_credit"] if r["is_debit"] else r["total_credit"] - r["total_debit"]
        if bal == 0:
            continue
        item = {"code": r["code"], "name": r["name"], "balance": bal}
        cat = r["category"]
        if cat == "자산":
            assets.append(item)
            asset_total += bal
        elif cat == "부채":
            liabilities.append(item)
            liability_total += bal
        elif cat == "자본":
            equity.append(item)
            equity_total += bal

    year_start = f"{as_of[:4]}-01-01"
    pl = conn.execute("""
        SELECT a.category, a.is_debit,
               COALESCE(SUM(CASE WHEN d.slip_date < ? THEN sl.debit ELSE 0 END),0) as pre_d,
               COALESCE(SUM(CASE WHEN d.slip_date < ? THEN sl.credit ELSE 0 END),0) as pre_c,
               COALESCE(SUM(CASE WHEN d.slip_date >= ? THEN sl.debit ELSE 0 END),0) as fy_d,
               COALESCE(SUM(CASE WHEN d.slip_date >= ? THEN sl.credit ELSE 0 END),0) as fy_c
        FROM accounts a
        LEFT JOIN slip_lines sl ON sl.account_code = a.code
        LEFT JOIN erp_docs d ON sl.doc_id = d.id AND d.slip_date <= ? AND d.company_id = ? AND d.status = 'done'
        WHERE a.company_id = ? AND a.category IN ('수익','비용')
        GROUP BY a.category, a.is_debit
    """, [year_start, year_start, year_start, year_start, as_of, book, book]).fetchall()

    pre_net = fy_net = 0
    for r in pl:
        pre_bal = r["pre_d"] - r["pre_c"] if r["is_debit"] else r["pre_c"] - r["pre_d"]
        fy_bal = r["fy_d"] - r["fy_c"] if r["is_debit"] else r["fy_c"] - r["fy_d"]
        sign = -1 if r["category"] == "비용" else 1
        pre_net += sign * pre_bal
        fy_net += sign * fy_bal

    if pre_net != 0:
        carried = next((it for it in equity if it["code"] in ("375", "377")), None)
        if carried:
            carried["balance"] += pre_net
        else:
            equity.append({"code": "375", "name": "이월이익잉여금", "balance": pre_net})
        equity_total += pre_net

    if fy_net != 0:
        equity.append({"code": "-", "name": "당기순이익", "balance": fy_net})
        equity_total += fy_net

    return as_of, assets, liabilities, equity, asset_total, liability_total, equity_total
