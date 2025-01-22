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

# Page configuration must be the first Streamlit command
st.set_page_config(
    page_title="Rimi Product Scraper",
    page_icon="🛒",
    layout="wide"
)

# Constants
SPECIFIC_PRODUCTS = [
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/gatavas-maltites/liellops-burgundijas-gaume-ar-bulguru-400g/p/2000297",
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/piedevas-un-merces/merce-loku-400g/p/2000165",
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/gatavas-maltites/cala-galas-tikkamasala-ar-basm-ris-400g/p/2000291",
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/marineta-gala/calu-pussparni-teriyaki-marinade-400g/p/2000324",
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/uzkodas-plates-kulinarija/cukas-mele-varita-kg/p/2000330",
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/salati/rujienas-salati-200g/p/2000511",
    "https://www.rimi.lv/e-veikals/lv/produkti/gatavots-rimi/jaunums-gatavots-rimi-ipasi-tev-/klingeris-ar-sokoladi-kg/p/228913"
]

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

@st.cache_data(ttl=300)
def get_cached_product_additives(_additive_manager, sku, ingredients):
    """Cache additive processing results to avoid repeated processing"""
    if not ingredients:
        return None, []
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



def select_ingredient(ingredient: str):
    """Callback for ingredient selection"""
    logger.info(f"Selecting ingredient: {ingredient}")
    logger.info(f"Previous active tab: {st.session_state.active_tab}")
    logger.info(f"Previous selected ingredient: {st.session_state.selected_ingredient}")

    # Update session state
    st.session_state.selected_ingredient = ingredient
    st.session_state.active_tab = 0

    logger.info(f"Updated session state - active_tab: {st.session_state.active_tab}")
    logger.info(f"Updated session state - selected_ingredient: {st.session_state.selected_ingredient}")

    # Force UI refresh
    st.rerun()

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_products(_db):
    """Cache product list to avoid repeated database queries"""
    try:
        conn = _db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.*, n.ingredients 
                    FROM products p
                    LEFT JOIN product_nutrition n ON p.sku = n.sku
                """)
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        finally:
            _db.return_connection(conn)
    except Exception as e:
        logger.error(f"Error getting cached products: {str(e)}")
        return []

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_product_by_name(_db, product_name: str) -> Optional[List[Dict]]:
    """Cache product search results to avoid repeated database queries"""
    try:
        conn = _db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.*, n.ingredients 
                    FROM products p
                    LEFT JOIN product_nutrition n ON p.sku = n.sku
                    WHERE LOWER(p.name) LIKE LOWER(%s)
                    LIMIT 10
                """, (f"%{product_name}%",))
                columns = [desc[0] for desc in cur.description]
                products = [dict(zip(columns, row)) for row in cur.fetchall()]
                return products if products else None
        finally:
            _db.return_connection(conn)
    except Exception as e:
        logger.error(f"Error searching for product: {str(e)}")
        return None

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

def refresh_ingredient_analysis(db: Database) -> bool:
    """Refresh the ingredient analysis tables with current data"""
    try:
        conn = db.get_connection()
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            with conn.cursor() as cur:
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

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_product_nutrition(_db, sku):
    """Cache nutritional information to avoid repeated database queries"""
    try:
        conn = _db.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT *
                    FROM product_nutrition
                    WHERE sku = %s
                """, (sku,))
                nutrition_info = cur.fetchone()
                return nutrition_info if nutrition_info else {}
        finally:
            _db.return_connection(conn)
    except Exception as e:
        logger.error(f"Error getting product nutrition for {sku}: {str(e)}")
        return {}

def debug_product_url(url: str) -> list:
    """Debug scraping process for a specific URL"""
    debug_logs = []
    try:
        scraper = RimiScraper(status_callback=lambda msg: debug_logs.append(msg))
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

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def filter_products_by_ingredient(products, ingredient):
    """Filter products containing a specific ingredient"""
    if not ingredient:
        logger.info("No ingredient filter applied")
        return products

    logger.info(f"Filtering products for ingredient: {ingredient}")
    filtered_products = []
    for product in products:
        if product.get('ingredients') and ingredient.lower() in product['ingredients'].lower():
            filtered_products.append(product)

    logger.info(f"Found {len(filtered_products)} products containing {ingredient}")
    return filtered_products


def handle_products_overview(products, db):
    """Handle the Products Overview tab functionality"""
    st.title("Products Overview")
    try:
        if products:
            # Filter products if ingredient is selected
            if st.session_state.selected_ingredient:
                logger.info(f"Filtering for ingredient: {st.session_state.selected_ingredient}")
                st.info(f"Showing products containing: {st.session_state.selected_ingredient}")

                # Clear filter button
                if st.button("Clear Filter"):
                    logger.info("Clearing ingredient filter")
                    st.session_state.selected_ingredient = None
                    st.rerun()

                # Filter products containing the selected ingredient
                filtered_products = filter_products_by_ingredient(products, st.session_state.selected_ingredient)

                if filtered_products:
                    logger.info(f"Displaying {len(filtered_products)} filtered products")
                    df = pd.DataFrame(filtered_products)
                    st.dataframe(df)
                else:
                    logger.warning("No products found with the selected ingredient")
                    st.warning("No products found containing this ingredient.")
            else:
                logger.info("Displaying all products")
                df = pd.DataFrame(products)
                st.dataframe(df)
        else:
            logger.warning("No products available in the database")
            st.info("No products available. Please refresh the data.")
    except Exception as e:
        logger.error(f"Error in Products Overview: {str(e)}")
        st.error(f"Error loading products: {str(e)}")

@st.cache_data(ttl=300)  # Cache data for 5 minutes
def get_cached_ingredient_analysis(_db: Database):
    """Cache ingredient analysis data to improve performance"""
    try:
        conn = _db.get_connection()
        try:
            with conn.cursor() as cur:
                logger.info("Querying cached ingredient analysis data...")
                cur.execute("""
                    SELECT ingredient, frequency 
                    FROM ingredient_analysis 
                    ORDER BY frequency DESC
                """)
                ingredients_data = cur.fetchall()
                logger.info(f"Found {len(ingredients_data) if ingredients_data else 0} ingredients in cache")
                return ingredients_data
        finally:
            _db.return_connection(conn)
    except Exception as e:
        logger.error(f"Error getting cached ingredient analysis: {str(e)}")
        return []

def handle_ingredient_analysis(db: Database):
    """Handle the Ingredient Analysis tab functionality"""
    st.title("Ingredient Analysis")
    st.markdown("### 📊 Ingredient Analysis")

    # Add refresh button with unique key
    if st.button("🔄 Refresh Analysis", key="refresh_ingredients_analysis"):
        with st.spinner("Refreshing ingredient analysis..."):
            if refresh_ingredient_analysis(db):
                st.success("Successfully refreshed ingredient analysis!")
                switch_to_products_tab()
            else:
                st.error("Failed to refresh ingredient analysis")
                return

    try:
        # Use loading spinner while fetching data
        with st.spinner("Loading ingredient analysis..."):
            ingredients_data = get_cached_ingredient_analysis(db)

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
                        if st.button(
                            f"**{ingredient}** ({frequency} products)",
                            key=f"ing_{idx}",
                            help="Click to view products containing this ingredient",
                            use_container_width=True
                        ):
                            switch_to_products_tab(ingredient)
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

def switch_to_products_tab(ingredient: Optional[str] = None):
    """Helper function to handle tab switching and ingredient selection"""
    if ingredient is not None:
        st.session_state.selected_ingredient = ingredient
    st.session_state.active_tab = 0
    st.rerun()

def main():
    # Initialize database connection
    db = ensure_database_connection()
    if not db:
        st.error("Database Connection Error")
        return

    # Initialize session state for tab management
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = 0
    if 'selected_ingredient' not in st.session_state:
        st.session_state.selected_ingredient = None

    # Tab configuration
    tab_titles = [
        "Products Overview",
        "Product Details",
        "Debug",
        "Specific Products Debug",
        "Scraping Logs",
        "Fix Country Codes",
        "Export Data",
        "Ingredient Analysis"
    ]

    logger.info(f"Current active tab index: {st.session_state.active_tab}")
    logger.info(f"Selected ingredient: {st.session_state.get('selected_ingredient')}")

    # Create tabs and handle tab switching
    tabs = st.tabs(tab_titles)
    current_tab = st.session_state.active_tab

    # Process tabs
    for i, tab in enumerate(tabs):
        with tab:
            if i == 0:  # Products Overview
                handle_products_overview(get_cached_products(db), db)
            elif i == 1:  # Product Details
                st.title("Product Details")
                product_name = st.text_input("Enter product name:", help="Enter part of the product name to search")
                if product_name:
                    try:
                        products = get_cached_product_by_name(db, product_name)
                        if products:
                            product_options = {f"{p['name']} (SKU: {p['sku']})": p for p in products}
                            selected_product_name = st.selectbox("Select a product:", list(product_options.keys()))
                            if selected_product_name:
                                product = product_options[selected_product_name]
                                st.write("### Product Information")
                                st.json(product)
                                if 'ingredients' in product:
                                    display_product_additives(product['sku'], product['ingredients'])
                                nutrition = get_cached_product_nutrition(db, product['sku'])
                                if nutrition:
                                    st.write("### Nutrition Information")
                                    st.json(nutrition)
                        else:
                            st.warning("No products found matching your search.")
                    except Exception as e:
                        st.error(f"Error loading product details: {str(e)}")
                        logger.error(f"Product details error: {str(e)}")
            elif i == 2: #Debug
                st.title("Debug")
                # Your debug code here
            elif i == 3: #Specific Products Debug
                st.title("Specific Products Debug")
                if SPECIFIC_PRODUCTS:
                    selected_product_url = st.selectbox("Select a product", SPECIFIC_PRODUCTS)
                    if selected_product_url:
                        debug_logs = debug_product_url(selected_product_url)
                        for log in debug_logs:
                            st.markdown(f"<div class='debug-log'>{log}</div>", unsafe_allow_html=True)
                else:
                    st.info("No specific products defined for debugging.")
            elif i == 4: #Scraping Logs
                st.title("Scraping Logs")
                # Your scraping log display code here
            elif i == 5: #Fix Country Codes
                st.title("Fix Country Codes")
                # Your country code fixing code here
            elif i == 6: #Export Data
                st.title("Export Data")
                # Your data export code here
            elif i == 7:  # Ingredient Analysis
                handle_ingredient_analysis(db)

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