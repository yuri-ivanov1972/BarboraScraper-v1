#!/usr/bin/env python3
"""
Enhanced scraper that integrates with external databases for comprehensive coverage
"""
import logging
import time
import random
from typing import List, Dict, Optional, Set
from database_integration import ExternalDatabaseManager, CategoryInfo
from scraper import RimiScraper, NutritionalInfo
from database import Database
from datetime import datetime, timedelta

class EnhancedRimiScraper:
    """Enhanced scraper with external database integration"""
    
    def __init__(self, status_callback=None):
        self.ext_db = ExternalDatabaseManager()
        self.scraper = RimiScraper(status_callback)
        self.local_db = Database()
        self.status_callback = status_callback or (lambda x: None)
        
        # Configuration
        self.max_products_per_session = 1000
        self.delay_between_categories = (1, 3)  # Random delay in seconds  
        self.delay_between_products = (0.5, 1.5)
    
    def get_scraping_plan(self) -> Dict:
        """Create a comprehensive scraping plan"""
        self.status_callback("Creating scraping plan...")
        
        # Get categories to scrape
        categories = self.ext_db.get_all_categories()
        category_urls = self.ext_db.get_category_urls()
        
        # Get existing products for comparison
        existing_products = self.ext_db.get_existing_products()
        stale_products = self.ext_db.get_products_needing_update(7)
        
        plan = {
            'total_categories': len(categories),
            'category_urls': category_urls,
            'existing_products': len(existing_products),
            'stale_products': len(stale_products),
            'estimated_time_hours': len(category_urls) * 0.5,  # Rough estimate
            'strategy': 'COMPREHENSIVE_UPDATE'
        }
        
        self.status_callback(f"Plan created: {plan['total_categories']} categories, {plan['existing_products']} existing products")
        return plan
    
    def scrape_with_external_integration(self, max_categories: int = 10) -> Dict:
        """Enhanced scraping with external database integration"""
        results = {
            'categories_processed': 0,
            'new_products': 0,
            'updated_products': 0,
            'nutrition_added': 0,
            'errors': [],
            'start_time': datetime.now(),
            'end_time': None
        }
        
        try:
            # Get scraping plan
            plan = self.get_scraping_plan()
            category_urls = plan['category_urls'][:max_categories]
            
            self.status_callback(f"Starting enhanced scraping of {len(category_urls)} categories")
            
            # Process each category
            for i, category_url in enumerate(category_urls):
                try:
                    self.status_callback(f"Processing category {i+1}/{len(category_urls)}: {category_url}")
                    
                    # Set up scraper for this category
                    self.scraper.category_urls = [category_url]
                    
                    # Scrape products from this category
                    products_with_nutrition = self.scraper.scrape_products()
                    
                    if products_with_nutrition:
                        # Save to local database
                        new_count, updated_count = self.local_db.save_products_with_nutrition(products_with_nutrition)
                        
                        results['new_products'] += new_count
                        results['updated_products'] += updated_count
                        results['nutrition_added'] += len([p for p in products_with_nutrition if p['nutrition'].ingredients])
                        
                        self.status_callback(f"Category complete: {new_count} new, {updated_count} updated products")
                    
                    results['categories_processed'] += 1
                    
                    # Delay between categories to avoid rate limiting
                    if i < len(category_urls) - 1:
                        delay = random.uniform(*self.delay_between_categories)
                        self.status_callback(f"Waiting {delay:.1f}s before next category...")
                        time.sleep(delay)
                        
                except Exception as e:
                    error_msg = f"Error processing category {category_url}: {str(e)}"
                    self.status_callback(error_msg)
                    results['errors'].append(error_msg)
                    continue
            
            results['end_time'] = datetime.now()
            duration = results['end_time'] - results['start_time']
            
            self.status_callback(f"Scraping complete! Duration: {duration}")
            self.status_callback(f"Results: {results['new_products']} new, {results['updated_products']} updated products")
            
            return results
            
        except Exception as e:
            results['end_time'] = datetime.now()
            error_msg = f"Critical scraping error: {str(e)}"
            self.status_callback(error_msg)
            results['errors'].append(error_msg)
            return results
    
    def update_stale_products(self, max_products: int = 100) -> Dict:
        """Update products that haven't been refreshed recently"""
        results = {
            'products_checked': 0,
            'products_updated': 0,
            'products_removed': 0,
            'errors': []
        }
        
        try:
            # Get stale products from external database
            stale_skus = self.ext_db.get_products_needing_update(7)[:max_products]
            existing_products = self.ext_db.get_existing_products()
            
            self.status_callback(f"Updating {len(stale_skus)} stale products...")
            
            for sku in stale_skus:
                try:
                    if sku in existing_products:
                        product = existing_products[sku]
                        
                        # Scrape current product data
                        products_with_nutrition = self.scraper.scrape_specific_products([product.rimi_url])
                        
                        if products_with_nutrition:
                            # Update in local database
                            new_count, updated_count = self.local_db.save_products_with_nutrition(products_with_nutrition)
                            results['products_updated'] += updated_count
                        else:
                            # Product might be discontinued
                            self.status_callback(f"Product {sku} may be discontinued")
                            results['products_removed'] += 1
                        
                        results['products_checked'] += 1
                        
                        # Small delay between products
                        time.sleep(random.uniform(*self.delay_between_products))
                        
                except Exception as e:
                    error_msg = f"Error updating product {sku}: {str(e)}"
                    results['errors'].append(error_msg)
                    continue
            
            self.status_callback(f"Stale product update complete: {results['products_updated']} updated")
            return results
            
        except Exception as e:
            error_msg = f"Error in stale product update: {str(e)}"
            results['errors'].append(error_msg)
            return results
    
    def get_scraping_status(self) -> Dict:
        """Get current scraping system status"""
        try:
            nutrition_stats = self.ext_db.get_nutrition_coverage()
            existing_products = self.ext_db.get_existing_products()
            stale_products = self.ext_db.get_products_needing_update(7)
            
            return {
                'total_products': len(existing_products),
                'stale_products': len(stale_products),
                'nutrition_coverage': nutrition_stats,
                'last_check': datetime.now().isoformat(),
                'system_ready': True
            }
            
        except Exception as e:
            return {
                'error': str(e),
                'system_ready': False
            }

def main():
    """Test the enhanced scraper"""
    def status_callback(msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    
    enhanced_scraper = EnhancedRimiScraper(status_callback)
    
    # Get system status
    status = enhanced_scraper.get_scraping_status()
    print("System Status:")
    print(f"Total products: {status.get('total_products', 0):,}")
    print(f"Stale products: {status.get('stale_products', 0):,}")
    print(f"Nutrition coverage: {status.get('nutrition_coverage', {})}")
    
    # Test scraping a few categories
    print("\nStarting test scrape...")
    results = enhanced_scraper.scrape_with_external_integration(max_categories=2)
    print(f"Test complete: {results}")

if __name__ == "__main__":
    main()