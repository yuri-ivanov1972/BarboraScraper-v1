import streamlit as st
import pandas as pd
from scraper import RimiScraper, ScraperError
from database import Database
from additive_manager import AdditiveManager
from database_integration import ExternalDatabaseManager
from enhanced_scraper import EnhancedRimiScraper
import logging
import traceback
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import re
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
import time
import json

# Page configuration must be the first Streamlit command
st.set_page_config(
    page_title="Rimi Product Scraper",
    page_icon="🛒",
    layout="wide"
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@st.cache_data(ttl=300)
def get_cached_products(_db):
    """Cache product list to avoid repeated database queries"""
    return _db.get_products()

@st.cache_data(ttl=300)
def get_cached_product_nutrition(_db, sku):
    """Cache nutritional information to avoid repeated database queries"""
    return _db.get_product_nutrition(sku)

def normalize_ingredient(ingredient: str) -> str:
    """Normalize ingredient text for consistent analysis"""
    if not ingredient:
        return ""
    normalized = ingredient.strip().lower()
    normalized = re.sub(r'\d+[.,]?\d*\s*%', '', normalized)
    normalized = re.sub(r'[\[\]\(\)]', '', normalized)
    normalized = re.sub(r'[^\w\s]', ' ', normalized)
    normalized = ' '.join(normalized.split())
    return normalized

def refresh_ingredient_analysis(db: Database) -> bool:
    """Refresh the ingredient analysis tables with current data"""
    try:
        conn = db.get_connection()
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Clear existing analysis
                cur.execute("TRUNCATE ingredient_analysis RESTART IDENTITY CASCADE")

                # Get products with ingredients
                cur.execute("""
                    SELECT p.sku, p.name, n.ingredients
                    FROM products p
                    JOIN product_nutrition n ON p.sku = n.sku
                    WHERE n.ingredients IS NOT NULL AND n.ingredients != ''
                """)
                products = cur.fetchall()

                total_products = len(products)
                status_text.text(f"Found {total_products} products to process")

                # Process ingredients
                ingredient_counts = defaultdict(int)
                processed = 0

                for product in products:
                    ingredients_text = product['ingredients']
                    ingredients = re.split(r'[,;]|\(|\)', ingredients_text)

                    for ingredient in ingredients:
                        normalized = normalize_ingredient(ingredient)
                        if normalized and len(normalized) > 1:
                            ingredient_counts[normalized] += 1

                    processed += 1
                    progress = processed / total_products
                    progress_bar.progress(progress)
                    status_text.text(f"Processing products: {processed}/{total_products}")

                # Save to database
                status_text.text("Saving to database...")
                for ingredient, count in ingredient_counts.items():
                    cur.execute("""
                        INSERT INTO ingredient_analysis (ingredient, frequency)
                        VALUES (%s, %s)
                    """, (ingredient, count))

                conn.commit()
                status_text.text("✅ Analysis completed successfully!")
                return True

        finally:
            db.return_connection(conn)

    except Exception as e:
        logger.error(f"Error in refresh_ingredient_analysis: {str(e)}")
        if 'status_text' in locals():
            status_text.text(f"❌ Error during analysis: {str(e)}")
        return False

def ensure_database_connection():
    """Ensure database connection is active and working"""
    try:
        if 'db' not in st.session_state:
            st.session_state.db = Database()
            logger.info("Database connection established successfully")
            st.session_state.additive_manager = AdditiveManager(st.session_state.db)

        # Verify connection
        conn = st.session_state.db.get_connection()
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
        st.session_state.db.return_connection(conn)
        return st.session_state.db
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        st.error(f"Failed to connect to database: {str(e)}")
        return None

def get_products_with_ingredient(db: Database, ingredient_filter: str = None) -> List[Dict]:
    """Get products, optionally filtered by ingredient"""
    try:
        conn = db.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if ingredient_filter:
                    # Query products containing the specified ingredient
                    cur.execute("""
                        SELECT DISTINCT p.* 
                        FROM products p
                        JOIN product_nutrition n ON p.sku = n.sku
                        WHERE LOWER(n.ingredients) LIKE LOWER(%s)
                        ORDER BY p.name
                    """, (f'%{ingredient_filter}%',))
                else:
                    # Get all products if no filter
                    cur.execute("SELECT * FROM products ORDER BY name")
                return cur.fetchall()
        finally:
            db.return_connection(conn)
    except Exception as e:
        logger.error(f"Error getting products with ingredient filter: {str(e)}")
        return []

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
                                st.markdown(f"**Safety Rating:** {additive.safety_rating}")
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



def main():
    # Initialize database connection
    db = ensure_database_connection()
    if not db:
        st.error("Database Connection Error")
        return

    # Create tabs
    tabs = st.tabs([
        "Products Overview",
        "Product Details",
        "Debug",
        "Specific Products Debug",
        "Scraping Logs",
        "Fix Country Codes",
        "Export Data",
        "Ingredient Analysis"
    ])

    # Tab 1: Products Overview
    with tabs[0]:
        st.title("Products Overview")

        # Add ingredient filter
        col1, col2 = st.columns([3, 1])
        with col1:
            ingredient_filter = st.text_input(
                "🔍 Filter by ingredient (copy from Ingredient Analysis tab)",
                key="product_ingredient_filter"
            )
        with col2:
            if st.button("Clear Filter", key="clear_ingredient_filter"):
                ingredient_filter = ""
                st.session_state.product_ingredient_filter = ""

        try:
            # Get filtered products
            products = get_products_with_ingredient(db, ingredient_filter)

            if products:
                df = pd.DataFrame(products)

                # Display filter status
                if ingredient_filter:
                    st.info(f"Showing products containing: {ingredient_filter}")
                    st.text(f"Found {len(products)} products")

                # Display products table
                st.dataframe(df)
            else:
                if ingredient_filter:
                    st.warning(f"No products found containing '{ingredient_filter}'")
                else:
                    st.info("No products available. Please refresh the data.")
        except Exception as e:
            st.error(f"Error loading products: {str(e)}")

    # Tab 2: Product Details
    with tabs[1]:
        st.title("Product Details")
        try:
            products = get_cached_products(db)
            if products:
                df = pd.DataFrame(products)
                selected_product = st.selectbox(
                    "Select a product to view details:",
                    options=df['sku'].tolist(),
                    format_func=lambda x: df[df['sku'] == x]['name'].iloc[0]
                )

                if selected_product:
                    nutrition = get_cached_product_nutrition(db, selected_product)
                    if nutrition:
                        product_info = df[df['sku'] == selected_product].iloc[0]

                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"#### {product_info['name']}")
                            st.markdown(f"**Price:** €{product_info['price']}")
                            if product_info['price_per_unit']:
                                st.markdown(f"**Price per unit:** {product_info['price_per_unit']}")
                            st.markdown(f"**Category:** {product_info['category']}")

                        st.markdown("#### 📊 Nutritional Information")
                        st.markdown('<div class="nutritional-info">', unsafe_allow_html=True)

                        if nutrition['ingredients']:
                            st.markdown("##### Ingredients")
                            st.markdown(nutrition['ingredients'])

                            # Display additives information
                            display_product_additives(selected_product, nutrition['ingredients'])
                    else:
                        st.warning("No nutritional information available for this product.")
            else:
                st.info("No products available. Please refresh the data first.")
        except Exception as e:
            st.error(f"Error displaying product details: {str(e)}")

    # Tab 3: Debug
    with tabs[2]:
        st.title("Debug Single Product")
        debug_url = st.text_input(
            "Product URL to debug",
            value="https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/uzkodas-plates-kulinarija/lasa-filejas-skelites-mazs-ar-dillem-kg/p/222966"
        )

        if st.button("Start Debug", key="start_debug"):
            debug_logs = debug_product_url(debug_url)
            for log in debug_logs:
                st.text(log)

    # Tab 4: Specific Products Debug
    with tabs[3]:
        st.title("Specific Products Debug")
        if st.button("Debug Specific Products", key="debug_specific"):
            for url in SPECIFIC_PRODUCTS:
                st.markdown(f"### Debugging {url}")
                debug_logs = debug_product_url(url)
                for log in debug_logs:
                    st.text(log)

    # Tab 5: Scraping Logs
    with tabs[4]:
        st.title("Scraping Logs")
        if 'scraping_logs' not in st.session_state:
            st.session_state.scraping_logs = []

        if st.button("Clear Logs", key="clear_logs"):
            st.session_state.scraping_logs = []
            st.success("Logs cleared!")

        for log in st.session_state.scraping_logs:
            st.text(log)

    # Tab 6: Fix Country Codes
    with tabs[5]:
        st.title("Fix Country Codes")
        if st.button("Reparse Missing Country Codes", key="reparse_countries"):
            try:
                with st.spinner("Checking products without country codes..."):
                    conn = db.get_connection()
                    with conn.cursor() as cur:
                        cur.execute("SELECT COUNT(*) FROM products WHERE country_code IS NULL")
                        missing_count = cur.fetchone()[0]
                    db.return_connection(conn)

                    if missing_count > 0:
                        st.info(f"Found {missing_count} products without country codes")
                    else:
                        st.success("All products have country codes!")
            except Exception as e:
                st.error(f"Error checking country codes: {str(e)}")

    # Tab 7: Export Data
    with tabs[6]:
        st.title("Export Data")

        # Products export section
        st.header("Products Export")
        if st.button("Export Products to CSV", key="export_csv"):
            try:
                products = db.get_products()
                if products:
                    df = pd.DataFrame(products)
                    csv = df.to_csv(index=False)
                    st.download_button(
                        label="Download Products CSV",
                        data=csv,
                        file_name="products_export.csv",
                        mime="text/csv"
                    )
                else:
                    st.warning("No products data to export")
            except Exception as e:
                st.error(f"Error exporting products data: {str(e)}")

        # Ingredients export section
        st.header("Ingredients Export")
        if st.button("Export Ingredients to CSV", key="export_ingredients"):
            try:
                conn = db.get_connection()
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT ingredient, frequency 
                            FROM ingredient_analysis 
                            ORDER BY frequency DESC, ingredient
                        """)
                        ingredients_data = cur.fetchall()

                        if ingredients_data:
                            # Convert to DataFrame
                            df = pd.DataFrame(ingredients_data, columns=['Ingredient', 'Number of Products'])
                            csv = df.to_csv(index=False)
                            st.download_button(
                                label="Download Ingredients CSV",
                                data=csv,
                                file_name="ingredients_export.csv",
                                mime="text/csv"
                            )
                        else:
                            st.warning("No ingredients data to export")
                finally:
                    db.return_connection(conn)
            except Exception as e:
                st.error(f"Error exporting ingredients data: {str(e)}")

    # Tab 8: Ingredient Analysis
    with tabs[7]:
        st.title("Ingredient Analysis")
        st.markdown("### 📊 Ingredient Analysis")

        # Add refresh button with unique key
        if st.button("🔄 Refresh Analysis", key="refresh_ingredients_analysis"):
            with st.spinner("Refreshing ingredient analysis..."):
                if refresh_ingredient_analysis(db):
                    st.success("Successfully refreshed ingredient analysis!")
                    st.experimental_rerun()
                else:
                    st.error("Failed to refresh ingredient analysis")

        try:
            # Query ingredient analysis data
            ingredients_data = None
            conn = db.get_connection()
            try:
                with conn.cursor() as cur:
                    logger.info("Querying ingredient analysis data...")
                    cur.execute("""
                        SELECT ingredient, frequency 
                        FROM ingredient_analysis 
                        ORDER BY frequency DESC
                    """)
                    ingredients_data = cur.fetchall()
                    logger.info(f"Found {len(ingredients_data) if ingredients_data else 0} ingredients")
            finally:
                db.return_connection(conn)

            if ingredients_data:
                st.info(f"Found {len(ingredients_data)} unique ingredients")
                search_term = st.text_input("🔍 Search ingredients", "")

                filtered_data = [
                    (ing, freq) for ing, freq in ingredients_data
                    if not search_term or search_term.lower() in ing.lower()
                ]

                if filtered_data:
                    col1, col2 = st.columns(2)
                    for idx, (ingredient, frequency) in enumerate(filtered_data):
                        col = col1 if idx % 2 == 0 else col2
                        with col:
                            st.markdown(f"**{ingredient}** ({frequency} products)")
                else:
                    if search_term:
                        st.warning("No ingredients found matching your search.")
                    else:
                        st.warning("No ingredients found in the database.")
            else:
                st.warning("No ingredient data available. Try refreshing the analysis.")

        except Exception as e:
            logger.error(f"Error in ingredient analysis: {str(e)}")
            st.error(f"Failed to analyze ingredients: {str(e)}")

if __name__ == "__main__":
    main()

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

def get_ingredient_frequencies(db: Database) -> List[Tuple[str, int, List[Dict]]]:
    """Get ingredient frequencies and related products from the cached analysis"""
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