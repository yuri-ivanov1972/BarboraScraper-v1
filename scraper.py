import requests
from bs4 import BeautifulSoup
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
            logging.debug(f"Raw HTML content length: {len(html_content)}")

            # Debug: Print the first 1000 characters of HTML
            self.status_callback(f"First 1000 chars of HTML: {html_content[:1000]}")

            # Find all product containers with most basic selector first
            products = soup.select('.product-grid-item, .card--product')

            if not products:
                self.status_callback("No products found with basic selector, trying alternative...")
                products = soup.select('[class*="product-"]')

            if not products:
                self.status_callback(f"No products found in category {url}")
                return []

            self.status_callback(f"Found {len(products)} potential product elements")

            for index, product in enumerate(products, 1):
                try:
                    # Log the product HTML for debugging
                    self.status_callback(f"Processing product {index} HTML: {str(product)[:200]}...")

                    # Try to find product name and link
                    name_elem = (
                        product.select_one('a.js-product-name-truncated') or 
                        product.select_one('a[class*="name"]') or
                        product.select_one('h3 a')
                    )

                    if not name_elem:
                        self.status_callback(f"Skipping product {index}: No name element found")
                        continue

                    name = name_elem.get_text(strip=True)
                    product_url = name_elem.get('href', '')
                    if product_url and not product_url.startswith('http'):
                        product_url = f"https://www.rimi.lv{product_url}"

                    # Try to find price
                    price_elem = (
                        product.select_one('.price') or
                        product.select_one('[class*="price-tag"]') or
                        product.select_one('[class*="price"]')
                    )

                    if not price_elem:
                        self.status_callback(f"Skipping product {index}: No price element found")
                        continue

                    price_text = price_elem.get_text(strip=True)
                    price = self.clean_price(price_text)

                    if price <= 0:
                        self.status_callback(f"Skipping product {index}: Invalid price")
                        continue

                    # Get price per unit if available
                    unit_price = product.select_one('.price-per-unit, .unit-price')
                    unit_price_text = unit_price.get_text(strip=True) if unit_price else None

                    product_info = {
                        'name': name,
                        'price': price,
                        'price_per_unit': unit_price_text,
                        'product_url': product_url
                    }

                    products_list.append(product_info)
                    self.status_callback(f"Successfully parsed product {index}: {name} - €{price}")

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

            # Log response headers for debugging
            self.status_callback(f"Response headers: {dict(response.headers)}")

            products = self.extract_product_info(response.text, category_url)

            if not products:
                raise ScraperError("No products found in the category. Please check if the website structure has changed.")

            self.status_callback(f"Successfully scraped {len(products)} products in total")
            return products

        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            raise ScraperError(str(e))