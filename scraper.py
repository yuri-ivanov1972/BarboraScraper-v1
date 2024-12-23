import trafilatura
from bs4 import BeautifulSoup
import requests
from decimal import Decimal, InvalidOperation
import logging
import re
import time
import random
from typing import List, Dict, Optional, Union
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class ScraperError(Exception):
    """Custom exception for scraper-related errors"""
    pass

class RimiScraper:
    def __init__(self):
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

    def extract_product_info(self, url: str) -> List[Dict[str, Union[str, Decimal]]]:
        """Extract product information using trafilatura"""
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                logging.error(f"Failed to fetch content from {url}")
                return []

            # Get both HTML and text content
            html_content = trafilatura.extract(downloaded, include_html=True)
            if not html_content:
                logging.error(f"No HTML content extracted from {url}")
                return []

            # Parse the HTML content
            soup = BeautifulSoup(html_content, 'html.parser')
            products_list = []

            # Find all product containers
            products = soup.find_all(['div', 'article'], 
                                   class_=lambda x: x and ('product' in x.lower() or 
                                                         'item' in x.lower()))

            for product in products:
                try:
                    # Extract name and URL
                    name_elem = product.find(['a', 'h3'], 
                                          class_=lambda x: x and ('name' in x.lower() or 
                                                                'title' in x.lower()))
                    if not name_elem:
                        continue

                    name = name_elem.get_text(strip=True)
                    product_url = name_elem.get('href', '')
                    if product_url and not product_url.startswith('http'):
                        product_url = f"https://www.rimi.lv{product_url}"

                    # Extract price
                    price_elem = product.find(['div', 'span'], 
                                           class_=lambda x: x and 'price' in x.lower())
                    if not price_elem:
                        continue

                    price_text = price_elem.get_text(strip=True)
                    price = self.clean_price(price_text)

                    # Skip if no valid price found
                    if price <= 0:
                        continue

                    # Extract price per unit
                    unit_elem = product.find(['div', 'span'], 
                                          class_=lambda x: x and ('unit' in x.lower() or 
                                                                'per' in x.lower()))
                    price_per_unit = unit_elem.get_text(strip=True) if unit_elem else None

                    # Extract SKU from URL
                    sku = None
                    if product_url:
                        sku_match = re.search(r'/p/(\d+)', product_url)
                        if sku_match:
                            sku = sku_match.group(1)

                    # Extract category from URL
                    category = None
                    if product_url:
                        category_match = re.search(r'produkti/([^/]+(?:/[^/]+)?)', product_url)
                        if category_match:
                            category = category_match.group(1).replace('-', ' ')

                    products_list.append({
                        'name': name,
                        'price': price,
                        'price_per_unit': price_per_unit,
                        'product_url': product_url,
                        'sku': sku,
                        'category': category
                    })

                except Exception as e:
                    logging.error(f"Error processing product: {str(e)}")
                    continue

            return products_list

        except Exception as e:
            logging.error(f"Error extracting product info: {str(e)}")
            return []

    def scrape_products(self) -> List[Dict[str, Union[str, Decimal]]]:
        """Scrape product information from Rimi online store"""
        try:
            # Categories to try
            categories = [
                '/produkti/augli-darzeni-un-ziedi/svaigie-augli',
                '/produkti/svaigi-produkti/augli-darzeni',
                '/produkti/dzeries/alus-un-sidri',
                '/produkti/saldumi-un-uzkodas'
            ]

            all_products = []
            for category in categories:
                try:
                    url = f"{self.base_url}{category}"
                    logging.info(f"Scraping category: {url}")

                    # Add random delay between requests
                    time.sleep(random.uniform(2, 4))

                    products = self.extract_product_info(url)
                    if products:
                        all_products.extend(products)
                        logging.info(f"Found {len(products)} products in category {category}")

                except Exception as e:
                    logging.error(f"Error scraping category {category}: {str(e)}")
                    continue

            if not all_products:
                raise ScraperError("No products found in any category. Please check if the website structure has changed.")

            logging.info(f"Successfully scraped {len(all_products)} products in total")
            return all_products

        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            raise ScraperError(str(e))