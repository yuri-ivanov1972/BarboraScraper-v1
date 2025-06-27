#!/usr/bin/env python3
"""
Product Matcher - Exact comparison between Rimi website and database products
Identifies new products, missing products, and changes
"""
import time
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass
from core_parser import RimiParser, DatabaseConnection, ProductInfo

@dataclass
class ProductMatch:
    sku: str
    name: str
    status: str  # 'new', 'missing', 'matched', 'changed'
    website_data: Optional[ProductInfo] = None
    database_data: Optional[Dict] = None
    changes: Optional[Dict] = None

@dataclass
class ComparisonResult:
    category_code: str
    total_website_products: int
    total_database_products: int
    new_products: List[ProductMatch]
    missing_products: List[ProductMatch]
    matched_products: List[ProductMatch]
    changed_products: List[ProductMatch]
    
    def get_summary(self) -> Dict:
        return {
            'category': self.category_code,
            'website_total': self.total_website_products,
            'database_total': self.total_database_products,
            'new_count': len(self.new_products),
            'missing_count': len(self.missing_products),
            'matched_count': len(self.matched_products),
            'changed_count': len(self.changed_products)
        }

class ProductMatcher:
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda x: None)
        self.parser = RimiParser(self.status_callback)
        self.db = DatabaseConnection()
    
    def get_all_website_products(self, category_code: str) -> List[ProductInfo]:
        """Get all products from website for the category"""
        self.status_callback(f"Fetching all website products for {category_code}")
        
        # Get pagination info
        category_url = self.parser.build_category_url(category_code)
        total_products, total_pages = self.parser.get_total_products_from_pagination(category_url)
        
        self.status_callback(f"Found {total_pages} pages with {total_products} products on website")
        
        all_products = []
        
        # Fetch products from all pages
        for page in range(1, total_pages + 1):
            self.status_callback(f"Fetching page {page}/{total_pages}")
            page_url = f"{category_url}?pageSize=20&currentPage={page}"
            
            try:
                page_products = self.parser.extract_products_from_page(page_url)
                all_products.extend(page_products)
                
                # Small delay to be respectful to the server
                time.sleep(0.5)
                
            except Exception as e:
                self.status_callback(f"Error fetching page {page}: {str(e)}")
                continue
        
        self.status_callback(f"Successfully fetched {len(all_products)} products from website")
        return all_products
    
    def get_all_database_products(self, category_code: str) -> List[Dict]:
        """Get all products from database for the category"""
        self.status_callback(f"Fetching all database products for {category_code}")
        
        db_products = self.db.get_products_for_category(category_code)
        
        self.status_callback(f"Found {len(db_products)} products in database")
        return db_products
    
    def compare_products(self, category_code: str) -> ComparisonResult:
        """Compare website vs database products and identify differences"""
        self.status_callback(f"Starting product comparison for {category_code}")
        
        # Get all products from both sources
        website_products = self.get_all_website_products(category_code)
        database_products = self.get_all_database_products(category_code)
        
        # Create lookup dictionaries
        website_by_sku = {p.sku: p for p in website_products}
        database_by_sku = {p['sku']: p for p in database_products}
        
        website_skus = set(website_by_sku.keys())
        database_skus = set(database_by_sku.keys())
        
        self.status_callback(f"Comparing {len(website_skus)} website SKUs vs {len(database_skus)} database SKUs")
        
        # Find differences
        new_skus = website_skus - database_skus
        missing_skus = database_skus - website_skus
        common_skus = website_skus & database_skus
        
        # Build results
        new_products = []
        missing_products = []
        matched_products = []
        changed_products = []
        
        # New products (on website but not in database)
        for sku in new_skus:
            website_product = website_by_sku[sku]
            new_products.append(ProductMatch(
                sku=sku,
                name=website_product.name,
                status='new',
                website_data=website_product,
                database_data=None
            ))
        
        # Missing products (in database but not on website)
        for sku in missing_skus:
            db_product = database_by_sku[sku]
            missing_products.append(ProductMatch(
                sku=sku,
                name=db_product['name'],
                status='missing',
                website_data=None,
                database_data=db_product
            ))
        
        # Common products - check for changes
        for sku in common_skus:
            website_product = website_by_sku[sku]
            db_product = database_by_sku[sku]
            
            changes = self._detect_changes(website_product, db_product)
            
            if changes:
                changed_products.append(ProductMatch(
                    sku=sku,
                    name=website_product.name,
                    status='changed',
                    website_data=website_product,
                    database_data=db_product,
                    changes=changes
                ))
            else:
                matched_products.append(ProductMatch(
                    sku=sku,
                    name=website_product.name,
                    status='matched',
                    website_data=website_product,
                    database_data=db_product
                ))
        
        self.status_callback(f"Comparison complete: {len(new_products)} new, {len(missing_products)} missing, {len(changed_products)} changed, {len(matched_products)} matched")
        
        return ComparisonResult(
            category_code=category_code,
            total_website_products=len(website_products),
            total_database_products=len(database_products),
            new_products=new_products,
            missing_products=missing_products,
            matched_products=matched_products,
            changed_products=changed_products
        )
    
    def _detect_changes(self, website_product: ProductInfo, db_product: Dict) -> Optional[Dict]:
        """Detect changes between website and database product"""
        changes = {}
        
        # Compare names
        if website_product.name.strip() != db_product['name'].strip():
            changes['name'] = {
                'website': website_product.name,
                'database': db_product['name']
            }
        
        # Compare prices (if available)
        if website_product.price and website_product.price != 'N/A':
            # Normalize price format for comparison
            website_price = website_product.price.replace('€', '').strip()
            if website_price != str(db_product.get('price', '')):
                changes['price'] = {
                    'website': website_product.price,
                    'database': db_product.get('price', 'N/A')
                }
        
        # Compare URLs
        if website_product.url and db_product.get('rimi_url'):
            if website_product.url != db_product['rimi_url']:
                changes['url'] = {
                    'website': website_product.url,
                    'database': db_product['rimi_url']
                }
        
        return changes if changes else None
    
    def get_sample_new_products(self, comparison_result: ComparisonResult, limit: int = 20) -> List[ProductMatch]:
        """Get a sample of new products for display"""
        return comparison_result.new_products[:limit]
    
    def get_sample_missing_products(self, comparison_result: ComparisonResult, limit: int = 20) -> List[ProductMatch]:
        """Get a sample of missing products for display"""
        return comparison_result.missing_products[:limit]

if __name__ == "__main__":
    def test_callback(msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}")
    
    # Test the matcher
    matcher = ProductMatcher(test_callback)
    
    # Test with a smaller category first
    test_category = "SH-12-1-1"  # Ice category - should have fewer products
    
    result = matcher.compare_products(test_category)
    
    print(f"\n=== Comparison Results for {test_category} ===")
    summary = result.get_summary()
    for key, value in summary.items():
        print(f"{key}: {value}")
    
    if result.new_products:
        print(f"\nSample new products:")
        for i, product in enumerate(result.new_products[:5], 1):
            print(f"  {i}. {product.sku}: {product.name[:50]}...")
    
    if result.missing_products:
        print(f"\nSample missing products:")
        for i, product in enumerate(result.missing_products[:5], 1):
            print(f"  {i}. {product.sku}: {product.name[:50]}...")