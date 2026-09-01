def up(conn):
    for col_name, col_def in [
        ("assigned_to", "INTEGER"),
        ("assigned_by", "INTEGER"),
        ("output_format", "TEXT DEFAULT 'excel'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE work_requests ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    conn.commit()
