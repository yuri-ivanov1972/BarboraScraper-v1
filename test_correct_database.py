"""
Test connection to the correct database with PRODUCTS_DB_URL
"""
import os
import psycopg2

def test_correct_database():
    """Test the PRODUCTS_DB_URL database"""
    
    # Get the correct database URL
    db_url = os.getenv('PRODUCTS_DB_URL')
    if not db_url:
        print("ERROR: PRODUCTS_DB_URL not found")
        return
    
    print(f"Connecting to PRODUCTS_DB_URL...")
    
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # Check tables
        cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """)
        tables = cursor.fetchall()
        print(f"Tables in PRODUCTS_DB_URL database:")
        for table in tables:
            print(f"  - {table[0]}")
        
        # Check if product 4007406 exists
        cursor.execute("SELECT product_id, sku, name FROM products WHERE sku = %s", ('4007406',))
        product = cursor.fetchone()
        if product:
            print(f"\nProduct found: ID={product[0]}, SKU={product[1]}, Name={product[2]}")
            
            # Check nutrition data
            cursor.execute("SELECT * FROM nutritionfacts WHERE product_id = %s", (product[0],))
            nutrition = cursor.fetchone()
            if nutrition:
                print(f"Nutrition data found: {nutrition}")
            else:
                print("No nutrition data found for this product")
        else:
            print("\nProduct 4007406 not found in products table")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Database error: {str(e)}")

if __name__ == "__main__":
    test_correct_database()