"""
Test Enhanced Photo Extraction - Comprehensive testing of improved photo parsing and database saving
Tests the complete workflow with SKU 815963 and validates error handling improvements
"""
import os
from robust_web_client import RobustWebClient
from enhanced_database_updater import EnhancedDatabaseUpdater
from enhanced_update_coordinator import EnhancedUpdateCoordinator

def test_enhanced_photo_extraction():
    """Test the enhanced photo extraction and database saving functionality"""
    
    print("=== TESTING ENHANCED PHOTO EXTRACTION SYSTEM ===")
    print("Target: SKU 815963 (known problematic case)")
    print("-" * 60)
    
    def status_callback(msg):
        print(f"[STATUS] {msg}")
    
    # Phase 1: Test Raw Photo Extraction
    print("\n1. TESTING RAW PHOTO EXTRACTION")
    print("-" * 40)
    
    web_client = RobustWebClient(status_callback)
    
    try:
        # Test photo extraction directly
        product_data = web_client.get_product_data("815963")
        
        if not product_data:
            print("❌ Failed to extract any product data")
            return False
        
        print(f"✓ Product found: {product_data.get('name', 'N/A')}")
        print(f"✓ Product URL: {product_data.get('url', 'N/A')}")
        print(f"✓ Price: €{product_data.get('price', 'N/A')}")
        
        # Check photo extraction results
        photos = product_data.get('photos', [])
        print(f"\nPhoto extraction results:")
        print(f"  Photos found: {len(photos)}")
        
        if photos:
            for i, photo in enumerate(photos, 1):
                print(f"  Photo {i}: {photo}")
            print("✓ Photo extraction successful")
        else:
            print("❌ No photos extracted - check extraction logic")
            
    except Exception as e:
        print(f"❌ Photo extraction failed with exception: {str(e)}")
        return False
    
    # Phase 2: Test Database Integration
    print(f"\n2. TESTING DATABASE INTEGRATION")
    print("-" * 40)
    
    try:
        db_updater = EnhancedDatabaseUpdater(status_callback)
        
        # Get product from database
        product = db_updater.get_product_by_sku("815963")
        
        if not product:
            print("❌ Product 815963 not found in database")
            return False
            
        product_id = product['product_id']
        print(f"✓ Product found in database - ID: {product_id}")
        
        # Test photo saving with extracted photos
        if photos:
            print(f"\nTesting photo save with {len(photos)} photo(s)...")
            
            photo_save_result = db_updater.add_product_photos(product_id, photos)
            
            if photo_save_result:
                print("✓ Photo save operation successful")
                
                # Verify photos were actually saved
                verification_query = "SELECT photo_url, is_primary FROM productphotos WHERE product_id = %s"
                saved_photos = db_updater._execute_query(verification_query, (product_id,), fetch=True)
                
                if saved_photos:
                    print(f"✓ Verification: {len(saved_photos)} photo(s) found in database")
                    for i, photo_record in enumerate(saved_photos, 1):
                        primary_status = "PRIMARY" if photo_record['is_primary'] else "SECONDARY"
                        print(f"  Photo {i} ({primary_status}): {photo_record['photo_url']}")
                else:
                    print("❌ Verification failed: No photos found in database after save")
                    return False
            else:
                print("❌ Photo save operation failed")
                return False
        else:
            print("⚠️  No photos to test database saving (extraction failed)")
        
        db_updater.close()
        
    except Exception as e:
        print(f"❌ Database integration test failed: {str(e)}")
        return False
    
    # Phase 3: Test Enhanced Coordinator Integration
    print(f"\n3. TESTING ENHANCED COORDINATOR INTEGRATION")
    print("-" * 50)
    
    try:
        coordinator = EnhancedUpdateCoordinator(status_callback)
        
        print("Testing force update with photo processing...")
        result = coordinator.process_single_product_enhanced("815963", "SH-13-10-24", force_update=True)
        
        print(f"\nCoordinator Results:")
        print(f"  Success: {result.success}")
        print(f"  Operation: {result.operation}")
        print(f"  Errors: {len(result.errors)}")
        
        if result.errors:
            print("  Error details:")
            for error in result.errors:
                print(f"    - {error}")
        
        if result.changes:
            print(f"  Changes made:")
            for change, status in result.changes.items():
                status_icon = "✓" if status else "❌"
                print(f"    {change}: {status_icon}")
                
            # Specifically check photo processing
            photos_saved = result.changes.get('photos_saved', False)
            photo_error = result.changes.get('photo_error')
            
            if photos_saved:
                print("✓ Enhanced coordinator successfully processed photos")
            elif photo_error:
                print(f"⚠️  Photo processing failed in coordinator: {photo_error}")
            else:
                print("⚠️  No photos processed by coordinator")
        
        coordinator.close()
        
    except Exception as e:
        print(f"❌ Enhanced coordinator test failed: {str(e)}")
        return False
    
    # Phase 4: Final Verification
    print(f"\n4. FINAL VERIFICATION")
    print("-" * 30)
    
    try:
        # Final check of database state
        final_db = EnhancedDatabaseUpdater(status_callback)
        
        # Check final photo count
        final_product = final_db.get_product_by_sku("815963")
        if final_product:
            final_photo_query = "SELECT COUNT(*) as count FROM productphotos WHERE product_id = %s"
            final_count_result = final_db._execute_query(final_photo_query, (final_product['product_id'],), fetch=True)
            final_photo_count = final_count_result[0]['count'] if final_count_result else 0
            
            print(f"Final photo count in database: {final_photo_count}")
            
            if final_photo_count > 0:
                print("✓ SUCCESS: Photos are properly saved in database")
                
                # Show final photos
                final_photos_query = "SELECT photo_url, is_primary FROM productphotos WHERE product_id = %s ORDER BY is_primary DESC"
                final_photos = final_db._execute_query(final_photos_query, (final_product['product_id'],), fetch=True)
                
                print("Final photos in database:")
                for i, photo_record in enumerate(final_photos, 1):
                    primary_status = "PRIMARY" if photo_record['is_primary'] else "SECONDARY"
                    print(f"  {i}. {photo_record['photo_url']} ({primary_status})")
                    
                return True
            else:
                print("❌ FAILURE: No photos found in final verification")
                return False
        else:
            print("❌ Product not found for final verification")
            return False
            
        final_db.close()
        
    except Exception as e:
        print(f"❌ Final verification failed: {str(e)}")
        return False

def test_error_handling():
    """Test error handling scenarios for photo processing"""
    
    print("\n" + "=" * 60)
    print("TESTING ERROR HANDLING SCENARIOS")
    print("=" * 60)
    
    def status_callback(msg):
        print(f"[ERROR_TEST] {msg}")
    
    # Test with invalid SKU
    print("\n1. Testing with invalid SKU...")
    web_client = RobustWebClient(status_callback)
    
    invalid_result = web_client.get_product_data("999999999")
    if not invalid_result:
        print("✓ Correctly handled invalid SKU")
    else:
        print("⚠️  Unexpected result for invalid SKU")
    
    # Test database error handling
    print("\n2. Testing database error handling...")
    db_updater = EnhancedDatabaseUpdater(status_callback)
    
    # Test with invalid product ID
    invalid_db_result = db_updater.add_product_photos(999999, ["https://example.com/test.jpg"])
    if not invalid_db_result:
        print("✓ Correctly handled invalid product ID")
    else:
        print("⚠️  Unexpected success with invalid product ID")
    
    # Test with empty photo list
    empty_result = db_updater.add_product_photos(1, [])
    if empty_result:
        print("✓ Correctly handled empty photo list")
    else:
        print("⚠️  Unexpected failure with empty photo list")
    
    db_updater.close()
    print("✓ Error handling tests completed")

if __name__ == "__main__":
    print("Starting enhanced photo extraction tests...")
    
    # Main functionality test
    main_success = test_enhanced_photo_extraction()
    
    # Error handling test
    test_error_handling()
    
    print("\n" + "=" * 60)
    if main_success:
        print("🎉 OVERALL RESULT: SUCCESS - Enhanced photo extraction is working!")
    else:
        print("❌ OVERALL RESULT: FAILURE - Issues detected in photo extraction")
    print("=" * 60)