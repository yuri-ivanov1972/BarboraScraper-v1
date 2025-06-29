"""
Debug Nutrition Parsing - Show what labels are actually found on product pages
"""
import requests
import re
from bs4 import BeautifulSoup

def debug_nutrition_labels(product_url: str):
    """Debug what nutrition labels are actually found on a product page"""
    
    print(f"=== Debugging nutrition labels for: {product_url} ===")
    
    # Create session with proper headers
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'lv,en-US;q=0.7,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    })
    
    response = session.get(product_url)
    if response.status_code != 200:
        print(f"Failed to fetch product page: {response.status_code}")
        return
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Find product details script
    script_tag = None
    for script in soup.find_all('script'):
        if script.string and 'Storefront.product_details_page' in script.string:
            script_tag = script
            break
    
    if not script_tag:
        print("No product details script found")
        return
    
    script_content = script_tag.string
    print("Found product details script")
    
    # Extract the details tab HTML content
    try:
        details_match = re.search(
            r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']',
            script_content, re.DOTALL)
        
        if not details_match:
            details_match = re.search(
                r'html:\s*["\']([^"\']+)["\'].*?identifier:\s*["\']details["\']',
                script_content, re.DOTALL)
        
        if not details_match:
            print("Could not find details HTML content in script")
            return
        
        html_content = details_match.group(1)
        
        # Handle escaped characters
        html_content = html_content.encode().decode('unicode-escape')
        html_content = html_content.replace('\\/', '/')
        html_content = html_content.replace('\\"', '"')
        
        details_soup = BeautifulSoup(html_content, 'html.parser')
        
        print("\n=== RAW DETAILS HTML ===")
        print(html_content[:500])
        print("...\n")
        
        # Find all tables and examine their contents
        tables = details_soup.find_all('table')
        print(f"Found {len(tables)} tables in details")
        
        for i, table in enumerate(tables):
            print(f"\n--- Table {i+1} ---")
            
            # Check table headers
            headers = table.find_all('th')
            print(f"Headers: {[h.get_text(strip=True) for h in headers]}")
            
            # Check if this looks like a nutrition table
            has_nutrition_header = any('Uzturvērtība' in header.get_text(strip=True) for header in headers)
            print(f"Has nutrition header: {has_nutrition_header}")
            
            # Show all rows
            rows = table.find_all('tr')
            for j, row in enumerate(rows):
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True)
                    value = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    print(f"  Row {j}: '{label}' = '{value}'")
        
        # Also look for ingredients
        print(f"\n=== INGREDIENTS SEARCH ===")
        for section in details_soup.find_all('div', class_='product__list-wrapper'):
            heading = section.find('p', class_='heading')
            if heading:
                heading_text = heading.get_text(strip=True)
                print(f"Found section heading: '{heading_text}'")
                
                if 'Sastāvdaļas' in heading_text:
                    text_div = section.find('div', class_='text')
                    if text_div and text_div.p:
                        ingredients = text_div.p.get_text(strip=True)
                        print(f"Found ingredients: {ingredients[:100]}...")
    
    except Exception as e:
        print(f"Error processing product details: {str(e)}")

if __name__ == "__main__":
    # Test with the problematic product
    product_url = "https://www.rimi.lv/e-veikals/lv/produkti/p/4007406"
    debug_nutrition_labels(product_url)