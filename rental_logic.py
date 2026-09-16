"""All business rules for the AV room desk live here, deliberately separate
from Flask, so they can be unit-tested without spinning up a web server.

Design in one paragraph:
Equipment is a "kind" of item with N interchangeable units (e.g. 3 DSLRs).
We never track individual serial numbers -- availability on any given day is
just: total_units - (number of active loans whose [borrowed_at, due_date]
window covers that day). Deposits and late fees are per-equipment so a
camera can have a bigger deposit than a mic. A transfer only ever changes
loans.borrower_id; it never touches equipment_id, borrowed_at or due_date,
which is exactly why the due date carries over and availability is
untouched by a transfer.
"""

from datetime import date, datetime, timedelta

DATE_FMT = "%Y-%m-%d"
MAX_ACTIVE_LOANS_PER_BORROWER = 3  # "one person shouldn't book out half the room"


class RentalError(Exception):
    """Raised for any rule violation; the message is safe to show a user."""


def today():
    return date.today()


def parse_date(value):
    if isinstance(value, date):
        return value
    return datetime.strptime(value, DATE_FMT).date()


# ---------------------------------------------------------------- lookups --

def get_equipment(conn, equipment_id):
    row = conn.execute("SELECT * FROM equipment WHERE id=?", (equipment_id,)).fetchone()
    if not row:
        raise RentalError("No such equipment.")
    return row


def get_borrower(conn, borrower_id):
    row = conn.execute("SELECT * FROM borrowers WHERE id=?", (borrower_id,)).fetchone()
    if not row:
        raise RentalError("No such borrower.")
    return row


# ------------------------------------------------------------- availability --

def units_committed_on(conn, equipment_id, on_date):
    """How many units of this equipment are out (or booked out) on a given day."""
    d = on_date.strftime(DATE_FMT)
    row = conn.execute(
        """SELECT COUNT(*) AS c FROM loans
           WHERE equipment_id = ? AND status = 'active'
             AND date(borrowed_at) <= date(?) AND date(due_date) >= date(?)""",
        (equipment_id, d, d),
    ).fetchone()
    return row["c"]


def available_units_on(conn, equipment_id, on_date):
    eq = get_equipment(conn, equipment_id)
    return eq["total_units"] - units_committed_on(conn, equipment_id, on_date)


def is_available_for_range(conn, equipment_id, start_date, end_date):
    """True only if at least one unit is free on *every* day in the range --
    this is what answers 'is a DSLR free this weekend?' properly, instead of
    just checking today."""
    d = start_date
    while d <= end_date:
        if available_units_on(conn, equipment_id, d) < 1:
            return False, d
        d += timedelta(days=1)
    return True, None


def active_loan_count(conn, borrower_id):
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM loans WHERE borrower_id = ? AND status = 'active'",
        (borrower_id,),
    ).fetchone()
    return row["c"]


# ------------------------------------------------------------------ borrow --

def create_loan(conn, equipment_id, borrower_id, loan_days=None):
    eq = get_equipment(conn, equipment_id)
    borrower = get_borrower(conn, borrower_id)

    borrowed_at = today()
    days = loan_days if loan_days else eq["default_loan_days"]
    if days <= 0:
        raise RentalError("Loan length must be at least 1 day.")
    due_date = borrowed_at + timedelta(days=days)

    ok, bad_day = is_available_for_range(conn, equipment_id, borrowed_at, due_date)
    if not ok:
        raise RentalError(f"No '{eq['name']}' units free on {bad_day}.")

    if active_loan_count(conn, borrower_id) >= MAX_ACTIVE_LOANS_PER_BORROWER:
        raise RentalError(
            f"{borrower['name']} already has {MAX_ACTIVE_LOANS_PER_BORROWER} "
            f"active loans -- return something before borrowing more."
        )

    deposit = eq["deposit_amount"]
    cur = conn.execute(
        """INSERT INTO loans (equipment_id, borrower_id, borrowed_at, due_date,
                               deposit_paid, status)
           VALUES (?, ?, ?, ?, ?, 'active')""",
        (
            equipment_id,
            borrower_id,
            borrowed_at.strftime(DATE_FMT),
            due_date.strftime(DATE_FMT),
            deposit,
        ),
    )
    conn.commit()
    return cur.lastrowid


# ------------------------------------------------------------------ return --

def return_loan(conn, loan_id, returned_on=None):
    loan = conn.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
    if not loan:
        raise RentalError("No such loan.")
    if loan["status"] != "active":
        raise RentalError("This loan is already closed.")

    returned_on = returned_on or today()
    due = parse_date(loan["due_date"])
    late_days = max(0, (returned_on - due).days)

    eq = get_equipment(conn, loan["equipment_id"])
    late_fee = round(late_days * eq["late_fee_per_day"], 2)
    refund = max(0.0, round(loan["deposit_paid"] - late_fee, 2))

    conn.execute(
        """UPDATE loans
           SET status='returned', returned_at=?, late_fee_charged=?, deposit_refunded=?
           WHERE id=?""",
        (returned_on.strftime(DATE_FMT), late_fee, refund, loan_id),
    )
    conn.commit()
    return {"late_days": late_days, "late_fee": late_fee, "deposit_refunded": refund}


# ---------------------------------------------------------------- transfer --

def transfer_loan(conn, loan_id, to_borrower_id):
    """Move an active loan to a new borrower.

    Deliberately the ONLY thing this changes is loans.borrower_id:
    - due_date is untouched -> it carries over unchanged.
    - equipment_id / borrowed_at are untouched -> availability, which is
      computed purely from equipment_id + the date window, is unaffected.
    """
    loan = conn.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
    if not loan:
        raise RentalError("No such loan.")
    if loan["status"] != "active":
        raise RentalError("Only an active loan can be transferred.")
    if loan["borrower_id"] == to_borrower_id:
        raise RentalError("That borrower already has this item.")

    to_borrower = get_borrower(conn, to_borrower_id)
    if active_loan_count(conn, to_borrower_id) >= MAX_ACTIVE_LOANS_PER_BORROWER:
        raise RentalError(
            f"{to_borrower['name']} already has {MAX_ACTIVE_LOANS_PER_BORROWER} active loans."
        )

    conn.execute(
        """INSERT INTO transfers (loan_id, from_borrower_id, to_borrower_id, transferred_at)
           VALUES (?, ?, ?, ?)""",
        (loan_id, loan["borrower_id"], to_borrower_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.execute("UPDATE loans SET borrower_id=? WHERE id=?", (to_borrower_id, loan_id))
    conn.commit()


# ------------------------------------------------------------------ nudges --

def overdue_loans(conn, on_date=None):
    on_date = on_date or today()
    return conn.execute(
        """SELECT loans.*, equipment.name AS equipment_name,
                  borrowers.name AS borrower_name, borrowers.contact AS borrower_contact
           FROM loans
           JOIN equipment ON equipment.id = loans.equipment_id
           JOIN borrowers ON borrowers.id = loans.borrower_id
           WHERE loans.status='active' AND date(loans.due_date) < date(?)
           ORDER BY loans.due_date""",
        (on_date.strftime(DATE_FMT),),
    ).fetchall()


def due_soon_loans(conn, within_days=1, on_date=None):
    on_date = on_date or today()
    limit = on_date + timedelta(days=within_days)
    return conn.execute(
        """SELECT loans.*, equipment.name AS equipment_name,
                  borrowers.name AS borrower_name, borrowers.contact AS borrower_contact
           FROM loans
           JOIN equipment ON equipment.id = loans.equipment_id
           JOIN borrowers ON borrowers.id = loans.borrower_id
           WHERE loans.status='active'
             AND date(loans.due_date) >= date(?) AND date(loans.due_date) <= date(?)
           ORDER BY loans.due_date""",
        (on_date.strftime(DATE_FMT), limit.strftime(DATE_FMT)),
    ).fetchall()


def reminder_messages(conn, on_date=None):
    """Plain-English nudge lines -- this is what a cron job / WhatsApp bot
    would send each morning. Kept as data so app.py can also show it on the
    dashboard instead of duplicating the wording."""
    on_date = on_date or today()
    messages = []
    for loan in overdue_loans(conn, on_date):
        days_late = (on_date - parse_date(loan["due_date"])).days
        messages.append(
            f"OVERDUE: {loan['borrower_name']}, your {loan['equipment_name']} "
            f"was due {loan['due_date']} ({days_late} day(s) ago). "
            f"Late fee is accruing -- please return it."
        )
    for loan in due_soon_loans(conn, within_days=1, on_date=on_date):
        messages.append(
            f"REMINDER: {loan['borrower_name']}, your {loan['equipment_name']} "
            f"is due back on {loan['due_date']}."
        )
    return messages
