#!/usr/bin/env python3
"""Test availability and country of origin extraction for SKU 953461"""

from robust_web_client import RobustWebClient
from enhanced_update_coordinator import EnhancedUpdateCoordinator

def status_print(msg):
    print(f"[TEST] {msg}")

# Test availability extraction
print("="*60)
print("Testing SKU 953461 - Should be UNAVAILABLE")
print("="*60)

# Create web client and fetch product
client = RobustWebClient(status_print)
product_data = client.get_product_data("953461")

if product_data:
    print(f"\n✓ Product found: {product_data['name']}")
    print(f"✓ is_available: {product_data.get('is_available')}")
    print(f"✓ Price: {product_data.get('price')}")
    
    # Extract nutrition data (includes country of origin)
    nutrition_data = client.extract_nutrition_data(product_data['soup'], product_data['url'])
    print(f"\n✓ Country of origin: {nutrition_data.get('country_of_origin', 'Not found')}")
    
    # Verify expected results
    print("\n" + "="*60)
    print("VERIFICATION:")
    print("="*60)
    if product_data.get('is_available') == False:
        print("✅ PASS: Availability correctly detected as FALSE")
    else:
        print("❌ FAIL: Availability should be FALSE but got:", product_data.get('is_available'))
    
    if nutrition_data.get('country_of_origin') != 'Unknown':
        print(f"✅ PASS: Country of origin extracted: {nutrition_data.get('country_of_origin')}")
    else:
        print("⚠️  INFO: Country of origin not found (may be normal for this product)")
else:
    print("❌ Failed to fetch product data")

client.close()
