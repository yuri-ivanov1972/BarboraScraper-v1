import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from decimal import Decimal, InvalidOperation
import logging
import re
import time
import random
import json
from typing import List, Dict, Optional, Union, Callable

class ScraperError(Exception):
    """Custom exception for scraper-related errors"""
    pass

class RimiScraper:
    def __init__(self, status_callback: Optional[Callable[[str], None]] = None):
        self.base_url = "https://www.rimi.lv"
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
            return Decimal(str(price_str))
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
            logging.debug(f"Raw HTML content length: {len(html_content)}")

            # Find all product containers with data-gtm-eec-product attribute
            products = soup.find_all(attrs={'data-gtm-eec-product': True})

            if not products:
                self.status_callback("No products found with GTM attribute, trying alternative selectors...")
                products = soup.select('.product-grid-item, .card--product')

            if not products:
                self.status_callback(f"No products found in category {url}")
                return []

            self.status_callback(f"Found {len(products)} potential product elements")

            for index, product in enumerate(products, 1):
                try:
                    # Try to get product data from GTM attribute
                    gtm_data = product.get('data-gtm-eec-product')
                    if gtm_data:
                        try:
                            # Parse the JSON data
                            product_data = json.loads(gtm_data)

                            # Extract unit price if available
                            price_per_unit_elem = product.select_one('.price-per-unit, .unit-price')
                            price_per_unit = price_per_unit_elem.get_text(strip=True) if price_per_unit_elem else None

                            # Find the product URL from the card__url element
                            url_elem = product.select_one('a.card__url.js-gtm-eec-product-click')
                            product_url = url_elem.get('href') if url_elem else None
                            if product_url:
                                product_url = f"{self.base_url}{product_url}"

                            product_info = {
                                'name': product_data.get('name', ''),
                                'price': self.clean_price(product_data.get('price', 0)),
                                'price_per_unit': price_per_unit,
                                'product_url': product_url,
                                'sku': product_data.get('id'),
                                'category': product_data.get('category')
                            }

                            if product_info['name'] and product_info['price'] > 0:
                                products_list.append(product_info)
                                self.status_callback(f"Successfully parsed product {index}: {product_info['name']} - €{product_info['price']}")
                            else:
                                self.status_callback(f"Skipping product {index}: Invalid name or price")

                        except json.JSONDecodeError as e:
                            self.status_callback(f"Error parsing GTM data for product {index}: {str(e)}")
                            continue

                except Exception as e:
                    logging.error(f"Error processing product {index}: {str(e)}")
                    self.status_callback(f"Error processing product {index}: {str(e)}")
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

            # Make the request
            self.status_callback("Attempting to fetch page content...")
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