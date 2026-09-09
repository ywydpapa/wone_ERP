from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
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
    health = payslip["health_insurance"]
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
        (doc_id, line_no, "[601] 급여", "601", gross, 0, "", summary),
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
            (doc_id, line_no, "[263] 예수금-소득세", "263", 0, income_tax, "", summary),
        )
        line_no += 1

    if pension > 0:
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, line_no, "[264] 예수금-국민연금", "264", 0, pension, "", summary),
        )
        line_no += 1

    if health > 0:
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, line_no, "[265] 예수금-건강보험", "265", 0, health, "", summary),
        )
        line_no += 1

    if employment > 0:
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, line_no, "[266] 예수금-고용보험", "266", 0, employment, "", summary),
        )


@router.get("/ledger/purchase", response_class=HTMLResponse)
async def purchase_ledger(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    date_from = request.query_params.get("from", "")
    date_to = request.query_params.get("to", "")
    partner = request.query_params.get("partner", "")

    sql = """SELECT sl.*, ed.doc_number, ed.slip_date, ed.title as doc_title
             FROM slip_lines sl
             JOIN erp_docs ed ON sl.doc_id=ed.id
             WHERE sl.account_code IN ('120','130','131','501','502')
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
async def ar_ap(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    ar_rows = conn.execute(
        """SELECT partner, SUM(debit) as total_debit, SUM(credit) as total_credit
           FROM slip_lines
           WHERE account_code='110' AND partner != ''
           GROUP BY partner
           HAVING SUM(debit) - SUM(credit) != 0
           ORDER BY partner"""
    ).fetchall()
    ar_list = []
    ar_total = 0
    for r in ar_rows:
        balance = r["total_debit"] - r["total_credit"]
        ar_list.append({"partner": r["partner"], "debit": r["total_debit"], "credit": r["total_credit"], "balance": balance})
        ar_total += balance

    ap_rows = conn.execute(
        """SELECT partner, SUM(debit) as total_debit, SUM(credit) as total_credit
           FROM slip_lines
           WHERE account_code='201' AND partner != ''
           GROUP BY partner
           HAVING SUM(credit) - SUM(debit) != 0
           ORDER BY partner"""
    ).fetchall()
    ap_list = []
    ap_total = 0
    for r in ap_rows:
        balance = r["total_credit"] - r["total_debit"]
        ap_list.append({"partner": r["partner"], "debit": r["total_debit"], "credit": r["total_credit"], "balance": balance})
        ap_total += balance

    return templates.TemplateResponse(request=request, name="erp/ledger_ar_ap.html", context={
        "request": request, "page_title": "채권/채무 현황",
        "user_name": u["name"],
        "ar_list": ar_list, "ar_total": ar_total,
        "ap_list": ap_list, "ap_total": ap_total,
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
           WHERE sl.account_code LIKE '4%' AND sl.credit > 0
             AND ed.slip_date LIKE ?
           GROUP BY SUBSTR(ed.slip_date,6,2)
           ORDER BY mon""",
        (f"{year}-%",),
    ).fetchall()
    revenue = {r["mon"]: r["amt"] for r in revenue_rows}

    expense_rows = conn.execute(
        """SELECT SUBSTR(ed.slip_date,6,2) as mon, SUM(sl.debit) as amt
           FROM slip_lines sl JOIN erp_docs ed ON sl.doc_id=ed.id
           WHERE (sl.account_code LIKE '5%' OR sl.account_code LIKE '6%'
                  OR sl.account_code LIKE '7%' OR sl.account_code LIKE '8%')
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
