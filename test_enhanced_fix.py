"""
Test Enhanced Fix - Verify the enhanced system fixes SKU 147762 issues
Tests robust web client and enhanced database updater
"""

def test_sku_147762_fix():
    """Test the enhanced system on the problematic SKU 147762"""
    
    print("=== TESTING ENHANCED FIX FOR SKU 147762 ===")
    
    def status_callback(msg):
        print(f"[ENHANCED FIX] {msg}")
    
    try:
        # Test 1: Robust Web Client
        print("\n1. TESTING ROBUST WEB CLIENT")
        from robust_web_client import RobustWebClient
        
        web_client = RobustWebClient(status_callback)
        product_data = web_client.get_product_data('147762')
        
        if product_data:
            print(f"✓ Product found: {product_data['name']}")
            print(f"✓ Price: €{product_data['price']}")
            print(f"✓ URL: {product_data['url']}")
            
            # Test nutrition extraction
            nutrition_data = web_client.extract_nutrition_data(product_data['soup'], product_data['url'])
            print(f"✓ Nutrition data extracted: {nutrition_data.get('has_nutrition', False)}")
            if nutrition_data.get('ingredients'):
                print(f"✓ Ingredients found: {nutrition_data['ingredients'][:50]}...")
        else:
            print("✗ Product not found with robust web client")
            return False
        
        web_client.close()
        
        # Test 2: Enhanced Database Updater
        print("\n2. TESTING ENHANCED DATABASE UPDATER")
        from enhanced_database_updater import EnhancedDatabaseUpdater
        
        db_updater = EnhancedDatabaseUpdater(status_callback)
        
        # Check if product exists and has corrupted data
        existing_product = db_updater.get_product_by_sku('147762')
        if existing_product:
            print(f"✓ Existing product found: ID {existing_product['product_id']}")
            print(f"  - Name: {existing_product.get('name', 'N/A')}")
            print(f"  - Category ID: {existing_product.get('category_id', 'N/A')}")
            print(f"  - Rimi URL: {existing_product.get('rimi_url', 'NULL')}")
            
            # Test force update
            print("\n3. TESTING FORCE UPDATE")
            update_data = {
                'rimi_url': product_data['url'],
                'category_id': 298,  # Correct category for olive oil
                'name': product_data['name'],
                'price': product_data['price'],
                'nutrition_data': nutrition_data,
                'ingredients': nutrition_data.get('ingredients', '')
            }
            
            success = db_updater.force_update_product_data('147762', update_data, force_overwrite=True)
            if success:
                print("✓ Force update successful")
                
                # Verify the fix
                updated_product = db_updater.get_product_by_sku('147762')
                if updated_product:
                    print(f"✓ Verification - Category ID: {updated_product.get('category_id')}")
                    print(f"✓ Verification - Rimi URL: {updated_product.get('rimi_url', 'NULL')}")
                
            else:
                print("✗ Force update failed")
                
        else:
            print("Product doesn't exist - would create new")
        
        db_updater.close()
        
        print("\n=== ENHANCED FIX TEST COMPLETED ===")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {str(e)}")
        return False

if __name__ == "__main__":
    test_sku_147762_fix()