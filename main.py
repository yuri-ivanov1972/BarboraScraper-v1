import streamlit as st
import pandas as pd
from scraper import RimiScraper
from database import Database
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

# Page configuration
st.set_page_config(
    page_title="Rimi Product Scraper",
    page_icon="🛒",
    layout="wide"
)

# Custom CSS
st.markdown("""
    <style>
    .stButton>button {
        background-color: #4CAF50;
        color: white;
    }
    .stDataFrame {
        background-color: white;
    }
    </style>
    """, unsafe_allow_html=True)

def main():
    st.title("🛒 Rimi Product Scraper")
    
    # Initialize database
    try:
        db = Database()
    except Exception as e:
        st.error(f"Failed to connect to database: {str(e)}")
        return

    # Refresh data button
    if st.button("🔄 Refresh Data"):
        with st.spinner("Scraping product data..."):
            try:
                scraper = RimiScraper()
                products = scraper.scrape_products()
                
                if products:
                    db.save_products(products)
                    st.success("Data successfully updated!")
                else:
                    st.warning("No products found during scraping.")
            except Exception as e:
                st.error(f"Error during data refresh: {str(e)}")
    
    # Display data
    try:
        products = db.get_products()
        if products:
            df = pd.DataFrame(products)
            
            # Remove id and created_at columns for display
            display_columns = ['name', 'price', 'price_per_unit', 'sku', 'category', 'product_url']
            df = df[display_columns]
            
            # Rename columns for better display
            df.columns = ['Product Name', 'Price (€)', 'Price per Unit', 'SKU', 'Category', 'Product URL']
            
            # Add sorting functionality
            st.markdown("### Product Data")
            st.markdown("Click on column headers to sort the data")
            st.dataframe(
                df,
                use_container_width=True,
                height=600
            )
            
            # Display statistics
            st.markdown("### Statistics")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Products", len(df))
            with col2:
                st.metric("Average Price", f"€{df['Price (€)'].mean():.2f}")
            with col3:
                st.metric("Categories", df['Category'].nunique())
                
        else:
            st.info("No data available. Click 'Refresh Data' to fetch products.")
            
    except Exception as e:
        st.error(f"Error displaying data: {str(e)}")

if __name__ == "__main__":
    main()
