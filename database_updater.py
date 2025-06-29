#!/usr/bin/env python3
"""
Database Updater - Core functionality for updating PRODUCTS_DB_URL database
Handles product CRUD operations, nutrition data, price history, and photos
"""
import os
import psycopg2
import psycopg2.extras
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone
import re
from decimal import Decimal
from nutriscore_calculator import NutriscoreCalculator

class DatabaseUpdater:
    """Core database updater for PRODUCTS_DB_URL database"""
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda x: None)
        self.db_url = os.getenv('PRODUCTS_DB_URL')
        if not self.db_url:
            raise ValueError("PRODUCTS_DB_URL environment variable not set")
        
        self.nutri_calculator = NutriscoreCalculator()
        self.conn = None
        self._connect()
    
    def _connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(self.db_url)
            self.conn.autocommit = False  # Use transactions
            self.status_callback("Database connection established")
        except Exception as e:
            raise Exception(f"Database connection failed: {str(e)}")
    
    def _execute_query(self, query: str, params: Tuple = None, fetch: bool = False) -> Optional[List]:
        """Execute query with error handling"""
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                if fetch:
                    return cursor.fetchall()
                return None
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Query execution failed: {str(e)}")
    
    def get_product_by_sku(self, sku: str) -> Optional[Dict]:
        """Get existing product by SKU"""
        query = "SELECT * FROM products WHERE sku = %s"
        result = self._execute_query(query, (sku,), fetch=True)
        return dict(result[0]) if result else None
    
    def add_new_product(self, product_data: Dict) -> int:
        """
        Add new product to database with all related data
        
        Args:
            product_data: Dictionary containing product information
            
        Returns:
            product_id of newly created product
        """
        try:
            # Extract basic product info
            sku = product_data['sku']
            name = product_data['name']
            rimi_url = product_data.get('url', '')
            category_id = product_data.get('category_id', 1)  # Default category
            price = product_data.get('price', '')
            
            # Parse quantity if available
            quantity_value, quantity_unit = self._parse_quantity(name)
            
            self.status_callback(f"Adding new product: {sku} - {name[:50]}")
            
            # Insert into products table
            product_query = """
                INSERT INTO products (sku, name, rimi_url, category_id, quantity_value, quantity_unit)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING product_id
            """
            
            result = self._execute_query(
                product_query,
                (sku, name, rimi_url, category_id, quantity_value, quantity_unit),
                fetch=True
            )
            
            product_id = result[0]['product_id']
            
            # Add initial price history record
            if price and price != 'N/A':
                price_decimal = self._parse_price(price)
                if price_decimal is not None:
                    self._add_price_history_record(product_id, price_decimal, True, 'rimi_scraper')
            
            self.conn.commit()
            self.status_callback(f"Successfully added product {sku} with ID {product_id}")
            return product_id
            
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to add product {sku}: {str(e)}")
    
    def add_nutrition_data(self, product_id: int, nutrition_data: Dict, category_code: str = None) -> bool:
        """
        Add nutrition data for a product with conditional nutri-score calculation
        
        Args:
            product_id: ID of the product
            nutrition_data: Dictionary with nutrition information
            category_code: Product category for nutri-score calculation
            
        Returns:
            True if successful
        """
        try:
            # Extract nutrition values with safe conversion - map from extracted data to schema fields
            ingredients_text = nutrition_data.get('ingredients', '')
            energy_kcal = float(nutrition_data.get('energy_kcal', 0)) if nutrition_data.get('energy_kcal') else None
            energy_kj = float(nutrition_data.get('energy_kj', 0)) if nutrition_data.get('energy_kj') else None
            
            # Map extracted field names to database field names
            fat_total = float(nutrition_data.get('fat', 0)) if nutrition_data.get('fat') else None
            fat_saturated = float(nutrition_data.get('saturated_fat', 0)) if nutrition_data.get('saturated_fat') else None
            carbs_total = float(nutrition_data.get('carbohydrates', 0)) if nutrition_data.get('carbohydrates') else None
            carbs_sugars = float(nutrition_data.get('sugar', 0)) if nutrition_data.get('sugar') else None
            protein = float(nutrition_data.get('protein', 0)) if nutrition_data.get('protein') else None
            salt = float(nutrition_data.get('salt', 0)) if nutrition_data.get('salt') else None
            fiber = float(nutrition_data.get('fiber', 0)) if nutrition_data.get('fiber') else None
            
            # Check if product already has nutri-score
            existing_nutri_query = """
                SELECT nutriscore_grade FROM product_nutrition WHERE sku = %s
            """
            # Get SKU from product_id
            sku_query = "SELECT sku FROM products WHERE product_id = %s"
            sku_result = self._execute_query(sku_query, (product_id,), fetch=True)
            if not sku_result:
                raise Exception(f"Product with ID {product_id} not found")
            sku = sku_result[0]['sku']
            
            existing_nutri = self._execute_query(existing_nutri_query, (sku,), fetch=True)
            
            # Calculate nutri-score only if product doesn't have one and we have sufficient data
            nutri_score_grade = None
            nutri_score_points = None
            
            if not existing_nutri and energy_kj and energy_kj > 0 and carbs_sugars is not None and fat_saturated is not None and salt is not None and protein is not None:
                nutri_result = self.nutri_calculator.calculate_single_product(
                    energy_kj=energy_kj,
                    sugars=carbs_sugars,
                    saturated_fat=fat_saturated,
                    salt=salt,
                    protein=protein,
                    fiber=int(fiber) if fiber else 0,
                    category_code=category_code
                )
                
                if nutri_result['success']:
                    nutri_score_grade = nutri_result['grade']
                    nutri_score_points = nutri_result['score']
                    self.status_callback(f"Calculated nutri-score: {nutri_score_grade} ({nutri_score_points} points)")
            elif existing_nutri:
                self.status_callback(f"Product {product_id} already has nutri-score, skipping calculation")
            
            # Insert nutrition data using correct table and field names
            nutrition_query = """
                INSERT INTO product_nutrition 
                (sku, ingredients, energy_kcal, energy_kj, fat, saturated_fat,
                 carbohydrates, sugars, protein, salt, nutriscore_grade, nutriscore_score,
                 created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sku) DO UPDATE SET
                    ingredients = EXCLUDED.ingredients,
                    energy_kcal = EXCLUDED.energy_kcal,
                    energy_kj = EXCLUDED.energy_kj,
                    fat = EXCLUDED.fat,
                    saturated_fat = EXCLUDED.saturated_fat,
                    carbohydrates = EXCLUDED.carbohydrates,
                    sugars = EXCLUDED.sugars,
                    protein = EXCLUDED.protein,
                    salt = EXCLUDED.salt,
                    nutriscore_grade = EXCLUDED.nutriscore_grade,
                    nutriscore_score = EXCLUDED.nutriscore_score,
                    updated_at = EXCLUDED.updated_at
            """
            
            self._execute_query(nutrition_query, (
                sku, ingredients_text, energy_kcal, energy_kj, fat_total, fat_saturated,
                carbs_total, carbs_sugars, protein, salt, nutri_score_grade, nutri_score_points,
                datetime.now(timezone.utc), datetime.now(timezone.utc)
            ))
            
            # Commit the transaction
            self.conn.commit()
            self.status_callback(f"Added nutrition data for product ID {product_id}")
            return True
            
        except Exception as e:
            raise Exception(f"Failed to add nutrition data: {str(e)}")
    
    def add_product_photos(self, product_id: int, photo_urls: List[str]) -> bool:
        """Add product photos"""
        try:
            if not photo_urls:
                return True
            
            # Clear existing photos
            self._execute_query("DELETE FROM productphotos WHERE product_id = %s", (product_id,))
            
            # Add new photos
            for i, url in enumerate(photo_urls):
                is_primary = (i == 0)  # First photo is primary
                photo_query = """
                    INSERT INTO productphotos (product_id, photo_url, is_primary)
                    VALUES (%s, %s, %s)
                """
                self._execute_query(photo_query, (product_id, url, is_primary))
            
            # Commit the transaction
            self.conn.commit()
            self.status_callback(f"Added {len(photo_urls)} photos for product ID {product_id}")
            return True
            
        except Exception as e:
            raise Exception(f"Failed to add photos: {str(e)}")
    
    def update_product_price(self, sku: str, price: str, is_available: bool = True) -> bool:
        """Update product price and availability"""
        try:
            # Get product ID
            product = self.get_product_by_sku(sku)
            if not product:
                self.status_callback(f"Product {sku} not found for price update")
                return False
            
            product_id = product['product_id']
            
            # Parse price
            price_decimal = self._parse_price(price)
            if price_decimal is None:
                self.status_callback(f"Invalid price format: {price}")
                return False
            
            # Add price history record
            self._add_price_history_record(product_id, price_decimal, is_available, 'rimi_scraper')
            
            self.conn.commit()
            self.status_callback(f"Updated price for {sku}: {price} (available: {is_available})")
            return True
            
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to update price for {sku}: {str(e)}")
    
    def mark_product_unavailable(self, sku: str) -> bool:
        """Mark product as unavailable"""
        try:
            product = self.get_product_by_sku(sku)
            if not product:
                return False
            
            product_id = product['product_id']
            
            # Get last known price
            last_price_query = """
                SELECT price FROM product_price_history 
                WHERE product_id = %s 
                ORDER BY recorded_at DESC 
                LIMIT 1
            """
            
            result = self._execute_query(last_price_query, (product_id,), fetch=True)
            last_price = result[0]['price'] if result else Decimal('0.00')
            
            # Add unavailable record
            self._add_price_history_record(product_id, last_price, False, 'rimi_scraper')
            
            self.conn.commit()
            self.status_callback(f"Marked product {sku} as unavailable")
            return True
            
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to mark {sku} unavailable: {str(e)}")
    
    def _add_price_history_record(self, product_id: int, price: Decimal, is_available: bool, data_source: str):
        """Add price history record"""
        # Use past timestamp to avoid constraint issues - subtract 1 minute to ensure it's in the past
        from datetime import timedelta
        current_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        
        price_query = """
            INSERT INTO product_price_history (product_id, price, currency, is_available, recorded_at, data_source)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        self._execute_query(price_query, (
            product_id,
            price,
            'EUR',
            is_available,
            current_time,
            data_source
        ))
    
    def _parse_price(self, price_str: str) -> Optional[Decimal]:
        """Parse price string to Decimal"""
        if not price_str or price_str == 'N/A':
            return None
        
        try:
            # Remove currency symbols and whitespace
            clean_price = re.sub(r'[€$£]', '', price_str).strip()
            # Replace comma with dot for decimal
            clean_price = clean_price.replace(',', '.')
            # Remove any remaining non-numeric characters except dots
            clean_price = re.sub(r'[^\d.]', '', clean_price)
            return Decimal(clean_price)
        except Exception as e:
            self.status_callback(f"Failed to parse price '{price_str}': {str(e)}")
            return None
    
    def _parse_quantity(self, product_name: str) -> Tuple[Optional[Decimal], Optional[str]]:
        """Extract quantity from product name"""
        try:
            # Look for patterns like "500g", "1.5L", "250ml", etc.
            quantity_pattern = r'(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|pcs|pc|gab)\b'
            match = re.search(quantity_pattern, product_name.lower())
            
            if match:
                value = Decimal(match.group(1).replace(',', '.'))
                unit = match.group(2)
                return value, unit
            
            return None, None
        except:
            return None, None
    
    def get_update_statistics(self) -> Dict:
        """Get statistics about recent updates"""
        try:
            stats = {}
            
            # Total products
            total_query = "SELECT COUNT(*) as count FROM products"
            result = self._execute_query(total_query, fetch=True)
            stats['total_products'] = result[0]['count']
            
            # Products with nutrition data
            nutrition_query = "SELECT COUNT(*) as count FROM nutritionfacts"
            result = self._execute_query(nutrition_query, fetch=True)
            stats['products_with_nutrition'] = result[0]['count']
            
            # Recent price updates (last 24 hours)
            recent_price_query = """
                SELECT COUNT(*) as count FROM product_price_history 
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """
            result = self._execute_query(recent_price_query, fetch=True)
            stats['recent_price_updates'] = result[0]['count']
            
            # Available vs unavailable products
            availability_query = """
                SELECT 
                    SUM(CASE WHEN is_available THEN 1 ELSE 0 END) as available,
                    SUM(CASE WHEN NOT is_available THEN 1 ELSE 0 END) as unavailable
                FROM (
                    SELECT DISTINCT ON (product_id) product_id, is_available
                    FROM product_price_history
                    ORDER BY product_id, recorded_at DESC
                ) latest
            """
            result = self._execute_query(availability_query, fetch=True)
            if result and result[0]:
                stats['available_products'] = result[0]['available'] or 0
                stats['unavailable_products'] = result[0]['unavailable'] or 0
            
            return stats
            
        except Exception as e:
            self.status_callback(f"Error getting statistics: {str(e)}")
            return {}
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.status_callback("Database connection closed")