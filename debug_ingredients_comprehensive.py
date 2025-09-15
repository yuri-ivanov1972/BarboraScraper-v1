#!/usr/bin/env python3
"""
Comprehensive debug script for ingredients extraction to ensure we don't miss "Sastāvdaļas" sections
"""
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from robust_web_client import RobustWebClient
from bs4 import BeautifulSoup
import re

def debug_ingredients_extraction(sku: str):
    """Comprehensive debugging of ingredients extraction for any SKU"""
    
    print(f"=== COMPREHENSIVE INGREDIENTS DEBUG FOR SKU {sku} ===\n")
    
    # Initialize the web client
    def status_callback(message):
        print(f"[STATUS] {message}")
    
    client = RobustWebClient(status_callback)
    
    # Get product data
    print("1. FETCHING PRODUCT DATA...")
    product_data = client.get_product_data(sku)
    
    if not product_data:
        print("❌ Failed to fetch product data")
        return
    
    print(f"✅ Product found: {product_data['name']}")
    soup = product_data.get('soup')
    
    if not soup:
        print("❌ No HTML content available")
        return
    
    # Test the current extraction method
    print("\n2. TESTING CURRENT EXTRACTION METHOD...")
    nutrition_data = client.extract_nutrition_data(soup, product_data['url'])
    print(f"Current method result: '{nutrition_data.get('ingredients', '')}'")
    print(f"Has nutrition data: {nutrition_data.get('has_nutrition', False)}")
    
    # Comprehensive manual search
    print("\n3. COMPREHENSIVE MANUAL SEARCH...")
    
    # Search entire page text for ingredients keywords
    page_text = soup.get_text()
    ingredients_keywords = ['sastāvdaļas', 'ingredients', 'sastāvs', 'Sastāvdaļas', 'Ingredients', 'SASTĀVDAĻAS']
    
    print("   A. Searching in full page text...")
    found_contexts = []
    for keyword in ingredients_keywords:
        if keyword in page_text:
            print(f"   ✅ Found '{keyword}' in page text")
            # Find all contexts where this keyword appears
            start_pos = 0
            while True:
                pos = page_text.find(keyword, start_pos)
                if pos == -1:
                    break
                context_start = max(0, pos - 100)
                context_end = min(len(page_text), pos + 300)
                context = page_text[context_start:context_end]
                found_contexts.append({
                    'keyword': keyword,
                    'position': pos,
                    'context': context.strip().replace('\n', ' ').replace('\t', ' ')
                })
                start_pos = pos + 1
    
    if found_contexts:
        print(f"   📍 Found {len(found_contexts)} occurrences of ingredients keywords:")
        for i, ctx in enumerate(found_contexts):
            print(f"   {i+1}. '{ctx['keyword']}' at position {ctx['position']}:")
            print(f"      ...{ctx['context'][:200]}...")
            print()
    
    # Search in script tags specifically
    print("   B. Searching in script tags...")
    script_found = False
    for i, script in enumerate(soup.find_all('script')):
        if script.string:
            script_content = script.string
            if any(keyword in script_content for keyword in ingredients_keywords):
                print(f"   ✅ Found ingredients keywords in script tag {i}")
                script_found = True
                
                # Look for Storefront.product_details_page
                if 'Storefront.product_details_page' in script_content:
                    print("      ✅ This is the product details script")
                    
                    # Try to extract the tabs structure
                    tabs_match = re.search(r'tabs:\s*(\[.*?\])', script_content, re.DOTALL)
                    if tabs_match:
                        print("      ✅ Found tabs structure")
                        tabs_content = tabs_match.group(1)
                        
                        # Look for details tab
                        if 'details' in tabs_content:
                            print("      ✅ Found details tab")
                            
                            # Extract details HTML more carefully
                            details_pattern = r'identifier:\s*["\']details["\']\s*,\s*[^}]*?html:\s*["\']([^"\']*?)["\']'
                            details_match = re.search(details_pattern, script_content, re.DOTALL)
                            
                            if details_match:
                                details_html = details_match.group(1)
                                print("      ✅ Extracted raw details HTML")
                                
                                # Decode escaped HTML carefully
                                details_html = details_html.replace('\\/', '/')
                                details_html = details_html.replace('\\"', '"')
                                details_html = details_html.replace('\\n', '\n')
                                details_html = details_html.replace('\\t', '\t')
                                details_html = details_html.replace('\\r', '\r')
                                
                                print(f"      📄 Details HTML length: {len(details_html)} characters")
                                print(f"      📝 First 200 chars: {details_html[:200]}")
                                
                                # Parse with BeautifulSoup
                                try:
                                    details_soup = BeautifulSoup(details_html, 'html.parser')
                                    print("      ✅ Successfully parsed details HTML")
                                    
                                    # Look for ingredients in the parsed HTML
                                    analyze_details_html(details_soup, ingredients_keywords)
                                    
                                except Exception as e:
                                    print(f"      ❌ Error parsing details HTML: {str(e)}")
                            else:
                                print("      ❌ Could not extract details HTML content")
                        else:
                            print("      ❌ No details tab found in tabs structure")
                    else:
                        print("      ❌ No tabs structure found")
    
    if not script_found:
        print("   ❌ No ingredients keywords found in any script tags")
    
    # Search in regular HTML elements
    print("   C. Searching in HTML structure...")
    
    # Look for any elements containing ingredients keywords
    elements_found = []
    for tag_name in ['div', 'span', 'p', 'li', 'td', 'th', 'section', 'article']:
        elements = soup.find_all(tag_name)
        for element in elements:
            element_text = element.get_text(strip=True)
            if any(keyword.lower() in element_text.lower() for keyword in ingredients_keywords):
                elements_found.append({
                    'tag': tag_name,
                    'text': element_text[:200],
                    'classes': element.get('class', []),
                    'element': element
                })
    
    if elements_found:
        print(f"   ✅ Found {len(elements_found)} HTML elements with ingredients keywords:")
        for i, elem in enumerate(elements_found):
            print(f"   {i+1}. <{elem['tag']} class='{elem['classes']}'>:")
            print(f"      Text: {elem['text']}")
            
            # If this looks like it might contain actual ingredients, analyze further
            if len(elem['text']) > 20:
                analyze_potential_ingredients_element(elem['element'], i+1)
            print()
    else:
        print("   ❌ No HTML elements found with ingredients keywords")

def analyze_details_html(details_soup: BeautifulSoup, keywords):
    """Analyze the details HTML for ingredients"""
    print("         📋 ANALYZING DETAILS HTML STRUCTURE:")
    
    # Look for list items
    items = details_soup.find_all('li', class_='item')
    print(f"         Found {len(items)} items in details")
    
    for j, item in enumerate(items):
        span = item.find('span')
        if span:
            span_text = span.get_text(strip=True)
            print(f"         Item {j+1} label: '{span_text}'")
            
            if any(keyword.lower() in span_text.lower() for keyword in keywords):
                print(f"         ⭐ INGREDIENTS ITEM FOUND!")
                
                # Look for the content
                text_div = item.find('div', class_='text')
                if text_div:
                    if text_div.p:
                        content = text_div.p.get_text(strip=True)
                        print(f"         📝 Ingredients content: {content}")
                    else:
                        content = text_div.get_text(strip=True)
                        print(f"         📝 Ingredients content (div): {content}")
                else:
                    print(f"         ❌ No text content found in ingredients item")

def analyze_potential_ingredients_element(element, index):
    """Analyze an HTML element that might contain ingredients"""
    print(f"      🔍 Analyzing element {index} structure:")
    
    # Check if it has child elements that might contain ingredient content
    children = element.find_all(['p', 'div', 'span'])
    for i, child in enumerate(children[:3]):  # Limit to first 3 children
        child_text = child.get_text(strip=True)
        if len(child_text) > 10:
            print(f"         Child {i+1} ({child.name}): {child_text[:100]}...")

if __name__ == "__main__":
    # Test with SKU 816707 (eggs)
    debug_ingredients_extraction("816707")
    
    print("\n" + "="*80)
    print("TESTING WITH ANOTHER PRODUCT THAT LIKELY HAS REAL INGREDIENTS")
    print("="*80)
    
    # Test with a product that likely has ingredients (for example, bread or processed food)
    debug_ingredients_extraction("4005900")  # This was mentioned earlier as another product