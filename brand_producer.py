"""Shared brand and producer normalization and persistence helpers."""

from typing import Optional, Tuple
import re
import unicodedata
from urllib.parse import urlparse


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS brands (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        normalized_name TEXT NOT NULL UNIQUE,
        website_url TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS producers (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        normalized_name TEXT NOT NULL UNIQUE,
        website_url TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS brand_producers (
        brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
        producer_id INTEGER NOT NULL REFERENCES producers(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (brand_id, producer_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_brand_producers_producer ON brand_producers (producer_id)",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brands(id)",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS producer_id INTEGER REFERENCES producers(id)",
    "CREATE INDEX IF NOT EXISTS idx_products_brand ON products (brand_id)",
    "CREATE INDEX IF NOT EXISTS idx_products_producer ON products (producer_id)",
)


def ensure_brand_producer_schema(connection) -> None:
    """Apply the ordered, idempotent brand/producer migration."""
    try:
        with connection.cursor() as cur:
            for statement in SCHEMA_STATEMENTS:
                cur.execute(statement)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def clean_label(value: Optional[str]) -> Optional[str]:
    """Return a trimmed, whitespace-collapsed label or None for blank values."""
    if value is None:
        return None
    cleaned = unicodedata.normalize("NFKC", str(value))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def normalize_entity_name(value: Optional[str]) -> Optional[str]:
    """Normalize names for matching without stripping Latvian diacritics."""
    cleaned = clean_label(value)
    return cleaned.casefold() if cleaned else None


def normalize_website_url(value: Optional[str]) -> Optional[str]:
    """Return a safe manual website URL, or reject non-HTTP(S) input."""
    cleaned = clean_label(value)
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Website URL must be a complete http:// or https:// address")
    return cleaned


def _get_or_create_entity(cur, table: str, name: Optional[str]) -> Optional[int]:
    cleaned = clean_label(name)
    normalized = normalize_entity_name(cleaned)
    if not normalized:
        return None

    # The table name is selected internally, never supplied by a user.
    cur.execute(
        f"""
        INSERT INTO {table} (name, normalized_name)
        VALUES (%s, %s)
        ON CONFLICT (normalized_name) DO UPDATE SET normalized_name = EXCLUDED.normalized_name
        RETURNING id
        """,
        (cleaned, normalized),
    )
    row = cur.fetchone()
    return row[0] if not isinstance(row, dict) else row["id"]


def persist_brand_producer_links(
    cur,
    product_id: int,
    brand_name: Optional[str] = None,
    producer_name: Optional[str] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """Persist current product links and historical associations transactionally."""
    brand_id = _get_or_create_entity(cur, "brands", brand_name)
    producer_id = _get_or_create_entity(cur, "producers", producer_name)

    cur.execute(
        """
        UPDATE products
        SET brand_id = %s, producer_id = %s, updated_at = CURRENT_TIMESTAMP
        WHERE product_id = %s
        """,
        (brand_id, producer_id, product_id),
    )

    if brand_id is not None and producer_id is not None:
        cur.execute(
            """
            INSERT INTO brand_producers (brand_id, producer_id)
            VALUES (%s, %s)
            ON CONFLICT (brand_id, producer_id) DO NOTHING
            """,
            (brand_id, producer_id),
        )

    return brand_id, producer_id