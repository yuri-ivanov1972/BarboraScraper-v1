"""
Test SKU 815963 fix - Complete test of ingredient and photo extraction
"""

def test_sku_815963_complete_fix():
    """Test the complete fix for SKU 815963"""
    
    def status_callback(msg):
        print(f"[{msg}]")
    
    try:
        from enhanced_update_coordinator import EnhancedUpdateCoordinator
        
        # Test with Force Update mode
        coordinator = EnhancedUpdateCoordinator(status_callback)
        
        sku = "815963"
        category_code = "SH-1-1-1"  # Default category
        
        print(f"Testing complete fix for SKU {sku}")
        print("=" * 50)
        
        # Process with force update to ensure complete data extraction
        result = coordinator.process_single_product_enhanced(
            sku=sku,
            category_code=category_code,
            force_update=True
        )
        
        print(f"\nProcessing result: {result.success}")
        print(f"Operation: {result.operation}")
        print(f"Changes: {result.changes}")
        
        if result.errors:
            print(f"Errors: {result.errors}")
        
        # Check if ingredients and photos were extracted
        product_data = result.product_data
        if product_data:
            print(f"\nExtracted product data:")
            print(f"- Name: {product_data.get('name', 'N/A')}")
            print(f"- Price: {product_data.get('price', 'N/A')}")
            
            # Check nutrition data for ingredients
            nutrition_data = product_data.get('nutrition_data', {})
            if nutrition_data.get('ingredients'):
                print(f"- Ingredients found: {nutrition_data['ingredients'][:100]}...")
            else:
                print("- No ingredients extracted")
                
            # Check photos
            photos = product_data.get('photos', [])
            if photos:
                print(f"- Photos found: {len(photos)} images")
                for i, photo in enumerate(photos):
                    print(f"  Photo {i+1}: {photo}")
            else:
                print("- No photos extracted")
        
        coordinator.close()
        
        # Verify in database
        print("\n" + "=" * 50)
        print("Verifying in database...")
        
        from enhanced_database_updater import EnhancedDatabaseUpdater
        db_updater = EnhancedDatabaseUpdater(status_callback)
        
        # Check product exists
        product = db_updater.get_product_by_sku(sku)
        if product:
            print(f"✓ Product found in database: {product['name']}")
            product_id = product['product_id']
            
            # Check ingredients
            ingredient_query = """
                SELECT ia.ingredient, ia.frequency 
                FROM ingredient_product_mapping ipm
                JOIN ingredient_analysis ia ON ipm.ingredient_id = ia.id
                WHERE ipm.product_sku = %s
            """
            ingredients = db_updater._execute_query(ingredient_query, (sku,), fetch=True)
            if ingredients:
                print(f"✓ Ingredients in database: {len(ingredients)} found")
                for ing in ingredients[:3]:  # Show first 3
                    print(f"  - {ing[0]} (frequency: {ing[1]})")
            else:
                print("✗ No ingredients found in database")
            
            # Check photos
            photo_query = """
                SELECT photo_url, is_primary
                FROM productphotos
                WHERE product_id = %s
            """
            photos = db_updater._execute_query(photo_query, (product_id,), fetch=True)
            if photos:
                print(f"✓ Photos in database: {len(photos)} found")
                for photo in photos:
                    primary = "PRIMARY" if photo[1] else "secondary"
                    print(f"  - {photo[0]} ({primary})")
            else:
                print("✗ No photos found in database")
        else:
            print("✗ Product not found in database")
        
        db_updater.close()
        
    except Exception as e:
        print(f"Error during test: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_sku_815963_complete_fix()