"""
Quick Photo Test - Simple verification of photo extraction and database saving
"""
from robust_web_client import RobustWebClient
from enhanced_database_updater import EnhancedDatabaseUpdater

def test_photo_functionality():
    """Quick test of photo extraction and saving"""
    
    print("Testing photo extraction and database saving...")
    
    def status_callback(msg):
        print(f"[TEST] {msg}")
    
    # Test photo extraction
    print("\n1. Testing photo extraction...")
    web_client = RobustWebClient(status_callback)
    product_data = web_client.get_product_data("815963")
    
    if product_data and product_data.get('photos'):
        photo_url = product_data['photos'][0]
        print(f"✓ Photo extracted: {photo_url}")
    else:
        print("❌ Photo extraction failed")
        return
    
    # Test database saving
    print("\n2. Testing database saving...")
    db_updater = EnhancedDatabaseUpdater(status_callback)
    
    # Get product
    product = db_updater.get_product_by_sku("815963")
    if not product:
        print("❌ Product not found")
        return
    
    product_id = product['product_id']
    print(f"✓ Product found: ID {product_id}")
    
    # Save photo
    result = db_updater.add_product_photos(product_id, [photo_url])
    print(f"Photo save result: {result}")
    
    # Verify saved
    check_query = "SELECT COUNT(*) as count FROM productphotos WHERE product_id = %s"
    check_result = db_updater._execute_query(check_query, (product_id,), fetch=True)
    
    if check_result:
        count = check_result[0][0]  # Access tuple directly
        print(f"Photos in database: {count}")
        
        if count > 0:
            print("✓ SUCCESS: Photo successfully saved!")
            
            # Show the photo
            photo_query = "SELECT photo_url, is_primary FROM productphotos WHERE product_id = %s"
            photos = db_updater._execute_query(photo_query, (product_id,), fetch=True)
            for i, photo_record in enumerate(photos, 1):
                primary = "PRIMARY" if photo_record[1] else "SECONDARY"
                print(f"  Photo {i}: {photo_record[0]} ({primary})")
        else:
            print("❌ No photos found after save")
    else:
        print("❌ Could not verify photo count")
    
    db_updater.close()

if __name__ == "__main__":
    test_photo_functionality()