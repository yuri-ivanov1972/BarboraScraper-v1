import trafilatura
from bs4 import BeautifulSoup
import requests
from decimal import Decimal, InvalidOperation
import logging
import re
import time
import random
from typing import List, Dict, Optional, Union, Callable

class ScraperError(Exception):
    """Custom exception for scraper-related errors"""
    pass

class RimiScraper:
    def __init__(self, status_callback: Optional[Callable[[str], None]] = None):
        self.base_url = "https://www.rimi.lv/e-veikals"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,lv;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Cookie': 'region=LV'
        }
        self.session = self._create_session()
        self.status_callback = status_callback or (lambda x: None)

    def _create_session(self) -> requests.Session:
        """Create a session with retry strategy"""
        try:
            session = requests.Session()
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update(self.headers)
            return session
        except Exception as e:
            raise ScraperError(f"Failed to create session: {str(e)}")

    def clean_price(self, price_str: str) -> Decimal:
        """Clean and convert price string to Decimal"""
        try:
            if not price_str:
                return Decimal('0.00')
            clean_price = price_str.replace('€', '').replace(',', '.').strip()
            return Decimal(clean_price)
        except (InvalidOperation, ValueError) as e:
            logging.error(f"Price conversion error for '{price_str}': {str(e)}")
            return Decimal('0.00')

    def extract_product_info(self, html_content: str, url: str) -> List[Dict[str, Union[str, Decimal]]]:
        """Extract product information from HTML content"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            products_list = []

            # Try different product grid selectors
            selectors = [
                'div.product-grid__item',
                'div.product-grid-item',
                'article.product-grid-item',
                'div[class*="product-"][class*="item"]',
                'div[class*="product-card"]'
            ]

            # Find all product containers
            products = []
            for selector in selectors:
                products = soup.select(selector)
                if products:
                    self.status_callback(f"Found {len(products)} products using selector: {selector}")
                    break

            if not products:
                self.status_callback(f"No products found in category {url}")
                return []

            for product in products:
                try:
                    # Extract name and URL with multiple selectors
                    name_selectors = [
                        'a[class*="name"]',
                        'a[class*="title"]',
                        'h3 a',
                        'div[class*="name"] a'
                    ]

                    name_elem = None
                    for selector in name_selectors:
                        name_elem = product.select_one(selector)
                        if name_elem:
                            break

                    if not name_elem:
                        continue

                    name = name_elem.get_text(strip=True)
                    product_url = name_elem.get('href', '')

                    if product_url and not product_url.startswith('http'):
                        product_url = f"https://www.rimi.lv{product_url}"

                    # Extract price with multiple selectors
                    price_selectors = [
                        'div[class*="price-tag"] span[class*="price"]',
                        'span[class*="price"]',
                        'div[class*="price"]'
                    ]

                    price_elem = None
                    for selector in price_selectors:
                        price_elem = product.select_one(selector)
                        if price_elem:
                            break

                    if not price_elem:
                        continue

                    price_text = price_elem.get_text(strip=True)
                    price = self.clean_price(price_text)

                    if price <= 0:
                        continue

                    # Extract additional information
                    unit_price = product.select_one('div[class*="unit-price"], span[class*="unit-price"]')
                    unit_price_text = unit_price.get_text(strip=True) if unit_price else None

                    # Extract SKU and category from URL
                    sku = None
                    if product_url:
                        sku_match = re.search(r'/p/(\d+)', product_url)
                        if sku_match:
                            sku = sku_match.group(1)

                    category = None
                    if product_url:
                        category_match = re.search(r'produkti/([^/]+(?:/[^/]+)?)', product_url)
                        if category_match:
                            category = category_match.group(1).replace('-', ' ').title()

                    products_list.append({
                        'name': name,
                        'price': price,
                        'price_per_unit': unit_price_text,
                        'product_url': product_url,
                        'sku': sku,
                        'category': category
                    })

                except Exception as e:
                    logging.error(f"Error processing product: {str(e)}")
                    continue

            return products_list

        except Exception as e:
            logging.error(f"Error parsing HTML content: {str(e)}")
            return []

    def scrape_products(self) -> List[Dict[str, Union[str, Decimal]]]:
        """Scrape product information from Rimi online store"""
        try:
            # Initialize session
            self.status_callback("Initializing scraper session...")
            initial_response = self.session.get(self.base_url)
            initial_response.raise_for_status()

            # Categories to try
            categories = [
                '/produkti/darzeni-un-augli',
                '/produkti/saldumi-un-uzkodas',
                '/produkti/dzerienu-nodala',
                '/produkti/maizes-nodala',
                '/produkti/piena-produkti-olas',
                '/produkti/gala-zivis-un-gatava-kulinarija'
            ]

            all_products = []
            for category in categories:
                try:
                    url = f"{self.base_url}{category}"
                    self.status_callback(f"Scraping category: {category}")

                    # Add random delay between requests
                    time.sleep(random.uniform(2, 4))

                    response = self.session.get(url)
                    if response.status_code != 200:
                        self.status_callback(f"Failed to access category {category}: {response.status_code}")
                        continue

                    # Try with trafilatura first
                    downloaded = trafilatura.fetch_url(url)
                    if downloaded:
                        html_content = trafilatura.extract(downloaded, include_html=True)
                        if html_content:
                            products = self.extract_product_info(html_content, url)
                            if products:
                                all_products.extend(products)
                                self.status_callback(f"Found {len(products)} products in category {category}")
                                continue

                    # Fallback to regular response content
                    self.status_callback(f"Trying alternative parsing for {category}")
                    products = self.extract_product_info(response.text, url)
                    if products:
                        all_products.extend(products)
                        self.status_callback(f"Found {len(products)} products in category {category}")

                except Exception as e:
                    logging.error(f"Error scraping category {category}: {str(e)}")
                    self.status_callback(f"Error in category {category}: {str(e)}")
                    continue

            if not all_products:
                raise ScraperError("No products found in any category. Please check if the website structure has changed.")

            self.status_callback(f"Successfully scraped {len(all_products)} products in total")
            return all_products

        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            raise ScraperError(str(e))