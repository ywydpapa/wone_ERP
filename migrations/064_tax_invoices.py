def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tax_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            kind TEXT NOT NULL CHECK(kind IN ('매출','매입')),
            tax_type TEXT NOT NULL DEFAULT '과세' CHECK(tax_type IN ('과세','영세','면세')),
            evidence TEXT NOT NULL DEFAULT '세금계산서' CHECK(evidence IN ('세금계산서','계산서','카드','현금영수증')),
            issue_date TEXT NOT NULL,
            partner_id INTEGER REFERENCES partners(id),
            supply_amt INTEGER NOT NULL,
            vat INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL,
            approval_no TEXT DEFAULT '',
            is_electronic INTEGER DEFAULT 1,
            deduct INTEGER DEFAULT 1,
            doc_id INTEGER REFERENCES erp_docs(id),
            source_type TEXT DEFAULT 'manual',
            source_id INTEGER,
            status TEXT NOT NULL DEFAULT '정상' CHECK(status IN ('정상','수정','취소')),
            orig_id INTEGER REFERENCES tax_invoices(id),
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tax_inv_book ON tax_invoices(company_id, issue_date);
        CREATE INDEX IF NOT EXISTS idx_tax_inv_doc ON tax_invoices(doc_id);
        CREATE INDEX IF NOT EXISTS idx_tax_inv_orig ON tax_invoices(orig_id);

        CREATE TABLE IF NOT EXISTS tax_invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL REFERENCES tax_invoices(id),
            line_no INTEGER NOT NULL,
            item_date TEXT,
            name TEXT NOT NULL,
            spec TEXT DEFAULT '',
            qty INTEGER DEFAULT 0,
            unit_price INTEGER DEFAULT 0,
            supply_amt INTEGER NOT NULL,
            vat INTEGER NOT NULL DEFAULT 0
        );

        ALTER TABLE partners ADD COLUMN tax_type TEXT DEFAULT '과세';
        ALTER TABLE client_companies ADD COLUMN biz_type TEXT DEFAULT '';
        ALTER TABLE client_companies ADD COLUMN biz_item TEXT DEFAULT '';
    """)
