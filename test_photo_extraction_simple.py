"""
Simple Photo Extraction Test
Tests photo extraction directly from SKU without URL construction issues
"""

from robust_web_client import RobustWebClient
from enhanced_database_updater import EnhancedDatabaseUpdater

def test_photo_extraction_simple():
    """Test photo extraction for a specific SKU"""
    print("Testing photo extraction for SKU 815963")
    print("=" * 50)
    
    def status_callback(msg):
        print(f"[STATUS] {msg}")
    
    # Test with just the SKU
    test_sku = "815963"
    
    # Initialize web client
    web_client = RobustWebClient(status_callback)
    
    try:
        # Get product data - pass just the SKU
        product_data = web_client.get_product_data(test_sku)
        
        if product_data:
            print(f"✅ Product found: {product_data['name']}")
            photos = product_data.get('photos', [])
            print(f"📸 Photos extracted: {len(photos)}")
            
            if photos:
                for i, photo in enumerate(photos):
                    print(f"   Photo {i+1}: {photo}")
                
                # Test database saving
                print(f"\nTesting database photo saving...")
                db_updater = EnhancedDatabaseUpdater(status_callback)
                
                try:
                    # Check if product exists
                    existing_product = db_updater.get_product_by_sku(test_sku)
                    
                    if existing_product:
                        product_id = existing_product.get('product_id')
                        print(f"Found existing product ID: {product_id}")
                        
                        # Save photos
                        success = db_updater.add_product_photos(product_id, photos)
                        
                        if success:
                            print("✅ Photos saved to database successfully!")
                        else:
                            print("❌ Failed to save photos to database")
                    else:
                        print(f"Product {test_sku} not found in database")
                
                except Exception as e:
                    print(f"Database error: {str(e)}")
                finally:
                    db_updater.close()
            else:
                print("No photos found")
        else:
            print("❌ Product not found")
            
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    test_photo_extraction_simple()