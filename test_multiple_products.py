#!/usr/bin/env python3
"""
Test category extraction on multiple products to see patterns
"""

def test_multiple_products():
    """Test category extraction on different products"""
    print("=== Testing Multiple Products for Category Data ===")
    
    try:
        from robust_web_client import RobustWebClient
        
        def debug_callback(msg):
            # Suppress detailed logs for cleaner output
            if any(x in msg for x in ['✓', 'Found category', 'No category', 'RIMI code']):
                print(f"[RESULT] {msg}")
        
        client = RobustWebClient(debug_callback)
        
        # Test different products
        test_products = [
            "147762",  # Olive oil (we know this one has no category)
            "961367",  # Different product 
            "999409",  # Another product
            "4007406"  # Another test product
        ]
        
        results = []
        
        for sku in test_products:
            print(f"\n--- Testing SKU {sku} ---")
            
            try:
                # Get product data
                product_data = client.get_product_data(sku)
                if not product_data:
                    print(f"❌ {sku}: Failed to fetch product data")
                    continue
                
                print(f"✓ {sku}: {product_data.get('name', 'N/A')[:50]}...")
                
                # Extract nutrition data with category
                nutrition_data = client.extract_nutrition_data(product_data['soup'], product_data['url'])
                
                category_code = nutrition_data.get('category_code', '')
                category_path = nutrition_data.get('category_path_full', '')
                ingredients = nutrition_data.get('ingredients_text', '')
                
                result = {
                    'sku': sku,
                    'name': product_data.get('name', 'N/A'),
                    'has_category': bool(category_code),
                    'category_code': category_code,
                    'category_path': category_path[:60] + '...' if len(category_path) > 60 else category_path,
                    'has_ingredients': bool(ingredients)
                }
                
                results.append(result)
                
                if category_code:
                    print(f"  ✅ Category: {category_code}")
                    print(f"  📁 Path: {category_path[:60]}...")
                else:
                    print(f"  ❌ No category found")
                
                print(f"  🧪 Ingredients: {'✓' if ingredients else '❌'}")
                
            except Exception as e:
                print(f"❌ {sku}: Error - {str(e)}")
        
        # Summary
        print(f"\n=== SUMMARY ===")
        print(f"Products tested: {len(results)}")
        
        products_with_category = [r for r in results if r['has_category']]
        products_without_category = [r for r in results if not r['has_category']]
        
        print(f"✅ With category codes: {len(products_with_category)}")
        print(f"❌ Without category codes: {len(products_without_category)}")
        
        if products_with_category:
            print(f"\n📋 Products WITH categories:")
            for r in products_with_category:
                print(f"  {r['sku']}: {r['category_code']} - {r['name'][:40]}...")
        
        if products_without_category:
            print(f"\n📋 Products WITHOUT categories:")
            for r in products_without_category:
                print(f"  {r['sku']}: {r['name'][:40]}...")
        
        return results
        
    except Exception as e:
        print(f"❌ Error during multi-product test: {str(e)}")
        import traceback
        traceback.print_exc()
        return []

if __name__ == "__main__":
    results = test_multiple_products()
    
    if results:
        has_any_categories = any(r['has_category'] for r in results)
        if has_any_categories:
            print(f"\n🎯 CONCLUSION: Some products DO have category codes!")
            print(f"   Phase 1 category extraction works for products that include this data.")
        else:
            print(f"\n🔧 CONCLUSION: No category codes found in any test products.")
            print(f"   May need alternative extraction methods.")
    else:
        print(f"\n❌ No results to analyze.")