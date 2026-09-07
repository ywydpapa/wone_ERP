def up(conn):
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(partners)").fetchall()]

    new_cols = [
        ("partner_type", "TEXT CHECK(partner_type IN ('supplier','customer','both')) DEFAULT 'supplier'"),
        ("contact_name", "TEXT DEFAULT ''"),
        ("contact_phone", "TEXT DEFAULT ''"),
        ("contact_email", "TEXT DEFAULT ''"),
        ("email", "TEXT DEFAULT ''"),
        ("fax", "TEXT DEFAULT ''"),
        ("notes", "TEXT DEFAULT ''"),
    ]
    for col_name, col_def in new_cols:
        if col_name not in cols:
            conn.execute(f"ALTER TABLE partners ADD COLUMN {col_name} {col_def}")

    conn.execute("UPDATE partners SET partner_type='supplier' WHERE partner_type IS NULL")
    conn.commit()
