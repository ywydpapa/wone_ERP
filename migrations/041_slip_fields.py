def up(conn):
    cols = [
        ("evidence_type", "TEXT DEFAULT ''"),
        ("evidence_no", "TEXT DEFAULT ''"),
        ("project_code", "TEXT DEFAULT ''"),
    ]
    for col_name, col_def in cols:
        try:
            conn.execute(f"ALTER TABLE erp_docs ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass
    conn.commit()
