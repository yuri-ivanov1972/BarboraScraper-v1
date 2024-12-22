import streamlit as st
import pandas as pd
from scraper import RimiScraper, ScraperError
from database import Database
import logging
import traceback
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    .error-message {
        color: #ff0000;
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #ffe6e6;
        margin: 1rem 0;
    }
    .success-message {
        color: #4CAF50;
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #e8f5e9;
        margin: 1rem 0;
    }
    </style>
    """, unsafe_allow_html=True)

def handle_error(error: Exception) -> str:
    """Convert exceptions to user-friendly error messages"""
    logger.error(f"Error occurred: {str(error)}\n{traceback.format_exc()}")

    if isinstance(error, ScraperError):
        return str(error)
    elif isinstance(error, ConnectionError):
        return "Failed to connect to the database. Please try again later."
    else:
        return "An unexpected error occurred. Please try again later."

def main():
    st.title("🛒 Rimi Product Scraper")
    st.markdown("### A tool for monitoring Rimi supermarket products and prices")

    # Initialize database
    try:
        db = Database()
    except Exception as e:
        error_msg = handle_error(e)
        st.error(f"Database Connection Error: {error_msg}")
        st.stop()

    # Add last update time indicator
    last_update = st.empty()

    # Refresh data button with error handling
    if st.button("🔄 Refresh Data"):
        with st.spinner("Scraping product data..."):
            try:
                scraper = RimiScraper()
                products = scraper.scrape_products()

                if products:
                    db.save_products(products)
                    st.success(f"Successfully updated data! Found {len(products)} products.")
                    last_update.markdown(f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
                else:
                    st.warning("No products found during scraping. Please try again later.")
            except ScraperError as e:
                st.error(f"Scraping Error: {str(e)}")
            except Exception as e:
                error_msg = handle_error(e)
                st.error(f"Error during data refresh: {error_msg}")

    # Display data with error handling
    try:
        products = db.get_products()
        if products:
            df = pd.DataFrame(products)

            # Remove id and created_at columns for display
            display_columns = ['name', 'price', 'price_per_unit', 'sku', 'category', 'product_url']
            df = df[display_columns]

            # Rename columns for better display
            df.columns = ['Product Name', 'Price (€)', 'Price per Unit', 'SKU', 'Category', 'Product URL']

            # Add filters
            st.markdown("### Filter Products")
            col1, col2 = st.columns(2)
            with col1:
                selected_category = st.selectbox(
                    "Select Category",
                    ["All"] + sorted(df['Category'].unique().tolist())
                )
            with col2:
                price_range = st.slider(
                    "Price Range (€)",
                    float(df['Price (€)'].min()),
                    float(df['Price (€)'].max()),
                    (float(df['Price (€)'].min()), float(df['Price (€)'].max()))
                )

            # Apply filters
            filtered_df = df.copy()
            if selected_category != "All":
                filtered_df = filtered_df[filtered_df['Category'] == selected_category]
            filtered_df = filtered_df[
                (filtered_df['Price (€)'] >= price_range[0]) &
                (filtered_df['Price (€)'] <= price_range[1])
            ]

            # Display the filtered dataframe
            st.markdown("### Product Data")
            st.markdown("Click on column headers to sort the data")
            st.dataframe(
                filtered_df,
                use_container_width=True,
                height=600
            )

            # Display statistics
            st.markdown("### Statistics")
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Total Products", len(filtered_df))
            with col2:
                st.metric("Average Price", f"€{filtered_df['Price (€)'].mean():.2f}")
            with col3:
                st.metric("Categories", filtered_df['Category'].nunique())
            with col4:
                st.metric("Price Range", f"€{filtered_df['Price (€)'].min():.2f} - €{filtered_df['Price (€)'].max():.2f}")

        else:
            st.info("No data available. Click 'Refresh Data' to fetch products.")

    except Exception as e:
        error_msg = handle_error(e)
        st.error(f"Error displaying data: {error_msg}")

if __name__ == "__main__":
    main()