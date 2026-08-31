import unittest
from types import SimpleNamespace
from unittest.mock import patch

from barbora_parser import BarboraParser
from brand_producer import (
    clean_label,
    ensure_brand_producer_schema,
    normalize_entity_name,
    normalize_website_url,
    persist_brand_producer_links,
)
from backfill_brand_producer import run_backfill


class FakeResponse:
    def __init__(self, html):
        self.text = html
        self.content = html.encode("utf-8")

    def raise_for_status(self):
        return None


def parse_html(html):
    parser = BarboraParser()
    parser.session.get = lambda *args, **kwargs: FakeResponse(html)
    return parser.extract_product_details("https://barbora.lv/produkti/test")


class ParserTests(unittest.TestCase):
    def test_extracts_brand_and_producer_from_adjacent_values(self):
        details = parse_html("""
            <h1>Rulete</h1>
            <dl class="b-dl-align-left">
              <dt>Zīmols:</dt><dd>  STABURADZE  </dd>
              <dt class="b-product-info--info-3-title">Ražotājs</dt>
              <dd>STABURADZE   SIA</dd>
            </dl>
        """)
        self.assertEqual(details.brand, "STABURADZE")
        self.assertEqual(details.producer, "STABURADZE SIA")
        self.assertEqual(details.manufacturer, "STABURADZE SIA")

    def test_tolerates_labels_outside_expected_definition_list(self):
        details = parse_html("""
            <h1>Test</h1>
            <dl><dt> Zīmols : </dt> <dd>Laima</dd></dl>
            <dl><dt>Ražotājs:</dt><dd>Orkla Latvija SIA</dd></dl>
        """)
        self.assertEqual(details.brand, "Laima")
        self.assertEqual(details.producer, "Orkla Latvija SIA")

    def test_missing_and_blank_values_are_none(self):
        details = parse_html("""
            <h1>Test</h1>
            <dl class="b-dl-align-left"><dt>Zīmols:</dt><dd>   </dd></dl>
        """)
        self.assertIsNone(details.brand)
        self.assertIsNone(details.producer)

    def test_supports_nested_label_text_and_only_producer(self):
        details = parse_html("""
            <h1>Test</h1><dl>
            <dt><span>Ražotājs</span></dt><dd>  Rīgas piena kombināts  </dd>
            </dl>
        """)
        self.assertIsNone(details.brand)
        self.assertEqual(details.producer, "Rīgas piena kombināts")

    def test_extracts_adjacent_span_label_value_markup(self):
        details = parse_html("""
            <h1>Test</h1>
            <div><span>Zīmols:</span><span> STABURADZE </span></div>
            <div>
              <span class="b-product-info--info-3-title">Ražotājs</span>
              <span>STABURADZE   SIA</span>
            </div>
        """)
        self.assertEqual(details.brand, "STABURADZE")
        self.assertEqual(details.producer, "STABURADZE SIA")

    def test_span_label_does_not_capture_non_adjacent_value(self):
        details = parse_html("""
            <h1>Test</h1>
            <div><span>Zīmols:</span><strong>separator</strong><span>Wrong</span></div>
            <div><span>Ražotājs</span><span>Producer SIA</span></div>
        """)
        self.assertIsNone(details.brand)
        self.assertEqual(details.producer, "Producer SIA")


class NormalizationTests(unittest.TestCase):
    def test_unicode_normalization_casefold_and_whitespace(self):
        self.assertEqual(clean_label("  RĪGAS\t PIENS  "), "RĪGAS PIENS")
        self.assertEqual(normalize_entity_name("  RĪGAS\t PIENS  "), "rīgas piens")
        self.assertNotEqual(normalize_entity_name("Ražotājs"), "razotajs")
        self.assertEqual(normalize_entity_name("ＡＢＣ"), "abc")

    def test_blank_values_do_not_create_normalized_names(self):
        self.assertIsNone(clean_label(" \n "))
        self.assertIsNone(normalize_entity_name(None))

    def test_manual_website_urls_allow_only_complete_http_addresses(self):
        self.assertEqual(normalize_website_url(" https://example.lv "), "https://example.lv")
        self.assertIsNone(normalize_website_url(""))
        with self.assertRaises(ValueError):
            normalize_website_url("javascript:alert(1)")


class FakePersistenceCursor:
    def __init__(self):
        self.calls = []
        self.return_ids = iter([(11,), (22,)])

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return next(self.return_ids)


class PersistenceTests(unittest.TestCase):
    def test_links_both_entities_and_relationship_without_overwriting_metadata(self):
        cur = FakePersistenceCursor()
        ids = persist_brand_producer_links(cur, 7, " Staburadze ", "Orkla Latvija SIA")
        self.assertEqual(ids, (11, 22))
        sql = "\n".join(call[0] for call in cur.calls)
        self.assertIn("ON CONFLICT (normalized_name)", sql)
        self.assertIn("ON CONFLICT (brand_id, producer_id) DO NOTHING", sql)
        self.assertNotIn("website_url =", sql)
        self.assertNotIn("name = EXCLUDED.name", sql)

    def test_absent_values_clear_product_links_without_placeholder_rows(self):
        cur = FakePersistenceCursor()
        cur.return_ids = iter([])
        ids = persist_brand_producer_links(cur, 7, " ", None)
        self.assertEqual(ids, (None, None))
        self.assertEqual(len(cur.calls), 1)
        self.assertEqual(cur.calls[0][1], (None, None, 7))


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows=None):
        self.rows = rows
        self.committed = False

    def cursor(self, *args, **kwargs):
        return FakeCursor(self.rows)

    def commit(self):
        self.committed = True

    def rollback(self):
        return None

    def close(self):
        return None


class BackfillTests(unittest.TestCase):
    def test_continues_after_failed_page_and_honors_selected_rows(self):
        rows = [
            {"product_id": 1, "sku": "bad", "barbora_url": "https://barbora.lv/bad"},
            {"product_id": 2, "sku": "ok", "barbora_url": "https://barbora.lv/ok"},
        ]
        parser = SimpleNamespace()
        parser.extract_product_details = lambda url: (
            None if url.endswith("/bad")
            else SimpleNamespace(brand="Laima", producer="Orkla", manufacturer=None)
        )
        connections = iter([FakeConnection(rows), FakeConnection()])
        with patch("backfill_brand_producer.persist_brand_producer_links") as persist:
            with patch("backfill_brand_producer.ensure_brand_producer_schema"):
                result = run_backfill(
                    "db", parser=parser, retries=0, delay=0,
                    sleep_fn=lambda _: None, connection_factory=lambda _: next(connections),
                )
        self.assertEqual(result["selected"], 2)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["last_product_id"], 2)
        self.assertEqual(result["resume_after_product_id"], 0)
        self.assertEqual(result["failed_product_ids"], [1])
        persist.assert_called_once()

    def test_resume_cursor_stops_before_failed_middle_product(self):
        rows = [
            {"product_id": 1, "sku": "ok-1", "barbora_url": "https://barbora.lv/ok-1"},
            {"product_id": 2, "sku": "bad", "barbora_url": "https://barbora.lv/bad"},
            {"product_id": 3, "sku": "ok-3", "barbora_url": "https://barbora.lv/ok-3"},
        ]
        parser = SimpleNamespace()
        parser.extract_product_details = lambda url: (
            None if url.endswith("/bad")
            else SimpleNamespace(brand="Laima", producer="Orkla", manufacturer=None)
        )
        connections = iter([FakeConnection(rows), FakeConnection(), FakeConnection()])
        with patch("backfill_brand_producer.persist_brand_producer_links"):
            with patch("backfill_brand_producer.ensure_brand_producer_schema"):
                result = run_backfill(
                    "db", parser=parser, retries=0, delay=0,
                    sleep_fn=lambda _: None, connection_factory=lambda _: next(connections),
                )
        self.assertEqual(result["resume_after_product_id"], 1)
        self.assertEqual(result["failed_product_ids"], [2])

    def test_schema_migration_is_ordered_and_committed(self):
        conn = FakeConnection()
        ensure_brand_producer_schema(conn)
        self.assertTrue(conn.committed)


if __name__ == "__main__":
    unittest.main()