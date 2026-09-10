
def up(conn):
    conn.execute("ALTER TABLE employees ADD COLUMN base_salary INTEGER NOT NULL DEFAULT 0")
    conn.commit()
