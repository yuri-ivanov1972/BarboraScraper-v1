"""Isolated PostgreSQL and HTTP fixtures; no application/production database access."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg2

from photo_maintenance import PhotoMaintenance, check_image, normalize_url

OLD = "https://cdn.barbora.lv/products/old.png"
NEW = "https://cdn.barbora.lv/products/new.png"
SECONDARY = "https://cdn.barbora.lv/products/secondary.png"


class HTTPTests(unittest.TestCase):
    def response(self, code, content=b"\x89PNG\r\n\x1a\nabc", mime="image/png"):
        session = MagicMock()
        response = session.get.return_value.__enter__.return_value
        response.status_code = code
        response.headers = {"Content-Type": mime}
        response.iter_content.return_value = iter([content])
        return session

    def test_classification(self):
        for code, result in [(200, "working"), (206, "working"), (403, "access_blocked"),
                             (429, "access_blocked"), (404, "missing_evidence"),
                             (410, "missing_evidence"), (502, "temporary_failure"),
                             (302, "temporary_failure")]:
            with self.subTest(code=code):
                self.assertEqual(check_image(OLD, self.response(code))[0], result)
        self.assertEqual(check_image(OLD, self.response(200, b"<html>", "text/html"))[0],
                         "invalid_content")
        self.assertEqual(check_image(OLD, self.response(200, b"<html>"))[0], "invalid_content")

    def test_normalization_and_private_hosts(self):
        self.assertEqual(normalize_url(NEW + "#fragment"), NEW)
        for url in ("http://cdn.barbora.lv/a", "https://localhost/a",
                    "https://cdn.barbora.lv.evil.com/a", "https://user@cdn.barbora.lv/a",
                    "https://cdn.barbora.lv:99/a", "https://cdn.barbora.lv/placeholder.png"):
            self.assertIsNone(normalize_url(url))


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="photo-tests-")
        cls.root = Path(cls.temp.name)
        cls.data = cls.root / "pg"
        subprocess.run(["initdb", "-D", str(cls.data), "-U", "fixture", "-A", "trust",
                        "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-l", str(cls.root / "pg.log"),
                        "-o", f"-k {cls.root} -h '' -p 6547", "-w", "start"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.service = PhotoMaintenance(f"host={cls.root} port=6547 dbname=postgres user=fixture")
        with cls.service.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE products(product_id int PRIMARY KEY,sku text,name text,barbora_url text);
                CREATE TABLE productphotos(photo_id serial PRIMARY KEY,product_id int,
                    photo_url text,is_primary bool);
                CREATE TABLE product_price_history(product_id int,is_available bool,recorded_at timestamptz);
            """)
        conn.close()
        cls.service.initialize()

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-m", "immediate", "stop"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.temp.cleanup()

    def sql(self, query, args=None):
        with self.service.connect() as conn, conn.cursor() as cur:
            cur.execute(query, args)
            rows = cur.fetchall() if cur.description else []
        conn.close()
        return rows

    def setUp(self):
        self.sql("""TRUNCATE products,productphotos,product_price_history,photo_maintenance,
                    photo_host_cooldown,photo_url_verification CASCADE;
                    UPDATE photo_maintenance_config SET leased_until=NULL,enabled=false;
                    INSERT INTO products VALUES (1,'sku1','First','https://barbora.lv/produkti/first'),
                      (2,'sku2','Unavailable','https://barbora.lv/produkti/second');
                    INSERT INTO product_price_history VALUES (1,true,now()),(2,false,now());""")
        self.sql("INSERT INTO productphotos(product_id,photo_url,is_primary) VALUES (1,%s,true),(1,%s,false),(2,%s,true)",
                 (OLD, SECONDARY, OLD))
        with self.service.connect() as conn, conn.cursor() as cur:
            self.service.observe(cur, 1, NEW)
        conn.close()

    def test_preview_and_secondary_coverage(self):
        with patch("photo_maintenance.check_image", return_value=("working", 200)):
            results = self.service.run()
        self.assertEqual({r["checked_url"] for r in results}, {NEW, OLD, SECONDARY})
        self.assertEqual(self.sql("SELECT count(*) n FROM photo_url_verification")[0]["n"], 0)
        self.assertEqual(self.sql("SELECT photo_url FROM productphotos WHERE product_id=1 AND is_primary")[0]["photo_url"], OLD)

    def test_unknown_then_retailer_replacement_and_idempotence(self):
        with patch("photo_maintenance.check_image", return_value=("working", 200)):
            results = self.service.run(apply=True)
            self.assertTrue(any("Review ownership" in r["outcome"] for r in results))
            self.service.set_ownership(1, "retailer")
            self.service.run(apply=True)
            self.assertEqual(self.service.run(apply=True), [])
        self.assertEqual(self.sql("SELECT photo_url FROM productphotos WHERE product_id=1 ORDER BY is_primary DESC")[0]["photo_url"], NEW)
        self.assertEqual(self.sql("SELECT count(*) n FROM productphotos WHERE product_id=1")[0]["n"], 2)

    def test_manual_protection(self):
        self.service.set_ownership(1, "manual")
        with patch("photo_maintenance.check_image") as check:
            self.assertEqual(self.service.run(apply=True), [])
            check.assert_not_called()

    def test_host_cooldown(self):
        with patch("photo_maintenance.check_image", return_value=("access_blocked", 403)) as check:
            self.assertEqual(len(self.service.run(apply=True)), 1)
            self.assertEqual(self.service.run(apply=True), [])
            self.assertEqual(check.call_count, 1)
        self.assertEqual(self.sql("SELECT status FROM photo_url_verification")[0]["status"], "access_blocked")

    def test_repeat_missing_requires_separate_day(self):
        with patch("photo_maintenance.check_image", return_value=("missing_evidence", 404)):
            self.service.run(apply=True, limit=1)
            self.sql("UPDATE photo_url_verification SET next_due=now()")
            self.service.run(apply=True, limit=1)
        self.assertFalse(self.sql("SELECT 1 FROM photo_url_verification WHERE status='confirmed_missing'"))

    def test_changed_candidate_resets_due(self):
        with patch("photo_maintenance.check_image", return_value=("working", 200)):
            self.service.run(apply=True)
            with self.service.connect() as conn, conn.cursor() as cur:
                self.service.observe(cur, 1, NEW + "?v=2")
            conn.close()
            results = self.service.run()
        self.assertEqual([r["checked_url"] for r in results], [NEW + "?v=2"])

    def test_race_protection(self):
        row = self.service.rows()[0]
        self.service.set_ownership(1, "manual")
        self.assertIn("Skipped", self.service.save_result(row, NEW, "working", 200))

    def test_bounds_and_schedule_opt_in(self):
        with patch("photo_maintenance.check_image", return_value=("working", 200)) as check:
            self.assertEqual(self.service.run_scheduled(), [])
            self.assertEqual(len(self.service.run(limit=1)), 1)
            self.assertEqual(check.call_count, 1)

    def test_missing_photo_added_without_duplicate(self):
        self.sql("DELETE FROM productphotos WHERE product_id=1")
        with patch("photo_maintenance.check_image", return_value=("working", 200)):
            self.service.run(apply=True)
            self.service.run(apply=True)
        self.assertEqual(self.sql("SELECT count(*) n FROM productphotos WHERE product_id=1")[0]["n"], 1)
        self.assertEqual(self.sql("SELECT ownership FROM photo_maintenance WHERE product_id=1")[0]["ownership"], "retailer")

    def test_availability_changes_during_check(self):
        row = next(r for r in self.service.rows() if r["product_id"] == 1 and r["effective_primary"])
        self.sql("INSERT INTO product_price_history VALUES(1,false,now()+interval '1 minute')")
        self.assertIn("no longer available", self.service.save_result(row, NEW, "working", 200))

    def test_two_separated_missing_checks_confirm(self):
        with patch("photo_maintenance.check_image", return_value=("missing_evidence", 404)):
            self.service.run(apply=True)
            self.sql("UPDATE photo_url_verification SET next_due=now(),last_attempt=now()-interval '2 days'")
            self.service.run(apply=True)
        self.assertEqual(self.sql("SELECT count(*) n FROM photo_url_verification WHERE status='confirmed_missing'")[0]["n"], 3)
        self.assertEqual(self.sql("SELECT count(*) n FROM productphotos")[0]["n"], 3)

    def test_legacy_writer_keeps_caller_transaction_and_manual_photos(self):
        from fix_broken_photos import _insert_missing_photos
        conn = self.service.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE products SET name='Pending transaction' WHERE product_id=1")
                self.assertFalse(_insert_missing_photos(cur, 1, [NEW]))
            conn.rollback()
        finally:
            conn.close()
        self.assertEqual(self.sql("SELECT name FROM products WHERE product_id=1")[0]["name"], "First")

    def test_external_manual_edit_not_overwritten(self):
        self.service.set_ownership(1, "retailer")
        self.sql("UPDATE productphotos SET photo_url=%s WHERE product_id=1 AND is_primary",
                 (OLD + "?manual=true",))
        with patch("photo_maintenance.check_image", return_value=("working", 200)):
            results = self.service.run(apply=True)
        self.assertTrue(any("External photo edit" in r["outcome"] for r in results))
        self.assertEqual(self.sql("SELECT ownership FROM photo_maintenance WHERE product_id=1")[0]["ownership"], "unknown")

    def test_bulk_approval_preserves_manual_protection(self):
        self.service.set_ownership(1, "manual")
        self.assertEqual(self.service.approve_retailer_ownership([1, 2]), 1)
        self.assertEqual(self.sql("SELECT ownership FROM photo_maintenance WHERE product_id=1")[0]["ownership"], "manual")

    def test_tool_report_preview_and_ownership_ui(self):
        import os
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ, {"DATABASE_URL": self.service.database_url}), \
                patch("photo_maintenance.check_image", return_value=("working", 200)):
            app = AppTest.from_string("from photo_maintenance_ui import render\nrender()").run()
            self.assertFalse(app.exception)
            self.assertTrue(app.dataframe)
            next(b for b in app.button if b.label == "Run bounded photo check").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.session_state["photo_maintenance_results"])


if __name__ == "__main__":
    unittest.main()
