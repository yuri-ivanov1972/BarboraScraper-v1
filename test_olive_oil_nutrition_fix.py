"""
Test Olive Oil Nutrition Fix for SKU 147762
"""

from robust_web_client import RobustWebClient
from enhanced_database_updater import EnhancedDatabaseUpdater
from enhanced_update_coordinator import EnhancedUpdateCoordinator
import psycopg2
import os

def test_olive_oil_nutrition_fix():
    """Test the complete olive oil nutrition fix for SKU 147762"""
    
    print("=== TESTING OLIVE OIL NUTRITION FIX FOR SKU 147762 ===")
    
    def status_callback(msg):
        print(f"[NUTRITION FIX] {msg}")
    
    # Test the robust web client nutrition extraction
    print("\n1. TESTING OLIVE OIL NUTRITION EXTRACTION")
    client = RobustWebClient(status_callback=status_callback)
    
    try:
        product_data = client.get_product_data("147762")
        
        if product_data:
            print(f"✓ Product found: {product_data['name']}")
            print(f"✓ Price: {product_data['price']}")
            print(f"✓ Has nutrition: {product_data.get('has_nutrition', False)}")
            
            if product_data.get('has_nutrition'):
                print(f"✓ Energy (kcal): {product_data.get('energy_kcal', 0)}")
                print(f"✓ Energy (kJ): {product_data.get('energy_kj', 0)}")
                print(f"✓ Fat total: {product_data.get('fat_total', 0)}g")
                print(f"✓ Fat saturated: {product_data.get('fat_saturated', 0)}g")
                print(f"✓ Carbs: {product_data.get('carbs_total', 0)}g")
                print(f"✓ Protein: {product_data.get('protein', 0)}g")
                print(f"✓ Salt: {product_data.get('salt', 0)}g")
                print(f"✓ Ingredients: {product_data.get('ingredients', 'N/A')}")
            else:
                print("✗ No nutrition data extracted")
        else:
            print("✗ Failed to extract product data")
            
    except Exception as e:
        print(f"✗ Error testing web client: {str(e)}")
    
    # Test the enhanced update coordinator
    print("\n2. TESTING ENHANCED UPDATE COORDINATOR")
    coordinator = EnhancedUpdateCoordinator(status_callback=status_callback)
    
    try:
        result = coordinator.process_single_product_enhanced("147762", "SH-4-3-15", force_update=True)
        
        print(f"✓ Processing result: {result.success}")
        print(f"✓ Operation: {result.operation}")
        print(f"✓ Changes made: {len(result.changes)} fields")
        
        if result.product_data:
            nutrition = result.product_data
            print(f"✓ Final nutrition - Energy: {nutrition.get('energy_kcal', 0)} kcal")
            print(f"✓ Final nutrition - Fat: {nutrition.get('fat_total', 0)}g")
            print(f"✓ Final nutrition - Has data: {nutrition.get('has_nutrition', False)}")
        
        if result.errors:
            print(f"⚠️  Errors encountered: {result.errors}")
        
    except Exception as e:
        print(f"✗ Error testing coordinator: {str(e)}")
    
    # Verify database state
    print("\n3. VERIFYING DATABASE STATE")
    try:
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()
        
        # Check product data
        cursor.execute("""
            SELECT p.product_id, p.name, p.rimi_url, p.category_id,
                   nf.energy_kcal, nf.energy_kj, nf.fat_total, nf.fat_saturated,
                   nf.carbs_total, nf.protein, nf.salt, nf.nutri_score_grade, nf.nutri_score_points
            FROM products p
            LEFT JOIN nutritionfacts nf ON p.product_id = nf.product_id
            WHERE p.sku = %s
        """, ("147762",))
        
        result = cursor.fetchone()
        if result:
            product_id, name, rimi_url, category_id, energy_kcal, energy_kj, fat_total, fat_saturated, carbs_total, protein, salt, nutri_grade, nutri_points = result
            
            print(f"✓ Product ID: {product_id}")
            print(f"✓ Name: {name}")
            print(f"✓ Rimi URL: {'SET' if rimi_url else 'NULL'}")
            print(f"✓ Category ID: {category_id}")
            print(f"✓ Energy (kcal): {energy_kcal}")
            print(f"✓ Energy (kJ): {energy_kj}")
            print(f"✓ Fat total: {fat_total}g")
            print(f"✓ Fat saturated: {fat_saturated}g")
            print(f"✓ Carbs: {carbs_total}g")
            print(f"✓ Protein: {protein}g")
            print(f"✓ Salt: {salt}g")
            print(f"✓ Nutri-score: {nutri_grade} ({nutri_points} points)")
            
            # Verify fix success
            fixes_applied = []
            if rimi_url and rimi_url.strip():
                fixes_applied.append("✓ Rimi URL fixed")
            if category_id != 1:
                fixes_applied.append("✓ Category ID fixed")
            if energy_kcal and energy_kcal > 0:
                fixes_applied.append("✓ Nutrition data fixed")
            if nutri_grade:
                fixes_applied.append("✓ Nutri-score calculated")
            
            print(f"\n🎯 FIXES APPLIED: {len(fixes_applied)}/4")
            for fix in fixes_applied:
                print(f"   {fix}")
                
        else:
            print("✗ Product not found in database")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"✗ Error checking database: {str(e)}")
    
    print("\n=== OLIVE OIL NUTRITION FIX TEST COMPLETED ===")

if __name__ == "__main__":
    test_olive_oil_nutrition_fix()