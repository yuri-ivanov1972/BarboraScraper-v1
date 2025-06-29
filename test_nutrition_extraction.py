"""
Test the nutrition extraction directly to verify it works
"""
import sys
sys.path.append('.')

from update_coordinator import UpdateCoordinator

def test_nutrition_extraction():
    """Test nutrition extraction for the problematic product"""
    
    def status_callback(msg):
        print(f"[STATUS] {msg}")
    
    coordinator = UpdateCoordinator(status_callback)
    
    # Test the nutrition data extraction directly
    product_url = "https://www.rimi.lv/e-veikals/lv/produkti/p/4007406"
    
    print(f"=== Testing nutrition extraction for {product_url} ===")
    
    nutrition_data = coordinator._get_nutrition_data(product_url)
    
    print(f"\n=== NUTRITION DATA RESULTS ===")
    print(f"Has nutrition: {nutrition_data['has_nutrition']}")
    print(f"Energy kcal: {nutrition_data['energy_kcal']}")
    print(f"Energy kJ: {nutrition_data['energy_kj']}")
    print(f"Fat total: {nutrition_data['fat_total']}")
    print(f"Fat saturated: {nutrition_data['fat_saturated']}")
    print(f"Carbs total: {nutrition_data['carbs_total']}")
    print(f"Carbs sugars: {nutrition_data['carbs_sugars']}")
    print(f"Protein: {nutrition_data['protein']}")
    print(f"Salt: {nutrition_data['salt']}")
    print(f"Fiber: {nutrition_data['fiber']}")
    print(f"Ingredients: {nutrition_data['ingredients'][:100]}...")
    
    coordinator.close()

if __name__ == "__main__":
    test_nutrition_extraction()