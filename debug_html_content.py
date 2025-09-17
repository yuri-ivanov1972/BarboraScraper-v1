#!/usr/bin/env python3
"""
Debug HTML content to see what category information is actually available
"""

def examine_product_html():
    """Examine the actual HTML content for category information"""
    print("=== Examining Product HTML for Category Data ===")
    
    try:
        from robust_web_client import RobustWebClient
        
        def debug_callback(msg):
            print(f"[DEBUG] {msg}")
        
        client = RobustWebClient(debug_callback)
        test_sku = "147762"
        
        # Get product data
        product_data = client.get_product_data(test_sku)
        if not product_data:
            print("❌ Failed to get product data")
            return
        
        soup = product_data['soup']
        
        # Look for JavaScript with product details
        print("\n1. Searching for product details script...")
        script_found = False
        for script in soup.find_all('script'):
            if script.string and 'Storefront.product_details_page' in script.string:
                script_content = script.string
                print("✓ Found product details script")
                script_found = True
                
                # Extract details HTML
                import re
                details_match = re.search(
                    r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']',
                    script_content, re.DOTALL
                )
                
                if details_match:
                    details_html = details_match.group(1)
                    details_html = details_html.replace('\\/', '/').replace('\\"', '"')
                    details_html = details_html.replace('\\n', '\n').replace('\\t', '\t')
                    
                    print("✓ Found details HTML content")
                    
                    # Decode Unicode
                    try:
                        details_html = details_html.encode('utf-8').decode('unicode_escape')
                    except:
                        pass
                    
                    # Parse and examine content
                    from bs4 import BeautifulSoup
                    details_soup = BeautifulSoup(details_html, 'html.parser')
                    
                    print(f"\n2. Examining details HTML structure:")
                    print(f"   Total text length: {len(details_soup.get_text())}")
                    
                    # Look for category-related text
                    all_text = details_soup.get_text().lower()
                    
                    category_keywords = ['kategorija', 'category', 'produkta kategorija']
                    print(f"\n3. Searching for category keywords...")
                    
                    found_keywords = []
                    for keyword in category_keywords:
                        if keyword in all_text:
                            found_keywords.append(keyword)
                            # Find context around keyword
                            pos = all_text.find(keyword)
                            start = max(0, pos - 50)
                            end = min(len(all_text), pos + 100)
                            context = all_text[start:end]
                            print(f"   ✓ Found '{keyword}' at position {pos}")
                            print(f"     Context: ...{context}...")
                    
                    if not found_keywords:
                        print("   ❌ No category keywords found in HTML")
                    
                    # Look for SH-codes
                    print(f"\n4. Searching for RIMI codes (SH-X-X format)...")
                    sh_codes = re.findall(r'\bSH-\d+-\d+(?:-\d+)?\b', all_text, re.IGNORECASE)
                    if sh_codes:
                        print(f"   ✓ Found RIMI codes: {sh_codes}")
                        for code in sh_codes:
                            pos = all_text.find(code.lower())
                            start = max(0, pos - 50)
                            end = min(len(all_text), pos + 100)
                            context = all_text[start:end]
                            print(f"     Code '{code}' context: ...{context}...")
                    else:
                        print("   ❌ No RIMI codes found in HTML")
                    
                    # Look at the structure
                    print(f"\n5. Examining HTML structure:")
                    list_items = details_soup.find_all('li')
                    print(f"   Found {len(list_items)} list items")
                    
                    for i, li in enumerate(list_items[:10]):  # Show first 10
                        span = li.find('span')
                        div_text = li.find('div', class_='text')
                        if span and div_text:
                            span_text = span.get_text(strip=True)
                            div_content = div_text.get_text(strip=True)
                            print(f"   Item {i+1}: '{span_text}' -> '{div_content[:60]}...'")
                    
                    # Look for product list wrappers
                    wrappers = details_soup.find_all('div', class_='product__list-wrapper')
                    print(f"\n   Found {len(wrappers)} product list wrappers")
                    
                    for i, wrapper in enumerate(wrappers):
                        heading = wrapper.find('p', class_='heading')
                        if heading:
                            heading_text = heading.get_text(strip=True)
                            print(f"   Wrapper {i+1} heading: '{heading_text}'")
                
                break
        
        if not script_found:
            print("❌ No product details script found")
        
        # Also check main page for category breadcrumbs
        print(f"\n6. Checking main page for category breadcrumbs...")
        breadcrumbs = soup.find_all(['nav', 'ol', 'ul'], class_=lambda x: x and 'breadcrumb' in x.lower())
        if breadcrumbs:
            print(f"   Found {len(breadcrumbs)} breadcrumb elements")
            for bc in breadcrumbs:
                print(f"   Breadcrumb: {bc.get_text(strip=True)[:100]}...")
        else:
            print("   ❌ No breadcrumbs found")
        
    except Exception as e:
        print(f"❌ Error examining HTML: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    examine_product_html()