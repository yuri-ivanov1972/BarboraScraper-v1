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
from barbora_site_data import (SiteDataError, category_page, product_data,
                               detail_values, query_data, verify_category_path)


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
    retail_unit_price: Optional[float] = None
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
    brand: Optional[str] = None
    producer: Optional[str] = None
    distributor_name: Optional[str] = None
    brand_name: Optional[str] = None
    producer_name: Optional[str] = None
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
        if product_url_slug.startswith(("p/", "produkti/")):
            return f"{self.BASE_URL}/{product_url_slug}"
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
        if "window.__remixContext" in html_content:
            data = query_data(html_content, "inventoryCategoryInventory")
            if data is None:
                raise SiteDataError("category_listing_unrecognized")
            page = data["offset"] // data["limit"] + 1
            return category_page(html_content, page)["products"]
        if not re.search(r"window\.b_productList\s*=", html_content):
            raise SiteDataError("category_listing_unrecognized")
        marker = re.search(r"window\.b_productList\s*=\s*", html_content)
        try:
            products, _ = json.JSONDecoder().raw_decode(html_content[marker.end():].lstrip())
            if not isinstance(products, list):
                raise SiteDataError("invalid_legacy_listing")
            return products
        except (ValueError, TypeError):
            raise SiteDataError("invalid_legacy_listing") from None
    
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
            retail_unit_price=(product_json.get("promotion") or {}).get("oldComparativeRate"),
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
            if "window.__remixContext" in response.text:
                data = category_page(response.text)
                return max(1, (data["count"] + data["limit"] - 1) // data["limit"]), len(data["products"])
            
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
            raise
    
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
        seen = set()
        expected = None
        expected_short = None
        page = 1
        
        while page <= max_pages:
            url = self.build_category_url(category_path, page)
            self.status_callback(f"Fetching page {page}: {url}")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                
                modern = "window.__remixContext" in response.text
                if modern:
                    metadata = category_page(response.text, page, expected_short)
                    verify_category_path(metadata, category_path)
                    expected_short = metadata["short_id"]
                    if expected is not None and expected != metadata["count"]:
                        raise SiteDataError("category_count_changed")
                    expected = metadata["count"]
                    products_json = metadata["products"]
                else:
                    products_json = self._extract_product_list_json(response.text)
                
                if not products_json:
                    self.status_callback(f"No products found on page {page}, stopping")
                    break
                
                for product_data in products_json:
                    product = self._parse_product_from_json(product_data)
                    if product.sku in seen:
                        raise SiteDataError("repeated_pagination_sku")
                    seen.add(product.sku)
                    all_products.append(product)
                
                self.status_callback(f"Page {page}: extracted {len(products_json)} products (total: {len(all_products)})")
                
                if (modern and len(all_products) == expected) or (
                        not modern and len(products_json) < self.PRODUCTS_PER_PAGE):
                    self.status_callback("Last page reached (fewer products than page size)")
                    break
                
                page += 1
                time.sleep(random.uniform(0.5, 1.5))
                
            except requests.RequestException as e:
                self.status_callback(f"Error fetching page {page}: {str(e)}")
                raise SiteDataError("category_request_failed") from None
        if expected is not None and len(all_products) != expected:
            raise SiteDataError("category_page_limit")
        if page > max_pages:
            raise SiteDataError("category_page_limit")
        
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
            
            if "window.__remixContext" in response.text:
                metadata = category_page(response.text, page)
                verify_category_path(metadata, category_path)
                products_json = metadata["products"]
            else:
                products_json = self._extract_product_list_json(response.text)
            products = [self._parse_product_from_json(p) for p in products_json]
            
            self.status_callback(f"Extracted {len(products)} products")
            return products
            
        except Exception as e:
            self.status_callback(f"Error: {str(e)}")
            raise
    
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
            return self.parse_product_details(response.text)
        except Exception as e:
            self.status_callback(f"Error extracting product details: {str(e)}")
            return None

    def parse_product_details(self, html: str) -> Optional[BarboraProductDetails]:
        modern = product_data(html)
        if modern is not None:
            values = detail_values(modern, html)
            values.pop("nutrition_issue")
            nutrients = values.pop("nutrition")
            mapping = dict(fat_total="fat", fat_saturated="saturated_fat",
                           carbs_total="carbohydrates", carbs_sugars="sugars")
            values["nutrition"] = BarboraNutritionInfo(**{
                mapping.get(k, k): v for k, v in nutrients.items()
            }) if nutrients else None
            return BarboraProductDetails(**values)
        """Parse already fetched HTML without network or database side effects."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            sku = ""
            ga4_pattern = r'window\.reportUserActionToGa4\(window\.ga4EventTypes\.viewItem,\s*\{[^}]*items:\s*\[(\{[^}]+\})\]'
            ga4_match = re.search(ga4_pattern, html, re.DOTALL)
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
            producer = None
            distributor = None
            net_quantity = None
            
            other_info_dl = soup.find('dl', class_='b-dl-align-left')
            # Prefer the product metadata list, but tolerate pages where Barbora
            # moves these labels to another definition list.
            dts = other_info_dl.find_all('dt') if other_info_dl else soup.find_all('dt')
            if other_info_dl:
                outside_dts = [dt for dt in soup.find_all('dt') if dt not in dts]
                dts.extend(outside_dts)
            for dt in dts:
                # Use the adjacent dd only. This avoids accidentally pairing
                # a label with a later metadata value when markup changes.
                dt_text = re.sub(r'\s+', ' ', dt.get_text(" ", strip=True)).strip().lower()
                dd = dt.find_next_sibling('dd')
                if dd:
                    dd_text = re.sub(r'\s+', ' ', dd.get_text(" ", strip=True)).strip()
                    if not dd_text:
                        dd_text = None
                        
                    if 'izcelsmes valsts' in dt_text:
                        country_of_origin = dd_text
                    elif 'zīmols' in dt_text:
                        brand = dd_text
                    elif 'ražotājs' in dt_text or 'razotajs' in dt_text:
                        producer = dd_text
                    elif 'piegādātāja kontaktinformācija' in dt_text or 'piegadataja kontaktinformacija' in dt_text:
                        distributor = dd_text
                    elif 'neto daudzums' in dt_text:
                        net_quantity = dd_text

            # Some Barbora metadata variants use adjacent spans instead of a
            # definition list. Pair only direct span siblings so a label can
            # never capture an unrelated value farther down the page.
            for label_span in soup.find_all('span'):
                label_text = re.sub(
                    r'\s+', ' ', label_span.get_text(" ", strip=True)
                ).strip().lower().rstrip(':').strip()
                if label_text not in {
                    'zīmols', 'ražotājs', 'razotajs',
                    'piegādātāja kontaktinformācija',
                    'piegadataja kontaktinformacija',
                }:
                    continue
                value_span = label_span.next_sibling
                while (
                    value_span is not None
                    and isinstance(value_span, str)
                    and not value_span.strip()
                ):
                    value_span = value_span.next_sibling
                if value_span is None or getattr(value_span, 'name', None) != 'span':
                    continue
                value = re.sub(
                    r'\s+', ' ', value_span.get_text(" ", strip=True)
                ).strip() or None
                if label_text == 'zīmols' and brand is None:
                    brand = value
                elif label_text in {'ražotājs', 'razotajs'} and producer is None:
                    producer = value
                elif label_text in {
                    'piegādātāja kontaktinformācija',
                    'piegadataja kontaktinformacija',
                } and distributor is None:
                    distributor = value

            # Distributor information is the best available producer proxy
            # when Barbora omits or leaves the producer field blank.
            producer_value = producer or distributor
            
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
                manufacturer=producer_value,
                brand=brand,
                producer=producer_value,
                distributor_name=distributor,
                brand_name=brand,
                producer_name=producer_value,
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
        response = self.session.get(self.build_category_url(category_path), timeout=15)
        response.raise_for_status()
        if "window.__remixContext" in response.text:
            data = category_page(response.text)
            verify_category_path(data, category_path)
            return data["count"], max(1, (data["count"] + data["limit"] - 1) // data["limit"])
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
                raise
        
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
