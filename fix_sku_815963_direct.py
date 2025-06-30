"""
Direct fix for SKU 815963 - Target ingredient and photo extraction specifically
"""

def fix_sku_815963():
    """Fix SKU 815963 ingredient and photo extraction issues"""
    
    def status_callback(msg):
        print(f"[{msg}]")
    
    try:
        # Test direct web scraping first
        import requests
        from bs4 import BeautifulSoup
        import re
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'lv,en-US;q=0.9,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        })
        
        url = "https://www.rimi.lv/e-veikals/lv/produkti/p/815963"
        print(f"Fetching: {url}")
        
        response = session.get(url)
        if response.status_code != 200:
            print(f"Failed to fetch: {response.status_code}")
            return
        
        soup = BeautifulSoup(response.text, 'html.parser')
        print("✓ Page fetched successfully")
        
        # 1. EXTRACT PHOTOS DIRECTLY
        print("\n=== PHOTO EXTRACTION ===")
        photos = []
        
        # Look for product images
        img_tags = soup.find_all('img')
        for img in img_tags:
            src = img.get('src') or img.get('data-src') or img.get('data-lazy')
            if src and any(x in str(src) for x in ['product', 'rimi', 'cloudinary']):
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = 'https://www.rimi.lv' + src
                
                if src not in photos:
                    photos.append(src)
                    print(f"Found photo: {src}")
        
        print(f"Total photos found: {len(photos)}")
        
        # 2. EXTRACT INGREDIENTS DIRECTLY FROM SCRIPT
        print("\n=== INGREDIENT EXTRACTION ===")
        ingredients_text = ""
        
        # Look in script tags for product details
        for script in soup.find_all('script'):
            if script.string and 'Storefront.product_details_page' in script.string:
                script_content = script.string
                print("Found product details script")
                
                # Look for ingredients in the script content
                if 'saulespuķu sēklu masa' in script_content.lower():
                    print("✓ Found sunflower seed ingredients in script")
                    
                    # Try different patterns
                    patterns = [
                        r'saulespuķu sēklu masa[^"]*?(?:, [^"]*)*',
                        r'Sastāvdaļas[^"]*?saulespuķu[^"]*',
                        r'"ingredients":"([^"]*saulespuķu[^"]*)"'
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, script_content, re.IGNORECASE | re.DOTALL)
                        if match:
                            if len(match.groups()) > 0:
                                ingredients_text = match.group(1)
                            else:
                                ingredients_text = match.group(0)
                            
                            print(f"Extracted ingredients: {ingredients_text}")
                            break
                
                # Also try structured extraction from details HTML
                details_match = re.search(
                    r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']',
                    script_content, re.DOTALL
                )
                
                if details_match:
                    details_html = details_match.group(1)
                    details_html = details_html.replace('\\/', '/').replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                    print("Found details HTML content")
                    
                    if 'saulespuķu' in details_html.lower():
                        print("✓ Found sunflower ingredients in details HTML")
                        
                        # Parse the details HTML
                        details_soup = BeautifulSoup(details_html, 'html.parser')
                        
                        # Look for ingredients section
                        for element in details_soup.find_all(['div', 'p', 'span']):
                            text = element.get_text()
                            if 'sastāvdaļas' in text.lower() and 'saulespuķu' in text.lower():
                                # Extract the ingredients part
                                lines = text.split('\n')
                                for line in lines:
                                    if 'saulespuķu' in line.lower():
                                        ingredients_text = line.strip()
                                        print(f"Found ingredients line: {ingredients_text}")
                                        break
                                if ingredients_text:
                                    break
                break
        
        # If still no ingredients, try direct text search
        if not ingredients_text:
            print("Trying direct text search...")
            page_text = soup.get_text()
            if 'saulespuķu sēklu masa' in page_text.lower():
                print("✓ Found ingredients in page text")
                # Find the context around the ingredients
                start_pos = page_text.lower().find('saulespuķu sēklu masa')
                context = page_text[max(0, start_pos-50):start_pos+200]
                # Try to extract just the ingredients part
                lines = context.split('\n')
                for line in lines:
                    if 'saulespuķu' in line.lower() and len(line.strip()) > 20:
                        ingredients_text = line.strip()
                        print(f"Extracted from context: {ingredients_text}")
                        break
        
        print(f"Final ingredients: {ingredients_text}")
        
        # 3. NOW UPDATE DATABASE WITH EXTRACTED DATA
        print("\n=== DATABASE UPDATE ===")
        
        if photos or ingredients_text:
            from enhanced_database_updater import EnhancedDatabaseUpdater
            
            db_updater = EnhancedDatabaseUpdater(status_callback)
            
            # Get the product
            product = db_updater.get_product_by_sku("815963")
            if product:
                product_id = product['product_id']
                print(f"Found product ID: {product_id}")
                
                # Save photos
                if photos:
                    success = db_updater.add_product_photos(product_id, photos)
                    print(f"Photos saved: {success}")
                
                # Save ingredients
                if ingredients_text:
                    success = db_updater.force_update_ingredients("815963", ingredients_text)
                    print(f"Ingredients saved: {success}")
                
                # Verify in database
                print("\n=== VERIFICATION ===")
                
                # Check photos
                photo_query = "SELECT photo_url, is_primary FROM productphotos WHERE product_id = %s"
                photos_in_db = db_updater._execute_query(photo_query, (product_id,), fetch=True)
                print(f"Photos in database: {len(photos_in_db) if photos_in_db else 0}")
                
                # Check ingredients
                ingredient_query = """
                    SELECT ia.ingredient, ia.frequency 
                    FROM ingredient_product_mapping ipm
                    JOIN ingredient_analysis ia ON ipm.ingredient_id = ia.id
                    WHERE ipm.product_sku = %s
                """
                ingredients_in_db = db_updater._execute_query(ingredient_query, ("815963",), fetch=True)
                print(f"Ingredients in database: {len(ingredients_in_db) if ingredients_in_db else 0}")
                
                if ingredients_in_db:
                    for ing in ingredients_in_db[:3]:
                        print(f"  - {ing[0]} (frequency: {ing[1]})")
            
            db_updater.close()
        else:
            print("No photos or ingredients found to save")
        
        print("\n=== SUMMARY ===")
        print(f"Photos extracted: {len(photos)}")
        print(f"Ingredients found: {'Yes' if ingredients_text else 'No'}")
        if ingredients_text:
            print(f"Ingredients text: {ingredients_text[:100]}...")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    fix_sku_815963()