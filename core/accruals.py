import calendar
import json
import re

from core import books

YM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

KIND_LABELS = {"prepaid": "선급비용", "accrued": "미지급비용"}
CONTRA_CODE = {"prepaid": "116", "accrued": "256"}


def valid_ym(s):
    return bool(YM_RE.match(s or ""))


def ym_list(start_ym, end_ym):
    y, m = int(start_ym[:4]), int(start_ym[5:7])
    ey, em = int(end_ym[:4]), int(end_ym[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


# 월할 분배, 단수는 마지막 달에 몰림
def monthly_amounts(amount, start_ym, end_ym):
    yms = ym_list(start_ym, end_ym)
    n = len(yms)
    base = amount // n
    out = {ym: base for ym in yms}
    out[yms[-1]] += amount - base * n
    return out


def month_end(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    d = calendar.monthrange(y, m)[1]
    return f"{y:04d}-{m:02d}-{d:02d}"


def remain(conn, accrual):
    posted = conn.execute(
        "SELECT COALESCE(SUM(d.slip_total), 0) FROM accrual_posts ap "
        "JOIN erp_docs d ON d.id=ap.doc_id WHERE ap.accrual_id=?",
        (accrual["id"],),
    ).fetchone()[0]
    return accrual["amount"] - posted


# 반환 (doc_id, None) 생성 / (None, None) 대상 아님 또는 이미 생성 / (None, 메시지) 전기 실패
def post_accrual(conn, book, uid, accrual, ym):
    if accrual["status"] != "active" or ym < accrual["start_ym"] or ym > accrual["end_ym"]:
        return None, None
    if conn.execute("SELECT 1 FROM accrual_posts WHERE accrual_id=? AND ym=?", (accrual["id"], ym)).fetchone():
        return None, None
    amt = monthly_amounts(accrual["amount"], accrual["start_ym"], accrual["end_ym"])[ym]
    contra = CONTRA_CODE[accrual["kind"]]
    lines = [
        {"code": accrual["expense_code"], "debit": amt, "credit": 0, "partner_id": accrual["partner_id"],
         "dept": accrual["dept"] or "", "summary": accrual["memo"] or ""},
        {"code": contra, "debit": 0, "credit": amt, "partner_id": accrual["partner_id"],
         "summary": accrual["memo"] or ""},
    ]
    title = f"{ym} {KIND_LABELS[accrual['kind']]} 배분" + (f" ({accrual['memo']})" if accrual["memo"] else "")
    try:
        doc_id = books.post(conn, book, uid, month_end(ym), lines, title, "accrual", accrual["id"])
    except ValueError as e:
        return None, str(e)
    conn.execute("INSERT INTO accrual_posts (accrual_id, ym, doc_id) VALUES (?,?,?)", (accrual["id"], ym, doc_id))
    return doc_id, None


def run_accruals(conn, book, uid, ym):
    rows = conn.execute("SELECT * FROM accruals WHERE company_id=? AND status='active'", (book,)).fetchall()
    created, skipped, errors = 0, 0, []
    for a in rows:
        doc_id, err = post_accrual(conn, book, uid, dict(a), ym)
        if err:
            errors.append(f"{a['memo'] or a['expense_code']}: {err}")
        elif doc_id:
            created += 1
        else:
            skipped += 1
    return created, skipped, errors


# day 0은 말일, 그 외엔 해당 월 말일로 클리핑
def resolved_date(ym, day):
    y, m = int(ym[:4]), int(ym[5:7])
    last = calendar.monthrange(y, m)[1]
    d = last if day == 0 else min(day, last)
    return f"{y:04d}-{m:02d}-{d:02d}"


def post_recurring(conn, book, uid, sched, ym):
    if sched["status"] != "active" or ym < sched["start_ym"] or ym > sched["end_ym"]:
        return None, None
    if conn.execute("SELECT 1 FROM recurring_posts WHERE recurring_id=? AND ym=?", (sched["id"], ym)).fetchone():
        return None, None
    lines = json.loads(sched["lines_json"])
    try:
        doc_id = books.post(conn, book, uid, resolved_date(ym, sched["day"]), lines,
                             f"{sched['title']} {ym}", "recurring", sched["id"])
    except ValueError as e:
        return None, str(e)
    conn.execute("INSERT INTO recurring_posts (recurring_id, ym, doc_id) VALUES (?,?,?)", (sched["id"], ym, doc_id))
    return doc_id, None


def run_recurring(conn, book, uid, ym):
    rows = conn.execute("SELECT * FROM recurring_slips WHERE company_id=? AND status='active'", (book,)).fetchall()
    created, skipped, errors = 0, 0, []
    for s in rows:
        doc_id, err = post_recurring(conn, book, uid, dict(s), ym)
        if err:
            errors.append(f"{s['title']}: {err}")
        elif doc_id:
            created += 1
        else:
            skipped += 1
    return created, skipped, errors
