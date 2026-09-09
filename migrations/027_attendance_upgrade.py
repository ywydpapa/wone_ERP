def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS attendance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attendance_id INTEGER NOT NULL REFERENCES attendance(id),
            changed_by INTEGER NOT NULL REFERENCES users(id),
            field TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            reason TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_attendance_logs_att
            ON attendance_logs(attendance_id);
    """)

    # appeal 정책 컬럼
    cursor = conn.execute("PRAGMA table_info(client_companies)")
    cols = [r[1] for r in cursor.fetchall()]

    if "appeal_guide" not in cols:
        conn.execute("ALTER TABLE client_companies ADD COLUMN appeal_guide TEXT DEFAULT ''")
    if "appeal_types" not in cols:
        conn.execute(
            "ALTER TABLE client_companies ADD COLUMN appeal_types TEXT "
            "DEFAULT '[\"transit\",\"medical\",\"accident\",\"disability\",\"family\",\"etc\"]'"
        )
    if "appeal_require_file" not in cols:
        conn.execute("ALTER TABLE client_companies ADD COLUMN appeal_require_file INTEGER DEFAULT 0")

    conn.commit()
