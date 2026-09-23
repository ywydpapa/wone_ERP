def up(conn):
    # SQLite는 CHECK 제약 변경을 ALTER로 지원 안 함 -> 테이블 재생성
    conn.executescript("""
        PRAGMA foreign_keys = OFF;

        CREATE TABLE attendance_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            work_date TEXT NOT NULL,
            clock_in TEXT,
            clock_out TEXT,
            work_minutes INTEGER DEFAULT 0,
            overtime_minutes INTEGER DEFAULT 0,
            break_minutes INTEGER DEFAULT 0,
            status TEXT DEFAULT 'normal'
                CHECK(status IN ('normal','late','early_leave','late_early','absent','holiday')),
            notes TEXT DEFAULT '',
            appeal TEXT CHECK(appeal IN ('pending','approved','rejected')),
            appeal_type TEXT,
            appeal_reason TEXT DEFAULT '',
            appeal_file TEXT DEFAULT '',
            appeal_reviewed_by INTEGER REFERENCES users(id),
            appeal_at TEXT,
            appeal_reject_reason TEXT DEFAULT '',
            disability_related INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        INSERT INTO attendance_new (
            id, employee_id, work_date, clock_in, clock_out,
            work_minutes, overtime_minutes, break_minutes,
            status, notes, appeal, appeal_type, appeal_reason,
            appeal_file, appeal_reviewed_by, appeal_at,
            appeal_reject_reason, disability_related, created_at
        )
        SELECT
            id, employee_id, work_date, clock_in, clock_out,
            work_minutes, overtime_minutes, break_minutes,
            status, notes, appeal, appeal_type, appeal_reason,
            appeal_file, appeal_reviewed_by, appeal_at,
            appeal_reject_reason, disability_related, created_at
        FROM attendance;

        DROP TABLE attendance;

        ALTER TABLE attendance_new RENAME TO attendance;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_emp_date
            ON attendance(employee_id, work_date);

        PRAGMA foreign_keys = ON;
    """)
    conn.commit()
