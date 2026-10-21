from core import books


def _partner(db, cid, code, name):
    return db.execute("INSERT INTO partners (code, name, company_id, is_active) VALUES (?,?,?,1)",
                      (code, name, cid)).lastrowid


# 전표 조회

def test_slip_list_sort(db, seed, login):
    a = seed["a"]["company"]
    books.post(db, a, seed["a"]["mgr"], "2026-09-05",
              [{"code": "813", "debit": 11000, "credit": 0}, {"code": "103", "debit": 0, "credit": 11000}],
              "소액전표", "manual")
    books.post(db, a, seed["a"]["mgr"], "2026-09-06",
              [{"code": "813", "debit": 99000, "credit": 0}, {"code": "103", "debit": 0, "credit": 99000}],
              "고액전표", "manual")
    db.commit()

    c = login("a_mgr")
    asc = c.get("/slip_list?sort=amount&dir=asc").text
    desc = c.get("/slip_list?sort=amount&dir=desc").text
    assert asc.index("11,000") < asc.index("99,000")
    assert desc.index("99,000") < desc.index("11,000")
    assert c.get("/slip_list?sort=1;DROP").status_code == 200


# 은행 거래내역

def _acct(db, cid, no="111"):
    return db.execute(
        "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) VALUES (?,'국민은행',?,'운영계좌','103')",
        (cid, no)).lastrowid


def _txn(db, cid, acct, amt_in, counterparty, txn_at="2026-10-01"):
    h = f"{acct}|{txn_at}|{amt_in}|{counterparty}"
    return db.execute(
        """INSERT INTO bank_txns (company_id, bank_account_id, txn_at, memo, counterparty, amt_in, amt_out,
               hash, uploaded_at) VALUES (?,?,?,'','',?,0,?,'2026-10-01')""",
        (cid, acct, txn_at, amt_in, h)).lastrowid


def test_bank_txn_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    acct_a = _acct(db, a, "111")
    acct_b = _acct(db, b, "222")
    _txn(db, a, acct_a, 11000, "거래처A")
    _txn(db, a, acct_a, 99000, "거래처B")
    _txn(db, b, acct_b, 50000, "남의거래처")
    db.commit()

    c = login("a_mgr")
    base = f"/bank-txns?account_id={acct_a}&status="
    asc = c.get(base + "&sort=in&dir=asc").text
    desc = c.get(base + "&sort=in&dir=desc").text
    assert asc.index("11,000") < asc.index("99,000")
    assert desc.index("99,000") < desc.index("11,000")
    assert c.get(base + "&sort=1;DROP").status_code == 200

    r = c.get(base + "&export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "남의거래처" not in r.text


def test_bank_rule_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO txn_rules (company_id, keyword, account_code) VALUES (?,'가나다','813')", (a,))
    db.execute("INSERT INTO txn_rules (company_id, keyword, account_code) VALUES (?,'하파타','813')", (a,))
    db.execute("INSERT INTO txn_rules (company_id, keyword, account_code) VALUES (?,'남의규칙','813')", (b,))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/bank-txns/rules?sort=keyword&dir=asc").text
    desc = c.get("/bank-txns/rules?sort=keyword&dir=desc").text
    assert asc.index("가나다") < asc.index("하파타")
    assert desc.index("하파타") < desc.index("가나다")
    assert c.get("/bank-txns/rules?sort=1;DROP").status_code == 200

    r = c.get("/bank-txns/rules?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "남의규칙" not in r.text


# 수금/지급

def test_settlement_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    pid_a = _partner(db, a, "C1", "가고객")
    pid_b = _partner(db, b, "C2", "남의고객")
    db.execute(
        """INSERT INTO settlements (company_id, kind, settle_date, partner_id, amount, method, account_code, created_at)
           VALUES (?,'수금','2026-10-05',?,11000,'보통예금','110','2026-10-05 10:00:00')""", (a, pid_a))
    db.execute(
        """INSERT INTO settlements (company_id, kind, settle_date, partner_id, amount, method, account_code, created_at)
           VALUES (?,'수금','2026-10-06',?,99000,'보통예금','110','2026-10-06 10:00:00')""", (a, pid_a))
    db.execute(
        """INSERT INTO settlements (company_id, kind, settle_date, partner_id, amount, method, account_code, created_at)
           VALUES (?,'수금','2026-10-06',?,50000,'보통예금','110','2026-10-06 10:00:00')""", (b, pid_b))
    db.commit()

    c = login("a_mgr")
    base = "/settlements?start=2026-10-01&end=2026-10-31"
    asc = c.get(base + "&sort=amount&dir=asc").text
    desc = c.get(base + "&sort=amount&dir=desc").text
    assert asc.index("11,000") < asc.index("99,000")
    assert desc.index("99,000") < desc.index("11,000")
    assert c.get(base + "&sort=1;DROP").status_code == 200

    r = c.get(base + "&export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "남의고객" not in r.text


# CRM 잠재고객

def test_crm_lead_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO crm_leads (company_id, name, status) VALUES (?,'가잠재','new')", (a,))
    db.execute("INSERT INTO crm_leads (company_id, name, status) VALUES (?,'하잠재','new')", (a,))
    db.execute("INSERT INTO crm_leads (company_id, name, status) VALUES (?,'남의잠재','new')", (b,))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/crm/leads?sort=name&dir=asc").text
    desc = c.get("/crm/leads?sort=name&dir=desc").text
    assert asc.index("가잠재") < asc.index("하잠재")
    assert desc.index("하잠재") < desc.index("가잠재")
    assert c.get("/crm/leads?sort=1;DROP").status_code == 200

    r = c.get("/crm/leads?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "남의잠재" not in r.text


# CRM 영업기회

def test_crm_opp_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO crm_opps (company_id, title, amount) VALUES (?,'가기회',11000)", (a,))
    db.execute("INSERT INTO crm_opps (company_id, title, amount) VALUES (?,'나기회',99000)", (a,))
    db.execute("INSERT INTO crm_opps (company_id, title, amount) VALUES (?,'남의기회',50000)", (b,))
    db.commit()

    c = login("a_mgr")
    base = "/crm/opps?view=list"
    asc = c.get(base + "&sort=amount&dir=asc").text
    desc = c.get(base + "&sort=amount&dir=desc").text
    assert asc.index("11,000") < asc.index("99,000")
    assert desc.index("99,000") < desc.index("11,000")
    assert c.get(base + "&sort=1;DROP").status_code == 200

    r = c.get(base + "&export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "남의기회" not in r.text


# CRM 영업활동

def test_crm_activity_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO crm_activities (company_id, kind, act_date, subject) VALUES (?,'call','2026-10-01','가활동')", (a,))
    db.execute("INSERT INTO crm_activities (company_id, kind, act_date, subject) VALUES (?,'call','2026-10-10','하활동')", (a,))
    db.execute("INSERT INTO crm_activities (company_id, kind, act_date, subject) VALUES (?,'call','2026-10-05','남의활동')", (b,))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/crm/activities?sort=date&dir=asc").text
    desc = c.get("/crm/activities?sort=date&dir=desc").text
    assert asc.index("가활동") < asc.index("하활동")
    assert desc.index("하활동") < desc.index("가활동")
    assert c.get("/crm/activities?sort=1;DROP").status_code == 200

    r = c.get("/crm/activities?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "남의활동" not in r.text


# BOM 목록

def test_bom_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    p1 = db.execute("INSERT INTO items (item_code, item_name, item_type, company_id) VALUES ('I1','가제품','product',?)", (a,)).lastrowid
    p2 = db.execute("INSERT INTO items (item_code, item_name, item_type, company_id) VALUES ('I2','하제품','product',?)", (a,)).lastrowid
    p3 = db.execute("INSERT INTO items (item_code, item_name, item_type, company_id) VALUES ('I3','남의제품','product',?)", (b,)).lastrowid
    db.execute("INSERT INTO bom_headers (product_id, company_id) VALUES (?,?)", (p1, a))
    db.execute("INSERT INTO bom_headers (product_id, company_id) VALUES (?,?)", (p2, a))
    db.execute("INSERT INTO bom_headers (product_id, company_id) VALUES (?,?)", (p3, b))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/bom?sort=name&dir=asc").text
    desc = c.get("/bom?sort=name&dir=desc").text
    assert asc.index("가제품") < asc.index("하제품")
    assert desc.index("하제품") < desc.index("가제품")
    assert c.get("/bom?sort=1;DROP").status_code == 200

    r = c.get("/bom?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "남의제품" not in r.text


# 작업지시 목록

def test_wo_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    p1 = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('P1','제품1',?)", (a,)).lastrowid
    p2 = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('P2','제품2',?)", (b,)).lastrowid
    db.execute(
        "INSERT INTO work_orders (wo_number, product_id, planned_qty, company_id) VALUES ('WO-1',?,11,?)", (p1, a))
    db.execute(
        "INSERT INTO work_orders (wo_number, product_id, planned_qty, company_id) VALUES ('WO-2',?,99,?)", (p1, a))
    db.execute(
        "INSERT INTO work_orders (wo_number, product_id, planned_qty, company_id) VALUES ('WO-3',?,50,?)", (p2, b))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/work-orders?sort=plan_qty&dir=asc").text
    desc = c.get("/work-orders?sort=plan_qty&dir=desc").text
    assert asc.index("WO-1") < asc.index("WO-2")
    assert desc.index("WO-2") < desc.index("WO-1")
    assert c.get("/work-orders?sort=1;DROP").status_code == 200

    r = c.get("/work-orders?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "WO-3" not in r.text
