"""
Debug script to analyze specific data extraction issues for SKU 147762
- Missing rimi_url
- Incorrect category_id (1 vs 298)
- Missing nutrition data (carbs_total, carbs_sugars, protein, salt)
"""

import requests
from bs4 import BeautifulSoup
import psycopg2
import os
from urllib.parse import urljoin
import re

def analyze_sku_147762():
    """Analyze the specific issues with SKU 147762"""
    
    print("=== ANALYZING SKU 147762 DATA EXTRACTION ISSUES ===")
    
    # 1. Check current database state
    print("\n1. CURRENT DATABASE STATE:")
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        cursor = conn.cursor()
        
        # Check products table
        cursor.execute("""
            SELECT product_id, sku, name, category_id, rimi_url, quantity_value, quantity_unit
            FROM products WHERE sku = %s
        """, ('147762',))
        product_data = cursor.fetchone()
        
        if product_data:
            print(f"Product ID: {product_data[0]}")
            print(f"SKU: {product_data[1]}")
            print(f"Name: {product_data[2]}")
            print(f"Category ID: {product_data[3]} (should be 298)")
            print(f"Rimi URL: {product_data[4]} (missing)")
            print(f"Quantity: {product_data[5]} {product_data[6] or ''}")
        else:
            print("Product not found in database")
            return
        
        # Check nutrition data
        cursor.execute("""
            SELECT carbs_total, carbs_sugars, protein, salt, nutri_score_points, nutri_score_grade
            FROM nutritionfacts WHERE product_id = %s
        """, (product_data[0],))
        nutrition_data = cursor.fetchone()
        
        if nutrition_data:
            print(f"\nNutrition Data:")
            print(f"Carbs Total: {nutrition_data[0]} (NULL)")
            print(f"Carbs Sugars: {nutrition_data[1]} (NULL)")
            print(f"Protein: {nutrition_data[2]} (NULL)")
            print(f"Salt: {nutrition_data[3]} (NULL)")
            print(f"Nutri-Score Points: {nutrition_data[4]} (NULL)")
            print(f"Nutri-Score Grade: {nutrition_data[5]} (NULL)")
        else:
            print("No nutrition data found")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Database error: {e}")
    
    # 2. Test direct URL access
    print("\n2. TESTING URL CONSTRUCTION:")
    base_url = "https://www.rimi.lv/e-veikals/lv/products/"
    product_url = f"{base_url}{147762}"
    print(f"Constructed URL: {product_url}")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'lv,en-US;q=0.7,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        response = requests.get(product_url, headers=headers, timeout=30)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Check if product exists
            title = soup.find('h1')
            if title:
                print(f"Product title found: {title.get_text().strip()}")
            else:
                print("No product title found - may be unavailable")
            
            # Check for nutrition data
            print("\n3. NUTRITION DATA EXTRACTION TEST:")
            nutrition_labels = soup.find_all(string=re.compile(r'Uzturvērtība|Sastāvdaļas', re.IGNORECASE))
            print(f"Found {len(nutrition_labels)} nutrition-related labels")
            
            # Look for specific nutrition values
            nutrition_patterns = {
                'carbs_total': r'Oglhidrāti[:\s]*(\d+(?:[.,]\d+)?)\s*g',
                'carbs_sugars': r'tostarp cukuri[:\s]*(\d+(?:[.,]\d+)?)\s*g',
                'protein': r'Olbaltumvielas[:\s]*(\d+(?:[.,]\d+)?)\s*g',
                'salt': r'Sāls[:\s]*(\d+(?:[.,]\d+)?)\s*g'
            }
            
            page_text = soup.get_text()
            found_nutrition = {}
            
            for nutrient, pattern in nutrition_patterns.items():
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    found_nutrition[nutrient] = match.group(1)
                    print(f"Found {nutrient}: {match.group(1)}g")
                else:
                    print(f"Missing {nutrient}")
            
            # Check category detection
            print("\n4. CATEGORY DETECTION TEST:")
            # Look for breadcrumbs or category info
            breadcrumbs = soup.find_all(['nav', 'ol', 'ul'], class_=re.compile(r'breadcrumb|navigation', re.IGNORECASE))
            for breadcrumb in breadcrumbs:
                print(f"Breadcrumb found: {breadcrumb.get_text().strip()}")
            
        else:
            print(f"Failed to access product page: {response.status_code}")
            
    except Exception as e:
        print(f"URL access error: {e}")
    
    # 3. Check category mapping
    print("\n5. CATEGORY MAPPING ANALYSIS:")
    try:
        conn = psycopg2.connect(os.environ.get('CATEGORIES_DB_URL'))
        cursor = conn.cursor()
        
        # Find category 298
        cursor.execute("""
            SELECT category_id, rimi_category_code, name_lv, name_en
            FROM normalized_categories WHERE category_id = %s
        """, (298,))
        correct_category = cursor.fetchone()
        
        if correct_category:
            print(f"Correct category (298): {correct_category[1]} - {correct_category[2]}")
        
        # Find category 1 (incorrect)
        cursor.execute("""
            SELECT category_id, rimi_category_code, name_lv, name_en
            FROM normalized_categories WHERE category_id = %s
        """, (1,))
        wrong_category = cursor.fetchone()
        
        if wrong_category:
            print(f"Wrong category (1): {wrong_category[1]} - {wrong_category[2]}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Category mapping error: {e}")

if __name__ == "__main__":
    analyze_sku_147762()