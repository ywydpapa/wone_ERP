def up(conn):
    cur = conn.execute("PRAGMA table_info(jobs)")
    cols = [r[1] for r in cur.fetchall()]
    if "task_id" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN task_id INTEGER REFERENCES tasks(id)")
    conn.commit()
