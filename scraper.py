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
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

class ScraperError(Exception):
    """Custom exception for scraper-related errors"""
    pass

class RimiScraper:
    def __init__(self, status_callback: Optional[Callable[[str], None]] = None):
        self.base_url = "https://www.rimi.lv"
        self.category_urls = [
            "https://www.rimi.lv/e-veikals/lv/produkti/gatavots-rimi/c/SH-17"
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
        self.page_size = 20  # Set page size to 20 items

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

    def get_max_page_number(self, html_content: str) -> int:
        """Extract maximum page number from pagination"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            pagination = soup.find('div', class_='pagination')
            if pagination:
                # Find all page links and get the highest page number
                page_links = pagination.find_all('a', attrs={'data-page': True})
                if page_links:
                    max_page = max(int(link['data-page']) for link in page_links)
                    return max_page
            return 1  # Return 1 if no pagination found
        except Exception as e:
            logging.error(f"Error extracting max page number: {str(e)}")
            return 1

    def build_page_url(self, category_url: str, page: int) -> str:
        """Build URL for specific page number"""
        parsed = urlparse(category_url)
        category_id = parsed.path.split('/')[-1]

        # Base query parameters
        params = {
            'query': f':relevance:allCategories:{category_id}:assortmentStatus:inAssortment',
            'pageSize': self.page_size,
            'currentPage': page
        }

        # Construct the URL with parameters
        return f"{category_url}?{urlencode(params)}"

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
                self.status_callback(f"No products found in {url}")
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

    def scrape_products(self) -> List[Dict[str, Union[str, Decimal]]]:
        """Scrape product information from multiple Rimi categories"""
        try:
            # Initialize session
            self.status_callback("Initializing scraper session...")
            all_products = []

            for category_url in self.category_urls:
                try:
                    self.status_callback(f"Processing category: {category_url}")

                    # First request to get max page number
                    response = self.session.get(category_url)
                    if response.status_code != 200:
                        self.status_callback(f"Failed to access category {category_url}. Status code: {response.status_code}")
                        continue

                    max_pages = self.get_max_page_number(response.text)
                    self.status_callback(f"Found {max_pages} pages in category")

                    # Process first page products from initial response
                    category_products = self.extract_product_info(response.text, category_url)
                    all_products.extend(category_products)
                    self.status_callback(f"Processed page 1/{max_pages} with {len(category_products)} products")

                    # Process remaining pages if any
                    for page in range(2, max_pages + 1):
                        try:
                            # Add random delay between pages
                            time.sleep(random.uniform(1, 2))

                            page_url = self.build_page_url(category_url, page)
                            self.status_callback(f"Fetching page {page}/{max_pages}")

                            response = self.session.get(page_url)
                            if response.status_code != 200:
                                self.status_callback(f"Failed to access page {page}. Status code: {response.status_code}")
                                continue

                            page_products = self.extract_product_info(response.text, page_url)
                            all_products.extend(page_products)
                            self.status_callback(f"Processed page {page}/{max_pages} with {len(page_products)} products")

                        except Exception as e:
                            logging.error(f"Error processing page {page} of category {category_url}: {str(e)}")
                            self.status_callback(f"Error processing page {page}: {str(e)}")
                            continue

                    self.status_callback(f"Completed category {category_url}")

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