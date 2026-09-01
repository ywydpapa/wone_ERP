def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS worker_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            company_id INTEGER NOT NULL REFERENCES client_companies(id),
            eval_year INTEGER NOT NULL,
            eval_quarter INTEGER NOT NULL,
            work_quality INTEGER DEFAULT 3,
            work_attitude INTEGER DEFAULT 3,
            cooperation INTEGER DEFAULT 3,
            punctuality INTEGER DEFAULT 3,
            overall_score REAL,
            strengths TEXT,
            improvements TEXT,
            comments TEXT,
            evaluator_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT,
            UNIQUE(employee_id, eval_year, eval_quarter)
        )
    """)
    conn.commit()
