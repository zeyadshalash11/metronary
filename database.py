import sqlite3

def create_orders_table():
    conn = sqlite3.connect('store.db') 
    conn.execute("PRAGMA foreign_keys = ON")

    conn.row_factory = sqlite3.Row  # Enables name-based access
    c = conn.cursor()

    # Create the orders table if it doesn't exist
    # This schema is aligned with what app.py expects and needs for Paymob
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            building TEXT NOT NULL,
            floor TEXT NOT NULL,
            apartment TEXT NOT NULL,
            governorate TEXT NOT NULL,
            email TEXT,
            payment TEXT NOT NULL, -- e.g., 'Cash on Delivery', 'card', 'mobile_wallet'
            shipping REAL NOT NULL,
            total_price REAL NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL, -- e.g., 'Pending Cash Delivery', 'Pending Paymob', 'Paid', 'Failed', etc.
            paymob_transaction_id TEXT, -- To store Paymob's transaction ID
            paymob_order_id TEXT -- To store Paymob's order ID (Paymob's internal order ID)
        )
    ''')
    conn.commit()

    # --- Add new columns if they don't already exist (for existing databases) ---
    # This handles cases where you already have a 'store.db' but it lacks these columns.
    c.execute("PRAGMA table_info(orders);")
    columns = [col[1] for col in c.fetchall()]

    if 'paymob_transaction_id' not in columns:
        print("Adding column 'paymob_transaction_id' to 'orders' table...")
        c.execute('ALTER TABLE orders ADD COLUMN paymob_transaction_id TEXT;')
        conn.commit()
        print("Column 'paymob_transaction_id' added successfully.")
    else:
        print("Column 'paymob_transaction_id' already exists.")

    if 'paymob_order_id' not in columns:
        print("Adding column 'paymob_order_id' to 'orders' table...")
        c.execute('ALTER TABLE orders ADD COLUMN paymob_order_id TEXT;')
        conn.commit()
        print("Column 'paymob_order_id' added successfully.")
    else:
        print("Column 'paymob_order_id' already exists.")

    conn.close()

# Add this NEW function to your database.py file:
def create_order_items_table():
    conn = sqlite3.connect('store.db')
    conn.execute("PRAGMA foreign_keys = ON")

    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            size TEXT,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE
            FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()

def create_products_table():
        conn = sqlite3.connect('store.db')
        conn.execute("PRAGMA foreign_keys = ON")

        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                image TEXT, -- CHANGED: Removed NOT NULL constraint
                sizes TEXT,
                description TEXT
            )
        ''')
        conn.commit()
        conn.close()

def create_faqs_table():
    conn = sqlite3.connect('store.db') # Unified to 'store.db'
    conn.execute("PRAGMA foreign_keys = ON")    
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# This part ensures tables are created when database.py is run directly
if __name__ == '__main__':
    print("Running database schema updates...")
    create_orders_table()
    create_products_table()
    create_faqs_table()
    create_order_items_table()
    print("Database schema update complete.")
