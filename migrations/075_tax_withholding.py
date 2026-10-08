def up(conn):
    conn.execute("ALTER TABLE employees ADD COLUMN tax_child_count INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE employees ADD COLUMN tax_rate INTEGER DEFAULT 100")
