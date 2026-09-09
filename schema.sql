-- ============================================================
-- Delivery Order Management System — Database Schema (SQLite)
-- ============================================================
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------
-- users: every person who logs in (admin / employee / driver)
-- ---------------------------------------------------------------
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    phone         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'employee', 'driver')),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_users_role ON users(role);

-- ---------------------------------------------------------------
-- driver_profiles: extra data that only applies to drivers
-- (1-to-1 with users, kept separate so users stays generic)
-- ---------------------------------------------------------------
CREATE TABLE driver_profiles (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'OFFLINE'
