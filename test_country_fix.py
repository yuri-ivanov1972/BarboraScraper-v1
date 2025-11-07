#!/usr/bin/env python3
"""
Test script to debug country of origin extraction issue
Tests both old and new HTML decoding methods
"""
import requests
from bs4 import BeautifulSoup
import re
import json

def test_product_country(sku):
    """Test country extraction for a specific SKU"""
    print(f"\n{'='*70}")
    print(f"Testing SKU: {sku}")
    print('='*70)
    
    url = f"https://www.rimi.lv/e-veikals/lv/produkti/p/{sku}"
    
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the product details script
        script_tag = None
        for script in soup.find_all('script'):
            if script.string and 'Storefront.product_details_page' in script.string:
                script_tag = script
                break
        
        if not script_tag or not script_tag.string:
            print("✗ No product details script found")
            return False
        
        script_content = script_tag.string
        print("✓ Found product details script")
        
        # Test OLD regex pattern
        print("\n--- Testing OLD pattern ---")
        old_pattern = r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']'
        old_match = re.search(old_pattern, script_content, re.DOTALL)
        
        if old_match:
            print(f"✓ OLD regex matched (captured {len(old_match.group(1))} chars)")
            old_html = old_match.group(1)
            print(f"  First 100 chars: {old_html[:100]}")
            
            # Try old decoding
            old_decoded = old_html.replace('\\/', '/').replace('\\"', '"')
            old_decoded = old_decoded.replace('\\n', '\n').replace('\\t', '\t')
            try:
                old_decoded = old_decoded.encode('utf-8').decode('unicode_escape')
                print("  ✓ Unicode escape decoding succeeded")
            except Exception as e:
                print(f"  ✗ Unicode escape decoding failed: {e}")
            
            old_soup = BeautifulSoup(old_decoded, 'html.parser')
            old_country = extract_country(old_soup, "OLD")
        else:
            print("✗ OLD regex did NOT match")
            old_country = None
        
        # Test NEW regex pattern
        print("\n--- Testing NEW pattern ---")
        new_pattern = r'identifier:\s*["\']details["\'],[^}]*html:\s*"((?:[^"\\]|\\.)*)"'
        new_match = re.search(new_pattern, script_content, re.DOTALL)
        
        if new_match:
            print(f"✓ NEW regex matched (captured {len(new_match.group(1))} chars)")
            new_html = new_match.group(1)
            print(f"  First 100 chars: {new_html[:100]}")
            
            # Try JSON decoding
            try:
                new_decoded = json.loads(f'"{new_html}"')
                print(f"  ✓ JSON decoding succeeded (length: {len(new_decoded)})")
            except json.JSONDecodeError as e:
                print(f"  ✗ JSON decoding failed: {e}")
                # Fallback
                new_decoded = new_html.replace('\\/', '/').replace('\\"', '"')
                new_decoded = new_decoded.replace('\\n', '\n').replace('\\t', '\t')
            
            new_soup = BeautifulSoup(new_decoded, 'html.parser')
            new_country = extract_country(new_soup, "NEW")
        else:
            print("✗ NEW regex did NOT match")
            new_country = None
        
        # Summary
        print(f"\n--- RESULTS ---")
        print(f"OLD method country: {old_country or 'NOT FOUND'}")
        print(f"NEW method country: {new_country or 'NOT FOUND'}")
        
        return new_country is not None
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def extract_country(details_soup, label):
    """Extract country from parsed HTML"""
    country_keywords = ['Izcelsmes valsts', 'izcelsmes valsts', 'Country of origin']
    
    # Method 1: Look in list items
    for item in details_soup.find_all('li', class_='item'):
        span = item.find('span')
        if span:
            span_text = span.get_text(strip=True)
            text_div = item.find('div', class_='text')
            if text_div and text_div.p:
                content = text_div.p.get_text(strip=True)
                if any(keyword in span_text for keyword in country_keywords):
                    print(f"  ✅ {label}: Found country via Method 1: {content}")
                    return content
    
    # Method 2: Look in product list wrappers
    for section in details_soup.find_all('div', class_='product__list-wrapper'):
        heading = section.find('p', class_='heading')
        if heading:
            heading_text = heading.get_text(strip=True)
            if any(keyword in heading_text for keyword in country_keywords):
                text_divs = section.find_all('div', class_='text')
                for text_div in text_divs:
                    if text_div.p and text_div.p.get_text(strip=True):
                        content = text_div.p.get_text(strip=True)
                        print(f"  ✅ {label}: Found country via Method 2: {content}")
                        return content
    
    print(f"  ✗ {label}: Country NOT found")
    print(f"    Found {len(details_soup.find_all('li', class_='item'))} list items")
    return None


if __name__ == "__main__":
    # Test with known yogurt products from category SH-11-6-19
    test_skus = ["246017", "176623", "113951", "953461"]
    
    success_count = 0
    for sku in test_skus:
        if test_product_country(sku):
            success_count += 1
    
    print(f"\n\n{'='*70}")
    print(f"SUMMARY: {success_count}/{len(test_skus)} products successfully extracted country")
    print('='*70)
