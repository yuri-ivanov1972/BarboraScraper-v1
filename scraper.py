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

# Add country code mapping
COUNTRY_MAPPING = {
    'Latvija': 'LV',
    'Igaunija': 'EE',
    'Lietuva': 'LT',
    'Polija': 'PL',
    'Vācija': 'DE',
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

                            # Extract quantity and unit if available
                            quantity_value = None
                            quantity_unit = None
                            quantity_elem = product.select_one('.quantity, .amount')
                            if quantity_elem:
                                quantity_text = quantity_elem.get_text(strip=True)
                                quantity_value, quantity_unit = extract_quantity(quantity_text)

                            product_info = {
                                'name': product_data.get('name', ''),
                                'price': self.clean_price(product_data.get('price', 0)),
                                'price_per_unit': price_per_unit,
                                'product_url': product_url,
                                'image_url': image_url,
                                'sku': product_data.get('id'),
                                'category': product_data.get('category'),
                                'quantity_value': quantity_value,
                                'quantity_unit': quantity_unit,
                                'country_code': None  # Will be updated in product details page
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
                            self.status_callback(f"\nProcessing product: {product.get('product_url')}")
                            nutrition, country_code, quantity = self.scrape_nutritional_info(product['product_url'])

                            # Update product with additional details
                            if country_code:
                                product['country_code'] = country_code
                                self.status_callback(f"Added country code: {country_code}")
                            if quantity and quantity[0] is not None:
                                product['quantity_value'] = quantity[0]
                                product['quantity_unit'] = quantity[1]
                                self.status_callback(f"Added quantity: {quantity[0]} {quantity[1]}")

                            # Add specific logging for problematic SKUs
                            if product.get('sku') in ['2000324', '2000330', '2000511']:
                                self.status_callback(f"\n=== Problematic SKU Data ===")
                                self.status_callback(f"SKU: {product.get('sku')}")
                                self.status_callback(f"Name: {product.get('name')}")
                                self.status_callback(f"Country: {product.get('country_code')}")
                                self.status_callback(f"Quantity: {product.get('quantity_value')} {product.get('quantity_unit')}")
                                self.status_callback(f"URL: {product.get('product_url')}")

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
                                    nutrition, country_code, quantity = self.scrape_nutritional_info(product['product_url'])
                                    product['country_code'] = country_code
                                    product['quantity_value'] = quantity[0]
                                    product['quantity_unit'] = quantity[1]
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

    def scrape_specific_products(self, urls: List[str]) -> List[Dict[str, Union[str, Decimal]]]:
        """Scrape specific product URLs"""
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

                    # Extract product data from JSON-LD
                    json_ld = None
                    for script in soup.find_all('script', type='application/ld+json'):
                        try:
                            # Clean and decode the JSON string
                            if script.string:
                                # First unescape HTML entities
                                json_str = html.unescape(script.string)
                                # Remove escaped newlines and normalize whitespace
                                json_str = re.sub(r'\s+', ' ', json_str.replace('\\n', ' '))
                                # Remove any escaped quotes within HTML attributes
                                json_str = re.sub(r'\\(["\'])', r'\1', json_str)

                                # Parse the JSON
                                data = json.loads(json_str)
                                if isinstance(data, dict) and data.get('@type') == 'Product':
                                    json_ld = data
                                    self.status_callback("Found product data in JSON-LD")
                                    self.status_callback(f"JSON-LD data: {json.dumps(data, indent=2)[:200]}...")
                                    break
                        except (json.JSONDecodeError, AttributeError) as e:
                            self.status_callback(f"Error parsing JSON-LD: {str(e)}")
                            if script.string:
                                self.status_callback(f"Problematic JSON: {script.string[:100]}...")
                            continue

                    # Initialize product data
                    product = {
                        'name': '',
                        'price': '0',
                        'sku': '',
                        'category': 'SH-gala-zivis-un-gatava-kulinarija',  # Default category
                        'product_url': url,
                        'image_url': None,
                    }

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

                    # Extract data from JSON-LD if available
                    if json_ld:
                        self.status_callback("Using data from JSON-LD schema:")
                        product['name'] = json_ld.get('name', '')
                        product['sku'] = json_ld.get('sku', '')
                        if 'offers' in json_ld and isinstance(json_ld['offers'], dict):
                            product['price'] = self.clean_price(json_ld['offers'].get('price', '0'))
                        product['image_url'] = json_ld.get('image', [None])[0] if isinstance(json_ld.get('image'), list) else json_ld.get('image')

                        self.status_callback(f"Name: {product['name']}")
                        self.status_callback(f"SKU: {product['sku']}")
                        self.status_callback(f"Price: {product['price']}")

                    # Add validation logging
                    self.status_callback("\n=== Product Data Validation ===")

                    has_required_fields = True

                    if not product['name']:
                        has_required_fields = False
                        self.status_callback("❌ Missing required field: name")
                        name_elem = soup.find('h1', class_='name')
                        if name_elem:
                            self.status_callback(f"  Found name in HTML: {name_elem.get_text(strip=True)}")

                    if not product['sku']:
                        has_required_fields = False
                        self.status_callback("❌ Missing required field: sku")
                        self.status_callback("  Could not find SKU in JSON-LD data")

                    if not product['price']:
                        self.status_callback("⚠️ Warning: No price found")
                        price_elem = soup.find('div', class_='price-wrapper')
                        if price_elem:
                            self.status_callback(f"  Raw price text: {price_elem.get_text(strip=True)}")

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
                        if country_code:
                            product['country_code'] = country_code
                            self.status_callback(f"Added country code: {country_code}")
                        if quantity and quantity[0]:
                            product['quantity_value'] = quantity[0]
                            product['quantity_unit'] = quantity[1]
                            self.status_callback(f"Added quantity: {quantity[0]} {quantity[1]}")

                        products_with_nutrition.append({
                            'product': product,
                            'nutrition': nutrition
                        })
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