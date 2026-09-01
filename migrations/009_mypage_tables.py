
def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            leave_type TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days REAL NOT NULL DEFAULT 1,
            reason TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            approved_by INTEGER,
            approved_at TEXT,
            reject_reason TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS accommodation_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            urgency TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by INTEGER,
            reviewed_at TEXT,
            review_notes TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS certificate_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            cert_type TEXT NOT NULL,
            purpose TEXT,
            status TEXT DEFAULT 'pending',
            requested_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    employees_columns = [
        ("annual_leave_total", "REAL DEFAULT 15"),
        ("annual_leave_used", "REAL DEFAULT 0"),
        ("bank_name", "TEXT"),
        ("bank_account", "TEXT"),
        ("address", "TEXT"),
    ]
    for col_name, col_def in employees_columns:
        try:
            conn.execute(f"ALTER TABLE employees ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass

    conn.commit()
