"""
Test the corrected availability logic for product 4007406 (price €0.00)
"""
import sys
sys.path.append('.')

from update_coordinator import UpdateCoordinator

def test_availability_logic():
    """Test availability detection for unavailable product"""
    
    def status_callback(msg):
        print(f"[STATUS] {msg}")
    
    coordinator = UpdateCoordinator(status_callback)
    
    print("=== Testing Availability Logic for Product 4007406 (€0.00) ===")
    
    # Process product 4007406 which should have price €0.00 (unavailable)
    result = coordinator.process_single_product(sku="4007406", category_code="SH-2-1-1")
    
    print(f"\n=== RESULTS ===")
    print(f"Success: {result['success']}")
    print(f"Operation: {result['operation']}")
    print(f"Product price: €{result['product_data'].get('price', 'N/A')}")
    
    if result['errors']:
        print(f"Errors: {result['errors']}")
    
    # Check price history to verify availability was set correctly
    if result['success']:
        import os
        import psycopg2
        
        db_url = os.getenv('PRODUCTS_DB_URL')
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # Get latest price history record
        cursor.execute("""
            SELECT price, is_available, recorded_at 
            FROM product_price_history 
            WHERE product_id = 8454 
            ORDER BY recorded_at DESC 
            LIMIT 1
        """)
        
        price_history = cursor.fetchone()
        if price_history:
            price, is_available, recorded_at = price_history
            print(f"\nLatest price history:")
            print(f"  Price: €{price}")
            print(f"  Available: {is_available}")
            print(f"  Recorded: {recorded_at}")
            
            if float(price) == 0.0 and not is_available:
                print("✅ CORRECT: Price €0.00 correctly marked as unavailable")
            elif float(price) == 0.0 and is_available:
                print("❌ ERROR: Price €0.00 incorrectly marked as available")
            else:
                print(f"ℹ️ INFO: Price €{price} marked as available: {is_available}")
        else:
            print("No price history found")
        
        cursor.close()
        conn.close()
    
    coordinator.close()

if __name__ == "__main__":
    test_availability_logic()