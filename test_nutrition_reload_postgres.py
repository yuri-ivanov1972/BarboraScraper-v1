"""Integration checks for an EMPTY isolated local PostgreSQL test instance.

Usage: python test_nutrition_reload_postgres.py /tmp/nutrition-reload-db.XXXXXX
The schema must already be restored there. Never connects to application DBs.
"""

import sys
from pathlib import Path
from unittest.mock import Mock

import psycopg2
from psycopg2.extras import RealDictCursor

from nutrition_reload_plan import propose
from nutrition_reload_source import parse_page
from nutrition_reload_store import apply_one, capture
from test_nutrition_reload import SKU, page


def run(socket):
    socket = str(Path(socket).resolve())
    if not socket.startswith("/tmp/nutrition-reload-db."):
        raise ValueError("Only isolated temporary test socket directories are allowed")
    conn = psycopg2.connect(host=socket, port=55441, user="runner", dbname="postgres")
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM products")
        if cur.fetchone()[0]:
            raise ValueError("Integration test requires an empty temporary database")
        cur.execute("INSERT INTO normalized_categories(category_id,name_lv,normalized_category,level) VALUES(1,'Test','test',1)")
        for sku, manual in [(SKU, False), ("protected", True), ("concurrent", False)]:
            cur.execute("""
                INSERT INTO products(sku,name,name_norm,category_id,needs_enrichment,
                    enrichment_reviewed,enrichment_skipped,name_manual_edit,ingredients)
                VALUES(%s,'Old name','old name',1,TRUE,FALSE,TRUE,%s,'stored ingredients')
            """, (sku, manual))
    conn.commit()
    conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
    snapshot = capture(conn, "test", False)
    assert len(snapshot["rows"]) == 3
    with conn.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        assert cur.fetchone()[0] == "on"
        try:
            cur.execute("UPDATE products SET name='should fail'")
        except psycopg2.errors.ReadOnlySqlTransaction:
            pass
        else:
            raise AssertionError("Read-only snapshot accepted a write")
    conn.rollback()
    conn.set_session(readonly=False, isolation_level="READ COMMITTED")
    calculator = Mock()
    calculator.calculate_single_product.return_value = {"success": True, "grade": "B", "score": 2}
    for row in snapshot["rows"]:
        row["proposal"] = propose(row, parse_page(page(sku=row["product"]["sku"])), calculator)
    row = snapshot["rows"][0]
    assert apply_one(conn, row) == "updated"
    assert apply_one(conn, row) == "already_applied_or_matches_approved_state"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT to_jsonb(p) AS p,to_jsonb(nf) AS nf FROM products p
            JOIN nutritionfacts nf USING(product_id) WHERE p.product_id=%s
        """, (row["product"]["product_id"],))
        after = cur.fetchone()
        product, nutrition = after["p"], after["nf"]
        assert product["name"] == "New name" and not product["needs_enrichment"]
        assert product["enrichment_skipped"] and product["ingredients"] == "stored ingredients"
        assert nutrition["energy_kj"] == 100 and nutrition["nutri_score_grade"] == "B"
        assert nutrition["fiber"] == 0 and nutrition["is_fiber_correct"]
        assert nutrition["usda_fdc_id"] is None
        for key, value in row["product"].items():
            if key not in {"name", "name_norm", "nutrition_source", "needs_enrichment", "updated_at"}:
                assert product[key] == value, key
    conn.rollback()
    protected = snapshot["rows"][1]
    assert apply_one(conn, protected) == "updated"
    with conn.cursor() as cur:
        cur.execute("SELECT name,name_manual_edit,needs_enrichment FROM products WHERE product_id=%s",
                    (protected["product"]["product_id"],))
        assert cur.fetchone() == ("Old name", True, False)
    conn.rollback()
    concurrent = snapshot["rows"][2]
    with conn.cursor() as cur:
        cur.execute("UPDATE products SET name='Edited now',name_manual_edit=TRUE WHERE product_id=%s",
                    (concurrent["product"]["product_id"],))
    conn.commit()
    assert apply_one(conn, concurrent) == "baseline_changed"
    with conn.cursor() as cur:
        cur.execute("UPDATE products SET needs_enrichment=TRUE WHERE product_id=%s",
                    (row["product"]["product_id"],))
        cur.execute("UPDATE nutritionfacts SET ingredients_text='Keep this' WHERE product_id=%s",
                    (row["product"]["product_id"],))
    conn.commit()
    conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
    refresh = capture(conn, "test", False)
    conn.rollback()
    conn.set_session(readonly=False, isolation_level="READ COMMITTED")
    row = next(r for r in refresh["rows"] if r["product"]["sku"] == SKU)
    candidate = parse_page(page())
    candidate["nutrition"]["protein"] = 2
    row["proposal"] = propose(row, candidate, calculator)
    assert apply_one(conn, row) == "updated"
    with conn.cursor() as cur:
        cur.execute("SELECT protein,ingredients_text FROM nutritionfacts WHERE product_id=%s",
                    (row["product"]["product_id"],))
        assert cur.fetchone() == (2, "Keep this")
        for table in ["product_price_history", "productphotos", "category_processing_jobs"]:
            cur.execute("SELECT count(*) FROM " + table)
            assert cur.fetchone()[0] == 0
    conn.rollback()
    conn.close()
    print("PASS: local PostgreSQL read-only enforcement, new/existing nutrition writes, unrelated-field preservation, skipped eligibility, manual name protection, resume idempotence and concurrent-edit rejection.")


if __name__ == "__main__":
    run(sys.argv[1])
