# 세션 강제 무효화용 버전 컬럼. 장애인 인식개선교육 실시/이수 기록


def up(conn):
    conn.executescript("""
        ALTER TABLE users ADD COLUMN sess_ver INTEGER NOT NULL DEFAULT 0;

        CREATE TABLE IF NOT EXISTS disability_awareness_trainings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id  INTEGER,
            held_date   TEXT NOT NULL,
            method      TEXT NOT NULL,
            instructor  TEXT DEFAULT '',
            content     TEXT DEFAULT '',
            created_by  INTEGER REFERENCES users(id),
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_training_company ON disability_awareness_trainings(company_id, held_date);

        CREATE TABLE IF NOT EXISTS disability_awareness_attendees (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            training_id INTEGER NOT NULL REFERENCES disability_awareness_trainings(id),
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            completed   INTEGER NOT NULL DEFAULT 1,
            UNIQUE(training_id, employee_id)
        );
        CREATE INDEX IF NOT EXISTS idx_attendee_emp ON disability_awareness_attendees(employee_id, completed);
    """)
