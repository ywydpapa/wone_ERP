import sqlite3

import pytest

from migrate import run_migrations
from tests.conftest import csrf


def _pre073_db(tmp_path, name="pre073.db"):
    path = str(tmp_path / name)
    run_migrations(path, upto=72)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cid = conn.execute("INSERT INTO client_companies (name) VALUES ('마이그레이션테스트')").lastrowid
    eid = conn.execute(
        "INSERT INTO employees (name, company_id) VALUES ('근로자', ?)", (cid,)
    ).lastrowid
    return path, conn, cid, eid


def test_migration_backfills_items_and_drops_columns(tmp_path):
    path, conn, cid, eid = _pre073_db(tmp_path)
    conn.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, base_salary, overtime_pay,
               disability_allowance, meal_allowance, gross_pay, total_deduction, net_pay, status)
           VALUES (?,2026,1,3000000,100000,0,200000,3300000,300000,3000000,'confirmed')""",
        (eid,),
    )
    conn.commit()
    conn.close()

    run_migrations(path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(payslips)")}
    for dropped in ("base_salary", "overtime_pay", "disability_allowance", "meal_allowance"):
        assert dropped not in cols

    total = conn.execute(
        """SELECT SUM(pi.amount) FROM payslip_items pi
           JOIN pay_items it ON it.id = pi.item_id
           WHERE it.kind='지급'"""
    ).fetchone()[0]
    assert total == 3_300_000

    row = conn.execute(
        "SELECT amount FROM payslip_items pi JOIN pay_items it ON it.id=pi.item_id "
        "WHERE it.code='BASE' AND pi.payslip_id=(SELECT id FROM payslips WHERE employee_id=?)",
        (eid,),
    ).fetchone()
    assert row["amount"] == 3_000_000

    premium_rule = conn.execute("SELECT premium_rule FROM payslips WHERE employee_id=?", (eid,)).fetchone()[0]
    assert premium_rule == ""
    conn.close()


def test_migration_aborts_on_mismatch(tmp_path):
    path, conn, cid, eid = _pre073_db(tmp_path, name="mismatch.db")
    conn.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, base_salary, overtime_pay,
               disability_allowance, meal_allowance, gross_pay, total_deduction, net_pay, status)
           VALUES (?,2026,1,3000000,100000,0,200000,9999999,300000,3000000,'confirmed')""",
        (eid,),
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError):
        run_migrations(path)

    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(payslips)")}
    assert "base_salary" in cols  # 롤백되어 원래 컬럼 유지
    applied = conn.execute("SELECT COUNT(*) FROM schema_versions WHERE version=73").fetchone()[0]
    assert applied == 0
    conn.close()


def test_default_items_seeded(db, seed):
    from core.pay_items import get_items

    items = get_items(db, seed["a"]["company"])
    codes = {it["code"] for it in items}
    assert {"BASE", "OT", "NIGHT", "HOLIDAY", "DISABLE", "MEAL", "BONUS", "ANNUAL"} <= codes

    meal = next(it for it in items if it["code"] == "MEAL")
    assert meal["tax_free_code"] == "P01"
    assert meal["tax_free_limit"] == 200_000


def test_tenant_isolation_pay_items(db, seed, login):
    from core.pay_items import get_items

    get_items(db, seed["a"]["company"])
    b_items = get_items(db, seed["b"]["company"])
    b_item_id = b_items[0]["id"]

    c = login("a_mgr")
    tok = csrf(c, "/pay-items")
    r = c.post(
        f"/pay-items/{b_item_id}",
        data={
            "csrf_token": tok, "name": "해킹시도", "taxable": "1", "tax_free_code": "",
            "tax_free_limit": "0", "ordinary": "0", "avg_wage": "1", "bonus": "0",
        },
        follow_redirects=False,
    )
    assert r.status_code == 404
    unchanged = db.execute("SELECT name FROM pay_items WHERE id=?", (b_item_id,)).fetchone()
    assert unchanged["name"] != "해킹시도"

    r2 = c.get(f"/pay-items/{b_item_id}/edit", follow_redirects=False)
    assert r2.status_code == 303
    assert r2.headers["location"] == "/pay-items"


def test_add_edit_deactivate_item(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_mgr")
    tok = csrf(c, "/pay-items")
    r = c.post(
        "/pay-items",
        data={
            "csrf_token": tok, "code": "CUSTOM1", "name": "커스텀수당",
            "taxable": "1", "tax_free_code": "", "tax_free_limit": "0",
            "ordinary": "0", "avg_wage": "1", "bonus": "0",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    row = db.execute(
        "SELECT id, active FROM pay_items WHERE company_id=? AND code='CUSTOM1'", (a,)
    ).fetchone()
    assert row and row["active"] == 1
    item_id = row["id"]

    tok2 = csrf(c, "/pay-items")
    c.post(
        f"/pay-items/{item_id}",
        data={
            "csrf_token": tok2, "name": "커스텀수당(수정)", "taxable": "1", "tax_free_code": "",
            "tax_free_limit": "0", "ordinary": "0", "avg_wage": "1", "bonus": "0",
        },
        follow_redirects=False,
    )
    edited = db.execute("SELECT name FROM pay_items WHERE id=?", (item_id,)).fetchone()
    assert edited["name"] == "커스텀수당(수정)"

    tok3 = csrf(c, "/pay-items")
    c.post(f"/pay-items/{item_id}/deactivate", data={"csrf_token": tok3}, follow_redirects=False)
    deactivated = db.execute("SELECT active FROM pay_items WHERE id=?", (item_id,)).fetchone()
    assert deactivated["active"] == 0


def test_confirmed_payslip_untouched_after_item_settings_change(db, seed, login):
    from core.pay_items import get_items

    a = seed["a"]["company"]
    emp_id = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()["id"]
    base_item = next(it for it in get_items(db, a) if it["code"] == "BASE")

    cur = db.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay,
               total_deduction, net_pay, pay_date, status)
           VALUES (?,2026,3,3000000,300000,2700000,'2026-03-25','confirmed')""",
        (emp_id,),
    )
    payslip_id = cur.lastrowid
    db.execute(
        "INSERT INTO payslip_items (payslip_id, item_id, amount) VALUES (?,?,3000000)",
        (payslip_id, base_item["id"]),
    )
    db.commit()

    c = login("a_mgr")

    # 사용 이력이 있는 항목은 삭제 불가
    tok = csrf(c, "/pay-items")
    r = c.post(f"/pay-items/{base_item['id']}/delete", data={"csrf_token": tok}, follow_redirects=False)
    assert "error=in_use" in r.headers["location"]
    assert db.execute("SELECT 1 FROM pay_items WHERE id=?", (base_item["id"],)).fetchone()

    # 항목명을 수정해도 이미 확정된 명세서의 payslip_items 금액은 유지
    tok2 = csrf(c, "/pay-items")
    c.post(
        f"/pay-items/{base_item['id']}",
        data={
            "csrf_token": tok2, "name": "기본급(변경)", "taxable": "1", "tax_free_code": "",
            "tax_free_limit": "0", "ordinary": "1", "avg_wage": "1", "bonus": "0",
        },
        follow_redirects=False,
    )
    amount = db.execute(
        "SELECT amount FROM payslip_items WHERE payslip_id=? AND item_id=?",
        (payslip_id, base_item["id"]),
    ).fetchone()["amount"]
    assert amount == 3_000_000


def test_override_flag_persists_and_shown_in_calc_note(db, seed, login):
    from core.pay_items import get_items
    from core.payroll import build_payslip_detail

    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET employee_count=5 WHERE id=?", (a,))
    emp_id = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()["id"]
    db.execute(
        "UPDATE employees SET base_salary=2090000, monthly_work_hours=209 WHERE id=?", (emp_id,)
    )
    db.execute(
        """INSERT INTO attendance (employee_id, work_date, clock_in, clock_out,
               work_minutes, overtime_minutes, status)
           VALUES (?, '2026-04-02', '09:00', '20:00', 600, 120, 'normal')""",
        (emp_id,),
    )
    db.commit()

    items = get_items(db, a)
    item_by_code = {it["code"]: it for it in items}

    c = login("a_mgr")
    tok = csrf(c, f"/payroll/{emp_id}?year=2026&month=4")
    form = {"csrf_token": tok, "year": "2026", "month": "4"}
    for it in items:
        if it["code"] == "BASE":
            form[f"amount_{it['id']}"] = "2090000"
        elif it["code"] == "OT":
            form[f"amount_{it['id']}"] = "999999"  # 제안액과 다른 수동 입력값
        else:
            form[f"amount_{it['id']}"] = "0"

    r = c.post(f"/payroll/{emp_id}", data=form, follow_redirects=False)
    assert r.status_code == 303

    ps_row = db.execute(
        "SELECT id FROM payslips WHERE employee_id=? AND pay_year=2026 AND pay_month=4", (emp_id,)
    ).fetchone()
    ot_row = db.execute(
        "SELECT amount, overridden FROM payslip_items WHERE payslip_id=? AND item_id=?",
        (ps_row["id"], item_by_code["OT"]["id"]),
    ).fetchone()
    assert ot_row["amount"] == 999_999
    assert ot_row["overridden"] == 1

    base_row = db.execute(
        "SELECT overridden FROM payslip_items WHERE payslip_id=? AND item_id=?",
        (ps_row["id"], item_by_code["BASE"]["id"]),
    ).fetchone()
    assert base_row["overridden"] == 0

    payslip = dict(db.execute("SELECT * FROM payslips WHERE id=?", (ps_row["id"],)).fetchone())
    _, _, detail_items = build_payslip_detail(db, emp_id, 209, payslip)
    ot_detail = next(i for i in detail_items if i["code"] == "OT")
    assert "수동 조정됨" in ot_detail["calc_note"]
