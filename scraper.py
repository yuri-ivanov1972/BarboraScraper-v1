import requests
from bs4 import BeautifulSoup
import logging
from decimal import Decimal
import re

class RimiScraper:
    def __init__(self):
        self.base_url = "https://www.rimi.lv/e-veikals/lv"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,lv;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }

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
            # Using the search endpoint with empty query to get all products
            url = f"{self.base_url}/meklesana"
            logging.info(f"Scraping URL: {url}")

            response = requests.get(url, headers=self.headers)
            response.raise_for_status()

            logging.info(f"Response status: {response.status_code}")
            logging.info(f"Response headers: {response.headers}")

            soup = BeautifulSoup(response.text, 'html.parser')
            products_list = []

            # Find all product cards - using the correct product grid selector
            products = soup.select('div.product-grid__item')
            logging.info(f"Found {len(products)} products")

            for product in products:
                try:
                    # Extract product link and name
                    link_elem = product.select_one('a.card__url')
                    if not link_elem:
                        logging.warning("No link element found for product")
                        continue

                    product_url = 'https://www.rimi.lv' + link_elem['href'] if link_elem else None
                    name = link_elem.text.strip() if link_elem else None

                    # Extract price
                    price_elem = product.select_one('div.price-tag__price')
                    price_text = price_elem.text.strip() if price_elem else '0.00'
                    price = self.clean_price(price_text)

                    # Extract price per unit
                    price_unit_elem = product.select_one('div.price-tag__unit')
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