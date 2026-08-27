def up(conn):
    for col_name, col_def in [
        ("category", "TEXT DEFAULT '공통'"),
        ("form_schema", "TEXT DEFAULT '{}'"),
        ("doc_number_prefix", "TEXT DEFAULT 'DOC'"),
        ("is_active", "INTEGER DEFAULT 1"),
        ("name", "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f"ALTER TABLE document_types ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    conn.execute("UPDATE document_types SET name = code WHERE name = '' OR name IS NULL")
    conn.commit()
