"""Actual isolated PostgreSQL tests. Never uses project/database credentials."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg2

from rimi_produce_reader import capture


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="produce-readonly-test-")
        cls.root = Path(cls.temp.name)
        cls.data = cls.root / "data"
        subprocess.run(["initdb", "-D", str(cls.data), "-U", "fixture", "-A", "trust",
                        "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-l", str(cls.root / "pg.log"),
                        "-o", f"-k {cls.root} -h '' -p 6543", "-w", "start"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.dsn = f"dbname=postgres user=fixture host={cls.root} port=6543"
        cls.env = {"PROD_DATABASE_URL": cls.dsn, "RIMI_DATABASE_URL": cls.dsn}
        with psycopg2.connect(cls.dsn) as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE normalized_categories(category_id int PRIMARY KEY,name_lv text,
                    name_en text,parent_category_id int,level int);
                INSERT INTO normalized_categories VALUES
                    (1,'Augļi un dārzeņi','Fruits',NULL,0),
                    (6,'Augļi un dārzeņi','Fruits',NULL,0),
                    (11,'Augļi','Fruit',1,1),(12,'Apakškategorija','Subcategory',11,2),
                    (61,'Augļi','Fruit',6,1);
                CREATE TABLE products(product_id int PRIMARY KEY,sku text,name text,
                    category_id int,needs_enrichment boolean,enrichment_reviewed boolean);
                INSERT INTO products VALUES
                    (1,'001','Kivi',11,TRUE,FALSE), (2,'002','Kivi',11,TRUE,NULL),
                    (3,'003','Kivi',11,TRUE,TRUE), (4,'004','Kivi',11,TRUE,FALSE),
                    (5,'005','Kivi',11,TRUE,FALSE),(7,'007','Kivi',12,TRUE,FALSE),
                    (100,'0100','Kivi',61,FALSE,TRUE),(101,'0101','Kivi',6,FALSE,FALSE);
                CREATE TABLE nutritionfacts(nutrition_id int,product_id int,fiber numeric);
                INSERT INTO nutritionfacts VALUES (2,2,0),(7,7,NULL);
                CREATE TABLE product_price_history(price_history_id int,product_id int,
                    is_available boolean,recorded_at timestamptz);
                INSERT INTO product_price_history VALUES
                    (1,1,TRUE,'2026-10-11'),(2,1,FALSE,'2026-10-11'),
                    (3,2,TRUE,'2026-10-11'),(4,3,TRUE,'2026-10-11'),
                    (5,5,TRUE,'2026-10-10'),(6,5,FALSE,'2026-10-11'),
                    (7,7,TRUE,'2026-10-11'),(8,100,FALSE,'2026-10-11');
            """)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-m", "immediate", "-w", "stop"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.temp.cleanup()

    def test_latest_availability_tie_reviewed_and_missing_history(self):
        result = capture("barbora", self.env)
        self.assertEqual([r["product"]["product_id"] for r in result["rows"]], [2, 7])
        self.assertEqual(result["rows"][0]["nutrition"]["fiber"], 0)
        self.assertTrue(result["read_only"])

    def test_separate_category_tree_direct_parent_and_source_unavailability(self):
        result = capture("rimi", self.env)
        self.assertEqual([r["product"]["product_id"] for r in result["rows"]], [100, 101])
        self.assertFalse(result["rows"][0]["available"])
        self.assertIsNone(result["rows"][1]["available"])
        self.assertIsNone(result["rows"][0]["nutrition"])

    def test_read_only_mode_rejects_writes_inside_actual_reader_session(self):
        real_connect = psycopg2.connect
        verified = []

        class ConnectionProbe:
            def __init__(self, *args, **kwargs):
                self.conn = real_connect(*args, **kwargs)

            def set_session(self, **kwargs):
                self.conn.set_session(**kwargs)
                self.asserted_readonly = kwargs["readonly"]

            def cursor(self, *args, **kwargs):
                if not verified:
                    # All operations below are inside the reader's read-only mode.
                    with self.conn.cursor() as probe:
                        probe.execute("SAVEPOINT readonly_test")
                        try:
                            probe.execute("UPDATE products SET name='would corrupt data'")
                            raise AssertionError("Read-only connection allowed an UPDATE")
                        except psycopg2.errors.ReadOnlySqlTransaction:
                            verified.append(True)
                        finally:
                            probe.execute("ROLLBACK TO SAVEPOINT readonly_test")
                            probe.execute("RELEASE SAVEPOINT readonly_test")
                return self.conn.cursor(*args, **kwargs)

            def rollback(self):
                self.conn.rollback()

            def close(self):
                self.conn.close()

        with patch("rimi_produce_reader.psycopg2.connect", ConnectionProbe):
            capture("barbora", self.env)
        self.assertEqual(verified, [True])
        with real_connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM products WHERE name='Kivi'")
            self.assertEqual(cur.fetchone()[0], 8)

    def test_connection_errors_never_expose_dsn_or_exception_text(self):
        with patch("rimi_produce_reader.psycopg2.connect", side_effect=Exception("password=DO-NOT-LOG")):
            with self.assertRaisesRegex(RuntimeError, "rimi read-only snapshot failed") as caught:
                capture("rimi", {"RIMI_DATABASE_URL": "password=DO-NOT-LOG"})
            self.assertNotIn("DO-NOT-LOG", str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
