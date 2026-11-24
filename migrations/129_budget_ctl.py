# 예산 통제. 회사별 가용성 점검 설정, 예산 변경 이력, 알림 중복 방지 기록


def up(conn):
    conn.execute("""
        CREATE TABLE budget_cfg (
            company_id INTEGER PRIMARY KEY,
            period TEXT NOT NULL DEFAULT 'year' CHECK(period IN ('year','month')),
            warn_pct INTEGER NOT NULL DEFAULT 90,
            notify_pct INTEGER NOT NULL DEFAULT 95,
            block_pct INTEGER NOT NULL DEFAULT 100
        )
    """)
    conn.execute("""
        CREATE TABLE budget_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            dept TEXT NOT NULL DEFAULT '',
            account_code TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('편성','추가','반환')),
            amount INTEGER NOT NULL,
            reason TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("CREATE INDEX idx_budget_changes_book ON budget_changes(company_id, dept, account_code, year, month)")
    conn.execute("""
        CREATE TABLE budget_notified (
            company_id INTEGER NOT NULL,
            dept TEXT NOT NULL DEFAULT '',
            account_code TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            notified_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (company_id, dept, account_code, year, month)
        )
    """)
    conn.commit()
