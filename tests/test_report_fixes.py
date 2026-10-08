import re

from core import books


def _num(html, label):
    m = re.search(label + r".*?([\-0-9,]+)\s*</td>", html, re.S)
    assert m, f"{label} 라인을 찾을 수 없습니다"
    return int(m.group(1).replace(",", ""))


def test_cash_flow_ties_out(db, seed, login):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    d = "2026-06-15"
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','거래처가',?)", (a,)).lastrowid

    slips = [
        ([{"code": "103", "debit": 10_000_000, "credit": 0},
          {"code": "331", "debit": 0, "credit": 10_000_000}], "자본금 출자"),
        ([{"code": "103", "debit": 5_000_000, "credit": 0},
          {"code": "291", "debit": 0, "credit": 5_000_000}], "장기차입금 실행"),
        ([{"code": "103", "debit": 2_000_000, "credit": 0},
          {"code": "259", "debit": 0, "credit": 2_000_000}], "단기차입금 실행"),
        ([{"code": "206", "debit": 3_000_000, "credit": 0},
          {"code": "103", "debit": 0, "credit": 3_000_000}], "비품 구입"),
        ([{"code": "110", "debit": 1_100_000, "credit": 0, "partner_id": pid},
          {"code": "401", "debit": 0, "credit": 1_000_000},
          {"code": "255", "debit": 0, "credit": 100_000}], "외상매출"),
        ([{"code": "103", "debit": 550_000, "credit": 0},
          {"code": "110", "debit": 0, "credit": 550_000, "partner_id": pid}], "매출채권 회수"),
        ([{"code": "452", "debit": 500_000, "credit": 0},
          {"code": "135", "debit": 50_000, "credit": 0},
          {"code": "251", "debit": 0, "credit": 550_000, "partner_id": pid}], "외상매입"),
        ([{"code": "251", "debit": 275_000, "credit": 0, "partner_id": pid},
          {"code": "103", "debit": 0, "credit": 275_000}], "매입채무 지급"),
        ([{"code": "801", "debit": 1_000_000, "credit": 0},
          {"code": "103", "debit": 0, "credit": 900_000},
          {"code": "261", "debit": 0, "credit": 50_000},
          {"code": "262", "debit": 0, "credit": 50_000}], "급여 지급"),
        ([{"code": "951", "debit": 30_000, "credit": 0},
          {"code": "103", "debit": 0, "credit": 30_000}], "이자비용 지급"),
        ([{"code": "816", "debit": 100_000, "credit": 0},
          {"code": "211", "debit": 0, "credit": 100_000}], "감가상각"),
    ]
    for lines, title in slips:
        books.post(db, a, wk, d, lines, title, "manual")
    db.commit()

    gl = db.execute(
        """SELECT COALESCE(SUM(sl.debit),0) - COALESCE(SUM(sl.credit),0) AS v
           FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code='103' AND d.slip_date <= '2026-12-31'""",
        (a,),
    ).fetchone()["v"]

    html = login("a_mgr").get(
        "/report/cash-flow?date_from=2026-01-01&date_to=2026-12-31"
    ).text

    assert f"{gl:,}" in html
    assert "-13,345,000" not in html


def test_income_statement_matches_bs_net_income(db, seed, login):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    d = "2026-03-10"
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','거래처나',?)", (a,)).lastrowid
    books.post(db, a, wk, d,
               [{"code": "110", "debit": 1_000_000, "credit": 0, "partner_id": pid},
                {"code": "401", "debit": 0, "credit": 1_000_000}],
               "매출", "manual")
    books.post(db, a, wk, d,
               [{"code": "813", "debit": 300_000, "credit": 0},
                {"code": "103", "debit": 0, "credit": 300_000}],
               "통신비", "manual")
    books.post(db, a, wk, d,
               [{"code": "951", "debit": 20_000, "credit": 0},
                {"code": "103", "debit": 0, "credit": 20_000}],
               "이자비용", "manual")
    db.commit()

    c = login("a_mgr")
    is_html = c.get("/report/income-statement?date_from=2026-01-01&date_to=2026-12-31").text
    bs_html = c.get("/report/balance-sheet?as_of=2026-12-31").text

    is_ni = _num(is_html, "당기순이익")
    assert "680,000" in is_html
    bs_m = re.search(r"당기순이익.*?([\-0-9,]+)\s*</span>", bs_html, re.S)
    assert bs_m
    bs_ni = int(bs_m.group(1).replace(",", ""))
    assert is_ni == bs_ni == 680_000


def test_balance_sheet_net_income_fiscal_year_only(db, seed, login):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]

    books.post(db, a, wk, "2025-06-01",
               [{"code": "103", "debit": 500_000, "credit": 0},
                {"code": "401", "debit": 0, "credit": 500_000}],
               "2025년 매출", "manual")
    books.post(db, a, wk, "2026-02-01",
               [{"code": "103", "debit": 200_000, "credit": 0},
                {"code": "401", "debit": 0, "credit": 200_000}],
               "2026년 매출", "manual")
    db.commit()

    html = login("a_mgr").get("/report/balance-sheet?as_of=2026-12-31").text
    ni_m = re.search(r"당기순이익.*?([\-0-9,]+)\s*</span>", html, re.S)
    assert ni_m
    assert int(ni_m.group(1).replace(",", "")) == 200_000
    assert "이월이익잉여금" in html
    assert "500,000" in html


def test_trial_balance_debit_credit_totals_balance(db, seed, login):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','거래처다',?)", (a,)).lastrowid

    books.post(db, a, wk, "2026-05-01",
               [{"code": "103", "debit": 1_000_000, "credit": 0},
                {"code": "331", "debit": 0, "credit": 1_000_000}],
               "자본금", "manual")
    books.post(db, a, wk, "2026-05-02",
               [{"code": "813", "debit": 300_000, "credit": 0},
                {"code": "103", "debit": 0, "credit": 300_000}],
               "통신비", "manual")
    books.post(db, a, wk, "2026-05-03",
               [{"code": "110", "debit": 200_000, "credit": 0, "partner_id": pid},
                {"code": "401", "debit": 0, "credit": 200_000}],
               "매출", "manual")
    db.commit()

    html = login("a_mgr").get("/ledger/trial-balance?date_from=2026-05-01&date_to=2026-05-31").text
    assert "차변잔액" in html
    assert "대변잔액" in html
    debit_m = re.findall(r"합계.*?</tr>", html, re.S)
    assert debit_m
    nums = re.findall(r"([\-0-9,]+)\s*</td>", debit_m[-1])
    nums = [int(n.replace(",", "")) for n in nums]
    assert nums[-2] == nums[-1]
    assert nums[-1] > 0


def test_aging_fifo_no_negative_bucket(db, seed, login, monkeypatch):
    import core.tz
    monkeypatch.setattr(core.tz, "today_kst", lambda: __import__("datetime").date(2026, 6, 1))
    import routers.erp_accounting as erp_accounting
    monkeypatch.setattr(erp_accounting, "today_kst", core.tz.today_kst)

    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','거래처라',?)", (a,)).lastrowid

    books.post(db, a, wk, "2026-01-05",
               [{"code": "110", "debit": 1_000_000, "credit": 0, "partner_id": pid},
                {"code": "401", "debit": 0, "credit": 1_000_000}],
               "1월 매출", "manual")
    books.post(db, a, wk, "2026-05-20",
               [{"code": "110", "debit": 500_000, "credit": 0, "partner_id": pid},
                {"code": "401", "debit": 0, "credit": 500_000}],
               "5월 매출", "manual")
    books.post(db, a, wk, "2026-05-25",
               [{"code": "103", "debit": 1_200_000, "credit": 0},
                {"code": "110", "debit": 0, "credit": 1_200_000, "partner_id": pid}],
               "입금", "manual")
    db.commit()

    html = login("a_mgr").get("/ledger/aging?view=ar").text
    nums = re.findall(r'class="num[^"]*">([\-0-9,]*)</td>', html)
    vals = [int(n.replace(",", "")) for n in nums if n and n != "-"]
    assert all(v >= 0 for v in vals[:-1])
    assert "300,000" in html


def test_ar_ap_opening_balance_sign(db, seed, login):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','거래처마',?)", (a,)).lastrowid

    books.post(db, a, wk, "2026-07-10",
               [{"code": "452", "debit": 1_000_000, "credit": 0},
                {"code": "251", "debit": 0, "credit": 1_000_000, "partner_id": pid}],
               "7월 외상매입", "manual")
    db.commit()

    html = login("a_mgr").get("/ledger/ar-ap?partner=거래처마&date_from=2026-08-01&date_to=2026-08-31").text
    assert "1,000,000" in html
    assert "-1,000,000" not in html


def test_budget_vs_actual_uses_net_amount(db, seed, login):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    db.execute(
        "INSERT INTO budgets (company_id, account_code, year, month, amount) VALUES (?,?,?,?,?)",
        (a, "813", 2026, 9, 500_000),
    )
    books.post(db, a, wk, "2026-09-05",
               [{"code": "813", "debit": 400_000, "credit": 0},
                {"code": "103", "debit": 0, "credit": 400_000}],
               "통신비", "manual")
    books.post(db, a, wk, "2026-09-10",
               [{"code": "103", "debit": 150_000, "credit": 0},
                {"code": "813", "debit": 0, "credit": 150_000}],
               "통신비 정정", "manual")
    db.commit()

    html = login("a_mgr").get("/budget/vs-actual?year=2026&month=9").text
    assert "250,000" in html
    assert "400,000" not in html


def test_calc_employer_insurance_matches_employee_base(db):
    from core.payroll import build_payslip, calc_employer_insurance

    rates = {
        "national_pension": 0.0475, "health_insurance": 0.03595, "long_care": 0.1314,
        "employment_insurance": 0.009, "pension_upper": 5900000, "pension_lower": 370000,
    }
    items = [
        {"amount": 3_000_000, "taxable": 1, "tax_free_limit": 0},
        {"amount": 200_000, "taxable": 1, "tax_free_limit": 200_000},
    ]
    ps = build_payslip(items, rates, 1)
    er = calc_employer_insurance(ps)

    assert er["employer_pension"] == ps["national_pension"]
    assert er["employer_health"] == ps["health_insurance"] + ps["long_care"]
    assert er["employer_employment"] == round(ps["taxable"] * 0.0115 / 10) * 10
    assert er["employer_accident"] == round(ps["taxable"] * 0.007 / 10) * 10


def test_payroll_slip_books_employer_cost_and_balances(db, seed):
    from routers.erp_accounting import _create_payroll_slip

    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    payslip = {
        "id": 1, "pay_year": 2026, "pay_month": 9, "pay_date": "2026-09-25",
        "gross_pay": 3_200_000, "net_pay": 2_856_000,
        "income_tax": 50_000, "resident_tax": 5_000,
        "national_pension": 140_000, "health_insurance": 110_000, "long_care": 14_000,
        "employment_insurance": 25_000,
        "employer_pension": 140_000, "employer_health": 124_000,
        "employer_employment": 36_000, "employer_accident": 22_000,
    }
    doc_id = _create_payroll_slip(db, a, payslip, "김직원", wk)
    db.commit()

    lines = db.execute("SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (doc_id,)).fetchall()
    dr = sum(l["debit"] for l in lines)
    cr = sum(l["credit"] for l in lines)
    assert dr == cr

    by_code = {l["account_code"]: (l["debit"], l["credit"]) for l in lines}
    assert by_code["815"][0] == 140_000
    assert by_code["804"][0] == 124_000
    assert by_code["818"][0] == 36_000 + 22_000
    assert by_code["256"][1] == 140_000 + 124_000 + 36_000 + 22_000
