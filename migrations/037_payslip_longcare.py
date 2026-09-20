def up(conn):
    try:
        conn.execute("ALTER TABLE payslips ADD COLUMN long_care INTEGER DEFAULT 0")
    except Exception:
        pass
    conn.commit()
