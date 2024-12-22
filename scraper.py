import requests
from bs4 import BeautifulSoup
import logging
from decimal import Decimal, InvalidOperation
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Dict, Optional, Union

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
            'Cache-Control': 'max-age=0',
            'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
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

    def scrape_products(self) -> List[Dict[str, Union[str, Decimal]]]:
        """Scrape product information from Rimi online store"""
        try:
            # First, get the main page to establish session and cookies
            initial_response = self.session.get(self.base_url)
            initial_response.raise_for_status()

            # Access a specific category that always has products
            search_url = f"{self.base_url}/produkti/dzivo-augu-nodala"
            logging.info(f"Scraping URL: {search_url}")

            response = self.session.get(search_url)
            if response.status_code == 404:
                raise ScraperError("Product category not found. The website structure might have changed.")
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            products_list = []

            # Try multiple possible selectors for product grid
            product_selectors = [
                'div.product-grid__item',
                'div.product-grid-item',
                'article.product-grid-item',
                'div.card.product-grid-item'
            ]

            for selector in product_selectors:
                products = soup.select(selector)
                if products:
                    logging.info(f"Found {len(products)} products using selector: {selector}")
                    break

            if not products:
                # Log HTML structure for debugging
                logging.error("HTML structure preview:")
                logging.error(soup.prettify()[:1000])
                raise ScraperError("No products found on the page. The website structure might have changed.")

            for product in products:
                try:
                    # Try multiple selectors for product elements
                    name = None
                    for name_selector in ['a.card__url', 'h3.product-grid-item__title a', 'a.product-grid-item__details-title-link']:
                        name_elem = product.select_one(name_selector)
                        if name_elem:
                            name = name_elem.text.strip()
                            product_url = self.base_url + name_elem['href'] if name_elem.get('href') else None
                            break

                    # Try multiple selectors for price
                    price_text = None
                    for price_selector in ['div.price-tag__price', 'span.price', 'div.price-tag__main-price']:
                        price_elem = product.select_one(price_selector)
                        if price_elem:
                            price_text = price_elem.text.strip()
                            break

                    price = self.clean_price(price_text) if price_text else Decimal('0.00')

                    # Try multiple selectors for price per unit
                    price_per_unit = None
                    for unit_selector in ['div.price-tag__unit', 'span.price-per-unit', 'span.price-tag__unit-price']:
                        unit_elem = product.select_one(unit_selector)
                        if unit_elem:
                            price_per_unit = unit_elem.text.strip()
                            break

                    if name and price > Decimal('0'):
                        logging.info(f"Found product: {name} - {price}")
                        products_list.append({
                            'name': name,
                            'price': price,
                            'price_per_unit': price_per_unit,
                            'product_url': product_url,
                            'sku': self.extract_sku(product_url),
                            'category': self.extract_category(product_url)
                        })

                except Exception as e:
                    logging.error(f"Error processing product: {str(e)}")
                    continue

            if not products_list:
                raise ScraperError("Failed to extract any valid products from the page.")

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