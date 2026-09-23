def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leave_accruals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            accrual_year INTEGER NOT NULL,
            granted     INTEGER NOT NULL,
            used        REAL NOT NULL DEFAULT 0,
            basis       TEXT NOT NULL DEFAULT 'auto',
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(employee_id, accrual_year)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leave_accruals_emp ON leave_accruals(employee_id)")
