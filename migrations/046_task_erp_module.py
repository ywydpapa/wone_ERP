def up(conn):
    cur = conn.execute("PRAGMA table_info(tasks)")
    cols = [r[1] for r in cur.fetchall()]
    if "erp_module" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN erp_module TEXT DEFAULT ''")
    conn.commit()
