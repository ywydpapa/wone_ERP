from core import books
from core.severance import calc_severance
from tests.conftest import csrf


def test_year_end_provision_lines(db, seed, login):
    a = seed["a"]["company"]
    from core.pay_items import ensure_default_items, get_items
    ensure_default_items(db, a)
    items = {it["code"]: it["id"] for it in get_items(db, a)}
    eid = db.execute(
        """INSERT INTO employees (name, company_id, hire_date, monthly_work_hours, status)
           VALUES ('근로자', ?, '2020-01-01', 300, 'active')""",
        (a,),
    ).lastrowid
    for y, m in ((2026, 9), (2026, 10), (2026, 11), (2026, 12)):
        ps_id = db.execute(
            """INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, total_deduction, net_pay, status)
               VALUES (?,?,?,3000000,0,3000000,'confirmed')""",
            (eid, y, m),
        ).lastrowid
        db.execute("INSERT INTO payslip_items (payslip_id, item_id, amount) VALUES (?,?,3000000)",
                  (ps_id, items["BASE"]))
    db.commit()

    expected = calc_severance(db, eid, resign_date="2026-12-31")["amount"]
    assert expected > 0

    c = login("a_mgr")
    r = c.get("/fi/year-end?year=2026")
    assert r.status_code == 200
    assert f'value="{expected}"' in r.text

    tok = csrf(c, "/fi/year-end")
    r = c.post("/fi/year-end", data={"csrf_token": tok, "year": "2026", "rate": "1", "end_stock": "0"},
               follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT * FROM erp_docs WHERE company_id=? AND source_type='closing'", (a,)).fetchone()
    lines = {(l["account_code"], l["debit"], l["credit"])
             for l in db.execute("SELECT * FROM slip_lines WHERE doc_id=?", (doc["id"],))}
    assert ("803", expected, 0) in lines
    assert ("292", 0, expected) in lines


def test_year_end_provision_refund(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    # 기존에 292에 쌓인 설정액(500,000)이 연말 추계액(재직자 없음, 0)보다 큰 경우 환입
    books.post(db, a, uid, "2026-06-01",
              [{"code": "801", "debit": 500_000, "credit": 0}, {"code": "292", "debit": 0, "credit": 500_000}],
              "충당금 설정(사전)", "manual")
    db.commit()

    c = login("a_mgr")
    r = c.get("/fi/year-end?year=2026")
    assert 'value="-500000"' in r.text

    tok = csrf(c, "/fi/year-end")
    r = c.post("/fi/year-end", data={"csrf_token": tok, "year": "2026", "rate": "1", "end_stock": "0"},
               follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT * FROM erp_docs WHERE company_id=? AND source_type='closing'", (a,)).fetchone()
    lines = {(l["account_code"], l["debit"], l["credit"])
             for l in db.execute("SELECT * FROM slip_lines WHERE doc_id=?", (doc["id"],))}
    assert ("292", 500_000, 0) in lines
    assert ("803", 0, 500_000) in lines


def _mk_record(db, eid, amount, income_tax, local_tax):
    return db.execute(
        """INSERT INTO severance_records
           (employee_id, calc_date, avg_salary, tenure_days, amount, income_tax, local_tax, net_amount, status)
           VALUES (?, '2026-09-20', 50000, 2000, ?, ?, ?, ?, 'pending')""",
        (eid, amount, income_tax, local_tax, amount - income_tax - local_tax),
    ).lastrowid


def test_pay_slip_partial(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    eid = db.execute(
        """INSERT INTO employees (name, company_id, hire_date, resign_date, status)
           VALUES ('퇴사자', ?, '2020-01-01', '2026-09-20', 'retired')""",
        (a,),
    ).lastrowid
    _mk_record(db, eid, 1_000_000, 50_000, 5_000)
    # 292에 300,000만 쌓여있어 부족분은 803로 처리
    books.post(db, a, uid, "2026-06-01",
              [{"code": "801", "debit": 300_000, "credit": 0}, {"code": "292", "debit": 0, "credit": 300_000}],
              "충당금 설정(사전)", "manual")
    db.commit()

    c = login("a_mgr")
    # 상세 화면은 status='pending'일 때 실제 급여 데이터로 재계산하므로 CSRF 토큰은 다른 화면에서 받음
    tok = csrf(c, "/severance/estimate")
    r = c.post(f"/severance/{eid}/pay-slip", data={"csrf_token": tok, "pay_date": "2026-09-20"},
               follow_redirects=False)
    assert r.status_code == 303 and "error=" not in r.headers["location"]

    doc = db.execute("SELECT * FROM erp_docs WHERE company_id=? AND source_type='severance' AND source_id=?",
                     (a, eid)).fetchone()
    assert doc
    lines = {(l["account_code"], l["debit"], l["credit"])
             for l in db.execute("SELECT * FROM slip_lines WHERE doc_id=?", (doc["id"],))}
    assert ("292", 300_000, 0) in lines
    assert ("803", 700_000, 0) in lines
    assert ("261", 0, 50_000) in lines
    assert ("253", 0, 5_000) in lines
    assert ("103", 0, 945_000) in lines
    assert db.execute("SELECT status FROM severance_records WHERE employee_id=?", (eid,)).fetchone()[0] == "paid"

    r = c.post(f"/severance/{eid}/pay-slip", data={"csrf_token": tok, "pay_date": "2026-09-20"},
               follow_redirects=False)
    assert r.status_code == 303 and "error=" in r.headers["location"]
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE source_type='severance' AND source_id=?",
                      (eid,)).fetchone()[0] == 1
