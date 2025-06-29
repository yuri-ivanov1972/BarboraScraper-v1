"""
Direct database update for product 4007406 nutrition data
"""
import os
import psycopg2
from decimal import Decimal

def update_nutrition_directly():
    """Update nutrition data directly in the database"""
    
    db_url = os.getenv('PRODUCTS_DB_URL')
    if not db_url:
        print("ERROR: PRODUCTS_DB_URL not found")
        return
    
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # Update the nutrition data with the extracted values
        update_query = """
            UPDATE nutritionfacts 
            SET fat_total = %s,
                fat_saturated = %s,
                carbs_total = %s,
                carbs_sugars = %s,
                fiber = %s,
                data_source_date = CURRENT_TIMESTAMP
            WHERE product_id = 8454
        """
        
        # Values from the successful extraction
        values = (
            Decimal('10.0'),   # fat_total
            Decimal('3.1'),    # fat_saturated  
            Decimal('0.8'),    # carbs_total
            Decimal('0.8'),    # carbs_sugars
            None               # fiber (not found)
        )
        
        cursor.execute(update_query, values)
        conn.commit()
        
        print("Successfully updated nutrition data")
        
        # Verify the update
        cursor.execute("SELECT * FROM nutritionfacts WHERE product_id = 8454")
        updated_nutrition = cursor.fetchone()
        print(f"Updated nutrition data: {updated_nutrition}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Database error: {str(e)}")

if __name__ == "__main__":
    update_nutrition_directly()