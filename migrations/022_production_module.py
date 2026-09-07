def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bom_headers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES items(id),
            bom_version TEXT DEFAULT '1.0',
            effective_date TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bom_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bom_id INTEGER NOT NULL REFERENCES bom_headers(id),
            component_id INTEGER NOT NULL REFERENCES items(id),
            quantity REAL NOT NULL,
            unit TEXT DEFAULT 'EA',
            process_step TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wo_number TEXT UNIQUE NOT NULL,
            product_id INTEGER NOT NULL REFERENCES items(id),
            bom_id INTEGER REFERENCES bom_headers(id),
            planned_qty INTEGER NOT NULL,
            actual_qty INTEGER DEFAULT 0,
            planned_start TEXT,
            planned_end TEXT,
            actual_start TEXT,
            actual_end TEXT,
            worker_id INTEGER REFERENCES employees(id),
            status TEXT CHECK(status IN ('planned','released','in_progress','completed','cancelled')) DEFAULT 'planned',
            doc_id INTEGER REFERENCES erp_docs(id),
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS production_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wo_id INTEGER NOT NULL REFERENCES work_orders(id),
            result_date TEXT NOT NULL,
            good_qty INTEGER NOT NULL,
            defect_qty INTEGER DEFAULT 0,
            worker_id INTEGER REFERENCES employees(id),
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.commit()
