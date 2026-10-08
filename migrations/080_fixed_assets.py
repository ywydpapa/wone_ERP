# 고정자산 대장, 연도별 감가상각 이력, 회기 마감. 감가상각은 법인세법 기준 연 단위 월할 계산


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS fixed_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            account_code TEXT NOT NULL,
            acq_date TEXT NOT NULL,
            acq_cost INTEGER NOT NULL,
            life_years INTEGER NOT NULL,
            method TEXT NOT NULL DEFAULT '정액법',
            open_accum INTEGER NOT NULL DEFAULT 0,
            open_year INTEGER NOT NULL,
            dept TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            disposed_date TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(company_id, code)
        );
        CREATE TABLE IF NOT EXISTS fa_depr (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            asset_id INTEGER NOT NULL REFERENCES fixed_assets(id),
            year INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            doc_id INTEGER REFERENCES erp_docs(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(asset_id, year)
        );
        CREATE TABLE IF NOT EXISTS fiscal_closings (
            company_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'closed',
            closed_by INTEGER REFERENCES users(id),
            closed_at TEXT,
            reopened_by INTEGER REFERENCES users(id),
            reopened_at TEXT,
            reopen_reason TEXT,
            PRIMARY KEY (company_id, year)
        );
    """)
