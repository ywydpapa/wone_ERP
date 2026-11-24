import os
from dotenv import load_dotenv

load_dotenv()

DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").lower()
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "erp.db")


def init_db():
    engine = os.getenv("DB_ENGINE", DB_ENGINE).lower()
    if engine in ("mariadb", "mysql"):
        from migrate_mariadb import init_mariadb_schema
        init_mariadb_schema()
    else:
        from migrate import run_migrations
        run_migrations(DB_PATH)


if __name__ == "__main__":
    init_db()
