# 거래처별 단가를 구매정보레코드로 확장. 거래처 x 품목당 현재 조건 1건 유지, 빈 날짜는 기간 제한 없음


def up(conn):
    conn.execute("ALTER TABLE partner_prices ADD COLUMN valid_from TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE partner_prices ADD COLUMN valid_to TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE partner_prices ADD COLUMN lead_days INTEGER NOT NULL DEFAULT 0")
