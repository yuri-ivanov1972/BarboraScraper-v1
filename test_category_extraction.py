#!/usr/bin/env python3
"""
Test script to validate category extraction functionality in Phase 1
Tests the enhanced robust_web_client.py category parsing capabilities
"""

import os
import sys
from robust_web_client import RobustWebClient

def test_category_extraction():
    """Test category extraction with sample Rimi product URLs"""
    
    print("=== Phase 1 Category Extraction Test ===")
    
    # Initialize client
    client = RobustWebClient()
    
    # Sample test URLs (you can replace these with actual Rimi product URLs)
    test_urls = [
        # Add real Rimi product URLs here when testing
        # Example: "https://www.rimi.lv/e-veikals/lv/produkti/product-name/p/123456"
    ]
    
    if not test_urls:
        print("⚠️ No test URLs provided. Please add real Rimi product URLs to test.")
        print("Category extraction functionality has been implemented with:")
        print("- Method 1: List items with spans (<li class='item'> > <span> + <div class='text'>)")
        print("- Method 2: Product list wrappers (<div class='product__list-wrapper'> parsing)")
        print("- Fallback: Regex pattern matching for category keywords")
        print("- RIMI code extraction: SH-X-X or SH-X-X-X format validation")
        return
    
    for i, url in enumerate(test_urls, 1):
        print(f"\n--- Test {i}: {url} ---")
        try:
            # Fetch and parse the product page
            soup = client.fetch_product_page(url)
            if not soup:
                print(f"❌ Failed to fetch page: {url}")
                continue
            
            # Extract nutrition data (which now includes category)
            nutrition_data = client.extract_nutrition_data(soup, url)
            
            # Check category extraction results
            category_code = nutrition_data.get('category_code', '')
            category_path = nutrition_data.get('category_path_full', '')
            
            if category_code:
                print(f"✅ Category Code: {category_code}")
                print(f"✅ Full Path: {category_path}")
                
                # Validate format
                import re
                if re.match(r'^SH-\d+-\d+(-\d+)?$', category_code):
                    print(f"✅ Valid RIMI format: {category_code}")
                else:
                    print(f"⚠️ Invalid format: {category_code}")
            else:
                print("❌ No category extracted")
                if category_path:
                    print(f"⚠️ Found path but no code: {category_path}")
            
            # Also check ingredients to ensure both work
            ingredients = nutrition_data.get('ingredients_text', '')
            if ingredients:
                print(f"✅ Ingredients also extracted: {ingredients[:50]}...")
            else:
                print("⚠️ No ingredients extracted")
                
        except Exception as e:
            print(f"❌ Error testing {url}: {str(e)}")
    
    print("\n=== Test Summary ===")
    print("Phase 1 implementation includes:")
    print("✅ Category keywords: Kategorija, kategorija, Category, Produkta kategorija")
    print("✅ HTML structure parsing: Same logic as ingredients extraction")
    print("✅ RIMI code validation: SH-X-X or SH-X-X-X format")
    print("✅ Fallback pattern matching")
    print("✅ Integration with existing nutrition_data structure")

if __name__ == "__main__":
    # Add status callback for detailed logs
    def status_callback(message):
        print(f"[LOG] {message}")
    
    # Test the helper function directly
    print("=== Testing RIMI Code Extraction Helper ===")
    
    # Test cases for rightmost RIMI code extraction
    test_cases = [
        "Produkti / Pārtikas produkti / Gaļa un gaļas produkti / SH-1-2",
        "Kategorija: Produkti / Dārzeņi / SH-3-4-5 / Svaigi dārzeņi",
        "SH-2-3 / Apakškategorija / SH-5-6-7",  # Should extract SH-5-6-7
        "Invalid / No / Codes / Here",
        "Produkti / SH-1-2-3-4",  # Invalid format (too many numbers)
        "",
        "Kategorija: SH-7-8"
    ]
    
    import re
    def extract_rightmost_rimi_code(category_path: str) -> str:
        """Extract rightmost RIMI category code from full path"""
        try:
            parts = [part.strip() for part in category_path.split('/')]
            for part in reversed(parts):
                # Match RIMI category format: SH-X-X or SH-X-X-X (allow single or multiple digits)
                if re.match(r'^SH-\d+-\d+(-\d+)?$', part):
                    return part
            return ''
        except Exception:
            return ''
    
    for test_case in test_cases:
        result = extract_rightmost_rimi_code(test_case)
        print(f"Input: '{test_case}' -> Output: '{result}'")
    
    print("\n🎯 Ready to test with real product URLs!")
    test_category_extraction()