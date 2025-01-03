import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from decimal import Decimal, InvalidOperation
import logging
import re
import time
import random
import json
from typing import List, Dict, Optional, Union, Callable, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
from dataclasses import dataclass
from bs4 import BeautifulSoup

class ScraperError(Exception):
    """Custom exception for scraper-related errors"""
    pass

@dataclass
class NutritionalInfo:
    ingredients: Optional[str] = None
    energy_kj: Optional[Decimal] = None
    energy_kcal: Optional[Decimal] = None
    fat: Optional[Decimal] = None
    saturated_fat: Optional[Decimal] = None
    carbohydrates: Optional[Decimal] = None
    sugars: Optional[Decimal] = None
    protein: Optional[Decimal] = None
    salt: Optional[Decimal] = None
    needs_review: bool = False
    review_notes: Optional[str] = None
    serving_size_unit: Optional[str] = None

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

        params = {
            'query': f':relevance:allCategories:{category_id}:assortmentStatus:inAssortment',
            'pageSize': self.page_size,
            'currentPage': page
        }

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

            self.status_callback("Analyzing page structure...")
            logging.debug(f"Raw HTML content length: {len(html_content)}")

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
                    gtm_data = product.get('data-gtm-eec-product')
                    if gtm_data:
                        try:
                            product_data = json.loads(gtm_data)

                            price_per_unit_elem = product.select_one('.price-per-unit, .unit-price')
                            price_per_unit = price_per_unit_elem.get_text(strip=True) if price_per_unit_elem else None

                            url_elem = product.select_one('a.card__url.js-gtm-eec-product-click')
                            product_url = url_elem.get('href') if url_elem else None
                            if product_url:
                                product_url = f"{self.base_url}{product_url}"

                            img_elem = product.select_one('.card__image-wrapper img')
                            image_url = None
                            if img_elem:
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

    def _extract_decimal(self, text: str) -> Optional[Decimal]:
        """Extract decimal number from text, handling various formats"""
        try:
            cleaned = re.sub(r'[^0-9.-]', '', text.replace(',', '.'))
            return Decimal(cleaned) if cleaned else None
        except (InvalidOperation, ValueError):
            return None

    def _extract_energy_values(self, text: str) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """Extract both kJ and kcal values from energy text"""
        try:
            pattern = r'(\d+(?:[,.]\d+)?)\s*kJ\s*(?:/|\s)\s*(\d+(?:[,.]\d+)?)\s*kcal'
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                kj = self._extract_decimal(match.group(1))
                kcal = self._extract_decimal(match.group(2))
                return kj, kcal
            return None, None
        except Exception as e:
            logging.error(f"Error extracting energy values: {str(e)}")
            return None, None

    def scrape_nutritional_info(self, product_url: str) -> NutritionalInfo:
        """Scrape nutritional information from product detail page"""
        try:
            if not product_url:
                return NutritionalInfo(needs_review=True, review_notes="Missing product URL")

            self.status_callback(f"Fetching nutritional info from {product_url}")
            response = self.session.get(product_url)
            if response.status_code != 200:
                return NutritionalInfo(needs_review=True, review_notes=f"Failed to fetch page: {response.status_code}")

            soup = BeautifulSoup(response.text, 'html.parser')
            self.status_callback("Page fetched successfully, looking for product details script")

            script_tag = None
            for script in soup.find_all('script'):
                if script.string and 'Storefront.product_details_page' in script.string:
                    script_tag = script
                    self.status_callback("Found Storefront.product_details_page script")

                    # Extract the complete script content
                    script_content = script_tag.string
                    self.status_callback("=== Script Content Analysis ===")
                    self.status_callback(f"Total length: {len(script_content)}")

                    # Find the tabs array section
                    tabs_pattern = r'tabs:\s*\[(.*?)\]'
                    tabs_match = re.search(tabs_pattern, script_content, re.DOTALL)

                    if tabs_match:
                        tabs_content = tabs_match.group(1)
                        self.status_callback("\nFound tabs section")

                        # Find the specific tab with index 0 and identifier 'details'
                        tab_pattern = r'\{\s*index:\s*0,\s*identifier:\s*["\']details["\'],.*?html:\s*["\']([^"\']+)["\']'
                        tab_match = re.search(tab_pattern, tabs_content, re.DOTALL)

                        if tab_match:
                            self.status_callback("Found details tab")
                            raw_html = tab_match.group(1)
                            self.status_callback(f"Raw HTML length: {len(raw_html)}")

                            try:
                                # Handle multiple levels of escaping
                                unescaped = raw_html
                                # First, handle standard escapes
                                unescaped = unescaped.replace('\\\\', '\\')
                                unescaped = unescaped.replace('\\"', '"')
                                # Then handle unicode escapes
                                while '\\u' in unescaped:
                                    unescaped = unescaped.encode().decode('unicode-escape')

                                # Parse the HTML content
                                details_soup = BeautifulSoup(unescaped, 'html.parser')

                                # Initialize nutritional info
                                info = NutritionalInfo()

                                # Extract ingredients - updated logic
                                for section in details_soup.find_all('div', class_='product__list-wrapper'):
                                    heading = section.find('p', class_='heading')
                                    if heading and 'Sastāvdaļas' in heading.get_text(strip=True):
                                        text_div = section.find('div', class_='text')
                                        if text_div and text_div.p:
                                            info.ingredients = text_div.p.get_text(strip=True)
                                            self.status_callback(f"Found ingredients: {info.ingredients[:100]}...")
                                        break

                                # Find nutrition table
                                nutrition_table = details_soup.find('table')
                                if nutrition_table:
                                    self.status_callback("Found nutrition table")

                                    for row in nutrition_table.find_all('tr'):
                                        cells = row.find_all(['td', 'th'])
                                        if len(cells) >= 2:
                                            label = cells[0].get_text(strip=True).lower()
                                            value = cells[1].get_text(strip=True)

                                            if 'enerģētiskā vērtība' in label:
                                                info.energy_kj, info.energy_kcal = self._extract_energy_values(value)
                                            elif 'tauki' == label:
                                                info.fat = self._extract_decimal(value)
                                            elif 'piesātinātās taukskābes' in label:
                                                info.saturated_fat = self._extract_decimal(value)
                                            elif 'ogļhidrāti' == label:
                                                info.carbohydrates = self._extract_decimal(value)
                                            elif 'cukuri' in label:
                                                info.sugars = self._extract_decimal(value)
                                            elif 'olbaltumvielas' == label:
                                                info.protein = self._extract_decimal(value)
                                            elif 'sāls' == label:
                                                info.salt = self._extract_decimal(value)

                                    return info
                                else:
                                    self.status_callback("No nutrition table found")
                                    info.needs_review = True
                                    info.review_notes = "No nutrition table found in content"
                                    return info

                            except Exception as e:
                                self.status_callback(f"Error processing HTML content: {str(e)}")
                                return NutritionalInfo(needs_review=True, review_notes=f"Processing error: {str(e)}")
                        else:
                            self.status_callback("Could not find details tab")
                            return NutritionalInfo(needs_review=True, review_notes="Details tab not found")
                    else:
                        self.status_callback("Could not find tabs section")
                        return NutritionalInfo(needs_review=True, review_notes="Tabs section not found")

            self.status_callback("No matching script found")
            return NutritionalInfo(needs_review=True, review_notes="Product details script not found")

        except Exception as e:
            logging.error(f"Error scraping nutritional info: {str(e)}")
            return NutritionalInfo(needs_review=True, review_notes=f"Error: {str(e)}")

    def scrape_products(self) -> List[Dict[str, Union[str, Decimal]]]:
        """Scrape product information from multiple Rimi categories"""
        try:
            self.status_callback("Initializing scraper session...")
            all_products = []
            products_with_nutrition = []

            for category_url in self.category_urls:
                try:
                    self.status_callback(f"Processing category: {category_url}")

                    response = self.session.get(category_url)
                    if response.status_code != 200:
                        self.status_callback(f"Failed to access category {category_url}. Status code: {response.status_code}")
                        continue

                    max_pages = self.get_max_page_number(response.text)
                    self.status_callback(f"Found {max_pages} pages in category")

                    products = self.extract_product_info(response.text, category_url)

                    for product in products:
                        if product.get('product_url'):
                            nutrition = self.scrape_nutritional_info(product['product_url'])
                            products_with_nutrition.append({
                                'product': product,
                                'nutrition': nutrition
                            })
                        time.sleep(random.uniform(0.5, 1))

                    all_products.extend(products)
                    self.status_callback(f"Processed page 1/{max_pages} with {len(products)} products")

                    for page in range(2, max_pages + 1):
                        try:
                            time.sleep(random.uniform(1, 2))
                            page_url = self.build_page_url(category_url, page)
                            self.status_callback(f"Fetching page {page}/{max_pages}")

                            response = self.session.get(page_url)
                            if response.status_code != 200:
                                self.status_callback(f"Failed to access page {page}. Status code: {response.status_code}")
                                continue

                            page_products = self.extract_product_info(response.text, page_url)

                            for product in page_products:
                                if product.get('product_url'):
                                    nutrition = self.scrape_nutritional_info(product['product_url'])
                                    products_with_nutrition.append({
                                        'product': product,
                                        'nutrition': nutrition
                                    })
                                time.sleep(random.uniform(0.5, 1))

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
                raise ScraperError("No products found in any category")

            needs_review_count = sum(1 for p in products_with_nutrition if p['nutrition'].needs_review)
            self.status_callback(f"Successfully scraped {len(all_products)} products, {needs_review_count} need review")

            return products_with_nutrition

        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            raise ScraperError(str(e))