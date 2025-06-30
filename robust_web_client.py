"""
Robust Web Client - Handles website unavailability with retry logic and proper error handling
Implements exponential backoff and user-friendly notifications for connection issues
"""

import requests
import time
import random
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup

class RobustWebClient:
    """Web client with robust retry logic for temporary website unavailability"""
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda msg: print(msg))
        self.session = None
        self._create_session()
    
    def _create_session(self):
        """Create session with proper headers to mimic browser"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'lv,en-US;q=0.7,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
    
    def fetch_with_retry(self, url: str, max_attempts: int = 3, base_delay: float = 2.0) -> Optional[requests.Response]:
        """
        Fetch URL with exponential backoff retry logic
        
        Args:
            url: URL to fetch
            max_attempts: Maximum number of retry attempts (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 2.0)
            
        Returns:
            Response object if successful, None if all attempts failed
        """
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                self.status_callback(f"Attempt {attempt + 1}/{max_attempts}: Fetching {url}")
                
                # Add timeout to prevent hanging
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 200:
                    self.status_callback(f"Successfully fetched {url}")
                    return response
                elif response.status_code == 404:
                    self.status_callback(f"Product not found (404): {url}")
                    return None  # Don't retry for 404 - product doesn't exist
                else:
                    self.status_callback(f"HTTP {response.status_code} from {url}")
                    last_error = f"HTTP {response.status_code}"
                    
            except requests.exceptions.Timeout:
                last_error = "Request timeout"
                self.status_callback(f"Timeout on attempt {attempt + 1}")
                
            except requests.exceptions.ConnectionError:
                last_error = "Connection error"
                self.status_callback(f"Connection error on attempt {attempt + 1}")
                
            except requests.exceptions.RequestException as e:
                last_error = f"Request error: {str(e)}"
                self.status_callback(f"Request error on attempt {attempt + 1}: {str(e)}")
            
            # Calculate delay with exponential backoff and jitter
            if attempt < max_attempts - 1:  # Don't delay after last attempt
                delay = base_delay * (2 ** attempt) + random.uniform(0.1, 0.5)
                self.status_callback(f"Waiting {delay:.1f}s before retry...")
                time.sleep(delay)
        
        self.status_callback(f"All {max_attempts} attempts failed for {url}. Last error: {last_error}")
        return None
    
    def get_product_data(self, sku: str) -> Optional[Dict[str, Any]]:
        """
        Get product data with multiple URL pattern attempts and robust error handling
        
        Args:
            sku: Product SKU
            
        Returns:
            Dictionary with product data or None if not found
        """
        # Try different URL patterns for Rimi products
        url_patterns = [
            f"https://www.rimi.lv/e-veikals/lv/produkti/p/{sku}",
            f"https://www.rimi.lv/e-veikals/lv/products/{sku}",
            f"https://www.rimi.lv/e-veikals/en/products/{sku}",
            f"https://www.rimi.lv/products/{sku}"
        ]
        
        for pattern in url_patterns:
            self.status_callback(f"Trying URL pattern: {pattern}")
            
            response = self.fetch_with_retry(pattern)
            if response is None:
                continue  # Try next pattern
            
            try:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Check if this is a valid product page
                title_elem = soup.find('h1', class_='name') or soup.find('h1')
                if not title_elem:
                    self.status_callback("No product title found - trying next URL pattern")
                    continue
                
                product_name = title_elem.get_text(strip=True)
                if not product_name or product_name.lower() in ['not found', 'error', 'page not found']:
                    self.status_callback("Invalid product title - trying next URL pattern")
                    continue
                
                self.status_callback(f"Found valid product: {product_name}")
                
                # Extract price with robust parsing
                price = self._extract_price(soup)
                
                return {
                    'name': product_name,
                    'price': price,
                    'url': pattern,
                    'soup': soup  # Include soup for further processing
                }
                
            except Exception as e:
                self.status_callback(f"Error parsing product page: {str(e)}")
                continue
        
        self.status_callback(f"Product SKU {sku} not found with any URL pattern")
        return None
    
    def _extract_price(self, soup: BeautifulSoup) -> str:
        """Extract price from product page with robust parsing"""
        price = "0.00"
        
        # Try multiple price selector patterns
        price_selectors = [
            '.price-wrapper .price',
            '.price-tag',
            '.price',
            '[data-price]',
            '.product-price'
        ]
        
        for selector in price_selectors:
            price_elem = soup.select_one(selector)
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                
                # Extract price number - handle newlines and spaces in price format
                import re
                # Remove all whitespace including newlines, then look for price pattern
                clean_text = re.sub(r'\s+', '', price_text)
                price_match = re.search(r'(\d+[.,]?\d*)', clean_text)
                
                if price_match:
                    price_str = price_match.group(1)
                    # Handle cases like "359" -> "3.59" for multi-digit prices
                    if '.' not in price_str and ',' not in price_str and len(price_str) >= 3:
                        # Insert decimal point before last 2 digits
                        price = f"{price_str[:-2]}.{price_str[-2:]}"
                    else:
                        price = price_str.replace(',', '.')
                    
                    self.status_callback(f"Price extraction: '{price_text}' -> '€{price}'")
                    break
        
        return price
    
    def extract_nutrition_data(self, soup: BeautifulSoup, product_url: str) -> Dict[str, Any]:
        """
        Extract nutrition data from product page with robust HTML table parsing
        
        Args:
            soup: BeautifulSoup object of the product page
            product_url: URL of the product page for logging
            
        Returns:
            Dictionary with nutrition data
        """
        import re
        from decimal import Decimal, InvalidOperation
        
        # Initialize nutrition data
        nutrition_data = {
            'has_nutrition': False,
            'ingredients': '',
            'energy_kcal': 0,
            'energy_kj': 0,
            'fat_total': 0,
            'fat_saturated': 0,
            'carbs_total': 0,
            'carbs_sugars': 0,
            'protein': 0,
            'salt': 0,
            'fiber': 0
        }
        
        try:
            # Helper function to extract decimal values
            def extract_decimal(text: str) -> float:
                try:
                    # Extract numbers from text, handling various formats
                    numbers = re.findall(r'\d+(?:[.,]\d+)?', text.replace(',', '.'))
                    return float(numbers[0]) if numbers else 0.0
                except (ValueError, AttributeError):
                    return 0.0
            
            # Helper function to extract energy values (kJ and kcal)
            def extract_energy_values(text: str) -> tuple:
                try:
                    # Match patterns like "3700 kJ/ 900 kcal" or "3700 kJ / 900 kcal"
                    pattern = r'(\d+(?:[.,]\d+)?)\s*kJ\s*[/\\]\s*(\d+(?:[.,]\d+)?)\s*kcal'
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        kj = extract_decimal(match.group(1))
                        kcal = extract_decimal(match.group(2))
                        return kj, kcal
                    return 0.0, 0.0
                except Exception:
                    return 0.0, 0.0
            
            # First, try to extract from JavaScript content (existing product details)
            script_tag = None
            for script in soup.find_all('script'):
                if script.string and 'Storefront.product_details_page' in script.string:
                    script_tag = script
                    break
            
            if script_tag and script_tag.string:
                script_content = script_tag.string
                self.status_callback("Found product details script - extracting HTML content")
                
                # Extract the details tab HTML content
                details_match = re.search(
                    r'identifier:\s*["\']details["\'],[^}]*html:\s*["\']([^"\']+)["\']',
                    script_content, re.DOTALL
                )
                
                if details_match:
                    # Decode the HTML content
                    details_html = details_match.group(1)
                    details_html = details_html.replace('\\/', '/').replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                    details_soup = BeautifulSoup(details_html, 'html.parser')
                    self.status_callback("Successfully parsed product details HTML")
                    
                    # Extract ingredients
                    for section in details_soup.find_all('div', class_='product__list-wrapper'):
                        heading = section.find('p', class_='heading')
                        if heading and 'Sastāvdaļas' in heading.get_text(strip=True):
                            text_div = section.find('div', class_='text')
                            if text_div and text_div.p:
                                nutrition_data['ingredients'] = text_div.p.get_text(strip=True)
                                self.status_callback(f"Found ingredients: {nutrition_data['ingredients'][:50]}...")
                            break
                    
                    # Find nutrition table with proper HTML parsing and character encoding handling
                    tables = details_soup.find_all('table')
                    nutrition_table = None
                    for table in tables:
                        headers = table.find_all('th')
                        # Check for nutrition headers with proper Unicode handling
                        for header in headers:
                            header_text = header.get_text(strip=True)
                            # Handle both Unicode escaped and normal Latvian characters
                            if any(pattern in header_text.lower() for pattern in ['uzturvērtība', 'uzturv\\u0113rt\\u012bba', 'nutrition']):
                                nutrition_table = table
                                self.status_callback("Found nutrition table with structured data")
                                break
                        if nutrition_table:
                            break
                    
                    if nutrition_table:
                        nutrition_data['has_nutrition'] = True
                        found_nutrition_count = 0
                        
                        for row in nutrition_table.find_all('tr'):
                            cells = row.find_all(['td'])
                            if len(cells) >= 2:
                                label = cells[0].get_text(strip=True).lower()
                                value = cells[1].get_text(strip=True)
                                
                                self.status_callback(f"Processing nutrition row: '{label}' -> '{value}'")
                                
                                # Handle Unicode escape sequences in Latvian text
                                if any(pattern in label for pattern in ['enerģētiskā vērtība', 'ener\\u0123\\u0113tisk\\u0101 v\\u0113rt\\u012bba', 'energy']):
                                    kj, kcal = extract_energy_values(value)
                                    if kj > 0 or kcal > 0:
                                        nutrition_data['energy_kj'] = kj
                                        nutrition_data['energy_kcal'] = kcal
                                        found_nutrition_count += 2
                                        self.status_callback(f"✓ Energy: {kcal} kcal ({kj} kJ)")
                                
                                elif ('tauki' in label or 'fat' in label) and not any(x in label for x in ['piesātinātās', 'pies\\u0101tin\\u0101t\\u0101s', 'tostarp', 'saturated']):
                                    fat_total = extract_decimal(value)
                                    nutrition_data['fat_total'] = fat_total
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Fat total: {fat_total}g")
                                
                                elif any(pattern in label for pattern in ['piesātinātās taukskābes', 'pies\\u0101tin\\u0101t\\u0101s tauksk\\u0101bes', 'tostarp piesātinātās', 'saturated']):
                                    fat_saturated = extract_decimal(value)
                                    nutrition_data['fat_saturated'] = fat_saturated
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Saturated fat: {fat_saturated}g")
                                
                                elif any(pattern in label for pattern in ['ogļhidrāti', 'og\\u013chidr\\u0101ti', 'carbohydrate']) and not any(x in label for x in ['cukuri', 'tostarp', 'sugar']):
                                    carbs_total = extract_decimal(value)
                                    nutrition_data['carbs_total'] = carbs_total
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Carbohydrates: {carbs_total}g")
                                
                                elif any(pattern in label for pattern in ['cukuri', 'tostarp cukuri', 'sugar']):
                                    carbs_sugars = extract_decimal(value)
                                    nutrition_data['carbs_sugars'] = carbs_sugars
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Sugars: {carbs_sugars}g")
                                
                                elif any(pattern in label for pattern in ['olbaltumvielas', 'protein']):
                                    protein = extract_decimal(value)
                                    nutrition_data['protein'] = protein
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Protein: {protein}g")
                                
                                elif any(pattern in label for pattern in ['sāls', 's\\u0101ls', 'salt']):
                                    salt = extract_decimal(value)
                                    nutrition_data['salt'] = salt
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Salt: {salt}g")
                                
                                elif any(pattern in label for pattern in ['šķiedrvielas', 'fiber']):
                                    fiber = extract_decimal(value)
                                    nutrition_data['fiber'] = fiber
                                    found_nutrition_count += 1
                                    self.status_callback(f"✓ Fiber: {fiber}g")
                        
                        self.status_callback(f"Nutrition table parsing complete: {found_nutrition_count} values extracted")
                        
                        if found_nutrition_count >= 3:
                            self.status_callback(f"✓ Complete nutrition data found ({found_nutrition_count} values)")
                        else:
                            self.status_callback(f"○ Partial nutrition data ({found_nutrition_count} values found)")
                    else:
                        self.status_callback("○ No nutrition table found in product details")
                else:
                    self.status_callback("○ Could not extract details HTML from script")
            else:
                self.status_callback("○ No product details script found")
                
        except Exception as e:
            self.status_callback(f"✗ Error extracting nutrition data: {str(e)}")
        
        return nutrition_data
    
    def close(self):
        """Close the session"""
        if self.session:
            self.session.close()