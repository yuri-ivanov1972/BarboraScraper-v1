import streamlit as st
import pandas as pd
from scraper import RimiScraper, ScraperError
from database import Database
import logging
import traceback
from datetime import datetime
import psycopg2

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
    }
    </style>
    """, unsafe_allow_html=True)

def debug_product_url(url: str) -> list:
    """Debug scraping process for a specific URL"""
    debug_logs = []

    def debug_callback(msg: str):
        debug_logs.append(msg)

    try:
        scraper = RimiScraper(status_callback=debug_callback)
        nutrition_info = scraper.scrape_nutritional_info(url)
        debug_logs.append("\n=== Final Nutrition Info ===")
        debug_logs.append(f"Ingredients: {nutrition_info.ingredients[:100]}..." if nutrition_info.ingredients else "No ingredients found")
        debug_logs.append(f"Energy: {nutrition_info.energy_kj}kJ / {nutrition_info.energy_kcal}kcal")
        debug_logs.append(f"Fat: {nutrition_info.fat}g")
        debug_logs.append(f"Carbohydrates: {nutrition_info.carbohydrates}g")
        debug_logs.append(f"Protein: {nutrition_info.protein}g")
        debug_logs.append(f"Salt: {nutrition_info.salt}g")

        if nutrition_info.needs_review:
            debug_logs.append(f"\nNeeds Review: {nutrition_info.review_notes}")

    except Exception as e:
        debug_logs.append(f"Error during scraping: {str(e)}")
        debug_logs.append(traceback.format_exc())

    return debug_logs

def main():
    st.title("🛒 Rimi Product Scraper")
    st.markdown("### A tool for monitoring Rimi supermarket products and prices")

    # Initialize database
    try:
        db = Database()
        logger.info("Database connection established successfully")
    except Exception as e:
        st.error(f"Database Connection Error: {str(e)}")
        st.stop()

    # Add buttons in the same row
    col1, col2 = st.columns([1, 4])
    with col1:
        refresh_clicked = st.button("🔄 Refresh Data")
    with col2:
        debug_clicked = st.button("🔍 Debug Single Product", type="secondary", help="Debug scraping process for a specific URL")

    # Debug section
    if debug_clicked:
        st.markdown("### 🔍 Debug Single Product")
        debug_url = st.text_input(
            "Product URL to debug",
            value="https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/gatava-kulinarija/uzkodas-plates-kulinarija/lasa-filejas-skelites-mazs-ar-dillem-kg/p/222966"
        )

        if st.button("Start Debug"):
            with st.spinner("Debugging product page..."):
                debug_logs = debug_product_url(debug_url)

                st.markdown("### Debug Results")
                st.markdown('<div class="debug-section">', unsafe_allow_html=True)
                for log in debug_logs:
                    st.markdown(f'<div class="debug-log">{log}</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

    # Add status area for scraping progress
    status_area = st.empty()

    # Refresh data section
    if refresh_clicked:
        with st.spinner("Scraping product data..."):
            try:
                scraper = RimiScraper(status_callback=lambda msg: status_area.markdown(f"""
                    <div class="status-area">
                        <h4>Scraping Status</h4>
                        <p>{msg}</p>
                    </div>
                """, unsafe_allow_html=True))

                products_with_nutrition = scraper.scrape_products()

                if products_with_nutrition:
                    try:
                        result = db.save_products_with_nutrition(products_with_nutrition)
                        st.success(f"Successfully processed {len(products_with_nutrition)} products!")
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

if __name__ == "__main__":
    main()