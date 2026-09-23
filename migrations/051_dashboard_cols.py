def up(conn):
    conn.execute("ALTER TABLE dashboard_prefs ADD COLUMN cols INTEGER DEFAULT 4")
    conn.commit()
