# erp_activity_log 테이블 생성, created_by 컬럼 추가

def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS erp_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            action TEXT NOT NULL,
            module TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            doc_number TEXT,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_erp_activity_user_date
        ON erp_activity_log(user_id, created_at)
    """)

    tables = ["items", "partners", "warehouses", "bom_headers", "production_results"]
    for tbl in tables:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
        if "created_by" not in cols:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN created_by INTEGER REFERENCES users(id)")

    conn.commit()
