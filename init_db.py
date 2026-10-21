
import os
from dotenv import load_dotenv
from migrate import run_migrations

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "erp.db")


def init_db():
    run_migrations(DB_PATH)


if __name__ == "__main__":
    init_db()
