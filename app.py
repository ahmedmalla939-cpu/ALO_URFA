import sqlite3
import hashlib
import secrets
import os
from flask import Flask, request, jsonify, g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "delivery.db"))

app = Flask(__name__)

def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # إنشاء جدول المستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT NOT NULL
        )
    ''')
    
    # إنشاء جدول الطلبات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT,
            phone TEXT,
            address TEXT,
            details TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # إنشاء جدول الجلسات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL
        )
    ''')
    
    # إضافة حساب المدير إذا لم يكن موجوداً
    admin_phone = os.environ.get("ADMIN_PHONE", "05300000000")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    
    cursor.execute("SELECT id FROM users WHERE phone = ?", (admin_phone,))
    if not cursor.fetchone():
        salt = secrets.token_hex(16)
        hashed = hash_password(admin_password, salt)
        cursor.execute(
            "INSERT INTO users (phone, password_hash, salt, role, name) VALUES (?, ?, ?, 'admin', 'System Admin')",
            (admin_phone, hashed, salt)
        )
        
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

@app.route('/')
def home():
    return jsonify({"status": "online", "message": "ALO_URFA API is running"}), 200

@app.route('/api/ping')
def ping():
    return jsonify({"status": "ok"}), 200

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    phone = data.get('phone')
    password = data.get('password')
    
    if not phone or not password:
        return jsonify({"error": "Missing phone or password"}), 400
        
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
    
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401
        
    hashed_input = hash_password(password, user['salt'])
    if hashed_input != user['password_hash']:
        return jsonify({"error": "Invalid credentials"}), 401
        
    token = secrets.token_hex(32)
    db.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user['id']))
    db.commit()
    
    return jsonify({
        "token": token,
        "role": user['role'],
        "name": user['name']
    }), 200

@app.route('/api/orders', methods=['GET', 'POST'])
def handle_orders():
    db = get_db()
    if request.method == 'POST':
        data = request.get_json() or {}
        db.execute(
            "INSERT INTO orders (customer_name, phone, address, details, status) VALUES (?, ?, ?, ?, 'pending')",
            (data.get('customer_name'), data.get('phone'), data.get('address'), data.get('details'))
        )
        db.commit()
        return jsonify({"message": "Order created successfully"}), 201
    else:
        orders = db.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
        return jsonify([dict(order) for order in orders]), 200
