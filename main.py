import streamlit as st
import pandas as pd
from scraper import RimiScraper, ScraperError
from database import Database
from additive_manager import AdditiveManager
import logging
import traceback
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import re
import time
from functools import wraps

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def timer_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_time = end_time - start_time
        logger.info(f"Function '{func.__name__}' took {execution_time:.2f} seconds to execute")
        return result
    return wrapper

@timer_decorator
@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_products(_db):
    """Cache product list to avoid repeated database queries"""
    logger.info("Fetching cached products list")
    return _db.get_products()

@timer_decorator
@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_product_nutrition(_db, sku):
    """Cache nutritional information to avoid repeated database queries"""
    logger.info(f"Fetching cached nutrition info for SKU: {sku}")
    return _db.get_product_nutrition(sku)

@timer_decorator
@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_product_additives(_additive_manager, sku, ingredients):
    """Cache additive processing results to avoid repeated processing"""
    logger.info(f"Processing cached additives for SKU: {sku}")
    start_process = time.time()
    stats = _additive_manager.process_product_ingredients(sku, ingredients)
    process_time = time.time() - start_process
    logger.info(f"Additive processing took {process_time:.2f} seconds")

    start_fetch = time.time()
    additives = _additive_manager.get_product_additives(sku) if stats['processed'] else []
    fetch_time = time.time() - start_fetch
    logger.info(f"Additive fetching took {fetch_time:.2f} seconds")

    return stats, additives

def display_product_details(selected_product, df, db):
    """Separate function to handle product details display with timing metrics"""
    start_time = time.time()

    # Get cached nutritional info for selected product
    logger.info(f"Starting to fetch details for product: {selected_product}")
    nutrition = get_cached_product_nutrition(db, selected_product)
    nutrition_time = time.time() - start_time
    logger.info(f"Nutrition info fetch took {nutrition_time:.2f} seconds")

    if nutrition:
        product_info = df[df['sku'] == selected_product].iloc[0]

        # Display product basic info
        start_render = time.time()
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"#### {product_info['name']}")
            st.markdown(f"**Price:** €{product_info['price']}")
            if product_info['price_per_unit']:
                st.markdown(f"**Price per unit:** {product_info['price_per_unit']}")
            st.markdown(f"**Category:** {product_info['category']}")

        render_time = time.time() - start_render
        logger.info(f"Basic info render took {render_time:.2f} seconds")

        # Display nutritional information
        start_nutrition_render = time.time()
        st.markdown("#### 📊 Nutritional Information")
        st.markdown('<div class="nutritional-info">', unsafe_allow_html=True)

        if nutrition['ingredients']:
            st.markdown("##### Ingredients")
            st.markdown(nutrition['ingredients'])

        st.markdown("##### Nutrition per 100g/ml")
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Energy**")
            st.markdown(f"- {nutrition['energy_kj']} kJ")
            st.markdown(f"- {nutrition['energy_kcal']} kcal")

            st.markdown("**Fats**")
            st.markdown(f"- Total: {nutrition['fat']}g")
            st.markdown(f"- Saturated: {nutrition['saturated_fat']}g")

        with col2:
            st.markdown("**Carbohydrates**")
            st.markdown(f"- Total: {nutrition['carbohydrates']}g")
            st.markdown(f"- Sugars: {nutrition['sugars']}g")

            st.markdown("**Other**")
            st.markdown(f"- Protein: {nutrition['protein']}g")
            st.markdown(f"- Salt: {nutrition['salt']}g")

        st.markdown('</div>', unsafe_allow_html=True)
        nutrition_render_time = time.time() - start_nutrition_render
        logger.info(f"Nutrition info render took {nutrition_render_time:.2f} seconds")

        # Display additives
        if nutrition['ingredients']:
            start_additives = time.time()
            display_product_additives(selected_product, nutrition['ingredients'])
            additives_time = time.time() - start_additives
            logger.info(f"Additives display took {additives_time:.2f} seconds")

    else:
        st.warning("No nutritional information available for this product.")

    total_time = time.time() - start_time
    logger.info(f"Total product details display took {total_time:.2f} seconds")

def display_product_additives(sku: str, ingredients: str):
    """Display additives found in the product ingredients"""
    if not ingredients:
        st.warning("No ingredients information available")
        return

    try:
        # Get AdditiveManager from session state
        additive_manager = st.session_state.additive_manager
        logger.info(f"Processing ingredients for product {sku}: {ingredients[:100]}...")

        # Get cached additive information
        stats, additives = get_cached_product_additives(additive_manager, sku, ingredients)

        # Add debug expander
        with st.expander("🔍 Debug Information"):
            st.markdown("#### Processing Statistics")
            st.markdown(f"- Found {stats['additives_found']} additives")
            st.markdown(f"- E-numbers detected: {', '.join(stats['additives'])}")

        if additives:
            st.markdown("### Found Additives")
            # Create columns for additives display
            cols = st.columns(2)
            for idx, additive in enumerate(additives):
                with cols[idx % 2]:
                    with st.expander(f"E{additive.e_number}"):
                        if additive.name:
                            st.markdown(f"**Name:** {additive.name}")
                        if additive.description:
                            st.markdown(f"**Description:** {additive.description}")
                        if additive.safety_rating:
                            st.markdown(f"**Safety Rating:** {additive.safety_rating}")
                        if additive.source_url:
                            st.markdown(f"[More Information]({additive.source_url})")
        else:
            st.info("No additives found in ingredients")

    except Exception as e:
        logger.error(f"Error processing additives: {str(e)}")
        st.error("Failed to process additive information")

def ensure_database_connection():
    """Ensure database connection is active and working"""
    try:
        if 'db' not in st.session_state:
            st.session_state.db = Database()
            logger.info("Database connection established successfully")

            # Initialize AdditiveManager
            st.session_state.additive_manager = AdditiveManager(st.session_state.db)

        # Verify connection is working
        conn = st.session_state.db.get_connection()
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
        st.session_state.db.return_connection(conn)

        return st.session_state.db
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        st.error(f"Failed to connect to database: {str(e)}")
        return None

def main():
    # Initialize session state
    if 'show_debug' not in st.session_state:
        st.session_state.show_debug = False
    if 'debug_logs' not in st.session_state:
        st.session_state.debug_logs = None
    if 'total_products' not in st.session_state:
        st.session_state.total_products = 0
    if 'processed_products' not in st.session_state:
        st.session_state.processed_products = 0
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 1
    if 'total_pages' not in st.session_state:
        st.session_state.total_pages = 0
    if 'specific_products_logs' not in st.session_state:
        st.session_state.specific_products_logs = []
    if 'scraping_logs_history' not in st.session_state:
        st.session_state.scraping_logs_history = []
    if 'current_scraping_logs' not in st.session_state:
        st.session_state.current_scraping_logs = []
    if 'reparse_batch_size' not in st.session_state:
        st.session_state.reparse_batch_size = 50
    if 'current_batch_progress' not in st.session_state:
        st.session_state.current_batch_progress = 0

    # Set page configuration
    st.set_page_config(
        page_title="Product Database",
        page_icon="🛒",
        layout="wide"
    )

    # Initialize database
    db = ensure_database_connection()
    if not db:
        st.error("Database Connection Error")
        return

    # Add tabs for different sections
    tab1, tab2 = st.tabs(["Products Overview", "Product Details"])

    with tab2:
        st.markdown("### 🔍 Product Details")
        try:
            start_time = time.time()
            # Use cached products
            products = get_cached_products(db)
            products_fetch_time = time.time() - start_time
            logger.info(f"Initial products fetch took {products_fetch_time:.2f} seconds")

            if products:
                # Convert to DataFrame for easier handling
                df = pd.DataFrame(products)

                # Create product selector
                start_select = time.time()
                selected_product = st.selectbox(
                    "Select a product to view details:",
                    options=df['sku'].tolist(),
                    format_func=lambda x: df[df['sku'] == x]['name'].iloc[0]
                )
                select_time = time.time() - start_select
                logger.info(f"Product selection took {select_time:.2f} seconds")

                if selected_product:
                    display_product_details(selected_product, df, db)

            else:
                st.info("No products available. Please refresh the data first.")
        except Exception as e:
            logger.error(f"Error displaying product details: {str(e)}")
            st.error(f"Error displaying product details: {str(e)}")

if __name__ == "__main__":
    main()