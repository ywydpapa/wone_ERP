import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import backup
from core.db import DB_PATH

BACKUP_DIR = os.path.join(os.path.dirname(DB_PATH), "var", "backups")

if __name__ == "__main__":
    path = backup.run(DB_PATH, BACKUP_DIR)
    print(path)
