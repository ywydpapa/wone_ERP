def up(conn):
    tables = ["erp_docs", "purchase_orders", "goods_receipts", "purchase_requisitions",
              "quotations", "sales_orders", "shipments", "work_orders", "bom_headers",
              "production_results", "items", "partners"]
    for tbl in tables:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
        if "task_id" not in cols:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN task_id INTEGER REFERENCES tasks(id)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS export_templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id  INTEGER NOT NULL REFERENCES client_companies(id),
            module      TEXT NOT NULL,
            columns     TEXT NOT NULL DEFAULT '[]',
            file_format TEXT NOT NULL DEFAULT 'xlsx' CHECK(file_format IN ('csv','xlsx')),
            created_by  INTEGER REFERENCES users(id),
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT,
            UNIQUE(company_id, module)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS export_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id      INTEGER NOT NULL REFERENCES client_companies(id),
            user_id         INTEGER NOT NULL REFERENCES users(id),
            work_request_id INTEGER NOT NULL REFERENCES work_requests(id),
            kind            TEXT NOT NULL DEFAULT 'data' CHECK(kind IN ('data','files')),
            template_id     INTEGER REFERENCES export_templates(id),
            row_count       INTEGER DEFAULT 0,
            file_name       TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_export_logs_company ON export_logs(company_id, created_at)")
    conn.commit()
