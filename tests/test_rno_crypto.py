import importlib.util
import os
import sqlite3

from migrate import run_migrations
from core.crypto import enc_rno, dec_rno, ENC_PREFIX


def _load_mig():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "migrations", "118_rno_encrypt.py")
    spec = importlib.util.spec_from_file_location("m118", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_enc_dec_roundtrip():
    rno = "900101-1234567"
    enc = enc_rno(rno)
    assert enc.startswith(ENC_PREFIX)
    assert rno not in enc
    assert dec_rno(enc) == rno


def test_dec_handles_plain_and_empty():
    # 암호화 전 평문이 섞여 있어도 그대로 반환
    assert dec_rno("900101-1234567") == "900101-1234567"
    assert dec_rno("") == ""
    assert dec_rno(None) is None
    assert enc_rno("") == ""
    assert enc_rno(None) is None


def test_migration_118_idempotent(tmp_path):
    path = str(tmp_path / "pre118.db")
    run_migrations(path, upto=117)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    conn.execute(
        "INSERT INTO employees (name, resident_no, status) VALUES ('멱등테스트', '900101-1234567', 'active')"
    )
    conn.commit()

    m118 = _load_mig()
    m118.up(conn)
    first = conn.execute("SELECT resident_no FROM employees WHERE name='멱등테스트'").fetchone()[0]
    assert first.startswith(ENC_PREFIX)

    m118.up(conn)  # 재실행 시 이중 암호화 방지
    second = conn.execute("SELECT resident_no FROM employees WHERE name='멱등테스트'").fetchone()[0]
    assert second == first
    assert dec_rno(second) == "900101-1234567"
    conn.close()


def test_create_stores_encrypted_not_plaintext(db, seed, login):
    rno = "880101-1234567"
    c = login("t_staff")
    r = c.post("/hr/employees", data={"name": "신규등록", "resident_no": rno}, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT resident_no FROM employees WHERE name='신규등록'").fetchone()
    assert row["resident_no"].startswith(ENC_PREFIX)
    assert rno not in row["resident_no"]
    assert dec_rno(row["resident_no"]) == rno


def test_edit_form_hides_original_resident_no(db, seed, login):
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (seed["a"]["company"],))
    db.commit()
    company = seed["a"]["company"]
    rno = "900101-5234567"
    emp_id = db.execute(
        "INSERT INTO employees (name, company_id, resident_no, status) VALUES (?,?,?,'active')",
        ("폼테스트", company, enc_rno(rno)),
    ).lastrowid
    db.commit()

    c = login("t_staff")
    r = c.get(f"/hr/employees/{emp_id}/edit")
    assert r.status_code == 200
    assert rno not in r.text
    assert ENC_PREFIX not in r.text
    assert "900101-*******" in r.text


def test_update_blank_keeps_existing_value(db, seed, login):
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (seed["a"]["company"],))
    db.commit()
    company = seed["a"]["company"]
    rno = "770101-1234567"
    emp_id = db.execute(
        "INSERT INTO employees (name, company_id, resident_no, status) VALUES (?,?,?,'active')",
        ("유지테스트", company, enc_rno(rno)),
    ).lastrowid
    db.commit()

    c = login("t_staff")
    r = c.post(f"/hr/employees/{emp_id}/edit", data={
        "name": "유지테스트", "dept": "경영지원팀", "position": "사원", "status": "active",
    }, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT resident_no FROM employees WHERE id=?", (emp_id,)).fetchone()
    assert dec_rno(row["resident_no"]) == rno


def test_update_with_value_replaces_existing(db, seed, login):
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (seed["a"]["company"],))
    db.commit()
    company = seed["a"]["company"]
    old_rno = "660101-1234567"
    new_rno = "660101-7654321"
    emp_id = db.execute(
        "INSERT INTO employees (name, company_id, resident_no, status) VALUES (?,?,?,'active')",
        ("교체테스트", company, enc_rno(old_rno)),
    ).lastrowid
    db.commit()

    c = login("t_staff")
    r = c.post(f"/hr/employees/{emp_id}/edit", data={
        "name": "교체테스트", "dept": "경영지원팀", "position": "사원", "status": "active",
        "resident_no": new_rno,
    }, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT resident_no FROM employees WHERE id=?", (emp_id,)).fetchone()
    assert dec_rno(row["resident_no"]) == new_rno


def test_external_submit_csv_has_plaintext(db, seed, login):
    company = seed["a"]["company"]
    rno = "900101-1234567"
    db.execute(
        "INSERT INTO employees (name, company_id, resident_no, hire_date, status) VALUES (?,?,?,?,'active')",
        ("신규가입", company, enc_rno(rno), "2026-01-15"),
    )
    db.commit()

    c = login("a_mgr")
    r = c.get("/insurance-reports/export?from=2026-01-01&to=2026-01-31&kind=acq&reason=테스트조회")
    assert r.status_code == 200
    body = r.content.decode("utf-8-sig")
    assert rno in body
    assert ENC_PREFIX not in body
