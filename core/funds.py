import calendar
from datetime import date, timedelta

from core import credit, partner

CASH_CODE = "101"


def _accounts(conn, book):
    return conn.execute(
        "SELECT id, bank, account_no, name, account_code, partner_id FROM bank_accounts "
        "WHERE company_id=? AND is_active=1 ORDER BY bank, account_no", (book,)).fetchall()


# 전일잔액(day 이전), 당일 입금/출금, 당일잔액을 한 질의로 산정
def _row(conn, book, code, day, cond, args, label):
    r = conn.execute(
        f"""SELECT COALESCE(SUM(CASE WHEN d.slip_date<? THEN sl.debit-sl.credit ELSE 0 END),0) AS prev,
                   COALESCE(SUM(CASE WHEN d.slip_date=? THEN sl.debit ELSE 0 END),0) AS din,
                   COALESCE(SUM(CASE WHEN d.slip_date=? THEN sl.credit ELSE 0 END),0) AS dout
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE d.company_id=? AND d.status='done' AND sl.account_code=? AND {cond}""",
        [day, day, day, book, code, *args],
    ).fetchone()
    return {"label": label, "code": code, "prev": r["prev"], "in": r["din"], "out": r["dout"],
            "cur": r["prev"] + r["din"] - r["dout"]}


# 현금(101)과 계좌별(103) 전일/당일 잔액. 계좌 연결 없는 103 라인은 "계좌 미지정"으로 묶음
def daily_funds(conn, book, day):
    accounts = _accounts(conn, book)
    rows = [_row(conn, book, CASH_CODE, day, "1=1", [], "현금")]
    for a in accounts:
        rows.append(_row(conn, book, a["account_code"], day, "sl.partner_id=?", [a["partner_id"]],
                          f"{a['bank']} {a['name']}"))

    codes = sorted({a["account_code"] for a in accounts})
    for code in codes:
        pids = [a["partner_id"] for a in accounts if a["account_code"] == code]
        ph = ",".join("?" * len(pids))
        row = _row(conn, book, code, day, f"(sl.partner_id IS NULL OR sl.partner_id NOT IN ({ph}))", pids,
                   "계좌 미지정")
        if row["prev"] or row["in"] or row["out"]:
            rows.append(row)

    totals = {"prev": sum(r["prev"] for r in rows), "in": sum(r["in"] for r in rows),
              "out": sum(r["out"] for r in rows), "cur": sum(r["cur"] for r in rows)}

    line_codes = sorted({CASH_CODE, *codes})
    ph = ",".join("?" * len(line_codes))
    lines = conn.execute(
        f"""SELECT d.id AS doc_id, d.doc_number, sl.summary, sl.partner, sl.debit, sl.credit
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE d.company_id=? AND d.status='done' AND d.slip_date=? AND sl.account_code IN ({ph})
            ORDER BY d.id, sl.line_no""",
        [book, day, *line_codes],
    ).fetchall()

    return {"rows": rows, "totals": totals, "lines": lines}


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _cash_balance(conn, book, until):
    r = conn.execute(
        """SELECT COALESCE(SUM(sl.debit),0)-COALESCE(SUM(sl.credit),0) FROM slip_lines sl
           JOIN erp_docs d ON sl.doc_id=d.id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code IN ('101','103') AND d.slip_date<=?""",
        (book, until),
    ).fetchone()[0]
    return r or 0


# 외상매출금(110)/외상매입금(251) 미결 항목을 거래처 결제조건 기준 만기일로 환산해 적재
def _ar_ap(conn, book, acct, place, kind, is_in):
    partners = {p["id"]: p for p in conn.execute(
        "SELECT id, name, pay_terms, pay_days FROM partners WHERE company_id=?", (book,))}
    for pid, info in credit.open_items(conn, book, acct).items():
        p = partners.get(pid)
        terms, days, name = (p["pay_terms"], p["pay_days"], p["name"]) if p else ("", 0, "")
        for it in info["items"]:
            if it["remain"] <= 0:
                continue
            due = partner.due_date(it["date"], terms, days)
            place(due, it["remain"], is_in, kind, name)
    for name, info in credit.open_items(conn, book, acct, orphan=True).items():
        for it in info["items"]:
            if it["remain"] <= 0:
                continue
            place(it["date"], it["remain"], is_in, kind, name)


# 받을어음(보유분)/지급어음(발행분) 만기를 적재
def _notes(conn, book, place, kind_recv, kind_pay):
    for n in conn.execute(
        "SELECT partner_id, amount, due_date FROM notes WHERE company_id=? AND kind='recv' AND status='held'",
        (book,),
    ):
        name = conn.execute("SELECT name FROM partners WHERE id=?", (n["partner_id"],)).fetchone()
        place(n["due_date"], n["amount"], True, kind_recv, name["name"] if name else "")
    for n in conn.execute(
        "SELECT partner_id, amount, due_date FROM notes WHERE company_id=? AND kind='pay' AND status='issued'",
        (book,),
    ):
        name = conn.execute("SELECT name FROM partners WHERE id=?", (n["partner_id"],)).fetchone()
        place(n["due_date"], n["amount"], False, kind_pay, name["name"] if name else "")


# 기준일부터 N개월, 주 단위 버킷. 기한 지난 미결은 첫 행 "연체"로 별도 집계
def cash_plan(conn, book, as_of, months):
    as_of_d = date.fromisoformat(as_of)
    end_d = _add_months(as_of_d, months)
    bucket_cnt = -(-(end_d - as_of_d).days // 7)

    buckets = []
    for i in range(bucket_cnt):
        start = as_of_d + timedelta(days=7 * i)
        stop = min(as_of_d + timedelta(days=7 * (i + 1) - 1), end_d)
        buckets.append({"label": f"{start.isoformat()} ~ {stop.isoformat()}", "in": 0, "out": 0, "items": []})
    overdue = {"label": "연체", "in": 0, "out": 0, "items": []}

    def place(due_iso, amount, is_in, kind, partner_name):
        due_d = date.fromisoformat(due_iso)
        item = {"kind": kind, "partner": partner_name, "due": due_iso, "amount": amount}
        if due_d < as_of_d:
            row = overdue
        else:
            idx = (due_d - as_of_d).days // 7
            if idx >= bucket_cnt:
                return
            row = buckets[idx]
        row["items"].append(item)
        row["in" if is_in else "out"] += amount

    _ar_ap(conn, book, "110", place, "외상매출금", True)
    _ar_ap(conn, book, "251", place, "외상매입금", False)
    _notes(conn, book, place, "받을어음", "지급어음")

    row254 = conn.execute(
        """SELECT COALESCE(SUM(sl.credit),0)-COALESCE(SUM(sl.debit),0) FROM slip_lines sl
           JOIN erp_docs d ON sl.doc_id=d.id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code='254' AND d.slip_date<=?""",
        (book, as_of),
    ).fetchone()[0]
    if row254 and row254 > 0:
        nd = _add_months(as_of_d, 1)
        place(date(nd.year, nd.month, 10).isoformat(), row254, False, "미지급금", "-")

    rows = [overdue] + buckets
    bal = _cash_balance(conn, book, as_of)
    for r in rows:
        bal += r["in"] - r["out"]
        r["balance"] = bal

    all_items = sorted(
        (dict(it, overdue=(r is overdue)) for r in rows for it in r["items"]),
        key=lambda it: it["due"],
    )

    return {"opening": _cash_balance(conn, book, as_of), "rows": rows, "items": all_items, "end": end_d.isoformat()}
