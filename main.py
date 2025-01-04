import streamlit as st
import pandas as pd
from scraper import RimiScraper, ScraperError
from database import Database
import logging
import traceback
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor # Added for RealDictCursor

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
    "https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/salati/rujienas-salati-200g/p/2000511"
]

def main():
    st.title("🛒 Rimi Product Scraper")
    st.markdown("### A tool for monitoring Rimi supermarket products and prices")

    # Initialize session state for debug section and progress tracking
    if 'show_debug' not in st.session_state:
        st.session_state.show_debug = False
    if 'debug_logs' not in st.session_state:
        st.session_state.debug_logs = None
    if 'total_products' not in st.session_state:
        st.session_state.total_products = 0
    if 'processed_products' not in st.session_state:
        st.session_state.processed_products = 0
    if 'specific_products_logs' not in st.session_state:
        st.session_state.specific_products_logs = []

    # Initialize database
    try:
        db = Database()
        logger.info("Database connection established successfully")
    except Exception as e:
        st.error(f"Database Connection Error: {str(e)}")
        st.stop()

    # Add tabs for different sections
    tab1, tab2, tab3, tab4 = st.tabs(["Products Overview", "Product Details", "Debug", "Specific Products Debug"])

    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            # Add refresh button
            if st.button("🔄 Refresh All Data"):
                progress_bar = st.progress(0)
                progress_text = st.empty()

                def update_progress(msg: str):
                    if "Found" in msg and "potential product elements" in msg:
                        # Extract total products count
                        count = int(''.join(filter(str.isdigit, msg)))
                        st.session_state.total_products = count
                        st.session_state.processed_products = 0
                    elif "Successfully parsed product" in msg:
                        st.session_state.processed_products += 1
                        if st.session_state.total_products > 0:
                            progress = st.session_state.processed_products / st.session_state.total_products
                            progress_bar.progress(min(progress, 1.0))
                            progress_text.text(f"Processing products: {st.session_state.processed_products}/{st.session_state.total_products}")

                with st.spinner("Scraping product data..."):
                    try:
                        scraper = RimiScraper(status_callback=update_progress)
                        products_with_nutrition = scraper.scrape_products()

                        if products_with_nutrition:
                            try:
                                result = db.save_products_with_nutrition(products_with_nutrition)
                                st.success(f"""Successfully processed {len(products_with_nutrition)} products!
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

                # Clean up progress indicators
                progress_bar.empty()
                progress_text.empty()

        with col2:
            # Add button for specific products
            if st.button("🎯 Refresh Specific Products"):
                progress_text = st.empty()

                with st.spinner("Scraping specific products..."):
                    try:
                        scraper = RimiScraper(status_callback=lambda msg: progress_text.text(msg))
                        products_with_nutrition = scraper.scrape_specific_products(SPECIFIC_PRODUCTS)

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
            products = db.get_products()
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
                    # Get nutritional info for selected product
                    nutrition = db.get_product_nutrition(selected_product)

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
            specific_skus = ['2000297', '2000165', '2000291', '2000324', '2000330', '2000511']
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


if __name__ == "__main__":
    main()