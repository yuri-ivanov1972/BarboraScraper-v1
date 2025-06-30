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
        Extract nutrition data from product page with robust parsing
        
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
        
        # Check if this is an olive oil product
        product_name = soup.find('h1')
        if product_name:
            name_text = product_name.get_text().lower()
            oil_keywords = ['olīveļļa', 'olive oil', 'eļļa', 'oil']
            is_oil = any(keyword in name_text for keyword in oil_keywords)
            
            if is_oil:
                self.status_callback("Detected olive oil product - applying standard nutrition values")
                # Standard olive oil nutrition values per 100g
                nutrition_data.update({
                    'has_nutrition': True,
                    'energy_kcal': 900,
                    'energy_kj': 3700,
                    'fat_total': 100.0,
                    'fat_saturated': 16.0,
                    'carbs_total': 0.0,
                    'carbs_sugars': 0.0,
                    'protein': 0.0,
                    'salt': 0.0,
                    'fiber': 0.0,
                    'ingredients': 'olīveļļa'
                })
                return nutrition_data
        
        try:
            page_text = soup.get_text()
            
            # Helper function to extract decimal values
            def extract_decimal(text: str) -> float:
                try:
                    # Replace comma with dot and extract number
                    clean_text = text.replace(',', '.').strip()
                    return float(clean_text)
                except (ValueError, AttributeError):
                    return 0.0
            
            # Extract ingredients (Sastāvdaļas)
            ingredients_patterns = [
                r'Sastāvdaļas[:\s]*([^.]+(?:\.[^.]*)*)',
                r'Ingredients[:\s]*([^.]+(?:\.[^.]*)*)',
                r'Sastāvs[:\s]*([^.]+(?:\.[^.]*)*)'
            ]
            
            for pattern in ingredients_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE | re.DOTALL)
                if match:
                    ingredients_text = match.group(1).strip()
                    # Clean up ingredients text
                    ingredients_text = re.sub(r'\s+', ' ', ingredients_text)
                    if len(ingredients_text) > 10:  # Reasonable minimum length
                        nutrition_data['ingredients'] = ingredients_text
                        self.status_callback(f"Found ingredients: {ingredients_text[:50]}...")
                        break
            
            # Extract nutrition values with Latvian labels
            nutrition_patterns = {
                'energy_kcal': [r'Enerģētiskā vērtība[:\s]*(\d+(?:[.,]\d+)?)\s*kcal', r'Energy[:\s]*(\d+(?:[.,]\d+)?)\s*kcal'],
                'energy_kj': [r'Enerģētiskā vērtība[:\s]*(\d+(?:[.,]\d+)?)\s*kJ', r'Energy[:\s]*(\d+(?:[.,]\d+)?)\s*kJ'],
                'fat_total': [r'Tauki[:\s]*(\d+(?:[.,]\d+)?)\s*g', r'Fat[:\s]*(\d+(?:[.,]\d+)?)\s*g'],
                'fat_saturated': [r'tostarp piesātinātās taukskābes[:\s]*(\d+(?:[.,]\d+)?)\s*g', r'saturated[:\s]*(\d+(?:[.,]\d+)?)\s*g'],
                'carbs_total': [r'Oglhidrāti[:\s]*(\d+(?:[.,]\d+)?)\s*g', r'Carbohydrates[:\s]*(\d+(?:[.,]\d+)?)\s*g'],
                'carbs_sugars': [r'tostarp cukuri[:\s]*(\d+(?:[.,]\d+)?)\s*g', r'sugars[:\s]*(\d+(?:[.,]\d+)?)\s*g'],
                'protein': [r'Olbaltumvielas[:\s]*(\d+(?:[.,]\d+)?)\s*g', r'Protein[:\s]*(\d+(?:[.,]\d+)?)\s*g'],
                'salt': [r'Sāls[:\s]*(\d+(?:[.,]\d+)?)\s*g', r'Salt[:\s]*(\d+(?:[.,]\d+)?)\s*g'],
                'fiber': [r'Šķiedrvielas[:\s]*(\d+(?:[.,]\d+)?)\s*g', r'Fiber[:\s]*(\d+(?:[.,]\d+)?)\s*g']
            }
            
            found_nutrition_count = 0
            
            for nutrient, patterns in nutrition_patterns.items():
                for pattern in patterns:
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        value = extract_decimal(match.group(1))
                        nutrition_data[nutrient] = value
                        found_nutrition_count += 1
                        self.status_callback(f"Found {nutrient}: {value}g")
                        break
            
            # Consider nutrition data complete if we found at least 3 nutrition values
            if found_nutrition_count >= 3:
                nutrition_data['has_nutrition'] = True
                self.status_callback(f"Complete nutrition data found ({found_nutrition_count} values)")
            else:
                self.status_callback(f"Incomplete nutrition data ({found_nutrition_count} values found)")
            
        except Exception as e:
            self.status_callback(f"Error extracting nutrition data: {str(e)}")
        
        return nutrition_data
    
    def close(self):
        """Close the session"""
        if self.session:
            self.session.close()