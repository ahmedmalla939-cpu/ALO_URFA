"""
Delivery Order Management System — REST API
Framework: Flask (kept dependency-free — no internet access in this sandbox
to install FastAPI/uvicorn, but the endpoint design below is framework-agnostic
and ports directly to FastAPI/Express later if needed).
"""
import sqlite3
import hashlib
import secrets
import functools
import os
from flask import Flask, request, jsonify, g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "delivery.db"))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

app = Flask(__name__)

@app.route("/")
def serve_frontend():
    from flask import send_from_directory
    return send_from_directory(BASE_DIR, "index.html")

def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def init_db():
    """Create the database and a bootstrap admin account on first boot.
    Safe to call on every startup — it's a no-op once the file exists."""
    if os.path.exists(DB_PATH):
        return
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(open(SCHEMA_PATH, encoding="utf-8").read())

    admin_phone = os.environ.get("ADMIN_PHONE", "0900000000")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    salt = secrets.token_hex(8)
    pwd_hash = hash_password(admin_password, salt)
    conn.execute(
        "INSERT INTO users (name, phone, password_hash, password_salt, role) VALUES (?,?,?,?, 'admin')",
        ("المدير", admin_phone, pwd_hash, salt),
    )
    conn.commit()
    conn.close()
    print(f"[init] new database created at {DB_PATH}")
    print(f"[init] bootstrap admin account -> phone: {admin_phone} / password: {admin_password}")
    print("[init] log in as admin and use the 'الموظفون' / 'السائقون' tabs to create the rest of the accounts.")

init_db()

# ---------------------------------------------------------------
# CORS (the front-end runs on a different origin)
# ---------------------------------------------------------------
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
    return resp

@app.route("/api/<path:_any>", methods=["OPTIONS"])
def cors_preflight(_any):
    return "", 204

# ---------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def row_to_dict(row):
    return dict(row) if row else None

# ---------------------------------------------------------------
# Auth — simple bearer-token sessions kept in memory.
# NOTE: a real deployment should use JWT or a persisted session
# store (Redis) so tokens survive a server restart / scale-out.
# ---------------------------------------------------------------
SESSIONS = {}  # token -> {"user_id": int, "role": str}

def issue_token(user_id, role):
    token = secrets.token_hex(24)
    SESSIONS[token] = {"user_id": user_id, "role": role}
    return token

def require_auth(*allowed_roles):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            token = auth.replace("Bearer ", "").strip()
            session = SESSIONS.get(token)
            if not session:
                return jsonify({"error": "unauthorized"}), 401
            if allowed_roles and session["role"] not in allowed_roles:
                return jsonify({"error": "forbidden"}), 403
            g.user_id = session["user_id"]
            g.role = session["role"]
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# ---------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------
@app.post("/api/auth/login")
def login():
    body = request.get_json(force=True) or {}
    phone, password = body.get("phone"), body.get("password")
    if not phone or not password:
        return jsonify({"error": "phone and password are required"}), 400

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE phone = ? AND is_active = 1", (phone,)).fetchone()
    if not user or hash_password(password, user["password_salt"]) != user["password_hash"]:
        return jsonify({"error": "invalid credentials"}), 401

    token = issue_token(user["id"], user["role"])
    return jsonify({
        "token": token,
        "user": {"id": user["id"], "name": user["name"], "role": user["role"]},
    })

@app.post("/api/auth/logout")
@require_auth()
def logout():
    auth = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    SESSIONS.pop(auth, None)
    return jsonify({"ok": True})

# ---------------------------------------------------------------
# ORDERS
# ---------------------------------------------------------------
@app.post("/api/orders")
@require_auth("employee", "admin")
def create_order():
    body = request.get_json(force=True) or {}
    required = ["customer_name", "customer_phone", "address", "amount"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400

    order_code = "ORD-" + secrets.token_hex(3).upper()
    db = get_db()
    cur = db.execute(
        """INSERT INTO orders (order_code, customer_name, customer_phone, address, items, amount, currency, status, created_by)
           VALUES (?,?,?,?,?,?, 'TRY', 'NEW', ?)""",
        (order_code, body["customer_name"], body["customer_phone"], body["address"],
         body.get("items", ""), body["amount"], g.user_id),
    )
    db.commit()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(row_to_dict(order)), 201

@app.get("/api/orders/available")
@require_auth("driver")
def available_orders():
    db = get_db()
    rows = db.execute("SELECT * FROM v_available_orders").fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/orders/mine")
@require_auth("driver")
def my_orders():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM orders WHERE driver_id = ? ORDER BY created_at DESC", (g.user_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/orders/<int:order_id>/claim")
@require_auth("driver")
def claim_order(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        return jsonify({"error": "order not found"}), 404
    if order["status"] != "NEW" or order["driver_id"] is not None:
        return jsonify({"error": "order already claimed"}), 409

    driver = db.execute("SELECT status FROM driver_profiles WHERE user_id = ?", (g.user_id,)).fetchone()
    if not driver or driver["status"] == "OFFLINE":
        return jsonify({"error": "you must be online to claim orders"}), 403

    db.execute("UPDATE orders SET status='ASSIGNED', driver_id=? WHERE id=?", (g.user_id, order_id))
    db.execute("UPDATE driver_profiles SET status='BUSY', updated_at=datetime('now') WHERE user_id=?", (g.user_id,))
    db.commit()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return jsonify(dict(order))

NEXT_STATUS = {"ASSIGNED": "PICKED_UP", "PICKED_UP": "ON_WAY", "ON_WAY": "DELIVERED"}

@app.post("/api/orders/<int:order_id>/advance")
@require_auth("driver")
def advance_order(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        return jsonify({"error": "order not found"}), 404
    if order["driver_id"] != g.user_id:
        return jsonify({"error": "this order is not assigned to you"}), 403
    nxt = NEXT_STATUS.get(order["status"])
    if not nxt:
        return jsonify({"error": f"cannot advance from status {order['status']}"}), 409

    db.execute("UPDATE orders SET status=? WHERE id=?", (nxt, order_id))
    if nxt == "DELIVERED":
        db.execute("UPDATE driver_profiles SET status='AVAILABLE', updated_at=datetime('now') WHERE user_id=?", (g.user_id,))
    db.commit()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return jsonify(dict(order))

@app.post("/api/orders/<int:order_id>/cancel")
@require_auth("employee", "admin")
def cancel_order(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        return jsonify({"error": "order not found"}), 404
    if order["status"] in ("DELIVERED", "CANCELLED"):
        return jsonify({"error": f"cannot cancel a {order['status']} order"}), 409
    db.execute("UPDATE orders SET status='CANCELLED' WHERE id=?", (order_id,))
    db.commit()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return jsonify(dict(order))

@app.get("/api/orders/created")
@require_auth("employee", "admin")
def orders_created_by_me():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM orders WHERE created_by = ? ORDER BY created_at DESC", (g.user_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/orders")
@require_auth("admin")
def list_orders():
    status = request.args.get("status")
    db = get_db()
    if status:
        rows = db.execute("SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/orders/<int:order_id>/history")
@require_auth("admin")
def order_history(order_id):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM order_status_history WHERE order_id = ? ORDER BY id", (order_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/employees")
@require_auth("admin")
def list_employees():
    db = get_db()
    rows = db.execute(
        """SELECT u.id AS employee_id, u.name AS employee_name, u.phone,
                  COUNT(o.id) AS orders_created
           FROM users u
           LEFT JOIN orders o ON o.created_by = u.id
           WHERE u.role = 'employee'
           GROUP BY u.id"""
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/employees")
@require_auth("admin")
def add_employee():
    body = request.get_json(force=True) or {}
    name, phone, password = body.get("name"), body.get("phone"), body.get("password", "1234")
    if not name or not phone:
        return jsonify({"error": "name and phone are required"}), 400

    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE phone = ?", (phone,)).fetchone():
        return jsonify({"error": "phone already registered"}), 409

    salt = secrets.token_hex(8)
    pwd_hash = hash_password(password, salt)
    cur = db.execute(
        "INSERT INTO users (name, phone, password_hash, password_salt, role) VALUES (?,?,?,?, 'employee')",
        (name, phone, pwd_hash, salt),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid, "name": name, "phone": phone}), 201

# ---------------------------------------------------------------
# DRIVERS
# ---------------------------------------------------------------
@app.get("/api/drivers/me")
@require_auth("driver")
def my_driver_profile():
    db = get_db()
    row = db.execute(
        "SELECT u.id, u.name, dp.status FROM users u JOIN driver_profiles dp ON dp.user_id = u.id WHERE u.id = ?",
        (g.user_id,),
    ).fetchone()
    return jsonify(dict(row))

@app.get("/api/drivers")
@require_auth("admin")
def list_drivers():
    db = get_db()
    rows = db.execute("SELECT * FROM v_driver_stats").fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/drivers")
@require_auth("admin")
def add_driver():
    body = request.get_json(force=True) or {}
    name, phone, password = body.get("name"), body.get("phone"), body.get("password", "1234")
    if not name or not phone:
        return jsonify({"error": "name and phone are required"}), 400

    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE phone = ?", (phone,)).fetchone():
        return jsonify({"error": "phone already registered"}), 409

    salt = secrets.token_hex(8)
    pwd_hash = hash_password(password, salt)
    cur = db.execute(
        "INSERT INTO users (name, phone, password_hash, password_salt, role) VALUES (?,?,?,?, 'driver')",
        (name, phone, pwd_hash, salt),
    )
    driver_id = cur.lastrowid
    db.execute("INSERT INTO driver_profiles (user_id, status) VALUES (?, 'AVAILABLE')", (driver_id,))
    db.commit()
    return jsonify({"id": driver_id, "name": name, "phone": phone, "status": "AVAILABLE"}), 201

@app.patch("/api/drivers/<int:driver_id>/status")
@require_auth("driver", "admin")
def set_driver_status(driver_id):
    if g.role == "driver" and g.user_id != driver_id:
        return jsonify({"error": "drivers can only update their own status"}), 403
    body = request.get_json(force=True) or {}
    status = body.get("status")
    if status not in ("AVAILABLE", "BUSY", "OFFLINE"):
        return jsonify({"error": "invalid status"}), 400
    db = get_db()
    db.execute("UPDATE driver_profiles SET status=?, updated_at=datetime('now') WHERE user_id=?", (status, driver_id))
    db.commit()
    return jsonify({"id": driver_id, "status": status})

# ---------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------
@app.get("/api/dashboard/summary")
@require_auth("admin")
def dashboard_summary():
    db = get_db()
    row = db.execute("SELECT * FROM v_dashboard_summary").fetchone()
    return jsonify(dict(row))

@app.get("/api/health")
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5055))
    app.run(host="0.0.0.0", port=port, debug=False)
