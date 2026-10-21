from core.pay_items import ensure_default_items
from core.withholding import get_report, get_simple_statement, get_simple_statement_month, simple_monthly


def _item_id(db, company_id, code):
    return db.execute(
        "SELECT id FROM pay_items WHERE company_id=? AND code=?", (company_id, code)
    ).fetchone()[0]


def _make_payslip(db, company_id, emp_id, pay_year, pay_month, items, status="confirmed", pay_date=None):
    ensure_default_items(db, company_id)
    gross = sum(items.values())
    taxable = 0
    for code, amt in items.items():
        row = db.execute(
            "SELECT taxable, tax_free_limit FROM pay_items WHERE company_id=? AND code=?", (company_id, code)
        ).fetchone()
        if row["tax_free_limit"]:
            taxable += max(0, amt - row["tax_free_limit"])
        elif row["taxable"]:
            taxable += amt
    income_tax, resident_tax = 1000, 100
    cur = db.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, income_tax, resident_tax,
               national_pension, health_insurance, employment_insurance, total_deduction, net_pay,
               pay_date, status)
           VALUES (?,?,?,?,?,?,0,0,0,?,?,?,?)""",
        (emp_id, pay_year, pay_month, gross, income_tax, resident_tax,
         income_tax + resident_tax, gross - income_tax - resident_tax, pay_date, status),
    )
    ps_id = cur.lastrowid
    for code, amt in items.items():
        db.execute(
            "INSERT INTO payslip_items (payslip_id, item_id, amount) VALUES (?,?,?)",
            (ps_id, _item_id(db, company_id, code), amt),
        )
    db.commit()
    return ps_id


def _second_employee(db, company_id, name="박근로", employee_no="E2"):
    return db.execute(
        "INSERT INTO employees (name, company_id, employee_no) VALUES (?,?,?)",
        (name, company_id, employee_no),
    ).lastrowid


def test_report_totals_and_meal_over_limit(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    emp2 = _second_employee(db, a)

    _make_payslip(db, a, emp1, 2026, 9, {"BASE": 3000000}, pay_date="2026-09-25")
    _make_payslip(db, a, emp2, 2026, 9, {"BASE": 2000000, "MEAL": 250000}, pay_date="2026-09-25")

    c = login("a_mgr")
    r = c.get("/withholding?year=2026&month=9")
    assert r.status_code == 200

    report = get_report(db, a, 2026, 9)
    assert report["headcount"] == 2
    assert report["sum_pay"] == 3000000 + 2050000 + 200000
    row2 = next(r for r in report["rows"] if r["emp_id"] == emp2)
    assert row2["taxable_pay"] == 2050000
    assert row2["submit_free_pay"] == 200000
    assert report["due_date"] == "2026-10-10"


def test_draft_payslip_excluded(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 10, {"BASE": 3000000}, status="draft", pay_date="2026-10-25")

    report = get_report(db, a, 2026, 10)
    assert report["headcount"] == 0


def test_pay_date_next_month_moves_period(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 11, {"BASE": 3000000}, pay_date="2026-12-05")

    nov_report = get_report(db, a, 2026, 11)
    dec_report = get_report(db, a, 2026, 12)
    assert nov_report["headcount"] == 0
    assert dec_report["headcount"] == 1


def test_simple_statement_switches_to_monthly_from_2027():
    assert simple_monthly(2026) is False
    assert simple_monthly(2027) is True


def test_monthly_simple_statement_scope_and_due_date(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2027, 1, {"BASE": 3000000}, pay_date="2027-01-25")
    _make_payslip(db, a, emp1, 2027, 2, {"BASE": 3000000}, pay_date="2027-02-25")

    jan = get_simple_statement_month(db, a, 2027, 1)
    feb = get_simple_statement_month(db, a, 2027, 2)
    assert len(jan["rows"]) == 1
    assert len(feb["rows"]) == 1
    assert jan["due_date"] == "2027-02-28"

    c = login("a_mgr")
    r = c.get("/withholding/simple-statement?year=2027&month=1")
    assert r.status_code == 200


def test_client_cannot_see_other_company_employee(db, seed, login):
    b = seed["b"]["company"]
    emp_b = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["b"]["wk"],)).fetchone()[0]

    c = login("a_mgr")
    r = c.get(f"/withholding/employees/{emp_b}?year=2026")
    assert r.status_code == 404


def test_staff_internal_book_shows_report(db, seed, login):
    c = login("t_staff")
    r = c.get("/withholding")
    assert r.status_code == 200
    assert "원천징수이행상황신고서" in r.text


def test_staff_with_delegated_company_sees_report(db, seed, login):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (a,))
    db.commit()
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 9, {"BASE": 3000000}, pay_date="2026-09-25")

    c = login("t_staff")
    c.post("/hr-book", data={"book": a, "next": "/withholding"})
    r = c.get("/withholding?year=2026&month=9")
    assert r.status_code == 200
    assert "원천징수이행상황신고서" in r.text


def test_csv_export_headers(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 9, {"BASE": 3000000}, pay_date="2026-09-25")

    c = login("a_mgr")
    r = c.get("/withholding/export?year=2026&month=9&reason=테스트조회")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf") and not r.content[3:].startswith(b"\xef\xbb\xbf")


def test_simple_statement_half_year_scope(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 3, {"BASE": 3000000}, pay_date="2026-03-25")
    _make_payslip(db, a, emp1, 2026, 8, {"BASE": 3000000}, pay_date="2026-08-25")

    h1 = get_simple_statement(db, a, 2026, 1)
    h2 = get_simple_statement(db, a, 2026, 2)
    assert len(h1["rows"]) == 1
    assert h1["rows"][0]["taxable_total"] == 3000000
    assert len(h2["rows"]) == 1
    assert h1["due_date"] == "2026-07-31"
    assert h2["due_date"] == "2027-01-31"


def test_staff_simple_statement_and_employee_routes(db, seed, login):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (a,))
    db.commit()
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 3, {"BASE": 3000000}, pay_date="2026-03-25")

    c = login("t_staff")
    c.post("/hr-book", data={"book": a, "next": "/withholding"})

    r = c.get("/withholding/simple-statement?year=2026&half=1")
    assert r.status_code == 200

    r2 = c.get(f"/withholding/employees/{emp1}?year=2026")
    assert r2.status_code == 200

    r3 = c.get("/withholding/export?year=2026&month=3&reason=테스트조회")
    assert r3.status_code == 200
    assert "text/csv" in r3.headers["content-type"]


def test_employee_yearly_record(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 9, {"BASE": 3000000, "MEAL": 250000}, pay_date="2026-09-25")

    c = login("a_mgr")
    r = c.get(f"/withholding/employees/{emp1}?year=2026")
    assert r.status_code == 200
    assert "연말정산 결과가 반영되지 않은" in r.text
