
def up(conn):
    conn.execute(
        "ALTER TABLE employees ADD COLUMN company_id INTEGER REFERENCES client_companies(id)"
    )
    conn.commit()
