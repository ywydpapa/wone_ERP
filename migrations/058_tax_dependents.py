def up(conn):
    conn.execute("ALTER TABLE employees ADD COLUMN tax_dependent_count INTEGER DEFAULT 1")
