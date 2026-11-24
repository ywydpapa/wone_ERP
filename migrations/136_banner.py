# 배너 프로젝트 저장용 테이블 생성

def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS banner_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '새 배너',
            category TEXT NOT NULL DEFAULT 'web',
            preset_name TEXT NOT NULL DEFAULT '가로형 배너 (1200x400)',
            width INTEGER NOT NULL DEFAULT 1200,
            height INTEGER NOT NULL DEFAULT 400,
            canvas_json TEXT NOT NULL DEFAULT '{}',
            thumbnail TEXT DEFAULT '',
            created_by INTEGER,
            created_by_name TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()
