import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from decimal import Decimal, InvalidOperation
import logging
import re
import time
import random
import json
import html
from typing import List, Dict, Optional, Union, Callable, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
from dataclasses import dataclass
from bs4 import BeautifulSoup

# Update country mappings
COUNTRY_MAPPING = {
    'Latvija': 'LV',
    'Igaunija': 'EE',
    'Lietuva': 'LT',
    'Polija': 'PL',
    'Vācija': 'DE',
    'Itālija': 'IT',
    'Beļģija': 'BE',
    'Grieķija': 'GR',
    'Slovākija': 'SK',
    'Zviedrija': 'SE',
    'Francija': 'FR',
    'Ukraina': 'UA',
    'Indija': 'IN',
    'Taizeme': 'TH',
    'Turcija': 'TR',
    'Serbija': 'RS',
    'Nīderlande': 'NL',
    'Dānija': 'DK',
    'Čehija': 'CZ',
    'Apvienotā karaliste': 'GB',
    'Maurīcija': 'MU',
    'Indonēzija': 'ID',
    'Šveice': 'CH',
    'Austrija': 'AT',
    'Taivana': 'TW',
    'Koreja': 'KR',
    'Spānija': 'ES',
    'Šrilanka': 'LK',
    'Peru': 'PE',
    'Vjetnama': 'VN',
    'Bulgārija': 'BG',
    'Čīle': 'CL',
    'Ekvadora': 'EC',
    'Kolumbija': 'CO',
    'Portugāle': 'PT',
    'Argentīna': 'AR',
    'Brazīlija': 'BR',
    'Maroka': 'MA',
    'Dienvidāfrika': 'ZA',
    'Kotdivuāra': 'CI',
    'Ruanda': 'RW',
    # Add more mappings as needed
}

def extract_quantity(text: str) -> Tuple[Optional[Decimal], Optional[str]]:
    """Extract numeric value and unit from quantity text"""
    if not text:
        return None, None

    # Pattern to match number followed by unit, now including more variations
    pattern = r'(\d+(?:[,.]\d+)?)\s*([kKmMlLgG]+[gG]?)'
    match = re.search(pattern, text)

    if match:
        value_str = match.group(1).replace(',', '.')
        unit = match.group(2).lower()

        try:
            value = Decimal(value_str)
            # Normalize units
            if unit in ['l', 'л']:
                unit = 'l'
            elif unit in ['kg', 'кг', 'kg']:
                unit = 'kg'
            elif unit in ['g', 'г', 'gg', 'g']:
                unit = 'g'
                value = value / 1000  # Convert to kg
                unit = 'kg'
            return value, unit
        except (InvalidOperation, ValueError):
            return None, None

    return None, None

def get_country_code(country_name: str) -> Optional[str]:
    """Convert country name to ISO country code"""
    if not country_name:
        return None

    # Clean the input string
    cleaned_name = country_name.strip().split(',')[0]  # Take first country if multiple
    return COUNTRY_MAPPING.get(cleaned_name)

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
            "https://www.rimi.lv/e-veikals/lv/produkti/gatavots-rimi/c/SH-2"
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
        self.start_page = 1  # Default starting page

    def set_start_page(self, page: int):
        """Set the starting page number for scraping"""
        if page < 1:
            raise ValueError("Start page must be greater than 0")
        self.start_page = page
        self.status_callback(f"Set starting page to: {page}")

    def _create_session(self) -> requests.Session:
        """Create a session with retry strategy and keepalive"""
        session = requests.Session()
        retry_strategy = Retry(
            total=5,  # Increased from 3 to 5
            backoff_factor=2,  # Increased from 1 to 2 for exponential backoff
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],  # Allow retries for POST
            respect_retry_after_header=True
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,  # Increased connection pool
            pool_maxsize=10,
            pool_block=False
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(self.headers)

        # Add keepalive settings
        session.headers.update({
            'Connection': 'keep-alive',
            'Keep-Alive': 'timeout=60, max=1000'
        })
        return session

    def _ensure_session(self):
        """Ensure session is active, recreate if needed"""
        try:
            # Test the session with a simple request
            response = self.session.get(self.base_url, timeout=10)
            response.raise_for_status()
        except (requests.exceptions.RequestException, Exception) as e:
            logging.warning(f"Session test failed: {str(e)}. Recreating session...")
            self.session = self._create_session()

    def get_max_page_number(self, html_content: str) -> int:
        """Extract maximum page number from pagination"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            pagination = soup.find('div', class_='pagination')
            if pagination:
                page_links = pagination.find_all('a', attrs={'data-page': True})
                if page_links:
                    max_page = max(int(link.get('data-page', 1)) for link in page_links)
                    self.status_callback(f"Found pagination with {max_page} pages")
                    return max_page
            total_items_elem = soup.find('div', class_='results-count')
            if total_items_elem:
                total_text = total_items_elem.get_text(strip=True)
                match = re.search(r'\d+', total_text)
                if match:
                    total_items = int(match.group())
                    max_page = (total_items + self.page_size - 1) // self.page_size
                    self.status_callback(f"Calculated {max_page} pages from {total_items} total items")
                    return max_page
            return 1
        except Exception as e:
            logging.error(f"Error extracting max page number: {str(e)}")
            return 1

    def build_page_url(self, category_url: str, page: int) -> str:
        """Build URL for specific page number"""
        try:
            parsed = urlparse(category_url)
            query_params = parse_qs(parsed.query)

            # Preserve existing query parameters except pagination ones
            params = {k: v[0] for k, v in query_params.items() if k not in ['pageSize', 'pageIndex', 'currentPage', 'page']}

            # Add pagination parameters
            params['pageSize'] = str(self.page_size)
            params['currentPage'] = str(page)  # Use currentPage starting from 1

            # Construct the URL preserving the path
            base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            final_url = f"{base_url}?{urlencode(params)}"

            self.status_callback(f"Generated URL for page {page}: {final_url}")
            return final_url

        except Exception as e:
            logging.error(f"Error building page URL: {str(e)}")
            return category_url

    def clean_price(self, price_str: str) -> Decimal:
        """Clean and convert price string to Decimal"""
        try:
            if not price_str:
                return Decimal('0.00')
            # Remove any currency symbols and whitespace
            cleaned = re.sub(r'[^\d.,]', '', str(price_str).strip().replace(' ', ''))
            # Replace comma with period for decimal point
            cleaned = cleaned.replace(',', '.')
            # Handle cases where there might be multiple periods
            if cleaned.count('.') > 1:
                # Keep only the last period for decimal places
                parts = cleaned.split('.')
                cleaned = parts[0].replace('.', '') + '.' + parts[-1]
            return Decimal(cleaned)
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

            # Try to find product price in multiple ways
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
                    product_info = {}

                    if gtm_data:
                        try:
                            product_data = json.loads(gtm_data)

                            # Extract price from GTM data
                            raw_price = product_data.get('price', 0)
                            self.status_callback(f"Raw price from GTM data: {raw_price}")
                            price = self.clean_price(raw_price)

                            # If price is 0, try to find it in the HTML
                            if price == 0:
                                price_elem = product.select_one('.price-wrapper .price, .card-price')
                                if price_elem:
                                    raw_price = price_elem.get_text(strip=True)
                                    self.status_callback(f"Raw price from HTML: {raw_price}")
                                    price = self.clean_price(raw_price)

                            product_info = {
                                'name': product_data.get('name', ''),
                                'price': price,
                                'sku': product_data.get('id'),
                                'category': product_data.get('category'),
                            }

                            # Get additional information
                            url_elem = product.select_one('a.card__url.js-gtm-eec-product-click')
                            if url_elem:
                                product_info['product_url'] = f"{self.base_url}{url_elem.get('href')}"

                            img_elem = product.select_one('.card__image-wrapper img')
                            if img_elem:
                                product_info['image_url'] = img_elem.get('data-src') or img_elem.get('src')

                            # Extract quantity and unit if available
                            quantity_elem = product.select_one('.quantity, .amount')
                            if quantity_elem:
                                quantity_text = quantity_elem.get_text(strip=True)
                                quantity_value, quantity_unit = extract_quantity(quantity_text)
                                product_info['quantity_value'] = quantity_value
                                product_info['quantity_unit'] = quantity_unit

                            if product_info.get('name') and product_info['price'] > 0:
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

    def scrape_nutritional_info(self, product_url: str) -> Tuple[NutritionalInfo, Optional[str], Optional[Tuple[Decimal, str]]]:
        """Scrape nutritional information and additional details from product detail page"""
        try:
            if not product_url:
                return NutritionalInfo(needs_review=True, review_notes="Missing product URL"), None, None
            self.status_callback(f"Fetching nutritional info from {product_url}")
            response = self.session.get(product_url)
            if response.status_code != 200:
                return NutritionalInfo(needs_review=True, review_notes=f"Failed to fetch page: {response.status_code}"), None, None

            soup = BeautifulSoup(response.text, 'html.parser')
            self.status_callback("Page fetched successfully, looking for product details script")

            # Initialize nutritional info
            info = NutritionalInfo()
            country_code = None
            quantity = None, None

            # First try to find quantity and country directly from the page
            for item in soup.find_all('li', class_='item'):
                span = item.find('span')
                if span:
                    label = span.get_text(strip=True)
                    text_div = item.find('div', class_='text')
                    if text_div and text_div.p:
                        value = text_div.p.get_text(strip=True)

                        # Extract country of origin
                        if 'Izcelsmes valsts' in label:
                            country_code = get_country_code(value)
                        # Extract quantity
                        elif 'Daudzums' in label:
                            quantity_value, quantity_unit = extract_quantity(value)
                            quantity = (quantity_value, quantity_unit)

            # If quantity not found, try to extract from product title or other elements
            if not quantity[0]:
                # Try product title
                title_elem = soup.find('h1', class_='name')
                if title_elem:
                    title_text = title_elem.get_text(strip=True)
                    quantity_value, quantity_unit = extract_quantity(title_text)
                    if quantity_value:
                        quantity = (quantity_value, quantity_unit)

            # Find and parse the product details script
            script_tag = None
            for script in soup.find_all('script'):
                if script.string and 'Storefront.product_details_page' in script.string:
                    script_tag = script
                    break

            if script_tag:
                script_content = script_tag.string
                self.status_callback("Found product details script")

                # Extract the tabs section using a more reliable method
                try:
                    # First, try to find the details tab in the script content
                    details_match = re.search(r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']',
                                           script_content, re.DOTALL)

                    if not details_match:
                        # Try alternative pattern
                        details_match = re.search(r'html:\s*["\']([^"\']+)["\'].*?identifier:\s*["\']details["\']',
                                               script_content, re.DOTALL)

                    if details_match:
                        html_content = details_match.group(1)

                        # Handle escaped characters
                        html_content = html_content.encode().decode('unicode-escape')
                        html_content = html_content.replace('\\/', '/')
                        html_content = html_content.replace('\\"', '"')

                        self.status_callback(f"Successfully extracted details HTML content, length: {len(html_content)}")

                        details_soup = BeautifulSoup(html_content, 'html.parser')

                        # Try to find quantity and country again in the details tab if not found earlier
                        if not country_code or not quantity[0]:
                            self.status_callback("Searching for country and quantity in details tab...")
                            for item in details_soup.find_all('li', class_='item'):
                                span = item.find('span')
                                if span:
                                    label = span.get_text(strip=True)
                                    self.status_callback(f"Found item with label: {label}")
                                    text_div = item.find('div', class_='text')
                                    if text_div and text_div.p:
                                        value = text_div.p.get_text(strip=True)
                                        self.status_callback(f"Found value: {value}")

                                        # Extract country of origin
                                        if 'Izcelsmes valsts' in label and not country_code:
                                            country_code = get_country_code(value)
                                            self.status_callback(f"Extracted country code: {country_code}")
                                        # Extract quantity
                                        elif 'Daudzums' in label and not quantity[0]:
                                            quantity_value, quantity_unit = extract_quantity(value)
                                            if quantity_value:
                                                quantity = (quantity_value, quantity_unit)
                                                self.status_callback(f"Extracted quantity: {quantity_value} {quantity_unit}")

                        # Find ingredients
                        for section in details_soup.find_all('div', class_='product__list-wrapper'):
                            heading = section.find('p', class_='heading')
                            if heading and 'Sastāvdaļas' in heading.get_text(strip=True):
                                text_div = section.find('div', class_='text')
                                if text_div and text_div.p:
                                    info.ingredients = text_div.p.get_text(strip=True)
                                    self.status_callback(f"Found ingredients: {info.ingredients[:100]}...")
                                break

                        # Find nutrition table
                        tables = details_soup.find_all('table')
                        nutrition_table = None
                        for table in tables:
                            headers = table.find_all('th')
                            if any('Uzturvērtība' in header.get_text(strip=True) for header in headers):
                                nutrition_table = table
                                self.status_callback("Found nutrition table")
                                break

                        if nutrition_table:
                            for row in nutrition_table.find_all('tr'):
                                cells = row.find_all(['td'])
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

                    else:
                        self.status_callback("Could not find details tab content in script")
                        return NutritionalInfo(needs_review=True, review_notes="Details tab content not found"), None, None

                except Exception as e:
                    self.status_callback(f"Error processing details tab: {str(e)}")
                    return NutritionalInfo(needs_review=True, review_notes=f"Error processing details: {str(e)}"), None, None

            else:
                self.status_callback("Product details script not found")
                return NutritionalInfo(needs_review=True, review_notes="Product details script not found"), None, None

            # Add summary logging
            self.status_callback("\n=== Extracted Data Summary ===")
            self.status_callback(f"Country Code: {country_code}")
            self.status_callback(f"Quantity: {quantity[0]} {quantity[1] if quantity[1] else 'N/A'}")
            self.status_callback(f"Ingredients: {info.ingredients[:100]}..." if info.ingredients else "No ingredients found")

            return info, country_code, quantity

        except Exception as e:
            logging.error(f"Error scraping nutritional info: {str(e)}")
            return NutritionalInfo(needs_review=True, review_notes=f"Error: {str(e)}"), None, None

    def get_total_products(self, category_url: str) -> Tuple[int, int]:
        """Get total number of products and pages for a category"""
        try:
            self.status_callback(f"Checking total products for category: {category_url}")
            response = self.session.get(category_url)
            if response.status_code != 200:
                self.status_callback(f"Failed to access category URL. Status code: {response.status_code}")
                return 0, 0

            soup = BeautifulSoup(response.text, 'html.parser')

            # Try to get total products from results count first
            total_items_elem = soup.find('div', class_='results-count')
            if total_items_elem:
                total_text = total_items_elem.get_text(strip=True)
                match = re.search(r'\d+', total_text)
                if match:
                    total_items = int(match.group())
                    max_pages = (total_items + self.page_size - 1) // self.page_size
                    self.status_callback(f"Found {total_items} total products from results count")
                    self.status_callback(f"Calculated {max_pages} total pages (page size: {self.page_size})")
                    return total_items, max_pages

            # Fallback to pagination
            pagination = soup.find('div', class_='pagination')
            if pagination:
                page_links = pagination.find_all('a', attrs={'data-page': True})
                if page_links:
                    max_page = max(int(link.get('data-page', 1)) for link in page_links)
                    total_items = max_page * self.page_size
                    self.status_callback(f"Found {max_page} pages from pagination links")
                    self.status_callback(f"Estimated {total_items} total products")
                    return total_items, max_page

            self.status_callback("Could not determine total products or pages")
            return 0, 0
        except Exception as e:
            logging.error(f"Error getting total products: {str(e)}")
            self.status_callback(f"Error determining total products: {str(e)}")
            return 0, 0

    def scrape_products(self) -> List[Dict[str, Union[str, Decimal]]]:
        """Scrape product information from multiple Rimi categories"""
        try:
            self.status_callback("Initializing scraper session...")
            all_products = []
            products_with_nutrition = []
            category_count = 0
            last_successful_page = 0  # Track last successful page

            # Calculate total products across all categories
            total_products = 0
            total_pages = 0
            for category_url in self.category_urls:
                products_in_category, pages_in_category = self.get_total_products(category_url)
                total_products += products_in_category
                total_pages += pages_in_category

            self.status_callback(f"Total products to process: {total_products} across {total_pages} pages")
            if self.start_page > 1:
                self.status_callback(f"Starting from page {self.start_page}")

            for category_url in self.category_urls:
                try:
                    self.status_callback(f"\nProcessing category: {category_url}")
                    category_products, category_pages = self.get_total_products(category_url)

                    if category_products == 0:
                        self.status_callback(f"No products found in category {category_url}")
                        continue

                    self.status_callback(f"Found {category_products} products in {category_pages} pages")

                    # Process all pages starting from start_page
                    page_products_with_nutrition = []
                    for page in range(self.start_page, category_pages + 1):
                        max_retries = 3
                        retry_count = 0

                        while retry_count < max_retries:
                            try:
                                self._ensure_session()  # Verify session before each page
                                self.status_callback(f"Processing page {page}/{category_pages}")

                                # Get the URL for the current page
                                current_url = self.build_page_url(category_url, page)
                                self.status_callback(f"Fetching URL: {current_url}")

                                # Add delay between pages
                                if page > self.start_page:
                                    time.sleep(random.uniform(2, 3))

                                response = self.session.get(current_url, timeout=30)  # Added timeout
                                if response.status_code != 200:
                                    raise requests.exceptions.RequestException(f"Failed with status {response.status_code}")

                                # Extract products from the page
                                products = self.extract_product_info(response.text, current_url)

                                if not products:
                                    self.status_callback(f"No products found on page {page}, retrying...")
                                    time.sleep(random.uniform(3, 4))
                                    self._ensure_session()  # Verify session before retry
                                    response = self.session.get(current_url, timeout=30)
                                    products = self.extract_product_info(response.text, current_url)

                                self.status_callback(f"Found {len(products)} products on page {page}")

                                # Process each product
                                for product in products:
                                    if product.get('product_url'):
                                        self.status_callback(f"Processing product: {product['name']} ({product.get('sku', 'No SKU')})")
                                        time.sleep(random.uniform(1, 2))

                                        nutrition, country_code, quantity = self.scrape_nutritional_info(product['product_url'])

                                        if country_code:
                                            product['country_code'] = country_code
                                        if quantity and quantity[0]:
                                            product['quantity_value'] = quantity[0]
                                            product['quantity_unit'] = quantity[1]

                                        page_products_with_nutrition.append({
                                            'product': product,
                                            'nutrition': nutrition
                                        })

                                all_products.extend(products)

                                # Save products after each page
                                if page_products_with_nutrition:
                                    try:
                                        from database import Database
                                        db = Database()
                                        result = db.save_products_with_nutrition(page_products_with_nutrition)
                                        self.status_callback(f"Saved {len(page_products_with_nutrition)} products from page {page}")
                                        self.status_callback(f"New: {result['new_products']}, Updated: {result['updated_products']}, Reviews needed: {result['needs_review']}")
                                        last_successful_page = page  # Update last successful page
                                        page_products_with_nutrition = []  # Clear after successful save
                                        break  # Exit retry loop on success
                                    except Exception as e:
                                        logging.error(f"Error saving products from page {page}: {str(e)}")
                                        self.status_callback(f"❌ Error saving products from page {page}: {str(e)}")
                                        if retry_count < max_retries - 1:
                                            retry_count += 1
                                            time.sleep(5 * retry_count)  # Exponential backoff
                                            continue
                                        products_with_nutrition.extend(page_products_with_nutrition)
                                    finally:
                                        if 'db' in locals():
                                            db.close()

                            except Exception as e:
                                logging.error(f"Error processing page {page}: {str(e)}")
                                if retry_count < max_retries - 1:
                                    retry_count += 1
                                    self.status_callback(f"Retry {retry_count}/{max_retries} for page {page}")
                                    time.sleep(5 * retry_count)  # Exponential backoff
                                    continue
                                self.status_callback(f"❌ Failed to process page {page} after {max_retries} retries: {str(e)}")
                                break

                    category_count += len(all_products)

                except Exception as e:
                    logging.error(f"Error scraping category {category_url}: {str(e)}")
                    self.status_callback(f"Error scraping category {category_url}: {str(e)}")
                    continue

            if category_count == 0:
                self.status_callback("⚠️ No products found during scraping. Please try again later.")
                return []  # Return empty list instead of raising error

            needs_review_count = sum(1 for p in products_with_nutrition if p['nutrition'].needs_review)
            self.status_callback(f"Successfully scraped {category_count} products, {needs_review_count} need review")
            if last_successful_page > 0:
                self.status_callback(f"Last successfully processed page: {last_successful_page}")
            return products_with_nutrition

        except Exception as e:
            logging.error(f"Scraping error:{str(e)}")
            if last_successful_page > 0:
                self.status_callback(f"Scraping interrupted at page {last_successful_page}")
            raise ScraperError(str(e))

    def scrape_specific_products(self, urls: List[str]) -> List[Dict[str, Union[str, Decimal]]]:
        """Scrape information for specific product URLs"""
        try:
            self.status_callback("Initializing specific products scraper session...")
            products_with_nutrition = []
            for url in urls:
                try:
                    self.status_callback(f"\nProcessing specific product: {url}")

                    # Clean URL
                    url = url.strip().strip('|')

                    # Fetch the product page
                    response = self.session.get(url)
                    if response.status_code != 200:
                        self.status_callback(f"Failed to access product {url}. Status code: {response.status_code}")
                        continue

                    self.status_callback("Successfully fetched product page")

                    # Parse the product information
                    soup = BeautifulSoup(response.text, 'html.parser')
                    self.status_callback("Created BeautifulSoup object")

                    # Initialize product data
                    product = {
                        'name': '',
                        'price': '0',
                        'sku': '',
                        'category': 'SH-gala-zivisun-gatava-kkulinarija',  # Default category
                        'product_url': url,
                        'image_url': None,
                    }

                    # First try to get product data from ld+json script
                    for script in soup.find_all('script', type='application/ld+json'):
                        try:
                            if script.string:
                                # Clean and parse JSON
                                json_str = html.unescape(script.string)
                                json_str = re.sub(r'\s+', ' ', json_str.replace('\\n', ' '))
                                json_str = re.sub(r'\\(["\'])', r'\1', json_str)

                                data = json.loads(json_str)
                                if isinstance(data, dict) and data.get('@type') == 'Product':
                                    self.status_callback("Found product data in ld+json")
                                    product['name'] = data.get('name', '')
                                    product['sku'] = data.get('sku', '')
                                    product['image_url'] = data.get('image', [None])[0] if isinstance(data.get('image'), list) else data.get('image')

                                    # Extract price from offers with detailed logging
                                    if 'offers' in data:
                                        offers = data['offers']
                                        self.status_callback(f"Found offers data: {json.dumps(offers, indent=2)}")

                                        if isinstance(offers, dict):
                                            price = offers.get('price')
                                            if price:
                                                try:
                                                    product['price'] = self.clean_price(price)
                                                    self.status_callback(f"Successfully extracted price from ld+json: {price} -> {product['price']}")
                                                except (InvalidOperation, ValueError) as e:
                                                    self.status_callback(f"Error converting price '{price}': {str(e)}")
                                        elif isinstance(offers, list) and offers:
                                            # Handle case where offers is a list
                                            first_offer = offers[0]
                                            if isinstance(first_offer, dict):
                                                price = first_offer.get('price')
                                                if price:
                                                    try:
                                                        product['price'] = self.clean_price(price)
                                                        self.status_callback(f"Successfully extracted price from first offer: {price} -> {product['price']}")
                                                    except (InvalidOperation, ValueError) as e:
                                                        self.status_callback(f"Error converting price '{price}': {str(e)}")
                                    else:
                                        self.status_callback("No offers data found in ld+json")
                                    break
                        except (json.JSONDecodeError, AttributeError) as e:
                            self.status_callback(f"Error parsing ld+json: {str(e)}")
                            if script.string:
                                self.status_callback(f"Problematic JSON: {script.string[:100]}...")
                            continue

                    # Extract category from statistics script
                    category_script = soup.find('script', attrs={
                        'type': 'text/plain',
                        'data-cookieconsent': 'statistics'
                    })

                    if category_script and category_script.string:
                        try:
                            # Find the dataLayer.push content
                            datalayer_match = re.search(r'dataLayer\.push\((.*?)\);', category_script.string, re.DOTALL)
                            if datalayer_match:
                                datalayer_data = json.loads(datalayer_match.group(1))
                                if 'ecommerce' in datalayer_data and 'impressions' in datalayer_data['ecommerce']:
                                    impressions = datalayer_data['ecommerce']['impressions']
                                    if impressions and isinstance(impressions, list) and len(impressions) > 0:
                                        category = impressions[0].get('category', '')
                                        if category:
                                            # Take the first part of the category path (most specific)
                                            product['category'] = category.split('/')[0]
                                            self.status_callback(f"Found category in dataLayer: {product['category']}")
                        except (json.JSONDecodeError, AttributeError) as e:
                            self.status_callback(f"Error parsing dataLayer: {str(e)}")

                    # Add validation logging
                    self.status_callback("\n=== Product Data Validation ===")

                    has_required_fields = True

                    if not product['name']:
                        has_required_fields = False
                        self.status_callback("❌ Missing required field: name")
                        name_elem = soup.find('h1', class_='name')
                        if name_elem:
                            name_text = name_elem.get_text(strip=True)
                            self.status_callback(f"  - Name element found but text was empty")

                    if not product['sku']:
                        has_required_fields = False
                        self.status_callback("❌ Missing required field: sku")
                        self.status_callback("  - Could not find SKU element in HTML")

                    if not product['price'] or Decimal(product['price']) <= 0:
                        self.status_callback("⚠️ Warning: No price found")
                        price_elem = soup.select_one('.price-wrapper .price, .price-tag')
                        if price_elem:
                            price_text = price_elem.get_text(strip=True)
                            self.status_callback(f"  - Price element found but could not extract number")
                            self.status_callback(f"  - Raw price text: {price_text}")

                    if not product['image_url']:
                        self.status_callback("⚠️ Warning: No image URL found in JSON-LD")
                        # Try to find image URL in HTML as fallback
                        img_elem = soup.select_one('.gallery-image img, .card__image-wrapper img')
                        if img_elem:
                            product['image_url'] = img_elem.get('data-src') or img_elem.get('src')
                            if product['image_url']:
                                self.status_callback(f"Found image URL in HTML: {product['image_url']}")

                    # Get nutritional info if we have required fields
                    if has_required_fields:
                        nutrition, country_code, quantity = self.scrape_nutritional_info(url)
                        products_with_nutrition.append({
                            'product': product,
                            'nutrition': nutrition
                        })
                        if country_code:
                            product['country_code'] = country_code
                            self.status_callback(f"Added country code: {country_code}")
                        if quantity and quantity[0]:
                            product['quantity_value'] = quantity[0]
                            product['quantity_unit'] = quantity[1]
                            self.status_callback(f"Added quantity: {quantity[0]} {quantity[1]}")
                        self.status_callback(f"✅ Successfully added product: {product['name']} (SKU: {product['sku']})")
                    else:
                        self.status_callback("⚠️ Product skipped: Missing required fields")
                        self.status_callback("  Required: name and sku")
                        self.status_callback(f"  Found: name='{product['name']}', sku='{product['sku']}'")

                    time.sleep(random.uniform(0.5, 1))

                except Exception as e:
                    self.status_callback(f"Error processing product {url}: {str(e)}")
                    continue

            self.status_callback(f"Successfully scraped {len(products_with_nutrition)} products")
            return products_with_nutrition

        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            raise ScraperError(str(e))