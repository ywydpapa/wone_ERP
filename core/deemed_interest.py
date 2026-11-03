import calendar
from datetime import date, timedelta
from decimal import Decimal

DEFAULT_RATE = "4.6"
THRESHOLD_PCT = Decimal("0.05")


def _daily_delta(conn, book, pid, code, year, debit_side):
    sign_debit, sign_credit = (1, -1) if debit_side else (-1, 1)
    rows = conn.execute(
        """SELECT d.slip_date AS slip_date, SUM(sl.debit) AS debit, SUM(sl.credit) AS credit
           FROM slip_lines sl JOIN erp_docs d ON d.id=sl.doc_id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code=? AND sl.partner_id=?
             AND d.slip_date BETWEEN ? AND ?
           GROUP BY d.slip_date""",
        (book, code, pid, f"{year}-01-01", f"{year}-12-31"),
    ).fetchall()
    return {r["slip_date"]: sign_debit * (r["debit"] or 0) + sign_credit * (r["credit"] or 0) for r in rows}


def _opening(conn, book, pid, code, year, debit_side):
    sign_debit, sign_credit = (1, -1) if debit_side else (-1, 1)
    row = conn.execute(
        """SELECT COALESCE(SUM(sl.debit),0) AS debit, COALESCE(SUM(sl.credit),0) AS credit
           FROM slip_lines sl JOIN erp_docs d ON d.id=sl.doc_id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code=? AND sl.partner_id=?
             AND d.slip_date<?""",
        (book, code, pid, f"{year}-01-01"),
    ).fetchone()
    return sign_debit * row["debit"] + sign_credit * row["credit"]


def _partners(conn, book, year):
    rows = conn.execute(
        """SELECT DISTINCT sl.partner_id AS pid FROM slip_lines sl JOIN erp_docs d ON d.id=sl.doc_id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code IN ('134','258')
             AND sl.partner_id IS NOT NULL AND d.slip_date<=?""",
        (book, f"{year}-12-31"),
    ).fetchall()
    return [r["pid"] for r in rows]


# 가지급금 적수 - 가수금 적수(같은 거래처 상계, 음수면 0), 일별 누적
def _jeoksu(conn, book, pid, year):
    delta_134 = _daily_delta(conn, book, pid, "134", year, True)
    delta_258 = _daily_delta(conn, book, pid, "258", year, False)
    bal_134 = _opening(conn, book, pid, "134", year, True)
    bal_258 = _opening(conn, book, pid, "258", year, False)
    d, end = date(year, 1, 1), date(year, 12, 31)
    total = 0
    while d <= end:
        iso = d.isoformat()
        bal_134 += delta_134.get(iso, 0)
        bal_258 += delta_258.get(iso, 0)
        total += max(0, bal_134 - bal_258)
        d += timedelta(days=1)
    return total


def _booked_interest(conn, book, pid, year):
    row = conn.execute(
        """SELECT COALESCE(SUM(sl.credit),0) - COALESCE(SUM(sl.debit),0) AS amt
           FROM slip_lines sl JOIN erp_docs d ON d.id=sl.doc_id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code='901' AND sl.partner_id=?
             AND d.slip_date BETWEEN ? AND ?""",
        (book, pid, f"{year}-01-01", f"{year}-12-31"),
    ).fetchone()
    return row["amt"]


# 가지급금 인정이자 조정명세. 법인세법 시행규칙 43조(당좌대출이자율), 시행령 89조 5항(5% 미만 제외)
def calc(conn, book, year, rate_str=DEFAULT_RATE):
    rate = Decimal(rate_str or DEFAULT_RATE)
    divisor = 366 if calendar.isleap(year) else 365

    rows = []
    for pid in _partners(conn, book, year):
        jeoksu = _jeoksu(conn, book, pid, year)
        deemed = int(Decimal(jeoksu) * rate / 100 / divisor)
        booked = _booked_interest(conn, book, pid, year)
        diff = deemed - booked
        add = diff if diff > 0 and diff >= deemed * THRESHOLD_PCT else 0
        name = conn.execute("SELECT name FROM partners WHERE id=?", (pid,)).fetchone()["name"]
        rows.append({"partner_id": pid, "partner_name": name, "jeoksu": jeoksu,
                     "deemed": deemed, "booked": booked, "diff": diff, "add": add})
    rows.sort(key=lambda r: r["partner_name"])

    total = {k: sum(r[k] for r in rows) for k in ("jeoksu", "deemed", "booked", "diff", "add")}
    return {"rows": rows, "total": total, "divisor": divisor}
