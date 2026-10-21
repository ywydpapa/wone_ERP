import calendar
import csv
import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette.responses import StreamingResponse
from core.deps import get_db, templates
from core.tz import today_kst
from core.books import require_book
from core.export import esc_cell

router = APIRouter()

CASH_CODE = "101"


def _daily_period(mode, date_from, date_to):
    today = today_kst()
    if date_from and date_to:
        return date_from, date_to
    if mode == "month":
        last_day = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=1).isoformat(), today.replace(day=last_day).isoformat()
    day = date_from or date_to or today.isoformat()
    return day, day


def _daily_data(conn, book, date_from, date_to):
    lines = conn.execute(
        """SELECT sl.doc_id, sl.account_code, sl.debit, sl.credit
           FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
           WHERE d.company_id=? AND d.status='done' AND d.slip_date BETWEEN ? AND ?""",
        (book, date_from, date_to),
    ).fetchall()

    # 현금 계정은 행 제외, 상대 계정의 현금 칸으로 표시하고 전일/금일 잔고로 대차 보정
    cash_out = {r["doc_id"] for r in lines if r["account_code"] == CASH_CODE and r["credit"]}
    cash_in = {r["doc_id"] for r in lines if r["account_code"] == CASH_CODE and r["debit"]}

    acc = {}
    for r in lines:
        code = r["account_code"]
        if code == CASH_CODE:
            continue
        row = acc.setdefault(code, {"debit_cash": 0, "debit_tr": 0, "credit_cash": 0, "credit_tr": 0})
        if r["doc_id"] in cash_out:
            row["debit_cash"] += r["debit"]
        else:
            row["debit_tr"] += r["debit"]
        if r["doc_id"] in cash_in:
            row["credit_cash"] += r["credit"]
        else:
            row["credit_tr"] += r["credit"]

    accounts = conn.execute(
        "SELECT code, name FROM accounts WHERE company_id=? AND is_active=1 ORDER BY code", (book,)
    ).fetchall()

    rows = []
    for a in accounts:
        v = acc.get(a["code"])
        if not v:
            continue
        debit_total = v["debit_cash"] + v["debit_tr"]
        credit_total = v["credit_cash"] + v["credit_tr"]
        if debit_total == 0 and credit_total == 0:
            continue
        rows.append({
            "code": a["code"], "name": a["name"],
            "debit_cash": v["debit_cash"], "debit_tr": v["debit_tr"], "debit_total": debit_total,
            "credit_cash": v["credit_cash"], "credit_tr": v["credit_tr"], "credit_total": credit_total,
        })

    keys = ("debit_cash", "debit_tr", "debit_total", "credit_cash", "credit_tr", "credit_total")
    totals = {k: sum(r[k] for r in rows) for k in keys}

    prev = conn.execute(
        """SELECT COALESCE(SUM(sl.debit - sl.credit), 0) FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code=? AND d.slip_date < ?""",
        (book, CASH_CODE, date_from),
    ).fetchone()[0]
    cash_lines = [r for r in lines if r["account_code"] == CASH_CODE]
    cur = prev + sum(r["debit"] for r in cash_lines) - sum(r["credit"] for r in cash_lines)
    totals["prev"], totals["cur"] = prev, cur
    totals["debit_sum"] = totals["debit_total"] + cur
    totals["credit_sum"] = totals["credit_total"] + prev
    return rows, totals


@router.get("/ledger/daily", response_class=HTMLResponse)
async def daily_ledger(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                       mode: str = "day", date_from: str = "", date_to: str = ""):
    date_from, date_to = _daily_period(mode, date_from, date_to)
    rows, totals = _daily_data(conn, u["book"], date_from, date_to)

    return templates.TemplateResponse(request=request, name="erp/ledger_daily.html", context={
        "request": request, "page_title": "일계표/월계표", "user_name": u["name"],
        "mode": mode, "date_from": date_from, "date_to": date_to,
        "rows": rows, "totals": totals,
    })


@router.get("/ledger/daily/excel")
async def daily_ledger_excel(u: dict = Depends(require_book), conn=Depends(get_db),
                             mode: str = "day", date_from: str = "", date_to: str = ""):
    date_from, date_to = _daily_period(mode, date_from, date_to)
    rows, totals = _daily_data(conn, u["book"], date_from, date_to)

    buf = io.StringIO()
    buf.write('﻿')
    writer = csv.writer(buf)
    writer.writerow(["계정코드", "계정명", "차변계", "차변대체", "차변현금", "대변현금", "대변대체", "대변계"])
    for r in rows:
        writer.writerow([esc_cell(v) for v in [
            r["code"], r["name"], r["debit_total"], r["debit_tr"], r["debit_cash"],
            r["credit_cash"], r["credit_tr"], r["credit_total"],
        ]])
    writer.writerow(["소계", "", totals["debit_total"], totals["debit_tr"], totals["debit_cash"],
                     totals["credit_cash"], totals["credit_tr"], totals["credit_total"]])
    writer.writerow(["현금잔고", "", totals["cur"], "", "금일", "전일", "", totals["prev"]])
    writer.writerow(["합계", "", totals["debit_sum"], "", "", "", "", totals["credit_sum"]])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=daily_ledger.csv"},
    )


def _cash_data(conn, book, date_from, date_to):
    opening = 0
    if date_from:
        opening = conn.execute(
            """SELECT COALESCE(SUM(sl.debit - sl.credit), 0) as v
               FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
               WHERE d.company_id=? AND d.status='done' AND sl.account_code=? AND d.slip_date < ?""",
            (book, CASH_CODE, date_from),
        ).fetchone()["v"]

    conds = ["d.company_id=?", "d.status='done'", "sl.account_code=?"]
    params = [book, CASH_CODE]
    if date_from:
        conds.append("d.slip_date >= ?")
        params.append(date_from)
    if date_to:
        conds.append("d.slip_date <= ?")
        params.append(date_to)
    where = " AND ".join(conds)

    lines = conn.execute(
        f"""SELECT d.slip_date, d.id as doc_id, d.doc_number, sl.summary, sl.partner, sl.debit, sl.credit
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE {where}
            ORDER BY d.slip_date, d.id, sl.line_no""",
        params,
    ).fetchall()

    bal = opening
    rows = []
    for r in lines:
        r = dict(r)
        bal += r["debit"] - r["credit"]
        r["bal"] = bal
        rows.append(r)

    period_in = sum(r["debit"] for r in rows)
    period_out = sum(r["credit"] for r in rows)

    cum = conn.execute(
        """SELECT COALESCE(SUM(sl.debit),0) as cum_in, COALESCE(SUM(sl.credit),0) as cum_out
           FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code=? AND d.slip_date <= ?""",
        (book, CASH_CODE, date_to or today_kst().isoformat()),
    ).fetchone()

    return rows, opening, period_in, period_out, cum["cum_in"], cum["cum_out"]


@router.get("/ledger/cash", response_class=HTMLResponse)
async def cash_ledger(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                      date_from: str = "", date_to: str = ""):
    rows, opening, period_in, period_out, cum_in, cum_out = _cash_data(conn, u["book"], date_from, date_to)

    return templates.TemplateResponse(request=request, name="erp/ledger_cash.html", context={
        "request": request, "page_title": "현금출납장", "user_name": u["name"],
        "date_from": date_from, "date_to": date_to,
        "rows": rows, "opening": opening,
        "period_in": period_in, "period_out": period_out,
        "cum_in": cum_in, "cum_out": cum_out,
    })


@router.get("/ledger/cash/excel")
async def cash_ledger_excel(u: dict = Depends(require_book), conn=Depends(get_db),
                            date_from: str = "", date_to: str = ""):
    rows, opening, period_in, period_out, cum_in, cum_out = _cash_data(conn, u["book"], date_from, date_to)

    buf = io.StringIO()
    buf.write('﻿')
    writer = csv.writer(buf)
    writer.writerow(["일자", "전표번호", "적요", "거래처", "입금", "출금", "잔액"])
    if date_from:
        writer.writerow([date_from, "", "전기이월", "", "", "", opening])
    for r in rows:
        writer.writerow([esc_cell(v) for v in [
            r["slip_date"], r["doc_number"] or "", r["summary"] or "", r["partner"] or "",
            r["debit"] or "", r["credit"] or "", r["bal"],
        ]])
    writer.writerow(["", "", "월계", "", period_in, period_out, rows[-1]["bal"] if rows else opening])
    writer.writerow(["", "", "누계", "", cum_in, cum_out, rows[-1]["bal"] if rows else opening])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=cash_ledger.csv"},
    )


def _journal_data(conn, book, date_from, date_to):
    today = today_kst()
    if not date_from:
        date_from = today.replace(day=1).isoformat()
    if not date_to:
        last_day = calendar.monthrange(today.year, today.month)[1]
        date_to = today.replace(day=last_day).isoformat()

    rows = conn.execute(
        """SELECT d.slip_date, d.id as doc_id, d.doc_number,
                  sl.account_code, sl.account_name, sl.summary, sl.partner, sl.debit, sl.credit
           FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
           WHERE d.company_id=? AND d.status='done' AND d.slip_date BETWEEN ? AND ?
           ORDER BY d.slip_date, d.id, sl.line_no""",
        (book, date_from, date_to),
    ).fetchall()
    rows = [dict(r) for r in rows]
    total_debit = sum(r["debit"] for r in rows)
    total_credit = sum(r["credit"] for r in rows)
    return date_from, date_to, rows, total_debit, total_credit


@router.get("/ledger/journal", response_class=HTMLResponse)
async def journal_ledger(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                         date_from: str = "", date_to: str = ""):
    date_from, date_to, rows, total_debit, total_credit = _journal_data(conn, u["book"], date_from, date_to)

    return templates.TemplateResponse(request=request, name="erp/ledger_journal.html", context={
        "request": request, "page_title": "분개장", "user_name": u["name"],
        "date_from": date_from, "date_to": date_to,
        "rows": rows, "total_debit": total_debit, "total_credit": total_credit,
    })


@router.get("/ledger/journal/excel")
async def journal_ledger_excel(u: dict = Depends(require_book), conn=Depends(get_db),
                               date_from: str = "", date_to: str = ""):
    date_from, date_to, rows, total_debit, total_credit = _journal_data(conn, u["book"], date_from, date_to)

    buf = io.StringIO()
    buf.write('﻿')
    writer = csv.writer(buf)
    writer.writerow(["일자", "전표번호", "계정코드", "계정명", "적요", "거래처", "차변", "대변"])
    for r in rows:
        writer.writerow([esc_cell(v) for v in [
            r["slip_date"], r["doc_number"] or "", r["account_code"], r["account_name"],
            r["summary"] or "", r["partner"] or "", r["debit"] or "", r["credit"] or "",
        ]])
    writer.writerow(["", "", "", "", "", "합계", total_debit, total_credit])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=journal_ledger.csv"},
    )


def _partner_balance_data(conn, book, account_code, date_from, date_to):
    if not account_code:
        return [], {}

    acct = conn.execute(
        "SELECT name, is_debit FROM accounts WHERE company_id=? AND code=?", (book, account_code)
    ).fetchone()
    is_debit = acct["is_debit"] if acct else 1

    opening = {}
    if date_from:
        for r in conn.execute(
            """SELECT COALESCE(sl.partner_id,'n:'||sl.partner) as pkey, COALESCE(p.name, sl.partner) as name,
                      SUM(sl.debit) as d, SUM(sl.credit) as c
               FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
               LEFT JOIN partners p ON sl.partner_id=p.id
               WHERE d.company_id=? AND d.status='done' AND sl.account_code=? AND sl.partner != '' AND d.slip_date < ?
               GROUP BY pkey""",
            (book, account_code, date_from),
        ).fetchall():
            bal = r["d"] - r["c"] if is_debit else r["c"] - r["d"]
            opening[r["pkey"]] = {"name": r["name"], "bal": bal}

    conds = ["d.company_id=?", "d.status='done'", "sl.account_code=?", "sl.partner != ''"]
    params = [book, account_code]
    if date_from:
        conds.append("d.slip_date >= ?")
        params.append(date_from)
    if date_to:
        conds.append("d.slip_date <= ?")
        params.append(date_to)
    where = " AND ".join(conds)

    period = {}
    for r in conn.execute(
        f"""SELECT COALESCE(sl.partner_id,'n:'||sl.partner) as pkey, COALESCE(p.name, sl.partner) as name,
                   SUM(sl.debit) as d, SUM(sl.credit) as c
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            LEFT JOIN partners p ON sl.partner_id=p.id
            WHERE {where}
            GROUP BY pkey""",
        params,
    ).fetchall():
        period[r["pkey"]] = {"name": r["name"], "d": r["d"], "c": r["c"]}

    rows = []
    for k in set(opening) | set(period):
        name = (period.get(k) or {}).get("name") or (opening.get(k) or {}).get("name")
        ob = (opening.get(k) or {}).get("bal", 0)
        d = (period.get(k) or {}).get("d", 0)
        c = (period.get(k) or {}).get("c", 0)
        bal = ob + (d - c if is_debit else c - d)
        if ob == 0 and d == 0 and c == 0:
            continue
        rows.append({"partner": name, "opening": ob, "debit": d, "credit": c, "balance": bal})
    rows.sort(key=lambda r: r["partner"])

    totals = {k: sum(r[k] for r in rows) for k in ("opening", "debit", "credit", "balance")}
    return rows, totals


@router.get("/ledger/partner-balance", response_class=HTMLResponse)
async def partner_balance_ledger(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                                 account: str = "", date_from: str = "", date_to: str = ""):
    book = u["book"]
    accounts = conn.execute(
        "SELECT code, name FROM accounts WHERE company_id=? AND is_active=1 AND req_partner=1 ORDER BY code", (book,)
    ).fetchall()
    rows, totals = _partner_balance_data(conn, book, account, date_from, date_to)
    acct_name = next((a["name"] for a in accounts if a["code"] == account), "")

    return templates.TemplateResponse(request=request, name="erp/ledger_partner_balance.html", context={
        "request": request, "page_title": "거래처계정잔액", "user_name": u["name"],
        "accounts": accounts, "account_code": account, "acct_name": acct_name,
        "date_from": date_from, "date_to": date_to,
        "rows": rows, "totals": totals,
    })


@router.get("/ledger/partner-balance/excel")
async def partner_balance_ledger_excel(u: dict = Depends(require_book), conn=Depends(get_db),
                                       account: str = "", date_from: str = "", date_to: str = ""):
    rows, totals = _partner_balance_data(conn, u["book"], account, date_from, date_to)

    buf = io.StringIO()
    buf.write('﻿')
    writer = csv.writer(buf)
    writer.writerow(["거래처", "전기이월", "차변", "대변", "잔액"])
    for r in rows:
        writer.writerow([esc_cell(v) for v in [
            r["partner"], r["opening"] or "", r["debit"] or "", r["credit"] or "", r["balance"],
        ]])
    if rows:
        writer.writerow(["합계", totals["opening"], totals["debit"], totals["credit"], totals["balance"]])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=partner_balance.csv"},
    )


def _dept_pnl_period(year, month):
    if month:
        last_day = calendar.monthrange(year, month)[1]
        return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"
    return f"{year}-01-01", f"{year}-12-31"


def _dept_pnl_data(conn, book, date_from, date_to):
    rows = conn.execute(
        """SELECT COALESCE(sl.dept, '') AS dept, a.category,
                  COALESCE(SUM(sl.debit),0) AS d, COALESCE(SUM(sl.credit),0) AS c
           FROM slip_lines sl
           JOIN erp_docs ed ON sl.doc_id = ed.id
           JOIN accounts a ON a.company_id = ed.company_id AND a.code = sl.account_code
           WHERE ed.company_id=? AND ed.status='done' AND ed.slip_date BETWEEN ? AND ?
             AND a.category IN ('수익','비용')
           GROUP BY COALESCE(sl.dept, ''), a.category""",
        (book, date_from, date_to),
    ).fetchall()

    by_dept = {}
    for r in rows:
        row = by_dept.setdefault(r["dept"], {"revenue": 0, "expense": 0})
        if r["category"] == "수익":
            row["revenue"] += r["c"] - r["d"]
        else:
            row["expense"] += r["d"] - r["c"]

    names = [r["name"] for r in conn.execute(
        "SELECT name FROM depts WHERE company_id=? AND is_active=1 ORDER BY sort, name", (book,)
    ).fetchall()]

    result = []
    for name in names + [""]:
        v = by_dept.pop(name, {"revenue": 0, "expense": 0})
        result.append({"dept": name or "미지정", "revenue": v["revenue"], "expense": v["expense"],
                       "income": v["revenue"] - v["expense"]})
    # 마스터에서 빠진 부서명(개정 전 이력 등)도 그대로 노출
    for name, v in sorted(by_dept.items()):
        result.append({"dept": name, "revenue": v["revenue"], "expense": v["expense"],
                       "income": v["revenue"] - v["expense"]})

    totals = {"revenue": sum(r["revenue"] for r in result), "expense": sum(r["expense"] for r in result),
              "income": sum(r["income"] for r in result)}
    return result, totals


@router.get("/ledger/dept-pnl", response_class=HTMLResponse)
async def dept_pnl(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                   year: int = 0, month: int = 0):
    year = year or today_kst().year
    month = month if 1 <= month <= 12 else 0
    date_from, date_to = _dept_pnl_period(year, month)
    rows, totals = _dept_pnl_data(conn, u["book"], date_from, date_to)

    return templates.TemplateResponse(request=request, name="erp/ledger_dept_pnl.html", context={
        "request": request, "page_title": "부문별 손익", "user_name": u["name"],
        "year": year, "month": month, "rows": rows, "totals": totals,
    })
