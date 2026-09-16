# Reasoning

## Reading the problem for what it actually asks

The prompt is written as a story, not a spec, and it explicitly says the job
is to notice the questions people ask and the gaps in the paper register —
so I treated those sentences as the real requirements list rather than
decoration:

- "popular items have several units" → equipment isn't a single object with
  a single status; it's a *count* of interchangeable units, and availability
  is a number, not a boolean.
- "kit goes missing and two clubs show up for the same projector" → the
  system's core job is to make double-booking structurally impossible, not
  to rely on someone remembering to check a ledger.
- "is a DSLR free this weekend?" → this is a *future date-range* question,
  not a "is it in the room right now" question. A register that only shows
  current status still can't answer this; you need to reason about
  everything currently on loan and whether it's due back before the date
  in question.
- "borrowers hang on to things far too long" → needs an explicit due date
  and a late fee tied to it, not just a polite return date with no teeth.
- "a refundable deposit... returned minus any late fee" → deposit and late
  fee are coupled: return logic must compute the fee first, then refund
  what's left, floored at zero (a very late return shouldn't create a debt).
- "one person shouldn't be able to book out half the room at once" → a cap
  on simultaneous active loans per borrower, independent of which specific
  items they're holding.

The final instruction — "get borrowing, availability and returns solid
first, then deposits and limits" — set my build order: I wrote
`rental_logic.py`'s borrow/availability/return functions and their tests
before touching deposits or the per-borrower cap, so the foundation was
correct before I layered policy on top of it.

## Key design decision: derive availability, don't store it

I considered giving each physical unit its own row with a `status` flag
(available/on loan) and flipping it on borrow/return. I rejected that
because it creates two sources of truth that can drift apart (what if a
return updates the loan but forgets to flip the unit flag?) — exactly the
kind of bug a paper register has.

Instead, an equipment row just has `total_units`, and availability on any
day is *computed*: `total_units − (active loans whose [borrowed_at, due_date]
window covers that day)`. There's nothing to desynchronize. This also gives
the "is a DSLR free this weekend?" feature almost for free — it's the same
function called once per day in the requested range — instead of being a
bolted-on special case.

## Key design decision: separate business rules from the web framework

`rental_logic.py` has no Flask import. Every rule (availability, the
per-borrower cap, late fee math, transfer validity) is a plain function
taking a DB connection, raising `RentalError` with a message that's safe to
show a user. `app.py` is a thin layer that calls these functions and
flashes the exception message on failure. This meant I could write and run
real unit tests (`tests/test_rental_logic.py`) against SQLite directly,
without spinning up a browser or mocking HTTP — which is also why I'm
confident the late-fee and transfer edge cases actually work, not just that
the UI looks right.

## The twist: transferring an active loan

The requirement is precise: the due date must carry over *unchanged*, and
the item's availability must be *unaffected*. Once availability is derived
from `(equipment_id, borrowed_at, due_date)` rather than from
`borrower_id`, this becomes almost a non-event: `transfer_loan()` updates
exactly one column, `loans.borrower_id`. It never touches `equipment_id`,
`borrowed_at`, or `due_date`, so:

- the due date is untouched by construction (there's no code path that
  could change it during a transfer), and
- `available_units_on()` never looks at `borrower_id` at all, so recomputing
  availability before and after a transfer gives the same number — this is
  asserted directly in `test_transfer_keeps_due_date_and_availability`.

I still log the transfer in a separate `transfers` table (who had it, who
it went to, when) rather than just silently overwriting `borrower_id`,
because "who currently has this and how did it get there" is exactly the
kind of accountability question a paper register fails at, and it costs
one extra table.

One judgment call: should a transfer be allowed to push the *new* borrower
over the simultaneous-loan cap? I decided no — the cap exists to stop one
person from holding too much of the room at once, and a transfer is just
another way for that to happen. If the item is truly needed and the
receiving person is at their cap, they can return something first, the
same as if they were borrowing directly.

## Other things I deliberately kept simple

- **Nudges are in-app, not emailed.** The dashboard surfaces "overdue" and
  "due within a day" panels, and `rental_logic.reminder_messages()` builds
  the exact text a cron job or WhatsApp bot would send — but I didn't wire
  up real email/SMS, since no mail server was in scope and a fake one would
  just be noise. The function returning plain strings makes it a one-line
  job to plug into something real later.
- **No login/auth.** This is a desk tool for whoever is staffing the AV
  room, not a public-facing system with untrusted users; adding auth would
  have traded build time on the actual problem (availability, returns,
  transfers) for boilerplate.
- **SQLite over a client-server DB.** One file, zero setup, and it's more
  than enough for a college AV room's volume. `database.py` isolates all
  connection logic, so swapping it later wouldn't touch `rental_logic.py`.
- **Equipment "kind" instead of serialized units.** The problem never
  mentions telling two DSLRs apart by serial number, only "several units",
  so I didn't invent that complexity.
