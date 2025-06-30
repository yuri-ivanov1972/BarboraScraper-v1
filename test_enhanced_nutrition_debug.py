"""
Test Enhanced Nutrition Debug - Show detailed nutrition data processing output
"""

def test_enhanced_nutrition_debugging():
    """Test the enhanced Force Update with detailed nutrition debugging output"""
    
    print("=== TESTING ENHANCED FORCE UPDATE WITH NUTRITION DEBUGGING ===")
    
    try:
        from enhanced_update_coordinator import EnhancedUpdateCoordinator
        
        def detailed_status_callback(msg):
            print(f"[DEBUG] {msg}")
        
        coordinator = EnhancedUpdateCoordinator(status_callback=detailed_status_callback)
        
        # Test with SKU 147762 (olive oil - typically no nutrition labels)
        print("\n1. TESTING SKU 147762 (Olive Oil - Expected: No Nutrition Labels)")
        print("-" * 70)
        
        result = coordinator.process_single_product_enhanced(
            sku='147762', 
            category_code='SH-4-3-15', 
            force_update=True
        )
        
        print(f"\nResult Summary:")
        print(f"  - Success: {result.success}")
        print(f"  - Operation: {result.operation}")
        print(f"  - Errors: {len(result.errors)}")
        
        if result.errors:
            for error in result.errors:
                print(f"    * {error}")
        
        coordinator.close()
        
        print("\n" + "=" * 70)
        print("ENHANCED NUTRITION DEBUGGING TEST COMPLETED")
        print("The output above shows:")
        print("1. Detailed nutrition data parsing from product page")
        print("2. Complete nutritionfacts table saving results")
        print("3. Exact nutri-score calculation process and any errors")
        
        return True
        
    except Exception as e:
        print(f"Test failed: {str(e)}")
        return False

if __name__ == "__main__":
    test_enhanced_nutrition_debugging()