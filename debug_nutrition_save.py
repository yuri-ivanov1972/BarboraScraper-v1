"""
Debug nutrition data saving process to find the root cause
"""
import sys
sys.path.append('.')

from database_updater import DatabaseUpdater

def debug_nutrition_save():
    """Debug the nutrition data saving process"""
    
    def status_callback(msg):
        print(f"[STATUS] {msg}")
    
    db_updater = DatabaseUpdater(status_callback)
    
    # Test nutrition data (same values that were extracted)
    test_nutrition_data = {
        'has_nutrition': True,
        'ingredients': 'olas',
        'energy_kcal': 150.0,
        'energy_kj': 625.0,
        'fat_total': 10.0,
        'fat_saturated': 3.1,
        'carbs_total': 0.8,
        'carbs_sugars': 0.8,
        'protein': 12.6,
        'salt': 0.3,
        'fiber': 0.0
    }
    
    product_id = 8454  # Known product ID for SKU 4007406
    category_code = "SH-2-1-1"
    
    print(f"=== Testing nutrition data save for product ID {product_id} ===")
    print(f"Input data: {test_nutrition_data}")
    
    try:
        # Test the add_nutrition_data method directly
        result = db_updater.add_nutrition_data(product_id, test_nutrition_data, category_code)
        print(f"Save result: {result}")
        
        # Check what was actually saved
        nutrition_query = """
        SELECT * FROM nutritionfacts WHERE product_id = %s
        """
        saved_data = db_updater._execute_query(nutrition_query, (product_id,), fetch=True)
        if saved_data:
            print(f"Saved data: {saved_data[0]}")
        else:
            print("No data found after save attempt")
            
    except Exception as e:
        print(f"Error during save: {str(e)}")
        import traceback
        traceback.print_exc()
    
    db_updater.close()

if __name__ == "__main__":
    debug_nutrition_save()