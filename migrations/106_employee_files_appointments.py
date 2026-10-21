# 근로자 서류 보관(employee_files), 인사 발령 이력(hr_appointments)


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS employee_files (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id  INTEGER,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            kind        TEXT NOT NULL CHECK(kind IN ('계약서','신분증','통장','자격','기타')),
            name        TEXT NOT NULL,
            path        TEXT NOT NULL,
            uploaded_by INTEGER REFERENCES users(id),
            uploaded_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_employee_files_emp ON employee_files(employee_id);
        CREATE INDEX IF NOT EXISTS idx_employee_files_company ON employee_files(company_id);

        CREATE TABLE IF NOT EXISTS hr_appointments (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id     INTEGER,
            employee_id    INTEGER NOT NULL REFERENCES employees(id),
            kind           TEXT NOT NULL CHECK(kind IN ('부서이동','승진','급여변경','휴직','복직')),
            from_val       TEXT DEFAULT '',
            to_val         TEXT DEFAULT '',
            effective_date TEXT NOT NULL,
            memo           TEXT DEFAULT '',
            created_by     INTEGER REFERENCES users(id),
            created_at     TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_hr_appointments_emp ON hr_appointments(employee_id, id);
        CREATE INDEX IF NOT EXISTS idx_hr_appointments_company ON hr_appointments(company_id);
    """)
