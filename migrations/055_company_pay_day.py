def up(conn):
    conn.execute("ALTER TABLE client_companies ADD COLUMN pay_day INTEGER DEFAULT 25")
