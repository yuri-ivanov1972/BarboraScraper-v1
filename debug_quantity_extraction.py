"""
Debug quantity extraction to identify the field mapping issue
"""
import sys
sys.path.append('.')

from database_updater import DatabaseUpdater

def test_quantity_extraction():
    """Test quantity extraction on sample product names"""
    
    def status_callback(msg):
        print(f"[STATUS] {msg}")
    
    updater = DatabaseUpdater(status_callback)
    
    # Test product names with quantities
    test_names = [
        "Olas Kalndruvas brīvos apstākļos dētas A/LMS Nr.1 10 gb.",
        "Piena produkts 500ml",
        "Maize baltā 750g",
        "Ūdens 1.5L",
        "Konfektes 250g",
        "Jogurts 125ml"
    ]
    
    print("=== Testing Quantity Extraction ===")
    for name in test_names:
        quantity_value, quantity_unit = updater._parse_quantity(name)
        print(f"'{name}' -> {quantity_value} {quantity_unit}")
    
    # Test with a real product from database
    print("\n=== Testing with Real Product ===")
    existing_product = updater.get_product_by_sku("4007406")
    if existing_product:
        product_name = existing_product['name']
        quantity_value, quantity_unit = updater._parse_quantity(product_name)
        print(f"Product: {product_name}")
        print(f"Extracted: {quantity_value} {quantity_unit}")
        print(f"Database values: {existing_product.get('quantity_value')} {existing_product.get('quantity_unit')}")
    
    updater.close()

if __name__ == "__main__":
    test_quantity_extraction()