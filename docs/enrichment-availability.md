# Available-only nutrition enrichment

The Nutrition Data Enrichment queue uses each product's newest
`product_price_history` row, ordered by `recorded_at` descending and then
`price_history_id` descending. Only an explicit `is_available=true` qualifies.
Missing history is not evidence of availability; an older available row cannot
override a newer unavailable row.

The same rule applies to:

- Needs Enrichment count and category counts;
- skipped count within the flagged, unreviewed queue;
- products loaded for enrichment, before ordering/pagination and API processing;
- unflagged-missing warning and the tab's explicit Scan & Flag action;
- refresh of previously loaded batches.

Reviewed, From USDA and From Rimi metrics still describe the whole catalogue.
No nutrition completeness criteria, source data, availability records or schema
have been changed by this filtering feature.

Unavailable entries retain their enrichment/review/skipped flags. When available
again, flagged and unreviewed products reappear. Reads do not rewrite timestamps
or flags. Scan & Flag only writes when explicitly clicked, and only flags currently
available products matching the existing missing-nutrition criteria.

On each tab rerun, cached batch matches that are no longer available are removed
without repeating translation or USDA searches. Still-available approved matches
remain as batch history. Other matches must still be awaiting enrichment.
An emptied batch is cleared without automatically processing a new one.
Widget keys use product identity so pruning does not transfer one product's
selection or custom search to another.

Approve/skip/unskip recheck queue eligibility in the write transaction.
An unavailable, removed or no-longer-eligible product is rejected before any
nutrition or flag updates. This is not a redesign of manual-correction protections.

## Verification

No live USDA or translation requests are needed for these tests:

```bash
python -m unittest test_enrichment_availability -v
```

The SQL and interactive Streamlit tests additionally require an empty isolated
local PostgreSQL database with the schema restored. They never use application
database secrets:

```bash
ROOT=$(mktemp -d /tmp/enrichment-availability-db.XXXXXX)
initdb -D "$ROOT/data" --auth=trust --no-locale --encoding=UTF8
pg_ctl -D "$ROOT/data" -l "$ROOT/server.log" \
  -o "-k $ROOT -p 55442 -c listen_addresses=''" -w start
trap 'pg_ctl -D "$ROOT/data" -m fast -w stop' EXIT
psql -X -h "$ROOT" -p 55442 -U runner -d postgres \
  --set=ON_ERROR_STOP=1 --file=docs/database-share/schema.sql
python test_enrichment_availability.py "$ROOT"
```

The fixture covers availability changes in both directions, tied timestamps,
multiple history rows, missing history, preserved flags, category counts,
pagination, skipped ordering, explicit scanning, stale actions, cached batches,
bulk approval and changing category/loading a new batch. Interactive tests render
the actual enrichment section extracted from the application, using real SQL
against this isolated database and mocked external matching.
