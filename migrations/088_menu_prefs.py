# 메뉴 그룹 숨김. 즐겨찾기와 같이 사용자 단위 서버 저장


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS menu_prefs (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            hidden TEXT NOT NULL DEFAULT ''
        );
    """)
