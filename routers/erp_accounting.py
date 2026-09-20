import calendar
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from core.deps import get_db, require_login, templates
from core.tz import today_kst

router = APIRouter()


def _create_payroll_slip(conn, payslip, employee_name, uid):
    year = payslip["pay_year"]
    month = payslip["pay_month"]
    gross = payslip["gross_pay"]
    net = payslip["net_pay"]
    income_tax = payslip["income_tax"] + payslip["resident_tax"]
    pension = payslip["national_pension"]
    health = payslip["health_insurance"] + (payslip.get("long_care") or 0)
    employment = payslip["employment_insurance"]

    title = f"급여 전표 ({employee_name} {year}.{month:02d})"
    cur = conn.execute(
        """INSERT INTO erp_docs (user_id, doc_type, title, content, status, slip_type, slip_date, slip_total)
           VALUES (?,?,?,?,?,?,?,?)""",
        (uid, "expense", title, f"{employee_name} {year}년 {month}월 급여 자동 전표", "done", "대체",
         f"{year}-{month:02d}-25", gross),
    )
    doc_id = cur.lastrowid
    doc_number = f"PAY-{year}-{doc_id:04d}"
    conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, doc_id))

    summary = f"{employee_name} {month}월 급여"
    line_no = 1

    conn.execute(
        "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
        (doc_id, line_no, "[801] 급여", "801", gross, 0, "", summary),
    )
    line_no += 1

    conn.execute(
        "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
        (doc_id, line_no, "[103] 보통예금", "103", 0, net, "", summary),
    )
    line_no += 1

    if income_tax > 0:
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, line_no, "[261] 예수금-소득세", "261", 0, income_tax, "", summary),
        )
        line_no += 1

    if pension > 0:
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, line_no, "[262] 예수금-국민연금", "262", 0, pension, "", summary),
        )
        line_no += 1

    if health > 0:
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, line_no, "[263] 예수금-건강보험", "263", 0, health, "", summary),
        )
        line_no += 1

    if employment > 0:
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, line_no, "[264] 예수금-고용보험", "264", 0, employment, "", summary),
        )


@router.get("/ledger/purchase", response_class=HTMLResponse)
async def purchase_ledger(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    date_from = request.query_params.get("from", "")
    date_to = request.query_params.get("to", "")
    partner = request.query_params.get("partner", "")

    sql = """SELECT sl.*, ed.doc_number, ed.slip_date, ed.title as doc_title
             FROM slip_lines sl
             JOIN erp_docs ed ON sl.doc_id=ed.id
             WHERE sl.account_code IN ('120','124','125','451','452')
               AND sl.debit > 0"""
    params = []
    if date_from:
        sql += " AND ed.slip_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND ed.slip_date <= ?"
        params.append(date_to)
    if partner:
        sql += " AND sl.partner LIKE ?"
        params.append(f"%{partner}%")
    sql += " ORDER BY ed.slip_date DESC, sl.doc_id DESC, sl.line_no"

    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    total = sum(r["debit"] for r in rows)

    partners = [r[0] for r in conn.execute(
        "SELECT DISTINCT partner FROM slip_lines WHERE partner != '' ORDER BY partner"
    ).fetchall()]

    return templates.TemplateResponse(request=request, name="erp/ledger_purchase.html", context={
        "request": request, "page_title": "매입장",
        "user_name": u["name"],
        "rows": rows, "total": total,
        "partners": partners,
        "date_from": date_from, "date_to": date_to, "partner_filter": partner,
    })


@router.get("/ledger/sales", response_class=HTMLResponse)
async def sales_ledger(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    date_from = request.query_params.get("from", "")
    date_to = request.query_params.get("to", "")
    partner = request.query_params.get("partner", "")

    sql = """SELECT sl.*, ed.doc_number, ed.slip_date, ed.title as doc_title
             FROM slip_lines sl
             JOIN erp_docs ed ON sl.doc_id=ed.id
             WHERE sl.account_code IN ('401','402','403')
               AND sl.credit > 0"""
    params = []
    if date_from:
        sql += " AND ed.slip_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND ed.slip_date <= ?"
        params.append(date_to)
    if partner:
        sql += " AND sl.partner LIKE ?"
        params.append(f"%{partner}%")
    sql += " ORDER BY ed.slip_date DESC, sl.doc_id DESC, sl.line_no"

    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    total = sum(r["credit"] for r in rows)

    partners = [r[0] for r in conn.execute(
        "SELECT DISTINCT partner FROM slip_lines WHERE partner != '' ORDER BY partner"
    ).fetchall()]

    return templates.TemplateResponse(request=request, name="erp/ledger_sales.html", context={
        "request": request, "page_title": "매출장",
        "user_name": u["name"],
        "rows": rows, "total": total,
        "partners": partners,
        "date_from": date_from, "date_to": date_to, "partner_filter": partner,
    })


@router.get("/ledger/ar-ap", response_class=HTMLResponse)
async def ar_ap(request: Request, u: dict = Depends(require_login), conn=Depends(get_db),
                partner: str = "", date_from: str = "", date_to: str = ""):
    partners = [r[0] for r in conn.execute(
        "SELECT DISTINCT partner FROM slip_lines WHERE partner != '' ORDER BY partner"
    ).fetchall()]

    rows = []
    opening_balance = 0
    period_debit = 0
    period_credit = 0
    summary_list = []
    summary_total = 0

    if partner:
        # 기초잔액 (date_from 이전)
        if date_from:
            ob = conn.execute("""
                SELECT COALESCE(SUM(sl.debit),0) - COALESCE(SUM(sl.credit),0)
                FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
                WHERE sl.partner=? AND sl.account_code IN ('110','251') AND d.slip_date < ?
            """, [partner, date_from]).fetchone()
            opening_balance = ob[0] if ob else 0

        conds = ["sl.partner = ?", "sl.account_code IN ('110','251')"]
        params = [partner]
        if date_from:
            conds.append("d.slip_date >= ?")
            params.append(date_from)
        if date_to:
            conds.append("d.slip_date <= ?")
            params.append(date_to)
        where = " AND ".join(conds)
        rows = conn.execute(f"""
            SELECT d.id as doc_id, d.slip_date, d.doc_number,
                   sl.account_code, sl.summary, sl.debit, sl.credit
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE {where}
            ORDER BY d.slip_date, d.id, sl.line_no
        """, params).fetchall()

        bal = opening_balance
        rows = [dict(r) for r in rows]
        for r in rows:
            if r["account_code"] == '110':
                bal += r["debit"] - r["credit"]
            else:
                bal += r["credit"] - r["debit"]
            r["bal"] = bal
        period_debit = sum(r["debit"] for r in rows)
        period_credit = sum(r["credit"] for r in rows)
    else:
        # 요약 뷰: 거래처별 채권/채무 합산
        conds = ["sl.partner != ''", "sl.account_code IN ('110','251')"]
        params = []
        if date_from:
            conds.append("d.slip_date >= ?")
            params.append(date_from)
        if date_to:
            conds.append("d.slip_date <= ?")
            params.append(date_to)
        where = " AND ".join(conds)
        sum_rows = conn.execute(f"""
            SELECT sl.partner,
                   SUM(CASE WHEN sl.account_code='110' THEN sl.debit ELSE 0 END) as ar_debit,
                   SUM(CASE WHEN sl.account_code='110' THEN sl.credit ELSE 0 END) as ar_credit,
                   SUM(CASE WHEN sl.account_code='251' THEN sl.credit ELSE 0 END) as ap_credit,
                   SUM(CASE WHEN sl.account_code='251' THEN sl.debit ELSE 0 END) as ap_debit
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE {where}
            GROUP BY sl.partner
            ORDER BY sl.partner
        """, params).fetchall()
        for r in sum_rows:
            ar_bal = r["ar_debit"] - r["ar_credit"]
            ap_bal = r["ap_credit"] - r["ap_debit"]
            net = ar_bal - ap_bal
            summary_list.append({
                "partner": r["partner"],
                "ar_bal": ar_bal,
                "ap_bal": ap_bal,
                "net": net,
            })
            summary_total += net

    return templates.TemplateResponse(request=request, name="erp/ledger_ar_ap.html", context={
        "request": request, "page_title": "거래처원장",
        "user_name": u["name"],
        "partners": partners,
        "partner": partner,
        "date_from": date_from,
        "date_to": date_to,
        "rows": rows,
        "opening_balance": opening_balance,
        "period_debit": period_debit,
        "period_credit": period_credit,
        "summary_list": summary_list,
        "summary_total": summary_total,
    })


@router.get("/ledger/pnl", response_class=HTMLResponse)
async def pnl_summary(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    year = request.query_params.get("year", "")
    if not year:
        year = today_kst().year
    else:
        year = int(year)

    revenue_rows = conn.execute(
        """SELECT SUBSTR(ed.slip_date,6,2) as mon, SUM(sl.credit) as amt
           FROM slip_lines sl JOIN erp_docs ed ON sl.doc_id=ed.id
           WHERE sl.account_code BETWEEN '401' AND '403' AND sl.credit > 0
             AND ed.slip_date LIKE ?
           GROUP BY SUBSTR(ed.slip_date,6,2)
           ORDER BY mon""",
        (f"{year}-%",),
    ).fetchall()
    revenue = {r["mon"]: r["amt"] for r in revenue_rows}

    expense_rows = conn.execute(
        """SELECT SUBSTR(ed.slip_date,6,2) as mon, SUM(sl.debit) as amt
           FROM slip_lines sl JOIN erp_docs ed ON sl.doc_id=ed.id
           WHERE (sl.account_code BETWEEN '451' AND '503'
                  OR sl.account_code BETWEEN '801' AND '899'
                  OR sl.account_code BETWEEN '951' AND '990')
             AND sl.debit > 0
             AND ed.slip_date LIKE ?
           GROUP BY SUBSTR(ed.slip_date,6,2)
           ORDER BY mon""",
        (f"{year}-%",),
    ).fetchall()
    expense = {r["mon"]: r["amt"] for r in expense_rows}

    months = []
    total_rev = 0
    total_exp = 0
    for m in range(1, 13):
        mk = f"{m:02d}"
        rev = revenue.get(mk, 0)
        exp = expense.get(mk, 0)
        total_rev += rev
        total_exp += exp
        months.append({"month": m, "revenue": rev, "expense": exp, "profit": rev - exp})

    return templates.TemplateResponse(request=request, name="erp/ledger_pnl.html", context={
        "request": request, "page_title": "월별 손익 요약",
        "user_name": u["name"],
        "year": year, "months": months,
        "total_revenue": total_rev, "total_expense": total_exp,
        "total_profit": total_rev - total_exp,
    })


@router.get("/ledger/general", response_class=HTMLResponse)
async def general_ledger(request: Request, u: dict = Depends(require_login), conn=Depends(get_db),
                         account_code: str = "", date_from: str = "", date_to: str = ""):
    accounts = conn.execute(
        "SELECT code, name, category, is_debit FROM accounts WHERE is_active=1 ORDER BY code"
    ).fetchall()
    acct_groups = []
    for a in accounts:
        if not acct_groups or acct_groups[-1][0] != a["category"]:
            acct_groups.append((a["category"], []))
        acct_groups[-1][1].append(a)

    rows = []
    opening_debit = 0
    opening_credit = 0

    if account_code:
        conditions = ["sl.account_code = ?"]
        params = [account_code]

        if date_from:
            opening = conn.execute("""
                SELECT COALESCE(SUM(sl.debit),0), COALESCE(SUM(sl.credit),0)
                FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
                WHERE sl.account_code=? AND d.slip_date < ?
            """, [account_code, date_from]).fetchone()
            opening_debit, opening_credit = opening[0], opening[1]
            conditions.append("d.slip_date >= ?")
            params.append(date_from)

        if date_to:
            conditions.append("d.slip_date <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)
        rows = conn.execute(f"""
            SELECT d.id as doc_id, d.slip_date, d.doc_number, d.title,
                   sl.summary, sl.partner, sl.debit, sl.credit
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE {where}
            ORDER BY d.slip_date, d.id, sl.line_no
        """, params).fetchall()

    acct = None
    if account_code:
        acct = conn.execute(
            "SELECT code, name, is_debit FROM accounts WHERE code=?", [account_code]
        ).fetchone()

    # 누적 잔액 계산
    display_rows = []
    if acct:
        is_debit = acct["is_debit"]
        bal = (opening_debit - opening_credit) if is_debit else (opening_credit - opening_debit)
        for r in rows:
            r = dict(r)
            bal = bal + r["debit"] - r["credit"] if is_debit else bal + r["credit"] - r["debit"]
            r["bal"] = bal
            display_rows.append(r)
    else:
        display_rows = [dict(r) for r in rows]

    period_debit = sum(r["debit"] for r in display_rows)
    period_credit = sum(r["credit"] for r in display_rows)

    return templates.TemplateResponse(request=request, name="erp/general_ledger.html", context={
        "request": request,
        "user_name": u["name"],
        "acct_groups": acct_groups,
        "rows": display_rows,
        "acct": acct,
        "account_code": account_code,
        "date_from": date_from,
        "date_to": date_to,
        "opening_debit": opening_debit,
        "opening_credit": opening_credit,
        "period_debit": period_debit,
        "period_credit": period_credit,
    })


@router.get("/ledger/trial-balance", response_class=HTMLResponse)
async def trial_balance(request: Request, u: dict = Depends(require_login), conn=Depends(get_db),
                        date_from: str = "", date_to: str = ""):
    today = today_kst()
    if not date_from:
        date_from = today.replace(day=1).isoformat()
    if not date_to:
        last_day = calendar.monthrange(today.year, today.month)[1]
        date_to = today.replace(day=last_day).isoformat()

    query = """
        SELECT a.code, a.name, a.category, a.is_debit,
               COALESCE(SUM(CASE WHEN d.slip_date < ? THEN sl.debit ELSE 0 END),0) as prev_debit,
               COALESCE(SUM(CASE WHEN d.slip_date < ? THEN sl.credit ELSE 0 END),0) as prev_credit,
               COALESCE(SUM(CASE WHEN d.slip_date BETWEEN ? AND ? THEN sl.debit ELSE 0 END),0) as period_debit,
               COALESCE(SUM(CASE WHEN d.slip_date BETWEEN ? AND ? THEN sl.credit ELSE 0 END),0) as period_credit
        FROM accounts a
        LEFT JOIN slip_lines sl ON sl.account_code = a.code
        LEFT JOIN erp_docs d ON sl.doc_id = d.id
        WHERE a.is_active = 1
        GROUP BY a.code, a.name, a.category, a.is_debit
        HAVING prev_debit > 0 OR prev_credit > 0 OR period_debit > 0 OR period_credit > 0
        ORDER BY a.code
    """
    raw = conn.execute(query, [date_from, date_from, date_from, date_to, date_from, date_to]).fetchall()

    result = []
    for r in raw:
        if r["is_debit"]:
            prev_bal = r["prev_debit"] - r["prev_credit"]
            closing_bal = prev_bal + r["period_debit"] - r["period_credit"]
        else:
            prev_bal = r["prev_credit"] - r["prev_debit"]
            closing_bal = prev_bal + r["period_credit"] - r["period_debit"]
        result.append({
            "code": r["code"], "name": r["name"], "category": r["category"],
            "prev_bal": prev_bal,
            "period_debit": r["period_debit"], "period_credit": r["period_credit"],
            "closing_bal": closing_bal,
        })

    # 카테고리 소계 삽입
    grouped = []
    cur_cat = ""
    sub = {"prev": 0, "debit": 0, "credit": 0, "closing": 0}
    for r in result:
        if r["category"] != cur_cat:
            if cur_cat:
                grouped.append({"_type": "subtotal", "category": cur_cat, **sub})
                sub = {"prev": 0, "debit": 0, "credit": 0, "closing": 0}
            grouped.append({"_type": "header", "category": r["category"]})
            cur_cat = r["category"]
        sub["prev"] += r["prev_bal"]
        sub["debit"] += r["period_debit"]
        sub["credit"] += r["period_credit"]
        sub["closing"] += r["closing_bal"]
        r["_type"] = "row"
        grouped.append(r)
    if cur_cat:
        grouped.append({"_type": "subtotal", "category": cur_cat, **sub})

    totals = {
        "prev": sum(r["prev_bal"] for r in result),
        "debit": sum(r["period_debit"] for r in result),
        "credit": sum(r["period_credit"] for r in result),
        "closing": sum(r["closing_bal"] for r in result),
    }

    return templates.TemplateResponse(request=request, name="erp/trial_balance.html", context={
        "request": request,
        "user_name": u["name"],
        "rows": result,
        "grouped": grouped,
        "totals": totals,
        "date_from": date_from,
        "date_to": date_to,
    })


@router.get("/tax-invoices", response_class=HTMLResponse)
async def tax_invoice_list(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    inv_type = request.query_params.get("type", "")

    sales_sql = """SELECT ed.id, ed.doc_number, ed.title, ed.slip_date, ed.slip_total, ed.status,
                          '매출' as inv_type
                   FROM erp_docs ed
                   WHERE ed.doc_number LIKE 'SAL-%'
                   ORDER BY ed.slip_date DESC"""
    sales_rows = [dict(r) for r in conn.execute(sales_sql).fetchall()]

    purchase_sql = """SELECT ed.id, ed.doc_number, ed.title, ed.slip_date, ed.slip_total, ed.status,
                            '매입' as inv_type
                      FROM erp_docs ed
                      WHERE ed.doc_number LIKE 'EXP-%'
                        AND ed.title LIKE '입고 전표%'
                      ORDER BY ed.slip_date DESC"""
    purchase_rows = [dict(r) for r in conn.execute(purchase_sql).fetchall()]

    if inv_type == "sales":
        rows = sales_rows
    elif inv_type == "purchase":
        rows = purchase_rows
    else:
        rows = sorted(sales_rows + purchase_rows, key=lambda x: x.get("slip_date", ""), reverse=True)

    sales_total = sum(r["slip_total"] for r in sales_rows)
    purchase_total = sum(r["slip_total"] for r in purchase_rows)

    return templates.TemplateResponse(request=request, name="erp/tax_invoice_list.html", context={
        "request": request, "page_title": "세금계산서 관리",
        "user_name": u["name"],
        "rows": rows,
        "sales_total": sales_total, "purchase_total": purchase_total,
        "inv_type": inv_type,
        "sales_count": len(sales_rows), "purchase_count": len(purchase_rows),
    })


@router.get("/tax/purchase-summary", response_class=HTMLResponse)
async def tax_purchase_summary(request: Request, u: dict = Depends(require_login), conn=Depends(get_db),
                               date_from: str = "", date_to: str = ""):
    today = today_kst()
    if not date_from or not date_to:
        q = (today.month - 1) // 3
        q_start_month = q * 3 + 1
        q_end_month = q_start_month + 2
        last_day = calendar.monthrange(today.year, q_end_month)[1]
        if not date_from:
            date_from = date(today.year, q_start_month, 1).isoformat()
        if not date_to:
            date_to = date(today.year, q_end_month, last_day).isoformat()

    # 매입부가세 거래처별 집계
    rows_raw = conn.execute("""
        SELECT
            COALESCE(sl_vat.partner, '') as partner,
            COUNT(DISTINCT d.id) as doc_cnt,
            SUM(sl_vat.debit) as tax_amount,
            SUM(supply.supply_sum) as supply_amount
        FROM erp_docs d
        JOIN slip_lines sl_vat ON sl_vat.doc_id = d.id AND sl_vat.account_code = '135'
        JOIN (
            SELECT doc_id, COALESCE(partner, '') as partner, SUM(debit) as supply_sum
            FROM slip_lines
            WHERE account_code != '135'
            GROUP BY doc_id, COALESCE(partner, '')
        ) supply ON supply.doc_id = d.id AND supply.partner = COALESCE(sl_vat.partner, '')
        WHERE d.slip_date BETWEEN ? AND ?
        GROUP BY COALESCE(sl_vat.partner, '')
        ORDER BY supply_amount DESC
    """, [date_from, date_to]).fetchall()

    rows = [dict(r) for r in rows_raw]
    total_cnt = sum(r["doc_cnt"] for r in rows)
    total_supply = sum(r["supply_amount"] or 0 for r in rows)
    total_tax = sum(r["tax_amount"] or 0 for r in rows)

    return templates.TemplateResponse(request=request, name="erp/tax_purchase_summary.html", context={
        "request": request,
        "user_name": u["name"],
        "rows": rows,
        "date_from": date_from,
        "date_to": date_to,
        "total_cnt": total_cnt,
        "total_supply": total_supply,
        "total_tax": total_tax,
    })


@router.get("/tax/sales-summary", response_class=HTMLResponse)
async def tax_sales_summary(request: Request, u: dict = Depends(require_login), conn=Depends(get_db),
                            date_from: str = "", date_to: str = ""):
    today = today_kst()
    if not date_from or not date_to:
        q = (today.month - 1) // 3
        q_start_month = q * 3 + 1
        q_end_month = q_start_month + 2
        last_day = calendar.monthrange(today.year, q_end_month)[1]
        if not date_from:
            date_from = date(today.year, q_start_month, 1).isoformat()
        if not date_to:
            date_to = date(today.year, q_end_month, last_day).isoformat()

    # 매출부가세 거래처별 집계
    rows_raw = conn.execute("""
        SELECT
            COALESCE(sl_vat.partner, '') as partner,
            COUNT(DISTINCT d.id) as doc_cnt,
            SUM(sl_vat.credit) as tax_amount,
            SUM(supply.supply_sum) as supply_amount
        FROM erp_docs d
        JOIN slip_lines sl_vat ON sl_vat.doc_id = d.id AND sl_vat.account_code = '255'
        JOIN (
            SELECT doc_id, COALESCE(partner, '') as partner, SUM(credit) as supply_sum
            FROM slip_lines
            WHERE account_code != '255'
            GROUP BY doc_id, COALESCE(partner, '')
        ) supply ON supply.doc_id = d.id AND supply.partner = COALESCE(sl_vat.partner, '')
        WHERE d.slip_date BETWEEN ? AND ?
        GROUP BY COALESCE(sl_vat.partner, '')
        ORDER BY supply_amount DESC
    """, [date_from, date_to]).fetchall()

    rows = [dict(r) for r in rows_raw]
    total_cnt = sum(r["doc_cnt"] for r in rows)
    total_supply = sum(r["supply_amount"] or 0 for r in rows)
    total_tax = sum(r["tax_amount"] or 0 for r in rows)

    return templates.TemplateResponse(request=request, name="erp/tax_sales_summary.html", context={
        "request": request,
        "user_name": u["name"],
        "rows": rows,
        "date_from": date_from,
        "date_to": date_to,
        "total_cnt": total_cnt,
        "total_supply": total_supply,
        "total_tax": total_tax,
    })


@router.get("/tax/vat-estimate", response_class=HTMLResponse)
async def tax_vat_estimate(request: Request, u: dict = Depends(require_login), conn=Depends(get_db),
                           date_from: str = "", date_to: str = ""):
    today = today_kst()
    if not date_from or not date_to:
        q = (today.month - 1) // 3
        q_start_month = q * 3 + 1
        q_end_month = q_start_month + 2
        last_day = calendar.monthrange(today.year, q_end_month)[1]
        if not date_from:
            date_from = date(today.year, q_start_month, 1).isoformat()
        if not date_to:
            date_to = date(today.year, q_end_month, last_day).isoformat()

    sales_tax = conn.execute("""
        SELECT COALESCE(SUM(sl.credit), 0) as total
        FROM slip_lines sl
        JOIN erp_docs d ON sl.doc_id = d.id
        WHERE sl.account_code = '255' AND d.slip_date BETWEEN ? AND ?
    """, [date_from, date_to]).fetchone()["total"]

    purchase_tax = conn.execute("""
        SELECT COALESCE(SUM(sl.debit), 0) as total
        FROM slip_lines sl
        JOIN erp_docs d ON sl.doc_id = d.id
        WHERE sl.account_code = '135' AND d.slip_date BETWEEN ? AND ?
    """, [date_from, date_to]).fetchone()["total"]

    estimated = sales_tax - purchase_tax

    return templates.TemplateResponse(request=request, name="erp/tax_vat_estimate.html", context={
        "request": request,
        "user_name": u["name"],
        "date_from": date_from,
        "date_to": date_to,
        "sales_tax": sales_tax,
        "purchase_tax": purchase_tax,
        "estimated": estimated,
    })


@router.get("/fi/closing", response_class=HTMLResponse)
async def fi_closing_list(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    error = request.query_params.get("error", "")

    earliest = conn.execute(
        "SELECT MIN(slip_date) as d FROM erp_docs WHERE slip_date IS NOT NULL AND slip_date != ''"
    ).fetchone()

    months = []
    if earliest and earliest["d"]:
        y, m = int(earliest["d"][:4]), int(earliest["d"][5:7])
        t = today_kst()
        end_y, end_m = t.year, t.month
        while (y, m) <= (end_y, end_m):
            closing = conn.execute(
                "SELECT * FROM fi_closings WHERE year=? AND month=?", [y, m]
            ).fetchone()

            slip_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM erp_docs WHERE slip_date BETWEEN ? AND ?",
                [f"{y}-{m:02d}-01", f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]}"]
            ).fetchone()["cnt"]

            closer_name = ""
            reopener_name = ""
            if closing:
                if closing["closed_by"]:
                    cu = conn.execute("SELECT name FROM users WHERE id=?", [closing["closed_by"]]).fetchone()
                    closer_name = cu["name"] if cu else ""
                if closing["reopened_by"]:
                    ru = conn.execute("SELECT name FROM users WHERE id=?", [closing["reopened_by"]]).fetchone()
                    reopener_name = ru["name"] if ru else ""

            months.append({
                "year": y, "month": m,
                "status": closing["status"] if closing else "open",
                "closing_id": closing["id"] if closing else None,
                "closed_at": (closing["closed_at"][:16] if closing and closing["closed_at"] else ""),
                "closer_name": closer_name,
                "reopened_at": (closing["reopened_at"][:10] if closing and closing["reopened_at"] else ""),
                "reopener_name": reopener_name,
                "reopen_reason": closing["reopen_reason"] if closing else "",
                "slip_count": slip_count,
            })
            m += 1
            if m > 12:
                m = 1
                y += 1

    months.reverse()

    return templates.TemplateResponse(request=request, name="erp/fi_closing.html", context={
        "request": request, "user_name": u["name"],
        "months": months, "error": error,
    })


@router.post("/fi/closing/close")
async def fi_close(request: Request, conn=Depends(get_db), u: dict = Depends(require_login),
                   year: int = Form(...), month: int = Form(...)):
    last_day = calendar.monthrange(year, month)[1]

    check = conn.execute("""
        SELECT COALESCE(SUM(sl.debit),0) as total_d, COALESCE(SUM(sl.credit),0) as total_c
        FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
        WHERE d.slip_date BETWEEN ? AND ?
    """, [f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day}"]).fetchone()
    if check["total_d"] != check["total_c"]:
        return RedirectResponse(f"/fi/closing?error=imbalance", status_code=303)

    conn.execute("""
        INSERT INTO fi_closings (year, month, status, closed_by, closed_at)
        VALUES (?, ?, 'closed', ?, datetime('now','localtime'))
        ON CONFLICT(year, month) DO UPDATE SET
            status='closed', closed_by=excluded.closed_by, closed_at=excluded.closed_at,
            reopened_by=NULL, reopened_at=NULL, reopen_reason=NULL
    """, [year, month, u["id"]])
    conn.commit()
    return RedirectResponse("/fi/closing", status_code=303)


@router.post("/fi/closing/reopen")
async def fi_reopen(request: Request, conn=Depends(get_db), u: dict = Depends(require_login),
                    closing_id: int = Form(...), reason: str = Form(...)):
    conn.execute("""
        UPDATE fi_closings SET status='open', reopened_by=?, reopened_at=datetime('now','localtime'),
               reopen_reason=?
        WHERE id=?
    """, [u["id"], reason, closing_id])
    conn.commit()
    return RedirectResponse("/fi/closing", status_code=303)


@router.get("/report/income-statement", response_class=HTMLResponse)
async def income_statement(request: Request, u: dict = Depends(require_login), conn=Depends(get_db),
                           date_from: str = "", date_to: str = ""):
    today = today_kst()
    if not date_from:
        date_from = f"{today.year}-01-01"
    if not date_to:
        date_to = today.isoformat()

    def _rev(code_start, code_end):
        return conn.execute("""
            SELECT COALESCE(SUM(sl.credit - sl.debit), 0)
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE sl.account_code BETWEEN ? AND ? AND d.slip_date BETWEEN ? AND ?
        """, [code_start, code_end, date_from, date_to]).fetchone()[0]

    def _exp(code_start, code_end):
        return conn.execute("""
            SELECT COALESCE(SUM(sl.debit - sl.credit), 0)
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE sl.account_code BETWEEN ? AND ? AND d.slip_date BETWEEN ? AND ?
        """, [code_start, code_end, date_from, date_to]).fetchone()[0]

    revenue = _rev("401", "403")
    cogs = _exp("451", "503")
    gross_profit = revenue - cogs
    sga = _exp("801", "899")
    operating_income = gross_profit - sga
    other_income = _rev("901", "930")
    other_expense = _exp("951", "990")
    net_income = operating_income + other_income - other_expense

    return templates.TemplateResponse(request=request, name="erp/income_statement.html", context={
        "request": request,
        "user_name": u["name"],
        "date_from": date_from, "date_to": date_to,
        "revenue": revenue, "cogs": cogs, "gross_profit": gross_profit,
        "sga": sga, "operating_income": operating_income,
        "other_income": other_income, "other_expense": other_expense,
        "net_income": net_income,
    })


@router.get("/report/balance-sheet", response_class=HTMLResponse)
async def balance_sheet(request: Request, u: dict = Depends(require_login), conn=Depends(get_db),
                        as_of: str = ""):
    if not as_of:
        as_of = today_kst().isoformat()

    rows = conn.execute("""
        SELECT a.code, a.name, a.category, a.is_debit,
               COALESCE(SUM(sl.debit),0) as total_debit,
               COALESCE(SUM(sl.credit),0) as total_credit
        FROM accounts a
        LEFT JOIN slip_lines sl ON sl.account_code = a.code
        LEFT JOIN erp_docs d ON sl.doc_id = d.id AND d.slip_date <= ?
        WHERE a.is_active = 1
        GROUP BY a.code, a.name, a.category, a.is_debit
        HAVING total_debit > 0 OR total_credit > 0
        ORDER BY a.code
    """, [as_of]).fetchall()

    assets, liabilities, equity = [], [], []
    asset_total = liability_total = equity_total = 0
    income_accts = {}

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
        elif cat in ("수익", "비용"):
            income_accts[r["code"]] = {"cat": cat, "bal": bal}

    rev = sum(v["bal"] for v in income_accts.values() if v["cat"] == "수익")
    exp = sum(v["bal"] for v in income_accts.values() if v["cat"] == "비용")
    net_income = rev - exp
    if net_income != 0:
        equity.append({"code": "-", "name": "당기순이익", "balance": net_income})
        equity_total += net_income

    return templates.TemplateResponse(request=request, name="erp/balance_sheet.html", context={
        "request": request,
        "user_name": u["name"],
        "as_of": as_of,
        "assets": assets, "liabilities": liabilities, "equity": equity,
        "asset_total": asset_total, "liability_total": liability_total,
        "equity_total": equity_total,
        "is_balanced": asset_total == liability_total + equity_total,
    })
