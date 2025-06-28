#!/usr/bin/env python3
"""
Database Update Test - Test the complete update system with a small category
"""
import os
from update_coordinator import UpdateCoordinator

def test_database_update_system():
    """Test the complete database update system"""
    
    # Check if PRODUCTS_DB_URL is available
    if not os.getenv('PRODUCTS_DB_URL'):
        print("❌ PRODUCTS_DB_URL environment variable not set")
        print("Please configure the products database connection")
        return False
    
    def status_callback(msg):
        print(f"[UPDATE] {msg}")
    
    print("=== Database Update System Test ===")
    print("Testing with category SH-12-1-1 (4 products)")
    print()
    
    try:
        # Initialize coordinator
        coordinator = UpdateCoordinator(status_callback)
        
        # Test category update
        test_category = "SH-12-1-1"
        results = coordinator.perform_category_update(test_category)
        
        # Display results
        print("\n" + "="*50)
        print(coordinator.get_update_summary(results))
        
        # Export products without nutrition if any
        if results['products_without_nutrition']:
            print("Products without nutrition facts:")
            csv_export = coordinator.export_products_without_nutrition(results)
            print(csv_export)
        
        # Display any errors
        if results['errors']:
            print("Errors encountered:")
            for error in results['errors']:
                print(f"  - {error}")
        
        coordinator.close()
        
        print("\n✅ Database update test completed successfully")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        return False

if __name__ == "__main__":
    test_database_update_system()