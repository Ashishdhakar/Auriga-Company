-- Equipment: a "kind" of item (e.g. "Canon DSLR") that may have several
-- interchangeable physical units. We never track individual serial numbers;
-- availability is derived by counting active loans against total_units.
CREATE TABLE IF NOT EXISTS equipment (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    category            TEXT,
    total_units         INTEGER NOT NULL DEFAULT 1 CHECK (total_units > 0),
    deposit_amount      REAL NOT NULL DEFAULT 500,
    late_fee_per_day    REAL NOT NULL DEFAULT 10,
    default_loan_days   INTEGER NOT NULL DEFAULT 3
);

CREATE TABLE IF NOT EXISTS borrowers (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    contact  TEXT
);

-- One row per physical checkout. status is 'active' until returned.
CREATE TABLE IF NOT EXISTS loans (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id       INTEGER NOT NULL REFERENCES equipment(id),
    borrower_id        INTEGER NOT NULL REFERENCES borrowers(id),
    borrowed_at        TEXT NOT NULL,          -- date, YYYY-MM-DD
    due_date           TEXT NOT NULL,          -- date, YYYY-MM-DD
    returned_at        TEXT,                   -- date, set on return
    deposit_paid       REAL NOT NULL,
    late_fee_charged   REAL DEFAULT 0,
    deposit_refunded   REAL,
    status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','returned'))
);

-- Audit trail of borrower-to-borrower transfers of an active loan.
-- The loan row itself is updated in place (borrower_id changes); this table
-- just remembers who had it before, for accountability.
CREATE TABLE IF NOT EXISTS transfers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id           INTEGER NOT NULL REFERENCES loans(id),
    from_borrower_id  INTEGER NOT NULL REFERENCES borrowers(id),
    to_borrower_id    INTEGER NOT NULL REFERENCES borrowers(id),
    transferred_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_loans_equipment ON loans(equipment_id);
CREATE INDEX IF NOT EXISTS idx_loans_borrower ON loans(borrower_id);
CREATE INDEX IF NOT EXISTS idx_loans_status ON loans(status);
