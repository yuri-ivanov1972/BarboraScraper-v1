import streamlit as st
from core_parser import RimiParser, DatabaseConnection
import time

st.set_page_config(
    page_title="Rimi Category Analyzer",
    page_icon="🛒",
    layout="wide"
)

def analyze_category(category_code: str):
    """Analyze a single category comparing website vs database"""
    
    # Initialize components
    parser = RimiParser()
    db = DatabaseConnection()
    
    # Get website data
    category_url = parser.build_category_url(category_code)
    st.info(f"Analyzing category: {category_url}")
    
    # Analyze pagination
    total_products_web, total_pages_web = parser.get_total_products_from_pagination(category_url)
    
    # Get sample products from first page
    page_url = f"{category_url}?pageSize=20&currentPage=1"
    sample_products_web = parser.extract_products_from_page(page_url, max_products=10)
    
    # Get database data
    db_products = db.get_products_for_category(category_code)
    
    # Display comparison
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🌐 Website Data")
        st.metric("Total Pages", total_pages_web)
        st.metric("Estimated Products", total_products_web)
        
        if sample_products_web:
            st.write("**Sample Products (First 10):**")
            for i, product in enumerate(sample_products_web):
                st.text(f"{i+1}. {product.sku}: {product.name[:40]}... - {product.price}")
    
    with col2:
        st.subheader("🗄️ Database Data")
        st.metric("Products in Database", len(db_products))
        
        if db_products:
            st.write("**Sample Database Products (First 10):**")
            for i, product in enumerate(db_products[:10]):
                quantity_info = ""
                if product.get('quantity_value') and product.get('quantity_unit'):
                    quantity_info = f" ({product['quantity_value']}{product['quantity_unit']})"
                st.text(f"{i+1}. {product['sku']}: {product['name'][:40]}...{quantity_info}")
    
    # Coverage analysis
    st.subheader("📊 Coverage Analysis")
    
    if total_products_web > 0 and db_products:
        coverage_percentage = (len(db_products) / total_products_web) * 100
        st.metric(
            "Database Coverage", 
            f"{coverage_percentage:.1f}%",
            f"{len(db_products)} of {total_products_web} products"
        )
        
        # Progress bar
        st.progress(coverage_percentage / 100)
        
        if coverage_percentage < 50:
            st.warning("Low database coverage - many products missing from database")
        elif coverage_percentage < 80:
            st.info("Moderate database coverage - some products missing")
        else:
            st.success("Good database coverage")
    else:
        st.warning("Unable to calculate coverage - insufficient data")

def main():
    st.title("Rimi Category Analyzer")
    st.markdown("**Read-only analysis** comparing website data with database data")
    
    # Category input
    category_code = st.text_input(
        "Enter Rimi Category Code", 
        value="SH-11",
        placeholder="e.g., SH-11, SH-13, SH-2",
        help="Enter a Rimi category code like SH-11 (dairy products)"
    )
    
    if st.button("Analyze Category", type="primary"):
        if category_code.strip():
            with st.spinner(f"Analyzing category {category_code}..."):
                try:
                    analyze_category(category_code.strip().upper())
                except Exception as e:
                    st.error(f"Analysis error: {str(e)}")
        else:
            st.error("Please enter a category code")
    
    # Show available categories
    with st.expander("Available Categories"):
        try:
            db = DatabaseConnection()
            categories = db.get_categories()
            
            if categories:
                st.write(f"Found {len(categories)} categories in database:")
                
                # Group by main category
                main_categories = {}
                for cat in categories[:50]:  # Show first 50
                    main_code = cat['category_code'].split('-')[1] if '-' in cat['category_code'] else cat['category_code']
                    if main_code not in main_categories:
                        main_categories[main_code] = []
                    main_categories[main_code].append(cat)
                
                for main_code, cats in list(main_categories.items())[:10]:
                    st.write(f"**SH-{main_code}**: {len(cats)} subcategories")
                    for cat in cats[:3]:
                        st.text(f"  - {cat['category_code']}: {cat.get('category_name', 'N/A')}")
                    if len(cats) > 3:
                        st.text(f"  ... and {len(cats)-3} more")
            else:
                st.warning("No categories found in database")
        except Exception as e:
            st.error(f"Database connection error: {str(e)}")

if __name__ == "__main__":
    main()