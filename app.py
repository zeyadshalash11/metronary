import os
import random
import requests
import sqlite3
import traceback
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, make_response, flash , g
from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
# Import all table creation functions from database.py
from database import create_orders_table, create_products_table, create_faqs_table
from datetime import datetime

from werkzeug.security import check_password_hash 
from werkzeug.utils import secure_filename 

import hmac
import hashlib
import ssl
import certifi
import json



# --- Configuration for file uploads ---
UPLOAD_FOLDER = 'static/product_images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


app = Flask(__name__)


# WARNING: This line globally disables SSL certificate verification.
# It's generally NOT recommended for production environments as it can expose you to security risks.
# For requests.post calls, we are explicitly using verify=certifi.where() for better security.
ssl._create_default_https_context = ssl._create_unverified_context


load_dotenv()  # Load the default .env file
load_dotenv('.env')  # Load api.env for SendGrid keys

# --- Paymob API Configuration (Loaded from .env) ---
PAYMOB_API_KEY = os.getenv("PAYMOB_API_KEY")
PAYMOB_MERCHANT_ID = os.getenv("PAYMOB_MERCHANT_ID")
PAYMOB_CARD_INTEGRATION_ID = os.getenv("PAYMOB_CARD_INTEGRATION_ID")
PAYMOB_MOBILE_WALLET_INTEGRATION_ID = os.getenv("PAYMOB_MOBILE_WALLET_INTEGRATION_ID")
PAYMOB_HMAC_SECRET = os.getenv("PAYMOB_HMAC_SECRET")
PAYMOB_BASE_URL = "https://accept.paymobsolutions.com/api"
PAYMOB_IFRAME_ID = os.getenv("PAYMOB_IFRAME_ID")

# --- Flask App Configuration ---
# IMPORTANT: Change this to a strong, random secret key for production!
app.secret_key = os.getenv("FLASK_SECRET_KEY")


# Base URL for Paymob API (ensure this is correct for your environment, e.g., production vs staging)
PAYMOB_BASE_URL = "https://accept.paymobsolutions.com/api"

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Database Initialization ---
# Ensure database tables are created when the application starts
# This will also run the ALTER TABLE statements if columns are missing
with app.app_context():
    create_orders_table()
    create_products_table()
    create_faqs_table()

# --- Helper functions ---
def get_product_images(product_folder):
    allowed_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')
    folder_path = os.path.join('static', product_folder)
    try:
        return sorted([
            img for img in os.listdir(folder_path)
            if img.lower().endswith(allowed_extensions)
        ])
    except FileNotFoundError:
        return []
    
def load_products():
    conn = sqlite3.connect('store.db')
    c = conn.cursor()
    c.execute('SELECT id, name, price, image, sizes, description FROM products')
    rows = c.fetchall()
    products = []
    for row in rows:
        product_data = {
            'id': row[0],
            'name': row[1],
            'price': row[2],
            'raw_image_string': row[3], # Store the raw comma-separated string from DB
            'sizes': row[4].split(',') if row[4] else [],
            'description': row[5],
        }

        # **UPDATED:** Ensure 'images' list always exists and 'image' (singular) points to the first image or placeholder
        if product_data['raw_image_string']:
            product_data['images'] = [path.strip() for path in product_data['raw_image_string'].split(',') if path.strip()]
        else:
            product_data['images'] = [] # Ensure 'images' key always exists as an empty list if no images

        # Set 'image' (singular) to the first image path or a placeholder URL
        product_data['image'] = product_data['images'][0] if product_data['images'] else url_for('static', filename='placeholder.png')
        
        products.append(product_data)
        
    conn.close()
    return products
def get_cart_totals():
    """Helper function to calculate cart totals for AJAX responses."""
    cart_data = session.get('cart', {})
    products = load_products() # Re-load products to get current prices

    calculated_subtotal = 0
    calculated_item_count = 0
    
    # Use cleaned cart logic here to ensure accurate calculation
    temp_cleaned_cart = {}
    for key, value in cart_data.items():
        if isinstance(value, int): # Handle old cart format if present
            try:
                pid_str, size = key.split('_')
                value = { 'product_id': int(pid_str), 'size': size, 'quantity': value }
            except ValueError:
                value = { 'product_id': int(key), 'size': 'Unknown', 'quantity': value }
        
        pid = value.get('product_id') 
        quantity = value.get('quantity')
        if pid is not None and quantity is not None:
            new_key = f"{pid}_{value.get('size', 'Unknown')}"
            if new_key in temp_cleaned_cart:
                temp_cleaned_cart[new_key]['quantity'] += quantity
            else:
                temp_cleaned_cart[new_key] = { 'product_id': pid, 'size': value.get('size', 'Unknown'), 'quantity': quantity }

    for key, entry in temp_cleaned_cart.items():
        pid = entry.get('product_id')
        quantity = entry.get('quantity')
        product = next((p for p in products if p['id'] == pid), None)
        if product:
            calculated_subtotal += product['price'] * quantity
            calculated_item_count += quantity
        else:
            # If product not found, clean it from the session cart
            if key in session['cart']:
                session['cart'].pop(key, None)
                session.modified = True

    # Shipping calculation (adjust this based on your actual logic, e.g., from session['user_governorate'])
    # For a simple cart, let's use a default or flat rate.
    # If you have detailed shipping in your checkout process, it's fine to keep it simple here.
    shipping = 0 # Set to a default or flat rate for the cart view
    calculated_total = calculated_subtotal + shipping

    return {
        "subtotal": calculated_subtotal,
        "item_count": calculated_item_count,
        "shipping": shipping,
        "total": calculated_total
    }

DATABASE = 'store.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row # This allows accessing columns by name
    return db



def send_order_email(to, subject, html_content):
    try:
        message = Mail(
            from_email='metronary@outlook.com',
            to_emails=to,
            subject=subject,
            html_content=html_content
        )
        sg = SendGridAPIClient(os.environ.get("SENDGRID_API_KEY"))
        response = sg.send(message)
        print(f"✅ Email sent to {to}. Status: {response.status_code}, Body: {response.body}")
    except Exception as e:
        print(f"❌ Email error: {e}")


# --- ROUTES ---

@app.route('/')
def home():
    """
    Renders the main home page.
    """
    try:
        # ✅ Log visitor IP
        ip = request.remote_addr
        today = datetime.now().strftime('%Y-%m-%d')

        conn = sqlite3.connect('store.db')
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS visitors (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, date TEXT)')
        c.execute('SELECT 1 FROM visitors WHERE ip = ? AND date = ?', (ip, today))
        if not c.fetchone():
            c.execute('INSERT INTO visitors (ip, date) VALUES (?, ?)', (ip, today))
            conn.commit()
        conn.close()

        # ✅ Load products
        # The load_products() function now correctly returns products with an 'images' key (a list of paths)
        products = load_products()
        # REMOVED: product['images'] = get_product_images(product['image']) - This line is no longer needed and causes the error

        return render_template('home.html', products=products) # Correctly render home.html

    except Exception as e:
        print(f"❌ Error in home(): {e}")
        return "<h1 style='color:red;'>Something went wrong. Please try again later.</h1>"

@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    size = request.form.get('size')
    
    try:
        quantity = int(request.form.get('quantity', 1))
        if quantity <= 0:
            return jsonify({"success": False, "message": "Quantity must be positive."}), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid quantity provided."}), 400

    if not size:
        return jsonify({"success": False, "message": "Product size is required."}), 400

    if 'cart' not in session:
        session['cart'] = {}

    cart_key = f"{product_id}_{size}"

    if cart_key in session['cart']:
        session['cart'][cart_key]['quantity'] += quantity
    else:
        session['cart'][cart_key] = {
            'product_id': product_id,
            'size': size,
            'quantity': quantity
        }
    session.modified = True
    flash("Item added to cart!", "success") # **ADDED: Flash message for consistent feedback**
    return jsonify({"success": True, "message": "Item added to cart!"})

@app.route('/cart', methods=['GET']) # Or whatever route leads to your cart
def view_cart(): # <--- This is the function name from your traceback
    cart_data = session.get('cart', {})
    products = load_products()
    cart_items = []

    # Clean and consolidate cart data (same logic as before)
    cleaned_cart = {}
    for key, value in cart_data.items():
        if isinstance(value, int):
            try:
                pid_str, size = key.split('_')
                value = {
                    'product_id': int(pid_str),
                    'size': size,
                    'quantity': value
                }
            except ValueError:
                value = {
                    'product_id': int(key),
                    'size': 'Unknown',
                    'quantity': value
                }
        
        pid = value.get('product_id') 
        size = value.get('size', 'Unknown')
        quantity = value.get('quantity')

        if pid is None or quantity is None:
            print(f"Skipping malformed cart entry: {key} -> {value}")
            continue

        new_key = f"{pid}_{size}"

        if new_key in cleaned_cart:
            cleaned_cart[new_key]['quantity'] += quantity
        else:
            cleaned_cart[new_key] = {
                'product_id': pid,
                'size': size,
                'quantity': quantity
            }
    
    session['cart'] = cleaned_cart
    session.modified = True
    cart_data = cleaned_cart

    for key, entry in cart_data.items():
        pid = entry.get('product_id')
        size = entry.get('size')
        quantity = entry.get('quantity')

        product = next((p for p in products if p['id'] == pid), None)
        if product:
            item = product.copy()
            item['quantity'] = quantity
            item['size'] = size
            item['cart_key'] = key
            item['product_id'] = pid
            cart_items.append(item)
        else:
            print(f"Product ID {pid} not found in database for cart item {key}. Removing from session cart.")
            session['cart'].pop(key, None)
            session.modified = True
            flash(f"A product in your cart (ID: {pid}) was not found and has been removed.", "warning")

    # Calculate totals
    subtotal = sum(item['price'] * item['quantity'] for item in cart_items)
    item_count = sum(item['quantity'] for item in cart_items)
    
    # Define shipping (as per previous instructions, you can make this dynamic if needed)
    shipping = 0 # Default shipping value for the cart view
                  # You can implement your governorate-based logic here if desired,
                  # but for now, 0 will prevent the error.
    
    total = subtotal + shipping

    return render_template('cart.html',
                           cart_items=cart_items,
                           subtotal=subtotal,
                           item_count=item_count,
                           shipping=shipping, # <--- THIS LINE IS CRUCIAL
                           total=total)      # <--- THIS LINE IS CRUCIAL

@app.route('/update_cart', methods=['POST'])
def update_cart():
    product_id = int(request.form.get('product_id'))
    size = request.form.get('size')
    quantity = int(request.form.get('quantity'))

    cart_key = f"{product_id}_{size}"

    if 'cart' in session and cart_key in session['cart']:
        if quantity > 0:
            session['cart'][cart_key]['quantity'] = quantity
        else:
            del session['cart'][cart_key]
        session.modified = True
        return jsonify({"success": True, "message": "Cart updated."})
    return jsonify({"success": False, "message": "Item not found in cart."}), 404

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    cart_key = request.form.get('cart_key')

    if not cart_key:
        return jsonify({"success": False, "message": "Invalid request"}), 400

    if 'cart' not in session or cart_key not in session['cart']:
        return jsonify({"success": False, "message": "Item not found in cart"}), 404

    session['cart'].pop(cart_key, None)
    session.modified = True
    flash("Item removed from cart.", "info")
    
    totals = get_cart_totals() # Recalculate totals after removal

    return jsonify({
        "success": True,
        "message": "Item removed from cart.",
        "removed_cart_key": cart_key,
        "totals": totals,
        "cart_empty": not session['cart'] # Indicate if cart is now empty
    })


@app.route('/cart', methods=['GET'])
def cart():
    cart_data = session.get('cart', {})
    products = load_products()
    cart_items = []

    # Clean and consolidate cart data (same logic as in checkout)
    cleaned_cart = {}
    for key, value in cart_data.items():
        if isinstance(value, int): # Handle old cart format
            try:
                pid_str, size = key.split('_')
                value = {
                    'product_id': int(pid_str),
                    'size': size,
                    'quantity': value
                }
            except ValueError:
                value = {
                    'product_id': int(key),
                    'size': 'Unknown',
                    'quantity': value
                }
        
        pid = value.get('product_id') 
        size = value.get('size', 'Unknown')
        quantity = value.get('quantity')

        if pid is None or quantity is None:
            print(f"Skipping malformed cart entry: {key} -> {value}")
            continue

        new_key = f"{pid}_{size}"

        if new_key in cleaned_cart:
            cleaned_cart[new_key]['quantity'] += quantity
        else:
            cleaned_cart[new_key] = {
                'product_id': pid,
                'size': size,
                'quantity': quantity
            }
    
    session['cart'] = cleaned_cart # Update session with cleaned cart
    session.modified = True
    cart_data = cleaned_cart # Use cleaned data for rendering

    # Populate cart_items with product details
    for key, entry in cart_data.items():
        pid = entry.get('product_id')
        size = entry.get('size')
        quantity = entry.get('quantity')

        product = next((p for p in products if p['id'] == pid), None)
        if product:
            item = product.copy()
            item['quantity'] = quantity
            item['size'] = size
            item['cart_key'] = key # Important for AJAX actions
            item['product_id'] = pid # Important for linking to product
            cart_items.append(item)
        else:
            # Handle cases where product in cart is no longer in DB
            print(f"Product ID {pid} not found in database for cart item {key}. Removing from session cart.")
            session['cart'].pop(key, None)
            session.modified = True
            flash(f"A product in your cart (ID: {pid}) was not found and has been removed.", "warning")

    # Calculate totals
    subtotal = sum(item['price'] * item['quantity'] for item in cart_items)
    item_count = sum(item['quantity'] for item in cart_items)
    
    # Placeholder for shipping (adjust based on your actual shipping logic)
    # If shipping depends on user's address/governorate, you'd fetch that from session or DB here.
    shipping = 0 # Assuming shipping is calculated later in checkout or is flat.
                  # For now, let's keep it simple. If you have governorate logic, move it from checkout() here.
    
    total = subtotal + shipping

    return render_template('cart.html',
                           cart_items=cart_items,
                           subtotal=subtotal,
                           item_count=item_count,
                           shipping=shipping, # Pass shipping to template
                           total=total)

@app.route('/checkout', methods=['GET'])
def checkout():
    """
    Handles GET requests to display the checkout page.
    It prepares cart data and pre-fills user information from session/DB.
    """
    cart_data = session.get('cart', {})
    if not cart_data:
        flash("Your cart is empty. Please add items before checking out.", "info")
        return redirect(url_for('home'))

    products = load_products()
    cart_items = []

    cleaned_cart = {}
    for key, value in cart_data.items():
        if isinstance(value, int):
            try:
                pid_str, size = key.split('_')
                value = {
                    'product_id': int(pid_str),
                    'size': size,
                    'quantity': value
                }
            except ValueError:
                value = {
                    'product_id': int(key),
                    'size': 'Unknown',
                    'quantity': value
                }
        
        pid = value.get('product_id') 
        size = value.get('size', 'Unknown')
        quantity = value.get('quantity')

        if pid is None or quantity is None:
            print(f"Skipping malformed cart entry: {key} -> {value}")
            continue

        new_key = f"{pid}_{size}"

        if new_key in cleaned_cart:
            cleaned_cart[new_key]['quantity'] += quantity
        else:
            cleaned_cart[new_key] = {
                'product_id': pid,
                'size': size,
                'quantity': quantity
            }
    
    session['cart'] = cleaned_cart
    session.modified = True
    cart_data = cleaned_cart

    for key, entry in cart_data.items():
        pid = entry.get('product_id')
        size = entry.get('size')
        quantity = entry.get('quantity')

        product = next((p for p in products if p['id'] == pid), None)
        if product:
            item = product.copy() # item now contains 'image' and 'images' due to updated load_products
            item['quantity'] = quantity
            item['size'] = size
            item['cart_key'] = key
            item['product_id'] = pid

            # **REMOVED:** The line that was causing the KeyError or IndexError.
            # item['image'] is already set correctly by load_products()
            # item['image'] = item['images'][0] if item['images'] else '' # This line is removed

            cart_items.append(item)
        else:
            print(f"Product ID {pid} not found in database for cart item {key}. Removing from cart.")
            # Use 'key' to remove from session directly as it's the current active key
            session['cart'].pop(key, None)
            session.modified = True
            flash(f"A product in your cart (ID: {pid}) was not found and has been removed.", "warning")

    user_email = session.get('user_email', '')
    user_name = session.get('user_name', '')
    user_phone = session.get('user_phone', '')
    user_address = session.get('user_address', '')
    user_building = session.get('user_building', '')
    user_floor = session.get('user_floor', '')
    user_apartment = session.get('user_apartment', '')
    user_governorate = session.get('user_governorate', 'Other')

    if user_email and not (user_name and user_phone and user_address):
        with sqlite3.connect('store.db') as conn:
            c = conn.cursor()
            c.execute('''SELECT name, phone, address, building, floor, apartment, governorate FROM orders WHERE email = ? ORDER BY created_at DESC LIMIT 1''', (user_email,))
            row = c.fetchone()
        if row:
            user_name, user_phone, user_address, user_building, user_floor, user_apartment, user_governorate_from_db = row
            session['user_name'] = user_name
            session['user_phone'] = user_phone
            session['user_address'] = user_address
            session['user_building'] = user_building
            session['user_floor'] = user_floor
            session['user_apartment'] = user_apartment
            session['user_governorate'] = user_governorate_from_db
            session.modified = True
            user_governorate = user_governorate_from_db

    governorate_for_calc = user_governorate.strip().lower()

    subtotal = sum(item['price'] * item['quantity'] for item in cart_items)
    item_count = sum(item['quantity'] for item in cart_items)
    shipping = 70 if governorate_for_calc == 'cairo' else 120
    total = subtotal + shipping

    return render_template('checkout.html',
                            cart_items=cart_items,
                            subtotal=subtotal,
                            item_count=item_count,
                            shipping=shipping,
                            total=total,
                            user_email=user_email,
                            user_name=user_name,
                            user_phone=user_phone,
                            user_address=user_address,
                            user_building=user_building,
                            user_floor=user_floor,
                            user_apartment=user_apartment,
                            user_governorate=user_governorate)

@app.route('/create_payment', methods=['POST'])
def create_payment():
    print(f"DEBUG: Cart session at start of create_payment: {session.get('cart')}")
    data = request.json
    amount = data.get('amount')
    currency = data.get('currency', 'EGP')
    payment_method_type = data.get('payment_method_type')

    email = data.get('email')
    full_name = data.get('full_name')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    phone_number = data.get('phone_number')
    address = data.get('address')
    building = data.get('building')
    floor = data.get('floor')
    apartment = data.get('apartment')
    governorate = data.get('governorate')
    mobile_wallet_number = data.get('mobile_wallet_number')

    if not all([amount, payment_method_type, email, full_name, phone_number, address, building, floor, apartment, governorate]):
        return jsonify({"error": "Missing required payment or delivery information."}), 400

    if payment_method_type == 'mobile_wallet' and (not mobile_wallet_number or not mobile_wallet_number.isdigit() or len(mobile_wallet_number) != 11):
        return jsonify({"error": "Valid 11-digit mobile wallet number is required for mobile wallet payments."}), 400

    print(f"DEBUG PAYMOB CONFIG: PAYMOB_API_KEY={PAYMOB_API_KEY[:10] + '...' if PAYMOB_API_KEY else 'None'}")
    print(f"DEBUG PAYMOB CONFIG: PAYMOB_MERCHANT_ID={PAYMOB_MERCHANT_ID}")
    print(f"DEBUG PAYMOB CONFIG: PAYMOB_CARD_INTEGRATION_ID={PAYMOB_CARD_INTEGRATION_ID}")
    print(f"DEBUG PAYMOB CONFIG: PAYMOB_MOBILE_WALLET_INTEGRATION_ID={PAYMOB_MOBILE_WALLET_INTEGRATION_ID}")
    print(f"DEBUG PAYMOB CONFIG: PAYMOB_HMAC_SECRET={PAYMOB_HMAC_SECRET[:10] + '...' if PAYMOB_HMAC_SECRET else 'None'}")
    print(f"DEBUG PAYMOB CONFIG: PAYMOB_IFRAME_ID={PAYMOB_IFRAME_ID}")

    if not all([PAYMOB_API_KEY, PAYMOB_MERCHANT_ID, PAYMOB_CARD_INTEGRATION_ID,
                PAYMOB_MOBILE_WALLET_INTEGRATION_ID, PAYMOB_HMAC_SECRET, PAYMOB_IFRAME_ID]):
        print("Error: Paymob API credentials or iFrame ID are not fully configured in .env")
        return jsonify({"error": "Server configuration error. Please contact support."}), 500

    amount_cents = int(float(amount) * 100)
    cart_data = session.get('cart', {})
    if not cart_data:
        return jsonify({"error": "Your cart is empty. Cannot create payment."}), 400

    products = load_products()
    cart_items_for_db = []
    cleaned_cart = {}
    for key, value in cart_data.items():
        if isinstance(value, int):
            try:
                pid_str, size = key.split('_')
            except ValueError:
                pid_str, size = key, 'Unknown'
            value = {
                'product_id': int(pid_str),
                'size': size,
                'quantity': value
            }
        pid = value['product_id']
        size = value.get('size', 'Unknown')
        new_key = f"{pid}_{size}"
        if new_key in cleaned_cart:
            cleaned_cart[new_key]['quantity'] += value['quantity']
        else:
            cleaned_cart[new_key] = {
                'product_id': pid,
                'size': size,
                'quantity': value['quantity']
            }
    session['cart'] = cleaned_cart
    session.modified = True
    cart_data = cleaned_cart

    for key, entry in cart_data.items():
        pid = entry.get('product_id')
        size = entry.get('size')
        quantity = entry.get('quantity')
        product = next((p for p in products if p['id'] == pid), None)
        if product:
            cart_items_for_db.append({
                'product_id': pid,
                'name': product['name'],
                'quantity': quantity,
                'price': product['price'],
                'size': size
            })
    if not cart_items_for_db:
        return jsonify({"error": "No valid items in cart to process."}), 400

    shipping_cost = 70 if governorate.strip().lower() == 'cairo' else 120
    order_id = None
    try:
        with sqlite3.connect('store.db') as conn:
            c = conn.cursor()
            created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute('''INSERT INTO orders (name, phone, address, building, floor, apartment, governorate, email, payment, shipping, total_price, created_at, status)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (full_name, phone_number, address, building, floor, apartment, governorate, email,
                       payment_method_type, shipping_cost, amount, created_at, 'Pending Paymob'))
            order_id = c.lastrowid

            c.execute('''
                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    size TEXT,
                    FOREIGN KEY (order_id) REFERENCES orders(id),
                    FOREIGN KEY (product_id) REFERENCES products(id)
                )
            ''')
            conn.commit()

            for item in cart_items_for_db:
                c.execute('''INSERT INTO order_items (order_id, product_id, product_name, quantity, price, size)
                             VALUES (?, ?, ?, ?, ?, ?)''',
                          (order_id, item['product_id'], item['name'], item['quantity'], item['price'], item['size']))
            conn.commit()
        print(f"Order {order_id} saved to DB with status: Pending Paymob")

    except sqlite3.Error as e:
        print(f"Database error when saving order: {e}")
        return jsonify({"error": "Failed to save order to database."}), 500
    except Exception as e:
        print(f"An unexpected error occurred during order saving: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

    try:
        auth_response = requests.post(
            f"{PAYMOB_BASE_URL}/auth/tokens",
            json={"api_key": PAYMOB_API_KEY},
            verify=certifi.where()
        )
        auth_response.raise_for_status()
        auth_token = auth_response.json()['token']
        print(f"Paymob Auth Token: {auth_token[:10]}...")

        order_registration_payload = {
            "auth_token": auth_token,
            "delivery_needed": "false",
            "merchant_id": PAYMOB_MERCHANT_ID,
            "amount_cents": amount_cents,
            "currency": currency,
            "merchant_order_id": str(order_id),
            "items": [
                {"name": item['name'], "amount_cents": int(item['price'] * 100), "description": item['name'], "quantity": str(item['quantity'])}
                for item in cart_items_for_db
            ],
            "shipping_data": {
                "apartment": apartment, "email": email, "floor": floor,
                "first_name": first_name, "street": address, "building": building,
                "phone_number": phone_number, "postal_code": "NA",
                "extra_description": "NA", "city": governorate, "country": "EG",
                "last_name": last_name, "state": governorate
            }
        }
        order_response = requests.post(
            f"{PAYMOB_BASE_URL}/ecommerce/orders",
            json=order_registration_payload,
            verify=certifi.where()
        )
        order_response.raise_for_status()
        paymob_order_id = order_response.json()['id']
        print(f"Paymob Order registered. Paymob Order ID: {paymob_order_id}")

        with sqlite3.connect('store.db') as conn:
            c = conn.cursor()
            c.execute("UPDATE orders SET paymob_order_id = ? WHERE id = ?", (paymob_order_id, order_id))
            conn.commit()

        integration_id = PAYMOB_CARD_INTEGRATION_ID if payment_method_type == 'card' else PAYMOB_MOBILE_WALLET_INTEGRATION_ID
        print(f"DEBUG: Using Integration ID: {integration_id} for payment type: {payment_method_type}")

        redirection_url = f"https://metronary.store/payment_status"

        payment_key_payload = {
            "auth_token": auth_token,
            "amount_cents": amount_cents,
            "expiration": 3600,
            "order_id": paymob_order_id,
            "billing_data": {
                "apartment": apartment, "email": email, "floor": floor,
                "first_name": first_name, "street": address, "building": building,
                "phone_number": phone_number, "postal_code": "NA",
                "extra_description": "NA", "city": governorate, "country": "EG",
                "last_name": last_name, "state": governorate
            },
            "currency": currency,
            "integration_id": integration_id,
            "lock_order_locked": "false",
            "wallets_callback": redirection_url
        }

        if payment_method_type == 'mobile_wallet':
            payment_key_payload["source"] = {
                "identifier": mobile_wallet_number,
                "subtype": "WALLET"
            }
            payment_key_payload["billing_data"]["phone_number"] = mobile_wallet_number

        payment_key_response = requests.post(
            f"{PAYMOB_BASE_URL}/acceptance/payment_keys",
            json=payment_key_payload,
            verify=certifi.where()
        )
        payment_key_response.raise_for_status()
        payment_key = payment_key_response.json()['token']
        print(f"Payment key generated: {payment_key[:10]}...")

        final_redirect_url = None
        if payment_method_type == 'card':
            final_redirect_url = f"https://accept.paymobsolutions.com/api/acceptance/iframes/{PAYMOB_IFRAME_ID}?payment_token={payment_key}"
        elif payment_method_type == 'mobile_wallet':
            wallet_initiation_payload = {
                "payment_token": payment_key,
                "source": {
                    "identifier": mobile_wallet_number,
                    "subtype": "WALLET"
                }
            }
            print(f"DEBUG: Mobile Wallet Initiation Payload: {json.dumps(wallet_initiation_payload, indent=2)}")
            wallet_initiation_response = requests.post(
                f"{PAYMOB_BASE_URL}/acceptance/payments/pay",
                json=wallet_initiation_payload,
                verify=certifi.where()
            )
            wallet_initiation_response.raise_for_status()
            
            print("DEBUG Full wallet response:", wallet_initiation_response.json())
            final_redirect_url = wallet_initiation_response.json().get('redirect_url')
            if not final_redirect_url:
                raise Exception(f"Paymob did not provide a redirect_url for mobile wallet. Response: {wallet_initiation_response.text}")
            print(f"DEBUG: Mobile Wallet Initiation Response: {wallet_initiation_response.text}")
            print(f"Mobile Wallet Redirect URL: {final_redirect_url}")
        else:
            return jsonify({"error": "Invalid payment method type"}), 400

        session['cart'] = {}
        session.modified = True

        return jsonify({
            "success": True,
            "payment_url": final_redirect_url,
            "payment_token": payment_key,
            "order_id": order_id
        })

    except requests.exceptions.HTTPError as e:
        print(f"Paymob API HTTP Error: {e.response.status_code} - {e.response.text}")
        traceback.print_exc()
        if order_id:
            with sqlite3.connect('store.db') as conn:
                c = conn.cursor()
                c.execute("UPDATE orders SET status = ? WHERE id = ?", ('Paymob API Failed', order_id))
                conn.commit()
        return jsonify({"error": f"Payment initiation failed: {e.response.text}"}), e.response.status_code
    except Exception as e:
        print(f"An unexpected error occurred during payment initiation: {e}")
        if order_id:
            with sqlite3.connect('store.db') as conn:
                c = conn.cursor()
                c.execute("UPDATE orders SET status = ? WHERE id = ?", ('Payment Initiation Error', order_id))
                conn.commit()
        return jsonify({"error": "An internal server error occurred during payment initiation."}), 500



@app.route('/paymob_webhook', methods=['POST'])
def paymob_webhook():
    """
    Handles incoming webhook notifications from Paymob.
    This endpoint will receive real-time updates about transaction status
    and update your SQLite order database.
    """
    try:
        data = request.json
        print(f"Received Paymob Webhook: {json.dumps(data, indent=2)}")

        # Verify HMAC signature for security
        # IMPORTANT: The fields for HMAC calculation must be exactly as specified by Paymob.
        # This is for 'transaction_processed' callback.
        obj = data['obj']
        amount_cents = str(obj.get('amount_cents'))
        created_at = str(obj.get('created_at'))
        currency = str(obj.get('currency'))
        error_occured = str(obj.get('error_occured'))
        has_parent_transaction = str(obj.get('has_parent_transaction'))
        transaction_id = str(obj.get('id')) # Paymob's transaction ID
        integration_id = str(obj.get('integration_id'))
        is_3d_secure = str(obj.get('is_3d_secure'))
        is_auth = str(obj.get('is_auth'))
        is_capture = str(obj.get('is_capture'))
        is_refunded = str(obj.get('is_refunded'))
        is_standalone_payment = str(obj.get('is_standalone_payment'))
        is_voided = str(obj.get('is_voided'))
        paymob_order_id = str(obj.get('order', {}).get('id')) # Paymob's order ID
        owner = str(obj.get('owner'))
        pending = str(obj.get('pending'))
        source_data_pan = str(obj.get('source_data', {}).get('pan'))
        source_data_sub_type = str(obj.get('source_data', {}).get('sub_type'))
        source_data_type = str(obj.get('source_data', {}).get('type'))
        success = str(obj.get('success'))

        # Construct the data string for HMAC calculation (alphabetical order)
        data_string = (
            amount_cents + created_at + currency + error_occured +
            has_parent_transaction + transaction_id + integration_id +
            is_3d_secure + is_auth + is_capture + is_refunded +
            is_standalone_payment + is_voided + paymob_order_id + owner +
            pending + source_data_pan + source_data_sub_type +
            source_data_type + success
        )

        hashed_string = hmac.new(
            PAYMOB_HMAC_SECRET.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()

        if hashed_string != data.get('hmac'):
            print("HMAC verification failed!")
            return jsonify({"status": "HMAC verification failed"}), 403

        print("HMAC verification successful.")

        # Extract relevant information
        transaction_status_paymob = "Paid" if obj.get('success') else "Failed"
        paymob_transaction_id = obj.get('id')
        merchant_order_id = obj.get('order', {}).get('merchant_order_id') # Your internal order ID from Paymob

        # Update your internal order database (SQLite)
        if merchant_order_id: # Ensure we have our internal order ID
            try:
                with sqlite3.connect('store.db') as conn:
                    c = conn.cursor()
                    c.execute("UPDATE orders SET status = ?, paymob_transaction_id = ? WHERE id = ?",
                              (transaction_status_paymob, paymob_transaction_id, merchant_order_id))
                    conn.commit()
                print(f"Order {merchant_order_id} updated to status: {transaction_status_paymob} in DB.")

                # Optional: Send email confirmation for Paymob payments
                # Fetch order details to send a proper email
                c.execute("SELECT email, name, total_price FROM orders WHERE id = ?", (merchant_order_id,))
                order_row = c.fetchone()
                if order_row:
                    customer_email, customer_name, total_price = order_row
                    if transaction_status_paymob == "Paid":
                        send_order_email(
                            customer_email,
                            "Metro Nary – Your Payment Was Successful!",
                            f"""
                            <h2 style='color:#10B981;'>Payment Confirmed!</h2>
                            <p>Dear {customer_name}, your payment of EGP {total_price} for order #{merchant_order_id} was successful.</p>
                            <p>Paymob Transaction ID: {paymob_transaction_id}</p>
                            <p>Your order is now being processed.</p>
                            """
                        )
                    else:
                        send_order_email(
                            customer_email,
                            "Metro Nary – Payment Failed",
                            f"""
                            <h2 style='color:#ff0000;'>Payment Failed</h2>
                            <p>Dear {customer_name}, your payment for order #{merchant_order_id} of EGP {total_price} failed.</p>
                            <p>Reason: {obj.get('data', {}).get('message', 'N/A')}</p>
                            <p>Please try again or contact support if you continue to experience issues.</p>
                            """
                        )

            except sqlite3.Error as e:
                print(f"Database error when updating order status from webhook: {e}")
                # Return a 500 status to Paymob to indicate an issue on your end
                return jsonify({"status": "error", "message": "Database update failed"}), 500
        else:
            print(f"Merchant Order ID not found in webhook data: {merchant_order_id}")
            # If merchant_order_id is missing, it's a critical error for tracking
            return jsonify({"status": "error", "message": "Missing merchant_order_id in webhook"}), 400

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"Error processing webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/payment_status', methods=['GET'])
def payment_status():
    paymob_response = request.args.to_dict()
    print(f"DEBUG: payment_status: Callback received. Args: {paymob_response}")

    merchant_order_id = paymob_response.get('merchant_order_id')
    paymob_transaction_id = paymob_response.get('paymob_transaction_id') # Get this from the URL args

    # Determine if this is a Cash on Delivery order based on the transaction ID
    is_cash_on_delivery = (paymob_transaction_id == 'N/A (Cash)')

    # --- 1. HMAC Verification (CRITICAL SECURITY STEP) ---
    # Skip HMAC verification if it's a Cash on Delivery order
    if not is_cash_on_delivery:
        hmac_param_names = [
            'amount_cents', 'created_at', 'currency', 'error_occured', 'has_parent_transaction',
            'id', 'integration_id', 'is_3d_secure', 'is_auth', 'is_capture', 'is_refunded',
            'is_standalone_payment', 'is_voided', 'order', 'owner', 'pending', 'profile_id',
            'refunded_amount_cents', 'success'
        ]

        hmac_data_elements = []
        for param_name in hmac_param_names:
            value = paymob_response.get(param_name, '')
            if isinstance(value, str):
                value = value.lower() if value in ['true', 'false'] else value
            hmac_data_elements.append(str(value))

        data_string = ''.join(hmac_data_elements)
        print(f"DEBUG: payment_status: HMAC Data String: {data_string}")

        hashed_hmac = hmac.new(
            PAYMOB_HMAC_SECRET.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()

        received_hmac = paymob_response.get('hmac')
        print(f"DEBUG: payment_status: Calculated HMAC: {hashed_hmac}")
        print(f"DEBUG: payment_status: Received HMAC: {received_hmac}")

        if hashed_hmac != received_hmac:
            print(f"ERROR: payment_status: HMAC Mismatch! Calculated: {hashed_hmac}, Received: {received_hmac}")
            return render_template('thankyou.html', success=False, message="Payment verification failed (HMAC mismatch). Please contact support.", name="Customer", merchant_order_id=merchant_order_id, db_status="HMAC Mismatch")
        print("DEBUG: payment_status: HMAC verification successful.")
    else:
        print("DEBUG: payment_status: Skipping HMAC verification for Cash on Delivery order.")


    # --- 2. Process Payment Status ---
    paymob_success = paymob_response.get('success') == 'true'
    paymob_message = paymob_response.get('data.message', 'No specific message provided.')
    paymob_pending = paymob_response.get('pending') == 'true'

    db_status = 'Failed'
    message_to_user = "Your payment could not be processed."
    customer_name = "Customer"
    customer_email = "N/A"

    print(f"DEBUG: payment_status: Processing order ID: {merchant_order_id}, Success: {paymob_success}, Pending: {paymob_pending}, Is COD: {is_cash_on_delivery}")

    if merchant_order_id:
        try:
            with sqlite3.connect('store.db') as conn:
                c = conn.cursor()
                current_order = c.execute("SELECT name, email, status FROM orders WHERE id = ?", (merchant_order_id,)).fetchone()
                if current_order:
                    customer_name = current_order[0]
                    customer_email = current_order[1]

                    if is_cash_on_delivery:
                        db_status = 'Pending Cash'
                        message_to_user = "Your Cash on Delivery order has been placed successfully!"
                        # For COD, we don't need to update transaction_id as it's 'N/A (Cash)'
                        # And status is already 'Pending Cash' from complete_checkout
                        # We only update if status is not already 'Pending Cash' to avoid redundant updates
                        c.execute("UPDATE orders SET status = ? WHERE id = ? AND status != 'Pending Cash'",
                                  (db_status, merchant_order_id))
                        conn.commit()
                        print(f"DEBUG: payment_status: COD Order {merchant_order_id} confirmed in DB.")
                        # Email for COD is sent from complete_checkout, no need to send again here.
                    elif paymob_success and not paymob_pending:
                        db_status = 'Paid'
                        message_to_user = "Your payment was successful!"
                        print(f"DEBUG: payment_status: Order {merchant_order_id} status will be set to PAID.")
                        c.execute("UPDATE orders SET status = ?, paymob_transaction_id = ? WHERE id = ? AND status != 'Paid'",
                                  (db_status, paymob_transaction_id, merchant_order_id))
                        conn.commit()
                        print(f"DEBUG: payment_status: Order {merchant_order_id} updated in DB.")
                        email_subject = f"Order #{merchant_order_id} Confirmed - Metro Nary"
                        email_content = f"""
                        <h1>Thank You for Your Order, {customer_name}!</h1>
                        <p>Your order #{merchant_order_id} has been successfully placed and paid for.</p>
                        <p>Transaction ID: {paymob_transaction_id}</p>
                        <p>We will process your order shortly.</p>
                        <p>Visit your order history: <a href="https://metronary.store/order_history">Order History</a></p>
                        """
                        send_order_email(customer_email, email_subject, email_content)
                        print(f"DEBUG: payment_status: Email sent for order {merchant_order_id}.")
                    elif paymob_pending:
                        db_status = 'Pending Paymob'
                        message_to_user = f"Your payment is pending: {paymob_message}. Please complete any required steps."
                        print(f"DEBUG: payment_status: Order {merchant_order_id} status will be set to PENDING PAYMOB.")
                        c.execute("UPDATE orders SET status = ?, paymob_transaction_id = ? WHERE id = ? AND status != 'Paid'",
                                  (db_status, paymob_transaction_id, merchant_order_id))
                        conn.commit()
                        print(f"DEBUG: payment_status: Order {merchant_order_id} updated in DB.")
                    else: # Payment failed
                        db_status = 'Failed'
                        message_to_user = f"Your payment failed: {paymob_message}. Please try again."
                        print(f"DEBUG: payment_status: Order {merchant_order_id} status will be set to FAILED.")
                        c.execute("UPDATE orders SET status = ?, paymob_transaction_id = ? WHERE id = ? AND status != 'Paid'",
                                  (db_status, paymob_transaction_id, merchant_order_id))
                        conn.commit()
                        print(f"DEBUG: payment_status: Order {merchant_order_id} updated in DB.")
                else:
                    message_to_user = "Payment status received, but order not found in our system."
                    db_status = "Order Not Found"
                    print(f"ERROR: payment_status: Order ID {merchant_order_id} not found in DB.")

        except sqlite3.Error as e:
            print(f"ERROR: payment_status: Database error during processing: {e}")
            db_status = "DB Error"
            message_to_user = "An internal database error occurred while processing your payment status."
        except Exception as e:
            print(f"ERROR: payment_status: An unexpected error occurred: {e}")
            db_status = "Server Error"
            message_to_user = "An internal server error occurred while processing your payment status."
    else:
        message_to_user = "Payment status received, but no merchant order ID was provided."
        db_status = "No Order ID"
        print("ERROR: payment_status: No merchant_order_id provided in callback.")

    print(f"DEBUG: payment_status: Preparing to render thankyou.html with success={paymob_success and not paymob_pending}, message='{message_to_user}', name='{customer_name}', merchant_order_id='{merchant_order_id}', paymob_transaction_id='{paymob_transaction_id}', db_status='{db_status}'")

    # Render the thankyou.html template
    return render_template('thankyou.html',
                           success=(paymob_success and not paymob_pending) or is_cash_on_delivery, # COD is always 'success' for display
                           message=message_to_user,
                           name=customer_name,
                           merchant_order_id=merchant_order_id,
                           paymob_transaction_id=paymob_transaction_id,
                           db_status=db_status
                          )

@app.route('/complete_checkout', methods=['POST'])
def complete_checkout():
    """
    Handles POST requests for Cash on Delivery payments only.
    It processes the order and saves it to SQLite.
    """
    payment_method = request.form.get('payment_method')

    # This route should ONLY handle 'cash' payments now.
    if payment_method != 'cash':
        flash("Online payments are handled separately. Please use the Pay with Card/Wallet buttons.", "error")
        return redirect(url_for('checkout'))

    cart_data = session.get('cart', {})
    
    # --- Cart data cleaning and validation (copied from checkout route for consistency) ---
    cleaned_cart = {}
    for key, value in cart_data.items():
        # Handle old cart format where value was just quantity (integer)
        if isinstance(value, int):
            try:
                pid_str, size = key.split('_')
                value = {
                    'product_id': int(pid_str),
                    'size': size,
                    'quantity': value
                }
            except ValueError: # Fallback if key is not 'pid_size' format
                value = {
                    'product_id': int(key), # Assume key is just product_id
                    'size': 'Unknown',
                    'quantity': value
                }
        
        pid = value.get('product_id') 
        size = value.get('size', 'Unknown')
        quantity = value.get('quantity')

        if pid is None or quantity is None:
            print(f"Skipping malformed cart entry during checkout: {key} -> {value}")
            continue # Skip malformed entries

        new_key = f"{pid}_{size}" # Re-create key for cleaned_cart

        if new_key in cleaned_cart:
            cleaned_cart[new_key]['quantity'] += quantity
        else:
            cleaned_cart[new_key] = {
                'product_id': pid,
                'size': size,
                'quantity': quantity
            }
    
    session['cart'] = cleaned_cart # Update session with cleaned cart
    session.modified = True # Mark session as modified
    cart_data = cleaned_cart # Use the cleaned cart for further processing

    if not cart_data:
        flash("Your cart is empty. Please add items before placing an order.", "error")
        return redirect(url_for('cart')) # Redirect to cart if empty

    products = load_products() # Load all products to get their details (name, price etc.)
    cart_items_for_db = [] # This list will hold the actual items to be saved to DB
    calculated_subtotal = 0

    for key, entry in cart_data.items():
        pid = entry.get('product_id')
        size = entry.get('size')
        quantity = entry.get('quantity')
        
        product = next((p for p in products if p['id'] == pid), None) # Find the product by its ID

        if product and quantity and quantity > 0: # Ensure product exists and quantity is valid
            item_price = product['price']
            item_name = product['name'] # Get the product name for order_items table
            
            calculated_subtotal += (item_price * quantity)
            
            cart_items_for_db.append({ # Prepare data for order_items table
                'product_id': pid,
                'product_name': item_name, # CRITICAL: Include product_name
                'size': size,
                'quantity': quantity,
                'price': item_price
            })
        else:
            # If a product in cart is invalid/not found in DB, remove it and flash error
            session['cart'].pop(key, None)
            session.modified = True
            flash(f"A product in your cart (ID: {pid}) was invalid or not found and has been removed. Please review your cart.", "warning")
            # If an item was removed, it's safer to redirect back to cart for user to review
            return redirect(url_for('cart'))

    if not cart_items_for_db: # After filtering/validation, if cart is now empty
        flash("Your cart is empty or contains only invalid items. Cannot place an order.", "error")
        return redirect(url_for('cart'))

    # --- Get customer details from form ---
    name = request.form.get('name')
    phone = request.form.get('phone')
    address = request.form.get('address')
    building = request.form.get('building')
    floor = request.form.get('floor')
    apartment = request.form.get('apartment')
    governorate = request.form.get('governorate')
    email = request.form.get('email') or None # Use None if email is empty string
    notes = request.form.get('notes', '') # Add notes field if you have one in your form

    # --- Server-side validation (duplicate from frontend but necessary) ---
    validation_errors = []
    if not all([name, phone, address, building, floor, apartment, governorate]):
        validation_errors.append("All delivery fields (Name, Phone, Address, Building, Floor, Apartment, Governorate) are required.")
    
    if phone and (not phone.isdigit() or len(phone) < 8 or len(phone) > 15):
        validation_errors.append("Phone number must be between 8 and 15 digits and contain only numbers.")
    
    try:
        if building: int(building)
        if floor: int(floor)
        if apartment: int(apartment)
    except ValueError:
        validation_errors.append("Building, floor, and apartment must be valid numbers.")

    if name and not all(c.isalpha() or c.isspace() for c in name):
        validation_errors.append("Name must contain only letters and spaces.")

    if validation_errors:
        # If validation fails, re-render checkout page with errors and pre-filled data
        # Recalculate totals for rendering the page again with error
        shipping_calc = 70 if (governorate and governorate.strip().lower() == 'cairo') else 120
        total_calc = calculated_subtotal + shipping_calc
        
        flash("❌ " + " ".join(validation_errors), "error")
        return render_template('checkout.html', 
                               cart_items=cart_items_for_db, # Use cart_items_for_db for display
                               item_count=len(cart_items_for_db),
                               subtotal=calculated_subtotal, 
                               shipping=shipping_calc, 
                               total=total_calc,
                               user_email=email, user_name=name, user_phone=phone, user_address=address,
                               user_building=building, user_floor=floor, user_apartment=apartment, user_governorate=governorate)

    # --- Calculate final shipping and total price ---
    shipping_cost = 70 if governorate.strip().lower() == 'cairo' else 120
    final_total_price = calculated_subtotal + shipping_cost
    
    # --- Database Transaction ---
    db = get_db() # Get database connection
    try:
        cursor = db.cursor()

        # 1. Insert into orders table
        cursor.execute('''
            INSERT INTO orders (name, phone, address, building, floor, apartment, governorate, email, payment, shipping, total_price, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            name, phone, address, building, floor, apartment, governorate, email,
            'Cash on Delivery', # Payment method
            shipping_cost, # Shipping cost
            final_total_price, # Total price
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'), # Current timestamp
            'Pending Cash Delivery' # Initial status for COD
        ))
        
        order_id = cursor.lastrowid # Get the ID of the newly created order

        # 2. Insert into order_items table for each item in the order
        for item in cart_items_for_db:
            cursor.execute('''
                INSERT INTO order_items (order_id, product_id, product_name, quantity, price, size)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                order_id,
                item['product_id'],
                item['product_name'], # This is now correctly provided
                item['quantity'],
                item['price'],
                item['size']
            ))

        db.commit() # Commit all changes to the database
        session.pop('cart', None) # Clear the cart after successful order

        flash("Your order has been placed successfully!", "success")

        # --- Send order confirmation emails ---
        # Ensure send_order_email function is defined and configured to work
        try:
            send_order_email(
                email,
                "Metro Nary – Your Order Has Been Received",
                f"""
                <h2 style='color:#ff0000;'>Thank you for your order, {name}!</h2>
                <p>We’ve received your order and it’s now being processed.</p>
                <p>Payment Method: Cash on Delivery</p>
                <ul>
                    {''.join(f"<li>{item['product_name']} × {item['quantity']} (Size: {item['size']}) – EGP {item['price'] * item['quantity']}</li>" for item in cart_items_for_db)}
                </ul>
                <p>Shipping to: {address}, Building {building}, Floor {floor}, Apartment {apartment}, {governorate}</p>
                <p>Total: EGP {final_total_price}</p>
                """
            )

            send_order_email(
                "mohamed11samy@gmail.com",  # Change to your admin email address
                "New Order Received – Metro Nary (Cash on Delivery)",
                f"""
                <h2 style='color:#ff0000;'>New Order Notification</h2>
                <p><strong>Customer:</strong> {name}</p>
                <p><strong>Phone:</strong> {phone}</p>
                <p><strong>Email:</strong> {email}</p>
                <p><strong>Address:</strong> {address}, Building {building}, Floor {floor}, Apartment {apartment}</p>
                <p><strong>Governorate:</strong> {governorate}</p>
                <p><strong>Payment:</strong> Cash on Delivery</p>
                <ul>
                    {''.join(f"<li>{item['product_name']} × {item['quantity']} (Size: {item['size']}) – EGP {item['price'] * item['quantity']}</li>" for item in cart_items_for_db)}
                </ul>
                <p><strong>Total:</strong> EGP {final_total_price}</p>
                """
            )
        except Exception as email_error:
            print(f"Error sending order confirmation emails: {email_error}")
            # Do not block order completion if email fails, but log it.

        # Redirect to the payment_status page with relevant order details
        return redirect(url_for('payment_status',
                                 success='true', # For cash, we assume immediate "success" for display
                                 merchant_order_id=order_id,
                                 paymob_transaction_id="N/A (Cash)", # Special identifier for COD
                                 amount_cents=int(final_total_price * 100), # Amount in cents
                                 currency="EGP",
                                 message="Cash on Delivery Order Placed.",
                                 pending='false', # COD is not pending in this context
                                 created_at=datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f'),
                                 error_occured='false',
                                 has_parent_transaction='false',
                                 id='N/A', # Placeholder for Paymob transaction ID
                                 integration_id='N/A', # Placeholder
                                 is_3d_secure='false', # Placeholder
                                 is_auth='false', # Placeholder
                                 is_capture='false', # Placeholder
                                 is_refunded='false', # Placeholder
                                 is_standalone_payment='true', # This is a direct payment
                                 is_voided='false', # Placeholder
                                 order=order_id, # Our internal order ID
                                 owner='N/A', # Placeholder
                                 profile_id='N/A', # Placeholder
                                 refunded_amount_cents='0', # Placeholder
                                 db_status="Pending Cash Delivery")) # Custom status for display

    except sqlite3.IntegrityError as e:
        db.rollback() # Rollback in case of integrity error (e.g., NOT NULL constraint)
        flash(f"Database integrity error: {e}. Please check your input.", "error")
        print(f"Database IntegrityError: {e}")
        return redirect(url_for('checkout')) # Redirect back to checkout
    except sqlite3.OperationalError as e:
        db.rollback() # Rollback in case of database operational error (e.g., locked)
        flash(f"Database error: {e}. Please try again later.", "error")
        print(f"Database OperationalError: {e}")
        return redirect(url_for('checkout'))
    except Exception as e:
        db.rollback() # Rollback for other unexpected errors
        flash(f"An unexpected error occurred: {e}. Please try again.", "error")
        print(f"Unexpected error placing order: {e}")
        return redirect(url_for('checkout'))
# --- Admin Routes ---
# (These routes were already mostly fine, just ensuring consistency with new fields)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # 🔐 Replace this with your hashed password from your .env or secure config
        ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin") # Example: Load from .env
        HASHED_PASSWORD = os.getenv("ADMIN_PASSWORD_HASH", "scrypt:32768:8:1$7jGUT5Tsb2sY8NGg$17939ad0c1609291b2b640e3e06143070aa84beb2a7630be20e8086e1bdd1393c70ceb3f3d6bf90e90addb8923adafd0fbbc0c07064dfe082e68c8a884b49eff")

        if username == ADMIN_USERNAME and check_password_hash(HASHED_PASSWORD, password):
            session['admin'] = True
            return redirect(url_for('admin'))
        else:
            error = "Invalid username or password."
    
    return render_template('admin_login.html', error=error)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    db = get_db()
    cursor = db.cursor()
    
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('store.db')
    c = conn.cursor()

    status_filter = request.args.get('status')
    if status_filter:
      cursor.execute("SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC", (status_filter,))
    
    else:
      cursor.execute("SELECT * FROM orders ORDER BY created_at DESC")

    if request.method == 'POST':
        if 'question' in request.form and 'answer' in request.form:
            question = request.form.get('question')
            answer = request.form.get('answer')
            if question.strip() and answer.strip():
                c.execute('INSERT INTO faqs (question, answer) VALUES (?, ?)', (question, answer))
                conn.commit()
                flash('FAQ added successfully!', 'success')
            else:
                flash('FAQ question and answer cannot be empty.', 'error')
            return redirect(url_for('admin'))

        name = request.form.get('name')
        price = int(request.form.get('price'))
        sizes = ','.join(request.form.getlist('sizes'))
        description = request.form.get('description')
        image_filenames = []

        if 'product_images' in request.files:
            files = request.files.getlist('product_images')
            if len(files) > 4:
                flash('You can only upload a maximum of 4 images.', 'error')
            for file in files:
                if file.filename == '':
                    continue
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    file.save(filepath)
                    image_filenames.append(f'product_images/{filename}')
                else:
                    flash(f'Invalid file type for {file.filename}. Only JPG, PNG, GIF are allowed.', 'error')

        images_db_string = ','.join(image_filenames)
        c.execute('INSERT INTO products (name, price, image, sizes, description) VALUES (?, ?, ?, ?, ?)', 
                  (name, price, images_db_string, sizes, description))
        conn.commit()
        flash('Product added successfully!', 'success')
        return redirect(url_for('admin'))

    today = datetime.now().strftime('%Y-%m-%d')

    c.execute('SELECT COUNT(*) FROM orders WHERE DATE(created_at) = ?', (today,))
    orders_today = c.fetchone()[0] or 0

    c.execute('SELECT SUM(total_price) FROM orders WHERE DATE(created_at) = ? AND status = "Delivered"', (today,))
    sales_today = c.fetchone()[0] or 0

    c.execute('SELECT id, name, price, image, sizes, description FROM products')
    rows = c.fetchall()
    products = [{
        'id': row[0],
        'name': row[1],
        'price': row[2],
        'image': row[3],
        'sizes': row[4].split(',') if row[4] else [],
        'description': row[5],
    } for row in rows]

    for product in products:
        if product['image']:
            product['images'] = [path.strip() for path in product['image'].split(',') if path.strip()]
        else:
            product['images'] = []

    query = '''SELECT id, name, phone, governorate, total_price, created_at, 
                      COALESCE(status, 'Unknown') as status, 
                      payment, paymob_transaction_id
               FROM orders'''

    if status_filter:
        query += ' WHERE COALESCE(status, "Unknown") = ?'

    query += ''' ORDER BY 
                      CASE COALESCE(status, 'Unknown')
                          WHEN 'Pending Paymob' THEN 0
                          WHEN 'Pending Cash Delivery' THEN 1
                          WHEN 'Paid' THEN 2
                          WHEN 'Shipped' THEN 3
                          WHEN 'Delivered' THEN 4
                          WHEN 'Failed' THEN 5
                          WHEN 'Unknown' THEN 6
                          ELSE 7
                      END,
                      created_at DESC
                LIMIT 20'''

    if status_filter:
        c.execute(query, (status_filter,))
    else:
        c.execute(query)

    order_rows = c.fetchall()
    orders = []

    for order in order_rows:
        order_id = order[0]
        c.execute('''
            SELECT products.name, order_items.quantity, order_items.price, order_items.size
            FROM order_items
            JOIN products ON order_items.product_id = products.id
            WHERE order_id = ?
        ''', (order_id,))
        items = [{"name": i[0], "quantity": i[1], "price": i[2], "size": i[3]} for i in c.fetchall()]

        orders.append({
            'id': order_id,
            'name': order[1],
            'phone': order[2],
            'governorate': order[3],
            'total_price': order[4],
            'created_at': order[5],
            'status': order[6],
            'payment_method': order[7],
            'paymob_transaction_id': order[8],
            'items': items,
        })

    c.execute('SELECT COUNT(*) FROM visitors WHERE date = ?', (today,))
    visitor_count = c.fetchone()[0]

    c.execute('SELECT id, question, answer FROM faqs ORDER BY id DESC')
    faqs = [{'id': row[0], 'question': row[1], 'answer': row[2]} for row in c.fetchall()]

    conn.close()

    return render_template('admin.html',
                           products=products,
                           orders=orders,
                           visitor_count=visitor_count,
                           orders_today=orders_today,
                           sales_today=sales_today,
                           faqs=faqs)


@app.route('/update_order_status/<int:order_id>', methods=['POST'])
def update_order_status(order_id):
    new_status = request.form.get('status')
    conn = sqlite3.connect('store.db')
    c = conn.cursor()
    c.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))


@app.route('/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    conn = sqlite3.connect('store.db')
    c = conn.cursor()
    c.execute('DELETE FROM products WHERE id=?', (product_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))


@app.route('/user/login', methods=['GET', 'POST'])
def user_login():
    if request.method == 'POST':
        # 🔁 Step 0: Resend code if requested
        if 'resend_email' in request.form:
            email = request.form.get('resend_email')
            code = str(random.randint(100000, 999999))

            session['verify_email'] = email
            session['verify_code'] = code
            session['verify_time'] = datetime.now().timestamp()

            html_content = f'''
                <div style="font-family: Rajdhani, sans-serif; padding: 20px; background-color: #111; color: white;">
                    <h2 style="color: red;">Metro Nary Login Code</h2>
                    <p>Hello,</p>
                    <p>Your new login code is:</p>
                    <p style="font-size: 28px; font-weight: bold; color: #ffffff; background: red; padding: 10px 20px; display: inline-block; border-radius: 6px;">
                        {code}
                    </p>
                    <p>This code is valid for <strong>15 minutes</strong>. For your security, do not share it with anyone.</p>
                    <p>If you didn’t request this code, you can safely ignore this email.</p>
                    <br>
                    <p>Thank you,<br>Metro Nary Team</p>
                </div>
            '''

            message = Mail(
                from_email='metronary@outlook.com',  
                to_emails=email,
                subject='Your New Metro Nary Login Code',
                html_content=html_content
            )

            try:
                sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                sg.send(message)
            except Exception as e:
                return f"Failed to resend code: {e}"

            return render_template('user_login.html', code_sent=True, email=email)

        # ✅ Step 2: Handle verification code
        if 'code' in request.form:
            input_code = request.form.get('code')
            correct_code = session.get('verify_code')
            email = session.get('verify_email')
            timestamp = session.get('verify_time')

            if timestamp and datetime.now().timestamp() - timestamp > 600:
                session.pop('verify_code', None)
                session.pop('verify_time', None)
                return render_template('user_login.html', code_sent=False, error="Code expired. Please request a new one.")

            if input_code == correct_code:
                session['user_email'] = email

                # Get user's first name
                conn = sqlite3.connect('store.db')
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute('SELECT name FROM orders WHERE email = ? ORDER BY created_at DESC LIMIT 1', (email,))
                row = c.fetchone()
                session['user_first_name'] = row['name'].split()[0] if row and row['name'] else 'User'
                conn.close()

                return redirect(url_for('home'))
            else:
                return render_template('user_login.html', code_sent=True, email=email, error="Invalid code")

        # ✅ Step 1: Send code for the first time
        email = request.form.get('email')
        code = str(random.randint(100000, 999999))

        session['verify_email'] = email
        session['verify_code'] = code
        session['verify_time'] = datetime.now().timestamp()

        html_content = f'''
            <div style="font-family: Rajdhani, sans-serif; padding: 20px; background-color: #111; color: white;">
                <h2 style="color: red;">Metro Nary Login Code</h2>
                <p>Hello,</p>
                <p>To log in to your Metro Nary account, please use the verification code below:</p>
                <p style="font-size: 28px; font-weight: bold; color: #ffffff; background: red; padding: 10px 20px; display: inline-block; border-radius: 6px;">
                    {code}
                </p>
                <p>This code is valid for <strong>15 minutes</strong>. For your security, do not share it with anyone.</p>
                <p>If you didn’t request this code, you can safely ignore this email.</p>
                <br>
                <p>Thank you,<br>Metro Nary Team</p>
            </div>
        '''

        message = Mail(
            from_email='metronary@outlook.com', 
            to_emails=email,
            subject='Your Metro Nary Login Code',
            html_content=html_content
        )

        try:
            sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            sg.send(message)
        except Exception as e:
            return f"Failed to send email: {e}"

        return render_template('user_login.html', code_sent=True, email=email)

    return render_template('user_login.html', code_sent=False)


@app.route('/user/logout')
def user_logout():
    session.pop('user_email', None)
    return redirect(url_for('home'))


@app.route('/orders')
def orders():
    email = session.get('user_email')
    if not email:
        return redirect(url_for('user_login'))

    conn = sqlite3.connect('store.db')
    conn.row_factory = sqlite3.Row  # ✅ allow dict-style access
    c = conn.cursor()

    c.execute('SELECT * FROM orders WHERE email = ? ORDER BY created_at DESC', (email,))
    order_rows = c.fetchall()

    orders = []

    for row in order_rows:
        order_id = row["id"]

        # Fetch items in this order
        c.execute('''
            SELECT products.name, order_items.quantity, order_items.price, order_items.size
            FROM order_items
            JOIN products ON order_items.product_id = products.id
            WHERE order_items.order_id = ?
        ''', (order_id,))
        item_rows = c.fetchall()

        items = [{
            'name': r[0],
            'quantity': r[1],
            'price': r[2],
            'size': r[3] if r[3] else 'Unknown'
        } for r in item_rows]

        orders.append({
            'id': row["id"],
            'name': row["name"],
            'phone': row["phone"],
            'address': row["address"],
            'building': row["building"],
            'floor': row["floor"],
            'apartment': row["apartment"],
            'governorate': row["governorate"],
            'total_price': row["total_price"],
            'created_at': row["created_at"],
            'status': row["status"],
            'email': row["email"],
            'payment': row["payment"] if "payment" in row.keys() else "N/A", # Include payment method
            'paymob_transaction_id': row["paymob_transaction_id"] if "paymob_transaction_id" in row.keys() else "N/A", # Include Paymob transaction ID
            'paymob_order_id': row["paymob_order_id"] if "paymob_order_id" in row.keys() else "N/A", # Include Paymob order ID
            'items': items
        })

    conn.close()

    return render_template('orders.html', orders=orders)


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.route('/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    conn = sqlite3.connect('store.db')
    c = conn.cursor()

    if request.method == 'POST':
        name = request.form.get('name')
        price = int(request.form.get('price'))
        image = request.form.get('image')
        sizes = ','.join(request.form.getlist('sizes'))
        description = request.form.get('description')

        c.execute('UPDATE products SET name=?, price=?, image=?, sizes=?, description=? WHERE id=?',
                  (name, price, image, sizes, description, product_id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin'))

    # GET method
    c.execute('SELECT id, name, price, image, sizes, description FROM products WHERE id=?', (product_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return "Product not found", 404

    product = {
        'id': row[0],
        'name': row[1],
        'price': row[2],
        'image': row[3],
        'sizes': row[4].split(',') if row[4] else [],
        'description': row[5],
    }

    return render_template('edit.html', product=product)

@app.before_request
def require_login():
    if request.endpoint == 'admin' and not session.get('admin'):
        return redirect(url_for('admin_login'))


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    conn = sqlite3.connect('store.db')
    c = conn.cursor()
    c.execute('SELECT id, name, price, image, sizes, description FROM products WHERE id = ?', (product_id,))
    row = c.fetchone()
    conn.close()

    if row:
        product = {
            'id': row[0],
            'name': row[1],
            'price': row[2],
            'image': row[3], # This is the raw comma-separated string from DB
            'sizes': row[4].split(',') if row[4] else [],
            'description': row[5],
        }
        # Crucial: Convert the comma-separated string into a list of image paths for the template
        if product['image']:
            product['images'] = [path.strip() for path in product['image'].split(',') if path.strip()]
        else:
            product['images'] = []

        return render_template('product.html', product=product)
    else:
        return "Product not found", 404 


@app.route('/size-guide')
def size_guide():
    return render_template('size_guide.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/update_quantity', methods=['POST'])
def update_quantity():
    cart_key = request.form.get('cart_key')
    action = request.form.get('action') # 'increase' or 'decrease'

    if not cart_key or action not in ['increase', 'decrease']:
        return jsonify({"success": False, "message": "Invalid request"}), 400

    if 'cart' not in session or cart_key not in session['cart']:
        return jsonify({"success": False, "message": "Item not found in cart"}), 404

    item_in_cart = session['cart'][cart_key]
    current_quantity = item_in_cart['quantity']

    if action == 'increase':
        item_in_cart['quantity'] += 1
    elif action == 'decrease':
        if current_quantity > 1:
            item_in_cart['quantity'] -= 1
        else:
            # If quantity is 1 and decreased, remove the item
            session['cart'].pop(cart_key, None)
            session.modified = True
            flash("Item removed from cart.", "info")
            # If removed, return specific response
            totals = get_cart_totals() # Recalculate totals after removal
            return jsonify({
                "success": True,
                "message": "Item removed from cart.",
                "removed_cart_key": cart_key,
                "totals": totals,
                "cart_empty": not session['cart'] # Indicate if cart is now empty
            })

    session.modified = True

    # After update (or if not removed), recalculate totals and return current item details
    products = load_products()
    product_id = item_in_cart.get('product_id')
    product_info = next((p for p in products if p['id'] == product_id), None)
    
    if product_info:
        item_price = product_info['price']
        new_item_subtotal = item_price * item_in_cart['quantity']
    else:
        # This case should ideally not happen if cart data is consistent with product DB
        item_price = 0
        new_item_subtotal = 0

    totals = get_cart_totals() # Recalculate all cart totals

    return jsonify({
        "success": True,
        "message": "Quantity updated.",
        "cart_key": cart_key,
        "new_quantity": item_in_cart['quantity'],
        "new_item_subtotal": new_item_subtotal,
        "item_price": item_price,
        "totals": totals, # Send updated overall cart totals
        "cart_empty": False # Explicitly state cart is not empty
    })


@app.route('/export_orders_csv')
def export_orders_csv():
    conn = sqlite3.connect('store.db')
    c = conn.cursor()
    c.execute('''
        SELECT id, name, phone, email, governorate, payment, total_price, created_at, status, paymob_transaction_id, paymob_order_id
        FROM orders
        ORDER BY created_at DESC
    ''')
    rows = c.fetchall()
    conn.close()

    # Create CSV response
    si = []
    header = ['Order ID','Name','Phone','Email','Governorate','Payment','Total Price','Created At', 'Status', 'Paymob Transaction ID', 'Paymob Order ID']
    si.append(','.join(header))

    for r in rows:
        si.append(','.join(str(item) for item in r))

    resp = make_response('\n'.join(si))
    resp.headers['Content-Disposition'] = 'attachment; filename=orders.csv'
    resp.headers['Content-Type'] = 'text/csv'
    return resp


@app.route('/faqs')
def faqs():
    conn = sqlite3.connect('store.db')
    c = conn.cursor()
    c.execute('SELECT id, question, answer FROM faqs')
    faqs = [{'id': row[0], 'question': row[1], 'answer': row[2]} for row in c.fetchall()]
    conn.close()
    return render_template('faqs.html', faqs=faqs)

@app.route('/add_faq', methods=['POST'])
def add_faq():
    question = request.form.get('question')
    answer = request.form.get('answer')
    conn = sqlite3.connect('store.db')
    c = conn.cursor()
    c.execute('INSERT INTO faqs (question, answer) VALUES (?, ?)', (question, answer))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/delete_faq/<int:faq_id>', methods=['POST'])
def delete_faq(faq_id):
    conn = sqlite3.connect('store.db')
    c = conn.cursor()
    c.execute('DELETE FROM faqs WHERE id = ?', (faq_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))


# ✅ This must be last
if __name__ == '__main__':
    # Ensure tables are created on app startup
    create_orders_table()
    create_products_table()
    create_faqs_table()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


