# 고객사별 반출 양식 복수 등록(더존, 이카운트 등). 기존 템플릿은 '기본' 양식으로 이관


def up(conn):
    conn.executescript("""
        CREATE TABLE export_templates_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id  INTEGER NOT NULL REFERENCES client_companies(id),
            module      TEXT NOT NULL,
            name        TEXT NOT NULL DEFAULT '기본',
            columns     TEXT NOT NULL DEFAULT '[]',
            file_format TEXT NOT NULL DEFAULT 'xlsx' CHECK(file_format IN ('csv','xlsx')),
            created_by  INTEGER REFERENCES users(id),
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT,
            UNIQUE(company_id, module, name)
        );
        INSERT INTO export_templates_new (id, company_id, module, name, columns, file_format, created_by, created_at, updated_at)
            SELECT id, company_id, module, '기본', columns, file_format, created_by, created_at, updated_at
            FROM export_templates;
        DROP TABLE export_templates;
        ALTER TABLE export_templates_new RENAME TO export_templates;
    """)
    conn.commit()
