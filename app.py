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

def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def init_db():
    """Create the database and a bootstrap admin account on first boot.
    Safe to call on every startup — it's a no-op once the file exists."""
    if os.path.exists(DB_PATH):
        return
    conn = sqlite3.connect(DB_PATH)
