# Reasoning

## 1. Problem Interpretation

The central requirement is to track AV room gear and nudge borrowers to return it. The solution therefore focuses on a reliable borrowing lifecycle rather than building an unnecessarily large application.

The main workflow is:

**Equipment → Borrow → Track → Due Date → Reminder → Return → Late Fee → Deposit Refund → History**

## 2. Requirements Derived

The problem statement implies:

- Multiple units can exist for popular equipment.
- Staff need to know current availability.
- Two users should not be able to borrow more units than are available.
- Every borrowing needs a sensible return date.
- Late returns need a daily fee.
- A refundable deposit should be tracked.
- A borrower should have a reasonable simultaneous borrowing limit.
- Staff need a way to identify equipment that is due or overdue.
- Returned equipment must become available again.

## 3. Architecture

A lightweight Flask server renders HTML pages using Jinja2. SQLite provides persistent relational storage.

This was selected because:
- It is quick to set up.
- It runs without external services.
- It works well in GitHub Codespaces.
- It is easy to debug within a limited assessment period.

## 4. Database Design

### equipment

Stores the inventory and financial rules for each equipment type.

Important fields:
- total_quantity
- available_quantity
- deposit
- late_fee

### borrowers

Stores borrower identity:
- name
- student_id
- contact

Student ID is unique so repeat borrowers can reuse their record.

### borrowings

Stores each checkout:
- borrower
- equipment
- quantity
- borrow date
- due date
- actual return date
- deposit
- late fee
- refund
- status

## 5. Availability

Availability is checked using the equipment's total quantity and active bookings that overlap the requested date range.

Two date ranges overlap when:

`existing_start <= requested_end AND existing_end >= requested_start`

The system sums quantities from overlapping active bookings and calculates:

`period_available = total_quantity - overlapping_units`

This directly addresses the problem of two clubs arriving for the same projector and the student question "is a DSLR free this weekend?"

`available_quantity` is still maintained for current inventory visibility, while date-range queries are the source of truth for future reservations.

## 6. Booking Window and Borrowing Limit

A booking window of up to 14 days and a maximum of 3 active units per student were selected as a reasonable assumption because the statement says one person should not book out half the room. The constant is kept near the top of `app.py` so it can be changed easily.

## 7. Return and Late Fee

The actual return date is compared with the expected due date.

If the actual return is after the due date:

`late_days = actual_return_date - due_date`

The fee is:

`late_fee = late_days × daily_late_fee × quantity`

The refund is:

`max(0, deposit - late_fee)`

This prevents a negative refund.

## 8. Return Nudge

No external notification service is required. The dashboard itself acts as the reminder center.

Active borrowings are labeled:
- Due in X days
- Due tomorrow
- Due today
- X days overdue

The Remind action provides an in-app nudge. Returned equipment is excluded from active reminders.

## 9. Validation

Server-side validation handles:
- Empty required fields
- Invalid quantities
- Insufficient availability
- Invalid dates
- Borrowing-limit violations
- Missing records
- Duplicate return attempts

## 10. Trade-offs

Because the assessment has a strict 2.5-hour limit, the solution avoids:
- Complex authentication
- Email/SMS integrations
- External APIs
- Microservices
- Complex frontend frameworks

The focus is on a working end-to-end borrowing and return workflow with clear business rules.
