# AV Room Equipment Desk

A small web app that replaces the paper register for lending out AV gear
(DSLRs, projectors, mics, tripods...). It tracks what's out, what's free,
who has what, and nudges people when things are late.

## Features

- **Equipment catalog** with multiple interchangeable units per item (e.g. 3 DSLRs), a per-item deposit and a per-item late fee/day.
- **Borrow** an item: checks real availability (not just "is it in the room right now" but "will a unit be free for my whole loan window"), enforces a per-borrower cap on simultaneous active loans, and creates a loan with a due date.
- **Availability check** for any date or date range — this is what answers "is a DSLR free this weekend?" — via `GET /api/availability/<equipment_id>?start=YYYY-MM-DD&end=YYYY-MM-DD`.
- **Return** an item: computes days late, charges a late fee (days × rate), and refunds `deposit − late fee` (never below zero).
- **Transfer** an active loan to a different borrower: the due date carries over unchanged, and the item's availability is unaffected (it's still one unit checked out — only *who* has it changes). A transfer is refused if it would push the new borrower over the same simultaneous-loan cap used for normal borrowing.
- **Dashboard nudges**: an "Overdue" panel and a "Due within a day" panel, so the desk knows who to chase without scanning a paper log.

## Tech stack

Python 3 + Flask + SQLite (stdlib `sqlite3`, no ORM). No external services, no build step — this keeps setup in Codespaces to one command.

## Project layout

```
app.py              Flask routes (the web layer only)
rental_logic.py      All business rules: availability, borrow, return, transfer, nudges
database.py          SQLite connection + schema init helper
schema.sql            Table definitions
seed.py               Sample data (run once for a demo)
templates/            Jinja2 HTML pages (Bootstrap via CDN, no build step)
tests/                Unit tests for rental_logic.py
.devcontainer/         Codespaces config (auto-installs requirements, forwards port 5000)
```

## Setup & running (GitHub Codespaces or local)

1. Open the repo in a Codespace (or clone it locally with Python 3.10+ installed).
   In Codespaces, `.devcontainer/devcontainer.json` runs step 2 for you automatically.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. (Optional but recommended for a demo) seed some sample equipment and borrowers:
   ```
   python seed.py
   ```
   This creates `rental.db` with 4 equipment types (DSLR ×3, Projector ×2, Mic ×5, Tripod ×4) and 4 sample borrowers.
   Skip this step if you'd rather start from an empty desk — the app creates
   an empty `rental.db` automatically on first run either way.
4. Run the app:
   ```
   python app.py
   ```
5. Open the forwarded port 5000 (Codespaces will prompt you, or click the "Ports" tab). Locally, visit `http://127.0.0.1:5000`.

## Using it

- **Dashboard** (`/`) — availability at a glance, plus overdue/due-soon nudges.
- **Equipment** (`/equipment`) — add new gear types and see current stock.
- **Borrowers** (`/borrowers`) — add people/clubs who can borrow.
- **Borrow** (`/borrow`) — pick equipment + borrower (+ optional custom loan length) to create a loan.
- **Loans** (`/loans`) — see active/returned/all loans; **Return** or **Transfer** each active loan from here. Overdue rows are highlighted.
- **Availability API** — `GET /api/availability/<equipment_id>` for "right now", or add `?start=...&end=...` for a date range (e.g. "this weekend").

## Running tests

```
python -m unittest tests.test_rental_logic -v
```

The tests cover: availability shrinking/growing on borrow/return, the total-units cap, the per-borrower simultaneous-loan cap, on-time vs. late returns and deposit math, late fees never exceeding the deposit, and — for the transfer feature — that the due date and availability are untouched by a transfer, that a returned loan can't be transferred, and that a transfer is blocked if it would put the new borrower over their loan cap.

## Debugging notes

- The app auto-creates `rental.db` (SQLite file, gitignored) on first request if it doesn't exist — delete it any time to reset to a blank desk, or re-run `python seed.py` (which wipes and reseeds it).
- Flask runs with `debug=True`, so tracebacks appear in the browser and the server auto-reloads on code changes.
- If port 5000 doesn't auto-forward in Codespaces, open the "Ports" panel and forward it manually, or check `.devcontainer/devcontainer.json`.
- All business rules (limits, fees, availability math) live in `rental_logic.py` and raise `RentalError` with a user-facing message on any rule violation — that message is what gets flashed on screen, so it's the first place to look if a "why did this fail?" question comes up.

## Configuration

Two constants worth knowing about, both in `rental_logic.py`:
- `MAX_ACTIVE_LOANS_PER_BORROWER` (default 3) — caps how much of the room one person can hold at once.
- Per-equipment `deposit_amount`, `late_fee_per_day`, and `default_loan_days` are set when the item is added (via `/equipment` or `seed.py`), so a camera can carry a bigger deposit than a mic.
