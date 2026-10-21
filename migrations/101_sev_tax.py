# 퇴직소득세, 미사용 연차수당 반영. 연차 잔여는 leave_accruals로 일원화해 employees 컬럼 제거


def up(conn):
    conn.execute("ALTER TABLE severance_records ADD COLUMN income_tax INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE severance_records ADD COLUMN local_tax INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE severance_records ADD COLUMN net_amount INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE severance_records ADD COLUMN leave_days REAL DEFAULT 0")
    conn.execute("ALTER TABLE severance_records ADD COLUMN leave_pay INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE employees DROP COLUMN annual_leave_total")
    conn.execute("ALTER TABLE employees DROP COLUMN annual_leave_used")
