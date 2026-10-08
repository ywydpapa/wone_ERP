# 전표 적요 표준화 마스터. 자주 쓰는 적요를 코드로 등록해 입력 속도를 높임


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            code TEXT NOT NULL,
            text TEXT NOT NULL,
            account_code TEXT,
            is_active INTEGER DEFAULT 1,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(company_id, code)
        );
        CREATE INDEX IF NOT EXISTS idx_memo_codes_book ON memo_codes(company_id, is_active);
    """)
