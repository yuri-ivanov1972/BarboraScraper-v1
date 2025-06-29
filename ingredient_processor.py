#!/usr/bin/env python3
"""
Ingredient Processor - Handles ingredient analysis for new products only
Maintains ingredient frequency tracking and product-ingredient mapping
"""
import os
import psycopg2
import psycopg2.extras
import re
from typing import Dict, List, Set, Tuple
from datetime import datetime, timezone

class IngredientProcessor:
    """Processes ingredients for new products and maintains frequency tracking"""
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda x: None)
        self.db_url = os.getenv('PRODUCTS_DB_URL')
        if not self.db_url:
            raise ValueError("PRODUCTS_DB_URL environment variable not set")
        
        self.conn = None
        self._connect()
    
    def _connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(self.db_url)
            self.conn.autocommit = False
            self.status_callback("Ingredient processor connected to database")
        except Exception as e:
            raise Exception(f"Database connection failed: {str(e)}")
    
    def _execute_query(self, query: str, params: Tuple = None, fetch: bool = False):
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
    
    def process_product_ingredients(self, sku: str, ingredients_text: str) -> Dict:
        """
        Process ingredients for a new product
        
        Args:
            sku: Product SKU
            ingredients_text: Raw ingredients text
            
        Returns:
            Dictionary with processing results
        """
        try:
            if not ingredients_text or ingredients_text.strip() == '':
                self.status_callback(f"No ingredients text for product {sku}")
                return {'processed': 0, 'new_ingredients': 0}
            
            # Extract and normalize ingredients
            ingredients = self._extract_ingredients(ingredients_text)
            
            if not ingredients:
                self.status_callback(f"No ingredients extracted from text for product {sku}")
                return {'processed': 0, 'new_ingredients': 0}
            
            # Process each ingredient
            processed_count = 0
            new_ingredients_count = 0
            
            for ingredient in ingredients:
                # Get or create ingredient
                ingredient_id = self._get_or_create_ingredient(ingredient)
                
                if ingredient_id:
                    # Create product-ingredient mapping
                    self._create_ingredient_mapping(ingredient_id, sku)
                    processed_count += 1
                    
                    # Check if this was a new ingredient
                    if self._is_new_ingredient(ingredient_id):
                        new_ingredients_count += 1
            
            self.conn.commit()
            
            self.status_callback(f"Processed {processed_count} ingredients for product {sku} ({new_ingredients_count} new)")
            
            return {
                'processed': processed_count,
                'new_ingredients': new_ingredients_count,
                'ingredients_list': ingredients
            }
            
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to process ingredients for {sku}: {str(e)}")
    
    def _extract_ingredients(self, ingredients_text: str) -> List[str]:
        """Extract and normalize individual ingredients from text"""
        try:
            # Clean the text
            text = ingredients_text.strip()
            
            # Remove common prefixes (case insensitive)
            text = re.sub(r'^(ingredients?|sastāvs?|sastāvdaļas?)[:;]?\s*', '', text, flags=re.IGNORECASE)
            
            # For single ingredient products (like "olas"), don't split by commas
            if ',' not in text and ';' not in text and ' un ' not in text.lower() and ' and ' not in text.lower():
                # Single ingredient case - but may contain compound ingredients like "vistas OLAS"
                # Check if it contains adjective + noun pattern (common in Latvian)
                words = text.strip().split()
                if len(words) == 2:
                    # For compound ingredients like "vistas OLAS", try to find the main ingredient
                    main_ingredient = words[1].lower()  # "OLAS" -> "olas"
                    normalized_main = self._normalize_ingredient(main_ingredient)
                    if normalized_main and len(normalized_main) > 1:
                        return [normalized_main]
                
                # Fallback to treating as single ingredient
                normalized = self._normalize_ingredient(text.strip())
                if normalized and len(normalized) > 1:
                    return [normalized]
                return []
            
            # Split by common delimiters for multi-ingredient products
            ingredients = re.split(r'[,;]|\band\b|\bun\b', text, flags=re.IGNORECASE)
            
            # Clean and normalize each ingredient
            normalized_ingredients = []
            for ingredient in ingredients:
                normalized = self._normalize_ingredient(ingredient.strip())
                if normalized and len(normalized) > 1:  # Allow shorter ingredients
                    normalized_ingredients.append(normalized)
            
            return normalized_ingredients
            
        except Exception as e:
            self.status_callback(f"Error extracting ingredients: {str(e)}")
            return []
    
    def _normalize_ingredient(self, ingredient: str) -> str:
        """Normalize a single ingredient"""
        try:
            # Remove parenthetical information
            ingredient = re.sub(r'\([^)]*\)', '', ingredient)
            
            # Remove percentages
            ingredient = re.sub(r'\d+%', '', ingredient)
            
            # Remove extra whitespace
            ingredient = re.sub(r'\s+', ' ', ingredient).strip()
            
            # Remove leading/trailing punctuation
            ingredient = ingredient.strip('.,;:')
            
            # Keep original case for database matching (don't convert to title case)
            return ingredient
            
        except Exception as e:
            return ingredient
    
    def _get_or_create_ingredient(self, ingredient_name: str) -> int:
        """Get existing ingredient ID or create new one using simple UPSERT"""
        try:
            # Use a simple UPSERT that PostgreSQL handles atomically
            upsert_query = """
                WITH upsert AS (
                    UPDATE ingredient_analysis 
                    SET frequency = frequency + 1 
                    WHERE ingredient = %s 
                    RETURNING id
                )
                INSERT INTO ingredient_analysis (ingredient, frequency)
                SELECT %s, 1
                WHERE NOT EXISTS (SELECT 1 FROM upsert)
                RETURNING id;
            """
            
            # Try the upsert first
            result = self._execute_query(upsert_query, (ingredient_name, ingredient_name), fetch=True)
            if result and len(result) > 0:
                return result[0]['id']
            
            # If upsert didn't return anything, the UPDATE part worked, so get the ID
            select_query = "SELECT id FROM ingredient_analysis WHERE ingredient = %s"
            fallback_result = self._execute_query(select_query, (ingredient_name,), fetch=True)
            if fallback_result and len(fallback_result) > 0:
                return fallback_result[0]['id']
            
            # Final fallback for any edge cases
            self.status_callback(f"Warning: Could not process ingredient {ingredient_name}")
            return None
                
        except Exception as e:
            # If there's any error, try a simple select as final fallback
            try:
                select_query = "SELECT id FROM ingredient_analysis WHERE ingredient = %s"
                fallback_result = self._execute_query(select_query, (ingredient_name,), fetch=True)
                if fallback_result and len(fallback_result) > 0:
                    # Update frequency manually
                    update_query = "UPDATE ingredient_analysis SET frequency = frequency + 1 WHERE id = %s"
                    self._execute_query(update_query, (fallback_result[0]['id'],))
                    return fallback_result[0]['id']
            except:
                pass
            
            self.status_callback(f"Error processing ingredient {ingredient_name}: {str(e)}")
            return None
    
    def _create_ingredient_mapping(self, ingredient_id: int, sku: str):
        """Create product-ingredient mapping"""
        try:
            mapping_query = """
                INSERT INTO ingredient_product_mapping (ingredient_id, product_sku)
                VALUES (%s, %s)
                ON CONFLICT (ingredient_id, product_sku) DO NOTHING
            """
            self._execute_query(mapping_query, (ingredient_id, sku))
            
        except Exception as e:
            self.status_callback(f"Error creating ingredient mapping: {str(e)}")
    
    def _is_new_ingredient(self, ingredient_id: int) -> bool:
        """Check if ingredient was just created (frequency = 1)"""
        try:
            check_query = "SELECT frequency FROM ingredient_analysis WHERE id = %s"
            result = self._execute_query(check_query, (ingredient_id,), fetch=True)
            return result and result[0]['frequency'] == 1
        except:
            return False
    
    def get_ingredient_statistics(self) -> Dict:
        """Get ingredient processing statistics"""
        try:
            stats = {}
            
            # Total unique ingredients
            total_query = "SELECT COUNT(*) as count FROM ingredient_analysis"
            result = self._execute_query(total_query, fetch=True)
            stats['total_ingredients'] = result[0]['count']
            
            # Most common ingredients
            common_query = """
                SELECT ingredient, frequency 
                FROM ingredient_analysis 
                ORDER BY frequency DESC 
                LIMIT 10
            """
            result = self._execute_query(common_query, fetch=True)
            stats['most_common'] = [dict(row) for row in result] if result else []
            
            # Recent ingredient additions
            recent_query = """
                SELECT COUNT(*) as count 
                FROM ingredient_analysis 
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """
            result = self._execute_query(recent_query, fetch=True)
            stats['recent_additions'] = result[0]['count']
            
            return stats
            
        except Exception as e:
            self.status_callback(f"Error getting ingredient statistics: {str(e)}")
            return {}
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.status_callback("Ingredient processor connection closed")