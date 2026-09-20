
def up(conn):
    conn.executescript("""
        CREATE TABLE purchase_orders_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_number TEXT UNIQUE NOT NULL,
            partner_id INTEGER REFERENCES partners(id),
            po_date TEXT NOT NULL,
            delivery_date TEXT,
            status TEXT CHECK(status IN ('draft','pending_approval','confirmed','partial','completed','cancelled')) DEFAULT 'draft',
            doc_id INTEGER REFERENCES erp_docs(id),
            total_amount INTEGER DEFAULT 0,
            tax_amount INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT
        );
        INSERT INTO purchase_orders_new SELECT * FROM purchase_orders;
        DROP TABLE purchase_orders;
        ALTER TABLE purchase_orders_new RENAME TO purchase_orders;
    """)
    conn.commit()
