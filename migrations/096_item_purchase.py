# 품목 구매 기준정보. 발주단위는 발주 수량 배수(반올림 단위)로 사용, 재고 단위 환산 없음


def up(conn):
    conn.execute("ALTER TABLE items ADD COLUMN purch_group TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE items ADD COLUMN partner_id INTEGER REFERENCES partners(id)")
    conn.execute("ALTER TABLE items ADD COLUMN lead_days INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE items ADD COLUMN moq INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE items ADD COLUMN order_unit INTEGER NOT NULL DEFAULT 1")
    conn.execute("ALTER TABLE items ADD COLUMN reorder_pt INTEGER NOT NULL DEFAULT 0")
