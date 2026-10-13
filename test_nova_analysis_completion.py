"""Private temporary PostgreSQL tests; never use an environment database."""

import concurrent.futures
import time
import unittest
from unittest.mock import patch

import psycopg2
from psycopg2.extras import RealDictCursor

from combined_ingredient_analyzer import (
    batch_update_ingredients, update_ingredient_combined, get_fallback_result,
    run_full_analysis, validate_combined_result,
)
from nova_calculator import assign_nova_score, calculate_nova, recalculate_linked_products
from product_refresh_store import apply_preview, RefreshError
import test_product_refresh as refresh_tests

SKU = refresh_tests.SKU


def analysis(ingredient_id, category="natural", suspicion=None):
    return {"id": ingredient_id, "clean_name": "fixture",
            "category": category,
            "is_processed": False if category == "natural" else True,
            "suspicion_level": suspicion, "suspicion_category": None, "health_note": None}


class CompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh_tests.DatabaseTests.setUpClass.__func__(cls)
        with psycopg2.connect(cls.dsn) as conn, conn.cursor() as cur:
            cur.execute("""
                ALTER TABLE ingredient_analysis ADD category text DEFAULT 'uncategorized',
                    ADD clean_name text,ADD suspicion_category text,ADD health_note text;
            """)

    @classmethod
    def tearDownClass(cls):
        refresh_tests.DatabaseTests.tearDownClass.__func__(cls)

    execute = refresh_tests.DatabaseTests.execute
    preview = refresh_tests.DatabaseTests.preview

    def setUp(self):
        # Base seed uses positional INSERTs: supply values for the extra fields.
        # Seed before adding analysis columns, then restore them.
        self.execute("""
            ALTER TABLE ingredient_analysis DROP category,DROP clean_name,
                DROP suspicion_category,DROP health_note
        """)
        refresh_tests.DatabaseTests.setUp(self)
        self.execute("""
            ALTER TABLE ingredient_analysis ADD category text DEFAULT 'uncategorized',
                ADD clean_name text,ADD suspicion_category text,ADD health_note text;
            UPDATE ingredient_analysis SET is_processed=NULL,suspicion_level=NULL;
            UPDATE products SET nova_score=NULL,nova_source=NULL WHERE product_id=1;
            INSERT INTO ingredient_product_mapping VALUES (1,'untouched');
        """)

    def scores(self):
        return self.execute("SELECT nova_score,nova_source FROM products ORDER BY product_id")

    def save(self, results, dict_cursor=False):
        with psycopg2.connect(self.dsn, cursor_factory=RealDictCursor if dict_cursor else None) as conn:
            return batch_update_ingredients(conn, results)

    def test_shared_partial_then_complete_and_idempotent(self):
        self.save([analysis(1)])
        self.assertEqual(self.scores(), [(None, None), (3, "category_inherited")])
        self.save([analysis(2, "processed", "clean")], dict_cursor=True)
        self.assertEqual(self.scores(), [(1, "category_inherited"), (3, "category_inherited")])
        before = self.execute("SELECT xmin::text FROM products ORDER BY product_id")
        self.save([analysis(1), analysis(2, "processed", "clean")])
        self.assertEqual(before, self.execute("SELECT xmin::text FROM products ORDER BY product_id"))

    def test_completed_flavouring_marker_uses_existing_atomic_path(self):
        self.execute("UPDATE ingredient_analysis SET ingredient='aromatizētāji' WHERE id=1")
        result = dict(analysis(1, "processed", "caution"), suspicion_category="flavor_enhancer")
        self.save([result])
        self.assertEqual(self.scores(), [(4, "additive_override"), (4, "additive_override")])
        self.execute("UPDATE products SET nova_source='manual_override',nova_score=2 WHERE product_id=1")
        self.save([result])
        self.assertEqual(self.scores()[0], (2, "manual_override"))

    def test_additive_despite_unknown_then_failed_analysis_clears(self):
        with psycopg2.connect(self.dsn) as conn:
            update_ingredient_combined(conn, analysis(1, "processed", "limit"))
        self.assertEqual(self.scores(), [(4, "additive_override"), (4, "additive_override")])
        self.save([get_fallback_result("fixture", 1)])
        self.assertEqual(self.scores(), [(None, None), (None, None)])

    def test_manual_override_removed_links_and_unrelated_products(self):
        self.execute("""
            UPDATE products SET nova_score=2,nova_source='manual_override' WHERE product_id=1;
            DELETE FROM ingredient_product_mapping WHERE product_sku='untouched';
        """)
        before = self.execute("SELECT xmin::text FROM products ORDER BY product_id")
        self.save([analysis(1, "processed", "avoid")])
        self.assertEqual(self.scores(), [(2, "manual_override"), (1, "category_inherited")])
        self.assertEqual(before, self.execute("SELECT xmin::text FROM products ORDER BY product_id"))

    def test_current_category_missing_category_and_stale_clear(self):
        self.execute("UPDATE products SET rimi_category_code=5 WHERE product_id=1")
        self.save([analysis(1), analysis(2)])
        self.assertEqual(self.scores()[0], (3, "category_inherited"))
        self.execute("UPDATE products SET rimi_category_code=999 WHERE product_id=1")
        self.save([analysis(1)])
        self.assertEqual(self.scores()[0], (None, None))

    def test_save_failure_rolls_back_analysis_and_scores(self):
        before = self.execute("SELECT to_jsonb(i) FROM ingredient_analysis i ORDER BY id")
        scores = self.scores()
        with patch("combined_ingredient_analyzer.recalculate_linked_products",
                   side_effect=RuntimeError("fixture scoring failure")):
            with self.assertRaises(RuntimeError):
                self.save([analysis(1)])
        self.assertEqual(before, self.execute("SELECT to_jsonb(i) FROM ingredient_analysis i ORDER BY id"))
        self.assertEqual(scores, self.scores())

    def test_transient_conflict_retries_whole_transaction(self):
        class Conflict(Exception):
            pgcode = "40001"
        calls = []
        def recalc(conn, ids):
            calls.append(ids)
            if len(calls) == 1:
                raise Conflict()
            return recalculate_linked_products(conn, ids)
        with patch("combined_ingredient_analyzer.recalculate_linked_products", side_effect=recalc):
            self.save([analysis(1)])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.scores()[1], (3, "category_inherited"))

    def test_exhausted_conflict_and_nonexistent_id(self):
        class Conflict(Exception):
            pgcode = "40P01"
        with patch("combined_ingredient_analyzer.recalculate_linked_products",
                   side_effect=Conflict()) as recalc:
            with self.assertRaises(Conflict):
                self.save([analysis(1)])
            self.assertEqual(recalc.call_count, 3)
        self.assertEqual(self.execute("SELECT category FROM ingredient_analysis WHERE id=1")[0][0],
                         "uncategorized")
        self.assertEqual(self.save([analysis(999)]), 0)

    def test_preview_becomes_stale_when_analysis_finishes(self):
        preview = self.preview()
        self.save([analysis(1), analysis(2)])
        with self.assertRaisesRegex(RefreshError, "changed"):
            apply_preview(preview, self.dsn)

    def test_refresh_replaces_links_then_completion_uses_only_accepted_ingredients(self):
        apply_preview(self.preview(), self.dsn)
        self.assertEqual(self.scores()[0], (None, None))
        before = self.execute("SELECT xmin::text FROM products WHERE product_id=1")
        self.save([analysis(2, "processed", "avoid")])
        self.assertEqual(before, self.execute("SELECT xmin::text FROM products WHERE product_id=1"))
        self.save([analysis(1)])
        self.assertEqual(self.scores()[0], (None, None))  # New starter ingredient is still unknown.
        new_id = self.execute("SELECT id FROM ingredient_analysis WHERE ingredient='ieraugs'")[0][0]
        self.save([analysis(new_id)])
        self.assertEqual(self.scores()[0], (1, "category_inherited"))

    def test_concurrent_real_refresh_and_analysis_retry_or_reject_safely(self):
        from product_refresh_store import persist_ingredients
        preview = self.preview()
        scorer = psycopg2.connect(self.dsn)
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = None
            def persist_after_analysis_starts(cur, sku, tokens):
                nonlocal future
                # Apply already holds the product lock. Let analysis save its
                # ingredient row and contend on that product before replacing links.
                future = pool.submit(batch_update_ingredients, scorer,
                                     [analysis(1, "processed", "avoid")])
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    rows = self.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s",
                                        (scorer.get_backend_pid(),))
                    if rows and rows[0][0] == "Lock":
                        break
                    time.sleep(.01)
                else:
                    raise AssertionError("Analysis did not reach product lock")
                persist_ingredients(cur, sku, tokens)
            try:
                with patch("product_refresh_store.persist_ingredients",
                           side_effect=persist_after_analysis_starts):
                    try:
                        apply_preview(preview, self.dsn)
                    except RefreshError:
                        pass  # Apply explicitly rolls back and asks for a fresh preview.
                self.assertIsNotNone(future)
                self.assertEqual(future.result(timeout=10), 1)
                self.assertEqual(self.scores(), [(4, "additive_override"), (4, "additive_override")])
            finally:
                scorer.close()

    def test_full_analysis_failure_finishes_once_and_reports_pending(self):
        with patch.dict("os.environ", {"DATABASE_URL": self.dsn}), \
             patch("combined_ingredient_analyzer.analyze_ingredients_batch",
                   side_effect=lambda rows, **kwargs: [
                       get_fallback_result(r["ingredient"], r["id"]) for r in rows]) as analyze, \
             patch("combined_ingredient_analyzer.refresh_materialized_view"):
            result = run_full_analysis()
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(result["pending"], 2)
        self.assertEqual(self.scores(), [(None, None), (None, None)])

    def test_concurrent_mapping_removal_uses_post_lock_state(self):
        refresh = psycopg2.connect(self.dsn)
        scorer = psycopg2.connect(self.dsn)
        try:
            with refresh.cursor() as cur:
                cur.execute("SELECT product_id FROM products WHERE product_id=1 FOR UPDATE")
                cur.execute("DELETE FROM ingredient_product_mapping WHERE product_sku=%s", (SKU,))
                cur.execute("UPDATE products SET nova_score=2,nova_source='category_inherited' WHERE product_id=1")
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(batch_update_ingredients, scorer, [analysis(1, "processed", "avoid")])
                # Wait for actual row-lock contention, not an arbitrary sleep.
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    rows = self.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s",
                                        (scorer.get_backend_pid(),))
                    if rows and rows[0][0] == "Lock":
                        break
                    time.sleep(.01)
                else:
                    refresh.rollback()
                    self.fail("Scoring did not wait on refresh product lock")
                refresh.commit()
                self.assertEqual(future.result(timeout=5), 1)
            self.assertEqual(self.scores(), [(2, "category_inherited"), (4, "additive_override")])
        finally:
            refresh.close()
            scorer.close()

    def test_compatibility_entrypoint_clears_stale_and_unlocks_manual(self):
        self.execute("UPDATE products SET nova_score=4,nova_source='additive_override' WHERE product_id=1")
        with psycopg2.connect(self.dsn) as conn:
            result = assign_nova_score(conn, 1, "wrong-log-only-sku")
        self.assertTrue(result["updated"])
        self.assertEqual(result["reason"], "pending_analysis")
        self.assertEqual(self.scores()[0], (None, None))


class RuleTests(unittest.TestCase):
    def test_incomplete_ai_result_cannot_become_clean_analysis(self):
        for partial in (
            {"category": "processed"},
            {"category": "processed", "is_processed": True},
            {"category": "natural", "is_processed": True, "suspicion_level": None},
            {"category": "processed", "is_processed": True, "suspicion_level": "invalid"},
        ):
            result = validate_combined_result(partial, "fixture", 1)
            self.assertEqual(result["category"], "uncategorized")
            self.assertEqual(calculate_nova([result], 1)[2], "pending_analysis")

    def test_flavourings_are_processing_markers_not_harm_flags(self):
        marker = dict(analysis(1, "processed", "caution"), ingredient="aromatizētāji",
                      suspicion_category="flavor_enhancer")
        self.assertEqual(calculate_nova([marker, {}], 1),
                         (4, "additive_override", "flavouring_marker"))
        for change in ({"ingredient": "garšvielas"}, {"is_processed": None},
                       {"suspicion_category": None}, {"category": "uncategorized"}):
            self.assertNotEqual(calculate_nova([dict(marker, **change), {}], 1)[0], 4)
        self.assertEqual(calculate_nova([], 1)[2], "pending_analysis")
        salt = dict(analysis(1), ingredient="sāls")
        self.assertEqual(calculate_nova([salt], 1),
                         (None, None, "unsupported_preparation_default"))
        self.assertEqual(calculate_nova([salt], 3)[0], 3)

    def test_unknown_vs_completed_natural_and_legacy(self):
        self.assertEqual(calculate_nova([{}], 1), (None, None, "pending_analysis"))
        self.assertEqual(calculate_nova([analysis(1)], 1), (1, "category_inherited", "category"))
        self.assertEqual(calculate_nova([{"is_processed": False}], 1)[2], "pending_analysis")
        self.assertEqual(calculate_nova([{"is_processed": True, "suspicion_level": "none"}], 2)[0], 2)
        self.assertEqual(calculate_nova([], None)[2], "no_category")


if __name__ == "__main__":
    unittest.main()
