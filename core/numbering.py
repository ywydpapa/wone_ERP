import sqlite3


def next_no(conn, prefix, table, column, seq_hint=None):
    if seq_hint is None:
        row = conn.execute(
            f"SELECT {column} FROM {table} WHERE {column} LIKE ? ORDER BY id DESC LIMIT 1",
            (f"{prefix}%",),
        ).fetchone()
        seq_hint = int(row[column].split("-")[-1]) + 1 if row else 1
    return f"{prefix}{seq_hint:04d}", seq_hint


def insert_no(conn, table, col, prefix, vals):
    number, seq = next_no(conn, prefix, table, col)
    cols = ", ".join(vals.keys())
    phs = ", ".join("?" * len(vals))
    while True:
        try:
            cur = conn.execute(
                f"INSERT INTO {table} ({col}, {cols}) VALUES (?, {phs})",
                (number, *vals.values()),
            )
            return cur.lastrowid, number
        except sqlite3.IntegrityError:
            seq += 1
            number, _ = next_no(conn, prefix, table, col, seq)
