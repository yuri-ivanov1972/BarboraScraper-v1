#!/usr/bin/env python3
"""
Category Analyzer - Read-only analysis of Rimi categories
Compares website data with existing database without making changes
"""
import requests
from bs4 import BeautifulSoup
import time
import random
from typing import Dict, List, Tuple, Optional
import logging
from database_integration import ExternalDatabaseManager
import re
from dataclasses import dataclass

@dataclass
class ProductInfo:
    sku: str
    name: str
    price: Optional[str]
    url: str

class CategoryAnalyzer:
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda x: None)
        self.ext_db = ExternalDatabaseManager()
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
        # Clean category code
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
            
            # Look for pagination information
            pagination_elements = soup.find_all(['a', 'span'], class_=re.compile(r'page|pagination'))
            
            max_page = 1
            total_products = 0
            
            # Try to find pagination links
            for element in pagination_elements:
                text = element.get_text(strip=True)
                if text.isdigit():
                    page_num = int(text)
                    max_page = max(max_page, page_num)
            
            # Also check for "Show X of Y products" type text
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
            
            # If we found pagination but no total, estimate from pages
            if max_page > 1 and total_products == 0:
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
    
    def get_database_products_for_category(self, category_code: str) -> List[Dict]:
        """Get products from database for specific category (read-only)"""
        try:
            self.status_callback(f"Querying database for category {category_code}")
            
            # Get all products from external database
            existing_products = self.ext_db.get_existing_products()
            
            # Get categories to find category_id for the code
            categories = self.ext_db.get_all_categories()
            
            # Find matching category
            category_id = None
            for cat in categories:
                if cat.rimi_category_code == category_code:
                    category_id = cat.category_id
                    break
            
            if not category_id:
                self.status_callback(f"Category {category_code} not found in database")
                return []
            
            # Filter products by category
            category_products = []
            for sku, product in existing_products.items():
                if product.category_id == category_id:
                    category_products.append({
                        'sku': product.sku,
                        'name': product.name,
                        'url': product.rimi_url,
                        'category_id': product.category_id
                    })
            
            self.status_callback(f"Found {len(category_products)} products in database for category {category_code}")
            return category_products
            
        except Exception as e:
            self.status_callback(f"Error querying database: {str(e)}")
            return []
    
    def analyze_category(self, category_code: str, sample_pages: int = 2) -> Dict:
        """Analyze a category comparing website vs database"""
        
        analysis_result = {
            'category_code': category_code,
            'category_url': '',
            'website_total_products': 0,
            'website_total_pages': 0,
            'website_sample_products': [],
            'database_products': [],
            'comparison': {
                'total_on_website': 0,
                'total_in_database': 0,
                'sampled_from_website': 0,
                'common_skus': [],
                'only_on_website': [],
                'only_in_database': []
            },
            'status': 'success',
            'errors': []
        }
        
        try:
            # Build category URL
            category_url = self.build_category_url(category_code)
            analysis_result['category_url'] = category_url
            
            # Get total products from pagination
            total_products, total_pages = self.get_total_products_from_pagination(category_url)
            analysis_result['website_total_products'] = total_products
            analysis_result['website_total_pages'] = total_pages
            
            if total_products == 0:
                analysis_result['status'] = 'error'
                analysis_result['errors'].append('No products found on website')
                return analysis_result
            
            # Sample products from first few pages
            website_products = []
            pages_to_sample = min(sample_pages, total_pages)
            
            for page_num in range(1, pages_to_sample + 1):
                page_url = f"{category_url}?pageSize=20&currentPage={page_num}"
                page_products = self.extract_products_from_page(page_url)
                website_products.extend(page_products)
                
                # Small delay between pages
                time.sleep(random.uniform(0.5, 1.5))
            
            analysis_result['website_sample_products'] = [
                {
                    'sku': p.sku,
                    'name': p.name,
                    'price': p.price,
                    'url': p.url
                } for p in website_products
            ]
            
            # Get database products for category
            database_products = self.get_database_products_for_category(category_code)
            analysis_result['database_products'] = database_products
            
            # Compare results
            website_skus = set([p.sku for p in website_products])
            database_skus = set([p['sku'] for p in database_products])
            
            common_skus = website_skus & database_skus
            only_website = website_skus - database_skus
            only_database = database_skus - website_skus
            
            analysis_result['comparison'] = {
                'total_on_website': total_products,
                'total_in_database': len(database_products),
                'sampled_from_website': len(website_products),
                'common_skus': list(common_skus),
                'only_on_website': list(only_website),
                'only_in_database': list(only_database),
                'coverage_percentage': round(len(database_skus) / total_products * 100, 2) if total_products > 0 else 0
            }
            
            self.status_callback("Category analysis completed successfully")
            return analysis_result
            
        except Exception as e:
            analysis_result['status'] = 'error'
            analysis_result['errors'].append(str(e))
            self.status_callback(f"Analysis failed: {str(e)}")
            return analysis_result

if __name__ == "__main__":
    def test_callback(msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}")
    
    analyzer = CategoryAnalyzer(test_callback)
    result = analyzer.analyze_category("SH-11", sample_pages=1)
    
    print("\n=== ANALYSIS RESULTS ===")
    print(f"Category: {result['category_code']}")
    print(f"Website total products: {result['website_total_products']}")
    print(f"Database total products: {result['comparison']['total_in_database']}")
    print(f"Coverage: {result['comparison']['coverage_percentage']}%")