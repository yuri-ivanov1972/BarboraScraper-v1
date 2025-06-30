#!/usr/bin/env python3
"""
Batch Processor - Optimized batch processing for multiple products
Includes connection pooling, progress tracking, and error recovery
"""
import time
import threading
from typing import Dict, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from update_coordinator import UpdateCoordinator

class BatchProcessor:
    """Handles batch processing of products with robust connection management"""
    
    def __init__(self, status_callback=None, max_workers=3):
        self.status_callback = status_callback or (lambda x: None)
        self.max_workers = max_workers
        self.coordinators = []
        self._lock = threading.Lock()
        
    def _get_coordinator(self) -> UpdateCoordinator:
        """Get or create a coordinator for the current thread"""
        with self._lock:
            # Create a new coordinator for each worker to avoid connection conflicts
            coordinator = UpdateCoordinator(self.status_callback)
            self.coordinators.append(coordinator)
            return coordinator
    
    def process_product_batch(self, products: List[Dict], category_code: str = 'SH-1-1-1') -> Dict:
        """
        Process a batch of products with optimized connection handling
        
        Args:
            products: List of product dictionaries with 'sku' and optionally 'name'
            category_code: Default category code to use
            
        Returns:
            Dictionary with batch processing results
        """
        start_time = time.time()
        results = {
            'total_products': len(products),
            'successful': 0,
            'failed': 0,
            'errors': [],
            'processing_time': 0,
            'products_processed': []
        }
        
        self.status_callback(f"Starting batch processing of {len(products)} products")
        
        def process_single_product(product_info):
            """Process a single product in a thread-safe manner"""
            sku = product_info.get('sku') or str(product_info)
            coordinator = None
            
            try:
                coordinator = self._get_coordinator()
                
                self.status_callback(f"Processing product {sku}")
                result = coordinator.process_single_product(sku, category_code)
                
                if result['success']:
                    return {'sku': sku, 'status': 'success', 'result': result}
                else:
                    return {'sku': sku, 'status': 'failed', 'error': result.get('error', 'Unknown error')}
                    
            except Exception as e:
                error_msg = f"Exception processing {sku}: {str(e)}"
                self.status_callback(error_msg)
                return {'sku': sku, 'status': 'failed', 'error': error_msg}
            
            finally:
                if coordinator:
                    try:
                        coordinator.close()
                    except:
                        pass
        
        # Process products with thread pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_product = {
                executor.submit(process_single_product, product): product 
                for product in products
            }
            
            for future in as_completed(future_to_product):
                try:
                    result = future.result()
                    results['products_processed'].append(result)
                    
                    if result['status'] == 'success':
                        results['successful'] += 1
                        self.status_callback(f"✓ {result['sku']} processed successfully")
                    else:
                        results['failed'] += 1
                        results['errors'].append(result['error'])
                        self.status_callback(f"✗ {result['sku']} failed: {result['error']}")
                        
                except Exception as e:
                    results['failed'] += 1
                    error_msg = f"Future execution error: {str(e)}"
                    results['errors'].append(error_msg)
                    self.status_callback(error_msg)
        
        results['processing_time'] = time.time() - start_time
        
        self.status_callback(f"Batch processing completed: {results['successful']} successful, {results['failed']} failed")
        return results
    
    def process_sku_list(self, sku_list: List[str], category_code: str = 'SH-1-1-1') -> Dict:
        """
        Process a list of SKUs
        
        Args:
            sku_list: List of product SKUs
            category_code: Category code to use for all products
            
        Returns:
            Batch processing results
        """
        products = [{'sku': sku} for sku in sku_list]
        return self.process_product_batch(products, category_code)
    
    def close(self):
        """Close all coordinator connections"""
        for coordinator in self.coordinators:
            try:
                coordinator.close()
            except:
                pass
        self.coordinators.clear()
        self.status_callback("Batch processor closed all connections")

def test_batch_processing():
    """Test batch processing functionality"""
    def status_callback(msg):
        print(f'[BATCH] {msg}')
    
    processor = BatchProcessor(status_callback, max_workers=2)
    
    print('=== TESTING BATCH PROCESSING ===')
    
    # Test with a small batch of products
    test_skus = ['147762', '961367', '999409']
    results = processor.process_sku_list(test_skus)
    
    print(f'\nBatch Results:')
    print(f'  Total: {results["total_products"]}')
    print(f'  Successful: {results["successful"]}')
    print(f'  Failed: {results["failed"]}')
    print(f'  Processing time: {results["processing_time"]:.2f}s')
    
    if results['errors']:
        print(f'  Errors: {len(results["errors"])}')
        for error in results['errors'][:3]:  # Show first 3 errors
            print(f'    - {error}')
    
    processor.close()
    return results

if __name__ == "__main__":
    test_batch_processing()