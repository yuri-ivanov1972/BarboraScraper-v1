"""
Nutrition Data Updater - Updates nutrition data for existing products without changing categories
Only fetches and updates nutrition information for products that lack it
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional
import requests
import json
import re
from bs4 import BeautifulSoup
from decimal import Decimal


class NutritionUpdater:
    """Updates nutrition data for existing products without modifying categories"""
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda msg: print(msg))
        self.conn = None
        self._connect()
    
    def _connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(
                os.environ['DATABASE_URL'],
                cursor_factory=RealDictCursor
            )
            self.status_callback("Database connection established")
        except Exception as e:
            self.status_callback(f"Database connection failed: {str(e)}")
            raise
    
    def _execute_query(self, query: str, params: tuple = None, fetch: bool = False):
        """Execute query with error handling"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(query, params)
                if fetch:
                    return cursor.fetchall()
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            self.status_callback(f"Query execution failed: {str(e)}")
            return None
    
    def get_products_without_nutrition(self, category_filter: str = None) -> List[Dict]:
        """Get products that lack nutrition data, optionally filtered by product name/category"""
        
        if category_filter:
            # Filter by product name or SKU containing the category term
            if category_filter.upper() == 'SH-11-6':  # Olas
                filter_terms = ['ola', 'egg']
            elif category_filter.upper() == 'SH-11-3':  # Kefirs
                filter_terms = ['kefir', 'kefīr']
            else:
                filter_terms = [category_filter.lower()]
            
            # Build dynamic WHERE clause for name filtering
            name_conditions = []
            params = []
            for term in filter_terms:
                name_conditions.append("LOWER(p.name) LIKE %s")
                params.append(f'%{term}%')
            
            query = f"""
                SELECT p.product_id, p.sku, p.name, p.rimi_url, p.category_id
                FROM products p
                LEFT JOIN product_nutrition n ON p.product_id = n.product_id
                WHERE n.product_id IS NULL AND ({' OR '.join(name_conditions)})
                ORDER BY p.sku
            """
        else:
            query = """
                SELECT p.product_id, p.sku, p.name, p.rimi_url, p.category_id
                FROM products p
                LEFT JOIN product_nutrition n ON p.product_id = n.product_id
                WHERE n.product_id IS NULL
                ORDER BY p.sku
            """
            params = []
        
        result = self._execute_query(query, tuple(params) if params else None, fetch=True)
        return list(result) if result else []
    
    def _get_nutrition_data(self, product_url: str) -> Dict:
        """Extract nutrition data from product page"""
        try:
            if not product_url:
                return {'has_nutrition': False, 'ingredients': '', 'energy_kcal': 0, 'energy_kj': 0, 
                       'fat_total': 0, 'fat_saturated': 0, 'carbs_total': 0, 'carbs_sugars': 0, 
                       'protein': 0, 'salt': 0, 'fiber': 0}
            
            self.status_callback(f"Fetching nutrition data from: {product_url}")
            
            # Create session with proper headers
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'lv,en-US;q=0.7,en;q=0.3',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })
            
            response = session.get(product_url)
            if response.status_code != 200:
                return {'has_nutrition': False, 'ingredients': '', 'energy_kcal': 0, 'energy_kj': 0, 
                       'fat_total': 0, 'fat_saturated': 0, 'carbs_total': 0, 'carbs_sugars': 0, 
                       'protein': 0, 'salt': 0, 'fiber': 0}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Initialize nutrition data
            nutrition_data = {
                'has_nutrition': False,
                'ingredients': '',
                'energy_kcal': 0,
                'energy_kj': 0,
                'fat_total': 0,
                'fat_saturated': 0,
                'carbs_total': 0,
                'carbs_sugars': 0,
                'protein': 0,
                'salt': 0,
                'fiber': 0
            }
            
            # Helper functions
            def extract_decimal(text: str) -> float:
                try:
                    cleaned = re.sub(r'[^0-9.-]', '', text.replace(',', '.'))
                    return float(cleaned) if cleaned else 0.0
                except (ValueError, TypeError):
                    return 0.0
            
            def extract_energy_values(text: str) -> tuple:
                try:
                    pattern = r'(\d+(?:[,.]\d+)?)\s*kJ\s*(?:/|\s)\s*(\d+(?:[,.]\d+)?)\s*kcal'
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        kj = extract_decimal(match.group(1))
                        kcal = extract_decimal(match.group(2))
                        return kj, kcal
                    return 0.0, 0.0
                except Exception:
                    return 0.0, 0.0
            
            # Find product details script
            script_tag = None
            for script in soup.find_all('script'):
                if script.string and 'Storefront.product_details_page' in script.string:
                    script_tag = script
                    break
            
            if script_tag:
                script_content = script_tag.string
                
                # Extract details tab HTML content
                try:
                    details_match = re.search(
                        r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']',
                        script_content, re.DOTALL)
                    
                    if not details_match:
                        details_match = re.search(
                            r'html:\s*["\']([^"\']+)["\'].*?identifier:\s*["\']details["\']',
                            script_content, re.DOTALL)
                    
                    if details_match:
                        html_content = details_match.group(1)
                        
                        # Handle escaped characters
                        html_content = html_content.encode().decode('unicode-escape')
                        html_content = html_content.replace('\\/', '/')
                        html_content = html_content.replace('\\"', '"')
                        
                        details_soup = BeautifulSoup(html_content, 'html.parser')
                        
                        # Find ingredients
                        for section in details_soup.find_all('div', class_='product__list-wrapper'):
                            heading = section.find('p', class_='heading')
                            if heading and 'Sastāvdaļas' in heading.get_text(strip=True):
                                text_div = section.find('div', class_='text')
                                if text_div and text_div.p:
                                    nutrition_data['ingredients'] = text_div.p.get_text(strip=True)
                                break
                        
                        # Find nutrition table
                        tables = details_soup.find_all('table')
                        nutrition_table = None
                        for table in tables:
                            headers = table.find_all('th')
                            if any('Uzturvērtība' in header.get_text(strip=True) for header in headers):
                                nutrition_table = table
                                break
                        
                        if nutrition_table:
                            nutrition_data['has_nutrition'] = True
                            for row in nutrition_table.find_all('tr'):
                                cells = row.find_all(['td'])
                                if len(cells) >= 2:
                                    label = cells[0].get_text(strip=True).lower()
                                    value = cells[1].get_text(strip=True)
                                    
                                    if 'enerģētiskā vērtība' in label:
                                        kj, kcal = extract_energy_values(value)
                                        nutrition_data['energy_kj'] = kj
                                        nutrition_data['energy_kcal'] = kcal
                                    elif 'tauki' == label:
                                        nutrition_data['fat_total'] = extract_decimal(value)
                                    elif 'piesātinātās taukskābes' in label:
                                        nutrition_data['fat_saturated'] = extract_decimal(value)
                                    elif 'ogļhidrāti' == label:
                                        nutrition_data['carbs_total'] = extract_decimal(value)
                                    elif 'cukuri' in label:
                                        nutrition_data['carbs_sugars'] = extract_decimal(value)
                                    elif 'olbaltumvielas' == label:
                                        nutrition_data['protein'] = extract_decimal(value)
                                    elif 'sāls' == label:
                                        nutrition_data['salt'] = extract_decimal(value)
                                    elif 'šķiedrvielas' in label or 'fiber' in label.lower():
                                        nutrition_data['fiber'] = extract_decimal(value)
                        
                        # If we found ingredients but no nutrition table, still mark as having nutrition data
                        if nutrition_data['ingredients'] and not nutrition_data['has_nutrition']:
                            nutrition_data['has_nutrition'] = True
                
                except Exception as e:
                    self.status_callback(f"Error processing product details: {str(e)}")
            
            return nutrition_data
            
        except Exception as e:
            self.status_callback(f"Error fetching nutrition data: {str(e)}")
            return {'has_nutrition': False, 'ingredients': '', 'energy_kcal': 0, 'energy_kj': 0, 
                   'fat_total': 0, 'fat_saturated': 0, 'carbs_total': 0, 'carbs_sugars': 0, 
                   'protein': 0, 'salt': 0, 'fiber': 0}
    
    def add_nutrition_data(self, product_id: int, nutrition_data: Dict) -> bool:
        """Add nutrition data for a product"""
        if not nutrition_data.get('has_nutrition'):
            return False
        
        query = """
            INSERT INTO product_nutrition (
                product_id, ingredients, energy_kj, energy_kcal, 
                fat_total, fat_saturated, carbs_total, carbs_sugars,
                protein, salt, fiber, data_source, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'rimi_scraper', NOW()
            )
            ON CONFLICT (product_id) DO UPDATE SET
                ingredients = EXCLUDED.ingredients,
                energy_kj = EXCLUDED.energy_kj,
                energy_kcal = EXCLUDED.energy_kcal,
                fat_total = EXCLUDED.fat_total,
                fat_saturated = EXCLUDED.fat_saturated,
                carbs_total = EXCLUDED.carbs_total,
                carbs_sugars = EXCLUDED.carbs_sugars,
                protein = EXCLUDED.protein,
                salt = EXCLUDED.salt,
                fiber = EXCLUDED.fiber,
                updated_at = NOW()
        """
        
        params = (
            product_id,
            nutrition_data.get('ingredients', ''),
            nutrition_data.get('energy_kj', 0),
            nutrition_data.get('energy_kcal', 0),
            nutrition_data.get('fat_total', 0),
            nutrition_data.get('fat_saturated', 0),
            nutrition_data.get('carbs_total', 0),
            nutrition_data.get('carbs_sugars', 0),
            nutrition_data.get('protein', 0),
            nutrition_data.get('salt', 0),
            nutrition_data.get('fiber', 0)
        )
        
        return self._execute_query(query, params)
    
    def calculate_and_add_nutriscore(self, product_id: int, nutrition_data: Dict, category_code: str = None) -> bool:
        """Calculate and add nutri-score for a product"""
        try:
            from nutriscore_calculator import NutriscoreCalculator
            
            # Check if nutriscore already exists
            check_query = "SELECT nutriscore_grade FROM product_nutrition WHERE product_id = %s AND nutriscore_grade IS NOT NULL"
            existing = self._execute_query(check_query, (product_id,), fetch=True)
            
            if existing:
                self.status_callback(f"Nutriscore already exists for product {product_id}")
                return False
            
            # Calculate nutriscore
            calculator = NutriscoreCalculator()
            result = calculator.calculate_single_product(
                energy_kj=nutrition_data.get('energy_kj', 0),
                sugars=nutrition_data.get('carbs_sugars', 0),
                saturated_fat=nutrition_data.get('fat_saturated', 0),
                salt=nutrition_data.get('salt', 0),
                protein=nutrition_data.get('protein', 0),
                fiber=int(nutrition_data.get('fiber', 0)),
                category_code=category_code
            )
            
            # Update product_nutrition with nutriscore
            update_query = """
                UPDATE product_nutrition 
                SET nutriscore_grade = %s, nutriscore_score = %s, updated_at = NOW()
                WHERE product_id = %s
            """
            
            success = self._execute_query(update_query, (result['grade'], result['score'], product_id))
            
            if success:
                self.status_callback(f"Added nutriscore {result['grade']} (score: {result['score']}) for product {product_id}")
            
            return success
            
        except Exception as e:
            self.status_callback(f"Error calculating nutriscore: {str(e)}")
            return False
    
    def update_category_nutrition(self, category_code: str) -> Dict:
        """Update nutrition data for all products in a category without nutrition"""
        
        self.status_callback(f"Starting nutrition update for category {category_code}")
        
        # Get products without nutrition
        products = self.get_products_without_nutrition(category_code)
        
        if not products:
            self.status_callback(f"No products without nutrition found in category {category_code}")
            return {
                'total_products': 0,
                'updated_products': 0,
                'failed_products': 0,
                'nutriscore_added': 0
            }
        
        self.status_callback(f"Found {len(products)} products without nutrition data")
        
        results = {
            'total_products': len(products),
            'updated_products': 0,
            'failed_products': 0,
            'nutriscore_added': 0
        }
        
        for product in products:
            try:
                self.status_callback(f"Processing {product['sku']}: {product['name']}")
                
                # Get nutrition data from product page
                nutrition_data = self._get_nutrition_data(product['rimi_url'])
                
                if nutrition_data['has_nutrition']:
                    # Add nutrition data
                    if self.add_nutrition_data(product['product_id'], nutrition_data):
                        results['updated_products'] += 1
                        self.status_callback(f"✓ Added nutrition data for {product['sku']}")
                        
                        # Calculate and add nutriscore
                        if self.calculate_and_add_nutriscore(product['product_id'], nutrition_data, category_code):
                            results['nutriscore_added'] += 1
                    else:
                        results['failed_products'] += 1
                        self.status_callback(f"✗ Failed to add nutrition data for {product['sku']}")
                else:
                    self.status_callback(f"○ No nutrition data found for {product['sku']}")
                    results['failed_products'] += 1
                    
            except Exception as e:
                self.status_callback(f"✗ Error processing {product['sku']}: {str(e)}")
                results['failed_products'] += 1
        
        return results
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.status_callback("Database connection closed")