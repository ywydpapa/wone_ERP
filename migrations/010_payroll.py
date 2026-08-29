VERSION = 10


def up(conn):
    # client_users: HR/운영 역할 분리
    try:
        conn.execute("ALTER TABLE client_users ADD COLUMN client_role TEXT DEFAULT 'all'")
    except Exception:
        pass

    # employees: 급여 본인확인용 생년월일
    try:
        conn.execute("ALTER TABLE employees ADD COLUMN birth_date TEXT")
    except Exception:
        pass

    # payslips: 임시저장/확정 상태
    try:
        conn.execute("ALTER TABLE payslips ADD COLUMN status TEXT DEFAULT 'confirmed'")
    except Exception:
        pass

    conn.execute("UPDATE payslips SET status='confirmed' WHERE status IS NULL")

    conn.commit()
