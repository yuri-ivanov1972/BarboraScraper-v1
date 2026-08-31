#!/usr/bin/env python3
"""Apply the idempotent brand/producer schema migration."""

import os
import psycopg2

from brand_producer import ensure_brand_producer_schema


def main():
    connection = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        ensure_brand_producer_schema(connection)
    finally:
        connection.close()
    print("Brand/producer schema migration complete.")


if __name__ == "__main__":
    main()