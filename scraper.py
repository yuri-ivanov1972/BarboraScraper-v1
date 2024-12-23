import trafilatura
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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
        self.base_url = "https://www.rimi.lv/e-veikals/lv"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'lv,en-US;q=0.9,en;q=0.8',
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
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(self.headers)
        return session

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

            # Log the HTML structure for debugging
            self.status_callback("Analyzing page structure...")

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
                self.status_callback(f"No products found with standard selectors, trying alternative selectors...")
                # Try alternative selectors
                products = soup.select('div.card.card--product')

            if not products:
                self.status_callback(f"No products found in category {url}")
                return []

            for index, product in enumerate(products, 1):
                try:
                    # Extract name and URL with multiple selectors
                    name_selectors = [
                        'a.card__url',
                        'h3.card__name a',
                        'a[class*="name"]',
                        'h3 a'
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
                        'div.price-tag span.price',
                        'span.price-tag__price',
                        'div[class*="price-tag"] span[class*="price"]'
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
                    unit_price = product.select_one('div.price-tag__unit, span.price-per-unit')
                    unit_price_text = unit_price.get_text(strip=True) if unit_price else None

                    product_info = {
                        'name': name,
                        'price': price,
                        'price_per_unit': unit_price_text,
                        'product_url': product_url
                    }

                    products_list.append(product_info)

                    # Log each successfully parsed product
                    self.status_callback(f"Parsed product {index}: {name} - €{price}")

                except Exception as e:
                    logging.error(f"Error processing product {index}: {str(e)}")
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

            # Specific category URL for apples and pears
            category_url = "https://www.rimi.lv/e-veikals/lv/produkti/augli-un-darzeni/augli-un-ogas/aboli-un-bumbieri/c/SH-2-1-2"

            self.status_callback(f"Accessing category: Apples and Pears")

            # Add random delay
            time.sleep(random.uniform(1, 2))

            # Try with trafilatura first
            self.status_callback("Attempting to fetch page content...")
            downloaded = trafilatura.fetch_url(category_url)

            if downloaded:
                self.status_callback("Successfully downloaded page, extracting content...")
                html_content = trafilatura.extract(downloaded, include_html=True)
                if html_content:
                    products = self.extract_product_info(html_content, category_url)
                    if products:
                        self.status_callback(f"Successfully extracted {len(products)} products")
                        return products

            # Fallback to direct request
            self.status_callback("Trying alternative fetching method...")
            response = self.session.get(category_url)

            if response.status_code != 200:
                raise ScraperError(f"Failed to access category. Status code: {response.status_code}")

            products = self.extract_product_info(response.text, category_url)

            if not products:
                raise ScraperError("No products found in the category. Please check if the website structure has changed.")

            self.status_callback(f"Successfully scraped {len(products)} products in total")
            return products

        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            raise ScraperError(str(e))