def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES client_companies(id),
            start_time TEXT NOT NULL DEFAULT '09:00',
            end_time TEXT NOT NULL DEFAULT '18:00',
            break_min INTEGER NOT NULL DEFAULT 60,
            UNIQUE(company_id)
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO work_schedules (company_id)
        SELECT id FROM client_companies
    """)
    conn.commit()
