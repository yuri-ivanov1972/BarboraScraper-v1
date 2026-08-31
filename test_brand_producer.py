import unittest
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from barbora_parser import BarboraParser
from brand_producer import (
    clean_label,
    ensure_brand_producer_schema,
    normalize_entity_name,
    normalize_website_url,
    persist_brand_producer_links,
    verify_brand_producer_schema,
)
from backfill_brand_producer import (
    BackfillFatalError,
    get_database_url,
    run_backfill,
)


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

    def test_uses_distributor_when_producer_is_missing(self):
        details = parse_html("""
            <h1>Test</h1>
            <dl>
              <dt>Ražotājs:</dt><dd> </dd>
              <dt>Piegādātāja kontaktinformācija:</dt>
              <dd>Granarolo Baltics O&#220;</dd>
            </dl>
        """)
        self.assertEqual(details.distributor_name, "Granarolo Baltics OÜ")
        self.assertEqual(details.producer, "Granarolo Baltics OÜ")
        self.assertEqual(details.producer_name, "Granarolo Baltics OÜ")

    def test_actual_producer_takes_precedence_over_distributor(self):
        details = parse_html("""
            <h1>Test</h1>
            <dl>
              <dt>Ražotājs:</dt><dd>Actual Producer SIA</dd>
              <dt>Piegādātāja kontaktinformācija:</dt><dd>Distributor SIA</dd>
            </dl>
        """)
        self.assertEqual(details.producer, "Actual Producer SIA")
        self.assertEqual(details.distributor_name, "Distributor SIA")


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


class ProductionTargetTests(unittest.TestCase):
    DEV_URL = "postgresql://dev:password@dev.example.com:5432/catalog"
    PROD_URL = "postgresql://prod:password@prod.example.com:5432/catalog"

    def test_production_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(ValueError, "confirm-production"):
            get_database_url(
                production=True,
                environment={
                    "PROD_DATABASE_URL": self.PROD_URL,
                    "DATABASE_URL": self.DEV_URL,
                },
            )

    def test_confirmation_cannot_be_used_without_production(self):
        with self.assertRaisesRegex(ValueError, "requires --production"):
            get_database_url(
                production=False,
                confirm_production=True,
                environment={"DATABASE_URL": self.DEV_URL},
            )

    def test_production_requires_separate_database_url(self):
        with self.assertRaisesRegex(ValueError, "PROD_DATABASE_URL"):
            get_database_url(production=True, confirm_production=True, environment={})

    def test_production_rejects_same_database_url(self):
        with self.assertRaisesRegex(ValueError, "must differ"):
            get_database_url(
                production=True,
                confirm_production=True,
                environment={
                    "DATABASE_URL": self.DEV_URL,
                    "PROD_DATABASE_URL": self.DEV_URL,
                },
            )

    def test_production_resolves_explicit_production_url(self):
        self.assertEqual(
            get_database_url(
                production=True,
                confirm_production=True,
                environment={
                    "DATABASE_URL": self.DEV_URL,
                    "PROD_DATABASE_URL": self.PROD_URL,
                },
            ),
            self.PROD_URL,
        )

    def test_production_rejects_equivalent_urls_with_different_credentials_and_options(self):
        development_url = (
            "postgresql://dev:one@DB.EXAMPLE.COM/catalog?sslmode=require"
        )
        production_url = (
            "postgresql://prod:two@db.example.com:5432/catalog?application_name=backfill"
        )
        with self.assertRaisesRegex(ValueError, "must differ"):
            get_database_url(
                production=True,
                confirm_production=True,
                environment={
                    "DATABASE_URL": development_url,
                    "PROD_DATABASE_URL": production_url,
                },
            )

    def test_production_guard_runs_before_database_connection(self):
        connection_factory = Mock()
        parser = Mock()
        with self.assertRaisesRegex(ValueError, "confirm-production"):
            run_backfill(
                "prod",
                parser=parser,
                production=True,
                confirm_production=False,
                connection_factory=connection_factory,
            )
        connection_factory.assert_not_called()
        parser.extract_product_details.assert_not_called()

    def test_programmatic_production_run_rejects_unvalidated_target(self):
        connection_factory = Mock()
        parser = Mock()
        other_url = "postgresql://other:password@other.example.com:5432/catalog"
        with self.assertRaisesRegex(ValueError, "validated PROD_DATABASE_URL"):
            run_backfill(
                other_url,
                parser=parser,
                production=True,
                confirm_production=True,
                environment={
                    "DATABASE_URL": self.DEV_URL,
                    "PROD_DATABASE_URL": self.PROD_URL,
                },
                connection_factory=connection_factory,
            )
        connection_factory.assert_not_called()
        parser.extract_product_details.assert_not_called()


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
    def __init__(self, connection, rows=None):
        self.connection = connection
        self.rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args, **kwargs):
        sql = " ".join(str(args[0]).split()) if args else ""
        if (
            self.connection.fail_on_execute
            and sql.startswith(self.connection.fail_on_execute)
        ):
            raise RuntimeError(f"forced execute failure: {sql}")
        return None

    def fetchall(self):
        self.connection.fetchall_calls += 1
        if not self.connection.pages:
            return []
        return self.connection.pages.pop(0)


class FakeConnection:
    def __init__(
        self,
        rows=None,
        pages=None,
        fail_commit_on=None,
        fail_on_execute=None,
    ):
        self.rows = rows
        self.pages = list(pages) if pages is not None else [rows or []]
        self.committed = False
        self.commit_count = 0
        self.rollback_count = 0
        self.fetchall_calls = 0
        self.fail_commit_on = fail_commit_on
        self.fail_on_execute = fail_on_execute

    def cursor(self, *args, **kwargs):
        return FakeCursor(self, self.rows)

    def commit(self):
        self.committed = True
        self.commit_count += 1
        if self.commit_count == self.fail_commit_on:
            raise RuntimeError("forced commit failure")

    def rollback(self):
        self.rollback_count += 1

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
        connection = FakeConnection(rows)
        with patch("backfill_brand_producer.persist_brand_producer_links") as persist:
            with patch("backfill_brand_producer.ensure_brand_producer_schema"):
                result = run_backfill(
                    "db", parser=parser, retries=0, delay=0,
                    sleep_fn=lambda _: None, connection_factory=lambda _: connection,
                )
        self.assertEqual(result["selected"], 2)
        self.assertEqual(result["attempted"], 2)
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
        connection = FakeConnection(rows)
        with patch("backfill_brand_producer.persist_brand_producer_links"):
            with patch("backfill_brand_producer.ensure_brand_producer_schema"):
                result = run_backfill(
                    "db", parser=parser, retries=0, delay=0,
                    sleep_fn=lambda _: None, connection_factory=lambda _: connection,
                )
        self.assertEqual(result["resume_after_product_id"], 1)
        self.assertEqual(result["failed_product_ids"], [2])

    def test_limit_counts_failed_attempts(self):
        rows = [
            {"product_id": 1, "sku": "bad-1", "barbora_url": "https://barbora.lv/bad-1"},
            {"product_id": 2, "sku": "bad-2", "barbora_url": "https://barbora.lv/bad-2"},
        ]
        parser = SimpleNamespace(extract_product_details=lambda _url: None)
        connection = FakeConnection(rows)
        with patch("backfill_brand_producer.ensure_brand_producer_schema"):
            result = run_backfill(
                "db",
                parser=parser,
                limit=1,
                batch_size=25,
                retries=0,
                delay=0,
                sleep_fn=lambda _: None,
                connection_factory=lambda _: connection,
            )
        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["errors"], 1)

    def test_production_uses_read_only_schema_preflight(self):
        connection = FakeConnection([])
        with patch("backfill_brand_producer.verify_brand_producer_schema") as verify:
            result = run_backfill(
                ProductionTargetTests.PROD_URL,
                parser=SimpleNamespace(),
                production=True,
                confirm_production=True,
                retries=0,
                delay=0,
                environment={
                    "DATABASE_URL": ProductionTargetTests.DEV_URL,
                    "PROD_DATABASE_URL": ProductionTargetTests.PROD_URL,
                },
                connection_factory=lambda _: connection,
            )
        verify.assert_called_once_with(connection)
        self.assertTrue(result["dry_run"] is False)

    def test_commits_each_completed_batch(self):
        pages = [
            [
                {"product_id": 1, "sku": "one", "barbora_url": "https://barbora.lv/one"},
                {"product_id": 2, "sku": "two", "barbora_url": "https://barbora.lv/two"},
            ],
            [
                {"product_id": 3, "sku": "three", "barbora_url": "https://barbora.lv/three"},
            ],
        ]
        parser = SimpleNamespace(
            extract_product_details=lambda _url: SimpleNamespace(
                brand="Laima", producer="Orkla", manufacturer=None
            )
        )
        connection = FakeConnection(pages=pages)
        with patch("backfill_brand_producer.ensure_brand_producer_schema"):
            with patch("backfill_brand_producer.persist_brand_producer_links"):
                result = run_backfill(
                    "db",
                    parser=parser,
                    batch_size=2,
                    retries=0,
                    delay=0,
                    sleep_fn=lambda _: None,
                    connection_factory=lambda _: connection,
                )
        self.assertEqual(result["attempted"], 3)
        self.assertEqual(connection.commit_count, 2)

    def test_dry_run_rolls_back_instead_of_committing_batch(self):
        rows = [
            {"product_id": 1, "sku": "one", "barbora_url": "https://barbora.lv/one"},
        ]
        parser = SimpleNamespace(
            extract_product_details=lambda _url: SimpleNamespace(
                brand="Laima", producer="Orkla", manufacturer=None
            )
        )
        connection = FakeConnection(rows)
        with patch("backfill_brand_producer.verify_brand_producer_schema") as verify:
            with patch("backfill_brand_producer.ensure_brand_producer_schema") as ensure:
                with patch("backfill_brand_producer.persist_brand_producer_links"):
                    result = run_backfill(
                        "db",
                        parser=parser,
                        dry_run=True,
                        retries=0,
                        delay=0,
                        sleep_fn=lambda _: None,
                        connection_factory=lambda _: connection,
                    )
        verify.assert_called_once_with(connection)
        ensure.assert_not_called()
        self.assertTrue(result["dry_run"])
        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(result["resume_after_product_id"], 0)
        self.assertEqual(result["simulated_resume_after_product_id"], 1)

    def test_commit_failure_reports_last_durable_resume_cursor(self):
        pages = [
            [{"product_id": 1, "sku": "one", "barbora_url": "https://barbora.lv/one"}],
            [{"product_id": 2, "sku": "two", "barbora_url": "https://barbora.lv/two"}],
        ]
        parser = SimpleNamespace(
            extract_product_details=lambda _url: SimpleNamespace(
                brand="Laima", producer="Orkla", manufacturer=None
            )
        )
        connection = FakeConnection(pages=pages, fail_commit_on=2)
        with patch("backfill_brand_producer.ensure_brand_producer_schema"):
            with patch("backfill_brand_producer.persist_brand_producer_links"):
                with self.assertRaises(BackfillFatalError) as raised:
                    run_backfill(
                        "db",
                        parser=parser,
                        batch_size=1,
                        retries=0,
                        delay=0,
                        sleep_fn=lambda _: None,
                        connection_factory=lambda _: connection,
                    )
        result = raised.exception.result
        self.assertEqual(result["resume_after_product_id"], 1)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["status"], "failed")
        self.assertIn("commit failure", result["fatal_error"])

    def test_savepoint_recovery_failure_keeps_last_durable_cursor(self):
        rows = [
            {"product_id": 1, "sku": "bad", "barbora_url": "https://barbora.lv/bad"},
        ]
        connection = FakeConnection(
            rows=rows,
            fail_on_execute="ROLLBACK TO SAVEPOINT",
        )
        with patch("backfill_brand_producer.ensure_brand_producer_schema"):
            with self.assertRaises(BackfillFatalError) as raised:
                run_backfill(
                    "db",
                    parser=SimpleNamespace(extract_product_details=lambda _url: None),
                    retries=0,
                    delay=0,
                    sleep_fn=lambda _: None,
                    connection_factory=lambda _: connection,
                )
        self.assertEqual(raised.exception.result["resume_after_product_id"], 0)
        self.assertEqual(raised.exception.result["status"], "failed")

    def test_main_returns_failure_exit_status_when_any_product_fails(self):
        with patch("backfill_brand_producer.get_database_url", return_value="db"):
            with patch(
                "backfill_brand_producer.run_backfill",
                return_value={"errors": 1},
            ):
                with patch("builtins.print"):
                    exit_code = __import__("backfill_brand_producer").main([])
        self.assertEqual(exit_code, 1)

    def test_main_returns_guard_failure_without_traceback(self):
        with patch.dict("os.environ", {"DATABASE_URL": "dev"}, clear=True):
            with patch("builtins.print") as output:
                exit_code = __import__("backfill_brand_producer").main(["--production"])
        self.assertEqual(exit_code, 2)
        output.assert_called_once()
        self.assertIn("--confirm-production", output.call_args.args[0])
        self.assertEqual(json.loads(output.call_args.args[0])["status"], "failed")

    def test_main_prints_fatal_recovery_summary_as_json(self):
        fatal_result = {
            "status": "failed",
            "fatal_error": "forced commit failure",
            "resume_after_product_id": 25,
        }
        with patch(
            "backfill_brand_producer.run_backfill",
            side_effect=BackfillFatalError("forced commit failure", fatal_result),
        ):
            with patch("builtins.print") as output:
                exit_code = __import__("backfill_brand_producer").main([])
        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(output.call_args.args[0]), fatal_result)

    def test_schema_migration_is_ordered_and_committed(self):
        conn = FakeConnection()
        ensure_brand_producer_schema(conn)
        self.assertTrue(conn.committed)

    def test_schema_preflight_accepts_complete_schema_without_writes(self):
        connection = FakeConnection(
            pages=[
                [("brands",), ("producers",), ("brand_producers",)],
                [
                    ("brands", "id"),
                    ("brands", "name"),
                    ("brands", "normalized_name"),
                    ("producers", "id"),
                    ("producers", "name"),
                    ("producers", "normalized_name"),
                    ("brand_producers", "brand_id"),
                    ("brand_producers", "producer_id"),
                    ("products", "product_id"),
                    ("products", "brand_id"),
                    ("products", "producer_id"),
                    ("products", "updated_at"),
                ],
                [
                    ("brands", ["normalized_name"]),
                    ("producers", ["normalized_name"]),
                    ("brand_producers", ["brand_id", "producer_id"]),
                ],
            ]
        )
        verify_brand_producer_schema(connection)
        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 0)

    def test_schema_preflight_reports_publish_requirement(self):
        connection = FakeConnection(
            pages=[
                [("brands",), ("producers",)],
                [
                    ("brands", "id"),
                    ("producers", "id"),
                    ("products", "product_id"),
                    ("products", "brand_id"),
                ],
                [],
            ]
        )
        with self.assertRaisesRegex(RuntimeError, "Publish the latest development schema"):
            verify_brand_producer_schema(connection)

    def test_schema_preflight_rejects_missing_conflict_target(self):
        connection = FakeConnection(
            pages=[
                [("brands",), ("producers",), ("brand_producers",)],
                [
                    ("brands", "id"),
                    ("brands", "name"),
                    ("brands", "normalized_name"),
                    ("producers", "id"),
                    ("producers", "name"),
                    ("producers", "normalized_name"),
                    ("brand_producers", "brand_id"),
                    ("brand_producers", "producer_id"),
                    ("products", "product_id"),
                    ("products", "brand_id"),
                    ("products", "producer_id"),
                    ("products", "updated_at"),
                ],
                [
                    ("brands", ["normalized_name"]),
                    ("producers", ["normalized_name"]),
                ],
            ]
        )
        with self.assertRaisesRegex(
            RuntimeError,
            r"brand_producers\(brand_id, producer_id\)",
        ):
            verify_brand_producer_schema(connection)


if __name__ == "__main__":
    unittest.main()