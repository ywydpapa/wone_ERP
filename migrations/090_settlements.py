# 수금/지급 반제. 미결 기준은 전표 문서(charge_doc_id). 취소는 역분개 후 배분 삭제


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('수금','지급')),
            settle_date TEXT NOT NULL,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            amount INTEGER NOT NULL,
            method TEXT NOT NULL,
            bank_account_id INTEGER REFERENCES bank_accounts(id),
            account_code TEXT NOT NULL,
            wht_type TEXT NOT NULL DEFAULT '없음',
            wht_amt INTEGER NOT NULL DEFAULT 0,
            doc_id INTEGER REFERENCES erp_docs(id),
            memo TEXT NOT NULL DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            canceled_at TEXT,
            cancel_doc_id INTEGER REFERENCES erp_docs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_settlements_company ON settlements(company_id, settle_date);
        CREATE INDEX IF NOT EXISTS idx_settlements_partner ON settlements(partner_id);

        CREATE TABLE IF NOT EXISTS settlement_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            settlement_id INTEGER NOT NULL REFERENCES settlements(id),
            charge_doc_id INTEGER NOT NULL REFERENCES erp_docs(id),
            amount INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_settlement_items_charge ON settlement_items(charge_doc_id);
        CREATE INDEX IF NOT EXISTS idx_settlement_items_settle ON settlement_items(settlement_id);
    """)
