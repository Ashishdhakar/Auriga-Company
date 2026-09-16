# AV Room Equipment Rental / Management System

A small Flask + SQLite web app for managing a college AV equipment room:
borrowing, availability checks, returns, deposits/late fees, and borrowing
limits — replacing a paper register.

## Features

- **Dashboard** — total/available/borrowed units, overdue count, recent activity.
- **Equipment management** — add, view, edit, delete equipment (name, category,
  total quantity, deposit, daily late fee, description). Delete is blocked while
  units are actively borrowed; total quantity can't be edited below the number
  currently checked out.
- **Availability check** — pick a date range and see, per equipment, how many
  units are free, with an Available / Partially Available / Unavailable status.
  This checks for overlapping active bookings, not just current stock.
- **Borrow workflow** — captures borrower name, student ID, contact, equipment,
  quantity, borrow date, and expected return date. Validates quantity, dates,
  availability for the requested period, and the borrower's total unit limit.
- **Returns** — marks a borrowing returned, records the actual return date,
  restores stock, and calculates late days / late fee / refund automatically.
- **Overdue tracking** — active borrowings past their expected return date are
  flagged everywhere (dashboard, history) with live day-count and estimated fee.
- **Borrowing history** — full table of every borrowing with filters for
  All / Active / Overdue / Returned.

## Technology Stack

- **Backend:** Python 3, Flask
- **Database:** SQLite (single file, `database.db`, created automatically)
- **Frontend:** Server-rendered Jinja2 templates, plain HTML/CSS/JS
  (no external CSS/JS frameworks or CDNs — works fully offline)

## Requirements

- Python 3.9+
- pip

## Installation / Setup

```bash
# 1. Go into the project folder
cd equipment-rental

# 2. (Recommended) create a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

## How to Run Locally

```bash
python app.py
```

The app starts on **http://127.0.0.1:5000**. Open that URL in your browser.

On first run, `database.db` is created automatically and seeded with four
sample equipment items (DSLR Camera, Projector, Microphone, Tripod) so the
app isn't empty when you open it.

## How to Run in GitHub Codespaces

1. Open the repository in a Codespace.
2. In the terminal:
   ```bash
   cd equipment-rental
   pip install -r requirements.txt
   python app.py
   ```
3. Codespaces will detect the app listening on port 5000 and show a
   **"Open in Browser"** popup / notification — click it (or open the
   **Ports** tab and click the forwarded 5000 link).
4. The app runs the same as locally; no extra configuration or external
   services are needed.

## Database

SQLite, single file `database.db`, three tables:

- **equipment** — `id, name, category, total_quantity, available_quantity, deposit_amount, daily_late_fee, description, created_at`
- **borrowers** — `id, name, student_id (unique), contact, created_at`
- **borrowings** — `id, borrower_id (FK), equipment_id (FK), quantity, borrow_date, expected_return_date, actual_return_date, status, deposit_amount, late_fee, refund_amount, created_at`

To reset the database, stop the app and delete `database.db` — it will be
recreated (with sample data) the next time you run `python app.py`.

## Main Workflows

1. **Add equipment** — Equipment → Add Equipment.
2. **Check availability** — Availability → pick a date range → see free
   units per item.
3. **Borrow** — Borrow → fill in borrower + equipment + dates → Confirm.
   Blocked if the quantity/period isn't available, dates are invalid, or
   the borrower would exceed the unit limit (default: 5, see below).
4. **Return** — History → find the active row → pick the actual return
   date → Return. Late fee and refund are computed and shown immediately.
5. **Track overdue** — Dashboard shows the overdue count; History → Overdue
   filter lists them with live late-day counts.

### Changing the borrowing limit

Edit `MAX_UNITS_PER_BORROWER` near the top of `app.py`:

```python
MAX_UNITS_PER_BORROWER = 5   # change this number
```

## Assumptions

See `REASONING.md` for the full list; the key ones are:

- A borrower is uniquely identified by **student ID** (contact/name are
  updated on repeat visits, not duplicated).
- "Availability for a period" is computed against **active** borrowings
  whose date range overlaps the requested range — not just the current
  `available_quantity` snapshot — so a future conflict is still caught.
- The borrowing limit (`MAX_UNITS_PER_BORROWER`) counts **total units
  currently active** for that student ID, across all equipment types.
- Deposit defaults to the equipment's per-unit deposit × quantity, but can
  be overridden per-borrowing (e.g. for a bundled/negotiated deposit).
- Late fee = late whole days × equipment's daily late fee; refund = deposit
  − late fee, floored at 0 (never negative).
- No authentication/login — this is a single shared internal tool, per the
  assessment's "avoid authentication systems" instruction.

## Troubleshooting

- **"ModuleNotFoundError: No module named 'flask'"** — activate your
  virtual environment and re-run `pip install -r requirements.txt`.
- **Port 5000 already in use** — stop whatever else is using it, or change
  the port in the last line of `app.py` (`app.run(..., port=5000)`).
- **Database looks broken / stuck in a weird state** — stop the app, delete
  `database.db`, and restart; it will rebuild automatically.
- **Changes to templates/CSS not showing** — the app runs with
  `debug=True`, so it auto-reloads; if not, restart `python app.py`.
- **"Cannot delete equipment"** — equipment with active (not-yet-returned)
  borrowings can't be deleted; wait for it to be returned or edit it instead.

## Example Usage

1. Start the app, open http://127.0.0.1:5000.
2. Dashboard shows 4 seeded equipment types, all fully available.
3. Go to **Borrow**, select "Canon EOS 1500D", quantity 1, student ID
   `PCE23CS028`, borrow date today, expected return in 3 days → Confirm.
4. Dashboard now shows 1 unit borrowed; Equipment page shows 3/4 available.
5. Go to **History**, find the row, set an actual return date a couple of
   days after the expected date, click **Return** → see the late fee and
   reduced refund calculated automatically.
