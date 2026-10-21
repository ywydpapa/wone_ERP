# 예산에 부서 차원 추가. 미지정은 전사 예산 취급. NULL 대신 빈문자 사용(UNIQUE 중복 체크 때문)


def up(conn):
    conn.executescript("""
        CREATE TABLE budgets_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            dept TEXT NOT NULL DEFAULT '',
            account_code TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(company_id, dept, account_code, year, month)
        );
        INSERT INTO budgets_new (id, company_id, dept, account_code, year, month, amount, created_by, created_at)
            SELECT id, company_id, '', account_code, year, month, amount, created_by, created_at FROM budgets;
        DROP TABLE budgets;
        ALTER TABLE budgets_new RENAME TO budgets;
        CREATE INDEX IF NOT EXISTS idx_budgets_dept ON budgets(company_id, dept, year);
    """)
