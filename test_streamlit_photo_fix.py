"""
Test script to verify photo processing works in Streamlit workflow
"""
import streamlit as st
from enhanced_update_coordinator import EnhancedUpdateCoordinator

def test_photo_processing():
    """Test photo processing with Streamlit-like workflow"""
    st.write("Testing photo processing...")
    
    # Clear any potential cache
    st.cache_data.clear()
    st.cache_resource.clear()
    
    messages = []
    def status_callback(msg):
        messages.append(msg)
        st.text(f"[STATUS] {msg}")
    
    # Test with a different SKU to avoid any caching issues
    test_skus = ['815963', '147762', '999409']
    
    for sku in test_skus:
        st.subheader(f"Testing SKU {sku}")
        
        try:
            coordinator = EnhancedUpdateCoordinator(status_callback)
            result = coordinator.process_single_product_enhanced(sku, 'SH-1-1-1', force_update=False)
            coordinator.close()
            
            st.write(f"**Success:** {result.success}")
            st.write(f"**Operation:** {result.operation}")
            st.write(f"**Changes:** {result.changes}")
            
            # Display changes exactly like main.py does
            if result.changes:
                st.write("**Changes Made:**")
                for change, made in result.changes.items():
                    display_name = change.replace('_', ' ').title()
                    status = '✅' if made else '❌'
                    st.write(f"  **{display_name}:** {status}")
                    
                    # Specifically check photos
                    if change == 'photos_saved':
                        if made:
                            st.success("✅ Photo processing working correctly!")
                        else:
                            st.error("❌ Photo processing failed")
            
        except Exception as e:
            st.error(f"Error: {e}")
        
        st.write("---")

if __name__ == "__main__":
    test_photo_processing()