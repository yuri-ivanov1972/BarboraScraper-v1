import streamlit as st
import pandas as pd
from scraper import RimiScraper, ScraperError
from database import Database
import logging
import traceback
from datetime import datetime
import psycopg2 # Added import for psycopg2 error handling

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
    .metric-card {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 0.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .status-area {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #4CAF50;
        margin: 1rem 0;
    }
    </style>
    """, unsafe_allow_html=True)

def handle_error(error: Exception) -> str:
    """Convert exceptions to user-friendly error messages"""
    logger.error(f"Error occurred: {str(error)}\n{traceback.format_exc()}")

    if isinstance(error, ScraperError):
        return str(error)
    elif isinstance(error, psycopg2.Error):
        return "Database error occurred. Please try again later."
    elif isinstance(error, ConnectionError):
        return "Failed to connect to the database. Please try again later."
    else:
        return f"An unexpected error occurred: {str(error)}"

def main():
    st.title("🛒 Rimi Product Scraper")
    st.markdown("### A tool for monitoring Rimi supermarket products and prices")

    # Initialize database
    try:
        db = Database()
        logger.info("Database connection established successfully")
    except Exception as e:
        error_msg = handle_error(e)
        st.error(f"Database Connection Error: {error_msg}")
        st.stop()

    # Show existing data and last update time
    try:
        last_update_time = db.get_last_update_time()
        if last_update_time:
            st.markdown(f"*Last updated: {last_update_time.strftime('%Y-%m-%d %H:%M:%S')}*")

        products = db.get_products()
        if products:
            st.info(f"Showing {len(products)} products from the database")
        else:
            st.info("No products in database. Click 'Refresh Data' to fetch products.")
    except Exception as e:
        error_msg = handle_error(e)
        st.error(f"Error loading existing data: {error_msg}")

    # Add status area for scraping progress
    status_area = st.empty()

    # Refresh data button with error handling
    if st.button("🔄 Refresh Data"):
        with st.spinner("Scraping product data..."):
            try:
                scraper = RimiScraper(status_callback=lambda msg: status_area.markdown(f"""
                    <div class="status-area">
                        <h4>Scraping Status</h4>
                        <p>{msg}</p>
                    </div>
                """, unsafe_allow_html=True))

                products = scraper.scrape_products()

                if products:
                    try:
                        new_products, updated_products = db.save_products(products)
                        status_message = []
                        if new_products > 0:
                            status_message.append(f"Added {new_products} new products")
                        if updated_products > 0:
                            status_message.append(f"Updated {updated_products} existing products")

                        if status_message:
                            st.success("Successfully " + " and ".join(status_message) + "!")
                        else:
                            st.info("No changes detected in product data")

                        st.rerun()  # Refresh the page to show updated data
                    except Exception as e:
                        error_msg = handle_error(e)
                        st.error(f"Error saving products: {error_msg}")
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
            display_columns = ['name', 'price', 'price_per_unit', 'sku', 'category', 'product_url', 'image_url']
            df = df[display_columns]

            # Rename columns for better display
            df.columns = ['Product Name', 'Price (€)', 'Price per Unit', 'SKU', 'Category', 'Product URL', 'Image URL']

            # Display raw data counts
            st.markdown("### 📊 Data Overview")

            # Add nutrition data overview
            needs_review = db.get_products_needing_review()
            if needs_review:
                st.warning(f"⚠️ {len(needs_review)} products need nutritional data review")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.info(f"Total Products: {len(df)} items")
            with col2:
                st.info(f"Categories: {df['Category'].nunique()}")
            with col3:
                st.info(f"Price Range: €{df['Price (€)'].min():.2f} - €{df['Price (€)'].max():.2f}")

            # Add filters
            st.markdown("### 🔍 Filter Products")
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
            st.markdown("### 📋 Product Data")
            st.markdown("Click on column headers to sort the data")

            # Add button to show nutrition data for selected product
            selected_sku = st.selectbox("Select product to view nutrition data", 
                                      filtered_df['SKU'].tolist(),
                                      format_func=lambda x: filtered_df[filtered_df['SKU'] == x]['Product Name'].iloc[0])

            if selected_sku:
                nutrition_data = db.get_product_nutrition(selected_sku)
                if nutrition_data:
                    st.markdown("### 🥗 Nutritional Information")

                    # Create two columns for layout
                    col1, col2 = st.columns(2)

                    with col1:
                        st.markdown("#### Product Details")
                        st.write(f"**Name:** {nutrition_data['product_name']}")
                        st.write(f"**Category:** {nutrition_data['category']}")
                        if nutrition_data['needs_review']:
                            st.warning(f"⚠️ Needs Review: {nutrition_data['review_notes']}")

                        if nutrition_data['ingredients']:
                            st.markdown("#### Ingredients")
                            st.write(nutrition_data['ingredients'])

                    with col2:
                        st.markdown("#### Nutrition Values")
                        st.write(f"**Serving Size:** {nutrition_data['serving_size_unit'] or '100g/ml'}")

                        # Create a clean nutrition table
                        nutrition_values = {
                            'Energy': f"{nutrition_data['energy_kj'] or '-'} kJ / {nutrition_data['energy_kcal'] or '-'} kcal",
                            'Fat': f"{nutrition_data['fat'] or '-'}g",
                            'of which saturates': f"{nutrition_data['saturated_fat'] or '-'}g",
                            'Carbohydrates': f"{nutrition_data['carbohydrates'] or '-'}g",
                            'of which sugars': f"{nutrition_data['sugars'] or '-'}g",
                            'Protein': f"{nutrition_data['protein'] or '-'}g",
                            'Salt': f"{nutrition_data['salt'] or '-'}g"
                        }

                        # Convert to DataFrame for better display
                        nutrition_df = pd.DataFrame(
                            nutrition_values.items(),
                            columns=['Nutrient', 'Amount']
                        )
                        st.table(nutrition_df)

            # Display the main products table
            st.dataframe(
                filtered_df,
                use_container_width=True,
                height=400
            )

            # Add review section
            if needs_review:
                st.markdown("### ⚠️ Products Needing Review")
                review_df = pd.DataFrame(needs_review)
                review_df.columns = ['Product Name', 'SKU', 'Category', 'Review Notes', 'Serving Size Unit']
                st.dataframe(review_df, use_container_width=True)

        else:
            st.info("No data available. Click 'Refresh Data' to fetch products.")

    except Exception as e:
        error_msg = handle_error(e)
        st.error(f"Error displaying data: {error_msg}")

if __name__ == "__main__":
    main()