def up(conn):
    for col_name, col_def in [
        ("cert_number", "TEXT"),
        ("completed_at", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE certificate_requests ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    conn.commit()
