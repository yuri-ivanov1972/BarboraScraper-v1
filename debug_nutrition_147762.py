"""
Debug Nutrition Data for SKU 147762 - Identify why nutrition extraction is failing
"""

import requests
from bs4 import BeautifulSoup
import re

def debug_nutrition_147762():
    """Debug nutrition data extraction for SKU 147762"""
    
    print("=== DEBUGGING NUTRITION DATA FOR SKU 147762 ===")
    
    # Fetch the product page
    url = "https://www.rimi.lv/e-veikals/lv/produkti/p/147762"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        print(f"✓ Successfully fetched page (Status: {response.status_code})")
        
        # Get all text content for analysis
        page_text = soup.get_text()
        
        # 1. Search for Latvian nutrition keywords
        print("\n1. SEARCHING FOR LATVIAN NUTRITION KEYWORDS")
        latvian_keywords = [
            'uzturvērtība', 'sastāvdaļas', 'enerģētiskā vērtība', 
            'tauki', 'oglhidrāti', 'olbaltumvielas', 'sāls',
            'tostarp piesātinātās', 'tostarp cukuri'
        ]
        
        for keyword in latvian_keywords:
            matches = re.findall(rf'.{{0,50}}{keyword}.{{0,50}}', page_text, re.IGNORECASE)
            if matches:
                print(f"  Found '{keyword}': {len(matches)} matches")
                for match in matches[:2]:  # Show first 2 matches
                    print(f"    → {match.strip()}")
            else:
                print(f"  NOT FOUND: '{keyword}'")
        
        # 2. Search for English nutrition keywords
        print("\n2. SEARCHING FOR ENGLISH NUTRITION KEYWORDS")
        english_keywords = [
            'nutrition', 'ingredients', 'energy', 'fat', 'carbohydrates', 
            'protein', 'salt', 'saturated', 'sugars'
        ]
        
        for keyword in english_keywords:
            matches = re.findall(rf'.{{0,50}}{keyword}.{{0,50}}', page_text, re.IGNORECASE)
            if matches:
                print(f"  Found '{keyword}': {len(matches)} matches")
                for match in matches[:2]:
                    print(f"    → {match.strip()}")
            else:
                print(f"  NOT FOUND: '{keyword}'")
        
        # 3. Look for structured data (JSON-LD, microdata)
        print("\n3. SEARCHING FOR STRUCTURED DATA")
        
        # Check for JSON-LD
        json_scripts = soup.find_all('script', type='application/ld+json')
        if json_scripts:
            print(f"  Found {len(json_scripts)} JSON-LD scripts")
            for i, script in enumerate(json_scripts):
                if 'nutrition' in script.get_text().lower():
                    print(f"    Script {i+1} contains nutrition data")
                    print(f"    Content preview: {script.get_text()[:200]}...")
        
        # Check for microdata
        nutrition_microdata = soup.find_all(attrs={'itemtype': re.compile(r'.*nutrition.*', re.I)})
        if nutrition_microdata:
            print(f"  Found {len(nutrition_microdata)} nutrition microdata elements")
        
        # 4. Look for specific HTML patterns
        print("\n4. SEARCHING FOR HTML PATTERNS")
        
        # Look for tables
        tables = soup.find_all('table')
        nutrition_tables = []
        for table in tables:
            table_text = table.get_text().lower()
            if any(word in table_text for word in ['uzturvērtība', 'nutrition', 'enerģētiskā', 'energy']):
                nutrition_tables.append(table)
        
        if nutrition_tables:
            print(f"  Found {len(nutrition_tables)} potential nutrition tables")
            for i, table in enumerate(nutrition_tables):
                print(f"    Table {i+1} preview: {table.get_text()[:150]}...")
        
        # Look for divs with nutrition-related classes or data
        nutrition_divs = soup.find_all('div', class_=re.compile(r'.*nutrition.*|.*uztur.*', re.I))
        if nutrition_divs:
            print(f"  Found {len(nutrition_divs)} nutrition-related divs")
        
        # 5. Check if this is an olive oil product (might not have nutrition labels)
        print("\n5. PRODUCT TYPE ANALYSIS")
        product_name = soup.find('h1')
        if product_name:
            name_text = product_name.get_text().lower()
            print(f"  Product name: {product_name.get_text()}")
            
            oil_keywords = ['olīveļļa', 'olive oil', 'eļļa', 'oil']
            is_oil = any(keyword in name_text for keyword in oil_keywords)
            
            if is_oil:
                print("  ⚠️  This is an olive oil product - may not have detailed nutrition labels by law")
                print("  ⚠️  Olive oil typically shows only energy values (3700kJ/900kcal) and fat content (100g)")
        
        # 6. Alternative data sources
        print("\n6. CHECKING ALTERNATIVE DATA LOCATIONS")
        
        # Check for accordion/collapsible content
        accordions = soup.find_all(['details', 'div'], class_=re.compile(r'.*accordion.*|.*collapse.*|.*expand.*', re.I))
        if accordions:
            print(f"  Found {len(accordions)} accordion/collapsible elements")
            for acc in accordions:
                if any(word in acc.get_text().lower() for word in ['uzturvērtība', 'nutrition', 'sastāv']):
                    print(f"    Nutrition content in accordion: {acc.get_text()[:100]}...")
        
        # Check for tabbed content
        tabs = soup.find_all(['div', 'section'], class_=re.compile(r'.*tab.*', re.I))
        nutrition_tabs = []
        for tab in tabs:
            if any(word in tab.get_text().lower() for word in ['uzturvērtība', 'nutrition', 'sastāv']):
                nutrition_tabs.append(tab)
        
        if nutrition_tabs:
            print(f"  Found {len(nutrition_tabs)} nutrition-related tabs")
        
        # 7. Raw nutrition value extraction attempt
        print("\n7. RAW NUTRITION VALUE EXTRACTION")
        
        # Look for specific nutrition patterns
        patterns = {
            'energy_kj': r'(\d+(?:[.,]\d+)?)\s*kJ',
            'energy_kcal': r'(\d+(?:[.,]\d+)?)\s*kcal',
            'fat': r'tauki[:\s]*(\d+(?:[.,]\d+)?)\s*g',
            'carbs': r'oglhidrāti[:\s]*(\d+(?:[.,]\d+)?)\s*g',
            'protein': r'olbaltumvielas[:\s]*(\d+(?:[.,]\d+)?)\s*g',
            'salt': r'sāls[:\s]*(\d+(?:[.,]\d+)?)\s*g'
        }
        
        for nutrient, pattern in patterns.items():
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            if matches:
                print(f"  {nutrient}: {matches}")
            else:
                print(f"  {nutrient}: Not found")
        
        return True
        
    except Exception as e:
        print(f"✗ Error fetching page: {str(e)}")
        return False

if __name__ == "__main__":
    debug_nutrition_147762()