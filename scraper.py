import requests
from bs4 import BeautifulSoup
import logging
from decimal import Decimal
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class RimiScraper:
    def __init__(self):
        self.base_url = "https://www.rimi.lv/e-veikals/lv"
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

    def _create_session(self):
        """Create a session with retry strategy"""
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

    def clean_price(self, price_str):
        """Clean and convert price string to Decimal"""
        try:
            if not price_str:
                return Decimal('0.00')
            # Remove € symbol and replace comma with dot
            clean_price = price_str.replace('€', '').replace(',', '.').strip()
            return Decimal(clean_price)
        except Exception as e:
            logging.error(f"Price conversion error: {str(e)}")
            return Decimal('0.00')

    def extract_sku(self, url):
        """Extract SKU from product URL"""
        try:
            if not url:
                return None
            match = re.search(r'/p/(\d+)$', url)
            return match.group(1) if match else None
        except Exception as e:
            logging.error(f"SKU extraction error: {str(e)}")
            return None

    def extract_category(self, url):
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
            logging.error(f"Category extraction error: {str(e)}")
            return None

    def scrape_products(self):
        """Scrape product information from Rimi online store"""
        try:
            # First, get the main page to establish session and cookies
            initial_response = self.session.get(self.base_url)
            initial_response.raise_for_status()

            # Now access the search page with specific parameters
            search_url = f"{self.base_url}/produkti/augli-un-darzeni"
            logging.info(f"Scraping URL: {search_url}")

            response = self.session.get(search_url)
            response.raise_for_status()

            logging.info(f"Response status: {response.status_code}")
            logging.info(f"Response headers: {response.headers}")
            logging.info(f"Response cookies: {dict(response.cookies)}")

            soup = BeautifulSoup(response.text, 'html.parser')

            # Log the HTML content for debugging
            logging.info("HTML Content Preview:")
            logging.info(soup.prettify()[:1000])  # First 1000 chars for debugging

            products_list = []

            # Updated selectors for product grid
            products = soup.select('article.product-grid-item')
            logging.info(f"Found {len(products)} products")

            for product in products:
                try:
                    # Extract product link and name
                    link_elem = product.select_one('h3.product-grid-item__title a')
                    if not link_elem:
                        logging.warning("No link element found for product")
                        continue

                    product_url = 'https://www.rimi.lv' + link_elem['href'] if link_elem else None
                    name = link_elem.text.strip() if link_elem else None

                    # Extract price
                    price_elem = product.select_one('span.price')
                    price_text = price_elem.text.strip() if price_elem else '0.00'
                    price = self.clean_price(price_text)

                    # Extract price per unit
                    price_unit_elem = product.select_one('span.price-per-unit')
                    price_per_unit = price_unit_elem.text.strip() if price_unit_elem else None

                    # Extract SKU and category from URL
                    sku = self.extract_sku(product_url)
                    category = self.extract_category(product_url)

                    if name and price:
                        logging.info(f"Found product: {name} - {price}")
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

            logging.info(f"Successfully scraped {len(products_list)} products")
            return products_list

        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            if hasattr(e, 'response'):
                logging.error(f"Response status code: {e.response.status_code}")
                logging.error(f"Response text: {e.response.text[:500]}")  # Log first 500 chars of response
            return []