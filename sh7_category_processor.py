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
from checkpoint_manager import CheckpointManager

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
    
    def __init__(self, status_callback=None, max_workers: int = 5, checkpoint_file: str = None):
        """
        Initialize SH-7 processor
        
        Args:
            status_callback: Function for progress updates
            max_workers: Maximum worker threads for batch processing
            checkpoint_file: Path to checkpoint file (optional)
        """
        self.status_callback = status_callback or self._default_callback
        self.max_workers = max_workers
        
        # Initialize components
        self.core_parser = CoreParser(self.status_callback)
        self.batch_processor = BatchProcessor(self.status_callback, max_workers=max_workers)
        
        # Initialize checkpoint manager
        self.checkpoint = CheckpointManager(checkpoint_file or "sh7_processing_checkpoint.json")
        
        # Processing statistics (legacy, now managed by checkpoint)
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
        Process all SH-7 subcategories sequentially with checkpoint support
        
        Returns:
            Dictionary with comprehensive processing results
        """
        # Check for previous progress
        if self.checkpoint.state['status'] == 'in_progress':
            self.status_callback("🔄 Resuming previous SH-7 processing session")
            self.status_callback(self.checkpoint.get_progress_summary())
        else:
            self.status_callback("🚀 Starting new SH-7 Category Processing")
            self.checkpoint.start_processing()
        
        self.status_callback(f"📊 Processing {len(self.SH7_SUBCATEGORIES)} subcategories (~480 products)")
        
        start_time = time.time()
        
        # Get remaining subcategories to process
        all_subcategories = list(self.SH7_SUBCATEGORIES.keys())
        remaining_subcategories = self.checkpoint.get_remaining_subcategories(all_subcategories)
        
        if not remaining_subcategories:
            self.status_callback("✅ All subcategories already completed!")
            # Ensure processing is marked as complete
            if self.checkpoint.state['status'] != 'completed':
                self.checkpoint.complete_processing()
            return self._build_final_stats()
        
        self.status_callback(f"📋 Found {len(remaining_subcategories)} subcategories to process")
        
        # Process remaining subcategories sequentially
        for subcategory_code in remaining_subcategories:
            expected_count = self.SH7_SUBCATEGORIES[subcategory_code]
            try:
                self.status_callback(f"\n{'='*60}")
                self.status_callback(f"🔄 Processing subcategory: {subcategory_code}")
                self.status_callback(f"📈 Expected products: {expected_count}")
                
                # Update checkpoint with current subcategory
                self.checkpoint.set_current_subcategory(subcategory_code)
                
                # Show current progress
                completed = self.checkpoint.state['completed_subcategories']
                total = self.checkpoint.state['total_subcategories']
                self.status_callback(f"📍 Progress: {completed + 1}/{total}")
                
                # Process single subcategory
                subcategory_result = self.process_single_subcategory(subcategory_code, expected_count)
                
                # Update checkpoint with results
                if subcategory_result['success']:
                    self.checkpoint.complete_subcategory(subcategory_code, subcategory_result)
                    self.status_callback(f"✅ {subcategory_code}: {subcategory_result['products_processed']} products processed")
                else:
                    self.checkpoint.fail_subcategory(subcategory_code, subcategory_result['error'])
                    self.status_callback(f"❌ {subcategory_code}: Failed - {subcategory_result['error']}")
                
                # Update legacy stats for compatibility
                self.stats['subcategory_details'].append(subcategory_result)
                
            except Exception as e:
                error_msg = f"Fatal error: {str(e)}"
                self.status_callback(f"💥 Fatal error processing {subcategory_code}: {str(e)}")
                
                # Update checkpoint with failure
                self.checkpoint.fail_subcategory(subcategory_code, error_msg)
                
                # Add failed subcategory to legacy stats
                self.stats['subcategory_details'].append({
                    'subcategory': subcategory_code,
                    'expected_products': expected_count,
                    'success': False,
                    'error': error_msg,
                    'skus_collected': 0,
                    'products_processed': 0,
                    'processing_time': 0
                })
        
        # Complete processing and build final results
        self.checkpoint.complete_processing()
        final_stats = self._build_final_stats()
        final_stats['processing_time'] = time.time() - start_time
        
        self.status_callback(f"\n{'='*60}")
        self.status_callback("🎯 SH-7 CATEGORY PROCESSING COMPLETE")
        self.status_callback(self.checkpoint.get_progress_summary())
        self.status_callback(f"⏱️  Session time: {final_stats['processing_time']:.1f} seconds")
        
        return final_stats
    
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
    
    def _build_final_stats(self) -> Dict:
        """Build final statistics from checkpoint data"""
        checkpoint_state = self.checkpoint.state
        detailed_results = self.checkpoint.get_detailed_results()
        
        return {
            'processing_id': checkpoint_state['processing_id'],
            'status': checkpoint_state['status'],
            'subcategories_total': checkpoint_state['total_subcategories'],
            'subcategories_completed': checkpoint_state['completed_subcategories'],
            'subcategories_failed': checkpoint_state['failed_subcategories'],
            'total_skus_collected': checkpoint_state['overall_stats']['total_skus_collected'],
            'total_products_processed': checkpoint_state['overall_stats']['total_products_processed'],
            'completed_list': checkpoint_state['completed_list'],
            'failed_list': checkpoint_state['failed_list'],
            'subcategory_details': list(detailed_results.values()),
            'processing_time': 0,  # Will be updated by caller
            'started_at': checkpoint_state['started_at'],
            'completed_at': checkpoint_state.get('completed_at'),
            'checkpoint_file': self.checkpoint.checkpoint_file
        }
    
    def get_processing_summary(self) -> str:
        """Get a formatted summary of processing results"""
        return self.checkpoint.get_progress_summary()
    
    def reset_progress(self):
        """Reset processing progress (use with caution)"""
        self.checkpoint.reset_checkpoint()
        self.status_callback("🔄 Processing progress reset")
    
    def can_resume(self) -> bool:
        """Check if there's a previous session that can be resumed"""
        return self.checkpoint.state['status'] == 'in_progress'
    
    def close(self):
        """Clean up resources"""
        try:
            if hasattr(self, 'batch_processor'):
                self.batch_processor.close()
            
            # Save final checkpoint state
            if hasattr(self, 'checkpoint'):
                self.checkpoint.save_checkpoint()
        except Exception as e:
            self.status_callback(f"Error closing processor: {str(e)}")


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