#!/usr/bin/env python3
"""
Price Parsing Code Examples - Shows how product prices are extracted from Rimi website
"""
import json
import re
from bs4 import BeautifulSoup

def extract_product_price_method_1(element):
    """
    Method 1: Extract price from JSON data attribute (Most Reliable)
    
    Rimi stores structured product data in 'data-gtm-eec-product' attribute
    containing accurate price information for analytics tracking.
    """
    price = ""
    gtm_data = element.get('data-gtm-eec-product')
    if gtm_data:
        try:
            product_data = json.loads(gtm_data)
            if 'price' in product_data:
                price = f"€{product_data['price']}"
                print(f"Method 1 - JSON data: {price}")
                return price
        except json.JSONDecodeError:
            print("Method 1 - JSON parsing failed")
            pass
    return price

def extract_product_price_method_2(element):
    """
    Method 2: Extract price from HTML structure (Fallback)
    
    Parses the visual price display which is split into main price
    and decimal parts (e.g., <span>3</span><sup>49</sup> = €3.49)
    """
    price = ""
    price_tag = element.select_one('.price-tag')
    if price_tag:
        # Extract main price and decimal parts
        price_parts = []
        
        # Get main price part (e.g., "3")
        main_span = price_tag.find('span')
        if main_span:
            price_parts.append(main_span.get_text(strip=True))
        
        # Get decimal part (e.g., "49")
        sup_elem = price_tag.find('sup')
        if sup_elem:
            price_parts.append(sup_elem.get_text(strip=True))
        
        # Combine parts
        if len(price_parts) >= 2:
            price = f"€{price_parts[0]}.{price_parts[1]}"
            print(f"Method 2 - HTML structure: {price}")
        elif len(price_parts) == 1:
            price = f"€{price_parts[0]}"
            print(f"Method 2 - Single part: {price}")
    
    return price

def extract_product_price_method_3(element):
    """
    Method 3: Simple text extraction (Last Resort)
    
    Searches for any element containing "price" in class name
    and extracts its text content.
    """
    price = ""
    price_elem = element.select_one('[class*="price"]')
    if price_elem:
        price = price_elem.get_text(strip=True)
        print(f"Method 3 - Simple text: {price}")
    
    return price

def extract_product_price_complete(element):
    """
    Complete price extraction logic used in the system
    
    Tries multiple methods in order of reliability:
    1. HTML price structure parsing (most accurate - prioritized due to JSON data discrepancies)
    2. JSON data attribute (fallback)
    3. Simple text extraction fallback
    """
    print("--- Price Extraction Process ---")
    
    # Method 1: HTML structure parsing (most reliable)
    price = extract_product_price_method_2(element)
    if price:
        return price
    
    # Method 2: JSON data attribute (fallback due to potential inaccuracies)
    price = extract_product_price_method_1(element)
    if price:
        return price
    
    # Method 3: Simple fallback
    price = extract_product_price_method_3(element)
    if price:
        return price
    
    print("No price found with any method")
    return ""

# Example HTML structures that the system handles
example_html_structures = {
    "json_data": '''
    <div data-gtm-eec-product='{"price": "3.49", "name": "Product Name"}'>
        <h3>Product Name</h3>
        <div class="price-tag">€3.49</div>
    </div>
    ''',
    
    "split_price": '''
    <div class="product">
        <h3>Product Name</h3>
        <div class="price-tag">
            <span>3</span><sup>49</sup>
        </div>
    </div>
    ''',
    
    "simple_price": '''
    <div class="product">
        <h3>Product Name</h3>
        <div class="price">€2.99</div>
    </div>
    '''
}

if __name__ == "__main__":
    print("=== Product Price Extraction Examples ===\n")
    
    for structure_name, html in example_html_structures.items():
        print(f"Testing {structure_name}:")
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.find('div')
        
        price = extract_product_price_complete(element)
        print(f"Final result: {price}\n")