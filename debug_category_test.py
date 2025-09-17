#!/usr/bin/env python3
"""
Debug test for category extraction functionality
"""

def test_category_extraction():
    """Test the core category extraction functionality"""
    print("=== Debug Category Extraction ===")
    
    try:
        # Test 1: Initialize robust web client
        print("Test 1: Initializing robust web client...")
        from robust_web_client import RobustWebClient
        
        def debug_callback(msg):
            print(f"[WEB] {msg}")
        
        client = RobustWebClient(debug_callback)
        print("✓ Web client initialized")
        
        # Test 2: Try to get product data
        print("\nTest 2: Fetching product data...")
        test_sku = "147762"  # Known test SKU
        product_data = client.get_product_data(test_sku)
        
        if product_data:
            print(f"✓ Product data fetched for SKU {test_sku}")
            print(f"  URL: {product_data.get('url', 'N/A')}")
            print(f"  Name: {product_data.get('name', 'N/A')}")
            
            # Test 3: Extract nutrition data with category
            print("\nTest 3: Extracting nutrition data with category...")
            nutrition_data = client.extract_nutrition_data(product_data['soup'], product_data['url'])
            
            print(f"  Has nutrition: {nutrition_data.get('has_nutrition', False)}")
            print(f"  Ingredients: {nutrition_data.get('ingredients_text', 'N/A')[:50]}...")
            print(f"  Category code: {nutrition_data.get('category_code', 'N/A')}")
            print(f"  Category path: {nutrition_data.get('category_path_full', 'N/A')}")
            
            if nutrition_data.get('category_code'):
                print("✓ Category extraction working!")
                return True
            else:
                print("❌ Category extraction failed - no category code found")
                return False
                
        else:
            print(f"❌ Failed to fetch product data for SKU {test_sku}")
            return False
            
    except Exception as e:
        print(f"❌ Error during test: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def test_enhanced_coordinator():
    """Test the enhanced coordinator with automatic category"""
    print("\n=== Debug Enhanced Coordinator ===")
    
    try:
        from enhanced_update_coordinator import EnhancedUpdateCoordinator
        
        def debug_callback(msg):
            print(f"[COORD] {msg}")
        
        coordinator = EnhancedUpdateCoordinator(debug_callback)
        print("✓ Enhanced coordinator initialized")
        
        # Test the automatic category extraction method
        print("\nTesting automatic category extraction...")
        test_sku = "147762"
        result = coordinator.process_single_product_with_auto_category(test_sku)
        
        print(f"  Success: {result.success}")
        print(f"  Errors: {result.errors}")
        print(f"  Operation: {result.operation}")
        
        coordinator.close()
        return result.success
        
    except Exception as e:
        print(f"❌ Error during coordinator test: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Starting debug tests...\n")
    
    # Test core functionality
    web_client_works = test_category_extraction()
    
    # Test coordinator
    coordinator_works = test_enhanced_coordinator()
    
    print(f"\n=== Debug Results ===")
    print(f"Web client category extraction: {'✓ Working' if web_client_works else '❌ Failed'}")
    print(f"Enhanced coordinator: {'✓ Working' if coordinator_works else '❌ Failed'}")
    
    if web_client_works and coordinator_works:
        print("\n🎯 Phase 1 components are working correctly!")
    else:
        print("\n🔧 Issues found - check error messages above")