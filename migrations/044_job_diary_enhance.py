def up(conn):
    cols = [
        ("start_time", "TEXT DEFAULT ''"),
        ("end_time", "TEXT DEFAULT ''"),
        ("work_minutes", "INTEGER DEFAULT 0"),
        ("volume", "INTEGER DEFAULT 0"),
        ("volume_unit", "TEXT DEFAULT ''"),
        ("review_status", "TEXT DEFAULT 'none'"),
        ("reviewer_id", "INTEGER"),
        ("review_comment", "TEXT DEFAULT ''"),
        ("reviewed_at", "TEXT"),
    ]
    for name, defn in cols:
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {defn}")
        except Exception:
            pass
    conn.commit()
