# REASONING

## How I Interpreted the Problem

The core pain point stated is a paper register causing missing equipment and
booking conflicts. The prioritized list (Borrowing, Availability, Returns,
Deposits/Refunds, Borrowing Limits) tells me the grading/usefulness weight,
so those five are implemented first and most carefully; supporting features
(dashboard, history, overdue view) exist to make those five usable and
auditable, not as independent priorities.

## Functional Requirements Identified

1. CRUD equipment with quantity, deposit, and late-fee metadata.
2. Period-based availability lookup that reflects real conflicts, not just a
   raw "units currently free" counter.
3. A borrowing form with full server-side validation (quantity, dates,
   availability, per-borrower limit).
4. A single-click-ish return flow that computes late days, late fee, and
   refund deterministically from stored data (never trusts client input for
   money math).
5. Overdue visibility, computed live from `expected_return_date` vs today for
   active items, and from `expected_return_date` vs `actual_return_date` for
   returned ones.
6. A history table with status filtering for accountability.

## Architecture

- **Flask, single `app.py`** — for a 2.5-hour scope, one file keeps routes,
  validation, and DB helpers easy to navigate without an import/package
  layer that adds no real value at this size.
- **Server-side rendering with Jinja2** — no JS framework/build step, which
  keeps Codespaces setup to `pip install` + `python app.py`.
- **No authentication** — explicitly out of scope per the prompt; this is a
  single shared internal tool (like the paper register it replaces).
- **Custom CSS instead of a CDN framework (e.g. Bootstrap)** — the brief
  asks for something that runs reliably in Codespaces without needing
  internet access for core functionality; a hand-written stylesheet removes
  that dependency entirely while still giving a clean, consistent look.

## Database Design

Three tables, matching the natural entities:

- `equipment` — one row per equipment *type* (e.g. "Canon EOS 1500D"), not
  per physical unit. `total_quantity` and `available_quantity` model the
  pool of interchangeable units. This avoids the complexity of tracking
  individual serial-numbered units, which the problem doesn't ask for
  ("multiple units of the same equipment" — a count, not identity, model
  is the standard, appropriately-scoped choice here).
- `borrowers` — one row per student, keyed by a **unique student ID**, so
  repeat borrowers don't create duplicate people and their borrowing-limit
  total is computed correctly across visits.
- `borrowings` — the transactional table; one row per borrow event, with a
  status (`active`/`returned`), the dates, and the money fields
  (`deposit_amount`, `late_fee`, `refund_amount`) captured at the time of
  the transaction rather than recomputed from equipment's *current* deposit
  (so changing an equipment's deposit later doesn't rewrite history).

Foreign keys (`borrower_id`, `equipment_id`) enforce relational integrity;
`CHECK` constraints guard against negative quantities/amounts at the DB
layer as a last line of defense behind the Flask-side validation.

## Business Rules

### Availability Logic

`available_quantity` on the equipment row is a fast, always-current counter
(decremented on borrow, restored on return) used for dashboard totals and
the borrow form's equipment dropdown.

For the **availability-by-period** check and for validating a *new*
borrowing, I don't just read that counter — I sum the quantities of all
*active* borrowings whose `[borrow_date, expected_return_date]` window
overlaps the requested window, and subtract from `total_quantity`. This
catches a conflict even if today's raw `available_quantity` looks free,
because it reasons about the specific date range being requested, not just
"right now." This is the mechanism that satisfies "prevent double-booking."

### Booking Conflict Logic

Two date ranges `[a_start, a_end]` and `[b_start, b_end]` overlap exactly
when `a_start <= b_end AND b_start <= a_end`. That's the SQL condition used
in `overlapping_borrowed_quantity()`. Only `status = 'active'` borrowings
count — a returned borrowing no longer holds a unit, regardless of its
original dates.

### Late Fee Logic

`late_days = max((actual_return_date - expected_return_date).days, 0)` —
returning early or exactly on time is never "negative late." For active
(not yet returned) borrowings, the same formula is applied against *today*
so the dashboard/history can show a live, running late-fee estimate before
the item is actually returned.

`late_fee = late_days × equipment.daily_late_fee`, computed and **stored**
at return time (not recalculated later), so the historical record is
immutable once a borrowing is closed.

### Deposit / Refund Logic

`refund_amount = max(deposit_amount − late_fee, 0)` — matches the spec
exactly, floored at zero so a very late return never produces a negative
refund (i.e., the borrower owes nothing beyond their deposit; the system
doesn't invoice for the difference, which is out of scope).

The deposit itself defaults to `equipment.deposit_amount × quantity` but can
be overridden per-borrowing at the form (e.g., a bundled deposit), and
whatever value is entered is what gets refunded against — an assumption
documented in the README.

### Borrowing-Limit Logic

`MAX_UNITS_PER_BORROWER` (default 5, a single constant at the top of
`app.py`) caps the **total units currently active** for a student ID,
summed across *all* equipment types — not per-equipment-type — since the
problem says "an excessive number of items," which reads as an overall cap
rather than a per-category one.

## Validation Decisions

All business-rule validation lives server-side in `app.py` (quantity > 0,
return date ≥ borrow date, requested quantity ≤ period availability,
borrower's post-borrow total ≤ limit, non-negative deposit). HTML5
`required`/`type="date"`/`type="number"` attributes are used for basic
client-side friendliness only — they are not trusted as the source of
truth. Every "not found" lookup (equipment, borrowing) is checked and
flashes a clear error instead of throwing, and returning an
already-returned borrowing is explicitly blocked.

## Testing Approach

I wrote a scripted test pass (using Flask's test client against a real
SQLite file) covering the required workflow end-to-end: add equipment →
availability check → borrow → verify quantity decrement → over-quantity
borrow rejected → overlapping-period conflict rejected → borrowing-limit
exceeded rejected → on-time return (full refund) → late return (fee +
reduced refund, verified against the exact formula) → double-return
blocked → available_quantity restored → overdue filter shows the right
record → equipment delete blocked while borrowed → equipment edit blocked
below currently-borrowed count → every page returns HTTP 200 → 404 handler
works. One real bug (a missing joined column feeding the dashboard's
late-fee calculation) was caught this way and fixed before submission.

## Trade-offs Made Because of the 2.5-Hour Limit

- **No authentication/roles** — per the brief; anyone with the URL can act
  as "the admin." Fine for a trusted internal tool, not fine for production.
- **No individual/serialized unit tracking** — equipment is tracked as a
  count per type, not by serial number, so "which specific camera unit #3"
  isn't tracked. Sufficient for the stated problem.
- **No email/SMS reminders for overdue items** — overdue items are surfaced
  in-app (dashboard + filter) but nothing proactively notifies the borrower.
- **No pagination** on the history table — fine at classroom/college-club
  scale, would need it at large scale.
- **No edit/cancel on an existing borrowing** (only create + return) — kept
  the state machine simple (`active` → `returned`) rather than adding
  amend/cancel flows not required by the brief.
- **Single shared SQLite file, no concurrent-write handling beyond SQLite's
  own locking** — adequate for a small internal tool, not for high concurrency.
