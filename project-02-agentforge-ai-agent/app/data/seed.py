"""Create the sandbox commerce database used by the sqlite_query tool.

Deterministic (fixed RNG seed) so demos and tests always see the same numbers.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from ..config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  country     TEXT NOT NULL,
  segment     TEXT NOT NULL,
  signup_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  category   TEXT NOT NULL,
  unit_price REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  id          INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  order_date  TEXT NOT NULL,
  status      TEXT NOT NULL,
  total       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
  id         INTEGER PRIMARY KEY,
  order_id   INTEGER NOT NULL REFERENCES orders(id),
  product_id INTEGER NOT NULL REFERENCES products(id),
  quantity   INTEGER NOT NULL,
  unit_price REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
"""

FIRST = ["Ada", "Grace", "Alan", "Katherine", "Linus", "Margaret", "Dennis", "Barbara", "Ken", "Radia",
         "Edsger", "Frances", "Tim", "Anita", "Guido", "Shafi", "Yann", "Fei-Fei", "Andrew", "Daphne"]
LAST = ["Lovelace", "Hopper", "Turing", "Johnson", "Torvalds", "Hamilton", "Ritchie", "Liskov", "Thompson",
        "Perlman", "Dijkstra", "Allen", "Berners-Lee", "Borg", "van Rossum", "Goldwasser", "LeCun", "Li",
        "Ng", "Koller"]
COUNTRIES = ["United States", "India", "Germany", "United Kingdom", "Singapore", "Brazil", "Japan", "Australia"]
SEGMENTS = ["startup", "smb", "enterprise"]
CATEGORIES = {
    "analytics": [("Insight Dashboard", 149.0), ("Event Pipeline", 399.0), ("Cohort Explorer", 249.0)],
    "infrastructure": [("Managed Postgres", 199.0), ("Edge Cache", 89.0), ("Queue Cluster", 279.0)],
    "ai": [("Embedding API", 59.0), ("Agent Runtime", 499.0), ("Eval Harness", 179.0)],
    "support": [("Helpdesk Seat", 29.0), ("Knowledge Base", 79.0), ("Onboarding Pack", 120.0)],
}
STATUS_WEIGHTS = [("completed", 0.74), ("cancelled", 0.12), ("refunded", 0.08), ("pending", 0.06)]


def create_database(path: str | Path | None = None, *, force: bool = False) -> Path:
    target = Path(path or settings.sqlite_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        return target

    rng = random.Random(20260101)
    conn = sqlite3.connect(target)
    try:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM order_items")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM customers")

        # ---- customers
        customers = []
        used_names: set[str] = set()
        for cid in range(1, 41):
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            while name in used_names:
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)} {cid}"
            used_names.add(name)
            signup = date(2024, 1, 1) + timedelta(days=rng.randint(0, 500))
            customers.append(
                (cid, name, rng.choice(COUNTRIES), rng.choice(SEGMENTS), signup.isoformat())
            )
        conn.executemany(
            "INSERT INTO customers (id, name, country, segment, signup_date) VALUES (?, ?, ?, ?, ?)",
            customers,
        )

        # ---- products
        products = []
        pid = 1
        for category, items in CATEGORIES.items():
            for name, price in items:
                products.append((pid, name, category, price))
                pid += 1
        conn.executemany(
            "INSERT INTO products (id, name, category, unit_price) VALUES (?, ?, ?, ?)", products
        )

        # ---- orders + items (12 months of history, mild growth trend)
        statuses = [s for s, _ in STATUS_WEIGHTS]
        weights = [w for _, w in STATUS_WEIGHTS]
        order_id = 1
        item_id = 1
        today = date(2026, 1, 1)
        for month_offset in range(12):
            month_start = today - timedelta(days=30 * (11 - month_offset))
            orders_this_month = 18 + month_offset * 2
            for _ in range(orders_this_month):
                customer = rng.choice(customers)
                order_date = month_start + timedelta(days=rng.randint(0, 27))
                status = rng.choices(statuses, weights=weights, k=1)[0]
                line_count = rng.randint(1, 4)
                chosen = rng.sample(products, line_count)
                total = 0.0
                items = []
                for product in chosen:
                    quantity = rng.randint(1, 4)
                    unit_price = round(product[3] * rng.uniform(0.9, 1.05), 2)
                    total += quantity * unit_price
                    items.append((item_id, order_id, product[0], quantity, unit_price))
                    item_id += 1
                conn.execute(
                    "INSERT INTO orders (id, customer_id, order_date, status, total) VALUES (?, ?, ?, ?, ?)",
                    (order_id, customer[0], order_date.isoformat(), status, round(total, 2)),
                )
                conn.executemany(
                    "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price) "
                    "VALUES (?, ?, ?, ?, ?)",
                    items,
                )
                order_id += 1

        conn.commit()
    finally:
        conn.close()
    return target


if __name__ == "__main__":
    db_path = create_database(force=True)
    with sqlite3.connect(db_path) as check:
        for table in ("customers", "products", "orders", "order_items"):
            count = check.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table:12s} {count:5d} rows")
    print(f"\nDemo database ready at {db_path}")
