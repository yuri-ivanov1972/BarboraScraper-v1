"""
Debug SKU 815963 ingredients extraction - Find where ingredients actually are in the HTML
"""

def debug_ingredient_extraction():
    """Debug exactly where ingredients are in the HTML for SKU 815963"""
    
    def status_callback(msg):
        print(f"[{msg}]")
    
    try:
        from robust_web_client import RobustWebClient
        
        client = RobustWebClient(status_callback)
        sku = "815963"
        url = f"https://www.rimi.lv/e-veikals/lv/produkti/p/{sku}"
        
        print(f"Debugging ingredient extraction for SKU {sku}")
        print("=" * 60)
        
        # Get the raw HTML
        soup = client.make_request_with_retry(url)
        
        if soup:
            # Look for any mention of "Sastāvdaļas" in the entire page
            full_text = soup.get_text()
            
            print("\n1. Searching for 'Sastāvdaļas' in full page text...")
            if 'Sastāvdaļas' in full_text:
                print("✓ Found 'Sastāvdaļas' in page text")
                
                # Find the context around it
                start_pos = full_text.find('Sastāvdaļas')
                context = full_text[max(0, start_pos-50):start_pos+200]
                print(f"Context: ...{context}...")
            else:
                print("✗ 'Sastāvdaļas' not found in page text")
            
            # Check in script tags for product details
            print("\n2. Checking script tags for product details...")
            script_tags = soup.find_all('script')
            
            for i, script in enumerate(script_tags):
                if script.string and 'Sastāvdaļas' in script.string:
                    print(f"✓ Found 'Sastāvdaļas' in script tag {i}")
                    
                    # Look for the product details structure
                    import re
                    details_match = re.search(
                        r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']',
                        script.string, re.DOTALL
                    )
                    
                    if details_match:
                        print("✓ Found details tab HTML structure")
                        details_html = details_match.group(1)
                        details_html = details_html.replace('\\/', '/').replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                        
                        print("\n3. Analyzing details HTML content...")
                        from bs4 import BeautifulSoup
                        details_soup = BeautifulSoup(details_html, 'html.parser')
                        
                        # Look for ingredients in different structures
                        print("\n   Method A: Looking in list items...")
                        items = details_soup.find_all('li', class_='item')
                        for j, item in enumerate(items):
                            span = item.find('span')
                            if span and 'Sastāvdaļas' in span.get_text(strip=True):
                                print(f"   ✓ Found in item {j}: {span.get_text(strip=True)}")
                                text_div = item.find('div', class_='text')
                                if text_div and text_div.p:
                                    ingredients = text_div.p.get_text(strip=True)
                                    print(f"   ✓ Ingredients: {ingredients[:100]}...")
                                    return ingredients
                        
                        print("\n   Method B: Looking in product list wrappers...")
                        sections = details_soup.find_all('div', class_='product__list-wrapper')
                        for j, section in enumerate(sections):
                            heading = section.find('p', class_='heading')
                            if heading and 'Sastāvdaļas' in heading.get_text(strip=True):
                                print(f"   ✓ Found in wrapper {j}: {heading.get_text(strip=True)}")
                                text_div = section.find('div', class_='text')
                                if text_div and text_div.p:
                                    ingredients = text_div.p.get_text(strip=True)
                                    print(f"   ✓ Ingredients: {ingredients[:100]}...")
                                    return ingredients
                        
                        print("\n   Method C: Raw text search in details HTML...")
                        if 'Sastāvdaļas' in details_html:
                            pattern = r'Sastāvdaļas[^<]*(?:<[^>]*>)*([^<]*(?:<[^>]*>[^<]*)*?)(?:<|$)'
                            match = re.search(pattern, details_html, re.DOTALL | re.IGNORECASE)
                            if match:
                                ingredients = match.group(1).strip()
                                print(f"   ✓ Raw match: {ingredients[:100]}...")
                                return ingredients
                        
                        # Show the actual details HTML structure
                        print(f"\n   Details HTML structure (first 500 chars):")
                        print(f"   {details_html[:500]}...")
                        
                        # Show ingredients context if found
                        if 'saulespuķu' in details_html.lower():
                            start = details_html.lower().find('saulespuķu')
                            context = details_html[max(0, start-100):start+200]
                            print(f"\n   Found 'saulespuķu' context:")
                            print(f"   {context}")
            
            print("\n4. Direct HTML search for ingredients...")
            html_str = str(soup)
            if 'saulespuķu sēklu masa' in html_str.lower():
                print("✓ Found ingredient text in main HTML")
                # Find context
                start = html_str.lower().find('saulespuķu sēklu masa')
                context = html_str[max(0, start-200):start+300]
                print(f"Context: {context}")
            else:
                print("✗ Ingredient text not found in main HTML")
        
        print("\n5. Summary:")
        print("✗ No ingredients extracted by any method")
        
    except Exception as e:
        print(f"Error during debug: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_ingredient_extraction()