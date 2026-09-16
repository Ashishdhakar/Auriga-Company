"""
AV Room Equipment Rental / Management System
----------------------------------------------
A small Flask + SQLite app for a college AV equipment room.

Run with:  python app.py
Then open: http://127.0.0.1:5000
"""

import sqlite3
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, g

app = Flask(__name__)
app.secret_key = "av-room-dev-secret-key"  # fine for a local assessment app

DATABASE = "database.db"

# ---------------------------------------------------------------------------
# CONFIG — easy to tweak
# ---------------------------------------------------------------------------
MAX_UNITS_PER_BORROWER = 5   # max total units a single borrower can hold at once
DATE_FORMAT = "%Y-%m-%d"     # HTML date inputs use this format


# ---------------------------------------------------------------------------
# DATABASE HELPERS
# ---------------------------------------------------------------------------
def get_db():
    """Return a request-scoped SQLite connection (rows behave like dicts)."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables if they don't exist yet, and seed sample equipment."""
    conn = sqlite3.connect(DATABASE)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            total_quantity INTEGER NOT NULL CHECK (total_quantity >= 0),
            available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
            deposit_amount REAL NOT NULL CHECK (deposit_amount >= 0),
            daily_late_fee REAL NOT NULL CHECK (daily_late_fee >= 0),
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS borrowers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            student_id TEXT NOT NULL UNIQUE,
            contact TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS borrowings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            borrower_id INTEGER NOT NULL,
            equipment_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            borrow_date TEXT NOT NULL,
            expected_return_date TEXT NOT NULL,
            actual_return_date TEXT,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'returned')),
            deposit_amount REAL NOT NULL,
            late_fee REAL NOT NULL DEFAULT 0,
            refund_amount REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (borrower_id) REFERENCES borrowers (id),
            FOREIGN KEY (equipment_id) REFERENCES equipment (id)
        )
    """)

    # Seed sample equipment only if the table is empty (first run)
    cur.execute("SELECT COUNT(*) FROM equipment")
    if cur.fetchone()[0] == 0:
        sample_equipment = [
            ("Canon EOS 1500D", "DSLR Camera", 4, 4, 2000.0, 50.0,
             "Entry-level DSLR kit with 18-55mm lens, battery, and charger."),
            ("Epson EB-X41 Projector", "Projector", 3, 3, 3000.0, 75.0,
             "Portable XGA projector with HDMI/VGA cable and remote."),
            ("Boya BY-M1 Lapel Mic", "Microphone", 6, 6, 500.0, 20.0,
             "Clip-on lavalier microphone with 6m cable."),
            ("Manfrotto Tripod", "Tripod", 5, 5, 800.0, 25.0,
             "Aluminium tripod, max height 1.6m, quick-release plate."),
        ]
        cur.executemany("""
            INSERT INTO equipment
                (name, category, total_quantity, available_quantity, deposit_amount, daily_late_fee, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, sample_equipment)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# BUSINESS LOGIC HELPERS
# ---------------------------------------------------------------------------
def parse_date(value):
    """Parse a 'YYYY-MM-DD' string into a date object. Returns None if invalid."""
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except (ValueError, TypeError):
        return None


def overlapping_borrowed_quantity(db, equipment_id, start_date, end_date, exclude_borrowing_id=None):
    """
    Sum of quantities from ACTIVE borrowings of this equipment whose
    [borrow_date, expected_return_date] window overlaps [start_date, end_date].
    This is how we detect booking conflicts for a requested period,
    independent of the equipment's live available_quantity counter.
    """
    query = """
        SELECT COALESCE(SUM(quantity), 0) AS total
        FROM borrowings
        WHERE equipment_id = ?
          AND status = 'active'
          AND borrow_date <= ?
          AND expected_return_date >= ?
    """
    params = [equipment_id, end_date, start_date]
    if exclude_borrowing_id is not None:
        query += " AND id != ?"
        params.append(exclude_borrowing_id)
    row = db.execute(query, params).fetchone()
    return row["total"] or 0


def compute_period_availability(db, equipment, start_date, end_date, exclude_borrowing_id=None):
    """Return the number of free units of `equipment` for the given date window."""
    overlapping = overlapping_borrowed_quantity(
        db, equipment["id"], start_date, end_date, exclude_borrowing_id
    )
    free_units = equipment["total_quantity"] - overlapping
    return max(free_units, 0)


def availability_status(free_units, total_units):
    if free_units <= 0:
        return "Unavailable"
    if free_units < total_units:
        return "Partially Available"
    return "Available"


def borrower_active_units(db, student_id, exclude_borrowing_id=None):
    """Total units a borrower currently has checked out (status='active')."""
    query = """
        SELECT COALESCE(SUM(b.quantity), 0) AS total
        FROM borrowings b
        JOIN borrowers br ON br.id = b.borrower_id
        WHERE br.student_id = ? AND b.status = 'active'
    """
    params = [student_id]
    if exclude_borrowing_id is not None:
        query += " AND b.id != ?"
        params.append(exclude_borrowing_id)
    row = db.execute(query, params).fetchone()
    return row["total"] or 0


def get_or_create_borrower(db, name, student_id, contact):
    row = db.execute("SELECT * FROM borrowers WHERE student_id = ?", (student_id,)).fetchone()
    if row:
        # Keep contact info fresh in case it changed
        db.execute("UPDATE borrowers SET name = ?, contact = ? WHERE id = ?",
                   (name, contact, row["id"]))
        return row["id"]
    cur = db.execute(
        "INSERT INTO borrowers (name, student_id, contact) VALUES (?, ?, ?)",
        (name, student_id, contact)
    )
    return cur.lastrowid


def calculate_late_days(expected_return_date, actual_return_date):
    """Whole days late. 0 if returned on/before the expected date."""
    expected = parse_date(expected_return_date)
    actual = parse_date(actual_return_date)
    if not expected or not actual:
        return 0
    delta = (actual - expected).days
    return max(delta, 0)


def borrowing_row_to_dict(row, today):
    """Enrich a borrowings row (joined with equipment/borrower) with computed fields."""
    d = dict(row)
    expected = parse_date(d["expected_return_date"])
    if d["status"] == "returned":
        d["late_days"] = calculate_late_days(d["expected_return_date"], d["actual_return_date"])
        d["current_late_fee"] = d["late_fee"]
        d["is_overdue"] = d["late_days"] > 0
    else:
        late_days = max((today - expected).days, 0) if expected else 0
        d["late_days"] = late_days
        d["current_late_fee"] = round(late_days * d["daily_late_fee"], 2)
        d["is_overdue"] = late_days > 0
    return d


# ---------------------------------------------------------------------------
# ROUTES — DASHBOARD
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    db = get_db()
    today = date.today()
    today_str = today.strftime(DATE_FORMAT)

    total_items = db.execute("SELECT COALESCE(SUM(total_quantity), 0) AS t FROM equipment").fetchone()["t"]
    available_items = db.execute("SELECT COALESCE(SUM(available_quantity), 0) AS t FROM equipment").fetchone()["t"]
    borrowed_items = db.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS t FROM borrowings WHERE status = 'active'"
    ).fetchone()["t"]
    overdue_count = db.execute(
        "SELECT COUNT(*) AS c FROM borrowings WHERE status = 'active' AND expected_return_date < ?",
        (today_str,)
    ).fetchone()["c"]

    recent_rows = db.execute("""
        SELECT b.*, e.name AS equipment_name, e.daily_late_fee, br.name AS borrower_name, br.student_id
        FROM borrowings b
        JOIN equipment e ON e.id = b.equipment_id
        JOIN borrowers br ON br.id = b.borrower_id
        ORDER BY b.created_at DESC
        LIMIT 8
    """).fetchall()
    recent_activity = [borrowing_row_to_dict(r, today) for r in recent_rows]

    return render_template(
        "index.html",
        total_items=total_items,
        available_items=available_items,
        borrowed_items=borrowed_items,
        overdue_count=overdue_count,
        recent_activity=recent_activity,
    )


# ---------------------------------------------------------------------------
# ROUTES — EQUIPMENT MANAGEMENT
# ---------------------------------------------------------------------------
@app.route("/equipment")
def equipment_list():
    db = get_db()
    items = db.execute("SELECT * FROM equipment ORDER BY category, name").fetchall()
    return render_template("equipment.html", items=items)


@app.route("/equipment/add", methods=["GET", "POST"])
def equipment_add():
    if request.method == "POST":
        error = validate_equipment_form(request.form)
        if error:
            flash(error, "error")
            return render_template("equipment_form.html", mode="add", form=request.form)

        db = get_db()
        total_qty = int(request.form["total_quantity"])
        db.execute("""
            INSERT INTO equipment
                (name, category, total_quantity, available_quantity, deposit_amount, daily_late_fee, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            request.form["name"].strip(),
            request.form["category"].strip(),
            total_qty,
            total_qty,  # available = total when newly added
            float(request.form["deposit_amount"]),
            float(request.form["daily_late_fee"]),
            request.form.get("description", "").strip(),
        ))
        db.commit()
        flash("Equipment added successfully.", "success")
        return redirect(url_for("equipment_list"))

    return render_template("equipment_form.html", mode="add", form={})


@app.route("/equipment/edit/<int:equipment_id>", methods=["GET", "POST"])
def equipment_edit(equipment_id):
    db = get_db()
    item = db.execute("SELECT * FROM equipment WHERE id = ?", (equipment_id,)).fetchone()
    if not item:
        flash("Equipment not found.", "error")
        return redirect(url_for("equipment_list"))

    if request.method == "POST":
        error = validate_equipment_form(request.form)
        if error:
            flash(error, "error")
            return render_template("equipment_form.html", mode="edit", form=request.form, item=item)

        new_total = int(request.form["total_quantity"])
        borrowed_now = item["total_quantity"] - item["available_quantity"]
        if new_total < borrowed_now:
            flash(
                f"Cannot set total quantity below {borrowed_now}, since that many units are currently borrowed.",
                "error"
            )
            return render_template("equipment_form.html", mode="edit", form=request.form, item=item)

        new_available = new_total - borrowed_now
        db.execute("""
            UPDATE equipment
            SET name = ?, category = ?, total_quantity = ?, available_quantity = ?,
                deposit_amount = ?, daily_late_fee = ?, description = ?
            WHERE id = ?
        """, (
            request.form["name"].strip(),
            request.form["category"].strip(),
            new_total,
            new_available,
            float(request.form["deposit_amount"]),
            float(request.form["daily_late_fee"]),
            request.form.get("description", "").strip(),
            equipment_id,
        ))
        db.commit()
        flash("Equipment updated successfully.", "success")
        return redirect(url_for("equipment_list"))

    return render_template("equipment_form.html", mode="edit", form=item, item=item)


@app.route("/equipment/delete/<int:equipment_id>", methods=["POST"])
def equipment_delete(equipment_id):
    db = get_db()
    active = db.execute(
        "SELECT COUNT(*) AS c FROM borrowings WHERE equipment_id = ? AND status = 'active'",
        (equipment_id,)
    ).fetchone()["c"]
    if active > 0:
        flash("Cannot delete equipment with active borrowings. Wait until all units are returned.", "error")
        return redirect(url_for("equipment_list"))

    db.execute("DELETE FROM equipment WHERE id = ?", (equipment_id,))
    db.commit()
    flash("Equipment deleted.", "success")
    return redirect(url_for("equipment_list"))


def validate_equipment_form(form):
    name = form.get("name", "").strip()
    category = form.get("category", "").strip()
    if not name or not category:
        return "Name and category are required."
    try:
        total_qty = int(form.get("total_quantity", ""))
        if total_qty < 0:
            return "Total quantity cannot be negative."
    except ValueError:
        return "Total quantity must be a whole number."
    try:
        deposit = float(form.get("deposit_amount", ""))
        if deposit < 0:
            return "Deposit amount cannot be negative."
    except ValueError:
        return "Deposit amount must be a number."
    try:
        late_fee = float(form.get("daily_late_fee", ""))
        if late_fee < 0:
            return "Daily late fee cannot be negative."
    except ValueError:
        return "Daily late fee must be a number."
    return None


# ---------------------------------------------------------------------------
# ROUTES — AVAILABILITY CHECK
# ---------------------------------------------------------------------------
@app.route("/availability", methods=["GET", "POST"])
def availability():
    db = get_db()
    equipment_list_ = db.execute("SELECT * FROM equipment ORDER BY name").fetchall()
    results = None
    form_data = {}

    if request.method == "POST":
        form_data = request.form
        start = parse_date(request.form.get("start_date", ""))
        end = parse_date(request.form.get("end_date", ""))

        if not start or not end:
            flash("Please provide valid start and end dates.", "error")
        elif end < start:
            flash("End date cannot be before start date.", "error")
        else:
            results = []
            for eq in equipment_list_:
                free_units = compute_period_availability(
                    db, eq, request.form["start_date"], request.form["end_date"]
                )
                results.append({
                    "equipment": eq,
                    "free_units": free_units,
                    "status": availability_status(free_units, eq["total_quantity"]),
                })

    return render_template(
        "availability.html",
        equipment_list=equipment_list_,
        results=results,
        form_data=form_data,
    )


# ---------------------------------------------------------------------------
# ROUTES — BORROW
# ---------------------------------------------------------------------------
@app.route("/borrow", methods=["GET", "POST"])
def borrow():
    db = get_db()
    equipment_list_ = db.execute(
        "SELECT * FROM equipment WHERE total_quantity > 0 ORDER BY name"
    ).fetchall()

    if request.method == "POST":
        form = request.form
        name = form.get("borrower_name", "").strip()
        student_id = form.get("student_id", "").strip()
        contact = form.get("contact", "").strip()
        equipment_id = form.get("equipment_id", "")
        quantity_raw = form.get("quantity", "")
        borrow_date_raw = form.get("borrow_date", "")
        return_date_raw = form.get("expected_return_date", "")
        deposit_override = form.get("deposit_amount", "")

        # --- basic field validation ---
        if not name or not student_id or not contact:
            flash("Borrower name, student ID, and contact are all required.", "error")
            return render_template("borrow.html", equipment_list=equipment_list_, form=form)

        equipment = db.execute("SELECT * FROM equipment WHERE id = ?", (equipment_id,)).fetchone()
        if not equipment:
            flash("Selected equipment does not exist.", "error")
            return render_template("borrow.html", equipment_list=equipment_list_, form=form)

        try:
            quantity = int(quantity_raw)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            flash("Quantity must be a positive whole number.", "error")
            return render_template("borrow.html", equipment_list=equipment_list_, form=form)

        borrow_dt = parse_date(borrow_date_raw)
        return_dt = parse_date(return_date_raw)
        if not borrow_dt or not return_dt:
            flash("Please provide valid borrow and expected return dates.", "error")
            return render_template("borrow.html", equipment_list=equipment_list_, form=form)
        if return_dt < borrow_dt:
            flash("Expected return date cannot be before the borrow date.", "error")
            return render_template("borrow.html", equipment_list=equipment_list_, form=form)

        # --- availability validation (period-based, prevents double-booking) ---
        free_units = compute_period_availability(db, equipment, borrow_date_raw, return_date_raw)
        if quantity > free_units:
            flash(
                f"Only {free_units} unit(s) of '{equipment['name']}' are available for the "
                f"selected period (requested {quantity}).",
                "error"
            )
            return render_template("borrow.html", equipment_list=equipment_list_, form=form)

        # --- borrowing limit validation ---
        current_units = borrower_active_units(db, student_id)
        if current_units + quantity > MAX_UNITS_PER_BORROWER:
            flash(
                f"Borrowing limit exceeded: you already hold {current_units} unit(s); "
                f"the maximum allowed at once is {MAX_UNITS_PER_BORROWER}.",
                "error"
            )
            return render_template("borrow.html", equipment_list=equipment_list_, form=form)

        # --- deposit ---
        try:
            deposit_amount = float(deposit_override) if deposit_override else equipment["deposit_amount"] * quantity
            if deposit_amount < 0:
                raise ValueError
        except ValueError:
            flash("Deposit amount must be a valid non-negative number.", "error")
            return render_template("borrow.html", equipment_list=equipment_list_, form=form)

        # --- commit the borrowing ---
        borrower_id = get_or_create_borrower(db, name, student_id, contact)
        db.execute("""
            INSERT INTO borrowings
                (borrower_id, equipment_id, quantity, borrow_date, expected_return_date,
                 status, deposit_amount, late_fee)
            VALUES (?, ?, ?, ?, ?, 'active', ?, 0)
        """, (borrower_id, equipment["id"], quantity, borrow_date_raw, return_date_raw, deposit_amount))

        db.execute(
            "UPDATE equipment SET available_quantity = available_quantity - ? WHERE id = ?",
            (quantity, equipment["id"])
        )
        db.commit()
        flash(f"Borrowing recorded: {quantity} x '{equipment['name']}' for {name}.", "success")
        return redirect(url_for("borrowings_history"))

    return render_template("borrow.html", equipment_list=equipment_list_, form={})


# ---------------------------------------------------------------------------
# ROUTES — RETURN
# ---------------------------------------------------------------------------
@app.route("/return/<int:borrowing_id>", methods=["POST"])
def process_return(borrowing_id):
    db = get_db()
    row = db.execute("SELECT * FROM borrowings WHERE id = ?", (borrowing_id,)).fetchone()
    if not row:
        flash("Borrowing record not found.", "error")
        return redirect(url_for("borrowings_history"))
    if row["status"] == "returned":
        flash("This item has already been returned.", "error")
        return redirect(url_for("borrowings_history"))

    equipment = db.execute("SELECT * FROM equipment WHERE id = ?", (row["equipment_id"],)).fetchone()

    actual_return_date = request.form.get("actual_return_date") or date.today().strftime(DATE_FORMAT)
    actual_dt = parse_date(actual_return_date)
    borrow_dt = parse_date(row["borrow_date"])
    if not actual_dt:
        flash("Invalid actual return date.", "error")
        return redirect(url_for("borrowings_history"))
    if actual_dt < borrow_dt:
        flash("Actual return date cannot be before the borrow date.", "error")
        return redirect(url_for("borrowings_history"))

    late_days = calculate_late_days(row["expected_return_date"], actual_return_date)
    late_fee = round(late_days * equipment["daily_late_fee"], 2)
    refund_amount = max(round(row["deposit_amount"] - late_fee, 2), 0)

    db.execute("""
        UPDATE borrowings
        SET status = 'returned', actual_return_date = ?, late_fee = ?, refund_amount = ?
        WHERE id = ?
    """, (actual_return_date, late_fee, refund_amount, borrowing_id))

    db.execute(
        "UPDATE equipment SET available_quantity = available_quantity + ? WHERE id = ?",
        (row["quantity"], equipment["id"])
    )
    db.commit()

    if late_days > 0:
        flash(
            f"Returned {late_days} day(s) late. Late fee: Rs.{late_fee:.2f}. Refund: Rs.{refund_amount:.2f}.",
            "success"
        )
    else:
        flash(f"Returned on time. Full deposit refunded: Rs.{refund_amount:.2f}.", "success")
    return redirect(url_for("borrowings_history"))


# ---------------------------------------------------------------------------
# ROUTES — BORROWING HISTORY / OVERDUE
# ---------------------------------------------------------------------------
@app.route("/borrowings")
def borrowings_history():
    db = get_db()
    status_filter = request.args.get("status", "all")
    today = date.today()
    today_str = today.strftime(DATE_FORMAT)

    query = """
        SELECT b.*, e.name AS equipment_name, e.daily_late_fee,
               br.name AS borrower_name, br.student_id, br.contact
        FROM borrowings b
        JOIN equipment e ON e.id = b.equipment_id
        JOIN borrowers br ON br.id = b.borrower_id
    """
    params = []
    if status_filter == "active":
        query += " WHERE b.status = 'active'"
    elif status_filter == "returned":
        query += " WHERE b.status = 'returned'"
    elif status_filter == "overdue":
        query += " WHERE b.status = 'active' AND b.expected_return_date < ?"
        params.append(today_str)

    query += " ORDER BY b.created_at DESC"
    rows = db.execute(query, params).fetchall()
    records = [borrowing_row_to_dict(r, today) for r in rows]

    return render_template("borrowings.html", records=records, status_filter=status_filter)


# ---------------------------------------------------------------------------
# ERROR HANDLERS
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", message="Page not found."), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", message="Something went wrong on our end. Please try again."), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
