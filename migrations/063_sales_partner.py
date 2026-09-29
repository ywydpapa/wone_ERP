def up(conn):
    for table in ("quotations", "sales_orders"):
        cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if cnt:
            raise Exception(f"{table}에 데이터가 있어 partner_id 전환을 위한 재생성을 할 수 없습니다.")

    conn.executescript("""
        CREATE TABLE quotations_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_number TEXT UNIQUE NOT NULL,
            partner_id INTEGER REFERENCES partners(id),
            quote_date TEXT NOT NULL,
            valid_until TEXT,
            status TEXT CHECK(status IN ('draft','sent','accepted','rejected','expired')) DEFAULT 'draft',
            total_amount INTEGER DEFAULT 0,
            tax_amount INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            task_id INTEGER REFERENCES tasks(id)
        );
        DROP TABLE quotations;
        ALTER TABLE quotations_new RENAME TO quotations;

        CREATE TABLE sales_orders_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            so_number TEXT UNIQUE NOT NULL,
            quote_id INTEGER REFERENCES quotations(id),
            partner_id INTEGER REFERENCES partners(id),
            order_date TEXT NOT NULL,
            delivery_date TEXT,
            status TEXT CHECK(status IN ('confirmed','picking','shipped','invoiced','cancelled')) DEFAULT 'confirmed',
            total_amount INTEGER DEFAULT 0,
            tax_amount INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            task_id INTEGER REFERENCES tasks(id)
        );
        DROP TABLE sales_orders;
        ALTER TABLE sales_orders_new RENAME TO sales_orders;
    """)
