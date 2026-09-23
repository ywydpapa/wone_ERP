def up(conn):
    for col in ("employer_pension", "employer_health", "employer_employment", "employer_accident"):
        try:
            conn.execute(f"ALTER TABLE payslips ADD COLUMN {col} INTEGER DEFAULT 0")
        except Exception:
            pass
    conn.commit()
