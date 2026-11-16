"""Seed a demo shop so the admin UI has something to show.

    python -m scripts.seed            # creates/refreshes the demo tenant
    python -m scripts.seed --reset    # deletes the demo tenant first

Deterministic: same items, same invoices, same totals every run. It talks to the
same service layer the API uses (not raw SQL), so seeded data obeys every rule —
numbering, GST split, stock ledger and payment signatures included.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.db import connect, init_db  # noqa: E402
from app.payments import create_order, simulate_signed_callback, verify_and_capture  # noqa: E402
from app.services import (  # noqa: E402
    cancel_invoice,
    create_invoice,
    create_item,
    get_tenant,
    list_invoices,
    register_tenant,
)

DEMO_EMAIL = "demo@billbook.dev"
DEMO_PASSWORD = "demo12345"

ITEMS = [
    # sku, name, hsn, unit, price, gst_rate, stock, reorder
    ("WM-01", "Wireless mouse", "8471", "pcs", 599.0, 18, 40, 10),
    ("KB-02", "Mechanical keyboard", "8471", "pcs", 2499.0, 18, 18, 5),
    ("HP-03", "USB-C headphone", "8518", "pcs", 1299.0, 18, 22, 6),
    ("CB-04", "USB-C cable 1m", "8544", "pcs", 249.0, 18, 120, 25),
    ("MP-05", "Mouse pad (large)", "3926", "pcs", 299.0, 12, 60, 15),
    ("PB-06", "Power bank 20000mAh", "8507", "pcs", 1899.0, 28, 9, 4),
    ("ST-07", "Laptop stand (aluminium)", "7616", "pcs", 1499.0, 18, 12, 4),
    ("NB-08", "Notebook (A5, ruled)", "4820", "pcs", 80.0, 0, 200, 40),
]

CUSTOMERS = [
    ("Sri Traders", "33ABCDE1234F1Z5", "33"),
    ("Walk-in customer", None, None),
    ("Bengaluru Retail", "29AAACB1234C1ZP", "29"),
    ("Hyderabad Hub", "36AACCT5678D1Z9", "36"),
]


def seed(conn: sqlite3.Connection, *, reset: bool = False) -> dict:
    settings = get_settings()

    row = conn.execute("SELECT tenant_id FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone()
    if row and reset:
        conn.execute("DELETE FROM tenants WHERE id = ?", (row["tenant_id"],))
        conn.commit()
        row = None

    if row:
        tenant_id = int(row["tenant_id"])
        owner = conn.execute("SELECT * FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone()
        user_id = int(owner["id"])
        print(f"· demo tenant already exists (id {tenant_id}); adding invoices to it")
    else:
        user, tenant = register_tenant(
            conn,
            tenant_name="Chennai Gadgets",
            state_code="33",
            gstin="33AABCU9603R1ZM",
            address="12 Anna Salai, Chennai 600002",
            name="Demo Owner",
            email=DEMO_EMAIL,
            password=DEMO_PASSWORD,
        )
        tenant_id, user_id = tenant["id"], user["id"]
        print(f"· created tenant {tenant_id} with owner {DEMO_EMAIL} / {DEMO_PASSWORD}")

    items = list(conn.execute("SELECT * FROM items WHERE tenant_id = ?", (tenant_id,)).fetchall())
    if not items:
        for sku, name, hsn, unit, price, rate, stock, reorder in ITEMS:
            create_item(
                conn, tenant_id=tenant_id, user_id=user_id, sku=sku, name=name, hsn=hsn,
                unit=unit, unit_price=price, gst_rate=rate, stock_qty=stock,
                reorder_level=reorder,
            )
        items = list(conn.execute("SELECT * FROM items WHERE tenant_id = ? ORDER BY id",
                                  (tenant_id,)).fetchall())
        print(f"· added {len(items)} items")

    existing = list_invoices(conn, tenant_id)
    created = 0
    if len(existing) < 8:
        # (customer, [(item index, qty)], pay?)
        plan = [
            (0, [(0, 2), (3, 1)], True),
            (1, [(5, 1)], False),
            (2, [(1, 3), (4, 2)], True),
            (3, [(6, 2)], False),
            (0, [(2, 1), (7, 6)], False),
            (1, [(3, 4)], True),
            (2, [(0, 5)], False),
            (0, [(5, 2), (6, 1)], False),
        ]
        for customer_index, picks, pay in plan:
            name, gstin, pos = CUSTOMERS[customer_index]
            invoice = create_invoice(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                customer_name=name,
                customer_gstin=gstin,
                customer_state_code=pos,
                place_of_supply=pos,
                notes="Seeded demo invoice",
                lines=[
                    {"item_id": int(items[item_index]["id"]), "qty": quantity}
                    for item_index, quantity in picks
                ],
            )
            created += 1
            if pay:
                order = create_order(conn, settings, tenant_id=tenant_id, user_id=user_id,
                                      invoice_id=invoice["id"])
                callback = simulate_signed_callback(conn, settings, tenant_id=tenant_id,
                                                    order_id=order["order_id"])
                verify_and_capture(
                    conn, settings, tenant_id=tenant_id, user_id=user_id,
                    invoice_id=invoice["id"], order_id=callback["order_id"],
                    payment_id=callback["payment_id"], signature=callback["signature"],
                )
        print(f"· issued {created} invoices (3 paid in test mode)")

    # one cancelled invoice, to exercise the reverse-stock path
    live = [invoice for invoice in list_invoices(conn, tenant_id) if invoice["status"] == "issued"]
    if live:
        try:
            cancel_invoice(conn, tenant_id=tenant_id, user_id=user_id, invoice_id=live[-1]["id"],
                           reason="customer changed their mind (demo)")
            print("· cancelled one invoice so the stock reversal is visible")
        except Exception as exc:  # noqa: BLE001 - demo script: report and continue
            print(f"· could not cancel demo invoice: {exc}")

    tenant = get_tenant(conn, tenant_id)
    return {"tenant": tenant, "email": DEMO_EMAIL, "password": DEMO_PASSWORD}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a demo BillBook tenant")
    parser.add_argument("--reset", action="store_true", help="delete the demo tenant first")
    args = parser.parse_args()

    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        init_db(conn)
        result = seed(conn, reset=args.reset)
    finally:
        conn.close()

    print("\nDone.")
    print(f"  database : {settings.db_path}")
    print(f"  sign in  : {result['email']} / {result['password']}")
    print(f"  shop     : {result['tenant']['name']} (state {result['tenant']['state_code']})")
    print("  start    : uvicorn app.main:app --reload --port 8100")


if __name__ == "__main__":
    main()
