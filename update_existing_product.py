"""
Update existing product 4007406 with complete nutrition data
"""
import sys
sys.path.append('.')

from update_coordinator import UpdateCoordinator

def update_existing_product():
    """Update product 4007406 with complete nutrition data"""
    
    def status_callback(msg):
        print(f"[STATUS] {msg}")
    
    coordinator = UpdateCoordinator(status_callback)
    
    # Process the existing product to update its nutrition data
    print("=== Updating Product 4007406 with Complete Nutrition Data ===")
    
    result = coordinator.process_single_product(sku="4007406", category_code="SH-2-1-1")
    
    print(f"\n=== PROCESSING RESULTS ===")
    print(f"Success: {result['success']}")
    print(f"Operation: {result['operation']}")
    print(f"Errors: {result['errors']}")
    
    if result['success']:
        print(f"Changes made: {result['changes']}")
        
        # Show the nutrition data that was processed
        nutrition = result['product_data'].get('nutrition', {})
        if nutrition:
            print(f"\nNutrition data processed:")
            print(f"  Has nutrition: {nutrition.get('has_nutrition')}")
            print(f"  Energy: {nutrition.get('energy_kcal')} kcal")
            print(f"  Fat: {nutrition.get('fat_total')}g")
            print(f"  Saturated Fat: {nutrition.get('fat_saturated')}g")
            print(f"  Carbohydrates: {nutrition.get('carbs_total')}g")
            print(f"  Sugar: {nutrition.get('carbs_sugars')}g")
            print(f"  Protein: {nutrition.get('protein')}g")
            print(f"  Salt: {nutrition.get('salt')}g")
    
    coordinator.close()

if __name__ == "__main__":
    update_existing_product()