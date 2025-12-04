"""
Change Report Module
Compares current vs previous product state to identify changes
"""

import psycopg2
import psycopg2.extras
import os
import time
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ChangeStats:
    total_products: int
    new_products: int
    price_changed: int
    availability_changed: int
    price_increased: int
    price_decreased: int
    became_available: int
    became_unavailable: int


class ChangeReportGenerator:
    def __init__(self):
        self.db_url = os.environ.get('DATABASE_URL')
    
    def _get_connection(self, retries: int = 3, delay: float = 2.0):
        """Get database connection with retry logic for Neon control plane errors"""
        last_error = None
        for attempt in range(retries):
            try:
                return psycopg2.connect(self.db_url)
            except psycopg2.OperationalError as e:
                last_error = e
                error_msg = str(e)
                if "Control plane request failed" in error_msg or "connection" in error_msg.lower():
                    if attempt < retries - 1:
                        time.sleep(delay)
                        continue
                raise
        raise last_error
    
    def get_summary_stats(self) -> ChangeStats:
        """Get high-level summary of changes between current and previous state"""
        query = """
        WITH ranked_prices AS (
            SELECT 
                pph.product_id,
                pph.price,
                pph.is_available,
                pph.recorded_at,
                ROW_NUMBER() OVER (PARTITION BY pph.product_id ORDER BY pph.recorded_at DESC) as rn
            FROM product_price_history pph
        ),
        current_state AS (
            SELECT product_id, price, is_available, recorded_at FROM ranked_prices WHERE rn = 1
        ),
        previous_state AS (
            SELECT product_id, price, is_available, recorded_at FROM ranked_prices WHERE rn = 2
        )
        SELECT 
            COUNT(*) as total_products,
            COUNT(*) FILTER (WHERE p.product_id IS NULL) as new_products,
            COUNT(*) FILTER (WHERE c.price != p.price) as price_changed,
            COUNT(*) FILTER (WHERE c.is_available != p.is_available) as availability_changed,
            COUNT(*) FILTER (WHERE c.price > p.price) as price_increased,
            COUNT(*) FILTER (WHERE c.price < p.price) as price_decreased,
            COUNT(*) FILTER (WHERE c.is_available = true AND p.is_available = false) as became_available,
            COUNT(*) FILTER (WHERE c.is_available = false AND p.is_available = true) as became_unavailable
        FROM current_state c
        LEFT JOIN previous_state p ON c.product_id = p.product_id
        """
        
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query)
                row = cur.fetchone()
                return ChangeStats(
                    total_products=row['total_products'],
                    new_products=row['new_products'],
                    price_changed=row['price_changed'],
                    availability_changed=row['availability_changed'],
                    price_increased=row['price_increased'],
                    price_decreased=row['price_decreased'],
                    became_available=row['became_available'],
                    became_unavailable=row['became_unavailable']
                )
    
    def get_price_changes(self, limit: int = 50) -> List[Dict]:
        """Get products with price changes, sorted by absolute change percentage"""
        query = """
        WITH ranked_prices AS (
            SELECT 
                pph.product_id,
                pph.price,
                pph.is_available,
                pph.recorded_at,
                ROW_NUMBER() OVER (PARTITION BY pph.product_id ORDER BY pph.recorded_at DESC) as rn
            FROM product_price_history pph
        ),
        current_state AS (
            SELECT product_id, price, is_available, recorded_at FROM ranked_prices WHERE rn = 1
        ),
        previous_state AS (
            SELECT product_id, price, is_available, recorded_at FROM ranked_prices WHERE rn = 2
        )
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            nc.name_lv as category_name,
            nc.rimi_category_code as category_code,
            prev.price as previous_price,
            c.price as current_price,
            (c.price - prev.price) as price_diff,
            ROUND(((c.price - prev.price) / NULLIF(prev.price, 0) * 100)::numeric, 1) as price_change_pct,
            prev.recorded_at as previous_recorded_at,
            c.recorded_at as current_recorded_at
        FROM current_state c
        JOIN products p ON c.product_id = p.product_id
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        JOIN previous_state prev ON c.product_id = prev.product_id
        WHERE c.price != prev.price
        ORDER BY ABS((c.price - prev.price) / NULLIF(prev.price, 0)) DESC NULLS LAST
        LIMIT %s
        """
        
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]
    
    def get_availability_changes(self, limit: int = 50) -> List[Dict]:
        """Get products with availability changes"""
        query = """
        WITH ranked_prices AS (
            SELECT 
                pph.product_id,
                pph.price,
                pph.is_available,
                pph.recorded_at,
                ROW_NUMBER() OVER (PARTITION BY pph.product_id ORDER BY pph.recorded_at DESC) as rn
            FROM product_price_history pph
        ),
        current_state AS (
            SELECT product_id, price, is_available, recorded_at FROM ranked_prices WHERE rn = 1
        ),
        previous_state AS (
            SELECT product_id, price, is_available, recorded_at FROM ranked_prices WHERE rn = 2
        )
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            nc.name_lv as category_name,
            nc.rimi_category_code as category_code,
            prev.is_available as previous_available,
            c.is_available as current_available,
            c.price as current_price,
            prev.recorded_at as previous_recorded_at,
            c.recorded_at as current_recorded_at
        FROM current_state c
        JOIN products p ON c.product_id = p.product_id
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        JOIN previous_state prev ON c.product_id = prev.product_id
        WHERE c.is_available != prev.is_available
        ORDER BY c.recorded_at DESC
        LIMIT %s
        """
        
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]
    
    def get_new_products(self, limit: int = 50) -> List[Dict]:
        """Get newly added products (only 1 price history record)"""
        query = """
        WITH product_history_count AS (
            SELECT product_id, COUNT(*) as record_count
            FROM product_price_history
            GROUP BY product_id
            HAVING COUNT(*) = 1
        )
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            nc.name_lv as category_name,
            nc.rimi_category_code as category_code,
            pph.price,
            pph.is_available,
            pph.recorded_at
        FROM product_history_count phc
        JOIN products p ON phc.product_id = p.product_id
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        JOIN product_price_history pph ON p.product_id = pph.product_id
        ORDER BY pph.recorded_at DESC
        LIMIT %s
        """
        
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]
    
    def get_category_breakdown(self) -> List[Dict]:
        """Get change summary per category"""
        query = """
        WITH ranked_prices AS (
            SELECT 
                pph.product_id,
                pph.price,
                pph.is_available,
                ROW_NUMBER() OVER (PARTITION BY pph.product_id ORDER BY pph.recorded_at DESC) as rn
            FROM product_price_history pph
        ),
        current_state AS (
            SELECT product_id, price, is_available FROM ranked_prices WHERE rn = 1
        ),
        previous_state AS (
            SELECT product_id, price, is_available FROM ranked_prices WHERE rn = 2
        ),
        product_changes AS (
            SELECT 
                p.category_id,
                CASE WHEN prev.product_id IS NULL THEN 1 ELSE 0 END as is_new,
                CASE WHEN c.price != prev.price THEN 1 ELSE 0 END as price_changed,
                CASE WHEN c.is_available != prev.is_available THEN 1 ELSE 0 END as availability_changed
            FROM current_state c
            JOIN products p ON c.product_id = p.product_id
            LEFT JOIN previous_state prev ON c.product_id = prev.product_id
        )
        SELECT 
            nc.category_id,
            nc.name_lv as category_name,
            nc.rimi_category_code as category_code,
            COUNT(*) as total_products,
            SUM(is_new) as new_products,
            SUM(price_changed) as price_changed,
            SUM(availability_changed) as availability_changed
        FROM product_changes pc
        JOIN normalized_categories nc ON pc.category_id = nc.category_id
        GROUP BY nc.category_id, nc.name_lv, nc.rimi_category_code
        HAVING SUM(is_new) > 0 OR SUM(price_changed) > 0 OR SUM(availability_changed) > 0
        ORDER BY (SUM(is_new) + SUM(price_changed) + SUM(availability_changed)) DESC
        """
        
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query)
                return [dict(row) for row in cur.fetchall()]
    
    def get_update_timestamps(self) -> Dict:
        """Get the timestamps of current and previous update sessions.
        
        An update session is a group of updates that happen close together in time.
        Sessions are separated by gaps of more than 6 hours.
        """
        query = """
        WITH distinct_hours AS (
            SELECT DISTINCT DATE_TRUNC('hour', recorded_at) as hour_ts
            FROM product_price_history
            ORDER BY hour_ts DESC
        ),
        hours_with_gaps AS (
            SELECT 
                hour_ts,
                LAG(hour_ts) OVER (ORDER BY hour_ts DESC) as prev_hour,
                EXTRACT(EPOCH FROM (LAG(hour_ts) OVER (ORDER BY hour_ts DESC) - hour_ts)) / 3600 as hours_since_prev
            FROM distinct_hours
        ),
        session_boundaries AS (
            SELECT 
                hour_ts,
                CASE 
                    WHEN hours_since_prev IS NULL THEN 1
                    WHEN hours_since_prev > 6 THEN 1
                    ELSE 0 
                END as is_new_session
            FROM hours_with_gaps
        ),
        sessions AS (
            SELECT 
                hour_ts,
                SUM(is_new_session) OVER (ORDER BY hour_ts DESC) as session_num
            FROM session_boundaries
        ),
        session_ranges AS (
            SELECT 
                session_num,
                MAX(hour_ts) as session_end,
                MIN(hour_ts) as session_start
            FROM sessions
            GROUP BY session_num
        )
        SELECT 
            MAX(CASE WHEN session_num = 1 THEN session_end END) as current_update,
            MAX(CASE WHEN session_num = 2 THEN session_end END) as previous_update
        FROM session_ranges
        WHERE session_num <= 2
        """
        
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query)
                row = cur.fetchone()
                return {
                    'current_update': row['current_update'],
                    'previous_update': row['previous_update']
                }
