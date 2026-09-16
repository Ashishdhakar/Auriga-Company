from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

import database
import rental_logic as rl

app = Flask(__name__)
app.secret_key = "dev-only-secret-key"


def conn():
    return database.get_connection()


@app.before_request
def ensure_db():
    if not database.DB_PATH.exists():
        database.init_db()


# --------------------------------------------------------------- dashboard --

@app.route("/")
def dashboard():
    c = conn()
    equipment = c.execute("SELECT * FROM equipment ORDER BY name").fetchall()
    eq_status = [
        {**dict(eq), "available_today": rl.available_units_on(c, eq["id"], rl.today())}
        for eq in equipment
    ]
    overdue = rl.overdue_loans(c)
    due_soon = rl.due_soon_loans(c, within_days=1)
    c.close()
    return render_template(
        "dashboard.html", equipment=eq_status, overdue=overdue, due_soon=due_soon
    )


# --------------------------------------------------------------- equipment --

@app.route("/equipment", methods=["GET", "POST"])
def equipment_page():
    c = conn()
    if request.method == "POST":
        try:
            c.execute(
                """INSERT INTO equipment
                   (name, category, total_units, deposit_amount, late_fee_per_day, default_loan_days)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    request.form["name"].strip(),
                    request.form.get("category", "").strip(),
                    int(request.form["total_units"]),
                    float(request.form["deposit_amount"]),
                    float(request.form["late_fee_per_day"]),
                    int(request.form["default_loan_days"]),
                ),
            )
            c.commit()
            flash(f"Added {request.form['name']}.")
        except (ValueError, KeyError):
            flash("Please fill in every field with a valid number.", "error")
        c.close()
        return redirect(url_for("equipment_page"))

    equipment = c.execute("SELECT * FROM equipment ORDER BY name").fetchall()
    c.close()
    return render_template("equipment.html", equipment=equipment)


@app.route("/api/availability/<int:equipment_id>")
def availability_api(equipment_id):
    """Answers 'is a DSLR free this weekend?' -- pass start & end (YYYY-MM-DD)
    for a range check, or nothing for 'right now'."""
    c = conn()
    try:
        eq = rl.get_equipment(c, equipment_id)
        start, end = request.args.get("start"), request.args.get("end")
        if start and end:
            ok, bad_day = rl.is_available_for_range(
                c, equipment_id, rl.parse_date(start), rl.parse_date(end)
            )
            result = {
                "equipment": eq["name"],
                "start": start,
                "end": end,
                "available": ok,
                "first_unavailable_day": str(bad_day) if bad_day else None,
            }
        else:
            result = {
                "equipment": eq["name"],
                "date": str(rl.today()),
                "available_units": rl.available_units_on(c, equipment_id, rl.today()),
            }
        return jsonify(result)
    except rl.RentalError as e:
        return jsonify({"error": str(e)}), 404
    finally:
        c.close()


# --------------------------------------------------------------- borrowers --

@app.route("/borrowers", methods=["GET", "POST"])
def borrowers_page():
    c = conn()
    if request.method == "POST":
        c.execute(
            "INSERT INTO borrowers (name, contact) VALUES (?, ?)",
            (request.form["name"].strip(), request.form.get("contact", "").strip()),
        )
        c.commit()
        flash(f"Added borrower {request.form['name']}.")
        c.close()
        return redirect(url_for("borrowers_page"))

    borrowers = c.execute("SELECT * FROM borrowers ORDER BY name").fetchall()
    c.close()
    return render_template("borrowers.html", borrowers=borrowers)


# -------------------------------------------------------------------- loans --

@app.route("/borrow", methods=["GET", "POST"])
def borrow_page():
    c = conn()
    if request.method == "POST":
        try:
            loan_days = int(request.form["loan_days"]) if request.form.get("loan_days") else None
            loan_id = rl.create_loan(
                c, int(request.form["equipment_id"]), int(request.form["borrower_id"]), loan_days
            )
            eq = rl.get_equipment(c, int(request.form["equipment_id"]))
            flash(
                f"Loan #{loan_id} created. Deposit due: {eq['deposit_amount']}. "
                f"Return by the date shown in Loans."
            )
        except rl.RentalError as e:
            flash(str(e), "error")
        c.close()
        return redirect(url_for("borrow_page"))

    equipment = c.execute("SELECT * FROM equipment ORDER BY name").fetchall()
    borrowers = c.execute("SELECT * FROM borrowers ORDER BY name").fetchall()
    eq_avail = {eq["id"]: rl.available_units_on(c, eq["id"], rl.today()) for eq in equipment}
    c.close()
    return render_template(
        "borrow.html", equipment=equipment, borrowers=borrowers, eq_avail=eq_avail
    )


@app.route("/loans")
def loans_page():
    c = conn()
    status = request.args.get("status", "active")
    base_query = """
        SELECT loans.*, equipment.name AS equipment_name, borrowers.name AS borrower_name
        FROM loans
        JOIN equipment ON equipment.id = loans.equipment_id
        JOIN borrowers ON borrowers.id = loans.borrower_id
    """
    if status == "all":
        rows = c.execute(base_query + " ORDER BY loans.id DESC").fetchall()
    else:
        rows = c.execute(
            base_query + " WHERE loans.status=? ORDER BY loans.id DESC", (status,)
        ).fetchall()
    borrowers = c.execute("SELECT * FROM borrowers ORDER BY name").fetchall()
    today_s = str(rl.today())
    c.close()
    return render_template(
        "loans.html", loans=rows, status=status, borrowers=borrowers, today=today_s
    )


@app.route("/loans/<int:loan_id>/return", methods=["POST"])
def return_page(loan_id):
    c = conn()
    try:
        result = rl.return_loan(c, loan_id)
        flash(
            f"Returned. Late fee: {result['late_fee']}, "
            f"deposit refunded: {result['deposit_refunded']}."
        )
    except rl.RentalError as e:
        flash(str(e), "error")
    c.close()
    return redirect(url_for("loans_page"))


@app.route("/loans/<int:loan_id>/transfer", methods=["POST"])
def transfer_page(loan_id):
    c = conn()
    try:
        rl.transfer_loan(c, loan_id, int(request.form["to_borrower_id"]))
        flash("Transferred. Due date and availability are unchanged.")
    except rl.RentalError as e:
        flash(str(e), "error")
    c.close()
    return redirect(url_for("loans_page"))


if __name__ == "__main__":
    database.init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
