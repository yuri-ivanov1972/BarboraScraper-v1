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
        self._cached_timestamps = None
    
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
    
    def _get_cached_timestamps(self) -> Dict:
        """Get timestamps with caching to avoid repeated queries"""
        if self._cached_timestamps is None:
            self._cached_timestamps = self.get_update_timestamps()
        return self._cached_timestamps
    
    def get_summary_stats(self) -> ChangeStats:
        """Get high-level summary of changes between current and previous update session.
        Uses effective price (discount_price when available, otherwise regular price)
        to reflect what MansRimi cardholders actually pay.
        
        Compares the state at the current update timestamp vs the previous update timestamp,
        so only products that changed BETWEEN those two sessions are counted."""
        timestamps = self._get_cached_timestamps()
        current_ts = timestamps.get('current_update')
        previous_ts = timestamps.get('previous_update')
        
        if not current_ts or not previous_ts:
            return ChangeStats(
                total_products=0, new_products=0, price_changed=0,
                availability_changed=0, price_increased=0, price_decreased=0,
                became_available=0, became_unavailable=0
            )
        
        query = """
        WITH current_state AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.price,
                pph.discount_price,
                COALESCE(pph.discount_price, pph.price) as effective_price,
                pph.is_available,
                pph.recorded_at
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
            ORDER BY pph.product_id, pph.recorded_at DESC
        ),
        previous_available_state AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.price,
                pph.discount_price,
                COALESCE(pph.discount_price, pph.price) as effective_price
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
              AND pph.is_available = true
            ORDER BY pph.product_id, pph.recorded_at DESC
        ),
        previous_any_state AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.is_available
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
            ORDER BY pph.product_id, pph.recorded_at DESC
        )
        SELECT 
            COUNT(*) as total_products,
            COUNT(*) FILTER (WHERE prev_any.product_id IS NULL) as new_products,
            COUNT(*) FILTER (WHERE c.effective_price != prev_avail.effective_price AND c.is_available = true AND c.effective_price > 0 AND prev_avail.effective_price > 0) as price_changed,
            COUNT(*) FILTER (WHERE c.is_available != prev_any.is_available) as availability_changed,
            COUNT(*) FILTER (WHERE c.effective_price > prev_avail.effective_price AND c.is_available = true AND c.effective_price > 0 AND prev_avail.effective_price > 0) as price_increased,
            COUNT(*) FILTER (WHERE c.effective_price < prev_avail.effective_price AND c.is_available = true AND c.effective_price > 0 AND prev_avail.effective_price > 0) as price_decreased,
            COUNT(*) FILTER (WHERE c.is_available = true AND prev_any.is_available = false) as became_available,
            COUNT(*) FILTER (WHERE c.is_available = false AND prev_any.is_available = true) as became_unavailable
        FROM current_state c
        LEFT JOIN previous_available_state prev_avail ON c.product_id = prev_avail.product_id
        LEFT JOIN previous_any_state prev_any ON c.product_id = prev_any.product_id
        """
        
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (current_ts, previous_ts, previous_ts))
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
        """Get products with price changes between the two update sessions.
        Uses effective price (discount_price when available, otherwise regular price)
        to reflect what MansRimi cardholders actually pay.
        
        Compares the state at current update timestamp vs previous update timestamp."""
        timestamps = self._get_cached_timestamps()
        current_ts = timestamps.get('current_update')
        previous_ts = timestamps.get('previous_update')
        
        if not current_ts or not previous_ts:
            return []
        
        query = """
        WITH current_state AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.price,
                pph.discount_price,
                COALESCE(pph.discount_price, pph.price) as effective_price,
                pph.is_available,
                pph.recorded_at
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
            ORDER BY pph.product_id, pph.recorded_at DESC
        ),
        previous_available_state AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.price,
                pph.discount_price,
                COALESCE(pph.discount_price, pph.price) as effective_price,
                pph.recorded_at
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
              AND pph.is_available = true
            ORDER BY pph.product_id, pph.recorded_at DESC
        )
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            p.rimi_url,
            nc.name_lv as category_name,
            nc.rimi_category_code as category_code,
            prev.effective_price as previous_price,
            c.effective_price as current_price,
            prev.price as previous_regular_price,
            c.price as current_regular_price,
            prev.discount_price as previous_discount_price,
            c.discount_price as current_discount_price,
            (c.effective_price - prev.effective_price) as price_diff,
            ROUND(((c.effective_price - prev.effective_price) / NULLIF(prev.effective_price, 0) * 100)::numeric, 1) as price_change_pct,
            prev.recorded_at as previous_recorded_at,
            c.recorded_at as current_recorded_at,
            CASE WHEN c.discount_price IS NOT NULL THEN true ELSE false END as current_has_discount,
            CASE WHEN prev.discount_price IS NOT NULL THEN true ELSE false END as previous_has_discount
        FROM current_state c
        JOIN products p ON c.product_id = p.product_id
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        JOIN previous_available_state prev ON c.product_id = prev.product_id
        WHERE c.effective_price != prev.effective_price 
          AND c.is_available = true 
          AND c.effective_price > 0
          AND prev.effective_price > 0
        ORDER BY ABS((c.effective_price - prev.effective_price) / NULLIF(prev.effective_price, 0)) DESC NULLS LAST
        LIMIT %s
        """
        
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (current_ts, previous_ts, limit))
                return [dict(row) for row in cur.fetchall()]
    
    def get_availability_changes(self, limit: int = 50) -> List[Dict]:
        """Get products with availability changes between the two update sessions.
        
        Compares the state at current update timestamp vs previous update timestamp."""
        timestamps = self._get_cached_timestamps()
        current_ts = timestamps.get('current_update')
        previous_ts = timestamps.get('previous_update')
        
        if not current_ts or not previous_ts:
            return []
        
        query = """
        WITH current_state AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.price,
                pph.is_available,
                pph.recorded_at
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
            ORDER BY pph.product_id, pph.recorded_at DESC
        ),
        previous_state AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.price,
                pph.is_available,
                pph.recorded_at
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
            ORDER BY pph.product_id, pph.recorded_at DESC
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
                cur.execute(query, (current_ts, previous_ts, limit))
                return [dict(row) for row in cur.fetchall()]
    
    def get_new_products(self, limit: int = 50) -> List[Dict]:
        """Get products that are new between the two update sessions.
        
        A product is considered "new" if it exists in the current session
        but did not exist in the previous session (first record is after previous timestamp)."""
        timestamps = self._get_cached_timestamps()
        current_ts = timestamps.get('current_update')
        previous_ts = timestamps.get('previous_update')
        
        if not current_ts or not previous_ts:
            return []
        
        query = """
        WITH current_products AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.price,
                pph.is_available,
                pph.recorded_at
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
            ORDER BY pph.product_id, pph.recorded_at DESC
        ),
        previous_products AS (
            SELECT DISTINCT pph.product_id
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
        )
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            nc.name_lv as category_name,
            nc.rimi_category_code as category_code,
            cp.price,
            cp.is_available,
            cp.recorded_at
        FROM current_products cp
        JOIN products p ON cp.product_id = p.product_id
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        LEFT JOIN previous_products pp ON cp.product_id = pp.product_id
        WHERE pp.product_id IS NULL
        ORDER BY cp.recorded_at DESC
        LIMIT %s
        """
        
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (current_ts, previous_ts, limit))
                return [dict(row) for row in cur.fetchall()]
    
    def get_category_breakdown(self) -> List[Dict]:
        """Get change summary per category between the two update sessions."""
        timestamps = self._get_cached_timestamps()
        current_ts = timestamps.get('current_update')
        previous_ts = timestamps.get('previous_update')
        
        if not current_ts or not previous_ts:
            return []
        
        query = """
        WITH current_state AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.price,
                COALESCE(pph.discount_price, pph.price) as effective_price,
                pph.is_available
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
            ORDER BY pph.product_id, pph.recorded_at DESC
        ),
        previous_available_state AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.price,
                COALESCE(pph.discount_price, pph.price) as effective_price
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
              AND pph.is_available = true
            ORDER BY pph.product_id, pph.recorded_at DESC
        ),
        previous_any_state AS (
            SELECT DISTINCT ON (pph.product_id)
                pph.product_id,
                pph.is_available
            FROM product_price_history pph
            WHERE pph.recorded_at <= %s
            ORDER BY pph.product_id, pph.recorded_at DESC
        ),
        product_changes AS (
            SELECT 
                p.category_id,
                CASE WHEN prev_any.product_id IS NULL THEN 1 ELSE 0 END as is_new,
                CASE WHEN c.effective_price != prev_avail.effective_price AND c.is_available = true AND c.effective_price > 0 AND prev_avail.effective_price > 0 THEN 1 ELSE 0 END as price_changed,
                CASE WHEN c.is_available != prev_any.is_available THEN 1 ELSE 0 END as availability_changed
            FROM current_state c
            JOIN products p ON c.product_id = p.product_id
            LEFT JOIN previous_available_state prev_avail ON c.product_id = prev_avail.product_id
            LEFT JOIN previous_any_state prev_any ON c.product_id = prev_any.product_id
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
                cur.execute(query, (current_ts, previous_ts, previous_ts))
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
