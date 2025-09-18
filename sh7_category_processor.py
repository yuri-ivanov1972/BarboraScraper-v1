"""
SH-7 Category Processor - Sequential processing of all SH-7 subcategories
Processes 17 subcategories (~480 products total) for comprehensive category testing
"""

import time
from typing import List, Dict, Optional
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core_parser import CoreParser
from batch_processor import BatchProcessor

class SH7CategoryProcessor:
    """Processor for SH-7 category with all 17 subcategories"""
    
    # SH-7 subcategories from user's CSV data (category_code: expected_count)
    SH7_SUBCATEGORIES = {
        'SH-7-2-28': 4,    # Start with smallest for testing
        'SH-7-1-1': 5,
        'SH-7-1-9': 6,
        'SH-7-2-19': 14,
        'SH-7-1-3': 16,
        'SH-7-2-15': 18,
        'SH-7-1-10': 18,
        'SH-7-2-21': 21,
        'SH-7-2-20': 24,
        'SH-7-2-14': 25,
        'SH-7-2-23': 26,
        'SH-7-2-17': 34,
        'SH-7-1-12': 37,
        'SH-7-2-25': 47,
        'SH-7-1-5': 52,
        'SH-7-1-11': 55,
        'SH-7-2-27': 71,   # End with largest
    }
    
    def __init__(self, status_callback=None, max_workers: int = 5):
        """
        Initialize SH-7 processor
        
        Args:
            status_callback: Function for progress updates
            max_workers: Maximum worker threads for batch processing
        """
        self.status_callback = status_callback or self._default_callback
        self.max_workers = max_workers
        
        # Initialize components
        self.core_parser = CoreParser(self.status_callback)
        self.batch_processor = BatchProcessor(self.status_callback, max_workers=max_workers)
        
        # Processing statistics
        self.stats = {
            'subcategories_total': len(self.SH7_SUBCATEGORIES),
            'subcategories_completed': 0,
            'subcategories_failed': 0,
            'total_skus_collected': 0,
            'total_products_processed': 0,
            'failed_skus': [],
            'processing_time': 0,
            'subcategory_details': []
        }
    
    def _default_callback(self, message: str):
        """Default status callback"""
        print(f"[SH7-PROCESSOR] {message}")
    
    def process_all_subcategories(self) -> Dict:
        """
        Process all SH-7 subcategories sequentially
        
        Returns:
            Dictionary with comprehensive processing results
        """
        self.status_callback("🚀 Starting SH-7 Category Processing")
        self.status_callback(f"📊 Processing {len(self.SH7_SUBCATEGORIES)} subcategories (~480 products)")
        
        start_time = time.time()
        
        # Process each subcategory sequentially
        for subcategory_code, expected_count in self.SH7_SUBCATEGORIES.items():
            try:
                self.status_callback(f"\n{'='*60}")
                self.status_callback(f"🔄 Processing subcategory: {subcategory_code}")
                self.status_callback(f"📈 Expected products: {expected_count}")
                self.status_callback(f"📍 Progress: {self.stats['subcategories_completed'] + 1}/{self.stats['subcategories_total']}")
                
                # Process single subcategory
                subcategory_result = self.process_single_subcategory(subcategory_code, expected_count)
                
                # Update overall statistics
                self.stats['subcategory_details'].append(subcategory_result)
                
                if subcategory_result['success']:
                    self.stats['subcategories_completed'] += 1
                    self.stats['total_skus_collected'] += subcategory_result['skus_collected']
                    self.stats['total_products_processed'] += subcategory_result['products_processed']
                    
                    self.status_callback(f"✅ {subcategory_code}: {subcategory_result['products_processed']} products processed")
                else:
                    self.stats['subcategories_failed'] += 1
                    self.status_callback(f"❌ {subcategory_code}: Failed - {subcategory_result['error']}")
                
            except Exception as e:
                self.status_callback(f"💥 Fatal error processing {subcategory_code}: {str(e)}")
                self.stats['subcategories_failed'] += 1
                
                # Add failed subcategory to details
                self.stats['subcategory_details'].append({
                    'subcategory': subcategory_code,
                    'expected_products': expected_count,
                    'success': False,
                    'error': f"Fatal error: {str(e)}",
                    'skus_collected': 0,
                    'products_processed': 0,
                    'processing_time': 0
                })
        
        # Final statistics
        self.stats['processing_time'] = time.time() - start_time
        
        self.status_callback(f"\n{'='*60}")
        self.status_callback("🎯 SH-7 CATEGORY PROCESSING COMPLETE")
        self.status_callback(f"⏱️  Total time: {self.stats['processing_time']:.1f} seconds")
        self.status_callback(f"✅ Successful subcategories: {self.stats['subcategories_completed']}/{self.stats['subcategories_total']}")
        self.status_callback(f"❌ Failed subcategories: {self.stats['subcategories_failed']}")
        self.status_callback(f"📊 Total products processed: {self.stats['total_products_processed']}")
        self.status_callback(f"🔍 Total SKUs collected: {self.stats['total_skus_collected']}")
        
        return self.stats
    
    def process_single_subcategory(self, subcategory_code: str, expected_count: int) -> Dict:
        """
        Process a single subcategory: collect SKUs then batch process
        
        Args:
            subcategory_code: Subcategory to process (e.g., 'SH-7-1-1')
            expected_count: Expected number of products
            
        Returns:
            Dictionary with subcategory processing results
        """
        subcategory_start = time.time()
        
        result = {
            'subcategory': subcategory_code,
            'expected_products': expected_count,
            'success': False,
            'error': None,
            'skus_collected': 0,
            'products_processed': 0,
            'processing_time': 0
        }
        
        try:
            self.status_callback(f"🔍 Phase 1: Collecting SKUs from {subcategory_code}")
            
            # Step 1: Collect all SKUs from category
            skus = self.core_parser.collect_category_skus(subcategory_code)
            
            if not skus:
                result['error'] = "No SKUs found in category"
                return result
            
            result['skus_collected'] = len(skus)
            self.status_callback(f"📋 Collected {len(skus)} SKUs (expected: {expected_count})")
            
            # Validation: Check if collected count is reasonable
            if len(skus) < expected_count * 0.8:  # Allow 20% variance
                self.status_callback(f"⚠️  WARNING: Collected {len(skus)} SKUs but expected {expected_count}")
                self.status_callback(f"⚠️  This may indicate under-collection from category pages")
            
            # Step 2: Batch process all collected SKUs
            self.status_callback(f"⚙️  Phase 2: Batch processing {len(skus)} products")
            
            # Convert SKUs to format expected by batch processor
            sku_products = [{'sku': sku} for sku in skus]
            
            # Process with automatic category extraction (no manual category needed)
            batch_results = self.batch_processor.process_sku_list_with_auto_category(skus)
            
            # Extract results
            result['products_processed'] = batch_results.get('successful', 0)
            failed_count = batch_results.get('failed', 0)
            
            if failed_count > 0:
                self.status_callback(f"⚠️  {failed_count} products failed processing")
                self.stats['failed_skus'].extend(batch_results.get('errors', []))
            
            result['success'] = True
            result['processing_time'] = time.time() - subcategory_start
            
            self.status_callback(f"✅ {subcategory_code} complete: {result['products_processed']}/{len(skus)} products processed")
            
        except Exception as e:
            result['error'] = str(e)
            result['processing_time'] = time.time() - subcategory_start
            self.status_callback(f"❌ Error in {subcategory_code}: {str(e)}")
        
        return result
    
    def get_processing_summary(self) -> str:
        """Get a formatted summary of processing results"""
        if not self.stats['subcategory_details']:
            return "No processing completed yet."
        
        summary = [
            f"SH-7 Category Processing Summary",
            f"{'='*40}",
            f"Total subcategories: {self.stats['subcategories_total']}",
            f"Completed: {self.stats['subcategories_completed']}",
            f"Failed: {self.stats['subcategories_failed']}",
            f"Total products processed: {self.stats['total_products_processed']}",
            f"Processing time: {self.stats['processing_time']:.1f}s",
            f"",
            f"Subcategory Details:",
            f"{'-'*40}"
        ]
        
        for detail in self.stats['subcategory_details']:
            status = "✅" if detail['success'] else "❌"
            summary.append(
                f"{status} {detail['subcategory']}: "
                f"{detail['products_processed']}/{detail['expected_products']} "
                f"({detail['processing_time']:.1f}s)"
            )
        
        return "\n".join(summary)
    
    def close(self):
        """Clean up resources"""
        try:
            if hasattr(self, 'batch_processor'):
                self.batch_processor.close()
        except Exception as e:
            self.status_callback(f"Error closing batch processor: {str(e)}")


def main():
    """Command line interface for SH-7 processing"""
    def status_callback(msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}")
    
    processor = SH7CategoryProcessor(status_callback, max_workers=3)
    
    try:
        print("Starting SH-7 Category Processing...")
        results = processor.process_all_subcategories()
        
        print("\n" + processor.get_processing_summary())
        
    finally:
        processor.close()


if __name__ == "__main__":
    main()