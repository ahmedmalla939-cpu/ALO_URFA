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
                 CHECK (status IN ('AVAILABLE', 'BUSY', 'OFFLINE')),
    vehicle_type TEXT,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_driver_profiles_status ON driver_profiles(status);

-- ---------------------------------------------------------------
-- orders
-- ---------------------------------------------------------------
CREATE TABLE orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    order_code     TEXT NOT NULL UNIQUE,        -- e.g. ORD-A1B2C3
    customer_name  TEXT NOT NULL,
    customer_phone TEXT NOT NULL,
    address        TEXT NOT NULL,
    items          TEXT,                        -- free text description of the order contents
    amount         NUMERIC NOT NULL CHECK (amount >= 0),
    currency       TEXT NOT NULL DEFAULT 'TRY',
    status         TEXT NOT NULL DEFAULT 'NEW'
                   CHECK (status IN ('NEW','ASSIGNED','PICKED_UP','ON_WAY','DELIVERED','CANCELLED')),
    created_by     INTEGER NOT NULL REFERENCES users(id),   -- the employee who created it
    driver_id      INTEGER REFERENCES users(id),            -- NULL while sitting in the available pool
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_orders_status    ON orders(status);
CREATE INDEX idx_orders_driver_id ON orders(driver_id);
CREATE INDEX idx_orders_created_by ON orders(created_by);

-- ---------------------------------------------------------------
-- order_status_history: full audit trail of every transition
-- ---------------------------------------------------------------
CREATE TABLE order_status_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status     TEXT NOT NULL,
    changed_by INTEGER REFERENCES users(id),
    changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_history_order_id ON order_status_history(order_id);

-- ---------------------------------------------------------------
-- Trigger: keep orders.updated_at fresh on every UPDATE
-- ---------------------------------------------------------------
CREATE TRIGGER trg_orders_updated_at
AFTER UPDATE ON orders
FOR EACH ROW
BEGIN
    UPDATE orders SET updated_at = datetime('now') WHERE id = OLD.id;
END;

-- ---------------------------------------------------------------
-- Trigger: auto-log every status change into the history table
-- ---------------------------------------------------------------
CREATE TRIGGER trg_orders_status_history
AFTER UPDATE OF status ON orders
FOR EACH ROW
WHEN OLD.status IS NOT NEW.status
BEGIN
    INSERT INTO order_status_history (order_id, status, changed_by)
    VALUES (NEW.id, NEW.status, NEW.driver_id);
END;

-- ---------------------------------------------------------------
-- Trigger: log the initial status when an order is first created
-- ---------------------------------------------------------------
CREATE TRIGGER trg_orders_status_history_insert
AFTER INSERT ON orders
FOR EACH ROW
BEGIN
    INSERT INTO order_status_history (order_id, status, changed_by)
    VALUES (NEW.id, NEW.status, NEW.created_by);
END;

-- ---------------------------------------------------------------
-- Helpful views
-- ---------------------------------------------------------------

-- Orders currently waiting in the pool (visible to every online driver)
CREATE VIEW v_available_orders AS
SELECT * FROM orders
WHERE status = 'NEW' AND driver_id IS NULL
ORDER BY created_at ASC;

-- Admin dashboard summary
CREATE VIEW v_dashboard_summary AS
SELECT
    COUNT(*)                                              AS total_orders,
    SUM(CASE WHEN status = 'DELIVERED' THEN 1 ELSE 0 END) AS delivered_count,
    SUM(CASE WHEN status NOT IN ('DELIVERED','CANCELLED') THEN 1 ELSE 0 END) AS pending_count,
    SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) AS cancelled_count,
    COALESCE(SUM(CASE WHEN status = 'DELIVERED' THEN amount ELSE 0 END), 0) AS revenue_collected
FROM orders;

-- Per-driver performance
CREATE VIEW v_driver_stats AS
SELECT
    u.id                                                   AS driver_id,
    u.name                                                 AS driver_name,
    dp.status                                               AS current_status,
    SUM(CASE WHEN o.status NOT IN ('DELIVERED','CANCELLED') THEN 1 ELSE 0 END) AS active_orders,
    SUM(CASE WHEN o.status = 'DELIVERED' THEN 1 ELSE 0 END) AS delivered_orders
FROM users u
JOIN driver_profiles dp ON dp.user_id = u.id
LEFT JOIN orders o ON o.driver_id = u.id
WHERE u.role = 'driver'
GROUP BY u.id;
