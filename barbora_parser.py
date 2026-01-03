#!/usr/bin/env python3
"""
Barbora Parser - Core parsing functionality for Barbora.lv website
- Category page parsing with pagination (extracts window.b_productList JSON)
- Product page parsing (nutrition, ingredients, allergens)
- Database connections using normalized_category slugs
"""
import requests
from bs4 import BeautifulSoup
import re
import time
import random
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json


@dataclass
class BarboraProductInfo:
    """Product information extracted from Barbora pages"""
    sku: str
    name: str
    price: Optional[float]
    url: str
    barbora_category_code: Optional[str] = None
    category_path: Optional[str] = None
    brand_name: Optional[str] = None
    image_url: Optional[str] = None
    big_image_url: Optional[str] = None
    comparative_unit: Optional[str] = None
    comparative_unit_price: Optional[float] = None
    retail_price: Optional[float] = None
    status: str = "active"
    is_available: bool = True
    promotion: Optional[Dict] = None
    is_made_in_eu: bool = False
    is_made_in_home_country: bool = False


@dataclass
class BarboraNutritionInfo:
    """Nutrition information from individual product page"""
    energy_kj: Optional[float] = None
    energy_kcal: Optional[float] = None
    fat: Optional[float] = None
    saturated_fat: Optional[float] = None
    carbohydrates: Optional[float] = None
    sugars: Optional[float] = None
    protein: Optional[float] = None
    salt: Optional[float] = None
    fiber: Optional[float] = None


@dataclass
class BarboraProductDetails:
    """Full product details from individual product page"""
    sku: str
    name: str
    description: Optional[str] = None
    ingredients: Optional[str] = None
    allergens: Optional[str] = None
    nutrition: Optional[BarboraNutritionInfo] = None
    country_of_origin: Optional[str] = None
    manufacturer: Optional[str] = None
    storage_conditions: Optional[str] = None
    weight: Optional[str] = None
    photo_urls: Optional[List[str]] = None


class BarboraParser:
    """Parser for Barbora.lv grocery website"""
    
    BASE_URL = "https://barbora.lv"
    PRODUCTS_PER_PAGE = 52
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda x: None)
        self.session = self._create_session()
        
    def _create_session(self) -> requests.Session:
        """Create session with headers to mimic browser"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'lv-LV,lv;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        return session
    
    def build_category_url(self, normalized_category_path: str, page: int = 1) -> str:
        """
        Build Barbora category URL from normalized category path
        
        Args:
            normalized_category_path: Full path like "piena-produkti-un-olas/piens/uht-piens"
            page: Page number (1-based)
            
        Returns:
            Full URL like "https://barbora.lv/piena-produkti-un-olas/piens/uht-piens?page=2"
        """
        normalized_category_path = normalized_category_path.strip().strip('/')
        url = f"{self.BASE_URL}/{normalized_category_path}"
        if page > 1:
            url += f"?page={page}"
        return url
    
    def build_product_url(self, product_url_slug: str) -> str:
        """
        Build full product URL from the Url field in b_productList
        
        Args:
            product_url_slug: Slug like "piens-farm-milk-2-proc-uht-1-l"
            
        Returns:
            Full URL like "https://barbora.lv/produkti/piens-farm-milk-2-proc-uht-1-l"
        """
        product_url_slug = product_url_slug.strip().strip('/')
        return f"{self.BASE_URL}/produkti/{product_url_slug}"
    
    def get_category_path_from_db(self, category_id: int) -> Optional[str]:
        """
        Build the full category path from database hierarchy
        
        Returns path like "piena-produkti-un-olas/piens/uht-piens"
        """
        conn = None
        try:
            conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    WITH RECURSIVE category_path AS (
                        SELECT category_id, normalized_category, parent_category_id, 1 as depth
                        FROM normalized_categories
                        WHERE category_id = %s
                        
                        UNION ALL
                        
                        SELECT nc.category_id, nc.normalized_category, nc.parent_category_id, cp.depth + 1
                        FROM normalized_categories nc
                        JOIN category_path cp ON nc.category_id = cp.parent_category_id
                    )
                    SELECT normalized_category FROM category_path
                    ORDER BY depth DESC
                """, (category_id,))
                
                rows = cur.fetchall()
                if rows:
                    path_parts = [row['normalized_category'] for row in rows]
                    return '/'.join(path_parts)
                return None
        except Exception as e:
            self.status_callback(f"Error getting category path: {str(e)}")
            return None
        finally:
            if conn:
                conn.close()
    
    def _extract_product_list_json(self, html_content: str) -> List[Dict]:
        """
        Extract window.b_productList JSON from page HTML
        
        Returns list of product dictionaries
        """
        try:
            start_marker = 'window.b_productList = ['
            start_idx = html_content.find(start_marker)
            
            if start_idx == -1:
                self.status_callback("No window.b_productList found in page")
                return []
            
            json_start = start_idx + len('window.b_productList = ')
            
            bracket_count = 0
            json_end = json_start
            in_string = False
            escape_next = False
            
            for i, char in enumerate(html_content[json_start:], json_start):
                if escape_next:
                    escape_next = False
                    continue
                    
                if char == '\\' and in_string:
                    escape_next = True
                    continue
                    
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                
                if not in_string:
                    if char == '[':
                        bracket_count += 1
                    elif char == ']':
                        bracket_count -= 1
                        if bracket_count == 0:
                            json_end = i + 1
                            break
            
            json_str = html_content[json_start:json_end]
            products = json.loads(json_str)
            return products
            
        except json.JSONDecodeError as e:
            self.status_callback(f"Error parsing product JSON: {str(e)}")
            return []
        except Exception as e:
            self.status_callback(f"Error extracting product list: {str(e)}")
            return []
    
    def _parse_product_from_json(self, product_json: Dict) -> BarboraProductInfo:
        """Convert a single product JSON object to BarboraProductInfo"""
        
        price = None
        if 'price' in product_json and product_json['price'] is not None:
            price = float(product_json['price'])
        
        retail_price = None
        if 'retail_price' in product_json and product_json['retail_price'] is not None:
            retail_price = float(product_json['retail_price'])
        
        comparative_unit_price = None
        if 'comparative_unit_price' in product_json and product_json['comparative_unit_price'] is not None:
            comparative_unit_price = float(product_json['comparative_unit_price'])
        
        is_available = product_json.get('status', '').lower() == 'active'
        
        product_url = ""
        if 'Url' in product_json and product_json['Url']:
            product_url = self.build_product_url(product_json['Url'])
        
        return BarboraProductInfo(
            sku=product_json.get('id', ''),
            name=product_json.get('title', ''),
            price=price,
            url=product_url,
            barbora_category_code=product_json.get('category_id'),
            category_path=product_json.get('category_path_url'),
            brand_name=product_json.get('brand_name'),
            image_url=product_json.get('image'),
            big_image_url=product_json.get('big_image'),
            comparative_unit=product_json.get('comparative_unit'),
            comparative_unit_price=comparative_unit_price,
            retail_price=retail_price,
            status=product_json.get('status', 'active'),
            is_available=is_available,
            promotion=product_json.get('promotion'),
            is_made_in_eu=product_json.get('is_made_in_Eu', False),
            is_made_in_home_country=product_json.get('is_made_in_Home_Country', False),
        )
    
    def get_pagination_info(self, category_url: str) -> Tuple[int, int]:
        """
        Get pagination info for a category page
        
        Returns:
            Tuple of (total_pages, products_on_first_page)
        """
        try:
            self.status_callback(f"Fetching category page: {category_url}")
            response = self.session.get(category_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            products = self._extract_product_list_json(response.text)
            products_on_page = len(products)
            self.status_callback(f"Found {products_on_page} products on page")
            
            max_page = 1
            pagination = soup.find('ul', class_='pagination')
            if pagination:
                page_links = pagination.find_all('a', href=True)
                for link in page_links:
                    href = link.get('href', '')
                    page_match = re.search(r'\?page=(\d+)', href)
                    if page_match:
                        page_num = int(page_match.group(1))
                        max_page = max(max_page, page_num)
                    
                    text = link.get_text(strip=True)
                    if text.isdigit():
                        page_num = int(text)
                        max_page = max(max_page, page_num)
            
            self.status_callback(f"Total pages: {max_page}")
            return max_page, products_on_page
            
        except Exception as e:
            self.status_callback(f"Error getting pagination info: {str(e)}")
            return 1, 0
    
    def extract_products_from_category(self, category_path: str, max_pages: int = 100) -> List[BarboraProductInfo]:
        """
        Extract all products from a category (all pages)
        
        Args:
            category_path: Normalized category path like "piena-produkti-un-olas/piens/uht-piens"
            max_pages: Maximum pages to fetch
            
        Returns:
            List of BarboraProductInfo objects
        """
        all_products = []
        page = 1
        
        while page <= max_pages:
            url = self.build_category_url(category_path, page)
            self.status_callback(f"Fetching page {page}: {url}")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                
                products_json = self._extract_product_list_json(response.text)
                
                if not products_json:
                    self.status_callback(f"No products found on page {page}, stopping")
                    break
                
                for product_data in products_json:
                    product = self._parse_product_from_json(product_data)
                    all_products.append(product)
                
                self.status_callback(f"Page {page}: extracted {len(products_json)} products (total: {len(all_products)})")
                
                if len(products_json) < self.PRODUCTS_PER_PAGE:
                    self.status_callback("Last page reached (fewer products than page size)")
                    break
                
                page += 1
                time.sleep(random.uniform(0.5, 1.5))
                
            except requests.RequestException as e:
                self.status_callback(f"Error fetching page {page}: {str(e)}")
                break
        
        return all_products
    
    def extract_products_from_single_page(self, category_path: str, page: int = 1) -> List[BarboraProductInfo]:
        """
        Extract products from a single category page
        
        Args:
            category_path: Normalized category path
            page: Page number
            
        Returns:
            List of BarboraProductInfo objects
        """
        url = self.build_category_url(category_path, page)
        self.status_callback(f"Fetching: {url}")
        
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            products_json = self._extract_product_list_json(response.text)
            products = [self._parse_product_from_json(p) for p in products_json]
            
            self.status_callback(f"Extracted {len(products)} products")
            return products
            
        except Exception as e:
            self.status_callback(f"Error: {str(e)}")
            return []
    
    def _parse_nutrition_value(self, value_text: str) -> Optional[float]:
        """Parse nutrition value from text like '3,20 g' or '249,00 kJ'"""
        try:
            match = re.search(r'([\d,\.]+)', value_text)
            if match:
                value_str = match.group(1).replace(',', '.')
                return float(value_str)
            return None
        except:
            return None
    
    def extract_product_details(self, product_url: str) -> Optional[BarboraProductDetails]:
        """
        Extract full product details from individual product page
        
        Args:
            product_url: Full product URL or slug
            
        Returns:
            BarboraProductDetails with nutrition, ingredients, etc.
        """
        if not product_url.startswith('http'):
            product_url = self.build_product_url(product_url)
        
        self.status_callback(f"Fetching product details: {product_url}")
        
        try:
            response = self.session.get(product_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            sku = ""
            ga4_pattern = r'window\.reportUserActionToGa4\(window\.ga4EventTypes\.viewItem,\s*\{[^}]*items:\s*\[(\{[^}]+\})\]'
            ga4_match = re.search(ga4_pattern, response.text, re.DOTALL)
            if ga4_match:
                try:
                    item_json = json.loads(ga4_match.group(1))
                    sku = item_json.get('item_id', '')
                except:
                    pass
            
            name = ""
            title_elem = soup.find('h1')
            if title_elem:
                name = title_elem.get_text(strip=True)
            
            description = None
            ingredients = None
            allergens = None
            
            info_sections = soup.find_all('dt', class_='b-product-info--info-3-title')
            for dt in info_sections:
                title_text = dt.get_text(strip=True).lower()
                dd = dt.find_next_sibling('dd')
                if dd:
                    value = dd.get_text(strip=True)
                    
                    if 'apraksts' in title_text:
                        description = value
                    elif 'sastāvdaļas' in title_text:
                        ingredients = value
                    elif 'alergēni' in title_text:
                        allergens = value
            
            photo_urls = []
            slider_slides = soup.find_all('div', class_='b-block-slider--slide')
            for slide in slider_slides:
                img = slide.find('img', src=True)
                if img:
                    src = img.get('src', '')
                    if src and 'cdn.barbora.lv' in src and 'no-image-placeholder' not in src:
                        photo_urls.append(src)
            
            country_of_origin = None
            brand = None
            net_quantity = None
            
            other_info_dl = soup.find('dl', class_='b-dl-align-left')
            if other_info_dl:
                dts = other_info_dl.find_all('dt')
                for dt in dts:
                    dt_text = dt.get_text(strip=True).lower()
                    dd = dt.find_next_sibling('dd')
                    if dd:
                        dd_text = dd.get_text(strip=True)
                        
                        if 'izcelsmes valsts' in dt_text:
                            country_of_origin = dd_text
                        elif 'zīmols' in dt_text:
                            brand = dd_text
                        elif 'neto daudzums' in dt_text:
                            net_quantity = dd_text
            
            nutrition = BarboraNutritionInfo()
            nutrition_title = soup.find('h3', class_='b-product-info--info-3-title', 
                                        string=re.compile(r'Uzturvērtība', re.IGNORECASE))
            if nutrition_title:
                nutrition_table = nutrition_title.find_next('table')
                if nutrition_table:
                    rows = nutrition_table.find_all('tr')
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) >= 2:
                            label = cells[0].get_text(strip=True).lower()
                            value_text = cells[1].get_text(strip=True)
                            value = self._parse_nutrition_value(value_text)
                            
                            if 'enerģētiskā' in label:
                                if 'kj' in value_text.lower():
                                    nutrition.energy_kj = value
                                    kcal_match = re.search(r'([\d,\.]+)\s*kcal', value_text, re.IGNORECASE)
                                    if kcal_match:
                                        nutrition.energy_kcal = float(kcal_match.group(1).replace(',', '.'))
                            elif label == 'tauki' or 'tauki' in label and 'piesātināt' not in label:
                                nutrition.fat = value
                            elif 'piesātināt' in label:
                                nutrition.saturated_fat = value
                            elif 'ogļhidrāti' in label:
                                nutrition.carbohydrates = value
                            elif 'cukur' in label:
                                nutrition.sugars = value
                            elif 'olbaltumvielas' in label or 'proteīn' in label:
                                nutrition.protein = value
                            elif 'sāls' in label:
                                nutrition.salt = value
                            elif 'šķiedrvielas' in label:
                                nutrition.fiber = value
            
            return BarboraProductDetails(
                sku=sku,
                name=name,
                description=description,
                ingredients=ingredients,
                allergens=allergens,
                nutrition=nutrition,
                country_of_origin=country_of_origin,
                weight=net_quantity,
                photo_urls=photo_urls if photo_urls else None,
            )
            
        except Exception as e:
            self.status_callback(f"Error extracting product details: {str(e)}")
            return None
    
    def collect_category_skus(self, category_path: str) -> List[str]:
        """
        Collect all SKUs from a category (all pages)
        
        Args:
            category_path: Normalized category path like "piena-produkti-un-olas/piens/uht-piens"
            
        Returns:
            List of SKU strings
        """
        products = self.extract_products_from_category(category_path)
        skus = [p.sku for p in products if p.sku]
        self.status_callback(f"Collected {len(skus)} SKUs from category")
        return skus
    
    def get_total_products_count(self, category_path: str) -> Tuple[int, int]:
        """
        Get total product count for a category
        
        Returns:
            Tuple of (total_products, total_pages)
        """
        total_pages, first_page_count = self.get_pagination_info(
            self.build_category_url(category_path)
        )
        
        if total_pages == 1:
            return first_page_count, 1
        
        if total_pages > 1:
            last_page_url = self.build_category_url(category_path, total_pages)
            try:
                response = self.session.get(last_page_url, timeout=15)
                products_json = self._extract_product_list_json(response.text)
                last_page_count = len(products_json)
                
                total_products = (total_pages - 1) * self.PRODUCTS_PER_PAGE + last_page_count
                self.status_callback(f"Total: ({total_pages}-1) × {self.PRODUCTS_PER_PAGE} + {last_page_count} = {total_products}")
                return total_products, total_pages
                
            except Exception as e:
                self.status_callback(f"Error counting products: {str(e)}")
                estimated_total = total_pages * self.PRODUCTS_PER_PAGE
                return estimated_total, total_pages
        
        return first_page_count, 1


def test_parser():
    """Test the parser with UHT milk category"""
    def status_print(msg):
        print(f"[STATUS] {msg}")
    
    parser = BarboraParser(status_callback=status_print)
    
    print("\n=== Testing Category Parsing ===")
    category_path = "piena-produkti-un-olas/piens/uht-piens"
    
    products = parser.extract_products_from_single_page(category_path)
    print(f"\nFound {len(products)} products:")
    for i, p in enumerate(products[:3], 1):
        print(f"\n{i}. {p.name}")
        print(f"   SKU: {p.sku}")
        print(f"   Price: €{p.price}")
        print(f"   Brand: {p.brand_name}")
        print(f"   Unit: {p.comparative_unit} @ €{p.comparative_unit_price}")
        print(f"   URL: {p.url}")
    
    if products:
        print("\n=== Testing Product Details ===")
        details = parser.extract_product_details(products[0].url)
        if details:
            print(f"Name: {details.name}")
            print(f"Description: {details.description}")
            print(f"Ingredients: {details.ingredients}")
            print(f"Allergens: {details.allergens}")
            if details.nutrition:
                n = details.nutrition
                print(f"Nutrition (per 100g/ml):")
                print(f"  Energy: {n.energy_kj} kJ / {n.energy_kcal} kcal")
                print(f"  Fat: {n.fat}g (saturated: {n.saturated_fat}g)")
                print(f"  Carbs: {n.carbohydrates}g (sugars: {n.sugars}g)")
                print(f"  Protein: {n.protein}g")


if __name__ == "__main__":
    test_parser()
