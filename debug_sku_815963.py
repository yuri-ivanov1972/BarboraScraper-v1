"""
Debug script to analyze specific data extraction issues for SKU 815963
- Missing ingredients
- Missing product photos
"""
import os
from enhanced_update_coordinator import EnhancedUpdateCoordinator
from robust_web_client import RobustWebClient

def analyze_sku_815963():
    """Analyze the specific issues with SKU 815963"""
    
    print("=== ANALYZING SKU 815963 DATA EXTRACTION ISSUES ===")
    
    def status_callback(msg):
        print(f"[DEBUG] {msg}")
    
    # Initialize web client to check what data is available
    web_client = RobustWebClient(status_callback)
    
    try:
        # Test data extraction from website
        print("\n1. TESTING WEBSITE DATA EXTRACTION")
        print("-" * 50)
        
        # Test with SKU directly
        product_data = web_client.get_product_data("815963")
        
        if not product_data:
            print("❌ Failed to extract product data from website")
            return
        
        print(f"✓ Product found: {product_data.get('name', 'N/A')}")
        print(f"✓ Price: {product_data.get('price', 'N/A')}")
        
        # Check ingredients
        print(f"\n2. INGREDIENTS ANALYSIS")
        print("-" * 30)
        ingredients = product_data.get('ingredients', '')
        if ingredients:
            print(f"✓ Ingredients extracted: {ingredients[:100]}...")
            print(f"  Full length: {len(ingredients)} characters")
        else:
            print("❌ No ingredients found in extracted data")
        
        # Check nutrition data
        nutrition = product_data.get('nutrition', {})
        if nutrition:
            print(f"✓ Nutrition data available: {len(nutrition)} fields")
            for key, value in nutrition.items():
                if key != 'ingredients':  # Already shown above
                    print(f"  {key}: {value}")
        
        # Check photos
        print(f"\n3. PRODUCT PHOTOS ANALYSIS")
        print("-" * 30)
        photos = product_data.get('photos', [])
        if photos:
            print(f"✓ Found {len(photos)} photo(s):")
            for i, photo in enumerate(photos, 1):
                print(f"  Photo {i}: {photo}")
        else:
            print("❌ No product photos found in extracted data")
        
        # Test enhanced processing
        print(f"\n4. TESTING ENHANCED PROCESSING")
        print("-" * 40)
        
        coordinator = EnhancedUpdateCoordinator(status_callback)
        result = coordinator.process_single_product_enhanced("815963", "SH-13-10-24", force_update=True)
        coordinator.close()
        
        print(f"\nProcessing result:")
        print(f"  Success: {result.success}")
        print(f"  Operation: {result.operation}")
        print(f"  Errors: {len(result.errors)}")
        
        if result.errors:
            print("  Error details:")
            for error in result.errors:
                print(f"    - {error}")
        
        # Check what changes were made
        if result.changes:
            print(f"  Changes made:")
            for change, made in result.changes.items():
                print(f"    {change}: {'✓' if made else '❌'}")
        
        # Check database state after processing
        print(f"\n5. DATABASE STATE CHECK")
        print("-" * 30)
        
        from enhanced_database_updater import EnhancedDatabaseUpdater
        db_updater = EnhancedDatabaseUpdater(status_callback)
        
        product = db_updater.get_product_by_sku("815963")
        if product:
            print(f"✓ Product in database: {product.get('name', 'N/A')}")
            print(f"  Product ID: {product.get('product_id')}")
            
            # Check ingredients in database
            results = db_updater._execute_query(
                "SELECT COUNT(*) as count FROM productingredients WHERE product_id = %s",
                (product['product_id'],),
                fetch=True
            )
            ingredient_count = results[0]['count'] if results else 0
            print(f"  Ingredients in database: {ingredient_count}")
            
            # Check photos in database
            results = db_updater._execute_query(
                "SELECT COUNT(*) as count FROM productphotos WHERE product_id = %s",
                (product['product_id'],),
                fetch=True
            )
            photo_count = results[0]['count'] if results else 0
            print(f"  Photos in database: {photo_count}")
            
            if photo_count == 0:
                print("  ❌ No photos saved to database")
            
            if ingredient_count == 0:
                print("  ❌ No ingredients saved to database")
        
        db_updater.close()
        
    except Exception as e:
        print(f"Error during analysis: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        web_client.close()

if __name__ == "__main__":
    analyze_sku_815963()