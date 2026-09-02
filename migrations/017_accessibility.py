def up(conn):
    conn.execute("ALTER TABLE users ADD COLUMN accessibility_settings TEXT DEFAULT '{}'")
    conn.commit()
