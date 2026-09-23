def up(conn):
    try:
        conn.execute("ALTER TABLE employees ADD COLUMN resign_date TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE employees ADD COLUMN resign_reason TEXT")
    except Exception:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS severance_records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER REFERENCES employees(id),
            calc_date   TEXT,
            avg_salary  INTEGER,
            tenure_days INTEGER,
            amount      INTEGER,
            status      TEXT DEFAULT 'pending' CHECK(status IN ('pending','paid','cancelled')),
            created_by  INTEGER,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
