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
import time

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

# Initialize session state for ingredient filtering
if 'selected_ingredient' not in st.session_state:
    st.session_state.selected_ingredient = None
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = 0

def select_ingredient(ingredient: str):
    """Callback for ingredient selection"""
    st.session_state.selected_ingredient = ingredient
    st.session_state.active_tab = 0  # Switch to products tab
    st.experimental_rerun()

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_products(_db):
    """Cache product list to avoid repeated database queries"""
    return _db.get_products()

@st.cache_data(ttl=300)  # Cache data for 5 minutes
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
        try:
            products = db.get_products()
            if products:
                df = pd.DataFrame(products)

                # Filter products if ingredient is selected
                if st.session_state.selected_ingredient:
                    st.info(f"Showing products containing: {st.session_state.selected_ingredient}")
                    # Clear filter button
                    if st.button("Clear Filter"):
                        st.session_state.selected_ingredient = None
                        st.experimental_rerun()

                    # Filter products containing the selected ingredient
                    filtered_products = []
                    for product in products:
                        nutrition = get_cached_product_nutrition(db, product['sku'])
                        if nutrition and nutrition.get('ingredients'):
                            if st.session_state.selected_ingredient.lower() in nutrition['ingredients'].lower():
                                filtered_products.append(product)

                    if filtered_products:
                        df = pd.DataFrame(filtered_products)
                        st.dataframe(df)
                    else:
                        st.warning("No products found containing this ingredient.")
                else:
                    st.dataframe(df)
            else:
                st.info("No products available. Please refresh the data.")
        except Exception as e:
            st.error(f"Error loading products: {str(e)}")

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
            except Exception as e:
                logger.error(f"Database error: {str(e)}")
                st.error(f"Error querying database: {str(e)}")
            finally:
                db.return_connection(conn)

            if ingredients_data:
                st.info(f"Found {len(ingredients_data)} unique ingredients")

                # Search box
                search_term = st.text_input("🔍 Search ingredients", "")

                # Filter and display ingredients
                filtered_data = [
                    (ing, freq) for ing, freq in ingredients_data
                    if not search_term or search_term.lower() in ing.lower()
                ]

                if filtered_data:
                    col1, col2 = st.columns(2)
                    for idx, (ingredient, frequency) in enumerate(filtered_data):
                        col = col1 if idx % 2 == 0 else col2
                        with col:
                            # Make ingredient name clickable
                            if st.button(
                                f"**{ingredient}** ({frequency} products)",
                                key=f"ing_{idx}",
                                help="Click to view products containing this ingredient"
                            ):
                                select_ingredient(ingredient)
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

    # Tab 2: Product Details
    with tabs[1]:
        st.title("Product Details")
        selected_sku = st.text_input("Enter product SKU:", "")
        if selected_sku:
            try:
                product = db.get_product_by_sku(selected_sku)
                if product:
                    st.write(product)
                    display_product_additives(selected_sku, product.get('ingredients'))
                    nutrition = db.get_product_nutrition(selected_sku)
                    if nutrition:
                        st.json(nutrition)
                else:
                    st.warning("Product not found.")
            except Exception as e:
                st.error(f"Error loading product details: {str(e)}")

    # Tab 3: Debug
    with tabs[2]:
        st.title("Debug")
        # Your debug code here

    # Tab 4: Specific Products Debug
    with tabs[3]:
        st.title("Specific Products Debug")
        selected_product_url = st.selectbox("Select a product", SPECIFIC_PRODUCTS)
        if selected_product_url:
            debug_logs = debug_product_url(selected_product_url)
            for log in debug_logs:
                st.markdown(f"<div class='debug-log'>{log}</div>", unsafe_allow_html=True)

    # Tab 5: Scraping Logs
    with tabs[4]:
        st.title("Scraping Logs")
        # Your scraping log display code here

    # Tab 6: Fix Country Codes
    with tabs[5]:
        st.title("Fix Country Codes")
        # Your country code fixing code here

    # Tab 7: Export Data
    with tabs[6]:
        st.title("Export Data")
        # Your data export code here


    # Tab 8: Ingredient Analysis (already defined above)


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