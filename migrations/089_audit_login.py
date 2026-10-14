# 감사 로그, 계정 기준 로그인 이력 및 잠금


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            user_id INTEGER,
            user_name TEXT,
            role TEXT,
            company_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            summary TEXT NOT NULL DEFAULT '',
            detail TEXT,
            ip TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_company_at ON audit_logs(company_id, at);
        CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_logs(target_type, target_id);

        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            ip TEXT,
            ok INTEGER NOT NULL,
            at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_login_attempts_user_at ON login_attempts(username, at);
    """)
    conn.execute("ALTER TABLE users ADD COLUMN locked_until TEXT")
