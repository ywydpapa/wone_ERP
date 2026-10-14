# 견적요청(RFQ)과 업체별 견적. 낙찰은 결재 문서(erp_docs) 완료 후 발주 생성


def up(conn):
    conn.execute("""
        CREATE TABLE rfqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            rfq_number TEXT NOT NULL UNIQUE,
            pr_id INTEGER REFERENCES purchase_requisitions(id),
            rfq_date TEXT NOT NULL,
            due_date TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','pending','ordered','cancelled')),
            partner_id INTEGER REFERENCES partners(id),
            doc_id INTEGER REFERENCES erp_docs(id),
            po_id INTEGER REFERENCES purchase_orders(id),
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("CREATE INDEX idx_rfqs_company ON rfqs(company_id, status)")
    conn.execute("""
        CREATE TABLE rfq_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id INTEGER NOT NULL REFERENCES rfqs(id),
            line_no INTEGER NOT NULL,
            item_id INTEGER NOT NULL REFERENCES items(id),
            quantity INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE rfq_vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id INTEGER NOT NULL REFERENCES rfqs(id),
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            quote_date TEXT DEFAULT '',
            valid_to TEXT DEFAULT '',
            lead_days INTEGER NOT NULL DEFAULT 0,
            notes TEXT DEFAULT '',
            UNIQUE(rfq_id, partner_id)
        )
    """)
    conn.execute("""
        CREATE TABLE rfq_quotes (
            vendor_id INTEGER NOT NULL REFERENCES rfq_vendors(id),
            line_id INTEGER NOT NULL REFERENCES rfq_lines(id),
            price INTEGER NOT NULL,
            PRIMARY KEY (vendor_id, line_id)
        )
    """)
