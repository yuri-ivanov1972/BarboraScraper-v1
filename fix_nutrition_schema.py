"""
Fix Nutrition Data Schema - Update olive oil nutrition data with correct table structure
"""

import psycopg2
import os
from robust_web_client import RobustWebClient

def fix_olive_oil_nutrition():
    """Fix olive oil nutrition data using correct database schema"""
    
    print("=== FIXING OLIVE OIL NUTRITION DATA WITH CORRECT SCHEMA ===")
    
    try:
        # Connect to database
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()
        
        # Get the olive oil product (using actual SKU from database)
        sku = "808052"  # Olīveļļa Rimi augstākā labuma 1l
        cursor.execute("SELECT id, name FROM products WHERE sku = %s", (sku,))
        product = cursor.fetchone()
        
        if not product:
            print(f"✗ Product {sku} not found")
            return
        
        product_id, name = product
        print(f"✓ Found product: {name} (ID: {product_id})")
        
        # Check if nutrition record exists
        cursor.execute("SELECT id FROM product_nutrition WHERE sku = %s", (sku,))
        existing_nutrition = cursor.fetchone()
        
        # Standard olive oil nutrition values per 100g
        olive_oil_nutrition = {
            'sku': sku,
            'ingredients': 'olīveļļa',
            'energy_kj': 3700,
            'energy_kcal': 900,
            'fat': 100.0,
            'saturated_fat': 16.0,
            'carbohydrates': 0.0,
            'sugars': 0.0,
            'protein': 0.0,
            'salt': 0.0,
            'serving_size_unit': '100g',
            'nutriscore_grade': 'C',
            'nutriscore_score': 1
        }
        
        if existing_nutrition:
            # Update existing record
            print("✓ Updating existing nutrition record...")
            
            update_query = """
                UPDATE product_nutrition 
                SET ingredients = %s,
                    energy_kj = %s,
                    energy_kcal = %s,
                    fat = %s,
                    saturated_fat = %s,
                    carbohydrates = %s,
                    sugars = %s,
                    protein = %s,
                    salt = %s,
                    serving_size_unit = %s,
                    nutriscore_grade = %s,
                    nutriscore_score = %s,
                    updated_at = NOW()
                WHERE sku = %s
            """
            
            cursor.execute(update_query, (
                olive_oil_nutrition['ingredients'],
                olive_oil_nutrition['energy_kj'],
                olive_oil_nutrition['energy_kcal'],
                olive_oil_nutrition['fat'],
                olive_oil_nutrition['saturated_fat'],
                olive_oil_nutrition['carbohydrates'],
                olive_oil_nutrition['sugars'],
                olive_oil_nutrition['protein'],
                olive_oil_nutrition['salt'],
                olive_oil_nutrition['serving_size_unit'],
                olive_oil_nutrition['nutriscore_grade'],
                olive_oil_nutrition['nutriscore_score'],
                sku
            ))
            
        else:
            # Insert new record
            print("✓ Creating new nutrition record...")
            
            insert_query = """
                INSERT INTO product_nutrition (
                    sku, ingredients, energy_kj, energy_kcal, fat, saturated_fat,
                    carbohydrates, sugars, protein, salt, serving_size_unit,
                    nutriscore_grade, nutriscore_score, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                )
            """
            
            cursor.execute(insert_query, (
                olive_oil_nutrition['sku'],
                olive_oil_nutrition['ingredients'],
                olive_oil_nutrition['energy_kj'],
                olive_oil_nutrition['energy_kcal'],
                olive_oil_nutrition['fat'],
                olive_oil_nutrition['saturated_fat'],
                olive_oil_nutrition['carbohydrates'],
                olive_oil_nutrition['sugars'],
                olive_oil_nutrition['protein'],
                olive_oil_nutrition['salt'],
                olive_oil_nutrition['serving_size_unit'],
                olive_oil_nutrition['nutriscore_grade'],
                olive_oil_nutrition['nutriscore_score']
            ))
        
        # Commit changes
        conn.commit()
        print("✓ Nutrition data updated successfully")
        
        # Verify the update
        cursor.execute("""
            SELECT p.name, pn.energy_kcal, pn.fat, pn.nutriscore_grade, pn.nutriscore_score
            FROM products p
            JOIN product_nutrition pn ON p.sku = pn.sku
            WHERE p.sku = %s
        """, (sku,))
        
        result = cursor.fetchone()
        if result:
            name, energy_kcal, fat, nutri_grade, nutri_score = result
            print(f"✓ Verification successful:")
            print(f"  - Product: {name}")
            print(f"  - Energy: {energy_kcal} kcal")
            print(f"  - Fat: {fat}g")
            print(f"  - Nutri-score: {nutri_grade} ({nutri_score} points)")
        
        cursor.close()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"✗ Error fixing nutrition data: {str(e)}")
        return False

if __name__ == "__main__":
    fix_olive_oil_nutrition()