#!/usr/bin/env python3
"""
Test SKU 816707 ingredient extraction after fixing Method 2
"""

def test_extraction():
    print("Testing SKU 816707 ingredient extraction...")
    
    try:
        from robust_web_client import RobustWebClient
        
        # Initialize client
        client = RobustWebClient(lambda msg: print(f"Status: {msg}"))
        
        # Test extraction
        print("Extracting basic product data...")
        result = client.get_product_data("816707")
        
        if result:
            print(f"✅ Basic extraction completed!")
            print(f"Product name: {result.get('name', 'N/A')}")
            print(f"Price: {result.get('price', 'N/A')}")
            print(f"Photos: {len(result.get('photos', []))} found")
            
            # Now extract nutrition data including ingredients
            soup = result.get('soup')
            if soup:
                print("\nExtracting nutrition data including ingredients...")
                nutrition_data = client.extract_nutrition_data(soup, result.get('url', ''))
                ingredients = nutrition_data.get('ingredients', '')
                
                print(f"Ingredients found: {'Yes' if ingredients else 'No'}")
                
                if ingredients:
                    print(f"Ingredients content: {ingredients[:200]}...")
                    print("\n🎯 SUCCESS: Method 2 fix worked! Ingredients were extracted.")
                    return True
                else:
                    print("❌ FAILED: No ingredients extracted despite fix")
                    return False
            else:
                print("❌ No soup object available for nutrition extraction")
                return False
        else:
            print("❌ FAILED: Could not extract product data")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")

if __name__ == "__main__":
    test_extraction()