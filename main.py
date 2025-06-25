import streamlit as st
from core_parser import RimiParser, DatabaseConnection

st.set_page_config(
    page_title="Rimi Core Parser",
    page_icon="🛒",
    layout="wide"
)

def main():
    st.title("Rimi Core Parser")
    st.markdown("Basic category and product parsing with database connection")

    # Test the core functionality
    if st.button("Test Core Parser"):
        with st.spinner("Testing core parser..."):
            try:
                def status_callback(msg):
                    st.text(msg)
                
                # Initialize components
                parser = RimiParser(status_callback)
                db = DatabaseConnection()
                
                # Test category SH-11
                category_code = "SH-11"
                category_url = parser.build_category_url(category_code)
                st.text(f"Category URL: {category_url}")
                
                # Test pagination
                total_products, total_pages = parser.get_total_products_from_pagination(category_url)
                st.success(f"Found {total_products} products across {total_pages} pages")
                
                # Test product extraction
                page_url = f"{category_url}?pageSize=20&currentPage=1"
                products = parser.extract_products_from_page(page_url)
                st.success(f"Extracted {len(products)} products from first page")
                
                if products:
                    st.subheader("Sample Products")
                    for i, product in enumerate(products[:5]):
                        st.text(f"{i+1}. {product.sku}: {product.name} - {product.price}")
                
                # Test database
                categories = db.get_categories()
                st.success(f"Connected to database: {len(categories)} categories available")
                
                db_products = db.get_products_for_category(category_code)
                st.success(f"Database has {len(db_products)} products for category {category_code}")
                
            except Exception as e:
                st.error(f"Error: {str(e)}")

if __name__ == "__main__":
    main()