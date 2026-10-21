# 고정자산 자본적 지출. 상각 시작 후 증설비 등 취득가 추가분을 별도 기록해 다음 연도 상각 기초에 반영


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS fa_capex (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            asset_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount INTEGER NOT NULL,
            memo TEXT NOT NULL DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_fa_capex_asset ON fa_capex(asset_id);
    """)
