def up(conn):
    conn.execute("ALTER TABLE work_requests ADD COLUMN rejected_at TEXT")
    conn.commit()
