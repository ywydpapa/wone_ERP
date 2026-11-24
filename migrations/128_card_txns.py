# 법인카드 사용내역. card_txns 테이블 생성


def up(conn):
    conn.execute("""
        CREATE TABLE card_txns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            card_no TEXT DEFAULT '',
            approve_date TEXT NOT NULL,
            approval_no TEXT NOT NULL,
            merchant TEXT DEFAULT '',
            merchant_biz_no TEXT DEFAULT '',
            supply_amt INTEGER NOT NULL DEFAULT 0,
            vat INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','posted','skip')),
            tax_invoice_id INTEGER REFERENCES tax_invoices(id),
            doc_id INTEGER REFERENCES erp_docs(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(company_id, card_no, approval_no, approve_date)
        )
    """)
    conn.execute("CREATE INDEX idx_card_txns_book ON card_txns(company_id)")
    conn.commit()
