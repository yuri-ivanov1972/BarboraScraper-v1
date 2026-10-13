"""Scoped recovery tests: private temporary PostgreSQL and strict HTTP fixtures."""

import copy
import json
import unittest
from unittest.mock import patch

import test_product_refresh as fixture
from barbora_lightweight_updater import BarboraLightweightUpdater
from nutrition_reload_source import SourceError
from poultry_recovery_source import CODE, PATH, URL, ROOT_CODE, PARENT_CODE, fetch_candidates
from poultry_category_recovery import preview_recovery, apply_recovery
from product_refresh_store import RefreshError
from product_view_db import ProductViewDatabase

SKUS = ["000000000001315297", "000000000001286881"]


class Website:
    def fetch(self, url):
        if "/produkti/" not in url:
            records = [{"id": sku, "category_id": CODE, "category_path_url": PATH, "Url": sku}
                       for sku in SKUS]
            return "<script>window.b_productList = " + json.dumps(records) + ";</script>", url
        sku = url.rsplit("/", 1)[-1]
        html = fixture.page(name="Fixture poultry 450g", sku=sku, category=CODE,
                            ingredients="Putnu gaļa, sāls.")
        html = html.replace("<dd>400</dd>", "<dd>450</dd>")
        html = html.replace('"category_id": "' + CODE + '"',
                            '"category_path_url": "' + PATH + '", "category_id": "' + CODE + '"')
        return html, url


class SourceTests(unittest.TestCase):
    def test_complete_pages_are_fetched_for_exact_category_skus(self):
        candidates = fetch_candidates(Website())
        self.assertEqual([p["sku"] for p in candidates], SKUS)
        self.assertTrue(all(p["nutrition"]["protein"] == 8.7 for p in candidates))
        self.assertTrue(all(p["photo_urls"] for p in candidates))

    def test_wrong_category_redirect_malformed_and_duplicate_listing_refused(self):
        examples = [
            ("<script>window.b_productList = [];</script>", URL),
            ("<script>window.b_productList = BAD;</script>", URL),
            ("<script>window.b_productList = [];</script>", "https://barbora.lv/other"),
            ("<script>window.b_productList = " + json.dumps(
                [{"id": SKUS[0], "category_id": "wrong", "category_path_url": PATH}]) + ";</script>", URL),
        ]
        for response in examples:
            with self.subTest(response=response), self.assertRaises(SourceError):
                fetch_candidates(type("Source", (), {"fetch": lambda self, url: response})())
        source = Website()
        original = source.fetch
        def duplicate(url):
            html, final = original(url)
            return (html.replace(json.dumps(SKUS[1]), json.dumps(SKUS[0])), final)
        with patch.object(source, "fetch", side_effect=duplicate), self.assertRaises(SourceError):
            fetch_candidates(source)

    def test_product_page_category_mismatch_refused(self):
        source = Website()
        original = source.fetch
        def wrong(url):
            html, final = original(url)
            return (html.replace(CODE, "wrong") if "/produkti/" in url else html, final)
        with patch.object(source, "fetch", side_effect=wrong), self.assertRaises(SourceError):
            fetch_candidates(source)


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.DatabaseTests.setUpClass()
        cls.dsn = fixture.DatabaseTests.dsn
        cls.helper = fixture.DatabaseTests()
        cls.helper.execute("""
            ALTER TABLE normalized_categories ADD COLUMN name_en text, ADD COLUMN level int;
            CREATE SEQUENCE recovery_test_products_seq START 20;
            ALTER TABLE products ALTER COLUMN product_id SET DEFAULT nextval('recovery_test_products_seq');
            CREATE TABLE category_processing_jobs(id serial PRIMARY KEY,category_code text,category_id int,
                total_products int,processed_count int,status text,completed_at timestamptz,
                requested_by text,update_mode text,notes text);
            CREATE UNIQUE INDEX recovery_active_job ON category_processing_jobs(category_code)
                WHERE status IN ('queued','processing','in_progress');
            CREATE TABLE product_processing_log(id serial PRIMARY KEY,job_id int,sku text,status text,product_url text);
            CREATE TABLE job_events(id serial PRIMARY KEY,job_id int,event_type text,message text,metadata jsonb);
        """)

    @classmethod
    def tearDownClass(cls):
        fixture.DatabaseTests.tearDownClass()

    def setUp(self):
        # The original fixture initializes existing unrelated products and analyses.
        # Its category INSERT uses a fixed shape; temporarily remove added columns
        # during setup, then restore them. These are PRIVATE fixture tables only.
        self.helper.execute("ALTER TABLE normalized_categories DROP COLUMN name_en,DROP COLUMN level")
        self.helper.setUp()
        self.helper.execute("""
            ALTER TABLE normalized_categories ADD COLUMN name_en text,ADD COLUMN level int;
            UPDATE normalized_categories SET level=3;
            TRUNCATE category_processing_jobs,product_processing_log,job_events RESTART IDENTITY;
            ALTER SEQUENCE recovery_test_products_seq RESTART WITH 20;
            INSERT INTO normalized_categories(category_id,barbora_category_code,name_lv,name_en,level,parent_category_id,normalized_category)
                VALUES (204,%s,'Root','Root',1,NULL,'gala-zivs-un-gatava-kulinarija'),
                       (233,%s,'Svaiga putnu gaļa','Fresh Poultry',2,204,'svaiga-putnu-gala');
        """, (ROOT_CODE, PARENT_CODE))

    def execute(self, query, params=None):
        return self.helper.execute(query, params)

    def preview(self):
        return preview_recovery(self.dsn, Website())

    def apply(self, preview=None):
        p = preview or self.preview()
        return apply_recovery(p, self.dsn, p["sha256"])

    def test_preview_has_no_category_product_master_job_or_analysis_writes(self):
        before = [self.execute(f"SELECT COUNT(*) FROM {table}") for table in
                  ("normalized_categories", "products", "ingredient_analysis", "brands", "category_processing_jobs")]
        preview = self.preview()
        self.assertTrue(preview["create_category"])
        self.assertEqual(preview["category"]["category_id"], 234)
        self.assertTrue(all(i["new"] for i in preview["items"]))
        after = [self.execute(f"SELECT COUNT(*) FROM {table}") for table in
                 ("normalized_categories", "products", "ingredient_analysis", "brands", "category_processing_jobs")]
        self.assertEqual(before, after)

    def test_atomic_full_recovery_browser_and_daily_inclusion_and_repeat(self):
        unrelated = self.execute("SELECT to_jsonb(p) FROM products p ORDER BY product_id")
        result = self.apply()
        self.assertEqual([p["status"] for p in result["products"]], ["created", "created"])
        self.assertEqual(self.execute("SELECT COUNT(*) FROM products")[0][0], 4)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM normalized_categories WHERE barbora_category_code=%s",(CODE,))[0][0],1)
        self.assertEqual(unrelated, self.execute("SELECT to_jsonb(p) FROM products p WHERE product_id IN (1,2) ORDER BY product_id"))
        for sku in SKUS:
            p = self.execute("""
                SELECT p.name,p.quantity_value,p.description,p.allergens,p.brand_id,p.needs_enrichment,
                       p.nutrition_source,n.energy_kj,n.protein,n.data_source_date,
                       (SELECT COUNT(*) FROM productphotos pp WHERE pp.product_id=p.product_id),
                       (SELECT COUNT(*) FROM product_price_history h WHERE h.product_id=p.product_id),
                       (SELECT COUNT(*) FROM ingredient_product_mapping m WHERE m.product_sku=p.sku)
                FROM products p JOIN nutritionfacts n USING(product_id) WHERE p.sku=%s
            """,(sku,))[0]
            self.assertEqual(p[0],"Fixture poultry 450g"); self.assertEqual(p[1],450)
            self.assertTrue(p[2]);self.assertTrue(p[3]);self.assertIsNotNone(p[4])
            self.assertFalse(p[5]);self.assertEqual(p[6],"barbora_scraped")
            self.assertEqual(p[7],261);self.assertIsNotNone(p[9])
            self.assertEqual(p[10:],(1,1,2))
        with patch.dict("os.environ", {"DATABASE_URL": self.dsn}), \
             patch.object(ProductViewDatabase,"_run_migrations",side_effect=AssertionError("no setup")):
            updater = BarboraLightweightUpdater()
            self.assertIn(result["category_id"],[c["category_id"] for c in updater.get_all_level3_categories()])
            self.assertEqual(updater.get_category_path_for_url(result["category_id"]), PATH)
            self.assertTrue(set(SKUS).issubset(updater.get_existing_skus()))
            db = ProductViewDatabase(initialize_schema=False)
            try:
                products, total = db.get_products_by_category(result["category_id"])
                self.assertEqual(total,2)
                self.assertEqual({p["sku"] for p in products},set(SKUS))
                self.assertTrue(db.get_product_details(result["products"][0]["product_id"])["photos"])
            finally: db.close()
        self.assertEqual(self.apply()["status"],"no_changes")
        self.assertEqual(self.execute("SELECT COUNT(*) FROM category_processing_jobs")[0][0],1)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM product_price_history")[0][0],3)
        self.assertEqual(self.execute("SELECT status,processed_count FROM category_processing_jobs")[0],("completed",2))

    def test_reuse_existing_correct_category_and_safe_ids(self):
        self.execute("""
            INSERT INTO normalized_categories(category_id,barbora_category_code,name_lv,name_en,level,parent_category_id,normalized_category)
            VALUES (999,'unrelated','Unrelated','Unrelated',3,NULL,'unrelated')
        """)
        self.assertEqual(self.preview()["category"]["category_id"],1000)
        self.apply()
        self.assertFalse(self.preview()["create_category"])
        self.assertEqual(self.preview()["category"]["category_id"],1000)
        self.assertEqual(self.execute("SELECT name_lv FROM normalized_categories WHERE category_id=999")[0][0],"Unrelated")

    def test_active_job_missing_parent_conflicting_path_block(self):
        self.execute("INSERT INTO category_processing_jobs(category_code,status) VALUES (%s,'queued')",(CODE,))
        with self.assertRaisesRegex(RefreshError,"active job"): self.preview()
        self.execute("DELETE FROM category_processing_jobs")
        self.execute("UPDATE normalized_categories SET normalized_category='bad' WHERE category_id=233")
        with self.assertRaisesRegex(RefreshError,"hierarchy"): self.preview()

    def test_rollback_after_second_product_failure_has_no_partial_category_or_product(self):
        import poultry_category_recovery as recovery
        original = recovery.persist_refresh_plan
        calls = []
        def fail_second(conn,snapshot,plan):
            calls.append(snapshot["product"]["sku"])
            if len(calls)==2: raise RuntimeError("fixture failure")
            original(conn,snapshot,plan)
        with patch.object(recovery,"persist_refresh_plan",side_effect=fail_second):
            with self.assertRaisesRegex(RefreshError,"rolled back") as error: self.apply()
        self.assertEqual(error.exception.failed_sku,SKUS[1])
        self.assertEqual(self.execute("SELECT COUNT(*) FROM products")[0][0],2)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM normalized_categories WHERE barbora_category_code=%s",(CODE,))[0][0],0)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM brands")[0][0],1)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM ingredient_analysis")[0][0],2)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM category_processing_jobs")[0][0],0)

    def test_required_approval_modified_preview_and_stale_taxonomy_refused(self):
        p = self.preview()
        with self.assertRaisesRegex(RefreshError,"approval"): apply_recovery(p,self.dsn)
        altered=copy.deepcopy(p);altered["items"][0]["candidate"]["sku"]="wrong"
        with self.assertRaisesRegex(RefreshError,"approval"): apply_recovery(altered,self.dsn,p["sha256"])
        self.execute("UPDATE normalized_categories SET name_lv='Changed' WHERE category_id=2")
        with self.assertRaisesRegex(RefreshError,"Categories"): self.apply(p)

    def test_concurrent_product_creation_refused_and_manual_inputs_retained(self):
        p = self.preview()
        self.execute("""
            INSERT INTO products(product_id,sku,name,barbora_url,category_id,name_manual_edit,needs_enrichment)
            VALUES (30,%s,'Manual name','https://barbora.lv/produkti/manual',1,TRUE,TRUE)
        """,(SKUS[0],))
        with self.assertRaisesRegex(RefreshError,"product changed"): self.apply(p)
        new = self.preview()
        self.assertFalse(new["items"][0]["new"])
        self.assertNotIn("name",new["items"][0]["plan"]["product_changes"])
        self.apply(new)
        self.assertEqual(self.execute("SELECT name FROM products WHERE sku=%s",(SKUS[0],))[0][0],"Manual name")


if __name__ == "__main__":
    unittest.main()
