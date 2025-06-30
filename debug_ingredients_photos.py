"""
Debug ingredients and photos extraction for SKU 815963
"""
import requests
from bs4 import BeautifulSoup
import re

def debug_ingredient_photo_extraction():
    """Debug ingredient and photo extraction for SKU 815963"""
    
    print("=== DEBUGGING INGREDIENTS AND PHOTOS FOR SKU 815963 ===")
    
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
    
    url = "https://www.rimi.lv/e-veikals/lv/produkti/p/815963"
    print(f"Fetching: {url}")
    
    response = session.get(url)
    if response.status_code != 200:
        print(f"Failed to fetch: {response.status_code}")
        return
    
    soup = BeautifulSoup(response.text, 'html.parser')
    print("✓ Page fetched successfully")
    
    # 1. CHECK FOR PRODUCT IMAGES
    print("\n=== PRODUCT IMAGES ANALYSIS ===")
    
    # Look for various image selectors
    image_selectors = [
        'img[src*="product"]',
        'img[src*="rimi"]', 
        '.product-image img',
        '.product__image img',
        '[data-src]',
        'img[data-lazy]'
    ]
    
    all_images = []
    for selector in image_selectors:
        images = soup.select(selector)
        if images:
            print(f"Found {len(images)} images with selector: {selector}")
            for img in images:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy')
                if src and any(x in src for x in ['product', 'rimi', '.jpg', '.png', '.webp']):
                    all_images.append(src)
                    print(f"  Image: {src}")
    
    print(f"Total product images found: {len(set(all_images))}")
    
    # 2. FIND PRODUCT DETAILS SCRIPT
    print("\n=== PRODUCT DETAILS SCRIPT ANALYSIS ===")
    script_tag = None
    for script in soup.find_all('script'):
        if script.string and 'Storefront.product_details_page' in script.string:
            script_tag = script
            break
    
    if not script_tag:
        print("✗ No product details script found")
        return
    
    print("✓ Product details script found")
    script_content = script_tag.string
    
    # Extract the details tab HTML content
    details_match = re.search(
        r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']',
        script_content, re.DOTALL
    )
    
    if not details_match:
        print("✗ Could not extract details HTML from script")
        return
    
    print("✓ Details HTML extracted from script")
    
    # Decode the HTML content
    details_html = details_match.group(1)
    details_html = details_html.replace('\\/', '/').replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
    
    details_soup = BeautifulSoup(details_html, 'html.parser')
    
    # 3. ANALYZE INGREDIENTS SECTION
    print("\n=== INGREDIENTS ANALYSIS ===")
    
    # Look for ingredients with different selectors
    ingredient_patterns = [
        ('div.product__list-wrapper', 'Sastāvdaļas'),
        ('div.list-wrapper', 'Sastāvdaļas'),
        ('li.item', 'Sastāvdaļas'),
        ('section', 'Sastāvdaļas'),
        ('div', 'Sastāvdaļas')
    ]
    
    ingredients_found = False
    
    for selector, keyword in ingredient_patterns:
        sections = details_soup.select(selector)
        print(f"Checking {len(sections)} elements with selector: {selector}")
        
        for i, section in enumerate(sections):
            section_text = section.get_text()
            if keyword in section_text:
                print(f"  Found '{keyword}' in section {i+1}")
                print(f"  Section HTML: {str(section)[:200]}...")
                
                # Try different ways to extract ingredients text
                text_divs = section.find_all('div', class_='text')
                if text_divs:
                    for j, text_div in enumerate(text_divs):
                        if text_div.get_text(strip=True):
                            print(f"    Text div {j+1}: {text_div.get_text(strip=True)[:100]}...")
                            ingredients_found = True
                
                # Also check for direct text content
                text_content = section.get_text(strip=True)
                if len(text_content) > 20:  # Meaningful content
                    print(f"    Direct text: {text_content[:100]}...")
                    ingredients_found = True
    
    if not ingredients_found:
        print("❌ No ingredients found with any pattern")
        
        # Show all sections that might contain ingredients
        print("\nAll sections in details HTML:")
        for i, section in enumerate(details_soup.find_all(['div', 'li', 'section'])[:10]):
            text = section.get_text(strip=True)
            if len(text) > 10:
                print(f"  Section {i+1}: {text[:50]}...")
    
    # 4. LOOK FOR IMAGES IN SCRIPT
    print("\n=== IMAGES IN SCRIPT DATA ===")
    
    # Look for image URLs in the script content
    image_patterns = [
        r'"(https?://[^"]*\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r"'(https?://[^']*\.(?:jpg|jpeg|png|webp)[^']*)'",
        r'src["\']?\s*:\s*["\']([^"\']*\.(?:jpg|jpeg|png|webp)[^"\']*)["\']'
    ]
    
    script_images = []
    for pattern in image_patterns:
        matches = re.findall(pattern, script_content, re.IGNORECASE)
        script_images.extend(matches)
    
    product_images = [img for img in script_images if any(x in img.lower() for x in ['product', 'rimi', '815963'])]
    
    if product_images:
        print(f"Found {len(product_images)} product images in script:")
        for img in product_images[:5]:  # Show first 5
            print(f"  {img}")
    else:
        print("❌ No product images found in script data")
        print(f"Total images in script: {len(script_images)}")
        if script_images:
            print("Sample images:")
            for img in script_images[:3]:
                print(f"  {img}")

if __name__ == "__main__":
    debug_ingredient_photo_extraction()