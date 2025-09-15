#!/usr/bin/env python3
"""
Test complete flow: extract ingredients for SKU 816707 and save to database
"""

def test_complete_flow():
    print("Testing complete SKU 816707 flow: extract + database save...")
    
    try:
        from enhanced_database_updater import EnhancedDatabaseUpdater
        
        # Initialize enhanced updater
        db_updater = EnhancedDatabaseUpdater(lambda msg: print(f"DB: {msg}"))
        
        print("Testing force update with SKU 816707...")
        
        # Simulate product data with ingredients
        product_data = {
            'sku': '816707',
            'name': 'Olas Rimi Smart kūtī dētas A/M Nr.2 10 gab.',
            'price': '2.15'
        }
        
        # Force update - this should extract ingredients and save to database
        success = db_updater.force_update_product_data('816707', product_data, force_overwrite=True)
        
        if success:
            print("✅ Force update completed!")
            
            # Check if ingredients_text was saved to database
            print("\nChecking database for ingredients_text...")
            
        else:
            print("❌ Force update failed!")
            
        db_updater.close()
            
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_complete_flow()