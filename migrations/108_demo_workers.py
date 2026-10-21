# 로그인 화면 테스트 계정 중 seed_sample.py 전용이던 2명. 운영 DB는 시드 미실행이므로 로그인 불가
from core.auth import hash_pw
from core.books import seed_accounts

WORKERS = (
    ("na_hyunwoo", "나현우", "경리팀", "한빛전자", "EMP-110", "2025-02-10", "지체장애", "5급", "1996-04-12"),
    ("kim_sujin", "김수진", "데이터처리팀", "한양정밀", "EMP-101", "2024-03-02", "지체장애", "4급", "1995-07-21"),
)


def up(conn):
    if not conn.execute("SELECT 1 FROM client_companies WHERE name='한양정밀'").fetchone():
        cid = conn.execute(
            """INSERT INTO client_companies (name, business_no, contact_name, contact_phone, contract_start, status)
               VALUES ('한양정밀', '211-81-00001', '김대표', '031-999-1111', '2026-01-01', 'active')"""
        ).lastrowid
        seed_accounts(conn, cid)

    pw = hash_pw("1234")
    for username, name, dept, co, emp_no, hire, dtype, grade, birth in WORKERS:
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            continue
        cid = conn.execute("SELECT id FROM client_companies WHERE name=?", (co,)).fetchone()
        if not cid:
            continue
        uid = conn.execute(
            "INSERT INTO users (username, password, name, dept, role) VALUES (?,?,?,?,'worker')",
            (username, pw, name, dept),
        ).lastrowid
        conn.execute(
            """INSERT INTO employees
               (user_id, name, employee_no, dept, position, hire_date, status,
                disability_type, disability_grade, company_id, birth_date, base_salary, monthly_work_hours)
               VALUES (?,?,?,?,'사원',?,'active',?,?,?,?,2156880,209)""",
            (uid, name, emp_no, dept, hire, dtype, grade, cid[0], birth),
        )
