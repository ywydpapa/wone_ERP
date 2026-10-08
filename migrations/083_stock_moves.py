# 재고조정(실사, 기초재고)과 창고 간 이동 헤더. 품목별 수량/금액은 stock_transactions에 ref_type adj/transfer로 기록


def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('adjust','transfer')),
            move_number TEXT NOT NULL UNIQUE,
            move_date TEXT NOT NULL,
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            to_wh_id INTEGER REFERENCES warehouses(id),
            reason TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            doc_id INTEGER REFERENCES erp_docs(id),
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_moves_company ON stock_moves(company_id, kind, move_date)")
