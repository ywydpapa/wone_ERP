VERSION = 11


def up(conn):
    cols = [
        ("attachment", "TEXT"),
        ("half_day_period", "TEXT"),
    ]
    for col_name, col_def in cols:
        try:
            conn.execute(f"ALTER TABLE leave_requests ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    conn.commit()
