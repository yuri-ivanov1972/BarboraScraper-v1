"""
Fix missing quantity data for all products by extracting from product names
"""
import sys
sys.path.append('.')

from database_updater import DatabaseUpdater
import time

def fix_all_quantity_data():
    """Update quantity data for all products missing this information"""
    
    def status_callback(msg):
        print(f"[STATUS] {msg}")
    
    updater = DatabaseUpdater(status_callback)
    
    try:
        # Get all products missing quantity data
        query = """
            SELECT product_id, sku, name 
            FROM products 
            WHERE quantity_value IS NULL OR quantity_unit IS NULL
            ORDER BY product_id
        """
        
        missing_products = updater._execute_query(query, fetch=True)
        total_products = len(missing_products)
        
        print(f"=== Fixing Quantity Data for {total_products} Products ===")
        
        updated_count = 0
        failed_count = 0
        
        for i, product in enumerate(missing_products, 1):
            product_id = product['product_id']
            sku = product['sku']
            name = product['name']
            
            # Extract quantity from product name
            quantity_value, quantity_unit = updater._parse_quantity(name)
            
            if quantity_value and quantity_unit:
                try:
                    # Update the products table
                    update_query = """
                        UPDATE products 
                        SET quantity_value = %s, quantity_unit = %s
                        WHERE product_id = %s
                    """
                    
                    updater._execute_query(update_query, (quantity_value, quantity_unit, product_id))
                    updated_count += 1
                    
                    if i % 50 == 0:  # Progress update every 50 items
                        print(f"Progress: {i}/{total_products} - Updated: {updated_count}, Failed: {failed_count}")
                        
                except Exception as e:
                    failed_count += 1
                    print(f"Failed to update {sku}: {str(e)}")
            else:
                failed_count += 1
                if i <= 10:  # Show first 10 failures for debugging
                    print(f"No quantity found in: '{name[:60]}...'")
        
        print(f"\n=== RESULTS ===")
        print(f"Total processed: {total_products}")
        print(f"Successfully updated: {updated_count}")
        print(f"Failed to extract quantity: {failed_count}")
        print(f"Success rate: {(updated_count/total_products)*100:.1f}%")
        
        # Verify the update
        verification_query = """
            SELECT COUNT(*) as still_missing 
            FROM products 
            WHERE quantity_value IS NULL OR quantity_unit IS NULL
        """
        result = updater._execute_query(verification_query, fetch=True)
        remaining = result[0]['still_missing']
        
        print(f"Products still missing quantity data: {remaining}")
        
        if remaining > 0:
            # Show sample of remaining products without quantity
            sample_query = """
                SELECT sku, name 
                FROM products 
                WHERE quantity_value IS NULL OR quantity_unit IS NULL
                LIMIT 5
            """
            samples = updater._execute_query(sample_query, fetch=True)
            print(f"\nSample products still missing quantity:")
            for product in samples:
                print(f"  {product['sku']}: {product['name'][:60]}...")
        
    except Exception as e:
        print(f"Error during quantity update: {str(e)}")
    
    finally:
        updater.close()

if __name__ == "__main__":
    fix_all_quantity_data()