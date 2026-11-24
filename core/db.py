import logging
import os
import re
import sqlite3
import threading
from queue import Queue, Empty

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

log = logging.getLogger("wone.db")

DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").lower()
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "erp.db")

# MariaDB 환경변수
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "wone_erp")
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))


class RowDict(dict):
    """
    sqlite3.Row 호환 딕셔너리:
    - row['column_name'] (딕셔너리 키 접근)
    - dict(row) (딕셔너리 변환)
    - row[0] (숫자 인덱스 접근 호환 - fetchone()[0] 등 지원)
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._keys = list(self.keys())

    def __getitem__(self, item):
        if isinstance(item, int):
            return self[self._keys[item]]
        return super().__getitem__(item)


def adapt_sql(sql: str) -> str:
    """
    SQLite 형식의 쿼리를 MariaDB/MySQL 호환 문법으로 안전하게 변환:
    1. INSERT OR IGNORE INTO -> INSERT IGNORE INTO
    2. INSERT OR REPLACE INTO -> REPLACE INTO
    3. IS ? -> <=> %s (MariaDB NULL-Safe 동등 비교)
    4. 문자열 리터럴 외부의 ? -> %s
    """
    # 1. INSERT OR IGNORE 치환
    sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT IGNORE INTO", sql, flags=re.IGNORECASE)
    # 2. INSERT OR REPLACE 치환
    sql = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "REPLACE INTO", sql, flags=re.IGNORECASE)
    # 3. IS ? 치환 (MariaDB NULL-safe equal)
    sql = re.sub(r"\bIS\s+\?", "<=> %s", sql, flags=re.IGNORECASE)

    # 4. SQLite 날짜/시간 함수를 MariaDB 함수로 변환
    sql = re.sub(r"date\(\s*'now'\s*,\s*'localtime'\s*\)", "CURDATE()", sql, flags=re.IGNORECASE)
    sql = re.sub(r"datetime\(\s*'now'\s*,\s*'localtime'\s*\)", "NOW()", sql, flags=re.IGNORECASE)
    sql = re.sub(r"CAST\s*\(\s*strftime\(\s*['\"]%Y['\"]\s*,\s*CURDATE\(\)\s*\)\s*AS\s+INTEGER\s*\)", "YEAR(CURDATE())", sql, flags=re.IGNORECASE)
    sql = re.sub(r"CAST\s*\(\s*strftime\(\s*['\"]%m['\"]\s*,\s*CURDATE\(\)\s*\)\s*AS\s+INTEGER\s*\)", "MONTH(CURDATE())", sql, flags=re.IGNORECASE)
    sql = re.sub(r"strftime\(\s*['\"]%%Y-%%m['\"]\s*,\s*([a-zA-Z0-9_\.]+)\s*\)", r"DATE_FORMAT(\1, '%Y-%m')", sql, flags=re.IGNORECASE)
    sql = re.sub(r"strftime\(\s*['\"](%[^'\"]+)['\"]\s*,\s*([a-zA-Z0-9_\.]+)\s*\)", r"DATE_FORMAT(\2, '\1')", sql, flags=re.IGNORECASE)

    # 5. 문자열 리터럴 내부의 물음표는 건드리지 않고 외부의 ? 만 %s로 치환
    tokens = []
    in_single = False
    in_double = False
    escape = False

    for ch in sql:
        if escape:
            tokens.append(ch)
            escape = False
            continue
        if ch == "\\":
            tokens.append(ch)
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            tokens.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            tokens.append(ch)
        elif ch == "?" and not in_single and not in_double:
            tokens.append("%s")
        else:
            tokens.append(ch)

    return "".join(tokens)


class MariaDBCursorWrapper:
    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchone(self):
        row = self._cur.fetchone()
        return RowDict(row) if row is not None else None

    def fetchall(self):
        rows = self._cur.fetchall()
        return [RowDict(r) for r in rows]

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size)
        return [RowDict(r) for r in rows]

    def close(self):
        self._cur.close()


class MariaDBConnectionWrapper:
    """
    MariaDB 연결 래퍼:
    - conn.execute(sql, params) 직접 호출 지원
    - 트랜잭션 컨텍스트 매니저 (with conn: 자동 commit / rollback)
    - 커넥션 풀 반환 관리
    """
    def __init__(self, raw_conn, pool=None):
        self._conn = raw_conn
        self._pool = pool
        self._closed = False

    def execute(self, sql, params=None):
        adapted = adapt_sql(sql)
        cur = self._conn.cursor()
        if params is not None:
            if isinstance(params, (list, tuple)):
                cur.execute(adapted, params)
            elif isinstance(params, dict):
                cur.execute(adapted, params)
            else:
                cur.execute(adapted, (params,))
        else:
            cur.execute(adapted)
        return MariaDBCursorWrapper(cur)

    def executemany(self, sql, params_list):
        adapted = adapt_sql(sql)
        cur = self._conn.cursor()
        cur.executemany(adapted, params_list)
        return MariaDBCursorWrapper(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._pool is not None:
            self._pool.release(self._conn)
        else:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            try:
                self.rollback()
            except Exception:
                pass
        else:
            try:
                self.commit()
            except Exception:
                pass


class SimpleMariaDBPool:
    """스레드 안전한 경량 MariaDB 커넥션 풀"""
    def __init__(self, max_connections=10):
        self.max_connections = max_connections
        self._pool = Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._created = 0

    def _create_raw_conn(self):
        import pymysql
        import pymysql.cursors
        return pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
        )

    def get_connection(self):
        conn = None
        try:
            conn = self._pool.get_nowait()
            conn.ping(reconnect=True)
        except (Empty, Exception):
            with self._lock:
                if self._created < self.max_connections:
                    conn = self._create_raw_conn()
                    self._created += 1
                else:
                    conn = self._pool.get(timeout=10)
                    conn.ping(reconnect=True)
        return MariaDBConnectionWrapper(conn, pool=self)

    def release(self, raw_conn):
        try:
            raw_conn.rollback()
            self._pool.put_nowait(raw_conn)
        except Exception:
            try:
                raw_conn.close()
            except Exception:
                pass
            with self._lock:
                self._created = max(0, self._created - 1)


_mariadb_pool = None
_pool_lock = threading.Lock()


def get_mariadb_pool():
    global _mariadb_pool
    if _mariadb_pool is None:
        with _pool_lock:
            if _mariadb_pool is None:
                _mariadb_pool = SimpleMariaDBPool(max_connections=DB_POOL_SIZE)
    return _mariadb_pool


class SQLiteConnectionWrapper:
    """SQLite 커넥션 래퍼 (트랜잭션 컨텍스트 매니저 with conn: 지원)"""
    def __init__(self, raw_conn):
        self._conn = raw_conn
        self._closed = False

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._conn.executemany(*args, **kwargs)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if not self._closed:
            self._closed = True
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            try:
                self.rollback()
            except Exception:
                pass
        else:
            try:
                self.commit()
            except Exception:
                pass


def get_connection():
    """설정된 엔진(DB_ENGINE)에 따라 DB 커넥션을 반환"""
    engine = os.getenv("DB_ENGINE", DB_ENGINE).lower()
    if engine in ("mariadb", "mysql"):
        pool = get_mariadb_pool()
        return pool.get_connection()
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return SQLiteConnectionWrapper(conn)


def get_sqlite():
    """기존 코드와의 100% 호환성을 위한 alias"""
    return get_connection()


STATUS_META = {
    "urgent":      ("긴급",    "status-urgent"),
    "progress":    ("진행중",  "status-progress"),
    "in_progress": ("진행중",  "status-progress"),
    "wait":        ("대기",    "status-wait"),
    "pending":     ("대기",    "status-wait"),
    "draft":       ("임시저장", "status-draft"),
    "withdrawn":   ("철회",    "status-withdrawn"),
    "done":        ("완료",    "status-done"),
    "approved":    ("완료",    "status-done"),
    "resolved":    ("완료",    "status-done"),
    "rejected":    ("반려",    "status-urgent"),
}


def with_status_meta(rows):
    out = []
    for r in rows:
        d = dict(r)
        label, cls = STATUS_META.get(d.get("status", ""), (d.get("status", ""), "status-progress"))
        d["status_label"], d["status_class"] = label, cls
        out.append(d)
    return out
