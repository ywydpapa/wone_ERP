# 양식별 기본 결재선. form_key는 문서유형(draft, leave 등) 또는 회사 서식(tpl-{id})


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS approval_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            form_key TEXT NOT NULL,
            lines TEXT NOT NULL DEFAULT '[]',
            updated_by INTEGER REFERENCES users(id),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(company_id, form_key)
        );
        CREATE INDEX IF NOT EXISTS idx_approval_lines_user ON approval_lines(approver_id, status);
        CREATE INDEX IF NOT EXISTS idx_approval_lines_doc ON approval_lines(doc_id, step);
    """)
