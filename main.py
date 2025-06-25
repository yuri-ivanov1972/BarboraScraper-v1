import streamlit as st
import pandas as pd
from category_analyzer import CategoryAnalyzer
import logging
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="Rimi Category Analyzer",
    page_icon="🛒",
    layout="wide"
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    st.title("Rimi Category Analyzer")
    st.markdown("Compare Rimi website data with database by category (read-only)")

    # Initialize analyzer
    try:
        analyzer = CategoryAnalyzer()
        st.success("Category analyzer initialized successfully")
    except Exception as e:
        st.error(f"Failed to initialize analyzer: {str(e)}")
        st.info("Make sure CATEGORIES_DB_URL and PRODUCTS_DB_URL environment variables are set")
        return

    st.divider()

    # Category input section
    st.subheader("Category Analysis")
    
    category_code = st.text_input(
        "Enter Rimi Category Code",
        placeholder="e.g., SH-11 (dairy products), SH-13 (sweets), SH-2 (fruits)",
        help="Enter the category code from Rimi URL. Examples: SH-11, SH-13, SH-2"
    )

    # Analysis button
    if st.button("Analyze Category", type="primary", disabled=not category_code):
        if not category_code.strip():
            st.error("Please enter a category code")
            return
            
        with st.spinner(f"Analyzing category {category_code}..."):
            # Status display
            status_placeholder = st.empty()
            logs_placeholder = st.empty()
            
            def status_callback(message):
                status_placeholder.text(f"Status: {message}")
                if 'analysis_logs' not in st.session_state:
                    st.session_state.analysis_logs = []
                st.session_state.analysis_logs.append(f"{datetime.now().strftime('%H:%M:%S')} - {message}")
                
                # Show recent logs
                recent_logs = st.session_state.analysis_logs[-5:]
                logs_placeholder.text_area("Recent Activity", "\n".join(recent_logs), height=100)

            try:
                analyzer.status_callback = status_callback
                result = analyzer.analyze_category(category_code, sample_pages=2)
                
                # Clear status displays
                status_placeholder.empty()
                logs_placeholder.empty()
                
                if result['status'] == 'error':
                    st.error("Analysis failed")
                    for error in result['errors']:
                        st.error(f"Error: {error}")
                    return
                
                # Display results
                st.success("Analysis completed successfully!")
                
                # Detailed comparison
                st.subheader("Analysis Results")
                
                comparison = result['comparison']
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Website Total", f"{result['website_total_products']:,}")
                with col2:
                    st.metric("Database Total", f"{comparison['total_in_database']:,}")
                with col3:
                    st.metric("Coverage", f"{comparison['coverage_percentage']}%")
                with col4:
                    st.metric("Sample Size", comparison['sampled_from_website'])
                
                # Tabs for detailed data
                tabs = st.tabs(["Website Sample", "Database Products", "Differences"])
                
                with tabs[0]:
                    st.subheader("Products Found on Website")
                    if result['website_sample_products']:
                        website_df = pd.DataFrame(result['website_sample_products'])
                        st.dataframe(website_df, use_container_width=True)
                        
                        # Download option
                        csv = website_df.to_csv(index=False)
                        st.download_button(
                            label="Download website products as CSV",
                            data=csv,
                            file_name=f"website_products_{category_code}_{datetime.now().strftime('%Y%m%d')}.csv",
                            mime="text/csv"
                        )
                    else:
                        st.info("No products found on website")
                
                with tabs[1]:
                    st.subheader("Products in Database")
                    if result['database_products']:
                        db_df = pd.DataFrame(result['database_products'])
                        st.dataframe(db_df, use_container_width=True)
                        
                        # Download option
                        csv = db_df.to_csv(index=False)
                        st.download_button(
                            label="Download database products as CSV",
                            data=csv,
                            file_name=f"database_products_{category_code}_{datetime.now().strftime('%Y%m%d')}.csv",
                            mime="text/csv"
                        )
                    else:
                        st.info("No products found in database for this category")
                
                with tabs[2]:
                    st.subheader("Product Differences")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**Only on Website (new products)**")
                        if comparison['only_on_website']:
                            for sku in comparison['only_on_website'][:10]:  # Show first 10
                                website_product = next((p for p in result['website_sample_products'] if p['sku'] == sku), None)
                                if website_product:
                                    st.text(f"• {sku}: {website_product['name'][:50]}...")
                            if len(comparison['only_on_website']) > 10:
                                st.caption(f"... and {len(comparison['only_on_website']) - 10} more")
                        else:
                            st.info("All sampled products exist in database")
                    
                    with col2:
                        st.markdown("**Only in Database (missing from website)**")
                        if comparison['only_in_database']:
                            for sku in comparison['only_in_database'][:10]:  # Show first 10
                                db_product = next((p for p in result['database_products'] if p['sku'] == sku), None)
                                if db_product:
                                    st.text(f"• {sku}: {db_product['name'][:50]}...")
                            if len(comparison['only_in_database']) > 10:
                                st.caption(f"... and {len(comparison['only_in_database']) - 10} more")
                        else:
                            st.info("All database products found on website sample")
                
                # Category information
                st.subheader("Category Information")
                st.text(f"Category Code: {result['category_code']}")
                st.text(f"Category URL: {result['category_url']}")
                
                # Save results to session state for reference
                st.session_state.last_analysis = result
                
            except Exception as e:
                st.error(f"Analysis failed: {str(e)}")
                status_placeholder.empty()
                logs_placeholder.empty()
    
    # Show recent activity logs if available
    if 'analysis_logs' in st.session_state and st.session_state.analysis_logs:
        with st.expander("View Recent Activity Logs"):
            for log in st.session_state.analysis_logs[-20:]:
                st.text(log)

if __name__ == "__main__":
    main()