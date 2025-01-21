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
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    .debug-button>button {
        background-color: #FFB74D !important;
        color: black !important;
    }
    .nutritional-info {
        background-color: #f5f5f5;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    .nutritional-info h4 {
        color: #2196F3;
        margin-bottom: 0.5rem;
    }
    .nutritional-info table {
        width: 100%;
        margin-top: 0.5rem;
    }
    .nutritional-info td {
        padding: 0.25rem;
    }
    .nutritional-info td:first-child {
        font-weight: bold;
        width: 40%;
    }
    .debug-section {
        background-color: #FFF3E0;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    .debug-log {
        font-family: monospace;
        white-space: pre-wrap;
        background-color: #F5F5F5;
        padding: 0.5rem;
        border-radius: 0.25rem;
        margin: 0.25rem 0;
        border-left: 4px solid #FFB74D;
    }
    .debug-log.error {
        border-left-color: #f44336;
    }
    .debug-log.success {
        border-left-color: #4CAF50;
    }
    .debug-instructions {
        background-color: #E3F2FD;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
        border-left: 4px solid #1976D2;
    }
    .debug-header {
        background-color: #1976D2;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 0.25rem;
        margin: 1rem 0;
    }
    .debug-log.warning {
        border-left-color: #FFB74D;
    }
    </style>
""", unsafe_allow_html=True)

def debug_product_url(url: str) -> list:
    """Debug scraping process for a specific URL"""
    debug_logs = []

    def debug_callback(msg: str):
        debug_logs.append(msg)
        print(f"Debug: {msg}")  # Print to console for additional debugging

    try:
        scraper = RimiScraper(status_callback=debug_callback)
        debug_logs.append(f"Starting debug for URL: {url}")

        debug_logs.append("\n=== Starting Nutritional Info Scraping ===")
        # Remove any parentheses and extra whitespace from URL
        cleaned_url = url.strip().strip('()')
        nutrition_info, country_code, quantity = scraper.scrape_nutritional_info(cleaned_url)

        debug_logs.append("\n=== Product Details ===")
        debug_logs.append(f"Country of Origin: {country_code if country_code else 'Not found'}")
        if quantity and quantity[0]:
            debug_logs.append(f"Quantity: {quantity[0]} {quantity[1]}")
        else:
            debug_logs.append("Quantity: Not found")

        debug_logs.append("\n=== Final Nutrition Info ===")
        debug_logs.append(f"Ingredients: {nutrition_info.ingredients[:100]}..." if nutrition_info.ingredients else "No ingredients found")
        debug_logs.append(f"Energy: {nutrition_info.energy_kj}kJ / {nutrition_info.energy_kcal}kcal")
        debug_logs.append(f"Fat: {nutrition_info.fat}g")
        debug_logs.append(f"Saturated Fat: {nutrition_info.saturated_fat}g")
        debug_logs.append(f"Carbohydrates: {nutrition_info.carbohydrates}g")
        debug_logs.append(f"Sugars: {nutrition_info.sugars}g")
        debug_logs.append(f"Protein: {nutrition_info.protein}g")
        debug_logs.append(f"Salt: {nutrition_info.salt}g")

        if nutrition_info.needs_review:
            debug_logs.append(f"\n⚠️ Needs Review: {nutrition_info.review_notes}")

    except Exception as e:
        debug_logs.append(f"❌ Error during scraping: {str(e)}")
        debug_logs.append(traceback.format_exc())

    return debug_logs

SPECIFIC_PRODUCTS = [
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/gatavas-maltites/liellops-burgundijas-gaume-ar-bulguru-400g/p/2000297",
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/piedevas-un-merces/merce-loku-400g/p/2000165",
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/gatavas-maltites/cala-galas-tikkamasala-ar-basm-ris-400g/p/2000291",
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/marineta-gala/calu-pussparni-teriyaki-marinade-400g/p/2000324",
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/uzkodas-plates-kulinarija/cukas-mele-varita-kg/p/2000330",
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/salati/rujienas-salati-200g/p/2000511",
    "https://www.rimi.lv/e-veikals/lv/produkti/gatavots-rimi/jaunums-gatavots-rimi-ipasi-tev-/klingeris-ar-sokoladi-kg/p/228913"
]

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

    # Initialize database
    db = ensure_database_connection()
    if not db:
        st.error("Database Connection Error")
        st.stop()

    # Add tabs for different sections
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "Products Overview", "Product Details", "Debug", "Specific Products Debug",
        "Scraping Logs", "Fix Country Codes", "Export Data", "Ingredient Analysis"
    ])

    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            # Add start page input
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                start_page = st.number_input("Start from page", min_value=1, value=1, step=1, help="Set the starting page number for scraping")

            with col2:
                # Add refresh button
                if st.button("🔄 Refresh All Data"):
                    progress_bar = st.progress(0)
                    progress_text = st.empty()
                    status_text = st.empty()

                    # Clear previous logs for this run
                    st.session_state.current_scraping_logs = []

                    def update_progress(msg: str):
                        # Add log with timestamp
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        st.session_state.current_scraping_logs.append(f"[{timestamp}] {msg}")

                        if "Total products to process:" in msg:
                            match = re.search(r"Total products to process: (\d+) across (\d+) pages", msg)
                            if match:
                                st.session_state.total_products = int(match.group(1))
                                st.session_state.total_pages = int(match.group(2))
                                st.session_state.processed_products = 0
                                progress_text.text(f"Found {st.session_state.total_products} products across {st.session_state.total_pages} pages")
                        elif "Processing page" in msg:
                            match = re.search(r"Processing page (\d+)/(\d+)", msg)
                            if match:
                                st.session_state.current_page = int(match.group(1))
                                progress_text.text(f"Processing page {st.session_state.current_page}/{st.session_state.total_pages}")
                        elif "Successfully parsed product" in msg:
                            st.session_state.processed_products += 1
                            if st.session_state.total_products > 0:
                                progress = st.session_state.processed_products / st.session_state.total_products
                                progress_bar.progress(min(progress, 1.0))
                                status_text.text(f"Processed {st.session_state.processed_products}/{st.session_state.total_products} products")

                    with st.spinner("Scraping product data..."):
                        try:
                            scraper = RimiScraper(status_callback=update_progress)
                            scraper.set_start_page(start_page)  # Set the start page
                            products_with_nutrition = scraper.scrape_products()

                            # Store current run's logs in history with timestamp
                            if st.session_state.current_scraping_logs:
                                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                st.session_state.scraping_logs_history.append((timestamp, st.session_state.current_scraping_logs))

                            if products_with_nutrition:
                                try:
                                    result = db.save_products_with_nutrition(products_with_nutrition)
                                    success_msg = f"""Successfully processed {len(products_with_nutrition)} products!
                                                New: {result['new_products']}, 
                                                Updated: {result['updated_products']}, 
                                                Reviews needed: {result['needs_review']}"""
                                    st.success(success_msg)
                                    # Add final result to logs
                                    update_progress(success_msg)
                                    st.rerun()
                                except Exception as e:
                                    error_msg = f"Error saving products: {str(e)}"
                                    st.error(error_msg)
                                    update_progress(f"❌ {error_msg}")
                            else:
                                warning_msg = "No products found during scraping. Please try again later."
                                st.warning(warning_msg)
                                update_progress(f"⚠️ {warning_msg}")

                        except Exception as e:
                            error_msg = f"Error during data refresh: {str(e)}"
                            st.error(error_msg)
                            update_progress(f"❌ {error_msg}")

                    # Clean up progress indicators
                    progress_bar.empty()
                    progress_text.empty()
                    status_text.empty()

            with col3:
                # Add button for specific products
                if st.button("🎯 Refresh Specific Products"):
                    progress_text = st.empty()

                    with st.spinner("Scraping specific products..."):
                        try:
                            # Create a list to store logs
                            scraping_logs = []
                            def log_callback(msg):
                                progress_text.text(msg)
                                scraping_logs.append(msg)

                            scraper = RimiScraper(status_callback=log_callback)
                            products_with_nutrition = scraper.scrape_specific_products(SPECIFIC_PRODUCTS)

                            # Store logs in session state with timestamp
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            st.session_state.scraping_logs_history.append((timestamp, scraping_logs))

                            if products_with_nutrition:
                                try:
                                    result = db.save_products_with_nutrition(products_with_nutrition)
                                    st.success(f"""Successfully processed specific products!
                                                    New: {result['new_products']}, 
                                                    Updated: {result['updated_products']}, 
                                                    Reviews needed: {result['needs_review']}""")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error saving products: {str(e)}")
                            else:
                                st.warning("No products found during scraping. Please try again later.")

                        except Exception as e:
                            st.error(f"Error during data refresh: {str(e)}")


        # Display existing data
        try:
            products = db.get_products()
            if products:
                st.markdown("### 📊 Products Overview")
                df = pd.DataFrame(products)
                st.dataframe(df)
        except Exception as e:
            st.error(f"Error displaying data: {str(e)}")

    with tab2:
        st.markdown("### 🔍 Product Details")
        try:
            # Use cached products
            products = get_cached_products(db)
            if products:
                # Convert to DataFrame for easier handling
                df = pd.DataFrame(products)

                # Create product selector
                selected_product = st.selectbox(
                    "Select a product to view details:",
                    options=df['sku'].tolist(),
                    format_func=lambda x: df[df['sku'] == x]['name'].iloc[0]
                )

                if selected_product:
                    # Get cached nutritional info for selected product
                    nutrition = get_cached_product_nutrition(db, selected_product)

                    if nutrition:
                        product_info = df[df['sku'] == selected_product].iloc[0]

                        # Display product basic info
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"#### {product_info['name']}")
                            st.markdown(f"**Price:** €{product_info['price']}")
                            if product_info['price_per_unit']:
                                st.markdown(f"**Price per unit:** {product_info['price_per_unit']}")
                            st.markdown(f"**Category:** {product_info['category']}")

                        # Display nutritional information
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

                        if nutrition['ingredients']:
                            display_product_additives(selected_product, nutrition['ingredients'])

                    else:
                        st.warning("No nutritional information available for this product.")
            else:
                st.info("No products available. Please refresh the data first.")
        except Exception as e:
            st.error(f"Error displaying product details: {str(e)}")

    with tab3:
        st.markdown('<div class="debug-header"><h2>🔍 Debug Single Product</h2></div>', unsafe_allow_html=True)
        st.markdown("""
        <div class="debug-instructions">
            <h4>How to use the debugger:</h4>
            <ol>
                <li>Enter a product URL or use the pre-filled example URL</li>
                <li>Click "Start Debug" to begin the scraping process</li>
                <li>Debug logs will appear below showing each step of the process</li>
                <li>Look for the "=== Script Content Analysis ===" section in the logs</li>
            </ol>
        </div>
        """, unsafe_allow_html=True)

        debug_url = st.text_input(
            "Product URL to debug",
            value="https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/uzkodas-plates-kulinarija/lasa-filejas-skelites-mazs-ar-dillem-kg/p/222966"
        )

        if st.button("Start Debug", key="start_debug"):
            st.session_state.debug_logs = debug_product_url(debug_url)

        # Always show debug logs if they exist
        if st.session_state.debug_logs:
            st.markdown('<div class="debug-header"><h3>🔍 Debug Results</h3></div>', unsafe_allow_html=True)
            for log in st.session_state.debug_logs:
                css_class = "debug-log"
                if "error" in log.lower() or "❌" in log:
                    css_class += " error"
                elif "success" in log.lower() or "found" in log.lower():
                    css_class += " success"
                st.markdown(f'<div class="{css_class}">{log}</div>', unsafe_allow_html=True)

    with tab4:
        st.markdown("### 🎯 Specific Products Debug")
        st.markdown("This tab shows detailed information about specific products that need attention.")

        # Display current values for specific products
        st.markdown("#### Current Database Values")
        try:
            specific_skus = ['2000297', '2000165', '2000291', '2000324', '2000330', '2000511', '228913']
            with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT p.*, n.ingredients, n.energy_kj, n.energy_kcal, n.needs_review
                    FROM products p
                    LEFT JOIN product_nutrition n ON p.sku = n.sku
                    WHERE p.sku = ANY(%s)
                    ORDER BY p.sku
                """, (specific_skus,))
                specific_products = cur.fetchall()

                if specific_products:
                    for product in specific_products:
                        with st.expander(f"{product['name']} (SKU: {product['sku']})"):
                            st.markdown("##### Basic Information")
                            st.markdown(f"**Price:** €{product['price']}")
                            st.markdown(f"**Quantity:** {product['quantity_value']} {product['quantity_unit']}")
                            st.markdown(f"**Country:** {product['country_code']}")
                            st.markdown(f"**Last Updated:** {product['updated_at']}")

                            st.markdown("##### Nutritional Information")
                            if product['ingredients']:
                                st.markdown(f"**Ingredients:** {product['ingredients'][:200]}...")
                            if product['energy_kj']:
                                st.markdown(f"**Energy:** {product['energy_kj']}kJ / {product['energy_kcal']}kcal")
                            if product['needs_review']:
                                st.warning("⚠️ This product needs nutrition review")
                else:
                    st.info("No specific products found in database")

        except Exception as e:
            st.error(f"Error fetching specific products: {str(e)}")

        # Display scraping logs
        if st.session_state.specific_products_logs:
            st.markdown("#### Recent Scraping Logs")
            for log in st.session_state.specific_products_logs:
                css_class = "debug-log"
                if "error" in log.lower() or "❌" in log:
                    css_class += " error"
                elif "success" in log.lower() or "found" in log.lower():
                    css_class += " success"
                st.markdown(f'<div class="{css_class}">{log}</div>', unsafe_allow_html=True)

    with tab5:
        st.markdown("### 📝 Scraping Logs History")
        st.markdown("This tab shows the complete history of scraping attempts and their results.")

        # Add clear logs button
        col1, col2 = st.columns([1, 5])
        with col1:
            if st.button("Clear Logs"):
                st.session_state.scraping_logs_history = []
                st.rerun()

        # Display logs with timestamps
        if st.session_state.scraping_logs_history:
            for timestamp, logs in reversed(st.session_state.scraping_logs_history):
                with st.expander(f"Scraping attempt at {timestamp}"):
                    for log in logs:
                        css_class = "debug-log"
                        if "error" in log.lower() or "❌" in log:
                            css_class += " error"
                        elif "success" in log.lower() or "✅" in log:
                            css_class += " success"
                        elif "warning" in log.lower() or "⚠️" in log:
                            css_class += " warning"
                        st.markdown(f'<div class="{css_class}">{log}</div>', unsafe_allow_html=True)
        else:
            st.info("No scraping logs available. Try running the scraper to see the logs.")

    with tab6:
        st.markdown("### 🌍 Fix Missing Country Codes")
        st.markdown("Re-parse products without country codes in batches of 50.")

        # Add button to start re-parsing
        if st.button("🔄 Re-parse Missing Country Codes"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            try:
                db = ensure_database_connection()
                if not db:
                    st.error("Database connection failed")
                    return

                conn = db.get_connection()
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute("""
                            SELECT * FROM products 
                            WHERE country_code IS NULL 
                            LIMIT %s
                        """, (st.session_state.reparse_batch_size,))
                        products_to_reparse = cur.fetchall()

                    if products_to_reparse:
                        scraper = RimiScraper()
                        total = len(products_to_reparse)
                        updated_count = 0

                        for idx, product in enumerate(products_to_reparse):
                            try:
                                nutrition_info, country_code, quantity = scraper.scrape_nutritional_info(
                                    product['product_url'])

                                if country_code:
                                    # Update the country code
                                    with conn.cursor() as cur:
                                        cur.execute("""
                                            UPDATE products 
                                            SET country_code = %s, updated_at = NOW()
                                            WHERE sku = %s
                                        """, (country_code, product['sku']))
                                        conn.commit()
                                    updated_count += 1

                                # Update progress
                                progress = (idx + 1) / total
                                progress_bar.progress(progress)
                                status_text.text(
                                    f"Processed {idx + 1}/{total} products. Updated {updated_count} country codes."
                                )

                            except Exception as e:
                                st.error(f"Error processing product {product['sku']}: {str(e)}")
                                continue

                        st.success(
                            f"Completed re-parsing {total} products. Updated {updated_count} country codes."
                        )
                        if st.button("View Updated Products"):
                            st.rerun()
                    else:
                        st.info("No products found without country codes.")

                finally:
                    db.return_connection(conn)

            except Exception as e:
                st.error(f"Error during re-parsing: {str(e)}")
                logger.error(f"Re-parsing error: {traceback.format_exc()}")


    with tab7:
        st.markdown("### 📥 Export Products Data")
        st.markdown("Export all products with their nutritional information to a CSV file.")

        if st.button("Export to CSV"):
            progress_text = st.empty()
            progress_text.text("Preparing data for export...")

            try:
                db = ensure_database_connection()
                if not db:
                    st.error("Database connection failed")
                    return

                conn = db.get_connection()
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute("""
                            SELECT 
                                p.name, p.price, p.price_per_unit, p.sku, 
                                p.category, p.quantity_value, p.quantity_unit, 
                                p.country_code, p.product_url, p.image_url,
                                n.ingredients, n.energy_kj, n.energy_kcal,
                                n.fat, n.saturated_fat, n.carbohydrates,
                                n.sugars, n.protein, n.salt,
                                n.serving_size_unit, n.needs_review,
                                n.review_notes
                            FROM products p
                            LEFT JOIN product_nutrition n ON p.sku = n.sku
                            ORDER BY p.name
                        """)
                        data = cur.fetchall()

                        if data:
                            df = pd.DataFrame(data)

                            # Convert DataFrame to CSV
                            csv = df.to_csv(index=False)

                            # Create download button
                            st.download_button(
                                label="Download CSV",
                                data=csv,
                                file_name="rimi_products_export.csv",
                                mime="text/csv"
                            )

                            progress_text.text(f"✅ Exported {len(data)} products successfully!")
                        else:
                            st.warning("No products found in the database.")

                finally:
                    db.return_connection(conn)

            except Exception as e:
                st.error(f"Error exporting data: {str(e)}")
                logger.error(f"Export error: {traceback.format_exc()}")

    with tab8:
        st.markdown("### 📊 Ingredient Analysis")
        st.markdown("Analysis of ingredient frequencies across all products")

        # Add refresh button
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🔄 Refresh Analysis"):
                with st.spinner("Refreshing ingredient analysis..."):
                    if refresh_ingredient_analysis(db):
                        st.success("Successfully refreshed ingredient analysis!")
                        st.rerun()
                    else:
                        st.error("Failed to refresh ingredient analysis")

        try:
            ingredients_data = get_ingredient_frequencies(db)

            if ingredients_data:
                # Display total unique ingredients
                st.info(f"Found {len(ingredients_data)} unique ingredients across all products")

                # Create a search box
                search_term = st.text_input("🔍 Search ingredients", "")

                # Filter ingredients based on search
                if search_term:
                    filtered_data = [
                        (ing, freq, prods) 
                        for ing, freq, prods in ingredients_data 
                        if search_term.lower() in ing.lower()
                    ]
                else:
                    filtered_data = ingredients_data

                # Display ingredients table
                for ingredient, frequency, products in filtered_data:
                    with st.expander(f"{ingredient} (Found in {frequency} products)"):
                        st.markdown("#### Products containing this ingredient:")
                        # Create two columns
                        cols = st.columns(2)
                        for idx, product in enumerate(products):
                            col = cols[idx % 2]
                            with col:
                                st.markdown(f"- {product['name']}")
            else:
                st.warning("No ingredient data available. Try refreshing the product data.")

        except Exception as e:
            logger.error(f"Error in ingredient analysis: {str(e)}")
            st.error("Failed to analyze ingredients")


@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_products(_db):
    """Cache product list to avoid repeated database queries"""
    return _db.get_products()

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_product_nutrition(_db, sku):
    """Cache nutritional information to avoid repeated database queries"""
    return _db.get_product_nutrition(sku)

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_product_additives(_additive_manager, sku, ingredients):
    """Cache additive processing results to avoid repeated processing"""
    stats = _additive_manager.process_product_ingredients(sku, ingredients)
    additives = _additive_manager.get_product_additives(sku) if stats['processed'] else []
    return stats, additives

def display_product_additives(sku: str, ingredients: str):
    """Display additives found in the product ingredients"""
    if not ingredients:
        logger.info(f"No ingredients provided for product {sku}")
        return
    try:
        additive_manager = st.session_state.additive_manager
        logger.info(f"Processing ingredients for product {sku}: {ingredients[:100]}...")

        # Get cached additive information
        stats, additives = get_cached_product_additives(additive_manager, sku, ingredients)

        #Add debug expander
        with st.expander("🔍 Debug Information"):
            st.markdown("### Ingredient Processing Debug")
            st.text(f"Processing ingredients for SKU: {sku}")
            st.text(f"Raw ingredients text:\n{ingredients}")
            st.text(f"\nProcessing results:\n{stats}")

            if stats['processed']:
                st.markdown("### Found Additives")
                for additive in additives:
                    st.markdown(f"#### {additive.e_number}")
                    if additive.name:
                        st.markdown(f"**Name:** {additive.name}")
                    if additive.description:
                        st.markdown(f"**Description:** {additive.description}")
                    if additive.safety_rating:
                        st.markdown(f"**Safety Rating:** {additive.safety_rating}")
                    if additive.source_url:
                        st.markdown(f"[More Information]({additive.source_url})")
            else:
                st.warning("No additives found or processing failed")
    # Regular additive display logic
        if stats['processed'] and stats['additives_found'] > 0:
            st.markdown("#### 🧪 Food Additives")
            st.markdown('<div class="nutritional-info">', unsafe_allow_html=True)

            if additives:
                # Create columns for better layout
                cols = st.columns(2)
                for idx, additive in enumerate(additives):
                    col = cols[idx % 2]
                    with col:
                        with st.expander(f"{additive.e_number} - {additive.name or 'Unknown'}"):
                            if additive.description:
                                st.markdown(f"**Description:** {additive.description}")
                            if additive.safety_rating:
                                st.markdown(f"**SafetyRating:** {additive.safety_rating}")
                            if additive.source_url:
                                st.markdown(f"[More Information]({additive.source_url})")
            else:
                st.info("No additive information available in the database.")

            st.markdown('</div>', unsafe_allow_html=True)
        else:
            logger.info(f"No additives found in ingredients for product {sku}")
            st.info("No food additives (E-numbers) found in this product.")

    except Exception as e:
        logger.error(f"Error displaying additives for {sku}: {str(e)}")
        st.error("Failed to process additive information")



def normalize_ingredient(ingredient: str) -> str:
    """Normalize ingredient text by removing quantities and converting to lowercase"""
    # Remove percentages and numbers
    cleaned = re.sub(r'\d+\.?\d*\s*%?', '', ingredient)
    # Remove parentheses and their contents
    cleaned = re.sub(r'\([^)]*\)', '', cleaned)
    # Convert to lowercase and strip whitespace
    cleaned = cleaned.lower().strip()
    return cleaned

def get_ingredient_frequencies(db: Database) -> List[Tuple[str, int, List[Dict]]]:
    """
    Get ingredient frequencies and related products from the cached analysis
    """
    try:
        conn = db.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        ia.ingredient,
                        ia.frequency,
                        array_agg(json_build_object(
                            'sku', p.sku,
                            'name', p.name
                        )) as products
                    FROM ingredient_analysis ia
                    JOIN ingredient_product_mapping ipm ON ia.id = ipm.ingredient_id
                    JOIN products p ON p.sku = ipm.product_sku
                    GROUP BY ia.id, ia.ingredient, ia.frequency
                    ORDER BY ia.frequency DESC, ia.ingredient
                """)
                results = cur.fetchall()

                return [(row['ingredient'], row['frequency'], row['products']) for row in results]

        finally:
            db.return_connection(conn)
    except Exception as e:
        logger.error(f"Error getting ingredient frequencies: {str(e)}")
        return []

# In the main() function, modify the tab8 section:
    with tab8:
        st.markdown("### 📊 Ingredient Analysis")
        st.markdown("Analysis of ingredient frequencies across all products")

        # Add refresh button
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🔄 Refresh Analysis"):
                with st.spinner("Refreshing ingredient analysis..."):
                    if refresh_ingredient_analysis(db):
                        st.success("Successfully refreshed ingredient analysis!")
                        st.rerun()
                    else:
                        st.error("Failed to refresh ingredient analysis")

        try:
            ingredients_data = get_ingredient_frequencies(db)

            if ingredients_data:
                # Display total unique ingredients
                st.info(f"Found {len(ingredients_data)} unique ingredients across all products")

                # Create a search box
                search_term = st.text_input("🔍 Search ingredients", "")

                # Filter ingredients based on search
                if search_term:
                    filtered_data = [
                        (ing, freq, prods) 
                        for ing, freq, prods in ingredients_data 
                        if search_term.lower() in ing.lower()
                    ]
                else:
                    filtered_data = ingredients_data

                # Display ingredients table
                for ingredient, frequency, products in filtered_data:
                    with st.expander(f"{ingredient} (Found in {frequency} products)"):
                        st.markdown("#### Products containing this ingredient:")
                        # Create two columns
                        cols = st.columns(2)
                        for idx, product in enumerate(products):
                            col = cols[idx % 2]
                            with col:
                                st.markdown(f"- {product['name']}")
            else:
                st.warning("No ingredient data available. Try refreshing the product data.")

        except Exception as e:
            logger.error(f"Error in ingredient analysis: {str(e)}")
            st.error("Failed to analyze ingredients")


@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_products(_db):
    """Cache product list to avoid repeated database queries"""
    return _db.get_products()

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_product_nutrition(_db, sku):
    """Cache nutritional information to avoid repeated database queries"""
    return _db.get_product_nutrition(sku)

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_product_additives(_additive_manager, sku, ingredients):
    """Cache additive processing results to avoid repeated processing"""
    stats = _additive_manager.process_product_ingredients(sku, ingredients)
    additives = _additive_manager.get_product_additives(sku) if stats['processed'] else []
    return stats, additives

def display_product_additives(sku: str, ingredients: str):
    """Display additives found in the product ingredients"""
    if not ingredients:
        logger.info(f"No ingredients provided for product {sku}")
        return
    try:
        additive_manager = st.session_state.additive_manager
        logger.info(f"Processing ingredients for product {sku}: {ingredients[:100]}...")

        # Get cached additive information
        stats, additives = get_cached_product_additives(additive_manager, sku, ingredients)

        #Add debug expander
        with st.expander("🔍 Debug Information"):
            st.markdown("### Ingredient Processing Debug")
            st.text(f"Processing ingredients for SKU: {sku}")
            st.text(f"Raw ingredients text:\n{ingredients}")
            st.text(f"\nProcessing results:\n{stats}")

            if stats['processed']:
                st.markdown("### Found Additives")
                for additive in additives:
                    st.markdown(f"#### {additive.e_number}")
                    if additive.name:
                        st.markdown(f"**Name:** {additive.name}")
                    if additive.description:
                        st.markdown(f"**Description:** {additive.description}")
                    if additive.safety_rating:
                        st.markdown(f"**Safety Rating:** {additive.safety_rating}")
                    if additive.source_url:
                        st.markdown(f"[More Information]({additive.source_url})")
            else:
                st.warning("No additives found or processing failed")
        # Regular additive display logic
        if stats['processed'] and stats['additives_found'] > 0:
            st.markdown("#### 🧪 Food Additives")
            st.markdown('<div class="nutritional-info">', unsafe_allow_html=True)

            if additives:
                # Create columns for better layout
                cols = st.columns(2)
                for idx, additive in enumerate(additives):
                    col = cols[idx % 2]
                    with col:
                        with st.expander(f"{additive.e_number} - {additive.name or 'Unknown'}"):
                            if additive.description:
                                st.markdown(f"**Description:** {additive.description}")
                            if additive.safety_rating:
                                st.markdown(f"**SafetyRating:** {additive.safety_rating}")
                            if additive.source_url:
                                st.markdown(f"[More Information]({additive.source_url})")
            else:
                st.info("No additive information available in the database.")

            st.markdown('</div>', unsafe_allow_html=True)
        else:
            logger.info(f"No additives found in ingredients for product {sku}")
            st.info("No food additives (E-numbers) found in this product.")

    except Exception as e:
        logger.error(f"Error displaying additives for {sku}: {str(e)}")
        st.error("Failed to process additive information")



def refresh_ingredient_analysis(db: Database) -> bool:
    """
    Refresh the ingredient analysis tables with current data
    Returns: True if successful, False otherwise
    """
    try:
        conn = db.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # First, clear existing analysis
                cur.execute("TRUNCATE ingredient_analysis CASCADE")

                # Get all products with ingredients
                cur.execute("""
                    SELECT p.sku, p.name, n.ingredients
                    FROM products p
                    JOIN product_nutrition n ON p.sku = n.sku
                    WHERE n.ingredients IS NOT NULL AND n.ingredients != ''
                """)
                products = cur.fetchall()

                # Process ingredients
                ingredient_data = defaultdict(lambda: {'count': 0, 'products': []})

                # First pass: collect data
                for product in products:
                    ingredients_text = product['ingredients']
                    ingredients = re.split(r'[,;.]', ingredients_text)

                    for ingredient in ingredients:
                        normalized = normalize_ingredient(ingredient)
                        if normalized:
                            ingredient_data[normalized]['count'] += 1
                            ingredient_data[normalized]['products'].append(product)

                # Second pass: insert data
                for ingredient, data in ingredient_data.items():
                    # Insert ingredient
                    cur.execute("""
                        INSERT INTO ingredient_analysis (ingredient, frequency)
                        VALUES (%s, %s)
                        RETURNING id
                    """, (ingredient, data['count']))
                    ingredient_id = cur.fetchone()['id']

                    # Insert product mappings
                    for product in data['products']:
                        cur.execute("""
                            INSERT INTO ingredient_product_mapping (ingredient_id, product_sku)
                            VALUES (%s, %s)
                        """, (ingredient_id, product['sku']))

                conn.commit()
                return True

        finally:
            db.return_connection(conn)
    except Exception as e:
        logger.error(f"Error refreshing ingredient analysis: {str(e)}")
        return False

def get_ingredient_frequencies(db: Database) -> List[Tuple[str, int, List[Dict]]]:
    """
    Get ingredient frequencies and related products from the cached analysis
    """
    try:
        conn = db.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        ia.ingredient,
                        ia.frequency,
                        array_agg(json_build_object(
                            'sku', p.sku,
                            'name', p.name
                        )) as products
                    FROM ingredient_analysis ia
                    JOIN ingredient_product_mapping ipm ON ia.id = ipm.ingredient_id
                    JOIN products p ON p.sku = ipm.product_sku
                    GROUP BY ia.id, ia.ingredient, ia.frequency
                    ORDER BY ia.frequency DESC, ia.ingredient
                """)
                results = cur.fetchall()

                return [(row['ingredient'], row['frequency'], row['products']) for row in results]

        finally:
            db.return_connection(conn)
    except Exception as e:
        logger.error(f"Error getting ingredient frequencies: {str(e)}")
        return []

    with tab7:
        st.markdown("### 📥 Export Products Data")
        st.markdown("Export all products with their nutritional information to a CSV file.")

        if st.button("Export to CSV"):
            progress_text = st.empty()
            progress_text.text("Preparing data for export...")

            try:
                db = ensure_database_connection()
                if not db:
                    st.error("Database connection failed")
                    return

                conn = db.get_connection()
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute("""
                            SELECT 
                                p.name, p.price, p.price_per_unit, p.sku, 
                                p.category, p.quantity_value, p.quantity_unit, 
                                p.country_code, p.product_url, p.image_url,
                                n.ingredients, n.energy_kj, n.energy_kcal,
                                n.fat, n.saturated_fat, n.carbohydrates,
                                n.sugars, n.protein, n.salt,
                                n.serving_size_unit, n.needs_review,
                                n.review_notes
                            FROM products p
                            LEFT JOIN product_nutrition n ON p.sku = n.sku
                            ORDER BY p.name
                        """)
                        data = cur.fetchall()

                        if data:
                            df = pd.DataFrame(data)

                            # Convert DataFrame to CSV
                            csv = df.to_csv(index=False)

                            # Create download button
                            st.download_button(
                                label="Download CSV",
                                data=csv,
                                file_name="rimi_products_export.csv",
                                mime="text/csv"
                            )

                            progress_text.text(f"✅ Exported {len(data)} products successfully!")
                        else:
                            st.warning("No products found in the database.")

                finally:
                    db.return_connection(conn)

            except Exception as e:
                st.error(f"Error exporting data: {str(e)}")
                logger.error(f"Export error: {traceback.format_exc()}")

    with tab8:
        st.markdown("### 📊 Ingredient Analysis")
        st.markdown("Analysis of ingredient frequencies across all products")

        # Add refresh button
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🔄 Refresh Analysis"):
                with st.spinner("Refreshing ingredient analysis..."):
                    if refresh_ingredient_analysis(db):
                        st.success("Successfully refreshed ingredient analysis!")
                        st.rerun()
                    else:
                        st.error("Failed to refresh ingredient analysis")

        try:
            ingredients_data = get_ingredient_frequencies(db)

            if ingredients_data:
                # Display total unique ingredients
                st.info(f"Found {len(ingredients_data)} unique ingredients across all products")

                # Create a search box
                search_term = st.text_input("🔍 Search ingredients", "")

                # Filter ingredients based on search
                if search_term:
                    filtered_data = [
                        (ing, freq, prods) 
                        for ing, freq, prods in ingredients_data 
                        if search_term.lower() in ing.lower()
                    ]
                else:
                    filtered_data = ingredients_data

                # Display ingredients table
                for ingredient, frequency, products in filtered_data:
                    with st.expander(f"{ingredient} (Found in {frequency} products)"):
                        st.markdown("#### Products containing this ingredient:")
                        # Create two columns
                        cols = st.columns(2)
                        for idx, product in enumerate(products):
                            col = cols[idx % 2]
                            with col:
                                st.markdown(f"- {product['name']}")
            else:
                st.warning("No ingredient data available. Try refreshing the product data.")

        except Exception as e:
            logger.error(f"Error in ingredient analysis: {str(e)}")
            st.error("Failed to analyze ingredients")


@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_products(_db):
    """Cache product list to avoid repeated database queries"""
    return _db.get_products()

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_product_nutrition(_db, sku):
    """Cache nutritional information to avoid repeated database queries"""
    return _db.get_product_nutrition(sku)

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_product_additives(_additive_manager, sku, ingredients):
    """Cache additive processing results to avoid repeated processing"""
    stats = _additive_manager.process_product_ingredients(sku, ingredients)
    additives = _additive_manager.get_product_additives(sku) if stats['processed'] else []
    return stats, additives

def display_product_additives(sku: str, ingredients: str):
    """Display additives found in the product ingredients"""
    if not ingredients:
        logger.info(f"No ingredients provided for product {sku}")
        return
    try:
        additive_manager = st.session_state.additive_manager
        logger.info(f"Processing ingredients for product {sku}: {ingredients[:100]}...")

        # Get cached additive information
        stats, additives = get_cached_product_additives(additive_manager, sku, ingredients)

        #Add debug expander
        with st.expander("🔍 Debug Information"):
            st.markdown("### Ingredient Processing Debug")
            st.text(f"Processing ingredients for SKU: {sku}")
            st.text(f"Raw ingredients text:\n{ingredients}")
            st.text(f"\nProcessing results:\n{stats}")

            if stats['processed']:
                st.markdown("### Found Additives")
                for additive in additives:
                    st.markdown(f"#### {additive.e_number}")
                    if additive.name:
                        st.markdown(f"**Name:** {additive.name}")
                    if additive.description:
                        st.markdown(f"**Description:** {additive.description}")
                    if additive.safety_rating:
                        st.markdown(f"**Safety Rating:** {additive.safety_rating}")
                    if additive.source_url:
                        st.markdown(f"[More Information]({additive.source_url})")
            else:
                st.warning("No additives found or processing failed")
        # Regular additive display logic
        if stats['processed'] and stats['additives_found'] > 0:
            st.markdown("#### 🧪 Food Additives")
            st.markdown('<div class="nutritional-info">', unsafe_allow_html=True)

            if additives:
                # Create columns for better layout
                cols = st.columns(2)
                for idx, additive in enumerate(additives):
                    col = cols[idx % 2]
                    with col:
                        with st.expander(f"{additive.e_number} - {additive.name or 'Unknown'}"):
                            if additive.description:
                                st.markdown(f"**Description:** {additive.description}")
                            if additive.safety_rating:
                                st.markdown(f"**SafetyRating:** {additive.safety_rating}")
                            if additive.source_url:
                                st.markdown(f"[More Information]({additive.source_url})")
            else:
                st.info("No additive information available in the database.")

            st.markdown('</div>', unsafe_allow_html=True)
        else:
            logger.info(f"No additives found in ingredients for product {sku}")
            st.info("No food additives (E-numbers) found in this product.")

    except Exception as e:
        logger.error(f"Error displaying additives for {sku}: {str(e)}")
        st.error("Failed to process additive information")



if __name__ == "__main__":
    main()