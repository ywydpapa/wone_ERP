def up(conn):
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(attendance)").fetchall()]

    new_cols = [
        ("appeal", "TEXT CHECK(appeal IN ('pending','approved','rejected'))"),
        ("appeal_type", "TEXT"),
        ("appeal_reason", "TEXT DEFAULT ''"),
        ("appeal_file", "TEXT DEFAULT ''"),
        ("appeal_reviewed_by", "INTEGER"),
        ("appeal_at", "TEXT"),
        ("disability_related", "INTEGER DEFAULT 0"),
    ]
    for col_name, col_def in new_cols:
        if col_name not in cols:
            conn.execute(f"ALTER TABLE attendance ADD COLUMN {col_name} {col_def}")

    conn.commit()
