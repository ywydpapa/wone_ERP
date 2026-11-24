import os
import sys
import pymysql
import pymysql.cursors

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "wone_erp")


def get_raw_connection(create_db_if_missing=True):
    try:
        return pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
    except pymysql.err.OperationalError as e:
        if e.args[0] == 1049 and create_db_if_missing:  # Unknown database
            print(f"Database '{DB_NAME}' does not exist. Creating...")
            temp_conn = pymysql.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                charset="utf8mb4",
                autocommit=True,
            )
            with temp_conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE `{DB_NAME}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            temp_conn.close()
            return pymysql.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                charset="utf8mb4",
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )
        raise


def init_mariadb_schema():
    """schema_mariadb.sql을 실행하여 MariaDB 초기 스키마 및 버전을 설정"""
    schema_path = os.path.join(ROOT_DIR, "schema_mariadb.sql")
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    conn = get_raw_connection()
    with conn.cursor() as cur:
        # 이미 테이블이 있는지 확인
        cur.execute("SHOW TABLES LIKE 'users'")
        if cur.fetchone():
            print("MariaDB schema already initialized.")
            conn.close()
            return

        print("Executing schema_mariadb.sql...")
        with open(schema_path, "r", encoding="utf-8") as f:
            sql_content = f.read()

        # 세미콜론 기준으로 문장 분리하여 실행
        statements = sql_content.split(";")
        for stmt in statements:
            stmt = stmt.strip()
            if stmt:
                try:
                    cur.execute(stmt)
                except Exception as e:
                    print(f"\n[오류 발생 SQL]\n{stmt}\n")
                    raise

        # schema_versions 테이블 생성 및 120 버전 등록
        cur.execute("""
            CREATE TABLE IF NOT EXISTS `schema_versions` (
                `version` INT PRIMARY KEY,
                `applied_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)

        cur.execute("SELECT MAX(version) AS max_v FROM schema_versions")
        row = cur.fetchone()
        if not row or row["max_v"] is None:
            cur.execute("INSERT INTO schema_versions (version) VALUES (120)")
            print("Registered baseline migration version: 120")

    conn.close()
    print("MariaDB initialization completed successfully.")


if __name__ == "__main__":
    init_mariadb_schema()
