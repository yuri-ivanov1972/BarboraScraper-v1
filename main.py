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

def load_categories():
    """Load categories from database for dropdown"""
    try:
        from database_integration import ExternalDatabaseManager
        db_manager = ExternalDatabaseManager()
        categories = db_manager.get_all_categories()
        
        # Format categories for dropdown: "Code - Name (Level X)"
        formatted_categories = []
        for cat in categories:
            name = cat.name_lv or cat.name_en or "No Name"
            formatted = f"{cat.rimi_category_code} - {name} (Level {cat.level})"
            formatted_categories.append((cat.rimi_category_code, formatted))
        
        return sorted(formatted_categories, key=lambda x: x[0])
    except Exception as e:
        st.error(f"Error loading categories: {str(e)}")
        return []

def product_manager_tab():
    """Individual Product Management Tab"""
    st.header("🎯 Product Manager")
    st.markdown("Process individual products by SKU - create new or update existing products")
    
    # Load categories for dropdown
    categories = load_categories()
    
    if not categories:
        st.error("Unable to load categories from database")
        return
    
    # Input form
    col1, col2 = st.columns([1, 2])
    
    with col1:
        sku = st.text_input(
            "Product SKU",
            placeholder="e.g., 999409, 4007406",
            help="Enter the Rimi product SKU number"
        )
    
    with col2:
        # Category selection dropdown
        category_options = [cat[1] for cat in categories]
        category_codes = [cat[0] for cat in categories]
        
        selected_index = st.selectbox(
            "Product Category",
            range(len(category_options)),
            format_func=lambda x: category_options[x],
            help="Select the appropriate product category"
        )
        
        selected_category = category_codes[selected_index] if selected_index is not None else ""
    
    # Process button
    if st.button("Process Product", type="primary", disabled=not (sku and selected_category)):
        if not sku.strip():
            st.error("Please enter a product SKU")
            return
        if not selected_category:
            st.error("Please select a product category")
            return
        
        # Processing workflow
        with st.spinner("Processing product..."):
            try:
                from update_coordinator import UpdateCoordinator
                
                # Status display with real-time logging
                status_container = st.container()
                progress_bar = st.progress(0)
                log_container = st.empty()
                
                processing_logs = []
                
                def status_callback(msg):
                    processing_logs.append(msg)
                    with status_container:
                        st.write(f"🔄 {msg}")
                    # Update log display
                    log_text = "\n".join([f"[{i+1:02d}] {log}" for i, log in enumerate(processing_logs)])
                    log_container.text_area("Processing Log", log_text, height=150)
                
                coordinator = UpdateCoordinator(status_callback)
                
                # Update progress
                progress_bar.progress(25)
                
                # Process the product
                result = coordinator.process_single_product(sku.strip(), selected_category)
                
                progress_bar.progress(100)
                
                # Display results
                if result['success']:
                    st.success("Product processed successfully!")
                    
                    # Show detailed debug information
                    with st.expander("Debug: Raw Result Data", expanded=False):
                        st.json(result)
                    
                    # Operation type
                    if result['operation'] == 'create':
                        st.info("New product created in database")
                    else:
                        st.info("Existing product updated")
                    
                    # Product information
                    st.subheader("Product Information")
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"**SKU**: {sku}")
                        st.write(f"**Name**: {result['product_data'].get('name', 'N/A')}")
                        st.write(f"**Price**: €{result['product_data'].get('price', '0.00')}")
                        st.write(f"**Category**: {selected_category}")
                        
                        # Show quantity if available
                        quantity_value = result['product_data'].get('quantity_value')
                        quantity_unit = result['product_data'].get('quantity_unit')
                        
                        if quantity_value and quantity_unit:
                            st.write(f"**Quantity**: {quantity_value} {quantity_unit}")
                        elif quantity_unit:
                            st.write(f"**Quantity**: Variable weight ({quantity_unit})")
                        else:
                            st.write("**Quantity**: Not specified")
                    
                    with col2:
                        # Product image
                        image_url = result['product_data'].get('image_url')
                        if image_url:
                            st.success("Product image found")
                            try:
                                st.image(image_url, width=200, caption="Product Image")
                            except Exception as img_error:
                                st.error(f"Error displaying image: {str(img_error)}")
                                st.write(f"**Image URL**: {image_url}")
                        else:
                            st.warning("No product image found")
                    
                    # Nutrition data - fix field mapping
                    nutrition = result['product_data'].get('nutrition', {})
                    st.subheader("Nutrition Information")
                    
                    if nutrition and nutrition.get('has_nutrition'):
                        st.success("Nutrition data found and processed")
                        
                        # Create nutrition display with correct field names
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            energy_kcal = nutrition.get('energy_kcal')
                            energy_kj = nutrition.get('energy_kj')
                            if energy_kcal:
                                st.metric("Energy", f"{energy_kcal} kcal")
                            elif energy_kj:
                                st.metric("Energy", f"{energy_kj} kJ")
                            else:
                                st.metric("Energy", "N/A")
                            
                            protein = nutrition.get('protein')
                            st.metric("Protein", f"{protein}g" if protein is not None else "N/A")
                        
                        with col2:
                            fat = nutrition.get('fat_total')  # Fix field name mapping
                            st.metric("Fat", f"{fat}g" if fat is not None else "N/A")
                            
                            saturated_fat = nutrition.get('fat_saturated')  # Fix field name mapping
                            st.metric("Saturated Fat", f"{saturated_fat}g" if saturated_fat is not None else "N/A")
                        
                        with col3:
                            carbs = nutrition.get('carbs_total')  # Fix field name mapping
                            st.metric("Carbohydrates", f"{carbs}g" if carbs is not None else "N/A")
                            
                            sugar = nutrition.get('carbs_sugars')  # Fix field name mapping
                            st.metric("Sugar", f"{sugar}g" if sugar is not None else "N/A")
                        
                        # Additional nutrition info
                        salt = nutrition.get('salt')
                        if salt is not None:
                            st.metric("Salt", f"{salt}g")
                        
                        fiber = nutrition.get('fiber')
                        if fiber is not None:
                            st.metric("Fiber", f"{fiber}g")
                        
                        # Nutri-score
                        nutri_score = nutrition.get('nutri_score')
                        if nutri_score:
                            st.info(f"**Nutri-Score**: {nutri_score}")
                        
                        # Ingredients
                        ingredients = nutrition.get('ingredients')
                        if ingredients:
                            st.subheader("Ingredients")
                            st.text(ingredients)
                            
                            # Show ingredient mappings
                            try:
                                import os, psycopg2
                                db_url = os.getenv('PRODUCTS_DB_URL')
                                conn = psycopg2.connect(db_url)
                                cursor = conn.cursor()
                                
                                cursor.execute('''
                                    SELECT ipm.ingredient_id, ia.ingredient, ia.frequency
                                    FROM ingredient_product_mapping ipm
                                    JOIN ingredient_analysis ia ON ipm.ingredient_id = ia.id
                                    WHERE ipm.product_sku = %s
                                    ORDER BY ia.frequency DESC
                                ''', (sku,))
                                
                                mappings = cursor.fetchall()
                                if mappings:
                                    st.write("**Ingredient Analysis:**")
                                    for mapping in mappings:
                                        ingredient_id, ingredient_name, frequency = mapping
                                        st.write(f"• {ingredient_name} (ID: {ingredient_id}, appears in {frequency} products)")
                                else:
                                    st.write("*No ingredient mappings found*")
                                
                                cursor.close()
                                conn.close()
                            except Exception as e:
                                st.write(f"*Error loading ingredient mappings: {str(e)}*")
                    else:
                        st.warning("No nutrition data found (may be fruits/vegetables without nutrition labels)")
                        
                        # Show what nutrition data was actually found
                        if nutrition:
                            st.write("Available nutrition fields:")
                            for key, value in nutrition.items():
                                st.write(f"- {key}: {value}")
                    
                    # Changes made
                    if result['changes']:
                        st.subheader("Changes Made")
                        changes = result['changes']
                        
                        for change, status in changes.items():
                            if status:
                                st.write(f"✅ {change.replace('_', ' ').title()}")
                    
                    # Database verification
                    st.subheader("Database Verification")
                    try:
                        from database_updater import DatabaseUpdater
                        db_updater = DatabaseUpdater()
                        
                        # Verify product exists in database
                        db_product = db_updater.get_product_by_sku(sku)
                        if db_product:
                            st.success(f"✅ Product verified in database (ID: {db_product['product_id']})")
                            
                            # Check for nutrition data - use correct table from schema export
                            nutrition_query = """
                            SELECT energy_kcal, protein, fat_total, carbs_total, carbs_sugars, salt, nutri_score_grade
                            FROM nutritionfacts 
                            WHERE product_id = %s
                            """
                            nutrition_data = db_updater._execute_query(nutrition_query, (db_product['product_id'],), fetch=True)
                            
                            if nutrition_data:
                                st.info(f"✅ Nutrition data verified: {len(nutrition_data)} records")
                                latest_nutrition = nutrition_data[0]
                                st.write(f"Energy: {latest_nutrition.get('energy_kcal')} kcal, Protein: {latest_nutrition.get('protein')}g")
                                st.write(f"Nutri-Score: {latest_nutrition.get('nutri_score_grade', 'N/A')}")
                            else:
                                st.warning("No nutrition data found in database")
                            
                            # Check for photos - use productphotos table from schema export
                            photo_query = """
                            SELECT photo_url, is_primary 
                            FROM productphotos 
                            WHERE product_id = %s
                            """
                            photo_data = db_updater._execute_query(photo_query, (db_product['product_id'],), fetch=True)
                            
                            if photo_data:
                                st.info(f"✅ Photos verified: {len(photo_data)} images")
                                for photo in photo_data:
                                    if photo.get('is_primary'):
                                        st.write(f"Primary photo: {photo['photo_url'][:60]}...")
                            else:
                                st.warning("No photos found in database")
                        else:
                            st.error("❌ Product not found in database after processing")
                        
                        db_updater.close()
                    except Exception as db_error:
                        st.error(f"Database verification failed: {str(db_error)}")
                
                else:
                    st.error("Product processing failed")
                    
                    # Show errors
                    if result['errors']:
                        st.subheader("Errors")
                        for error in result['errors']:
                            st.write(f"❌ {error}")
                
                coordinator.close()
                
            except Exception as e:
                st.error(f"Error processing product: {str(e)}")
    
    # Help section
    with st.expander("ℹ️ How to use Product Manager"):
        st.markdown("""
        **Product Manager** allows you to process individual products by SKU:
        
        1. **Enter SKU**: Product SKU number from Rimi website
        2. **Select Category**: Choose the appropriate product category
        3. **Process**: Click to start processing
        
        **What happens**:
        - Checks if product exists on Rimi website
        - Checks if product exists in database
        - Extracts product information (name, price, nutrition, photo)
        - Creates new product OR updates existing product
        - Stores all data in PRODUCTS_DB_URL database
        
        **Data extracted**:
        - Basic info (name, price, quantity)
        - Nutrition facts and ingredients
        - Main product photo
        - Nutri-score calculation
        """)

def main():
    st.title("🛒 Rimi Category Analyzer")
    st.markdown("Analyze and compare Rimi product categories with database data")
    
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Category Analysis", "Product Manager", "Batch Processing", "Database Info"])
    
    with tab1:
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
    
        # Separate handling for Database Update to avoid nested button issues
        if analysis_type == "Database Update":
            st.warning("⚠️ Database Update performs permanent changes to PRODUCTS_DB_URL database")
            
            col1, col2 = st.columns([1, 3])
            with col1:
                db_confirm = st.checkbox("I understand this will modify the database", key="db_update_confirm")
            with col2:
                if db_confirm:
                    if st.button("Perform Database Update", type="secondary", key="db_update_btn"):
                        if category_code.strip():
                            with st.spinner(f"Updating database for {category_code}..."):
                                try:
                                    from update_coordinator import UpdateCoordinator
                                    
                                    status_container = st.container()
                                    def update_callback(msg):
                                        with status_container:
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
                        else:
                            st.error("Please enter a category code")
        
        # Handle other analysis types with the Run Analysis button
        elif st.button("Run Analysis", type="primary"):
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
                                        file_name=f"{category_code}_comparison.csv",
                                        mime="text/csv"
                                    )
                    
                except Exception as e:
                    st.error(f"Analysis failed: {str(e)}")
            else:
                st.error("Please enter a category code")
    
    with tab2:
        # Product Manager Tab
        product_manager_tab()
    
    with tab3:
        # Batch Processing Tab
        st.header("📦 Batch Processing")
        st.markdown("Process multiple products with robust connection management")
        
        # Input methods
        input_method = st.radio(
            "Input Method:",
            ["Manual SKU List", "Text Area Input", "Test Batch"],
            help="Choose how to provide product SKUs for batch processing"
        )
        
        skus_to_process = []
        
        if input_method == "Manual SKU List":
            st.subheader("Enter SKUs")
            col1, col2 = st.columns(2)
            
            with col1:
                sku1 = st.text_input("SKU 1", placeholder="147762")
                sku2 = st.text_input("SKU 2", placeholder="961367")
                sku3 = st.text_input("SKU 3", placeholder="999409")
            
            with col2:
                sku4 = st.text_input("SKU 4", placeholder="Optional")
                sku5 = st.text_input("SKU 5", placeholder="Optional")
                sku6 = st.text_input("SKU 6", placeholder="Optional")
            
            skus_to_process = [sku for sku in [sku1, sku2, sku3, sku4, sku5, sku6] if sku.strip()]
        
        elif input_method == "Text Area Input":
            sku_text = st.text_area(
                "Enter SKUs (one per line or comma-separated):",
                placeholder="147762\n961367\n999409",
                height=100
            )
            if sku_text:
                # Handle both newline and comma separated
                sku_text = sku_text.replace(',', '\n')
                skus_to_process = [sku.strip() for sku in sku_text.split('\n') if sku.strip()]
        
        else:  # Test Batch
            st.info("Test batch with known products")
            skus_to_process = ["147762", "961367", "999409"]
            st.write("Test SKUs:", skus_to_process)
        
        # Category selection
        category_code = st.selectbox(
            "Category Code:",
            ["SH-1-1-1", "SH-2-1-1", "SH-11", "SH-12", "SH-13"],
            help="Category to assign to all products in batch"
        )
        
        # Batch processing options
        col1, col2 = st.columns(2)
        with col1:
            max_workers = st.slider("Concurrent Workers", 1, 5, 2, help="Number of products to process simultaneously")
        with col2:
            show_details = st.checkbox("Show Detailed Progress", value=True)
        
        if skus_to_process:
            st.write(f"Ready to process {len(skus_to_process)} products:")
            st.code(", ".join(skus_to_process))
            
            if st.button("🚀 Start Batch Processing", type="primary"):
                try:
                    from batch_processor import BatchProcessor
                    
                    # Progress tracking
                    progress_container = st.container()
                    status_container = st.container()
                    
                    with progress_container:
                        progress_bar = st.progress(0)
                        progress_text = st.empty()
                    
                    with status_container:
                        status_text = st.empty()
                    
                    messages = []
                    
                    def batch_status_callback(msg):
                        messages.append(msg)
                        if show_details:
                            status_text.text(f"Latest: {msg}")
                        
                        # Update progress
                        if "Processing product" in msg:
                            current = len([m for m in messages if "Processing product" in m])
                            progress = min(current / len(skus_to_process), 1.0)
                            progress_bar.progress(progress)
                            progress_text.text(f"Processing {current}/{len(skus_to_process)} products...")
                    
                    processor = BatchProcessor(batch_status_callback, max_workers=max_workers)
                    
                    start_time = time.time()
                    results = processor.process_sku_list(skus_to_process, category_code)
                    processor.close()
                    
                    # Final progress
                    progress_bar.progress(1.0)
                    progress_text.text(f"Completed in {results['processing_time']:.2f}s")
                    
                    # Results summary
                    st.success("Batch processing completed!")
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Total Products", results['total_products'])
                    with col2:
                        st.metric("Successful", results['successful'])
                    with col3:
                        st.metric("Failed", results['failed'])
                    with col4:
                        st.metric("Processing Time", f"{results['processing_time']:.1f}s")
                    
                    # Detailed results
                    if results['products_processed']:
                        st.subheader("Processing Details")
                        for product in results['products_processed']:
                            if product['status'] == 'success':
                                st.success(f"✓ {product['sku']}: Successfully processed")
                            else:
                                st.error(f"✗ {product['sku']}: {product['error']}")
                    
                    # Connection reliability info
                    st.info("✅ **Robust Connection Management Active**: Automatic reconnection, retry logic, and connection pooling ensure reliable batch processing even with network issues.")
                    
                except Exception as e:
                    st.error(f"Batch processing error: {str(e)}")
        else:
            st.warning("Please enter at least one SKU to process")
        
        # Help section
        with st.expander("ℹ️ About Batch Processing"):
            st.markdown("""
            **Batch Processing** allows you to process multiple products efficiently:
            
            **Features:**
            - **Robust Connection Management**: Automatic reconnection and retry logic
            - **Concurrent Processing**: Process multiple products simultaneously
            - **Progress Tracking**: Real-time progress updates
            - **Error Handling**: Individual product failures don't stop the batch
            - **Connection Pooling**: Optimized database connections
            
            **Connection Reliability Improvements:**
            - Automatic reconnection when connections are lost
            - Retry logic with exponential backoff
            - Connection health checks before queries
            - Thread-safe connection management
            - Graceful error recovery
            
            **Use Cases:**
            - Process multiple new products at once
            - Update existing product information
            - Bulk nutrition data extraction
            - Category-wide product updates
            """)
    
    with tab4:
        # Database Info Tab
        st.header("📊 Database Information")
        st.markdown("View information about connected databases")
        
        try:
            from core_parser import DatabaseConnection
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