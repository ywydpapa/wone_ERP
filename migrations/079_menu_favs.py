# 메뉴 즐겨찾기. 공유오피스 PC 교체 시에도 유지되도록 서버 저장


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS menu_favs (
            user_id INTEGER NOT NULL REFERENCES users(id),
            href TEXT NOT NULL,
            label TEXT NOT NULL,
            sort INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (user_id, href)
        );
    """)
