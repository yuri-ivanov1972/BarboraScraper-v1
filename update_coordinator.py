#!/usr/bin/env python3
"""
Update Coordinator - Orchestrates database updates with scraper integration
Handles the complete update workflow including product comparison and processing
"""
import time
from typing import Dict, List, Set, Tuple, Any
from datetime import datetime
from database_updater import DatabaseUpdater
from ingredient_processor import IngredientProcessor
from product_matcher import ProductMatcher

class UpdateCoordinator:
    """Coordinates the complete database update process"""
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda x: None)
        self.db_updater = DatabaseUpdater(self.status_callback)
        self.ingredient_processor = IngredientProcessor(self.status_callback)
        self.product_matcher = ProductMatcher(self.status_callback)
        
        # Track products without nutrition facts
        self.products_without_nutrition = []
    
    def perform_category_update(self, category_code: str) -> Dict:
        """
        Perform complete update for a category
        
        Args:
            category_code: Category to update (e.g., 'SH-12-1-1')
            
        Returns:
            Dictionary with update results and statistics
        """
        start_time = datetime.now()
        self.status_callback(f"Starting update for category {category_code}")
        
        update_results = {
            'category': category_code,
            'start_time': start_time,
            'new_products_added': 0,
            'prices_updated': 0,
            'products_marked_unavailable': 0,
            'nutrition_data_added': 0,
            'ingredients_processed': 0,
            'products_without_nutrition': [],
            'errors': [],
            'processing_time': None
        }
        
        try:
            # Step 1: Get product comparison results
            self.status_callback("Comparing website vs database products")
            comparison_result = self.product_matcher.compare_products(category_code)
            
            # Step 2: Process new products
            if comparison_result.new_products:
                self.status_callback(f"Processing {len(comparison_result.new_products)} new products")
                new_results = self._process_new_products(comparison_result.new_products, category_code)
                update_results.update(new_results)
            
            # Step 3: Update existing product prices
            if comparison_result.changed_products:
                self.status_callback(f"Updating {len(comparison_result.changed_products)} product prices")
                price_results = self._process_price_updates(comparison_result.changed_products)
                update_results['prices_updated'] = price_results['updated']
            
            # Step 4: Mark missing products as unavailable
            if comparison_result.missing_products:
                self.status_callback(f"Marking {len(comparison_result.missing_products)} products as unavailable")
                unavailable_results = self._process_unavailable_products(comparison_result.missing_products)
                update_results['products_marked_unavailable'] = unavailable_results['marked']
            
            # Step 5: Collect products without nutrition facts
            update_results['products_without_nutrition'] = self.products_without_nutrition
            
            update_results['processing_time'] = (datetime.now() - start_time).total_seconds()
            self.status_callback(f"Update completed for {category_code} in {update_results['processing_time']:.2f} seconds")
            
            return update_results
            
        except Exception as e:
            error_msg = f"Update failed for {category_code}: {str(e)}"
            self.status_callback(error_msg)
            update_results['errors'].append(error_msg)
            update_results['processing_time'] = (datetime.now() - start_time).total_seconds()
            return update_results
    
    def _process_new_products(self, new_products: List, category_code: str) -> Dict:
        """Process new products found on website"""
        results = {
            'new_products_added': 0,
            'nutrition_data_added': 0,
            'ingredients_processed': 0,
            'errors': []
        }
        
        for product_match in new_products:
            try:
                website_data = product_match.website_data
                
                # Prepare product data
                product_data = {
                    'sku': website_data.sku,
                    'name': website_data.name,
                    'url': website_data.url,
                    'price': website_data.price,
                    'category_id': self._get_category_id(category_code)
                }
                
                # Add product to database
                product_id = self.db_updater.add_new_product(product_data)
                results['new_products_added'] += 1
                
                # Try to get nutrition data (this would be from detailed scraping)
                nutrition_data = self._get_nutrition_data(website_data.url)
                
                if nutrition_data and nutrition_data.get('has_nutrition'):
                    # Add nutrition data with nutri-score calculation
                    self.db_updater.add_nutrition_data(product_id, nutrition_data, category_code)
                    results['nutrition_data_added'] += 1
                    
                    # Process ingredients for new products only
                    if nutrition_data.get('ingredients'):
                        ingredient_results = self.ingredient_processor.process_product_ingredients(
                            website_data.sku, 
                            nutrition_data['ingredients']
                        )
                        results['ingredients_processed'] += ingredient_results['processed']
                
                else:
                    # Track products without nutrition facts
                    self.products_without_nutrition.append({
                        'sku': website_data.sku,
                        'name': website_data.name,
                        'category': category_code,
                        'url': website_data.url
                    })
                    self.status_callback(f"Product {website_data.sku} has no nutrition data - added to tracking list")
                
                # Add a small delay to be respectful to the server
                time.sleep(0.2)
                
            except Exception as e:
                error_msg = f"Error processing new product {website_data.sku}: {str(e)}"
                results['errors'].append(error_msg)
                self.status_callback(error_msg)
        
        return results
    
    def _process_price_updates(self, changed_products: List) -> Dict:
        """Process price updates for existing products"""
        results = {'updated': 0, 'errors': []}
        
        for product_match in changed_products:
            try:
                website_data = product_match.website_data
                
                # Update price (all changes are tracked without review)
                success = self.db_updater.update_product_price(
                    website_data.sku,
                    website_data.price,
                    True  # Product is available since it's on website
                )
                
                if success:
                    results['updated'] += 1
                    
            except Exception as e:
                error_msg = f"Error updating price for {website_data.sku}: {str(e)}"
                results['errors'].append(error_msg)
                self.status_callback(error_msg)
        
        return results
    
    def _process_unavailable_products(self, missing_products: List) -> Dict:
        """Mark products as unavailable"""
        results = {'marked': 0, 'errors': []}
        
        for product_match in missing_products:
            try:
                sku = product_match.sku
                
                success = self.db_updater.mark_product_unavailable(sku)
                if success:
                    results['marked'] += 1
                    
            except Exception as e:
                error_msg = f"Error marking {sku} unavailable: {str(e)}"
                results['errors'].append(error_msg)
                self.status_callback(error_msg)
        
        return results
    
    def _get_nutrition_data(self, product_url: str) -> Dict:
        """
        Get nutrition data for a product URL
        This would integrate with detailed scraping if available
        For now, returns empty data structure
        """
        # TODO: Integrate with detailed product page scraping
        # For now, return empty nutrition data
        return {
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
    
    def _get_category_id(self, category_code: str) -> int:
        """Get category ID from category code - placeholder implementation"""
        # TODO: Map category codes to database category IDs
        # For now, return default category ID
        return 1
    
    def get_update_summary(self, update_results: Dict) -> str:
        """Generate human-readable summary of update results"""
        summary_lines = [
            f"Update Summary for {update_results['category']}:",
            f"Processing time: {update_results['processing_time']:.2f} seconds",
            "",
            f"✓ New products added: {update_results['new_products_added']}",
            f"✓ Prices updated: {update_results['prices_updated']}",
            f"✓ Products marked unavailable: {update_results['products_marked_unavailable']}",
            f"✓ Nutrition data added: {update_results['nutrition_data_added']}",
            f"✓ Ingredients processed: {update_results['ingredients_processed']}",
            ""
        ]
        
        if update_results['products_without_nutrition']:
            summary_lines.extend([
                f"📋 Products without nutrition facts: {len(update_results['products_without_nutrition'])}",
                "   (These will need nutrition data provided separately)",
                ""
            ])
        
        if update_results['errors']:
            summary_lines.extend([
                f"⚠ Errors encountered: {len(update_results['errors'])}",
                ""
            ])
        
        return "\n".join(summary_lines)
    
    def export_products_without_nutrition(self, update_results: Dict) -> str:
        """Export products without nutrition facts as CSV string"""
        if not update_results['products_without_nutrition']:
            return ""
        
        csv_lines = ["SKU,Name,Category,URL"]
        
        for product in update_results['products_without_nutrition']:
            csv_lines.append(f"{product['sku']},{product['name']},{product['category']},{product['url']}")
        
        return "\n".join(csv_lines)
    
    def close(self):
        """Close all connections"""
        self.db_updater.close()
        self.ingredient_processor.close()
        self.status_callback("Update coordinator closed all connections")