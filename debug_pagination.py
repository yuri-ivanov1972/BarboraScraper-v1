#!/usr/bin/env python3
"""
Debug script to show exactly when and where price detection happens
"""
import requests
from bs4 import BeautifulSoup
import re
import json

def demonstrate_price_extraction_timing():
    """Show exactly when price extraction occurs in the workflow"""
    
    print("=== Price Detection Timing Demo ===\n")
    
    # Example category page URL (with pagination)
    category_url = "https://www.rimi.lv/e-veikals/lv/produkti/c/SH-12-1-1?pageSize=20&currentPage=1"
    
    print("1. CATEGORY PAGE PARSING")
    print(f"   URL: {category_url}")
    print("   This page shows 20 or fewer products in a grid layout")
    print("   Each product has: name, price, SKU, and link")
    print()
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    try:
        response = session.get(category_url, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find product containers on the category page
        product_elements = soup.select('div[class*="product"]')
        
        print(f"2. PRODUCTS FOUND ON CATEGORY PAGE: {len(product_elements)}")
        print()
        
        for i, element in enumerate(product_elements[:3], 1):  # Show first 3
            print(f"   Product {i} extraction from category page:")
            
            # Extract SKU
            link = element.find('a', href=True)
            sku = "Not found"
            individual_url = ""
            if link:
                href = link['href']
                sku_match = re.search(r'/p/(\d+)', href)
                if sku_match:
                    sku = sku_match.group(1)
                if href.startswith('/'):
                    individual_url = f"https://www.rimi.lv{href}"
            
            # Extract name
            name = "Not found"
            for selector in ['h3', 'h4', '[class*="title"]']:
                name_elem = element.select_one(selector)
                if name_elem:
                    name = name_elem.get_text(strip=True)
                    break
            
            # Extract price FROM CATEGORY PAGE
            price = ""
            
            # Method 1: HTML structure
            price_tag = element.select_one('.price-tag')
            if price_tag:
                price_parts = []
                main_span = price_tag.find('span')
                if main_span:
                    price_parts.append(main_span.get_text(strip=True))
                
                sup_elem = price_tag.find('sup')
                if sup_elem:
                    price_parts.append(sup_elem.get_text(strip=True))
                
                if len(price_parts) >= 2:
                    price = f"€{price_parts[0]}.{price_parts[1]}"
                elif len(price_parts) == 1:
                    price = f"€{price_parts[0]}"
            
            # Method 2: JSON fallback
            if not price:
                gtm_data = element.get('data-gtm-eec-product')
                if gtm_data:
                    try:
                        product_data = json.loads(gtm_data)
                        if 'price' in product_data:
                            price = f"€{product_data['price']}"
                    except:
                        pass
            
            print(f"     SKU: {sku}")
            print(f"     Name: {name[:40]}...")
            print(f"     Price: {price} ← EXTRACTED FROM CATEGORY PAGE")
            print(f"     Individual URL: {individual_url[:60]}...")
            print("     ↑ This URL is stored but NOT visited for price extraction")
            print()
        
        print("3. KEY POINTS:")
        print("   ✓ Price is extracted during category page parsing")
        print("   ✓ System processes 20 products per page maximum")
        print("   ✓ Individual product pages are NOT visited for price data")
        print("   ✓ All product info (name, SKU, price, URL) comes from category grid")
        print("   ✓ For comparison, system fetches ALL category pages (respecting pagination)")
        print()
        print("4. WORKFLOW:")
        print("   Category URL → Parse 20 products → Extract prices → Next page")
        print("   Repeat until all pages processed")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    demonstrate_price_extraction_timing()