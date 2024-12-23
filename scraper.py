import requests
from bs4 import BeautifulSoup
import logging
from decimal import Decimal, InvalidOperation
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Dict, Optional, Union
import json
import time
import random

class ScraperError(Exception):
    """Custom exception for scraper-related errors"""
    pass

class RimiScraper:
    def __init__(self):
        self.base_url = "https://www.rimi.lv/e-veikals"
        self.api_url = "https://www.rimi.lv/api/products"  # Updated API endpoint
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9,lv;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Pragma': 'no-cache',
            'Cookie': 'region=LV',
            'X-Requested-With': 'XMLHttpRequest'
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
            # Remove € symbol and replace comma with dot
            clean_price = price_str.replace('€', '').replace(',', '.').strip()
            return Decimal(clean_price)
        except (InvalidOperation, ValueError) as e:
            logging.error(f"Price conversion error for '{price_str}': {str(e)}")
            return Decimal('0.00')

    def extract_sku(self, url: Optional[str]) -> Optional[str]:
        """Extract SKU from product URL"""
        try:
            if not url:
                return None
            match = re.search(r'/p/(\d+)$', url)
            return match.group(1) if match else None
        except Exception as e:
            logging.error(f"SKU extraction error for URL '{url}': {str(e)}")
            return None

    def extract_category(self, url: Optional[str]) -> Optional[str]:
        """Extract category path from product URL"""
        try:
            if not url:
                return None
            parts = url.split('/')
            if 'produkti' in parts:
                start_idx = parts.index('produkti')
                category_parts = parts[start_idx+1:-1]
                return '/'.join(category_parts)
            return None
        except Exception as e:
            logging.error(f"Category extraction error for URL '{url}': {str(e)}")
            return None

    def scrape_html_fallback(self, response: requests.Response) -> List[Dict[str, Union[str, Decimal]]]:
        """Fallback method to scrape HTML when API fails"""
        soup = BeautifulSoup(response.text, 'html.parser')
        products_list = []

        # Try multiple possible selectors for product grid
        products = soup.select('div.product-grid__item, div.product-grid-item, article.product-grid-item')

        if not products:
            logging.warning("No products found in HTML structure")
            return []

        for product in products:
            try:
                name_elem = product.select_one('a.card__url, h3.product-grid-item__title a')
                price_elem = product.select_one('div.price-tag__price, span.price')
                unit_elem = product.select_one('div.price-tag__unit, span.price-per-unit')

                if name_elem and price_elem:
                    product_url = name_elem.get('href', '')
                    if product_url and not isinstance(product_url, list):
                        if not product_url.startswith('http'):
                            product_url = f"https://www.rimi.lv{product_url}"

                        products_list.append({
                            'name': name_elem.text.strip(),
                            'price': self.clean_price(price_elem.text.strip()),
                            'price_per_unit': unit_elem.text.strip() if unit_elem else None,
                            'product_url': product_url,
                            'sku': self.extract_sku(product_url),
                            'category': self.extract_category(product_url)
                        })

            except Exception as e:
                logging.error(f"Error processing HTML product: {str(e)}")
                continue

        return products_list

    def scrape_products(self) -> List[Dict[str, Union[str, Decimal]]]:
        """Scrape product information from Rimi online store"""
        try:
            # First, get the main page to establish session and cookies
            logging.info("Accessing main page to establish session...")
            initial_response = self.session.get(self.base_url)
            initial_response.raise_for_status()
            logging.info("Successfully accessed main page")

            # Try multiple category URLs
            categories = [
                '/produkti/augli-darzeni-un-ziedi/svaigie-augli',
                '/produkti/dzivo-augu-nodala',
                '/produkti/svaigi-produkti'
            ]

            products_list = []
            success = False

            for category in categories:
                try:
                    # Try API first
                    category_url = f"{self.base_url}{category}"
                    logging.info(f"Trying category: {category_url}")

                    # Add a small delay between requests
                    time.sleep(random.uniform(1, 3))

                    response = self.session.get(category_url)
                    if response.status_code == 200:
                        # Log HTML content for debugging
                        logging.info(f"Response headers: {dict(response.headers)}")
                        logging.info(f"Response preview: {response.text[:500]}")

                        products = self.scrape_html_fallback(response)
                        if products:
                            products_list.extend(products)
                            success = True
                            break

                except Exception as e:
                    logging.error(f"Failed to scrape category {category}: {str(e)}")
                    continue

            if not success:
                # Try alternative URL patterns
                alt_categories = [
                    '/produkti/augli-darzeni-ziedi/augli-darzeni',
                    '/produkti/svaigi-produkti/augli-darzeni',
                    '/produkti/partikas-preces'
                ]

                for category in alt_categories:
                    try:
                        category_url = f"{self.base_url}{category}"
                        logging.info(f"Trying alternative category: {category_url}")

                        # Add a small delay between requests
                        time.sleep(random.uniform(1, 3))

                        response = self.session.get(category_url)
                        if response.status_code == 200:
                            products = self.scrape_html_fallback(response)
                            if products:
                                products_list.extend(products)
                                success = True
                                break

                    except Exception as e:
                        logging.error(f"Failed to scrape alternative category {category}: {str(e)}")
                        continue

            if not success:
                raise ScraperError("Failed to scrape products from any category")

            if not products_list:
                raise ScraperError("No products found in any category")

            logging.info(f"Successfully scraped {len(products_list)} products")
            return products_list

        except requests.exceptions.ConnectionError:
            raise ScraperError("Failed to connect to Rimi website. Please check your internet connection.")
        except requests.exceptions.Timeout:
            raise ScraperError("Request timed out. The Rimi website might be slow or unresponsive.")
        except requests.exceptions.RequestException as e:
            raise ScraperError(f"Failed to fetch data from Rimi website: {str(e)}")
        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            if hasattr(e, 'response'):
                logging.error(f"Response status code: {e.response.status_code}")
                logging.error(f"Response text: {e.response.text[:500]}")
            raise ScraperError(f"An unexpected error occurred while scraping: {str(e)}")