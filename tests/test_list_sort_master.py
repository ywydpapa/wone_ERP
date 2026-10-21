MARK = "B-SORT-SECRET"


def test_item_list_sort(db, seed, login):
    a = seed["a"]["company"]
    db.execute("INSERT INTO items (item_code, item_name, company_id, unit_price) VALUES ('I1','볼트',?,5000)", (a,))
    db.execute("INSERT INTO items (item_code, item_name, company_id, unit_price) VALUES ('I2','너트',?,1000)", (a,))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/items?sort=price&dir=asc").text
    desc = c.get("/items?sort=price&dir=desc").text
    assert asc.index("너트") < asc.index("볼트")
    assert desc.index("볼트") < desc.index("너트")
    assert c.get("/items?sort=1;DROP").status_code == 200


def test_item_list_export_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('I1','볼트',?)", (a,))
    db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('I9',?,?)", (MARK, b))
    db.commit()

    r = login("a_mgr").get("/items?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "볼트" in r.text and MARK not in r.text


def test_stock_list_sort(db, seed, login):
    a = seed["a"]["company"]
    i1 = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('I1','볼트',?)", (a,)).lastrowid
    i2 = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('I2','너트',?)", (a,)).lastrowid
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','창고',?)", (a,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,5)", (i1, wh))
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,50)", (i2, wh))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/stock?sort=qty&dir=asc").text
    desc = c.get("/stock?sort=qty&dir=desc").text
    assert asc.index("볼트") < asc.index("너트")
    assert desc.index("너트") < desc.index("볼트")
    assert c.get("/stock?sort=1;DROP").status_code == 200


def test_stock_list_export_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    i1 = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('I1','볼트',?)", (a,)).lastrowid
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','창고',?)", (a,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,5)", (i1, wh))
    i9 = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('I9',?,?)", (MARK, b)).lastrowid
    wh2 = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W2','창고2',?)", (b,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,5)", (i9, wh2))
    db.commit()

    r = login("a_mgr").get("/stock?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "볼트" in r.text and MARK not in r.text


def test_warehouse_list_sort(db, seed, login):
    a = seed["a"]["company"]
    w1 = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','가창고',?)", (a,)).lastrowid
    w2 = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W2','나창고',?)", (a,)).lastrowid
    item = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('I1','볼트',?)", (a,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,100)", (item, w1))
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,1)", (item, w2))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/warehouses?sort=qty&dir=asc").text
    desc = c.get("/warehouses?sort=qty&dir=desc").text
    assert asc.index("나창고") < asc.index("가창고")
    assert desc.index("가창고") < desc.index("나창고")
    assert c.get("/warehouses?sort=1;DROP").status_code == 200


def test_warehouse_list_export_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','가창고',?)", (a,))
    db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W9',?,?)", (MARK, b))
    db.commit()

    r = login("a_mgr").get("/warehouses?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "가창고" in r.text and MARK not in r.text


def test_bank_account_list_sort(db, seed, login):
    a = seed["a"]["company"]
    db.execute("INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) "
               "VALUES (?,'국민은행','111','가계좌','103')", (a,))
    db.execute("INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) "
               "VALUES (?,'신한은행','222','나계좌','103')", (a,))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/bank-accounts?sort=name&dir=asc").text
    desc = c.get("/bank-accounts?sort=name&dir=desc").text
    assert asc.index("가계좌") < asc.index("나계좌")
    assert desc.index("나계좌") < desc.index("가계좌")
    assert c.get("/bank-accounts?sort=1;DROP").status_code == 200


def test_bank_account_list_export_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) "
               "VALUES (?,'국민은행','111-222','가계좌','103')", (a,))
    db.execute("INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) "
               "VALUES (?,'신한은행',?,?,'103')", (b, MARK, MARK))
    db.commit()

    r = login("a_mgr").get("/bank-accounts?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    # 계좌번호 마스킹 없음. 화면 표시 기준
    assert "111-222" in r.text and MARK not in r.text


def test_dept_list_sort(db, seed, login):
    a = seed["a"]["company"]
    db.execute("INSERT INTO depts (company_id, code, name) VALUES (?,'001','가부서')", (a,))
    db.execute("INSERT INTO depts (company_id, code, name) VALUES (?,'002','나부서')", (a,))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/depts?sort=name&dir=asc").text
    desc = c.get("/depts?sort=name&dir=desc").text
    assert asc.index("가부서") < asc.index("나부서")
    assert desc.index("나부서") < desc.index("가부서")
    assert c.get("/depts?sort=1;DROP").status_code == 200


def test_dept_list_export_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO depts (company_id, code, name) VALUES (?,'001','가부서')", (a,))
    db.execute("INSERT INTO depts (company_id, code, name) VALUES (?,'001',?)", (b, MARK))
    db.commit()

    r = login("a_mgr").get("/depts?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "가부서" in r.text and MARK not in r.text


def test_memo_code_list_sort(db, seed, login):
    a = seed["a"]["company"]
    db.execute("INSERT INTO memo_codes (company_id, code, text) VALUES (?,'101','가현금입금')", (a,))
    db.execute("INSERT INTO memo_codes (company_id, code, text) VALUES (?,'102','나현금지급')", (a,))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/memo-codes?sort=text&dir=asc").text
    desc = c.get("/memo-codes?sort=text&dir=desc").text
    assert asc.index("가현금입금") < asc.index("나현금지급")
    assert desc.index("나현금지급") < desc.index("가현금입금")
    assert c.get("/memo-codes?sort=1;DROP").status_code == 200


def test_memo_code_list_export_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO memo_codes (company_id, code, text) VALUES (?,'101','가현금입금')", (a,))
    db.execute("INSERT INTO memo_codes (company_id, code, text) VALUES (?,'101',?)", (b, MARK))
    db.commit()

    r = login("a_mgr").get("/memo-codes?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "가현금입금" in r.text and MARK not in r.text


def test_partner_list_sort(db, seed, login):
    a = seed["a"]["company"]
    db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','가거래처',?)", (a,))
    db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P2','나거래처',?)", (a,))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/partners?sort=name&dir=asc").text
    desc = c.get("/partners?sort=name&dir=desc").text
    assert asc.index("가거래처") < asc.index("나거래처")
    assert desc.index("나거래처") < desc.index("가거래처")
    assert c.get("/partners?sort=1;DROP").status_code == 200
