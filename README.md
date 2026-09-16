# AV Gear Manager

A simple Equipment Rental / AV Room Management System built for the Auriga IT Builder Round.

## Goal

The system tracks college AV equipment and helps staff follow up on returns. It covers the core problem areas: borrowing, availability, returns, overdue tracking, late fees, deposits/refunds, borrowing limits, and in-app return nudges.

## Features

- Dashboard with inventory and borrowing statistics
- Equipment inventory with multiple units
- Availability tracking by date range
- Future booking conflict prevention for overlapping date ranges
- Borrowing workflow
- Borrowing limit of 3 active units per student
- Return workflow
- Automatic overdue detection
- Per-day late fee calculation
- Refundable deposit calculation
- In-app return reminders / nudges
- Borrowing history
- SQLite database
- Responsive UI

## Tech Stack

- Python
- Flask
- SQLite
- HTML/CSS
- Jinja2

## Setup

### 1. Create a virtual environment (optional)

```bash
python -m venv .venv
```

Activate it:

Linux/macOS:
```bash
source .venv/bin/activate
```

Windows:
```bash
.venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run

```bash
python app.py
```

The application will run on:

`http://127.0.0.1:5000`

In GitHub Codespaces, open the forwarded port 5000 from the Ports panel.

## First Use

1. Open Dashboard.
2. Check the seeded equipment.
3. Add more equipment if required.
4. Create a borrowing.
5. Check the Return Reminders section.
6. Return the item from Borrowings.
7. The system calculates late fee and deposit refund automatically.

## Business Rules

### Availability

Availability is calculated for the requested date range, not just for today.

For an equipment type:

`period_available = total_quantity - overlapping_active_booked_units`

Two active bookings overlap when:

`existing_start <= requested_end AND existing_end >= requested_start`

This prevents two clubs from booking the same units for overlapping dates.

### Borrowing Limit

A student can have a maximum of 3 active equipment units.

### Late Fee

```text
late_fee = late_days × daily_late_fee × quantity
```

### Deposit Refund

```text
refund = max(0, deposit - late_fee)
```

### Booking Window

A booking can be up to 14 calendar days. This is a configurable assessment assumption.

### Return Nudges

The dashboard labels active borrowings as Due Soon, Due Today, or Overdue. The Remind button provides an in-app nudge message. No external email/SMS service is required.

## Database

SQLite creates `equipment.db` automatically on first run.

Tables:
- `equipment`
- `borrowers`
- `borrowings`

## Debugging

If the port is busy, stop the existing Flask process and run again.

If the database becomes inconsistent during development, stop the app, delete `equipment.db`, and restart. The sample inventory will be recreated.

## Assessment Notes

The implementation intentionally prioritizes the problem statement's core workflow:

**Check date-range availability → Borrow → Track → Reminder → Return → Late Fee/Deposit → History**

The system is kept small enough to understand and run in GitHub Codespaces.
