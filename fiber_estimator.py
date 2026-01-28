"""
Fiber Estimation Module for Barbora Project

Uses rimi_category_code from products table to look up fiber defaults.
Exception rules are checked first (keyword match), then falls back to category defaults.
Products without rimi_category_code are skipped.
"""

import json
import os
from typing import Optional, Tuple, List, Dict
import psycopg2
from psycopg2.extras import RealDictCursor


class FiberEstimator:
    def __init__(self, config_path: str = "fiber_estimation_config.json"):
        """Load fiber estimation config from JSON file."""
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        self.category_defaults = {
            int(k): v for k, v in config['category_fiber_defaults'].items()
        }
        self.exception_rules = config['exception_rules']
        self.code_to_id_mapping = config.get('category_code_to_id_mapping', {})
    
    def rimi_code_to_category_id(self, rimi_code: str) -> Optional[int]:
        """Convert rimi_category_code (e.g. 'SH-4-16') to category_id (e.g. 47)."""
        if not rimi_code:
            return None
        return self.code_to_id_mapping.get(rimi_code)
    
    def check_exception_rules(self, product_name: str, category_id: int) -> Tuple[Optional[float], Optional[str]]:
        """
        Check if product matches any exception rules.
        Exception rules override category defaults for specific products.
        
        Returns:
            (fiber_value, reason) if matched, else (None, None)
        """
        if not product_name or category_id is None:
            return None, None
            
        product_name_lower = product_name.lower()
        category_id_str = str(category_id)
        
        for rule in self.exception_rules:
            if not category_id_str.startswith(rule["category_id_prefix"]):
                continue
            
            for keyword in rule["keywords"]:
                if keyword.lower() in product_name_lower:
                    return rule["fiber"], rule["reason"]
        
        return None, None
    
    def estimate_fiber(
        self, 
        product_name: str, 
        rimi_category_code: Optional[int],
        current_fiber: Optional[float]
    ) -> Tuple[float, str, bool, str]:
        """
        Estimate fiber content for a product using rimi_category_code.
        
        Args:
            product_name: Product name for exception matching
            rimi_category_code: Rimi category ID (integer from products table)
            current_fiber: Current fiber value from database
            
        Returns:
            tuple of (fiber_value, source_description, should_update, match_type)
            - fiber_value: The fiber amount to use
            - source_description: Explanation of where value came from
            - should_update: Whether database should be updated
            - match_type: 'existing', 'exception', 'category', or 'none'
        """
        if current_fiber is not None and current_fiber > 0:
            return current_fiber, "Existing scraped/USDA value", False, "existing"
        
        if rimi_category_code is None:
            return 0.0, "No rimi_category_code", False, "none"
        
        category_id = int(rimi_category_code)
        
        exception_fiber, exception_reason = self.check_exception_rules(product_name, category_id)
        if exception_fiber is not None:
            return exception_fiber, f"Exception: {exception_reason}", True, "exception"
        
        category_fiber = self.category_defaults.get(category_id)
        if category_fiber is not None:
            return category_fiber, f"Category default (ID {category_id})", True, "category"
        
        return 0.0, f"No fiber default for category ID {category_id}", False, "none"
    
    def batch_estimate(self, products: List[Dict]) -> List[Dict]:
        """
        Estimate fiber for multiple products.
        
        Args:
            products: List of dicts with keys: product_id, name, rimi_category_code, fiber
            
        Returns:
            List of dicts with estimation results (only products that need updates)
        """
        results = []
        for product in products:
            fiber, source, should_update, match_type = self.estimate_fiber(
                product_name=product.get('name', ''),
                rimi_category_code=product.get('rimi_category_code'),
                current_fiber=product.get('fiber')
            )
            
            if should_update:
                results.append({
                    'product_id': product['product_id'],
                    'sku': product.get('sku', ''),
                    'name': product['name'],
                    'rimi_category_code': product.get('rimi_category_code'),
                    'old_fiber': product.get('fiber'),
                    'new_fiber': fiber,
                    'source': source,
                    'match_type': match_type
                })
        
        return results


def get_fiber_stats(conn) -> Dict:
    """Get fiber estimation statistics."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                COUNT(*) as total_products,
                COUNT(*) FILTER (WHERE nf.fiber IS NULL OR nf.fiber = 0) as missing_fiber,
                COUNT(*) FILTER (WHERE nf.fiber IS NOT NULL AND nf.fiber > 0) as has_fiber,
                COUNT(*) FILTER (WHERE nf.is_fiber_correct = TRUE) as marked_correct,
                COUNT(*) FILTER (WHERE p.rimi_category_code IS NOT NULL) as has_rimi_code
            FROM products p
            JOIN nutritionfacts nf ON p.product_id = nf.product_id
            WHERE nf.energy_kj IS NOT NULL
        """)
        return dict(cur.fetchone())


def get_products_for_estimation(conn, limit: int = 50) -> List[Dict]:
    """
    Get products that need fiber estimation.
    Only includes products with rimi_category_code and missing/zero fiber.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                p.product_id,
                p.sku,
                p.name,
                p.rimi_category_code,
                nf.fiber,
                nf.nutri_score_grade
            FROM products p
            JOIN nutritionfacts nf ON p.product_id = nf.product_id
            WHERE (nf.fiber IS NULL OR nf.fiber = 0)
              AND p.rimi_category_code IS NOT NULL
              AND nf.energy_kj IS NOT NULL
            ORDER BY p.name
            LIMIT %s
        """, (limit,))
        return [dict(row) for row in cur.fetchall()]


def get_products_for_estimation_by_categories(conn, category_ids: List[int], limit: int = 50) -> List[Dict]:
    """
    Get products that need fiber estimation, filtered by specific categories.
    """
    if not category_ids:
        return []
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                p.product_id,
                p.sku,
                p.name,
                p.rimi_category_code,
                nf.fiber,
                nf.nutri_score_grade
            FROM products p
            JOIN nutritionfacts nf ON p.product_id = nf.product_id
            WHERE (nf.fiber IS NULL OR nf.fiber = 0)
              AND p.rimi_category_code = ANY(%s)
              AND nf.energy_kj IS NOT NULL
            ORDER BY p.name
            LIMIT %s
        """, (category_ids, limit))
        return [dict(row) for row in cur.fetchall()]


def get_products_for_estimation_count_by_categories(conn, category_ids: List[int]) -> int:
    """Get count of products ready for fiber estimation in specific categories."""
    if not category_ids:
        return 0
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*)
            FROM products p
            JOIN nutritionfacts nf ON p.product_id = nf.product_id
            WHERE (nf.fiber IS NULL OR nf.fiber = 0)
              AND p.rimi_category_code = ANY(%s)
              AND nf.energy_kj IS NOT NULL
        """, (category_ids,))
        return cur.fetchone()[0]


def get_products_for_estimation_count(conn) -> int:
    """Get count of products ready for fiber estimation."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*)
            FROM products p
            JOIN nutritionfacts nf ON p.product_id = nf.product_id
            WHERE (nf.fiber IS NULL OR nf.fiber = 0)
              AND p.rimi_category_code IS NOT NULL
              AND nf.energy_kj IS NOT NULL
        """)
        return cur.fetchone()[0]


def apply_fiber_estimates(conn, estimates: List[Dict]) -> int:
    """
    Apply fiber estimates to database.
    Sets fiber value and is_fiber_correct=FALSE for estimated values.
    
    Returns:
        Number of products updated
    """
    if not estimates:
        return 0
    
    updated = 0
    with conn.cursor() as cur:
        for est in estimates:
            cur.execute("""
                UPDATE nutritionfacts 
                SET fiber = %s, is_fiber_correct = FALSE
                WHERE product_id = %s
            """, (est['new_fiber'], est['product_id']))
            updated += cur.rowcount
    
    conn.commit()
    return updated


def recalculate_nutriscore_for_products(conn, product_ids: List[int]) -> int:
    """
    Recalculate Nutri-Score for specific products after fiber update.
    Uses NutriscoreCalculator with full category and ingredient detection.
    
    Returns:
        Number of products with changed grades
    """
    from nutriscore_calculator import NutriscoreCalculator
    
    calculator = NutriscoreCalculator(conn)
    
    changed = 0
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        for product_id in product_ids:
            cur.execute("""
                SELECT 
                    p.name, p.category_id,
                    nf.energy_kj, nf.fat_saturated, nf.fat_total, nf.carbs_sugars, 
                    nf.salt, nf.fiber, nf.protein, nf.ingredients_text,
                    nf.nutri_score_grade as old_grade
                FROM nutritionfacts nf
                JOIN products p ON p.product_id = nf.product_id
                WHERE nf.product_id = %s
            """, (product_id,))
            
            row = cur.fetchone()
            if not row or row['energy_kj'] is None:
                continue
            
            result = calculator.calculate_single_product(
                energy_kj=float(row['energy_kj']) if row['energy_kj'] else 0,
                sugars=float(row['carbs_sugars']) if row['carbs_sugars'] else 0,
                saturated_fat=float(row['fat_saturated']) if row['fat_saturated'] else 0,
                salt=float(row['salt']) if row['salt'] else 0,
                protein=float(row['protein']) if row['protein'] else 0,
                fiber=float(row['fiber']) if row['fiber'] else 0,
                total_fat=float(row['fat_total']) if row['fat_total'] else None,
                category_id=row['category_id'],
                product_name=row['name'],
                ingredients_text=row['ingredients_text']
            )
            
            if result['success']:
                new_grade = result['grade']
                new_points = result['score']
                
                cur.execute("""
                    UPDATE nutritionfacts 
                    SET nutri_score_grade = %s, nutri_score_points = %s
                    WHERE product_id = %s
                """, (new_grade, new_points, product_id))
                
                if row['old_grade'] != new_grade:
                    changed += 1
    
    conn.commit()
    return changed


def preview_fiber_estimates(limit: int = 50, only_nonzero_fiber: bool = True) -> Tuple[List[Dict], int]:
    """
    Preview fiber estimates without applying them.
    
    Args:
        limit: Max number of products to preview
        only_nonzero_fiber: If True, only show products from categories with fiber > 0
    
    Returns:
        Tuple of (preview_results, total_count_ready)
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return [], 0
    
    conn = psycopg2.connect(database_url)
    try:
        estimator = FiberEstimator()
        
        if only_nonzero_fiber:
            nonzero_categories = [cat_id for cat_id, fiber in estimator.category_defaults.items() if fiber > 0]
            products = get_products_for_estimation_by_categories(conn, nonzero_categories, limit=limit)
            total_count = get_products_for_estimation_count_by_categories(conn, nonzero_categories)
        else:
            products = get_products_for_estimation(conn, limit=limit)
            total_count = get_products_for_estimation_count(conn)
        
        estimates = estimator.batch_estimate(products)
        
        from nutriscore_calculator import calculate_nutriscore
        
        for est in estimates:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT energy_kj, fat_saturated, carbs_sugars, 
                           salt, protein, nutri_score_grade
                    FROM nutritionfacts 
                    WHERE product_id = %s
                """, (est['product_id'],))
                nf = cur.fetchone()
            
            if nf and nf['energy_kj']:
                sodium = float(nf['salt']) * 400 if nf['salt'] else 0
                
                before_score, before_grade, _ = calculate_nutriscore(
                    energy_kj=float(nf['energy_kj']) if nf['energy_kj'] else 0,
                    saturated_fat=float(nf['fat_saturated']) if nf['fat_saturated'] else 0,
                    sugars=float(nf['carbs_sugars']) if nf['carbs_sugars'] else 0,
                    sodium=sodium,
                    fiber=float(est['old_fiber']) if est['old_fiber'] else 0,
                    protein=float(nf['protein']) if nf['protein'] else 0
                )
                
                after_score, after_grade, _ = calculate_nutriscore(
                    energy_kj=float(nf['energy_kj']) if nf['energy_kj'] else 0,
                    saturated_fat=float(nf['fat_saturated']) if nf['fat_saturated'] else 0,
                    sugars=float(nf['carbs_sugars']) if nf['carbs_sugars'] else 0,
                    sodium=sodium,
                    fiber=float(est['new_fiber']) if est['new_fiber'] else 0,
                    protein=float(nf['protein']) if nf['protein'] else 0
                )
                
                est['before_grade'] = before_grade
                est['new_grade'] = after_grade
            else:
                est['before_grade'] = None
                est['new_grade'] = None
        
        return estimates, total_count
    finally:
        conn.close()


def apply_all_fiber_estimates(progress_callback=None, only_nonzero_fiber: bool = True) -> Dict:
    """
    Apply fiber estimates to all eligible products and recalculate Nutri-Scores.
    
    Args:
        progress_callback: Optional callback(processed, total) for progress updates
        only_nonzero_fiber: If True, only process products from categories with fiber > 0
    
    Returns:
        Dict with statistics
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return {"error": "DATABASE_URL not set"}
    
    conn = psycopg2.connect(database_url)
    try:
        estimator = FiberEstimator()
        
        if only_nonzero_fiber:
            nonzero_categories = [cat_id for cat_id, fiber in estimator.category_defaults.items() if fiber > 0]
            total_count = get_products_for_estimation_count_by_categories(conn, nonzero_categories)
        else:
            nonzero_categories = None
            total_count = get_products_for_estimation_count(conn)
            
        if total_count == 0:
            return {"message": "No products need fiber estimation", "updated": 0, "grades_changed": 0}
        
        batch_size = 500
        total_updated = 0
        total_grades_changed = 0
        processed = 0
        
        while True:
            if only_nonzero_fiber:
                products = get_products_for_estimation_by_categories(conn, nonzero_categories, limit=batch_size)
            else:
                products = get_products_for_estimation(conn, limit=batch_size)
            if not products:
                break
            
            estimates = estimator.batch_estimate(products)
            if not estimates:
                break
            
            updated = apply_fiber_estimates(conn, estimates)
            total_updated += updated
            
            product_ids = [e['product_id'] for e in estimates]
            grades_changed = recalculate_nutriscore_for_products(conn, product_ids)
            total_grades_changed += grades_changed
            
            processed += len(products)
            if progress_callback:
                progress_callback(processed, total_count)
        
        return {
            "updated": total_updated,
            "grades_changed": total_grades_changed,
            "total_processed": processed
        }
    finally:
        conn.close()


if __name__ == "__main__":
    estimator = FiberEstimator()
    
    test_products = [
        {"product_id": 1, "name": "Pilngraudu makaroni 500g", "rimi_category_code": "SH-4-16", "fiber": None},
        {"product_id": 2, "name": "Baltie rīsi 1kg", "rimi_category_code": "SH-4-16", "fiber": None},
        {"product_id": 3, "name": "Tumšā šokolāde 85% 100g", "rimi_category_code": "SH-13-14-51", "fiber": None},
        {"product_id": 4, "name": "Piens 2.5% 1L", "rimi_category_code": "SH-11-1-1", "fiber": None},
        {"product_id": 5, "name": "Pilngraudu cepumi 200g", "rimi_category_code": "SH-13-3-7", "fiber": None},
    ]
    
    print("Testing fiber estimation:")
    print("-" * 80)
    
    for product in test_products:
        fiber, source, should_update, match_type = estimator.estimate_fiber(
            product['name'], product['rimi_category_code'], product['fiber']
        )
        print(f"{product['name'][:40]:40} | {product['rimi_category_code']:15} | "
              f"fiber:{fiber:4.1f}g | {match_type:10} | {source[:30]}")
    
    print("-" * 80)
    print("\nBatch estimate results:")
    results = estimator.batch_estimate(test_products)
    for r in results:
        print(f"  {r['name'][:40]} -> {r['new_fiber']}g ({r['match_type']})")
