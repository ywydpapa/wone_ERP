def up(conn):
    for col in [
        "phone TEXT DEFAULT ''",
        "email TEXT DEFAULT ''",
        "gender TEXT DEFAULT ''",
    ]:
        conn.execute(f"ALTER TABLE employees ADD COLUMN {col}")
