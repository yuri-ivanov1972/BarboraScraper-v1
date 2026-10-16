"""Bounded photo verification. No network requests hold database connections open."""
import time
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import requests
from psycopg2.extras import RealDictCursor


def normalize_url(value):
    if not isinstance(value, str):
        return None
    try:
        p = urlsplit(value or "")
        if (p.scheme != "https" or p.hostname != "cdn.barbora.lv"
                or p.username or p.password or p.port not in (None, 443)
                or "placeholder" in p.path.lower()):
            return None
        return urlunsplit(("https", p.hostname, p.path, p.query, ""))
    except ValueError:
        return None


def check_image(url, session=None):
    """GET a small image prefix: HEAD is often denied even for valid images."""
    if not normalize_url(url):
        return "invalid_url", None
    try:
        with (session or requests).get(
            url, timeout=(3, 5), stream=True, allow_redirects=False,
            headers={"Accept": "image/*", "Range": "bytes=0-511"},
        ) as response:
            code = response.status_code
            if code in (401, 403, 429):
                return "access_blocked", code
            if code in (404, 410):
                return "missing_evidence", code
            if code not in (200, 206):
                return "temporary_failure", code
            data = next(response.iter_content(512), b"")
            magic = (data.startswith(b"\x89PNG\r\n\x1a\n") or
                     data.startswith(b"\xff\xd8\xff") or
                     data.startswith((b"GIF87a", b"GIF89a")) or
                     (data.startswith(b"RIFF") and data[8:12] == b"WEBP"))
            if response.headers.get("Content-Type", "").lower().startswith("image/") and magic:
                return "working", code
            return "invalid_content", code
    except requests.RequestException:
        return "temporary_failure", None


SCHEMA = """
CREATE TABLE IF NOT EXISTS photo_maintenance (
 product_id integer PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
 candidate_url text, managed_url text, ownership text NOT NULL DEFAULT 'unknown',
 status text NOT NULL DEFAULT 'not_checked', http_status integer,
 last_attempt timestamptz, last_success timestamptz,
 next_due timestamptz NOT NULL DEFAULT now(), missing_count integer NOT NULL DEFAULT 0,
 outcome text NOT NULL DEFAULT '', observed_at timestamptz
);
CREATE TABLE IF NOT EXISTS photo_host_cooldown (
 host text PRIMARY KEY, paused_until timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS photo_maintenance_due ON photo_maintenance(next_due);
CREATE TABLE IF NOT EXISTS photo_maintenance_config (
 id integer PRIMARY KEY CHECK(id=1), enabled boolean NOT NULL DEFAULT false,
 leased_until timestamptz
);
INSERT INTO photo_maintenance_config(id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS photo_url_verification (
 url text PRIMARY KEY, status text NOT NULL, http_status integer,
 last_attempt timestamptz NOT NULL DEFAULT now(), last_success timestamptz,
 next_due timestamptz NOT NULL, missing_count integer NOT NULL DEFAULT 0
);
"""


class PhotoMaintenance:
    def __init__(self, database_url):
        self.database_url = database_url

    def connect(self):
        return psycopg2.connect(self.database_url, cursor_factory=RealDictCursor,
                                connect_timeout=5,
                                options="-c statement_timeout=10000 -c lock_timeout=3000")

    def initialize(self):
        conn = self.connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(SCHEMA)
        finally:
            conn.close()

    @staticmethod
    def observe(cur, product_id, url):
        url = normalize_url(url)
        if not url:
            return
        cur.execute("""
            INSERT INTO photo_maintenance(product_id,candidate_url,observed_at)
            VALUES (%s,%s,now()) ON CONFLICT(product_id) DO UPDATE SET
              next_due=CASE WHEN photo_maintenance.candidate_url IS DISTINCT FROM excluded.candidate_url
                            THEN now() ELSE photo_maintenance.next_due END,
              missing_count=CASE WHEN photo_maintenance.candidate_url IS DISTINCT FROM excluded.candidate_url
                            THEN 0 ELSE photo_maintenance.missing_count END,
              candidate_url=excluded.candidate_url, observed_at=now()
        """, (product_id, url))

    def rows(self):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.product_id,p.sku,p.name,p.barbora_url,
                           ph.photo_url,ph.photo_id,COALESCE(ph.effective_primary,true) effective_primary,
                           m.candidate_url,target.check_url,target.kind,
                           COALESCE(m.ownership,'unknown') ownership,
                           CASE WHEN ph.photo_url IS NULL AND m.candidate_url IS NULL
                             THEN 'missing_photo' ELSE COALESCE(v.status,'not_checked') END status,
                           v.http_status,v.last_attempt,v.last_success,v.next_due,
                           m.outcome, COALESCE(a.is_available,false) is_available,
                           h.paused_until
                    FROM products p
                    LEFT JOIN photo_maintenance m USING(product_id)
                    LEFT JOIN LATERAL (
                        SELECT photo_id,photo_url,
                          row_number() OVER(ORDER BY is_primary DESC NULLS LAST,photo_id)=1 effective_primary
                        FROM productphotos
                        WHERE product_id=p.product_id
                    ) ph ON true
                    LEFT JOIN LATERAL (
                        SELECT ph.photo_url AS check_url,'stored' AS kind
                        WHERE ph.photo_url IS NOT NULL
                        UNION ALL
                        SELECT m.candidate_url,'candidate'
                        WHERE COALESCE(ph.effective_primary,true)
                          AND m.candidate_url IS NOT NULL
                          AND m.candidate_url IS DISTINCT FROM ph.photo_url
                    ) target ON true
                    LEFT JOIN photo_url_verification v ON v.url=target.check_url
                    LEFT JOIN LATERAL (
                        SELECT is_available FROM product_price_history
                        WHERE product_id=p.product_id ORDER BY recorded_at DESC LIMIT 1
                    ) a ON true
                    LEFT JOIN photo_host_cooldown h ON h.host='cdn.barbora.lv'
                    WHERE p.barbora_url IS NOT NULL
                    ORDER BY v.next_due NULLS FIRST,
                             (target.kind='candidate') DESC,p.product_id,ph.photo_id
                """)
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def set_ownership(self, product_id, ownership):
        if ownership not in {"manual", "retailer"}:
            raise ValueError("Invalid ownership")
        conn = self.connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO photo_maintenance(product_id,ownership)
                    VALUES (%s,%s) ON CONFLICT(product_id) DO UPDATE
                    SET ownership=excluded.ownership,next_due=now()
                """, (product_id, ownership))
                cur.execute("""
                    UPDATE photo_maintenance SET managed_url=CASE WHEN ownership='retailer'
                      THEN (SELECT photo_url FROM productphotos WHERE product_id=%s
                            ORDER BY is_primary DESC NULLS LAST,photo_id LIMIT 1) END
                    WHERE product_id=%s
                """, (product_id, product_id))
                cur.execute("""
                    UPDATE photo_url_verification SET next_due=now()
                    WHERE url IN (
                      SELECT candidate_url FROM photo_maintenance WHERE product_id=%s
                      UNION SELECT photo_url FROM productphotos WHERE product_id=%s
                    )
                """, (product_id, product_id))
        finally:
            conn.close()

    def approve_retailer_ownership(self, product_ids):
        """Explicit batch approval never overrides a concurrently marked manual photo."""
        conn = self.connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO photo_maintenance(product_id,ownership,managed_url)
                    SELECT p.product_id,'retailer',ph.photo_url FROM products p
                    LEFT JOIN LATERAL (
                      SELECT photo_url FROM productphotos WHERE product_id=p.product_id
                      ORDER BY is_primary DESC NULLS LAST,photo_id LIMIT 1
                    ) ph ON true
                    WHERE p.product_id=ANY(%s)
                    ON CONFLICT(product_id) DO UPDATE
                      SET ownership='retailer',managed_url=excluded.managed_url,next_due=now()
                    WHERE photo_maintenance.ownership='unknown'
                    RETURNING product_id
                """, (product_ids,))
                ids = [r["product_id"] for r in cur.fetchall()]
                cur.execute("""
                    UPDATE photo_url_verification SET next_due=now() WHERE url IN (
                      SELECT candidate_url FROM photo_maintenance WHERE product_id=ANY(%s)
                      UNION SELECT photo_url FROM productphotos WHERE product_id=ANY(%s)
                    )
                """, (ids, ids))
                return len(ids)
        finally:
            conn.close()

    def set_enabled(self, enabled):
        conn = self.connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("UPDATE photo_maintenance_config SET enabled=%s WHERE id=1",
                            (enabled,))
        finally:
            conn.close()

    def enabled(self):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT enabled FROM photo_maintenance_config WHERE id=1")
                return cur.fetchone()["enabled"]
        finally:
            conn.close()

    def run_scheduled(self):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT enabled FROM photo_maintenance_config WHERE id=1")
                enabled = cur.fetchone()["enabled"]
        finally:
            conn.close()
        return self.run(apply=True, limit=1500, seconds=1200) if enabled else []

    def run(self, apply=False, limit=100, seconds=90):
        """Preview leaves photos and results unchanged; only a temporary run lease is written."""
        from datetime import datetime, timezone
        start = time.monotonic()
        results, cache = [], {}
        conn = self.connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("""
                    UPDATE photo_maintenance_config
                    SET leased_until=now()+(%s * interval '1 second')
                    WHERE id=1 AND (leased_until IS NULL OR leased_until < now())
                    RETURNING id
                """, (seconds + 30,))
                if not cur.fetchone():
                    return []
        finally:
            conn.close()
        # Lease expires after the run budget, including on crashes; no open network-time DB session.
        candidates = self.rows()
        now = datetime.now(timezone.utc)
        session = requests.Session()
        try:
            for row in candidates:
                if len(results) >= limit or time.monotonic() - start > seconds - 10:
                    break
                if not row["is_available"] or row["ownership"] == "manual":
                    continue
                if row["paused_until"] and row["paused_until"] > now:
                    break
                if row["next_due"] and row["next_due"] > now:
                    continue
                url = row["check_url"]
                if not normalize_url(url):
                    continue
                if url not in cache:
                    if cache:
                        time.sleep(0.5)
                    cache[url] = check_image(url, session)
                status, code = cache[url]
                result = dict(row, checked_url=url, check_result=status, check_http=code)
                if apply:
                    result["outcome"] = self.save_result(row, url, status, code)
                else:
                    if status != "working":
                        action = "Retain existing photos"
                    elif row["effective_primary"] and row["candidate_url"] and not row["photo_url"]:
                        action = "Would add retailer primary"
                    elif row["effective_primary"] and url != row["photo_url"]:
                        action = ("Would replace retailer primary" if row["ownership"] == "retailer"
                                  else "Review ownership before replacement")
                    else:
                        action = "No photo changes needed"
                    result["outcome"] = "Preview: " + action
                results.append(result)
                if status == "access_blocked":
                    break
        finally:
            session.close()
            conn = self.connect()
            try:
                with conn, conn.cursor() as cur:
                    cur.execute("UPDATE photo_maintenance_config SET leased_until=NULL WHERE id=1")
            finally:
                conn.close()
        return results

    def save_result(self, row, url, status, code):
        conn = self.connect()
        try:
            with conn, conn.cursor() as cur:
                # Serialize maintenance and manual protection changes on this product.
                cur.execute("SELECT product_id FROM products WHERE product_id=%s FOR UPDATE",
                            (row["product_id"],))
                cur.execute("""
                    SELECT is_available FROM product_price_history WHERE product_id=%s
                    ORDER BY recorded_at DESC LIMIT 1
                """, (row["product_id"],))
                latest = cur.fetchone()
                if not latest or not latest["is_available"]:
                    return "Skipped: product is no longer available"
                cur.execute("""
                    INSERT INTO photo_maintenance(product_id) VALUES (%s)
                    ON CONFLICT DO NOTHING
                """, (row["product_id"],))
                cur.execute("SELECT * FROM photo_maintenance WHERE product_id=%s FOR UPDATE",
                            (row["product_id"],))
                state = cur.fetchone()
                if row["effective_primary"]:
                    cur.execute("""
                        SELECT photo_id,photo_url FROM productphotos WHERE product_id=%s
                        ORDER BY is_primary DESC NULLS LAST,photo_id LIMIT 1 FOR UPDATE
                    """, (row["product_id"],))
                else:
                    cur.execute("SELECT photo_id,photo_url FROM productphotos WHERE photo_id=%s FOR UPDATE",
                                (row["photo_id"],))
                current = cur.fetchone()
                if (state["ownership"] == "manual" or
                    (current["photo_url"] if current else None) != row["photo_url"] or
                    (current["photo_id"] if current else None) != row["photo_id"] or
                    state["candidate_url"] != row["candidate_url"]):
                    return "Skipped: photo, protection or candidate changed during check"
                if (row["effective_primary"] and current and state["ownership"] == "retailer"
                        and current["photo_url"] != state["managed_url"]):
                    cur.execute("""
                        UPDATE photo_maintenance SET ownership='unknown',
                        outcome='External photo edit detected; ownership review required'
                        WHERE product_id=%s
                    """, (row["product_id"],))
                    return "External photo edit detected; ownership review required"
                outcome = "Verified; existing photos retained"
                cur.execute("""
                    SELECT missing_count, last_attempt <= now()-interval '1 day' AS retry_due
                    FROM photo_url_verification WHERE url=%s
                """, (url,))
                previous = cur.fetchone()
                missing = ((previous["missing_count"] if previous else 0)
                           + (1 if not previous or previous["retry_due"] else 0)
                           if status == "missing_evidence" else 0)
                final_status = ("confirmed_missing" if missing >= 2 else status)
                if status == "working" and row["effective_primary"] and url == state["candidate_url"]:
                    if not current:
                        cur.execute("""
                            INSERT INTO productphotos(product_id,photo_url,is_primary)
                            VALUES (%s,%s,true)
                        """, (row["product_id"], url))
                        outcome = "Added retailer primary"
                        cur.execute("""
                            UPDATE photo_maintenance SET ownership='retailer',managed_url=%s
                            WHERE product_id=%s
                        """, (url, row["product_id"]))
                    elif current["photo_url"] == url:
                        # Matching a listing is not proof that the existing row was not manual.
                        outcome = "Current photo verified; ownership unchanged"
                    elif state["ownership"] == "retailer":
                        cur.execute("UPDATE productphotos SET photo_url=%s WHERE photo_id=%s",
                                    (url, current["photo_id"]))
                        cur.execute("UPDATE photo_maintenance SET managed_url=%s WHERE product_id=%s",
                                    (url, row["product_id"]))
                        outcome = "Replaced retailer primary"
                    else:
                        outcome = "Review ownership before replacement"
                cur.execute("""
                    INSERT INTO photo_url_verification
                      (url,status,http_status,last_attempt,last_success,next_due,missing_count)
                    VALUES (%s,%s,%s,now(),CASE WHEN %s='working' THEN now() END,
                      now()+CASE WHEN %s='working' THEN interval '7 days' ELSE interval '1 day' END,%s)
                    ON CONFLICT(url) DO UPDATE SET status=excluded.status,http_status=excluded.http_status,
                      last_attempt=excluded.last_attempt,
                      last_success=COALESCE(excluded.last_success,photo_url_verification.last_success),
                      next_due=excluded.next_due,missing_count=excluded.missing_count
                """, (url, final_status, code, status, status, missing))
                cur.execute("""
                    UPDATE photo_maintenance SET status=%s,http_status=%s,
                    last_attempt=now(),last_success=CASE WHEN %s='working' THEN now() ELSE last_success END,
                    next_due=now()+CASE WHEN %s='working' THEN interval '7 days'
                                      ELSE interval '1 day' END,
                    missing_count=%s,outcome=%s WHERE product_id=%s
                """, (final_status, code, status, status, missing, outcome, row["product_id"]))
                if status == "access_blocked":
                    cur.execute("""
                        INSERT INTO photo_host_cooldown VALUES ('cdn.barbora.lv',now()+interval '1 day')
                        ON CONFLICT(host) DO UPDATE SET paused_until=excluded.paused_until
                    """)
                return outcome
        finally:
            conn.close()


def main():
    import argparse
    import json
    import os
    parser = argparse.ArgumentParser(description="Bounded Barbora photo maintenance")
    parser.add_argument("--initialize", action="store_true", help="Create additive tracking tables")
    parser.add_argument("--apply", action="store_true", help="Save checks and safe replacements")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1500:
        parser.error("--limit must be between 1 and 1500")
    service = PhotoMaintenance(os.environ["DATABASE_URL"])
    if args.initialize:
        service.initialize()
        print("Tracking initialized; scheduled writes remain opt-in.")
        return
    results = service.run(apply=args.apply, limit=args.limit)
    print(json.dumps(results, default=str, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
