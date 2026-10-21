import importlib.util
import os
import sqlite3

from migrate import run_migrations


def _load_mig():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "migrations", "116_worker_register.py")
    spec = importlib.util.spec_from_file_location("m116", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_116_adds_columns_and_is_idempotent(tmp_path):
    path = str(tmp_path / "pre116.db")
    run_migrations(path, upto=115)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    before = {r[1] for r in conn.execute("PRAGMA table_info(employees)")}
    assert "renew_date" not in before
    assert "disability_class" not in before

    m116 = _load_mig()
    m116.up(conn)
    m116.up(conn)  # 재실행해도 에러 없어야 함

    after = {r[1] for r in conn.execute("PRAGMA table_info(employees)")}
    for col in ("renew_date", "contract_end", "career", "education", "military",
                "license", "training", "disability_class", "veteran_grade", "disability_date"):
        assert col in after
    conn.close()


def _fill_emp(db, emp_id):
    db.execute(
        """UPDATE employees SET
               gender='M', birth_date='1990-05-01', address='서울시 강남구', phone='010-1234-5678',
               job_title='데이터 입력', hire_date='2024-03-01', renew_date='2025-03-01',
               contract_end='2026-02-28', career='전직장 2년', education='고졸',
               military='병역필', license='컴퓨터활용능력 2급', training='장애인식개선교육 이수',
               notes='비고 사항'
           WHERE id=?""",
        (emp_id,),
    )
    db.commit()


def test_register_print_shows_legal_form_fields(db, seed, login):
    a_wk = seed["a"]["wk"]
    emp_id = db.execute("SELECT id FROM employees WHERE user_id=?", (a_wk,)).fetchone()["id"]
    _fill_emp(db, emp_id)

    c = login("a_mgr")
    r = c.get(f"/register/{emp_id}/print?reason=급여산정 확인")
    assert r.status_code == 200
    html = r.text

    for label in ("근로자 명부", "성명", "성별", "생년월일", "주소", "종사 업무",
                  "고용일", "계약기간", "퇴직일", "퇴직(해고)", "경력", "기타 사항",
                  "그 밖에 필요한 사항"):
        assert label in html

    assert "가테스트근로자" in html
    assert "데이터 입력" in html
    assert "전직장 2년" in html
    assert "고졸" in html
    assert "병역필" in html
    assert "컴퓨터활용능력 2급" in html
    assert "장애인식개선교육 이수" in html


def test_register_tenant_isolation(db, seed, login):
    b_wk = seed["b"]["wk"]
    emp_b = db.execute("SELECT id FROM employees WHERE user_id=?", (b_wk,)).fetchone()["id"]

    c = login("a_mgr")
    r = c.get("/register")
    assert "가테스트근로자" in r.text
    assert "나테스트근로자" not in r.text

    r2 = c.get(f"/register/{emp_b}/print?reason=급여산정 확인")
    assert r2.status_code == 404
