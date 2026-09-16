"""Populate a fresh database with sample equipment and borrowers so the app
is immediately demoable. Run with: python seed.py"""

import database

def run():
    database.init_db(force=True)
    conn = database.get_connection()

    equipment = [
        # name, category, total_units, deposit, late_fee/day, default_loan_days
        ("Canon 200D DSLR", "Camera", 3, 2000, 100, 3),
        ("Epson Projector", "Projector", 2, 1500, 75, 2),
        ("Rode Shotgun Mic", "Audio", 5, 500, 30, 3),
        ("Camera Tripod", "Accessory", 4, 200, 10, 3),
    ]
    conn.executemany(
        """INSERT INTO equipment (name, category, total_units, deposit_amount, late_fee_per_day, default_loan_days)
           VALUES (?, ?, ?, ?, ?, ?)""",
        equipment,
    )

    borrowers = [
        ("Aarav Sharma", "aarav@college.edu"),
        ("Priya Verma", "priya@college.edu"),
        ("Rohan Gupta", "rohan@college.edu"),
        ("Photography Club", "photoclub@college.edu"),
    ]
    conn.executemany("INSERT INTO borrowers (name, contact) VALUES (?, ?)", borrowers)

    conn.commit()
    conn.close()
    print("Seeded rental.db with sample equipment and borrowers.")


if __name__ == "__main__":
    run()
