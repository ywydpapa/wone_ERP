def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bank_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            bank TEXT NOT NULL,
            account_no TEXT NOT NULL,
            name TEXT NOT NULL,
            account_code TEXT NOT NULL DEFAULT '103',
            is_active INTEGER DEFAULT 1,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(company_id, account_no)
        );
        CREATE INDEX IF NOT EXISTS idx_bank_accounts_book ON bank_accounts(company_id, is_active);
    """)
