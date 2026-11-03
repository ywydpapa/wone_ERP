# 업무일지 첨부. 기존 업로드 파일이 기록에 미연결


def up(conn):
    conn.execute("ALTER TABLE jobs ADD COLUMN attachment TEXT NOT NULL DEFAULT ''")
    conn.commit()
