import pytest
import sqlite3

from core.db import adapt_sql, RowDict, SQLiteConnectionWrapper

def test_adapt_sql_placeholders():
    q = "SELECT * FROM users WHERE username=? AND role=?"
    assert adapt_sql(q) == "SELECT * FROM users WHERE username=%s AND role=%s"

def test_adapt_sql_preserves_literals():
    q = "SELECT * FROM logs WHERE message='Why?' AND user_id=?"
    assert adapt_sql(q) == "SELECT * FROM logs WHERE message='Why?' AND user_id=%s"

def test_adapt_sql_null_safe_is():
    q = "SELECT * FROM employees WHERE id=? AND company_id IS ?"
    assert adapt_sql(q) == "SELECT * FROM employees WHERE id=%s AND company_id <=> %s"

def test_adapt_sql_insert_ignore():
    q = "INSERT OR IGNORE INTO user_perms (user_id, group_key) VALUES (?, ?)"
    assert adapt_sql(q) == "INSERT IGNORE INTO user_perms (user_id, group_key) VALUES (%s, %s)"

def test_adapt_sql_date_functions():
    q1 = "SELECT strftime('%Y-%m', a.work_date) FROM attendance a WHERE id=?"
    assert adapt_sql(q1) == "SELECT DATE_FORMAT(a.work_date, '%Y-%m') FROM attendance a WHERE id=%s"

    q2 = "SELECT pay_year=CAST(strftime('%Y',date('now','localtime')) AS INTEGER)"
    assert adapt_sql(q2) == "SELECT pay_year=YEAR(CURDATE())"

def test_row_dict_compatibility():
    data = {"id": 101, "username": "admin", "role": "platform_staff"}
    row = RowDict(data)

    # 1. 키 접근
    assert row["id"] == 101
    assert row["username"] == "admin"

    # 2. 숫자 인덱스 접근 (fetchone()[0] 호환)
    assert row[0] == 101
    assert row[1] == "admin"
    assert row[2] == "platform_staff"

    # 3. dict 변환
    d = dict(row)
    assert d == data
    assert isinstance(d, dict)

def test_sqlite_transaction_context_manager():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE test_tbl (id INTEGER PRIMARY KEY, val TEXT)")

    wrapped = SQLiteConnectionWrapper(conn)

    # 정상 블록 탈출 시 커밋
    with wrapped:
        wrapped.execute("INSERT INTO test_tbl (val) VALUES ('success')")

    cur = conn.execute("SELECT COUNT(*) FROM test_tbl")
    assert cur.fetchone()[0] == 1

    # 예외 발생 시 롤백
    try:
        with SQLiteConnectionWrapper(conn) as w_conn:
            w_conn.execute("INSERT INTO test_tbl (val) VALUES ('fail')")
            raise ValueError("강제 에러")
    except ValueError:
        pass

    cur = conn.execute("SELECT COUNT(*) FROM test_tbl WHERE val='fail'")
    assert cur.fetchone()[0] == 0

    conn.close()
