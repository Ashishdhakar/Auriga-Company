from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import date, datetime
from pathlib import Path

app = Flask(__name__)
app.secret_key = "equipment-rental-assessment"
DB = Path(__file__).with_name("equipment.db")

# Easy-to-change business rules
MAX_BORROWED_UNITS = 3
DEFAULT_MIN_BORROW_DAYS = 1
DEFAULT_MAX_BORROW_DAYS = 14

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        total_quantity INTEGER NOT NULL CHECK(total_quantity > 0),
        available_quantity INTEGER NOT NULL CHECK(available_quantity >= 0),
        deposit REAL NOT NULL DEFAULT 0,
        late_fee REAL NOT NULL DEFAULT 0,
        description TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS borrowers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        student_id TEXT NOT NULL UNIQUE,
        contact TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS borrowings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        borrower_id INTEGER NOT NULL,
        equipment_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        borrow_date TEXT NOT NULL,
        due_date TEXT NOT NULL,
        actual_return_date TEXT,
        deposit REAL NOT NULL DEFAULT 0,
        late_fee REAL NOT NULL DEFAULT 0,
        refund_amount REAL,
        status TEXT NOT NULL DEFAULT 'Active'
            CHECK(status IN ('Active','Returned','Cancelled')),
        FOREIGN KEY(borrower_id) REFERENCES borrowers(id),
        FOREIGN KEY(equipment_id) REFERENCES equipment(id)
    );
    """)
    if conn.execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 0:
        conn.executemany("""
            INSERT INTO equipment
            (name, category, total_quantity, available_quantity, deposit, late_fee, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            ("DSLR Camera", "Camera", 3, 3, 2000, 100, "College DSLR camera kit"),
            ("Projector", "Display", 2, 2, 1500, 100, "HD classroom projector"),
            ("Wireless Microphone", "Audio", 5, 5, 500, 50, "Wireless microphone"),
            ("Tripod", "Accessory", 4, 4, 300, 30, "Camera tripod")
        ])
    conn.commit()
    conn.close()

def parse_day(value):
    return datetime.strptime(value, "%Y-%m-%d").date()

def overlapping_units(conn, equipment_id, start_date, end_date):
    """Count units already reserved during an inclusive date range."""
    row = conn.execute("""
        SELECT COALESCE(SUM(quantity), 0) AS units
        FROM borrowings
        WHERE equipment_id=?
          AND status='Active'
          AND borrow_date <= ?
          AND due_date >= ?
    """, (equipment_id, end_date.isoformat(), start_date.isoformat())).fetchone()
    return row["units"]

def available_for_period(conn, equipment_id, start_date, end_date):
    item = conn.execute("SELECT * FROM equipment WHERE id=?", (equipment_id,)).fetchone()
    if not item:
        return None
    reserved = overlapping_units(conn, equipment_id, start_date, end_date)
    return max(0, item["total_quantity"] - reserved)

def reminder(row):
    due = parse_day(row["due_date"])
    today = date.today()
    days = (due - today).days
    if days < 0:
        return f"{abs(days)} day(s) overdue", "danger", abs(days)
    if days == 0:
        return "Due today", "warning", 0
    if days == 1:
        return "Due tomorrow", "warning", 1
    if days <= 3:
        return f"Due in {days} days", "warning", days
    return f"Due in {days} days", "ok", days

@app.context_processor
def globals_for_templates():
    return {
        "today": date.today().isoformat(),
        "max_borrowed_units": MAX_BORROWED_UNITS,
        "max_borrow_days": DEFAULT_MAX_BORROW_DAYS
    }

@app.route("/")
def index():
    conn = db()
    stats = {
        "equipment": conn.execute("SELECT COALESCE(SUM(total_quantity),0) FROM equipment").fetchone()[0],
        "available": conn.execute("SELECT COALESCE(SUM(available_quantity),0) FROM equipment").fetchone()[0],
        "borrowed": conn.execute("SELECT COALESCE(SUM(quantity),0) FROM borrowings WHERE status='Active'").fetchone()[0],
        "overdue": conn.execute("""
            SELECT COUNT(*) FROM borrowings
            WHERE status='Active' AND due_date < ?
        """, (date.today().isoformat(),)).fetchone()[0]
    }

    reminders = conn.execute("""
        SELECT b.*, br.name AS borrower_name, br.student_id,
               e.name AS equipment_name, e.late_fee AS daily_late_fee
        FROM borrowings b
        JOIN borrowers br ON br.id=b.borrower_id
        JOIN equipment e ON e.id=b.equipment_id
        WHERE b.status='Active'
        ORDER BY b.due_date ASC
    """).fetchall()

    recent = conn.execute("""
        SELECT b.*, br.name AS borrower_name, e.name AS equipment_name
        FROM borrowings b
        JOIN borrowers br ON br.id=b.borrower_id
        JOIN equipment e ON e.id=b.equipment_id
        ORDER BY b.id DESC LIMIT 6
    """).fetchall()

    conn.close()
    return render_template(
        "index.html",
        stats=stats,
        reminders=[(r, *reminder(r)) for r in reminders],
        recent=recent
    )

@app.route("/equipment")
def equipment():
    conn = db()
    rows = conn.execute("SELECT * FROM equipment ORDER BY name").fetchall()
    conn.close()
    return render_template("equipment.html", equipment=rows)

@app.route("/equipment/add", methods=["GET", "POST"])
def add_equipment():
    if request.method == "POST":
        try:
            name = request.form["name"].strip()
            category = request.form["category"].strip()
            qty = int(request.form["quantity"])
            deposit = float(request.form.get("deposit", 0))
            late_fee = float(request.form.get("late_fee", 0))
            description = request.form.get("description", "").strip()
            if not name or not category or qty < 1 or deposit < 0 or late_fee < 0:
                raise ValueError
        except (ValueError, KeyError):
            flash("Please enter valid equipment details.", "error")
            return render_template("equipment_form.html")

        conn = db()
        conn.execute("""
            INSERT INTO equipment
            (name, category, total_quantity, available_quantity, deposit, late_fee, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, category, qty, qty, deposit, late_fee, description))
        conn.commit()
        conn.close()
        flash("Equipment added successfully.", "success")
        return redirect(url_for("equipment"))

    return render_template("equipment_form.html")

@app.route("/availability")
def availability():
    conn = db()
    equipment_rows = conn.execute("SELECT * FROM equipment ORDER BY name").fetchall()
    result = None
    selected_id = request.args.get("equipment_id", type=int)
    start_value = request.args.get("start_date", date.today().isoformat())
    end_value = request.args.get("end_date", date.today().isoformat())

    if selected_id:
        try:
            start = parse_day(start_value)
            end = parse_day(end_value)
            if end < start:
                raise ValueError
            result = {
                "available": available_for_period(conn, selected_id, start, end),
                "item": conn.execute("SELECT * FROM equipment WHERE id=?", (selected_id,)).fetchone()
            }
        except ValueError:
            flash("Please choose a valid date range.", "error")

    conn.close()
    return render_template(
        "availability.html",
        equipment=equipment_rows,
        result=result,
        selected_id=selected_id,
        start_value=start_value,
        end_value=end_value
    )

@app.route("/borrow", methods=["GET", "POST"])
def borrow():
    conn = db()
    equipment_rows = conn.execute("SELECT * FROM equipment ORDER BY name").fetchall()

    if request.method == "POST":
        try:
            name = request.form["borrower_name"].strip()
            student_id = request.form["student_id"].strip()
            contact = request.form.get("contact", "").strip()
            equipment_id = int(request.form["equipment_id"])
            quantity = int(request.form["quantity"])
            borrow_date = parse_day(request.form["borrow_date"])
            due_date = parse_day(request.form["due_date"])

            if (not name or not student_id or quantity < 1 or
                due_date < borrow_date):
                raise ValueError

            duration = (due_date - borrow_date).days + 1
            if duration > DEFAULT_MAX_BORROW_DAYS:
                raise ValueError("duration")

        except (ValueError, KeyError):
            conn.close()
            flash(f"Use valid details. A booking can be up to {DEFAULT_MAX_BORROW_DAYS} days.", "error")
            return render_template("borrow.html", equipment=equipment_rows)

        item = conn.execute("SELECT * FROM equipment WHERE id=?", (equipment_id,)).fetchone()
        if not item:
            conn.close()
            flash("Equipment not found.", "error")
            return render_template("borrow.html", equipment=equipment_rows)

        period_available = available_for_period(conn, equipment_id, borrow_date, due_date)
        if quantity > period_available:
            conn.close()
            flash(
                f"Only {period_available} unit(s) of {item['name']} are available for that date range.",
                "error"
            )
            return render_template("borrow.html", equipment=equipment_rows)

        borrower = conn.execute(
            "SELECT id FROM borrowers WHERE student_id=?", (student_id,)
        ).fetchone()

        existing = 0
        if borrower:
            existing = conn.execute("""
                SELECT COALESCE(SUM(quantity),0)
                FROM borrowings
                WHERE borrower_id=? AND status='Active'
            """, (borrower["id"],)).fetchone()[0]

        if existing + quantity > MAX_BORROWED_UNITS:
            conn.close()
            flash(
                f"Borrowing limit is {MAX_BORROWED_UNITS} active units per student.",
                "error"
            )
            return render_template("borrow.html", equipment=equipment_rows)

        if borrower:
            borrower_id = borrower["id"]
            conn.execute(
                "UPDATE borrowers SET name=?, contact=? WHERE id=?",
                (name, contact, borrower_id)
            )
        else:
            cur = conn.execute(
                "INSERT INTO borrowers(name,student_id,contact) VALUES(?,?,?)",
                (name, student_id, contact)
            )
            borrower_id = cur.lastrowid

        deposit = item["deposit"] * quantity

        conn.execute("""
            INSERT INTO borrowings
            (borrower_id,equipment_id,quantity,borrow_date,due_date,deposit,status)
            VALUES (?,?,?,?,?,?, 'Active')
        """, (
            borrower_id, equipment_id, quantity,
            borrow_date.isoformat(), due_date.isoformat(), deposit
        ))

        # Current inventory is adjusted only when the booking starts today.
        # Future reservations are represented by the date-range query.
        if borrow_date <= date.today() <= due_date:
            conn.execute("""
                UPDATE equipment
                SET available_quantity=available_quantity-?
                WHERE id=?
            """, (quantity, equipment_id))

        conn.commit()
        conn.close()
        flash(
            f"Booking confirmed for {item['name']}. The dashboard will nudge the borrower before return.",
            "success"
        )
        return redirect(url_for("index"))

    conn.close()
    return render_template("borrow.html", equipment=equipment_rows)

@app.route("/borrowings")
def borrowings():
    status_filter = request.args.get("status", "all")
    conn = db()

    query = """
        SELECT b.*, br.name AS borrower_name, br.student_id, br.contact,
               e.name AS equipment_name, e.category, e.late_fee AS daily_late_fee
        FROM borrowings b
        JOIN borrowers br ON br.id=b.borrower_id
        JOIN equipment e ON e.id=b.equipment_id
    """
    params = []
    if status_filter == "active":
        query += " WHERE b.status='Active'"
    elif status_filter == "returned":
        query += " WHERE b.status='Returned'"
    elif status_filter == "overdue":
        query += " WHERE b.status='Active' AND b.due_date < ?"
        params.append(date.today().isoformat())
    query += " ORDER BY b.id DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return render_template("borrowings.html", borrowings=rows, status_filter=status_filter)

@app.post("/return/<int:borrowing_id>")
def return_equipment(borrowing_id):
    conn = db()
    row = conn.execute("""
        SELECT b.*, e.late_fee AS daily_late_fee
        FROM borrowings b
        JOIN equipment e ON e.id=b.equipment_id
        WHERE b.id=?
    """, (borrowing_id,)).fetchone()

    if not row:
        conn.close()
        flash("Borrowing record not found.", "error")
        return redirect(url_for("borrowings"))

    if row["status"] != "Active":
        conn.close()
        flash("This borrowing is already closed.", "error")
        return redirect(url_for("borrowings"))

    today = date.today()
    due = parse_day(row["due_date"])
    late_days = max(0, (today - due).days)
    late_fee = late_days * row["daily_late_fee"] * row["quantity"]
    refund = max(0, row["deposit"] - late_fee)

    conn.execute("""
        UPDATE borrowings
        SET actual_return_date=?, late_fee=?, refund_amount=?, status='Returned'
        WHERE id=?
    """, (today.isoformat(), late_fee, refund, borrowing_id))

    # If this booking was currently consuming inventory, restore it.
    if parse_day(row["borrow_date"]) <= today <= due:
        conn.execute("""
            UPDATE equipment
            SET available_quantity=MIN(total_quantity, available_quantity+?)
            WHERE id=?
        """, (row["quantity"], row["equipment_id"]))

    conn.commit()
    conn.close()

    flash(
        f"Returned successfully. Late fee: ₹{late_fee:.2f}. Refund: ₹{refund:.2f}.",
        "success"
    )
    return redirect(url_for("borrowings"))

@app.post("/remind/<int:borrowing_id>")
def remind(borrowing_id):
    conn = db()
    row = conn.execute("""
        SELECT br.name AS borrower_name, e.name AS equipment_name, b.due_date
        FROM borrowings b
        JOIN borrowers br ON br.id=b.borrower_id
        JOIN equipment e ON e.id=b.equipment_id
        WHERE b.id=? AND b.status='Active'
    """, (borrowing_id,)).fetchone()
    conn.close()

    if row:
        flash(
            f"Return nudge queued for {row['borrower_name']}: "
            f"{row['equipment_name']} is due on {row['due_date']}.",
            "success"
        )
    else:
        flash("Active borrowing not found.", "error")

    return redirect(url_for("index"))

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
