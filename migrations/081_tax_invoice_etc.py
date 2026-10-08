# 증빙 없는 매출(건별 14, 수출 16) 입력을 위해 증빙 CHECK에 기타 추가. SQLite는 CHECK 변경 불가. 재생성


def up(conn):
    conn.execute("""
        CREATE TABLE tax_invoices_081_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            kind TEXT NOT NULL CHECK(kind IN ('매출','매입')),
            tax_type TEXT NOT NULL DEFAULT '과세' CHECK(tax_type IN ('과세','영세','면세')),
            evidence TEXT NOT NULL DEFAULT '세금계산서' CHECK(evidence IN ('세금계산서','계산서','카드','현금영수증','기타')),
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
            created_at TEXT DEFAULT (datetime('now','localtime')),
            receipt_type TEXT DEFAULT '청구',
            remark TEXT DEFAULT '',
            amend_reason INTEGER
        )
    """)
    cols = (
        "id, company_id, kind, tax_type, evidence, issue_date, partner_id, supply_amt, vat, total, approval_no, "
        "is_electronic, deduct, doc_id, source_type, source_id, status, orig_id, created_by, created_at, "
        "receipt_type, remark, amend_reason"
    )
    conn.execute(f"INSERT INTO tax_invoices_081_new ({cols}) SELECT {cols} FROM tax_invoices")
    conn.execute("DROP TABLE tax_invoices")
    conn.execute("ALTER TABLE tax_invoices_081_new RENAME TO tax_invoices")
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_tax_inv_book ON tax_invoices(company_id, issue_date);
        CREATE INDEX IF NOT EXISTS idx_tax_inv_doc ON tax_invoices(doc_id);
        CREATE INDEX IF NOT EXISTS idx_tax_inv_orig ON tax_invoices(orig_id);
    """)
