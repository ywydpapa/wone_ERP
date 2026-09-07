def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_number TEXT UNIQUE NOT NULL,
            customer_id INTEGER REFERENCES client_companies(id),
            quote_date TEXT NOT NULL,
            valid_until TEXT,
            status TEXT CHECK(status IN ('draft','sent','accepted','rejected','expired')) DEFAULT 'draft',
            total_amount INTEGER DEFAULT 0,
            tax_amount INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS quote_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_id INTEGER NOT NULL REFERENCES quotations(id),
            line_no INTEGER,
            item_id INTEGER NOT NULL REFERENCES items(id),
            quantity INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            discount_rate REAL DEFAULT 0,
            amount INTEGER NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sales_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            so_number TEXT UNIQUE NOT NULL,
            quote_id INTEGER REFERENCES quotations(id),
            customer_id INTEGER REFERENCES client_companies(id),
            order_date TEXT NOT NULL,
            delivery_date TEXT,
            status TEXT CHECK(status IN ('confirmed','picking','shipped','invoiced','cancelled')) DEFAULT 'confirmed',
            total_amount INTEGER DEFAULT 0,
            tax_amount INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS so_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            so_id INTEGER NOT NULL REFERENCES sales_orders(id),
            line_no INTEGER,
            item_id INTEGER NOT NULL REFERENCES items(id),
            quantity INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            shipped_qty INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ship_number TEXT UNIQUE NOT NULL,
            so_id INTEGER REFERENCES sales_orders(id),
            warehouse_id INTEGER REFERENCES warehouses(id),
            ship_date TEXT NOT NULL,
            status TEXT CHECK(status IN ('draft','confirmed')) DEFAULT 'draft',
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ship_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ship_id INTEGER NOT NULL REFERENCES shipments(id),
            so_line_id INTEGER REFERENCES so_lines(id),
            item_id INTEGER NOT NULL REFERENCES items(id),
            shipped_qty INTEGER NOT NULL
        )
    """)

    conn.commit()
