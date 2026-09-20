
def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS purchase_requisitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pr_number TEXT UNIQUE NOT NULL,
            requester_id INTEGER NOT NULL REFERENCES users(id),
            dept TEXT,
            request_date TEXT NOT NULL,
            need_date TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS pr_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pr_id INTEGER NOT NULL REFERENCES purchase_requisitions(id),
            line_no INTEGER NOT NULL,
            item_id INTEGER REFERENCES items(id),
            item_name TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            estimated_price INTEGER DEFAULT 0,
            notes TEXT
        );
    """)
    conn.commit()
