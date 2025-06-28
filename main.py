import streamlit as st
from core_parser import RimiParser, DatabaseConnection
import time

st.set_page_config(
    page_title="Rimi Category Analyzer",
    page_icon="🛒",
    layout="wide"
)

def compare_products_detailed(category_code: str):
    """Compare website vs database products with exact matching"""
    from product_matcher import ProductMatcher
    
    st.subheader("🔍 Detailed Product Comparison")
    
    matcher = ProductMatcher(lambda msg: st.write(f"📊 {msg}"))
    
    with st.spinner("Performing detailed product comparison..."):
        result = matcher.compare_products(category_code)
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("New Products", len(result.new_products))
    with col2:
        st.metric("Missing Products", len(result.missing_products))
    with col3:
        st.metric("Changed Products", len(result.changed_products))
    with col4:
        st.metric("Matched Products", len(result.matched_products))
    
    # New products section
    if result.new_products:
        st.subheader("🆕 New Products (On Website, Not in Database)")
        
        with st.expander(f"Show all {len(result.new_products)} new products"):
            for i, product in enumerate(result.new_products, 1):
                st.write(f"**{i}. {product.sku}**: {product.name}")
                if product.website_data and product.website_data.price:
                    st.write(f"   Price: {product.website_data.price}")
                if product.website_data and product.website_data.url:
                    st.write(f"   URL: {product.website_data.url[:80]}...")
                st.divider()
    
    # Missing products section  
    if result.missing_products:
        st.subheader("❌ Missing Products (In Database, Not on Website)")
        
        with st.expander(f"Show all {len(result.missing_products)} missing products"):
            for i, product in enumerate(result.missing_products, 1):
                st.write(f"**{i}. {product.sku}**: {product.name}")
                if product.database_data and product.database_data.get('quantity_value'):
                    st.write(f"   Quantity: {product.database_data['quantity_value']}{product.database_data.get('quantity_unit', '')}")
                if product.database_data and product.database_data.get('rimi_url'):
                    st.write(f"   URL: {product.database_data['rimi_url'][:80]}...")
                st.divider()
    
    # Changed products section
    if result.changed_products:
        st.subheader("🔄 Changed Products")
        
        with st.expander(f"Show all {len(result.changed_products)} changed products"):
            for i, product in enumerate(result.changed_products, 1):
                st.write(f"**{i}. {product.sku}**: {product.name}")
                if product.changes:
                    for field, change in product.changes.items():
                        st.write(f"   {field.title()} changed:")
                        st.write(f"     Website: {change['website']}")
                        st.write(f"     Database: {change['database']}")
                st.divider()
    
    return result

def analyze_category(category_code: str):
    """Analyze a single category comparing website vs database"""
    
    # Initialize components
    parser = RimiParser()
    db = DatabaseConnection()
    
    # Get website data
    category_url = parser.build_category_url(category_code)
    st.info(f"Analyzing category: {category_url}")
    
    # Analyze pagination
    total_products_web, total_pages_web = parser.get_total_products_from_pagination(category_url)
    
    # Get sample products from first page
    page_url = f"{category_url}?pageSize=20&currentPage=1"
    sample_products_web = parser.extract_products_from_page(page_url, max_products=10)
    
    # Get database data
    db_products = db.get_products_for_category(category_code)
    
    # Display comparison
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🌐 Website Data")
        st.metric("Total Pages", total_pages_web)
        st.metric("Estimated Products", total_products_web)
        
        if sample_products_web:
            st.write("**Sample Products (First 10):**")
            for i, product in enumerate(sample_products_web):
                st.text(f"{i+1}. {product.sku}: {product.name[:40]}... - {product.price}")
    
    with col2:
        st.subheader("🗄️ Database Data")
        st.metric("Products in Database", len(db_products))
        
        if db_products:
            st.write("**Sample Database Products (First 10):**")
            for i, product in enumerate(db_products[:10]):
                quantity_info = ""
                if product.get('quantity_value') and product.get('quantity_unit'):
                    quantity_info = f" ({product['quantity_value']}{product['quantity_unit']})"
                st.text(f"{i+1}. {product['sku']}: {product['name'][:40]}...{quantity_info}")
    
    # Coverage analysis
    st.subheader("📊 Coverage Analysis")
    
    if total_products_web > 0 and db_products:
        coverage_percentage = (len(db_products) / total_products_web) * 100
        st.metric(
            "Database Coverage", 
            f"{coverage_percentage:.1f}%",
            f"{len(db_products)} of {total_products_web} products"
        )
        
        # Progress bar
        st.progress(coverage_percentage / 100)
        
        if coverage_percentage < 50:
            st.warning("Low database coverage - many products missing from database")
        elif coverage_percentage < 80:
            st.info("Moderate database coverage - some products missing")
        else:
            st.success("Good database coverage")
    else:
        st.warning("Unable to calculate coverage - insufficient data")

def main():
    st.title("Rimi Category Analyzer")
    st.markdown("**Read-only analysis** comparing website data with database data")
    
    # Category input
    category_code = st.text_input(
        "Enter Rimi Category Code", 
        value="SH-11",
        placeholder="e.g., SH-11, SH-13, SH-2",
        help="Enter a Rimi category code like SH-11 (dairy products)"
    )
    
    # Analysis type selection
    analysis_type = st.radio(
        "Analysis Type:",
        ["Basic Overview", "Detailed Product Comparison", "Database Update"],
        help="Basic: Quick stats comparison. Detailed: Product-by-product matching. Database Update: Permanent database changes"
    )
    
    if st.button("Run Analysis", type="primary"):
        if category_code.strip():
            try:
                if analysis_type == "Basic Overview":
                    with st.spinner(f"Analyzing category {category_code}..."):
                        analyze_category(category_code.strip().upper())
                        st.success(f"Basic analysis complete for {category_code}")
                
                elif analysis_type == "Detailed Product Comparison":
                    with st.spinner(f"Performing detailed comparison for {category_code}..."):
                        result = compare_products_detailed(category_code.strip().upper())
                        st.success(f"Detailed comparison complete for {category_code}")
                        
                        # Show download option for detailed results
                        if result.new_products or result.missing_products:
                            st.subheader("Export Results")
                            
                            # Prepare CSV data
                            csv_data = []
                            
                            # Add new products
                            for product in result.new_products:
                                csv_data.append({
                                    'Status': 'New',
                                    'SKU': product.sku,
                                    'Name': product.name,
                                    'Price': product.website_data.price if product.website_data and product.website_data.price else '',
                                    'URL': product.website_data.url if product.website_data and product.website_data.url else ''
                                })
                            
                            # Add missing products
                            for product in result.missing_products:
                                csv_data.append({
                                    'Status': 'Missing',
                                    'SKU': product.sku,
                                    'Name': product.name,
                                    'Price': product.database_data.get('price', '') if product.database_data else '',
                                    'URL': product.database_data.get('rimi_url', '') if product.database_data else ''
                                })
                            
                            if csv_data:
                                import pandas as pd
                                df = pd.DataFrame(csv_data)
                                csv = df.to_csv(index=False)
                                
                                st.download_button(
                                    label="Download Results as CSV",
                                    data=csv,
                                    file_name=f"{category_code}_product_comparison.csv",
                                    mime="text/csv"
                                )
                
                elif analysis_type == "Database Update":
                    st.warning("⚠️ Database Update performs permanent changes to PRODUCTS_DB_URL database")
                    
                    if st.checkbox("I understand this will modify the database", key="db_update_confirm"):
                        if st.button("Perform Database Update", type="secondary"):
                            with st.spinner(f"Updating database for {category_code}..."):
                                try:
                                    from update_coordinator import UpdateCoordinator
                                    
                                    def update_callback(msg):
                                        st.write(f"📊 {msg}")
                                    
                                    coordinator = UpdateCoordinator(update_callback)
                                    update_result = coordinator.perform_category_update(category_code.strip().upper())
                                    
                                    # Show summary
                                    st.success("Database update completed!")
                                    st.text(coordinator.get_update_summary(update_result))
                                    
                                    # Show products without nutrition
                                    if update_result['products_without_nutrition']:
                                        st.subheader("📋 Products Without Nutrition Facts")
                                        st.write(f"Found {len(update_result['products_without_nutrition'])} products that need nutrition data:")
                                        
                                        for product in update_result['products_without_nutrition']:
                                            st.write(f"• **{product['sku']}**: {product['name']}")
                                        
                                        # Export option
                                        csv_export = coordinator.export_products_without_nutrition(update_result)
                                        if csv_export:
                                            st.download_button(
                                                label="Download Products Without Nutrition (CSV)",
                                                data=csv_export,
                                                file_name=f"{category_code}_no_nutrition.csv",
                                                mime="text/csv"
                                            )
                                    
                                    coordinator.close()
                                    
                                except Exception as e:
                                    st.error(f"Database update failed: {str(e)}")
                                    st.write("Check the error message and try again.")
                
            except Exception as e:
                st.error(f"Analysis error: {str(e)}")
                st.write("Please check the category code and try again.")
        else:
            st.error("Please enter a category code")
    
    # Show available categories
    with st.expander("Available Categories"):
        try:
            db = DatabaseConnection()
            categories = db.get_categories()
            
            if categories:
                st.write(f"Found {len(categories)} categories in database:")
                
                # Group by main category
                main_categories = {}
                for cat in categories[:50]:  # Show first 50
                    main_code = cat['rimi_category_code'].split('-')[1] if '-' in cat['rimi_category_code'] else cat['rimi_category_code']
                    if main_code not in main_categories:
                        main_categories[main_code] = []
                    main_categories[main_code].append(cat)
                
                for main_code, cats in list(main_categories.items())[:10]:
                    st.write(f"**SH-{main_code}**: {len(cats)} subcategories")
                    for cat in cats[:3]:
                        st.text(f"  - {cat['rimi_category_code']}: {cat.get('name_lv', 'N/A')}")
                    if len(cats) > 3:
                        st.text(f"  ... and {len(cats)-3} more")
            else:
                st.warning("No categories found in database")
        except Exception as e:
            st.error(f"Database connection error: {str(e)}")

if __name__ == "__main__":
    main()