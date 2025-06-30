"""
Debug Olive Oil Nutrition - Analyze the exact HTML structure and table detection for SKU 147762
"""
import requests
from bs4 import BeautifulSoup
import re

def debug_olive_oil_nutrition():
    """Debug the exact HTML structure for olive oil SKU 147762"""
    
    print("=== DEBUGGING OLIVE OIL NUTRITION EXTRACTION ===")
    
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
    
    url = "https://www.rimi.lv/e-veikals/lv/produkti/p/147762"
    print(f"Fetching: {url}")
    
    response = session.get(url)
    if response.status_code != 200:
        print(f"Failed to fetch: {response.status_code}")
        return
    
    soup = BeautifulSoup(response.text, 'html.parser')
    print("✓ Page fetched successfully")
    
    # Find product details script
    script_tag = None
    for script in soup.find_all('script'):
        if script.string and 'Storefront.product_details_page' in script.string:
            script_tag = script
            break
    
    if not script_tag:
        print("✗ No product details script found")
        return
    
    print("✓ Product details script found")
    script_content = script_tag.string
    
    # Extract the details tab HTML content
    details_match = re.search(
        r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']',
        script_content, re.DOTALL
    )
    
    if not details_match:
        print("✗ Could not extract details HTML from script")
        return
    
    print("✓ Details HTML extracted from script")
    
    # Decode the HTML content
    details_html = details_match.group(1)
    details_html = details_html.replace('\\/', '/').replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
    
    print("\n=== RAW DETAILS HTML ===")
    print(details_html[:1000] + "..." if len(details_html) > 1000 else details_html)
    
    details_soup = BeautifulSoup(details_html, 'html.parser')
    print("\n=== PARSED DETAILS HTML STRUCTURE ===")
    
    # Find all tables
    tables = details_soup.find_all('table')
    print(f"Found {len(tables)} table(s)")
    
    for i, table in enumerate(tables):
        print(f"\n--- TABLE {i+1} ---")
        headers = table.find_all('th')
        print(f"Headers ({len(headers)}):")
        for j, header in enumerate(headers):
            header_text = header.get_text(strip=True)
            print(f"  {j+1}. '{header_text}'")
            if 'Uzturvērtība' in header_text:
                print("    ^ NUTRITION HEADER FOUND!")
        
        # Show first few rows
        rows = table.find_all('tr')
        print(f"Rows ({len(rows)}):")
        for j, row in enumerate(rows[:5]):  # Show first 5 rows
            cells = row.find_all(['td', 'th'])
            if cells:
                cell_texts = [cell.get_text(strip=True) for cell in cells]
                print(f"  Row {j+1}: {cell_texts}")
    
    print("\n=== NUTRITION DATA EXTRACTION TEST ===")
    
    # Test the exact logic from robust_web_client.py
    nutrition_table = None
    for table in tables:
        headers = table.find_all('th')
        print(f"Checking table with {len(headers)} headers...")
        for header in headers:
            header_text = header.get_text(strip=True)
            print(f"  Header: '{header_text}'")
            if 'Uzturvērtība' in header_text:
                nutrition_table = table
                print("  ✓ NUTRITION TABLE FOUND!")
                break
        if nutrition_table:
            break
    
    if nutrition_table:
        print("\n✓ Nutrition table detected - extracting data...")
        
        def extract_decimal(text: str) -> float:
            try:
                numbers = re.findall(r'\d+(?:[.,]\d+)?', text.replace(',', '.'))
                return float(numbers[0]) if numbers else 0.0
            except (ValueError, AttributeError):
                return 0.0
        
        def extract_energy_values(text: str) -> tuple:
            try:
                pattern = r'(\d+(?:[.,]\d+)?)\s*kJ\s*[/\\]\s*(\d+(?:[.,]\d+)?)\s*kcal'
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    kj = extract_decimal(match.group(1))
                    kcal = extract_decimal(match.group(2))
                    return kj, kcal
                return 0.0, 0.0
            except Exception:
                return 0.0, 0.0
        
        nutrition_data = {}
        found_count = 0
        
        for row in nutrition_table.find_all('tr'):
            cells = row.find_all(['td'])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                value = cells[1].get_text(strip=True)
                
                print(f"Processing: '{label}' -> '{value}'")
                
                if 'enerģētiskā vērtība' in label:
                    kj, kcal = extract_energy_values(value)
                    if kj > 0 or kcal > 0:
                        nutrition_data['energy_kj'] = kj
                        nutrition_data['energy_kcal'] = kcal
                        found_count += 2
                        print(f"  ✓ Energy: {kcal} kcal ({kj} kJ)")
                
                elif 'tauki' in label and 'piesātinātās' not in label and 'tostarp' not in label:
                    fat_total = extract_decimal(value)
                    if fat_total > 0:
                        nutrition_data['fat_total'] = fat_total
                        found_count += 1
                        print(f"  ✓ Fat total: {fat_total}g")
                
                elif 'piesātinātās taukskābes' in label or 'tostarp piesātinātās' in label:
                    fat_saturated = extract_decimal(value)
                    nutrition_data['fat_saturated'] = fat_saturated
                    found_count += 1
                    print(f"  ✓ Saturated fat: {fat_saturated}g")
                
                elif 'ogļhidrāti' in label and 'cukuri' not in label and 'tostarp' not in label:
                    carbs_total = extract_decimal(value)
                    nutrition_data['carbs_total'] = carbs_total
                    found_count += 1
                    print(f"  ✓ Carbohydrates: {carbs_total}g")
                
                elif 'cukuri' in label or 'tostarp cukuri' in label:
                    carbs_sugars = extract_decimal(value)
                    nutrition_data['carbs_sugars'] = carbs_sugars
                    found_count += 1
                    print(f"  ✓ Sugars: {carbs_sugars}g")
                
                elif 'olbaltumvielas' in label:
                    protein = extract_decimal(value)
                    nutrition_data['protein'] = protein
                    found_count += 1
                    print(f"  ✓ Protein: {protein}g")
                
                elif 'sāls' in label:
                    salt = extract_decimal(value)
                    nutrition_data['salt'] = salt
                    found_count += 1
                    print(f"  ✓ Salt: {salt}g")
        
        print(f"\n=== FINAL RESULTS ===")
        print(f"Found {found_count} nutrition values:")
        for key, value in nutrition_data.items():
            print(f"  {key}: {value}")
            
    else:
        print("✗ No nutrition table found")
        print("\nTrying alternative detection methods...")
        
        # Look for any table with nutrition-like content
        for table in tables:
            table_text = table.get_text().lower()
            if any(word in table_text for word in ['enerģētiskā', 'tauki', 'ogļhidrāti', 'olbaltumvielas', 'sāls']):
                print(f"Found table with nutrition keywords:")
                print(table.prettify()[:500] + "...")
                break

if __name__ == "__main__":
    debug_olive_oil_nutrition()