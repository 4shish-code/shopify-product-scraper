from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import Product

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    site_key    TEXT NOT NULL,
    domain      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    products    INTEGER DEFAULT 0,
    variants    INTEGER DEFAULT 0,
    images      INTEGER DEFAULT 0,
    requests    INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'running',
    error       TEXT
);

CREATE TABLE IF NOT EXISTS products (
    site_key    TEXT NOT NULL,
    product_id  INTEGER NOT NULL,
    handle      TEXT NOT NULL,
    title       TEXT,
    vendor      TEXT,
    ptype       TEXT,
    price_min   REAL,
    price_max   REAL,
    in_stock    INTEGER,
    n_variants  INTEGER,
    n_images    INTEGER,
    updated_at  TEXT,
    first_seen  TEXT,
    last_seen   TEXT,
    run_id      INTEGER,
    payload     TEXT NOT NULL,
    PRIMARY KEY (site_key, product_id)
);

CREATE INDEX IF NOT EXISTS idx_products_site   ON products(site_key);
CREATE INDEX IF NOT EXISTS idx_products_vendor ON products(vendor);
CREATE INDEX IF NOT EXISTS idx_products_handle ON products(handle);

CREATE TABLE IF NOT EXISTS price_history (
    site_key   TEXT NOT NULL,
    product_id INTEGER NOT NULL,
    variant_id INTEGER,
    sku        TEXT,
    price      REAL,
    compare_at REAL,
    available  INTEGER,
    seen_at    TEXT NOT NULL,
    run_id     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_hist ON price_history(site_key, product_id, variant_id, seen_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def start_run(self, site_key: str, domain: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (site_key, domain, started_at) VALUES (?,?,?)",
            (site_key, domain, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, *, products=0, variants=0, images=0,
                   requests=0, status="ok", error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, products=?, variants=?, images=?, "
            "requests=?, status=?, error=? WHERE id=?",
            (_now(), products, variants, images, requests, status, error, run_id),
        )
        self.conn.commit()

    def runs(self, limit: int = 20, site_key: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM runs"
        args: list = []
        if site_key:
            q += " WHERE site_key=?"
            args.append(site_key)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return self.conn.execute(q, args).fetchall()

    def upsert(self, products: list[Product], run_id: int) -> tuple[int, int]:
        now = _now()
        new = updated = 0
        for p in products:
            row = self.conn.execute(
                "SELECT first_seen FROM products WHERE site_key=? AND product_id=?",
                (p.site_key, p.id),
            ).fetchone()
            first_seen = row["first_seen"] if row else now
            if row:
                updated += 1
            else:
                new += 1

            self.conn.execute(
                """INSERT INTO products
                   (site_key, product_id, handle, title, vendor, ptype, price_min, price_max,
                    in_stock, n_variants, n_images, updated_at, first_seen, last_seen, run_id, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(site_key, product_id) DO UPDATE SET
                     handle=excluded.handle, title=excluded.title, vendor=excluded.vendor,
                     ptype=excluded.ptype, price_min=excluded.price_min, price_max=excluded.price_max,
                     in_stock=excluded.in_stock, n_variants=excluded.n_variants,
                     n_images=excluded.n_images, updated_at=excluded.updated_at,
                     last_seen=excluded.last_seen, run_id=excluded.run_id, payload=excluded.payload
                """,
                (p.site_key, p.id, p.handle, p.title, p.vendor, p.product_type,
                 float(p.price_min or 0), float(p.price_max or 0), int(p.in_stock),
                 len(p.variants), len(p.images), p.updated_at, first_seen, now, run_id,
                 json.dumps(p.to_dict(), ensure_ascii=False)),
            )

            for v in p.variants:
                self.conn.execute(
                    "INSERT INTO price_history (site_key, product_id, variant_id, sku, price, "
                    "compare_at, available, seen_at, run_id) VALUES (?,?,?,?,?,?,?,?,?)",
                    (p.site_key, p.id, v.id, v.sku,
                     float(v.price or 0), float(v.compare_at_price or 0),
                     int(v.available), now, run_id),
                )
        self.conn.commit()
        return new, updated

    def load(self, site_keys: list[str] | None = None) -> list[Product]:
        from .models import Product as P, Variant, Image
        q = "SELECT payload FROM products"
        args: list = []
        if site_keys:
            q += f" WHERE site_key IN ({','.join('?' * len(site_keys))})"
            args = list(site_keys)
        q += " ORDER BY site_key, title"

        out: list[P] = []
        for row in self.conn.execute(q, args):
            d = json.loads(row["payload"])
            d["variants"] = [Variant(**v) for v in d.get("variants", [])]
            d["images"] = [Image(**i) for i in d.get("images", [])]
            out.append(P(**d))
        return out

    def summary(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT site_key,
                      COUNT(*)                AS products,
                      SUM(n_variants)         AS variants,
                      SUM(n_images)           AS images,
                      SUM(in_stock)           AS in_stock,
                      ROUND(MIN(NULLIF(price_min,0)),2) AS min_price,
                      ROUND(MAX(price_max),2) AS max_price,
                      MAX(last_seen)          AS last_seen
               FROM products GROUP BY site_key ORDER BY products DESC"""
        ).fetchall()

    def price_changes(self, site_key: str | None = None, limit: int = 200) -> list[sqlite3.Row]:
        q = """
        WITH ranked AS (
          SELECT h.*, ROW_NUMBER() OVER
                 (PARTITION BY site_key, product_id, variant_id ORDER BY seen_at DESC, rowid DESC) rn
          FROM price_history h
          {where}
        ),
        latest AS (SELECT * FROM ranked WHERE rn = 1),
        prev AS (
          SELECT r.* FROM ranked r JOIN latest l
            ON r.site_key=l.site_key AND r.product_id=l.product_id
           AND IFNULL(r.variant_id,-1)=IFNULL(l.variant_id,-1)
          WHERE r.rn > 1 AND r.price <> l.price
          GROUP BY r.site_key, r.product_id, r.variant_id
          HAVING MIN(r.rn)
        )
        SELECT p.title, l.site_key, l.sku, prev.price AS old_price, l.price AS new_price,
               ROUND((l.price - prev.price) * 100.0 / NULLIF(prev.price,0), 1) AS pct,
               l.seen_at
        FROM latest l
        JOIN prev  ON prev.site_key=l.site_key AND prev.product_id=l.product_id
                  AND IFNULL(prev.variant_id,-1)=IFNULL(l.variant_id,-1)
        JOIN products p ON p.site_key=l.site_key AND p.product_id=l.product_id
        ORDER BY ABS(pct) DESC LIMIT ?
        """
        where = "WHERE site_key = ?" if site_key else ""
        args = ([site_key] if site_key else []) + [limit]
        return self.conn.execute(q.format(where=where), args).fetchall()

    def purge(self, site_key: str | None = None) -> int:
        if site_key:
            n = self.conn.execute("DELETE FROM products WHERE site_key=?", (site_key,)).rowcount
            self.conn.execute("DELETE FROM price_history WHERE site_key=?", (site_key,))
            self.conn.execute("DELETE FROM runs WHERE site_key=?", (site_key,))
        else:
            n = self.conn.execute("DELETE FROM products").rowcount
            self.conn.execute("DELETE FROM price_history")
            self.conn.execute("DELETE FROM runs")
        self.conn.commit()
        return n

    def close(self):
        self.conn.close()

    @contextmanager
    def session(self):
        try:
            yield self
        finally:
            self.close()
