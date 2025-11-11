"""
Rimi Product Scraper - Redesigned UI
Two-section interface: Category Processing + Product View
"""

import streamlit as st
from product_view_db import ProductViewDatabase
import time

st.set_page_config(
    page_title="Rimi Product Scraper",
    page_icon="🛒",
    layout="wide"
)

# Session state initialization
if 'view_mode' not in st.session_state:
    st.session_state.view_mode = 'category_processing'
if 'selected_product_id' not in st.session_state:
    st.session_state.selected_product_id = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1
if 'selected_category_id' not in st.session_state:
    st.session_state.selected_category_id = None
if 'expanded_categories' not in st.session_state:
    st.session_state.expanded_categories = set()


def render_nutri_score_badge(grade: str) -> str:
    """Render Nutri-Score badge HTML"""
    if not grade:
        return ""
    
    colors = {
        'A': '#038141',
        'B': '#85BB2F',
        'C': '#FECB02',
        'D': '#EE8100',
        'E': '#E63E11'
    }
    
    color = colors.get(grade, '#999')
    return f'<div style="background-color: {color}; color: white; font-weight: bold; padding: 4px 8px; border-radius: 4px; display: inline-block; font-size: 14px;">{grade}</div>'


def render_product_card(product: dict) -> None:
    """Render a single product card in grid"""
    
    # Product image
    image_url = product.get('photo_url')
    if image_url:
        st.image(image_url, use_container_width=True)
    else:
        st.markdown("<div style='background:#f0f0f0; height:150px; display:flex; align-items:center; justify-content:center;'>No Image</div>", unsafe_allow_html=True)
    
    # Nutri-Score badge
    nutri_grade = product.get('nutri_score_grade')
    if nutri_grade:
        st.markdown(render_nutri_score_badge(nutri_grade), unsafe_allow_html=True)
    
    # Product name (clickable)
    product_name = product.get('name', 'Unknown Product')
    if st.button(f"**{product_name[:50]}**", key=f"prod_{product['product_id']}", use_container_width=True):
        st.session_state.selected_product_id = product['product_id']
        st.rerun()
    
    # Quantity
    qty = product.get('quantity_value')
    unit = product.get('quantity_unit', '')
    if qty:
        st.caption(f"{qty}{unit}")
    
    # Nutrition values
    if product.get('carbs_sugars') is not None:
        st.caption(f"🍬 Cukurs: {product['carbs_sugars']}g")
    if product.get('fat_total') is not None:
        st.caption(f"🧈 Tauki: {product['fat_total']}g")
    if product.get('protein') is not None:
        st.caption(f"💪 Olbaltumvielas: {product['protein']}g")
    if product.get('salt') is not None:
        st.caption(f"🧂 Sāls: {product['salt']}g")


def render_category_tree_node(category: dict, db: ProductViewDatabase, level: int = 0) -> None:
    """Recursively render category tree node with expand/collapse"""
    
    indent = "　" * level
    category_id = category['category_id']
    has_children = len(category.get('children', [])) > 0
    is_expanded = category_id in st.session_state.expanded_categories
    
    # Category display
    col1, col2 = st.columns([4, 1])
    
    with col1:
        # Expand/collapse icon
        if has_children:
            icon = "▼" if is_expanded else "▶"
            if st.button(f"{indent}{icon} {category['name_lv']}", key=f"cat_{category_id}", use_container_width=True):
                if is_expanded:
                    st.session_state.expanded_categories.discard(category_id)
                else:
                    st.session_state.expanded_categories.add(category_id)
                st.rerun()
        else:
            if st.button(f"{indent}• {category['name_lv']}", key=f"cat_{category_id}", use_container_width=True):
                st.session_state.selected_category_id = category_id
                st.session_state.current_page = 1
                st.rerun()
    
    with col2:
        # Product count badge
        product_count = category.get('product_count', 0)
        if product_count > 0:
            st.caption(f"({product_count})")
    
    # Render children if expanded
    if is_expanded and has_children:
        for child in category['children']:
            render_category_tree_node(child, db, level + 1)


def section_category_processing():
    """Section 1: Category Processing"""
    st.header("📦 Category Processing")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        category_code = st.text_input(
            "Category Code",
            placeholder="e.g., SH-11-6-19, SH-7",
            help="Enter full category code (e.g., SH-11-6-19)"
        )
    
    with col2:
        st.write("")
        st.write("")
        force_update = st.checkbox("Force Update", help="Overwrite existing data")
    
    # Check for incomplete jobs
    incomplete_job = None
    if category_code:
        from progress_manager import ProgressManager
        progress_mgr = ProgressManager()
        incomplete_job = progress_mgr.find_incomplete_job(category_code)
        
        if incomplete_job:
            st.info(f"📌 Found incomplete processing job for this category")
            col_resume1, col_resume2, col_resume3 = st.columns(3)
            with col_resume1:
                st.metric("Total Products", incomplete_job['total_products'])
            with col_resume2:
                st.metric("Completed", incomplete_job['processed_count'])
            with col_resume3:
                remaining = incomplete_job['total_products'] - incomplete_job['processed_count']
                st.metric("Remaining", remaining)
    
    # Job queueing controls
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    
    with col_btn1:
        priority = st.number_input("Priority", min_value=1, max_value=10, value=5, help="Higher = more urgent")
    
    with col_btn2:
        st.write("")
        st.write("")
        queue_job = st.button("📥 Queue Job", type="primary", disabled=not category_code)
    
    with col_btn3:
        st.write("")
        st.write("")
        if incomplete_job:
            st.info(f"Job #{incomplete_job['job_id']} in queue")
    
    if queue_job:
        from core_parser import RimiParser
        import psycopg2
        
        with st.spinner("Collecting products and creating job..."):
            try:
                # Collect SKUs from category
                parser = RimiParser(lambda msg: st.text(msg))
                all_skus = parser.collect_category_skus(category_code)
                
                if not all_skus:
                    st.error(f"No products found in category {category_code}")
                else:
                    # Create job in database
                    conn = psycopg2.connect(os.environ['DATABASE_URL'])
                    cur = conn.cursor()
                    
                    try:
                        # Create job
                        cur.execute("""
                            INSERT INTO category_processing_jobs 
                            (category_code, category_id, total_products, processed_count, status, priority, requested_by)
                            VALUES (%s, NULL, %s, 0, 'queued', %s, 'streamlit_ui')
                            RETURNING id
                        """, (category_code, len(all_skus), priority))
                        
                        job_id = cur.fetchone()[0]
                        
                        # Log all SKUs as pending
                        for sku in all_skus:
                            cur.execute("""
                                INSERT INTO product_processing_log (job_id, sku, status)
                                VALUES (%s, %s, 'pending')
                            """, (job_id, sku))
                        
                        # Log event
                        cur.execute("""
                            INSERT INTO job_events (job_id, event_type, message)
                            VALUES (%s, 'job_created', %s)
                        """, (job_id, f"Job created via Streamlit UI for {category_code} with {len(all_skus)} products (priority: {priority})"))
                        
                        conn.commit()
                        
                        st.success(f"✅ Job #{job_id} created successfully!")
                        st.info(f"📦 Queued {len(all_skus)} products from category {category_code}")
                        st.info(f"🔧 Run the worker to process: `python worker.py --resume-all`")
                        
                        with st.expander("View job details"):
                            st.json({
                                "job_id": job_id,
                                "category_code": category_code,
                                "total_products": len(all_skus),
                                "priority": priority,
                                "status": "queued"
                            })
                        
                    except psycopg2.IntegrityError as e:
                        if 'idx_unique_active_category' in str(e):
                            st.warning(f"⚠️ Job already exists for category {category_code}")
                        else:
                            raise
                    finally:
                        conn.close()
                        
            except Exception as e:
                st.error(f"❌ Error creating job: {str(e)}")
                import traceback
                with st.expander("Error details"):
                    st.code(traceback.format_exc())
    
    # Help section
    with st.expander("ℹ️ Help"):
        st.markdown("""
        **Category Processing** allows you to scrape and update product data:
        
        - Enter a full category code (e.g., SH-11-6-19)
        - Toggle Force Update to overwrite existing data
        - Monitor progress with real-time statistics
        - Processing is automatic with category extraction from product pages
        """)


def section_product_view():
    """Section 2: Product View with hierarchical categories and grid"""
    st.header("🛍️ Product Browser")
    
    # Check if viewing product details
    if st.session_state.selected_product_id:
        render_product_detail_view()
        return
    
    db = ProductViewDatabase()
    
    # Build category tree with product counts
    category_tree = db.build_category_tree()
    product_counts = db.get_category_product_counts()
    
    # Add product counts to tree
    def add_counts(categories):
        for cat in categories:
            cat['product_count'] = product_counts.get(cat['category_id'], 0)
            if cat['children']:
                add_counts(cat['children'])
    
    add_counts(category_tree)
    
    # Layout: Sidebar (categories) + Main (products)
    col_sidebar, col_main = st.columns([1, 3])
    
    with col_sidebar:
        st.subheader("📂 Kategorijas")
        
        # "All Products" button
        if st.button("📋 Visi produkti", use_container_width=True):
            st.session_state.selected_category_id = None
            st.session_state.current_page = 1
            st.rerun()
        
        st.divider()
        
        # Render category tree
        for root_category in category_tree:
            render_category_tree_node(root_category, db, level=0)
    
    with col_main:
        # Get products for selected category
        products, total = db.get_products_by_category(
            category_id=st.session_state.selected_category_id,
            page=st.session_state.current_page,
            page_size=20,
            include_subcategories=True
        )
        
        # Display category name
        if st.session_state.selected_category_id:
            category_query = """
            SELECT name_lv, rimi_category_code 
            FROM normalized_categories 
            WHERE category_id = %s
            """
            db._ensure_connection()
            with db.connection.cursor() as cursor:
                cursor.execute(category_query, (st.session_state.selected_category_id,))
                cat_info = cursor.fetchone()
                if cat_info:
                    st.subheader(f"{cat_info['name_lv']} ({cat_info['rimi_category_code']})")
        else:
            st.subheader("Visi produkti")
        
        # Product count
        st.caption(f"Kopā: {total} produkti")
        
        # Pagination controls (top)
        total_pages = (total + 19) // 20
        if total_pages > 1:
            col1, col2, col3 = st.columns([1, 2, 1])
            with col1:
                if st.button("◀ Previous", disabled=st.session_state.current_page == 1):
                    st.session_state.current_page -= 1
                    st.rerun()
            with col2:
                st.write(f"Lapa {st.session_state.current_page} no {total_pages}")
            with col3:
                if st.button("Next ▶", disabled=st.session_state.current_page >= total_pages):
                    st.session_state.current_page += 1
                    st.rerun()
        
        st.divider()
        
        # Product grid (4 columns x 5 rows)
        if products:
            # Render in rows of 4
            for row in range(0, len(products), 4):
                cols = st.columns(4)
                for col_idx, col in enumerate(cols):
                    product_idx = row + col_idx
                    if product_idx < len(products):
                        with col:
                            render_product_card(products[product_idx])
        else:
            st.info("Nav produktu šajā kategorijā")
        
        # Pagination controls (bottom)
        if total_pages > 1:
            st.divider()
            col1, col2, col3 = st.columns([1, 2, 1])
            with col1:
                if st.button("◀ Prev", disabled=st.session_state.current_page == 1, key="prev_bottom"):
                    st.session_state.current_page -= 1
                    st.rerun()
            with col2:
                st.write(f"Lapa {st.session_state.current_page} no {total_pages}")
            with col3:
                if st.button("Next ▶", disabled=st.session_state.current_page >= total_pages, key="next_bottom"):
                    st.session_state.current_page += 1
                    st.rerun()
    
    db.close()


def render_product_detail_view():
    """Render detailed product view (similar to reference app)"""
    
    db = ProductViewDatabase()
    product = db.get_product_details(st.session_state.selected_product_id)
    
    if not product:
        st.error("Product not found")
        if st.button("← Atpakaļ"):
            st.session_state.selected_product_id = None
            st.rerun()
        db.close()
        return
    
    # Back button
    if st.button("← Atpakaļ uz produktu sarakstu"):
        st.session_state.selected_product_id = None
        st.rerun()
    
    st.divider()
    
    # Product header
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.title(product['name'])
        st.caption(f"SKU: {product['sku']}")
        if product.get('quantity_value'):
            st.caption(f"Daudzums: {product['quantity_value']}{product.get('quantity_unit', '')}")
    
    with col2:
        # Nutri-Score
        if product.get('nutri_score_grade'):
            st.markdown(render_nutri_score_badge(product['nutri_score_grade']), unsafe_allow_html=True)
            if product.get('nutri_score_points') is not None:
                st.caption(f"Punkti: {product['nutri_score_points']}")
        
        # Price
        if product.get('price'):
            st.metric("Cena", f"€{product['price']:.2f}")
    
    st.divider()
    
    # Product images
    if product.get('photos'):
        st.subheader("📸 Attēli")
        cols = st.columns(min(len(product['photos']), 3))
        for idx, photo_url in enumerate(product['photos'][:3]):
            with cols[idx]:
                st.image(photo_url, use_container_width=True)
    
    # Nutrition information
    st.subheader("📊 Uzturvielu informācija (uz 100g/ml)")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if product.get('energy_kj'):
            st.metric("Enerģija", f"{product['energy_kj']} kJ")
        if product.get('energy_kcal'):
            st.caption(f"({product['energy_kcal']} kcal)")
    
    with col2:
        if product.get('fat_total') is not None:
            st.metric("Tauki", f"{product['fat_total']}g")
        if product.get('fat_saturated') is not None:
            st.caption(f"t.sk. piesātinātās: {product['fat_saturated']}g")
    
    with col3:
        if product.get('carbs_total') is not None:
            st.metric("Ogļhidrāti", f"{product['carbs_total']}g")
        if product.get('carbs_sugars') is not None:
            st.caption(f"t.sk. cukuri: {product['carbs_sugars']}g")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if product.get('protein') is not None:
            st.metric("Olbaltumvielas", f"{product['protein']}g")
    
    with col2:
        if product.get('salt') is not None:
            st.metric("Sāls", f"{product['salt']}g")
    
    with col3:
        if product.get('fiber') is not None:
            st.metric("Šķiedrvielas", f"{product['fiber']}g")
    
    # Ingredients
    if product.get('ingredients_text'):
        st.subheader("📝 Sastāvdaļas")
        st.write(product['ingredients_text'])
    
    # Country of Origin
    if product.get('country_of_origin') and product.get('country_of_origin') != 'Unknown':
        st.subheader("🌍 Izcelsmes valsts")
        st.write(product['country_of_origin'])
    
    # Category
    st.subheader("📂 Kategorija")
    st.write(f"{product.get('category_name', 'N/A')} ({product.get('rimi_category_code', 'N/A')})")
    
    # Link to Rimi
    if product.get('rimi_url'):
        st.subheader("🔗 Saites")
        st.markdown(f"[Skatīt Rimi.lv]({product['rimi_url']})")
    
    db.close()


def main():
    st.title("🛒 Rimi Product Scraper")
    
    # Top navigation
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📦 Category Processing", use_container_width=True, 
                     type="primary" if st.session_state.view_mode == 'category_processing' else "secondary"):
            st.session_state.view_mode = 'category_processing'
            st.rerun()
    
    with col2:
        if st.button("🛍️ Product Browser", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'product_view' else "secondary"):
            st.session_state.view_mode = 'product_view'
            st.rerun()
    
    st.divider()
    
    # Render selected section
    if st.session_state.view_mode == 'category_processing':
        section_category_processing()
    else:
        section_product_view()


if __name__ == "__main__":
    main()
