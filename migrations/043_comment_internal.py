def up(conn):
    conn.execute("ALTER TABLE work_request_comments ADD COLUMN is_internal INTEGER DEFAULT 0")
    conn.commit()
