"""HTTP fixtures and isolated PostgreSQL; no real credentials or production writes."""

import copy
import json
import logging
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg2

from nutrition_reload_source import SourceError
from product_refresh_source import ProductRefreshSource, parse_full_page, photo_url
from product_refresh_store import RefreshError, apply_preview, prepare_preview

SKU = "000000000000940284"
URL = "https://barbora.lv/produkti/old-name"
CATEGORY = "2c214c16-e453-4954-9389-1421a9391baf"
PHOTO = "https://cdn.barbora.lv/products/new.png"


def page(name="Jogurts Grieķu BALTAIS bez piedevām 400g", sku=SKU, nutrition=True,
         ingredients="PIENS, ieraugs.", market=None, category=CATEGORY, gallery=None):
    product = {"id": sku, "title": name, "category_id": category, "brand_name": "BALTAIS",
               "price": 1.49, "retail_price": 1.75, "status": "active",
               "comparative_unit_price": 3.73, "comparative_unit": "kg",
               "promotion": {"oldPrice": 1.75, "oldComparativeRate": 4.38, "loyaltyCardRequired": True},
               "gallery": [PHOTO] if gallery is None else gallery}
    if market:
        product.update(market)
    table = """<h3 class="b-product-info--info-3-title">Uzturvērtība (100 g/ml)</h3><table>
        <tr><td>Enerģētiskā vērtība</td><td>261 kJ / 62 kcal</td></tr>
        <tr><td>Tauki</td><td>2 g</td></tr>
        <tr><td>Piesātinātas taukskābes</td><td>1.1 g</td></tr>
        <tr><td>Ogļhidrāti</td><td>2.3 g</td></tr>
        <tr><td>Cukuri</td><td>2.3 g</td></tr>
        <tr><td>Olbaltumvielas</td><td>8.7 g</td></tr>
        <tr><td>Sāls</td><td>0 g</td></tr></table>""" if nutrition else ""
    return f"""<h1>{name}</h1><script>window.product = {json.dumps(product)};
        window.reportUserActionToGa4(window.ga4EventTypes.viewItem,
        {{items: [{{"item_id":"{sku}"}}]}});</script>
        <dl><dt class="b-product-info--info-3-title">Sastāvdaļas</dt><dd>{ingredients}</dd>
        <dt class="b-product-info--info-3-title">Apraksts</dt><dd>Current description</dd>
        <dt class="b-product-info--info-3-title">Alergēni</dt><dd>Milk</dd></dl>
        <dl class="b-dl-align-left"><dt>Zīmols</dt><dd>BALTAIS</dd>
        <dt>Izcelsmes valsts</dt><dd>Latvija</dd><dt>Neto daudzums (g/ml)</dt><dd>400</dd></dl>{table}"""


class FixtureSource:
    def __init__(self, html=None):
        self.html = html or page()

    def product(self, snapshot):
        return parse_full_page(self.html, "https://barbora.lv/produkti/new-name", snapshot["product"]["sku"])


class SourceTests(unittest.TestCase):
    def test_same_sku_renamed_identity_and_promotions(self):
        result = parse_full_page(page(), URL, SKU)
        self.assertIn("BALTAIS", result["name"])
        self.assertEqual(result["sku"], SKU)
        self.assertEqual(result["market"]["price"], 1.75)
        self.assertEqual(result["market"]["discount_price"], 1.49)
        self.assertEqual(result["nutrition"]["salt"], 0)

    def test_wrong_or_missing_identity_rejected(self):
        for html in (page(sku="940284"), page().replace('"item_id"', '"wrong_key"')):
            with self.assertRaises(SourceError):
                parse_full_page(html, URL, SKU)

    def test_absent_and_invalid_nutrition_are_not_complete(self):
        self.assertEqual(parse_full_page(page(nutrition=False), URL, SKU)["nutrition_issue"], "absent_nutrition")
        self.assertIsNotNone(parse_full_page(page().replace("2.3 g", "-2.3 g"), URL, SKU)["nutrition_issue"])

    def test_placeholder_untrusted_and_empty_photos_rejected(self):
        for url in ("https://evil.test/cdn.barbora.lv/products/a.png",
                    "https://cdn.barbora.lv/products/no-image-placeholder.png",
                    "https://cdn.barbora.lv.evil.test/products/a.png", "http://cdn.barbora.lv/products/a.png"):
            self.assertFalse(photo_url(url))
        self.assertEqual(parse_full_page(page(gallery=[]), URL, SKU)["photo_urls"], [])

    def test_redirect_validation_and_retries(self):
        source = ProductRefreshSource()
        source.delay = 0
        response = type("Response", (), {"status_code": 302, "headers": {"Location": "https://evil.test/a"}})()
        source.local.session = type("Session", (), {"get": lambda *args, **kwargs: response})()
        with self.assertRaisesRegex(SourceError, "untrusted_url"):
            source.fetch(URL)
        self.assertEqual(source.retries, 1)
        self.assertEqual(source.max_pages, 6)

    def test_fallback_finds_exact_sku_not_name(self):
        source = ProductRefreshSource()
        with patch.object(source, "fetch", side_effect=[SourceError("page_not_found"),
                                                       (page(), URL)]), \
             patch.object(source, "category_urls", return_value={SKU: {URL}}):
            result = source.product({"product": {"sku": SKU, "barbora_url": URL}, "category_path": "food"})
        self.assertEqual(result["sku"], SKU)


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="product-refresh-tests-")
        cls.root = Path(cls.temp.name)
        cls.data = cls.root / "pg"
        subprocess.run(["initdb", "-D", str(cls.data), "-U", "fixture", "-A", "trust",
                        "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-l", str(cls.root / "pg.log"),
                        "-o", f"-k {cls.root} -h '' -p 6545", "-w", "start"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.dsn = f"host={cls.root} port=6545 dbname=postgres user=fixture"
        cls.log = logging.getLogger("nutriscore_calculator")
        cls.old_level = cls.log.level
        cls.log.setLevel(logging.ERROR)
        with psycopg2.connect(cls.dsn) as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE brands(id serial PRIMARY KEY,name text,normalized_name text UNIQUE,
                    website_url text,updated_at timestamptz);
                CREATE TABLE producers(LIKE brands INCLUDING ALL);
                CREATE TABLE brand_producers(brand_id int,producer_id int,PRIMARY KEY(brand_id,producer_id));
                CREATE TABLE normalized_categories(category_id int PRIMARY KEY,parent_category_id int,
                    normalized_category text,name_lv text,barbora_category_code text);
                CREATE TABLE products(product_id int PRIMARY KEY,sku text UNIQUE,name text,name_norm text,
                    description text,allergens text,ingredients text,country_of_origin text,
                    barbora_url text,category_id int,rimi_category_code int,
                    quantity_value numeric,quantity_unit text,
                    name_manual_edit bool,is_hidden bool,nutrition_source text,needs_enrichment bool,
                    enrichment_reviewed bool,enrichment_skipped bool,nova_score int,nova_source text,
                    brand_id int,producer_id int,updated_at timestamptz);
                CREATE TABLE nutritionfacts(nutrition_id serial PRIMARY KEY,product_id int UNIQUE,
                    energy_kj int,energy_kcal int,fat_total numeric,fat_saturated numeric,
                    carbs_total numeric,carbs_sugars numeric,protein numeric,salt numeric,fiber numeric,
                    is_fiber_correct bool DEFAULT FALSE,nutrition_manual_edit bool DEFAULT FALSE,
                    ingredients_text text,usda_fdc_id int,nutri_score_grade text,nutri_score_points int,
                    data_source_date timestamptz);
                CREATE TABLE productphotos(photo_id serial PRIMARY KEY,product_id int,photo_url text,is_primary bool,alt_text text);
                CREATE TABLE product_price_history(price_history_id serial PRIMARY KEY,product_id int,
                    price numeric,discount_price numeric,price_per_unit numeric,price_per_unit_type text,
                    discount_price_per_unit numeric,is_available bool,recorded_at timestamptz,created_at timestamptz DEFAULT NOW(),data_source text);
                CREATE TABLE ingredient_analysis(id serial PRIMARY KEY,ingredient text UNIQUE,
                    frequency int,is_processed bool,suspicion_level text);
                CREATE TABLE ingredient_product_mapping(ingredient_id int,product_sku text,PRIMARY KEY(ingredient_id,product_sku));
                CREATE TABLE rimi_nova_categories(rimi_category_code int,nova_score int);
                CREATE TABLE nutrition_validation(product_id int UNIQUE,suspicion_level text,suspicion_score numeric,
                    reasons jsonb,checked_at timestamptz);
            """)

    @classmethod
    def tearDownClass(cls):
        cls.log.setLevel(cls.old_level)
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-m", "immediate", "-w", "stop"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.temp.cleanup()

    def setUp(self):
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("""
                TRUNCATE products,nutritionfacts,productphotos,product_price_history,brands,producers,
                    brand_producers,normalized_categories,ingredient_analysis,ingredient_product_mapping,
                    rimi_nova_categories,nutrition_validation RESTART IDENTITY;
                INSERT INTO normalized_categories VALUES
                    (1,NULL,'yogurt','Jogurts',%s),
                    (2,NULL,'juice','Sulas','84e6b16a-6acf-4e72-a248-925d35c2ef0d');
                INSERT INTO brands(id,name,normalized_name,website_url) VALUES (1,'Old brand','old brand','https://manual.test');
                INSERT INTO producers(id,name,normalized_name,website_url) VALUES (10,'Producer','producer','https://producer.test');
                INSERT INTO products VALUES
                    (1,%s,'Jogurts GRIEĶU bez piedevām 400g','old','Old description','Old allergens','piens, cukurs',
                    'Other',%s,1,197,400,'g',FALSE,FALSE,'usda_api',TRUE,FALSE,FALSE,4,'additive_override',1,10,'2026-01-01'),
                    (2,'untouched','Other','other',NULL,NULL,NULL,NULL,%s,2,5,1,'l',FALSE,FALSE,
                    NULL,TRUE,FALSE,FALSE,1,'category_inherited',1,10,'2026-01-01');
                INSERT INTO nutritionfacts(product_id,energy_kj,energy_kcal,fat_total,fat_saturated,
                    carbs_total,carbs_sugars,protein,salt,fiber,is_fiber_correct,nutrition_manual_edit,
                    ingredients_text,usda_fdc_id,nutri_score_grade,nutri_score_points)
                    VALUES (1,240,58,2,1,3,3,7,.2,0,TRUE,FALSE,'piens, cukurs',123,'C',3);
                INSERT INTO productphotos(product_id,photo_url,is_primary) VALUES (1,'https://cdn.barbora.lv/products/old.png',TRUE);
                INSERT INTO product_price_history(product_id,price,price_per_unit,price_per_unit_type,is_available,recorded_at)
                    VALUES (1,1.8,4.5,'kg',TRUE,'2026-01-01');
                INSERT INTO ingredient_analysis VALUES (1,'piens',1,TRUE,'none'),(2,'cukurs',1,TRUE,'avoid');
                SELECT setval('ingredient_analysis_id_seq',2);
                SELECT setval('brands_id_seq',1);
                INSERT INTO ingredient_product_mapping VALUES (1,%s),(2,%s);
                INSERT INTO rimi_nova_categories VALUES (197,1),(5,3);
                INSERT INTO nutrition_validation(product_id) VALUES (1),(2);
            """, (CATEGORY, SKU, URL, URL, SKU, SKU))
        self.source = FixtureSource()

    def execute(self, sql_text, params=None):
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(sql_text, params)
            return cur.fetchall() if cur.description else None

    def preview(self, source=None):
        return prepare_preview(1, self.dsn, source or self.source)

    def test_preview_is_readonly_no_setup_or_cache_writes(self):
        before = self.execute("SELECT to_jsonb(p) FROM products p ORDER BY product_id")
        with patch("product_refresh_store.connect", wraps=__import__("product_refresh_store").connect) as connect:
            preview = self.preview()
            self.assertTrue(connect.call_args[0][1])
        self.assertEqual(before, self.execute("SELECT to_jsonb(p) FROM products p ORDER BY product_id"))
        self.assertEqual(self.execute("SELECT COUNT(*) FROM brands")[0][0], 1)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM ingredient_analysis")[0][0], 2)
        self.assertIn("BALTAIS", preview["plan"]["product_changes"]["name"])

    def test_full_apply_and_same_source_repeat_are_deduplicated(self):
        untouched = self.execute("SELECT to_jsonb(p) FROM products p WHERE product_id=2")
        result = apply_preview(self.preview(), self.dsn)
        self.assertEqual(result["status"], "updated")
        p = self.execute("SELECT name,needs_enrichment,nutrition_source,producer_id,nova_score FROM products WHERE product_id=1")[0]
        self.assertIn("BALTAIS", p[0]); self.assertFalse(p[1]); self.assertEqual(p[2], "barbora_scraped")
        self.assertEqual(p[3], 10); self.assertIsNone(p[4])
        n = self.execute("SELECT salt,usda_fdc_id,ingredients_text FROM nutritionfacts WHERE product_id=1")[0]
        self.assertEqual(n[0], 0); self.assertIsNone(n[1]); self.assertEqual(n[2],"PIENS, ieraugs.")
        self.assertEqual(self.execute("SELECT website_url FROM brands WHERE id=1")[0][0],"https://manual.test")
        self.assertEqual(self.execute("SELECT website_url FROM producers WHERE id=10")[0][0],"https://producer.test")
        prices = self.execute("SELECT price,discount_price FROM product_price_history ORDER BY price_history_id DESC LIMIT 1")[0]
        self.assertEqual(tuple(float(v) for v in prices), (1.75,1.49))
        second = self.preview()
        self.assertEqual(apply_preview(second,self.dsn)["status"],"no_changes")
        self.assertEqual(self.execute("SELECT COUNT(*) FROM product_price_history")[0][0],2)
        self.assertEqual(untouched,self.execute("SELECT to_jsonb(p) FROM products p WHERE product_id=2"))
        self.assertEqual(self.execute("SELECT COUNT(*) FROM nutrition_validation")[0][0],2)
        self.assertIsNotNone(self.execute("SELECT checked_at FROM nutrition_validation WHERE product_id=1")[0][0])

    def test_manual_name_ingredients_nutrition_and_nova_protected(self):
        self.execute("UPDATE products SET name_manual_edit=TRUE,nova_source='manual_override',nova_score=2 WHERE product_id=1")
        self.execute("UPDATE nutritionfacts SET nutrition_manual_edit=TRUE WHERE product_id=1")
        preview = self.preview()
        plan = preview["plan"]
        self.assertNotIn("name", plan["product_changes"])
        self.assertNotIn("ingredients_text", plan["nutrition_changes"])
        self.assertNotIn("energy_kj", plan["nutrition_changes"])
        self.assertNotIn("nova_score", plan["product_changes"])
        apply_preview(preview,self.dsn)
        self.assertEqual(self.execute("SELECT name,nova_score FROM products WHERE product_id=1")[0],
                         ("Jogurts GRIEĶU bez piedevām 400g",2))

    def test_incomplete_web_nutrition_retains_enriched_values_flags_and_fiber(self):
        source = FixtureSource(page().replace("<tr><td>Sāls</td><td>0 g</td></tr>",""))
        before = self.execute("SELECT energy_kj,salt,usda_fdc_id FROM nutritionfacts WHERE product_id=1")
        preview = self.preview(source)
        self.assertFalse(preview["plan"]["nutrition_complete"])
        apply_preview(preview,self.dsn)
        self.assertEqual(before,self.execute("SELECT energy_kj,salt,usda_fdc_id FROM nutritionfacts WHERE product_id=1"))
        self.assertTrue(self.execute("SELECT needs_enrichment FROM products WHERE product_id=1")[0][0])

    def test_existing_positive_fiber_and_provenance_preserved(self):
        self.execute("UPDATE nutritionfacts SET fiber=2.8,is_fiber_correct=TRUE WHERE product_id=1")
        apply_preview(self.preview(),self.dsn)
        fiber, correct = self.execute("SELECT fiber,is_fiber_correct FROM nutritionfacts WHERE product_id=1")[0]
        self.assertEqual(float(fiber), 2.8)
        self.assertTrue(correct)

    def test_hidden_remains_unavailable(self):
        self.execute("UPDATE products SET is_hidden=TRUE WHERE product_id=1")
        apply_preview(self.preview(),self.dsn)
        self.assertFalse(self.execute("SELECT is_available FROM product_price_history ORDER BY price_history_id DESC LIMIT 1")[0][0])
        self.assertTrue(self.execute("SELECT is_hidden FROM products WHERE product_id=1")[0][0])

    def test_concurrent_product_nutrition_photo_price_and_manual_changes_reject(self):
        queries = ("UPDATE products SET name='Concurrent' WHERE product_id=1",
                   "UPDATE nutritionfacts SET nutrition_manual_edit=TRUE WHERE product_id=1",
                   "UPDATE productphotos SET photo_url='changed' WHERE product_id=1",
                   "INSERT INTO product_price_history(product_id,price,recorded_at) VALUES (1,9,NOW())")
        for query in queries:
            preview = self.preview()
            self.execute(query)
            with self.assertRaisesRegex(RefreshError,"changed"):
                apply_preview(preview,self.dsn)

    def test_rollback_after_ingredient_writer_failure(self):
        preview = self.preview()
        before = self.execute("SELECT to_jsonb(p) FROM products p ORDER BY product_id")
        with patch("product_refresh_store.persist_ingredients",side_effect=RuntimeError("fixture")):
            with self.assertRaisesRegex(RefreshError,"rolled back"):
                apply_preview(preview,self.dsn)
        self.assertEqual(before,self.execute("SELECT to_jsonb(p) FROM products p ORDER BY product_id"))
        self.assertEqual(self.execute("SELECT COUNT(*) FROM product_price_history")[0][0],1)
        self.assertEqual(self.execute("SELECT photo_url FROM productphotos")[0][0],"https://cdn.barbora.lv/products/old.png")

    def test_ingredient_mappings_replaced_not_accumulated(self):
        apply_preview(self.preview(),self.dsn)
        tokens = self.execute("SELECT i.ingredient FROM ingredient_analysis i JOIN ingredient_product_mapping m ON m.ingredient_id=i.id WHERE m.product_sku=%s ORDER BY i.ingredient",(SKU,))
        self.assertEqual(tokens,[("ieraugs",),("piens",)])
        self.assertEqual(self.execute("SELECT frequency FROM ingredient_analysis WHERE ingredient='cukurs'")[0][0],0)
        self.assertFalse(self.execute("SELECT is_processed FROM ingredient_analysis WHERE ingredient='ieraugs'")[0][0])

    def test_category_change_maps_nova_and_uses_beverage_scoring(self):
        source = FixtureSource(page(category="84e6b16a-6acf-4e72-a248-925d35c2ef0d",
                                   ingredients="PIENS"))
        preview = self.preview(source)
        self.assertEqual(preview["plan"]["product_changes"]["category_id"],2)
        self.assertEqual(preview["plan"]["product_changes"]["rimi_category_code"],5)
        self.assertEqual(preview["plan"]["product_changes"]["nova_score"],3)
        apply_preview(preview,self.dsn)
        self.assertEqual(self.execute("SELECT category_id FROM products WHERE product_id=1")[0][0],2)

    def test_missing_fields_photos_and_unmapped_category_retained(self):
        preview = self.preview(FixtureSource(page(gallery=[],category="unknown")))
        self.assertIsNone(preview["plan"]["photos"])
        self.assertNotIn("category_id",preview["plan"]["product_changes"])
        self.assertNotIn("producer",preview["plan"]["links"])

    def test_tampered_expired_and_wrong_database_previews_refused(self):
        p = self.preview()
        altered = copy.deepcopy(p); altered["plan"]["product_changes"]["sku"]="bad"
        with self.assertRaisesRegex(RefreshError,"altered"):
            apply_preview(altered,self.dsn)
        from nutrition_reload_plan import digest
        expired = copy.deepcopy(p); expired["fetched_at"]="2000-01-01T00:00:00+00:00"
        expired["sha256"]=digest({k:v for k,v in expired.items() if k!="sha256"})
        with self.assertRaisesRegex(RefreshError,"expired"):
            apply_preview(expired,self.dsn)
        with self.assertRaisesRegex(RefreshError,"Database"):
            apply_preview(p,self.dsn.replace("dbname=postgres","dbname=other"))

    def test_ui_fetch_cancel_then_apply_with_real_fixture_database(self):
        from streamlit.testing.v1 import AppTest
        ui = AppTest.from_string(
            "from product_refresh_ui import render_refresh_controls\nrender_refresh_controls(1)",
            default_timeout=20)
        with patch.dict("os.environ", {"DATABASE_URL": self.dsn}), \
             patch("product_refresh_ui.prepare_preview", side_effect=lambda pid: self.preview()):
            ui.run()
            self.assertFalse(ui.exception)
            ui.button(key="barbora_refresh_fetch_1").click().run()
            self.assertFalse(ui.exception)
            self.assertEqual(len(ui.dataframe), 1)
            self.assertNotIn("BALTAIS", self.execute("SELECT name FROM products WHERE product_id=1")[0][0])
            ui.button(key="barbora_refresh_cancel_1").click().run()
            self.assertNotIn("barbora_refresh_preview_1", ui.session_state)
            # AppTest retains old deltas on an explicit st.rerun; flush the next frame.
            ui.run()
            self.assertEqual(len(ui.dataframe), 0)
            ui.button(key="barbora_refresh_fetch_1").click().run()
            ui.button(key="barbora_refresh_apply_1").click().run()
            self.assertFalse(ui.exception)
            self.assertFalse(ui.error)
            self.assertIn("Product refreshed", ui.success[0].value)
            self.assertIn("BALTAIS", self.execute("SELECT name FROM products WHERE product_id=1")[0][0])

    def test_main_browser_detail_exposes_refresh_without_setup_writes(self):
        from streamlit.testing.v1 import AppTest
        from product_view_db import ProductViewDatabase
        app = AppTest.from_file("main.py", default_timeout=20)
        app.session_state["view_mode"] = "product_view"
        app.session_state["selected_product_id"] = 1
        with patch.dict("os.environ", {"DATABASE_URL": self.dsn}), \
             patch.object(ProductViewDatabase, "_run_migrations", side_effect=AssertionError("No setup in detail preview")):
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.button(key="barbora_refresh_fetch_1").label, "Fetch refresh preview")
            self.assertEqual(app.session_state["selected_product_id"], 1)

    def test_missing_nutrition_row_is_created_only_on_apply(self):
        self.execute("DELETE FROM nutritionfacts WHERE product_id=1")
        preview = self.preview()
        self.assertEqual(self.execute("SELECT COUNT(*) FROM nutritionfacts")[0][0],0)
        apply_preview(preview,self.dsn)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM nutritionfacts")[0][0],1)
        self.assertIsNotNone(self.execute("SELECT data_source_date FROM nutritionfacts WHERE product_id=1")[0][0])

    def test_incomplete_stored_nutrition_cannot_remain_falsely_complete(self):
        self.execute("UPDATE nutritionfacts SET energy_kj=NULL,energy_kcal=NULL,protein=NULL WHERE product_id=1")
        self.execute("UPDATE products SET needs_enrichment=FALSE WHERE product_id=1")
        apply_preview(self.preview(FixtureSource(page(nutrition=False))),self.dsn)
        self.assertTrue(self.execute("SELECT needs_enrichment FROM products WHERE product_id=1")[0][0])
        self.assertIsNone(self.execute("SELECT nutri_score_grade FROM nutritionfacts WHERE product_id=1")[0][0])


if __name__ == "__main__":
    unittest.main()
