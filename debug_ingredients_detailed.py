"""
Detailed ingredient extraction debug for SKU 815963
"""

def debug_ingredient_locations():
    """Find exactly where ingredients are stored in the HTML"""
    
    import requests
    from bs4 import BeautifulSoup
    import re
    import json
    
    # Fetch the page
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    url = "https://www.rimi.lv/e-veikals/lv/produkti/p/815963"
    response = session.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    print("=== SEARCHING FOR INGREDIENTS ===")
    
    # 1. Look for specific ingredient text patterns
    ingredient_keywords = ['saulespuķu', 'sastāvdaļas', 'ingredients', 'sēklu masa']
    
    print("\n1. Direct text search in page:")
    page_text = soup.get_text().lower()
    for keyword in ingredient_keywords:
        if keyword in page_text:
            # Find context around the keyword
            start_pos = page_text.find(keyword)
            context = page_text[max(0, start_pos-100):start_pos+200]
            print(f"Found '{keyword}' in context:")
            print(f"...{context.strip()}...")
            print()
    
    # 2. Search in all script tags
    print("\n2. Searching in script tags:")
    script_count = 0
    for script in soup.find_all('script'):
        if script.string:
            script_content = script.string.lower()
            if any(keyword in script_content for keyword in ingredient_keywords):
                script_count += 1
                print(f"\nScript {script_count} contains ingredients:")
                
                # Try to extract structured data
                if 'storefront.product_details_page' in script_content:
                    print("✓ Found Storefront.product_details_page script")
                    
                    # Look for the tabs structure
                    tabs_match = re.search(r'tabs:\s*(\[.*?\])', script.string, re.DOTALL)
                    if tabs_match:
                        print("✓ Found tabs structure")
                        tabs_text = tabs_match.group(1)
                        
                        # Look for details tab
                        if 'details' in tabs_text:
                            print("✓ Found details tab")
                            
                            # Extract the HTML content from details tab
                            details_match = re.search(
                                r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']*)["\']',
                                script.string, re.DOTALL
                            )
                            
                            if details_match:
                                details_html = details_match.group(1)
                                # Decode escaped HTML
                                details_html = details_html.replace('\\/', '/').replace('\\"', '"')
                                details_html = details_html.replace('\\n', '\n').replace('\\t', '\t')
                                
                                print("\n✓ Extracted details HTML:")
                                print(details_html[:500] + "..." if len(details_html) > 500 else details_html)
                                
                                # Parse the details HTML
                                details_soup = BeautifulSoup(details_html, 'html.parser')
                                
                                # Look for ingredients in the parsed HTML
                                for element in details_soup.find_all(['div', 'p', 'span', 'td', 'th']):
                                    text = element.get_text().strip()
                                    if any(keyword in text.lower() for keyword in ingredient_keywords):
                                        print(f"\nFound ingredient element: {element.name}")
                                        print(f"Text: {text}")
                                        
                                        # Check if this contains the actual ingredients
                                        if len(text) > 50 and 'saulespuķu' in text.lower():
                                            print(f"★ POTENTIAL INGREDIENTS: {text}")
    
    # 3. Look in JSON-LD structured data
    print("\n3. Searching in JSON-LD structured data:")
    json_scripts = soup.find_all('script', type='application/ld+json')
    for i, script in enumerate(json_scripts):
        try:
            data = json.loads(script.string)
            print(f"JSON-LD {i+1}: {type(data)}")
            
            def search_json_recursive(obj, path=""):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        new_path = f"{path}.{key}" if path else key
                        if isinstance(value, str) and any(keyword in value.lower() for keyword in ingredient_keywords):
                            print(f"Found in {new_path}: {value}")
                        search_json_recursive(value, new_path)
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        search_json_recursive(item, f"{path}[{i}]")
            
            search_json_recursive(data)
        except json.JSONDecodeError:
            continue
    
    # 4. Look in meta tags
    print("\n4. Checking meta tags:")
    for meta in soup.find_all('meta'):
        content = meta.get('content', '')
        if content and any(keyword in content.lower() for keyword in ingredient_keywords):
            print(f"Meta {meta.get('name', meta.get('property', 'unknown'))}: {content}")
    
    # 5. Look for specific HTML structures
    print("\n5. Checking common ingredient containers:")
    
    # Check for ingredient tables
    for table in soup.find_all('table'):
        table_text = table.get_text().lower()
        if any(keyword in table_text for keyword in ingredient_keywords):
            print("Found ingredients in table:")
            print(table.prettify()[:500])
    
    # Check for ingredient divs
    for div in soup.find_all('div'):
        div_text = div.get_text().lower()
        if 'sastāvdaļas' in div_text and len(div_text) > 20:
            print("Found ingredients in div:")
            print(f"Class: {div.get('class')}")
            print(f"Text: {div.get_text().strip()}")

if __name__ == "__main__":
    debug_ingredient_locations()