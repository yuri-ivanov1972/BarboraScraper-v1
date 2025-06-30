"""
Complete Photo Functionality Test
Tests the entire photo workflow from website extraction to database saving
Uses the correct PRODUCTS_DB_URL schema with productphotos table
"""

import os
from robust_web_client import RobustWebClient
from enhanced_database_updater import EnhancedDatabaseUpdater

def test_complete_photo_workflow():
    """Test complete photo workflow from extraction to database saving"""
    print("=" * 60)
    print("COMPLETE PHOTO FUNCTIONALITY TEST")
    print("=" * 60)
    
    # Test SKU with known photo availability
    test_sku = "815963"  # SKU that should have photos
    
    def status_callback(msg):
        print(f"[STATUS] {msg}")
    
    print(f"\n1. Testing photo extraction for SKU {test_sku}")
    print("-" * 40)
    
    # Initialize web client
    web_client = RobustWebClient(status_callback)
    
    # Get product data including photos
    product_url = f"https://www.rimi.lv/e-veikals/lv/produkti/p/{test_sku}"
    print(f"Extracting from: {product_url}")
    
    try:
        product_data = web_client.get_product_data(product_url)
        
        if not product_data:
            print("❌ Failed to extract product data")
            return
        
        print(f"✅ Product data extracted: {product_data.get('name', 'Unknown')}")
        
        # Check photo extraction
        photos = product_data.get('photos', [])
        print(f"📸 Photos extracted: {len(photos)}")
        
        if photos:
            for i, photo in enumerate(photos):
                print(f"   Photo {i+1}: {photo}")
        else:
            print("❌ No photos extracted - checking HTML content...")
            
            # Debug photo extraction
            print("\n2. Debugging photo extraction")
            print("-" * 40)
            
            response = web_client.session.get(product_url)
            if response.status_code == 200:
                soup = web_client._create_soup(response.text)
                
                # Check different photo selectors
                selectors_to_test = [
                    'img[src*="cloudinary"]',
                    '.product-image img',
                    '.product-photos img',
                    'img[alt*="product"]',
                    'img[data-src*="cloudinary"]'
                ]
                
                for selector in selectors_to_test:
                    elements = soup.select(selector)
                    print(f"   Selector '{selector}': {len(elements)} matches")
                    
                    if elements:
                        for i, elem in enumerate(elements[:3]):  # Show first 3
                            src = elem.get('src') or elem.get('data-src')
                            print(f"      {i+1}. {src}")
            
            # Stop here if no photos found
            return
    
    except Exception as e:
        print(f"❌ Error during photo extraction: {str(e)}")
        return
    
    print(f"\n3. Testing database photo saving")
    print("-" * 40)
    
    # Initialize database updater
    db_updater = EnhancedDatabaseUpdater(status_callback)
    
    try:
        # Get or create a test product
        existing_product = db_updater.get_product_by_sku(test_sku)
        
        if existing_product:
            product_id = existing_product['product_id']
            print(f"✅ Found existing product ID: {product_id}")
        else:
            print(f"⚠️  Product {test_sku} not found in database")
            print("Creating test product entry...")
            
            # Create minimal product entry for testing
            test_product_data = {
                'sku': test_sku,
                'name': 'Test Product for Photo Testing',
                'rimi_url': product_url,
                'category_id': 1,  # Default category
                'price': '1.99',
                'is_available': True
            }
            
            product_id = db_updater.add_new_product(test_product_data)
            if product_id:
                print(f"✅ Created test product with ID: {product_id}")
            else:
                print("❌ Failed to create test product")
                return
        
        # Test photo saving
        print(f"\n4. Saving photos to database")
        print("-" * 40)
        
        if photos:
            success = db_updater.add_product_photos(product_id, photos)
            
            if success:
                print("✅ Photos saved successfully!")
                
                # Verify photos in database
                print(f"\n5. Verifying photos in database")
                print("-" * 40)
                
                query = "SELECT photo_id, photo_url, is_primary FROM productphotos WHERE product_id = %s ORDER BY is_primary DESC"
                saved_photos = db_updater._execute_query(query, (product_id,), fetch=True)
                
                if saved_photos:
                    print(f"✅ Found {len(saved_photos)} photo(s) in database:")
                    for photo in saved_photos:
                        primary_status = "PRIMARY" if photo[2] else "secondary"
                        print(f"   {primary_status}: {photo[1]}")
                else:
                    print("❌ No photos found in database after saving")
            else:
                print("❌ Failed to save photos to database")
        else:
            print("⚠️  No photos to save")
    
    except Exception as e:
        print(f"❌ Error during database operations: {str(e)}")
    
    finally:
        db_updater.close()
        print(f"\n6. Test completed")
        print("=" * 60)

if __name__ == "__main__":
    test_complete_photo_workflow()