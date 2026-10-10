"""No live APIs/application DBs. Optional SQL/UI tests use an isolated local socket.

python test_enrichment_availability.py /tmp/enrichment-availability-db.XXXXXX
Restore docs/database-share/schema.sql into that empty local DB first (port 55442).
"""

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import psycopg2
from streamlit.testing.v1 import AppTest

from nutrition_enrichment_service import (
    EnrichmentBatch, EnrichmentMatch, NutritionEnrichmentService, ProductForEnrichment,
)
from food_translator import TranslationResult
from usda_enrichment import NutritionData, USDAFoodMatch

SOCKET = None


def match(product_id, status="pending"):
    product = ProductForEnrichment(product_id, str(product_id), f"Product {product_id}")
    return EnrichmentMatch(
        product, TranslationResult(product.name, product.name, "test", 1),
        [USDAFoodMatch(product_id, product.name, "test", 100,
                       nutrition=NutritionData(energy_kcal=24, energy_kj=100,
                                               fat_total=1, fat_saturated=0.1,
                                               carbs_total=2, carbs_sugars=1,
                                               protein=0, salt=0, fiber=2.5))],
        status=status,
    )


class BatchRefreshTests(unittest.TestCase):
    def service(self, rows=()):
        service = NutritionEnrichmentService.__new__(NutritionEnrichmentService)
        conn, cur = MagicMock(), MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        cur.fetchall.return_value = list(rows)
        service._get_connection = Mock(return_value=conn)
        service.status_callback = Mock()
        return service, conn, cur

    def test_pruning_keeps_objects_options_and_accurate_counts(self):
        service, conn, _ = self.service([(1, True, False), (3, False, True)])
        kept = match(1, "skipped")
        approved = match(3, "approved")
        batch = EnrichmentBatch([kept, match(2), approved, match(4, "no_match")])
        self.assertEqual(service.refresh_batch_availability(batch), 2)
        self.assertEqual(batch.matches, [kept, approved])
        self.assertIs(batch.matches[0], kept)
        self.assertEqual((batch.total, batch.skipped, batch.approved, batch.pending), (2, 1, 1, 0))
        conn.commit.assert_not_called()
        conn.close.assert_called()

    def test_reviewed_pending_entries_removed_but_approved_history_retained(self):
        service, _, _ = self.service([(1, False, True), (2, False, True)])
        batch = EnrichmentBatch([match(1), match(2, "approved")])
        self.assertEqual(service.refresh_batch_availability(batch), 1)
        self.assertEqual([m.product.product_id for m in batch.matches], [2])

    def test_all_unavailable_yields_empty_batch_without_writes(self):
        service, conn, _ = self.service()
        batch = EnrichmentBatch([match(1), match(2, "approved")])
        self.assertEqual(service.refresh_batch_availability(batch), 2)
        self.assertEqual(batch.total, 0)
        conn.commit.assert_not_called()

    def test_empty_batch_does_not_connect(self):
        service, _, _ = self.service()
        self.assertEqual(service.refresh_batch_availability(EnrichmentBatch()), 0)
        service._get_connection.assert_not_called()

    def test_stale_actions_are_blocked_before_updates(self):
        for action in ("save_enrichment", "skip_product", "unskip_product"):
            service, conn, cur = self.service()
            cur.fetchone.return_value = None
            self.assertFalse(getattr(service, action)(match(1)))
            conn.commit.assert_not_called()
            conn.rollback.assert_called()
            self.assertEqual(cur.execute.call_count, 1)
            self.assertIn("FOR UPDATE", cur.execute.call_args.args[0])


@unittest.skipUnless(SOCKET, "Requires isolated local PostgreSQL socket")
class SQLAndTabTests(unittest.TestCase):
    def connect(self):
        return psycopg2.connect(host=SOCKET, port=55442, user="runner", dbname="postgres")

    def setUp(self):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE products, normalized_categories RESTART IDENTITY CASCADE")
            cur.execute("""
                INSERT INTO normalized_categories(category_id,name_lv,normalized_category,level)
                VALUES(1,'Category One','one',1),(2,'Category Two','two',1)
            """)
            self.ids = {}
            for index, letter in enumerate("ABCDEFGHIJKL"):
                flag = None if letter == "I" else letter not in "IJKL"
                reviewed = letter in "HL"
                if letter == "E":
                    reviewed = None
                source = "usda_api" if letter in "AK" else "rimi_scraped" if letter == "H" else None
                cur.execute("""
                    INSERT INTO products(sku,name,category_id,needs_enrichment,
                        enrichment_reviewed,enrichment_skipped,nutrition_source)
                    VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING product_id
                """, (letter, "Product " + letter, 2 if letter in "DG" else 1,
                      flag, reviewed, letter == "D", source))
                pid = cur.fetchone()[0]
                self.ids[letter] = pid
                cur.execute("INSERT INTO nutritionfacts(product_id,energy_kj,energy_kcal) VALUES(%s,%s,%s)",
                            (pid, 100 if letter == "K" else 0, 24 if letter == "K" else 0))
                if letter != "C":
                    cur.execute("""
                        INSERT INTO product_price_history(product_id,price,is_available,recorded_at)
                        VALUES(%s,1,%s,'2026-01-01T00:00:00Z')
                    """, (pid, letter not in "AEG"))
                    if letter in "ABEFGJ":
                        cur.execute("""
                            INSERT INTO product_price_history(product_id,price,is_available,recorded_at)
                            VALUES(%s,1,%s,%s)
                        """, (pid, letter in "AEG",
                              "2026-01-01T00:00:00Z" if letter in "FG" else "2026-01-02T00:00:00Z"))
        self.service = NutritionEnrichmentService.__new__(NutritionEnrichmentService)
        self.service._get_connection = self.connect
        self.service.status_callback = Mock()
        self.service._calculate_nutriscore = Mock(return_value=(None, None))
        self.service.process_batch = Mock(
            side_effect=lambda products: EnrichmentBatch([match(p.product_id) for p in products]))

    def availability(self, letter, value):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO product_price_history(product_id,price,is_available,recorded_at)
                VALUES(%s,1,%s,'2026-01-03T00:00:00Z')
            """, (self.ids[letter], value))

    def snapshot(self):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_jsonb(p) FROM products p ORDER BY product_id")
            return cur.fetchall()

    def test_latest_record_counts_and_historical_metrics(self):
        self.assertEqual(self.service.get_enrichment_stats(), {
            "needs_enrichment": 4, "reviewed": 2, "from_usda": 2,
            "from_rimi": 1, "skipped": 1, "total": 12,
        })

    def test_category_totals_and_no_duplicates(self):
        categories = self.service.get_categories_needing_enrichment()
        self.assertEqual([(c["category_id"], c["product_count"]) for c in categories], [(1, 2), (2, 2)])
        products = self.service.get_products_needing_enrichment(limit=20)
        self.assertEqual([p.sku for p in products], ["A", "E", "G", "D"])

    def test_category_pagination_and_skipped_last(self):
        self.assertEqual([p.sku for p in self.service.get_products_needing_enrichment(2, 1)], ["E", "G"])
        self.assertEqual([p.sku for p in self.service.get_products_needing_enrichment(1, 1, 2)], ["D"])
        self.assertEqual(self.service.get_products_needing_enrichment(category_id=99), [])

    def test_available_only_warning_and_explicit_scan(self):
        before = self.snapshot()
        self.assertEqual(self.service.get_unflagged_missing_count(), 1)
        self.assertEqual(self.service.scan_and_flag_products(), {"flagged": 1})
        after = self.snapshot()
        for (old,), (new,) in zip(before, after):
            if old["sku"] == "I":
                self.assertTrue(new["needs_enrichment"])
                for key in old:
                    if key not in {"needs_enrichment", "updated_at"}:
                        self.assertEqual(new[key], old[key])
            else:
                self.assertEqual(old, new)
        self.assertEqual(self.service.get_unflagged_missing_count(), 0)
        self.assertEqual(self.service.get_enrichment_stats()["needs_enrichment"], 5)

    def test_queue_reads_leave_flags_and_timestamps_unchanged(self):
        before = self.snapshot()
        self.service.get_enrichment_stats()
        self.service.get_categories_needing_enrichment()
        self.service.get_products_needing_enrichment()
        self.service.get_unflagged_missing_count()
        self.assertEqual(self.snapshot(), before)

    def test_unavailable_and_missing_history_preserve_flags(self):
        before = self.snapshot()
        self.availability("A", False)
        self.assertEqual(self.service.get_enrichment_stats()["needs_enrichment"], 3)
        self.assertEqual(self.snapshot(), before)
        self.availability("A", True)
        self.assertEqual(self.service.get_enrichment_stats()["needs_enrichment"], 4)
        self.assertEqual(self.snapshot(), before)

    def test_stale_batch_pruning_does_not_reprocess_or_write_flags(self):
        batch = EnrichmentBatch([match(self.ids["A"]), match(self.ids["B"]),
                                 match(self.ids["D"], "skipped"), match(self.ids["C"])])
        before = self.snapshot()
        self.assertEqual(self.service.refresh_batch_availability(batch), 2)
        self.assertEqual([m.product.product_id for m in batch.matches], [self.ids["A"], self.ids["D"]])
        self.assertEqual(self.snapshot(), before)
        self.service.process_batch.assert_not_called()

    def test_stale_writes_are_blocked_and_available_action_still_works(self):
        before = self.snapshot()
        for action in ["save_enrichment", "skip_product", "unskip_product"]:
            self.assertFalse(getattr(self.service, action)(match(self.ids["B"])))
        self.assertEqual(self.snapshot(), before)
        available = match(self.ids["A"])
        self.assertTrue(self.service.save_enrichment(available))
        self.assertEqual(available.status, "approved")
        self.assertEqual(self.service.get_enrichment_stats()["needs_enrichment"], 3)

    def app(self):
        source = Path("main.py").read_text()
        node = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef) and n.name == "section_nutrition_enrichment")
        section = "\n".join(source.splitlines()[node.lineno-1:node.end_lineno])
        return AppTest.from_string("import streamlit as st\n" + section +
                                   "\nsection_nutrition_enrichment()\n", default_timeout=20)

    def button(self, app, label):
        return next(b for b in app.button if b.label == label)

    def test_rendered_tab_counts_batches_and_available_scan_warning(self):
        with patch("nutrition_enrichment_service.NutritionEnrichmentService", return_value=self.service):
            app = self.app().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "4")
            self.assertIn("1 available products", app.warning[0].value)
            self.assertIn("latest scraped availability", app.caption[1].value)
            self.button(app, "🔄 Load Batch").click().run()
            self.assertFalse(app.exception)
            batch = app.session_state["enrichment_batch"]
            self.assertEqual([m.product.product_id for m in batch.matches],
                             [self.ids[l] for l in "AEGD"])
            self.assertEqual(self.service.process_batch.call_count, 1)
            self.assertEqual(len(app.expander), 4)
            self.availability("A", False)
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "3")
            self.assertEqual(len(app.expander), 3)
            self.assertEqual(self.service.process_batch.call_count, 1)
            self.assertNotIn(self.ids["A"], [m.product.product_id for m in batch.matches])
            self.assertEqual({s.key for s in app.selectbox if s.key},
                             {f"select_{self.ids[l]}" for l in "EGD"})

    def test_rendered_bulk_action_excludes_newly_unavailable_product(self):
        with patch("nutrition_enrichment_service.NutritionEnrichmentService", return_value=self.service):
            app = self.app().run()
            self.button(app, "🔄 Load Batch").click().run()
            self.availability("A", False)
            self.button(app, "✅ Approve All Matches").click().run()
            self.assertFalse(app.exception)
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT needs_enrichment,enrichment_reviewed FROM products WHERE sku='A'")
                self.assertEqual(cur.fetchone(), (True, False))
            self.assertEqual(app.metric[0].value, "0")
            self.assertEqual(app.session_state["enrichment_batch"].approved, 3)

    def test_loading_again_replaces_cached_batch_and_category_filter(self):
        with patch("nutrition_enrichment_service.NutritionEnrichmentService", return_value=self.service):
            app = self.app().run()
            self.button(app, "🔄 Load Batch").click().run()
            app.selectbox[1].select("Category Two (2)").run()
            self.button(app, "🔄 Load Batch").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(self.service.process_batch.call_count, 2)
            batch = app.session_state["enrichment_batch"]
            self.assertEqual([m.product.product_id for m in batch.matches], [self.ids[l] for l in "GD"])

    def test_empty_cached_batch_clears_without_new_api_processing(self):
        with patch("nutrition_enrichment_service.NutritionEnrichmentService", return_value=self.service):
            app = self.app().run()
            self.button(app, "🔄 Load Batch").click().run()
            for letter in "AEGD":
                self.availability(letter, False)
            app.run()
            self.assertFalse(app.exception)
            self.assertIsNone(app.session_state["enrichment_batch"])
            self.assertFalse(app.session_state["enrichment_processing"])
            self.assertEqual(self.service.process_batch.call_count, 1)
            self.assertEqual(app.metric[0].value, "0")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].startswith("/tmp/enrichment-availability-db."):
        SOCKET = str(Path(sys.argv.pop(1)).resolve())
        if not SOCKET.startswith("/tmp/enrichment-availability-db."):
            raise ValueError("Only isolated test socket directories are allowed")
        SQLAndTabTests.__unittest_skip__ = False
        with psycopg2.connect(host=SOCKET, port=55442, user="runner", dbname="postgres") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM products")
                if cur.fetchone()[0]:
                    raise ValueError("Requires an empty isolated local database")
    unittest.main(verbosity=2)
