#!/usr/bin/env python3
"""
Core parsing functionality for Rimi website
- Category page parsing with pagination
- Product page parsing
- Database connections
"""
import requests
from bs4 import BeautifulSoup
import re
import time
import random
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import psycopg2
from psycopg2.extras import RealDictCursor
import os

@dataclass
class ProductInfo:
    sku: str
    name: str
    price: Optional[str]
    url: str

class RimiParser:
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda x: None)
        self.session = self._create_session()
        
    def _create_session(self) -> requests.Session:
        """Create session with headers to mimic browser"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        return session
    
    def build_category_url(self, category_code: str) -> str:
        """Build Rimi category URL from category code"""
        category_code = category_code.strip().upper()
        if not category_code.startswith('SH-'):
            category_code = f"SH-{category_code}"
        return f"https://www.rimi.lv/e-veikals/lv/produkti/c/{category_code}"
    
    def get_total_products_from_pagination(self, category_url: str) -> Tuple[int, int]:
        """Get total products and pages using pagination"""
        try:
            self.status_callback(f"Fetching category page: {category_url}")
            response = self.session.get(category_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            max_page = 1
            total_products = 0
            
            # Method 1: Look for Rimi's specific pagination structure
            pagination_container = soup.find('div', class_='pagination')
            if pagination_container:
                # Find all page links with data-page attribute
                page_links = pagination_container.find_all('a', attrs={'data-page': True})
                if page_links:
                    page_numbers = []
                    for link in page_links:
                        page_num = link.get('data-page')
                        if page_num and page_num.isdigit():
                            page_numbers.append(int(page_num))
                    if page_numbers:
                        max_page = max(page_numbers)
                        self.status_callback(f"Found pagination with pages: {sorted(page_numbers)}")
            
            # Method 2: Fallback - look for any numeric pagination links
            if max_page == 1:
                pagination_links = soup.find_all('a', href=re.compile(r'currentPage=\d+'))
                for link in pagination_links:
                    href = link.get('href', '')
                    page_match = re.search(r'currentPage=(\d+)', href)
                    if page_match:
                        page_num = int(page_match.group(1))
                        max_page = max(max_page, page_num)
            
            # Method 3: Look for numeric text in pagination elements
            if max_page == 1:
                pagination_elements = soup.find_all(['a', 'span'], class_=re.compile(r'pagination'))
                for element in pagination_elements:
                    text = element.get_text(strip=True)
                    if text.isdigit() and 1 <= int(text) <= 100:
                        page_num = int(text)
                        max_page = max(max_page, page_num)
            
            # Method 4: Check for product count patterns
            product_count_patterns = [
                r'(\d+)\s*produkti',  # Latvian
                r'(\d+)\s*products',  # English
                r'Rāda\s*\d+\s*no\s*(\d+)',  # "Showing X of Y"
                r'Showing\s*\d+\s*of\s*(\d+)'
            ]
            
            page_text = soup.get_text()
            for pattern in product_count_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    total_products = int(match.group(1))
                    break
            
            # Calculate total products from pages if not found directly
            if total_products == 0 and max_page > 1:
                # Rimi typically shows 20 products per page
                total_products = max_page * 20
            
            # Count products on current page if no other method worked
            if total_products == 0:
                product_elements = soup.find_all(['div', 'article'], class_=re.compile(r'product|item'))
                total_products = len(product_elements)
                if max_page > 1:
                    total_products = total_products * max_page
            
            self.status_callback(f"Found {max_page} pages, estimated {total_products} products")
            return total_products, max_page
            
        except Exception as e:
            self.status_callback(f"Error getting pagination info: {str(e)}")
            return 0, 0
    
    def extract_products_from_page(self, page_url: str, max_products: int = 20) -> List[ProductInfo]:
        """Extract product information from a single page"""
        products = []
        
        try:
            self.status_callback(f"Fetching products from: {page_url}")
            response = self.session.get(page_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for product containers
            product_selectors = [
                'div[class*="product"]',
                'article[class*="product"]',
                'div[class*="item"]',
                '[data-testid*="product"]'
            ]
            
            product_elements = []
            for selector in product_selectors:
                elements = soup.select(selector)
                if elements:
                    product_elements = elements[:max_products]
                    break
            
            for element in product_elements:
                try:
                    # Extract SKU from URL or data attributes
                    sku = None
                    link = element.find('a', href=True)
                    if link:
                        href = link['href']
                        # Extract SKU from URL pattern like /p/123456
                        sku_match = re.search(r'/p/(\d+)', href)
                        if sku_match:
                            sku = sku_match.group(1)
                        
                        # Build full URL if relative
                        if href.startswith('/'):
                            product_url = f"https://www.rimi.lv{href}"
                        else:
                            product_url = href
                    else:
                        product_url = ""
                    
                    # Extract product name
                    name_selectors = ['h3', 'h4', '[class*="title"]', '[class*="name"]']
                    name = ""
                    for selector in name_selectors:
                        name_elem = element.select_one(selector)
                        if name_elem:
                            name = name_elem.get_text(strip=True)
                            break
                    
                    # Extract price
                    price_selectors = ['[class*="price"]', '[data-testid*="price"]']
                    price = ""
                    for selector in price_selectors:
                        price_elem = element.select_one(selector)
                        if price_elem:
                            price = price_elem.get_text(strip=True)
                            break
                    
                    if sku and name:
                        products.append(ProductInfo(
                            sku=sku,
                            name=name,
                            price=price,
                            url=product_url
                        ))
                
                except Exception as e:
                    continue  # Skip problematic products
            
            self.status_callback(f"Extracted {len(products)} products from page")
            return products
            
        except Exception as e:
            self.status_callback(f"Error extracting products: {str(e)}")
            return []

class DatabaseConnection:
    """Simple database connection manager"""
    
    def __init__(self):
        self.categories_db_url = os.getenv('CATEGORIES_DB_URL')
        self.products_db_url = os.getenv('PRODUCTS_DB_URL')
        
        if not self.categories_db_url or not self.products_db_url:
            raise ValueError("CATEGORIES_DB_URL and PRODUCTS_DB_URL must be set")
    
    def get_categories(self) -> List[Dict]:
        """Get all categories from external database"""
        try:
            conn = psycopg2.connect(self.categories_db_url)
            conn.autocommit = True
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT category_code, category_name, category_name_eng
                    FROM categories 
                    WHERE category_code LIKE 'SH-%'
                    ORDER BY category_code;
                """)
                return cur.fetchall()
                
        except Exception as e:
            print(f"Error getting categories: {str(e)}")
            return []
        finally:
            if 'conn' in locals():
                conn.close()
    
    def get_products_for_category(self, category_code: str) -> List[Dict]:
        """Get products from external database for specific category"""
        try:
            # First get category_id
            categories = self.get_categories()
            # Check if the category exists
            category_found = False
            for cat in categories:
                if cat['category_code'].startswith(category_code):
                    category_found = True
                    break
            
            if not category_found:
                return []
            
            # Get products for this category
            conn = psycopg2.connect(self.products_db_url)
            conn.autocommit = True
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Search for products using multiple methods
                products = []
                
                # Method 1: Direct URL match
                cur.execute("""
                    SELECT product_id, sku, name, rimi_url, category_id,
                           quantity_value, quantity_unit, name_norm
                    FROM products 
                    WHERE rimi_url LIKE %s
                    ORDER BY name;
                """, (f'%/c/{category_code}%',))
                products.extend(cur.fetchall())
                
                # Method 2: If SH-11 (dairy), also search by URL pattern
                if category_code == 'SH-11':
                    cur.execute("""
                        SELECT product_id, sku, name, rimi_url, category_id,
                               quantity_value, quantity_unit, name_norm
                        FROM products 
                        WHERE rimi_url LIKE '%piena-produkti%' OR rimi_url LIKE '%dairy%'
                        ORDER BY name;
                    """)
                    products.extend(cur.fetchall())
                
                # Remove duplicates based on sku
                unique_products = {}
                for product in products:
                    if product['sku'] not in unique_products:
                        unique_products[product['sku']] = product
                
                return list(unique_products.values())
                return cur.fetchall()
                
        except Exception as e:
            print(f"Error getting products for category: {str(e)}")
            return []
        finally:
            if 'conn' in locals():
                conn.close()

if __name__ == "__main__":
    def test_callback(msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}")
    
    # Test the parser
    parser = RimiParser(test_callback)
    db = DatabaseConnection()
    
    category_code = "SH-11"
    category_url = parser.build_category_url(category_code)
    
    # Test pagination parsing
    total_products, total_pages = parser.get_total_products_from_pagination(category_url)
    print(f"Category {category_code}: {total_products} products, {total_pages} pages")
    
    # Test product extraction
    page_url = f"{category_url}?pageSize=20&currentPage=1"
    products = parser.extract_products_from_page(page_url)
    print(f"Extracted {len(products)} products from first page")
    
    # Test database connection
    categories = db.get_categories()
    print(f"Found {len(categories)} categories in database")
    
    db_products = db.get_products_for_category(category_code)
    print(f"Found {len(db_products)} products in database for {category_code}")