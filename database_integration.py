#!/usr/bin/env python3
"""
Integration layer for external databases
- CATEGORIES_DB_URL: Contains 396 normalized categories with hierarchical structure
- PRODUCTS_DB_URL: Contains 8,447 products with nutrition data
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class CategoryInfo:
    category_id: int
    rimi_category_code: str
    name_lv: str
    name_en: Optional[str]
    parent_category_id: Optional[int]
    level: int

@dataclass
class ExternalProduct:
    product_id: int
    sku: str
    name: str
    rimi_url: str
    category_id: int
    quantity_value: Optional[Decimal]
    quantity_unit: Optional[str]
    name_norm: str

class ExternalDatabaseManager:
    """Manager for accessing external categories and products databases"""
    
    def __init__(self):
        from database_config import db_config
        self.categories_db_url = db_config.categories_db_url
        self.products_db_url = db_config.products_db_url
    
    def get_all_categories(self) -> List[CategoryInfo]:
        """Get all categories from the external database"""
        try:
            conn = psycopg2.connect(self.categories_db_url)
            conn.autocommit = True
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT category_id, rimi_category_code, name_lv, name_en, 
                           parent_category_id, level
                    FROM normalized_categories 
                    ORDER BY level, category_id;
                """)
                
                categories = []
                for row in cur.fetchall():
                    categories.append(CategoryInfo(
                        category_id=row['category_id'],
                        rimi_category_code=row['rimi_category_code'],
                        name_lv=row['name_lv'],
                        name_en=row['name_en'],
                        parent_category_id=row['parent_category_id'],
                        level=row['level']
                    ))
                
            conn.close()
            return categories
            
        except Exception as e:
            logging.error(f"Error fetching categories: {str(e)}")
            return []
    
    def get_category_urls(self) -> List[str]:
        """Generate Rimi category URLs for scraping"""
        categories = self.get_all_categories()
        urls = []
        
        for category in categories:
            if category.rimi_category_code and category.level <= 2:  # Focus on main categories
                # Build URL from category code
                url = f"https://www.rimi.lv/e-veikals/lv/produkti/c/{category.rimi_category_code}"
                urls.append(url)
        
        return urls
    
    def get_existing_products(self) -> Dict[str, ExternalProduct]:
        """Get all existing products indexed by SKU"""
        try:
            conn = psycopg2.connect(self.products_db_url)
            conn.autocommit = True
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT product_id, sku, name, rimi_url, category_id,
                           quantity_value, quantity_unit, name_norm
                    FROM products;
                """)
                
                products = {}
                for row in cur.fetchall():
                    product = ExternalProduct(
                        product_id=row['product_id'],
                        sku=row['sku'],
                        name=row['name'],
                        rimi_url=row['rimi_url'],
                        category_id=row['category_id'],
                        quantity_value=row['quantity_value'],
                        quantity_unit=row['quantity_unit'],
                        name_norm=row['name_norm']
                    )
                    products[product.sku] = product
                
            conn.close()
            return products
            
        except Exception as e:
            logging.error(f"Error fetching existing products: {str(e)}")
            return {}
    
    def get_products_needing_update(self, days: int = 7) -> List[str]:
        """Get product SKUs that haven't been updated recently"""
        try:
            conn = psycopg2.connect(self.products_db_url)
            conn.autocommit = True
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT sku FROM products 
                    WHERE updated_at < NOW() - INTERVAL '%s days'
                    ORDER BY updated_at ASC;
                """, (days,))
                
                return [row['sku'] for row in cur.fetchall()]
                
            conn.close()
            
        except Exception as e:
            logging.error(f"Error finding products needing update: {str(e)}")
            return []
    
    def get_nutrition_coverage(self) -> Dict[str, int]:
        """Get statistics on nutrition data coverage"""
        try:
            conn = psycopg2.connect(self.products_db_url)
            conn.autocommit = True
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if nutrition_facts table exists, if not fall back to basic product count
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'nutrition_facts'
                    );
                """)
                
                nutrition_table_exists = cur.fetchone()['exists']
                
                if nutrition_table_exists:
                    cur.execute("""
                        SELECT 
                            COUNT(*) as total_products,
                            COUNT(nf.product_id) as with_nutrition,
                            COUNT(CASE WHEN nf.ingredients IS NOT NULL THEN 1 END) as with_ingredients
                        FROM products p
                        LEFT JOIN nutrition_facts nf ON p.product_id = nf.product_id;
                    """)
                else:
                    cur.execute("""
                        SELECT 
                            COUNT(*) as total_products,
                            0 as with_nutrition,
                            0 as with_ingredients
                        FROM products;
                    """)
                
                result = cur.fetchone()
                return {
                    'total_products': result['total_products'],
                    'with_nutrition': result['with_nutrition'],
                    'with_ingredients': result['with_ingredients'],
                    'nutrition_coverage': round(result['with_nutrition'] / result['total_products'] * 100, 2) if result['total_products'] > 0 else 0,
                    'ingredients_coverage': round(result['with_ingredients'] / result['total_products'] * 100, 2) if result['total_products'] > 0 else 0
                }
                
            conn.close()
            
        except Exception as e:
            logging.error(f"Error getting nutrition coverage: {str(e)}")
            return {}

def create_scraping_strategy() -> Dict:
    """Create a comprehensive scraping strategy based on external database analysis"""
    
    ext_db = ExternalDatabaseManager()
    
    # Get current state
    categories = ext_db.get_all_categories()
    category_urls = ext_db.get_category_urls()
    existing_products = ext_db.get_existing_products()
    stale_products = ext_db.get_products_needing_update(7)
    nutrition_stats = ext_db.get_nutrition_coverage()
    
    strategy = {
        'total_categories': len(categories),
        'scraping_urls': category_urls[:10],  # Start with first 10 categories
        'existing_products_count': len(existing_products),
        'stale_products_count': len(stale_products),
        'nutrition_coverage': nutrition_stats,
        'priority_actions': []
    }
    
    # Determine priorities
    if nutrition_stats.get('ingredients_coverage', 0) < 50:
        strategy['priority_actions'].append('IMPROVE_NUTRITION_DATA')
    
    if len(stale_products) > 1000:
        strategy['priority_actions'].append('UPDATE_STALE_PRODUCTS')
    
    if len(existing_products) < 10000:
        strategy['priority_actions'].append('EXPAND_PRODUCT_COVERAGE')
    
    return strategy

if __name__ == "__main__":
    strategy = create_scraping_strategy()
    print("Scraping Strategy Analysis:")
    print(f"Categories available: {strategy['total_categories']}")
    print(f"Existing products: {strategy['existing_products_count']:,}")
    print(f"Stale products: {strategy['stale_products_count']:,}")
    print(f"Nutrition coverage: {strategy['nutrition_coverage']}")
    print(f"Priority actions: {', '.join(strategy['priority_actions'])}")