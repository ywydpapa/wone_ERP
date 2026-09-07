def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_number TEXT UNIQUE NOT NULL,
            partner_id INTEGER REFERENCES partners(id),
            po_date TEXT NOT NULL,
            delivery_date TEXT,
            status TEXT CHECK(status IN ('draft','confirmed','partial','completed','cancelled')) DEFAULT 'draft',
            doc_id INTEGER REFERENCES erp_docs(id),
            total_amount INTEGER DEFAULT 0,
            tax_amount INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS po_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id INTEGER NOT NULL REFERENCES purchase_orders(id),
            line_no INTEGER,
            item_id INTEGER NOT NULL REFERENCES items(id),
            quantity INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            received_qty INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS goods_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gr_number TEXT UNIQUE NOT NULL,
            po_id INTEGER REFERENCES purchase_orders(id),
            warehouse_id INTEGER REFERENCES warehouses(id),
            receipt_date TEXT NOT NULL,
            status TEXT CHECK(status IN ('draft','confirmed')) DEFAULT 'draft',
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gr_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gr_id INTEGER NOT NULL REFERENCES goods_receipts(id),
            po_line_id INTEGER REFERENCES po_lines(id),
            item_id INTEGER NOT NULL REFERENCES items(id),
            received_qty INTEGER NOT NULL,
            defective_qty INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES items(id),
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            trans_date TEXT NOT NULL,
            trans_type TEXT CHECK(trans_type IN ('in','out','adjust')) NOT NULL,
            quantity INTEGER NOT NULL,
            ref_type TEXT,
            ref_id INTEGER,
            balance_qty INTEGER,
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.commit()
