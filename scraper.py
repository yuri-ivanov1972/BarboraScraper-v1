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
        self.category_urls = [
            "https://www.rimi.lv/e-veikals/lv/produkti/augli-un-darzeni/c/SH-2",
            "https://www.rimi.lv/e-veikals/lv/produkti/gatavots-rimi/c/SH-17",
            "https://www.rimi.lv/e-veikals/lv/produkti/veganiem-un-vegetariesiem/c/SH-16",
            "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/c/SH-6",
            "https://www.rimi.lv/e-veikals/lv/produkti/piena-produkti-un-olas/c/SH-11",
            "https://www.rimi.lv/e-veikals/lv/produkti/maize-un-konditoreja/c/SH-7",
            "https://www.rimi.lv/e-veikals/lv/produkti/saldetie-edieni/c/SH-12",
            "https://www.rimi.lv/e-veikals/lv/produkti/iepakota-partika/c/SH-4",
            "https://www.rimi.lv/e-veikals/lv/produkti/saldumi-un-uzkodas/c/SH-13",
            "https://www.rimi.lv/e-veikals/lv/produkti/dzerieni/c/SH-5"
        ]
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
        self.page_size = 20  # Default page size used by Rimi

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
                self.status_callback(f"No products found in page {url}")
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

                            # Extract image URL from card__image-wrapper
                            img_elem = product.select_one('.card__image-wrapper img')
                            image_url = None
                            if img_elem:
                                # Try to get the high-quality data-src first, fallback to src
                                image_url = img_elem.get('data-src') or img_elem.get('src')

                            product_info = {
                                'name': product_data.get('name', ''),
                                'price': self.clean_price(product_data.get('price', 0)),
                                'price_per_unit': price_per_unit,
                                'product_url': product_url,
                                'image_url': image_url,
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

    def has_next_page(self, html_content: str) -> bool:
        """Check if there is a next page by looking for pagination elements"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            # Look for active page number
            active_page = soup.select_one('.pagination__item--active')
            if active_page:
                next_page = active_page.find_next_sibling('li', class_='pagination__item')
                return bool(next_page)
            return False
        except Exception as e:
            logging.error(f"Error checking for next page: {str(e)}")
            return False

    def scrape_products(self) -> List[Dict[str, Union[str, Decimal]]]:
        """Scrape product information from multiple Rimi categories with pagination"""
        try:
            # Initialize session
            self.status_callback("Initializing scraper session...")
            all_products = []

            for category_url in self.category_urls:
                try:
                    self.status_callback(f"Processing category: {category_url}")
                    current_page = 1
                    has_more_pages = True

                    while has_more_pages:
                        # Construct paginated URL
                        paginated_url = f"{category_url}?currentPage={current_page}&pageSize={self.page_size}"
                        self.status_callback(f"Fetching page {current_page}")

                        # Add random delay between requests
                        time.sleep(random.uniform(1, 2))

                        # Make the request
                        response = self.session.get(paginated_url)

                        if response.status_code != 200:
                            self.status_callback(f"Failed to access {paginated_url}. Status code: {response.status_code}")
                            break

                        # Extract products from current page
                        page_products = self.extract_product_info(response.text, paginated_url)

                        if page_products:
                            all_products.extend(page_products)
                            self.status_callback(f"Found {len(page_products)} products on page {current_page}")
                        else:
                            self.status_callback(f"No products found on page {current_page}")
                            break

                        # Check if there's a next page
                        has_more_pages = self.has_next_page(response.text)
                        if has_more_pages:
                            current_page += 1
                        else:
                            self.status_callback(f"No more pages available for category {category_url}")

                    self.status_callback(f"Finished processing category {category_url}")

                except Exception as e:
                    logging.error(f"Error scraping category {category_url}: {str(e)}")
                    self.status_callback(f"Error scraping category {category_url}: {str(e)}")
                    continue

            if not all_products:
                raise ScraperError("No products found in any category. Please check if the website structure has changed.")

            self.status_callback(f"Successfully scraped {len(all_products)} products in total")
            return all_products

        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            raise ScraperError(str(e))