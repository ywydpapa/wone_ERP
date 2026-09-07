def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code TEXT UNIQUE NOT NULL,
            item_name TEXT NOT NULL,
            item_type TEXT CHECK(item_type IN ('material','product','semi','consumable')) DEFAULT 'material',
            unit TEXT DEFAULT 'EA',
            unit_price INTEGER DEFAULT 0,
            safety_stock INTEGER DEFAULT 0,
            category TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS warehouses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            location TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES items(id),
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            quantity INTEGER DEFAULT 0,
            UNIQUE(item_id, warehouse_id)
        )
    """)

    accounts = [
        # 자산
        ("101", "현금",         "자산", 1, ""),
        ("102", "당좌예금",     "자산", 1, ""),
        ("103", "보통예금",     "자산", 1, ""),
        ("108", "단기금융상품", "자산", 1, ""),
        ("110", "외상매출금",   "자산", 1, ""),
        ("111", "받을어음",     "자산", 1, ""),
        ("112", "미수금",       "자산", 1, ""),
        ("113", "선급금",       "자산", 1, ""),
        ("114", "선급비용",     "자산", 1, ""),
        ("115", "부가세대급금", "자산", 1, ""),
        ("120", "상품",         "자산", 1, ""),
        ("121", "제품",         "자산", 1, ""),
        ("130", "원재료",       "자산", 1, ""),
        ("131", "부재료",       "자산", 1, ""),
        ("132", "재공품",       "자산", 1, ""),
        ("140", "비품",         "자산", 1, ""),
        ("150", "건물",         "자산", 1, ""),
        ("151", "기계장치",     "자산", 1, ""),
        ("152", "차량운반구",   "자산", 1, ""),
        ("159", "감가상각누계액", "자산", 0, ""),
        # 부채
        ("201", "외상매입금",   "부채", 0, ""),
        ("202", "지급어음",     "부채", 0, ""),
        ("203", "미지급금",     "부채", 0, ""),
        ("204", "선수금",       "부채", 0, ""),
        ("205", "미지급비용",   "부채", 0, ""),
        ("206", "예수금",       "부채", 0, ""),
        ("210", "부가세예수금", "부채", 0, ""),
        ("220", "단기차입금",   "부채", 0, ""),
        ("230", "장기차입금",   "부채", 0, ""),
        ("263", "예수금-소득세",   "부채", 0, ""),
        ("264", "예수금-국민연금", "부채", 0, ""),
        ("265", "예수금-건강보험", "부채", 0, ""),
        ("266", "예수금-고용보험", "부채", 0, ""),
        # 자본
        ("301", "자본금",       "자본", 0, ""),
        ("331", "이익잉여금",   "자본", 0, ""),
        # 수익
        ("401", "상품매출",     "수익", 0, ""),
        ("402", "제품매출",     "수익", 0, ""),
        ("403", "용역매출",     "수익", 0, ""),
        ("410", "임대료수익",   "수익", 0, ""),
        ("420", "이자수익",     "수익", 0, ""),
        ("490", "잡이익",       "수익", 0, ""),
        # 비용
        ("501", "상품매입",     "비용", 1, ""),
        ("502", "원재료매입",   "비용", 1, ""),
        ("601", "급여",         "비용", 1, ""),
        ("602", "상여금",       "비용", 1, ""),
        ("603", "퇴직급여",     "비용", 1, ""),
        ("611", "복리후생비",   "비용", 1, ""),
        ("612", "여비교통비",   "비용", 1, ""),
        ("613", "접대비",       "비용", 1, ""),
        ("614", "통신비",       "비용", 1, ""),
        ("615", "수도광열비",   "비용", 1, ""),
        ("616", "세금과공과",   "비용", 1, ""),
        ("617", "감가상각비",   "비용", 1, ""),
        ("618", "임차료",       "비용", 1, ""),
        ("619", "보험료",       "비용", 1, ""),
        ("620", "수선비",       "비용", 1, ""),
        ("621", "소모품비",     "비용", 1, ""),
        ("630", "지급수수료",   "비용", 1, ""),
        ("640", "광고선전비",   "비용", 1, ""),
        ("650", "운반비",       "비용", 1, ""),
        ("660", "교육훈련비",   "비용", 1, ""),
        ("670", "도서인쇄비",   "비용", 1, ""),
        ("680", "차량유지비",   "비용", 1, ""),
        ("690", "잡손실",       "비용", 1, ""),
        ("801", "급여(제조)",   "비용", 1, ""),
        ("802", "재료비",       "비용", 1, ""),
        ("803", "제조경비",     "비용", 1, ""),
    ]

    for code, name, category, is_debit, parent_code in accounts:
        existing = conn.execute("SELECT id FROM accounts WHERE code=?", (code,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO accounts (code, name, category, is_debit, parent_code) VALUES (?,?,?,?,?)",
                (code, name, category, is_debit, parent_code),
            )

    for code, name, location in [("WH-01", "본사 창고", "서울"), ("WH-02", "물류 창고", "인천")]:
        existing = conn.execute("SELECT id FROM warehouses WHERE code=?", (code,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO warehouses (code, name, location) VALUES (?,?,?)",
                (code, name, location),
            )

    sample_items = [
        ("ITM-001", "A4용지",         "consumable", "BOX", 25000,  10, "사무용품"),
        ("ITM-002", "모니터 24인치",   "material",   "EA",  280000, 3,  "전자기기"),
        ("ITM-003", "복합기 토너",     "consumable", "EA",  85000,  5,  "사무용품"),
        ("ITM-004", "조립부품 B-300",  "material",   "EA",  12000,  50, "부품"),
        ("ITM-005", "완제품 P-200",    "product",    "EA",  95000,  10, "완제품"),
    ]
    for code, name, itype, unit, price, safety, cat in sample_items:
        existing = conn.execute("SELECT id FROM items WHERE item_code=?", (code,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO items (item_code, item_name, item_type, unit, unit_price, safety_stock, category) VALUES (?,?,?,?,?,?,?)",
                (code, name, itype, unit, price, safety, cat),
            )

    conn.commit()

    items = {r["item_code"]: r["id"] for r in conn.execute("SELECT id, item_code FROM items").fetchall()}
    whs = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM warehouses").fetchall()}
    stock_data = [
        ("ITM-001", "WH-01", 45),
        ("ITM-002", "WH-01", 8),
        ("ITM-003", "WH-01", 12),
        ("ITM-004", "WH-02", 200),
        ("ITM-005", "WH-02", 35),
        ("ITM-001", "WH-02", 20),
    ]
    for item_code, wh_code, qty in stock_data:
        iid = items.get(item_code)
        wid = whs.get(wh_code)
        if iid and wid:
            existing = conn.execute(
                "SELECT id FROM stock WHERE item_id=? AND warehouse_id=?", (iid, wid)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,?)",
                    (iid, wid, qty),
                )

    sample_partners = [
        ("P-001", "한국부품",       "123-45-67890", "이사장", "제조업", "부품", "경기도 안산시", "031-123-4567"),
        ("P-002", "세원테크",       "234-56-78901", "김대표", "제조업", "전자", "서울 강남구",   "02-987-6543"),
        ("P-003", "동양물산",       "345-67-89012", "박대표", "도매업", "잡화", "인천 남동구",   "032-456-7890"),
        ("P-004", "우리사무용품",   "456-78-90123", "최대표", "소매업", "사무", "서울 종로구",   "02-111-2222"),
    ]
    for code, name, biz_no, rep, btype, bitem, addr, phone in sample_partners:
        existing = conn.execute("SELECT id FROM partners WHERE code=?", (code,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO partners (code, name, biz_no, representative, biz_type, biz_item, address, phone) VALUES (?,?,?,?,?,?,?,?)",
                (code, name, biz_no, rep, btype, bitem, addr, phone),
            )

    conn.commit()
