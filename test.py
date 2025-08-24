import sqlite3

# Path to your database
DB_PATH = "store.db"

# New columns to ensure exist
COLUMNS = {
    "paymob_order_id": "INTEGER",
    "paymob_merchant_order_id": "VARCHAR(64)",
    "paymob_last_payment_key": "TEXT",
    "paymob_attempts": "INTEGER DEFAULT 0"
}

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table});")
    cols = [row[1] for row in cursor.fetchall()]
    return column in cols

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for col, col_type in COLUMNS.items():
        if not column_exists(cur, "orders", col):
            print(f"Adding column {col}...")
            cur.execute(f"ALTER TABLE orders ADD COLUMN {col} {col_type}")
        else:
            print(f"Column {col} already exists, skipping.")

    conn.commit()
    conn.close()
    print("✅ Database update complete.")

if __name__ == "__main__":
    main()
