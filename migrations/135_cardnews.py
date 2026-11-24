# 카드뉴스 프로젝트 저장용 테이블 생성

def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cardnews_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '새 카드뉴스',
            aspect_ratio TEXT NOT NULL DEFAULT '1:1',
            width INTEGER NOT NULL DEFAULT 1080,
            height INTEGER NOT NULL DEFAULT 1080,
            slides_json TEXT NOT NULL DEFAULT '[]',
            thumbnail TEXT DEFAULT '',
            created_by INTEGER,
            created_by_name TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()
