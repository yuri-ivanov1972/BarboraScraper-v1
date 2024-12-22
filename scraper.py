import requests
from bs4 import BeautifulSoup
import logging
from decimal import Decimal
import re

class RimiScraper:
    def __init__(self):
        self.base_url = "https://www.rimi.lv/e-veikals/lv/meklesana"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    def clean_price(self, price_str):
        """Clean and convert price string to Decimal"""
        try:
            # Remove € symbol and replace comma with dot
            clean_price = price_str.replace('€', '').replace(',', '.').strip()
            return Decimal(clean_price)
        except Exception as e:
            logging.error(f"Price conversion error: {str(e)}")
            return Decimal('0.00')

    def extract_sku(self, url):
        """Extract SKU from product URL"""
        try:
            return url.split('/')[-1].split('-')[-1]
        except Exception:
            return None

    def extract_category(self, url):
        """Extract category path from product URL"""
        try:
            parts = url.split('/')
            start_idx = parts.index('produkti')
            return '/'.join(parts[start_idx+1:-1])
        except Exception:
            return None

    def scrape_products(self):
        """Scrape product information from Rimi online store"""
        try:
            response = requests.get(self.base_url, headers=self.headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            products_list = []
            
            # Find all product cards
            products = soup.find_all('div', class_='product-grid__item')
            
            for product in products:
                try:
                    # Extract product link and name
                    link_elem = product.find('a', class_='card__url')
                    product_url = 'https://www.rimi.lv' + link_elem['href'] if link_elem else None
                    name = link_elem.text.strip() if link_elem else None
                    
                    # Extract price
                    price_elem = product.find('div', class_='price-tag__price-value')
                    price = self.clean_price(price_elem.text) if price_elem else Decimal('0.00')
                    
                    # Extract price per unit
                    price_unit_elem = product.find('div', class_='price-tag__unit')
                    price_per_unit = price_unit_elem.text.strip() if price_unit_elem else None
                    
                    # Extract SKU and category from URL
                    sku = self.extract_sku(product_url) if product_url else None
                    category = self.extract_category(product_url) if product_url else None
                    
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
            
            return products_list
            
        except Exception as e:
            logging.error(f"Scraping error: {str(e)}")
            return []
