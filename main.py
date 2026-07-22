"""
Maxima Product Scraper - Redesigned UI
Two-section interface: Category Processing + Product View
"""

import streamlit as st
import pandas as pd
from product_view_db import ProductViewDatabase
import time
import os
import psycopg2
from psycopg2.extras import RealDictCursor
try:
    from combined_ingredient_analyzer import (
        get_analysis_stats, run_test_batch, run_full_analysis,
        reset_all_analysis, batch_update_ingredients, BATCH_SIZE,
        refresh_materialized_view
    )
    _ANALYZER_AVAILABLE = True
    _ANALYZER_ERROR = None
except Exception as _analyzer_import_error:
    _ANALYZER_AVAILABLE = False
    _ANALYZER_ERROR = str(_analyzer_import_error)
    BATCH_SIZE = 40
    get_analysis_stats = run_test_batch = run_full_analysis = None
    reset_all_analysis = batch_update_ingredients = refresh_materialized_view = None

st.set_page_config(
    page_title="Maxima Product Scraper",
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


_NOVA_COLORS = {1: '#038141', 2: '#85BB2F', 3: '#EE8100', 4: '#E63E11'}
_NOVA_LABELS = {
    1: 'Unprocessed',
    2: 'Culinary ingredient',
    3: 'Processed',
    4: 'Ultra-processed',
}
_NOVA_SOURCE_LABELS = {
    'additive_override': 'from additives',
    'category_inherited': 'from category',
    'manual_override': 'manual override',
}


def render_nova_badge(score: int) -> str:
    """Render NOVA score badge HTML"""
    if score is None:
        return ""
    color = _NOVA_COLORS.get(score, '#999')
    label = _NOVA_LABELS.get(score, '')
    return (
        f'<div style="background-color: {color}; color: white; font-weight: bold; '
        f'padding: 4px 8px; border-radius: 4px; display: inline-block; font-size: 13px;">'
        f'NOVA {score} — {label}</div>'
    )


def render_product_card(product: dict) -> None:
    """Render a single product card in grid"""
    
    # Product image
    image_url = product.get('photo_url')
    if image_url:
        st.image(image_url, use_container_width=True)
    else:
        st.markdown("<div style='background:#f0f0f0; height:150px; display:flex; align-items:center; justify-content:center;'>No Image</div>", unsafe_allow_html=True)
    
    # Score badges row
    nutri_grade = product.get('nutri_score_grade')
    nova_score = product.get('nova_score')
    badges = []
    if nutri_grade:
        badges.append(render_nutri_score_badge(nutri_grade))
    if nova_score is not None:
        badges.append(render_nova_badge(nova_score))
    if badges:
        st.markdown(" &nbsp; ".join(badges), unsafe_allow_html=True)

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


def get_category_path_for_url(category_id: int) -> str:
    """Build the full URL path for a category from its hierarchy"""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    conn = None
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                WITH RECURSIVE category_path AS (
                    SELECT category_id, normalized_category, parent_category_id, 1 as depth
                    FROM normalized_categories
                    WHERE category_id = %s
                    
                    UNION ALL
                    
                    SELECT nc.category_id, nc.normalized_category, nc.parent_category_id, cp.depth + 1
                    FROM normalized_categories nc
                    JOIN category_path cp ON nc.category_id = cp.parent_category_id
                )
                SELECT normalized_category FROM category_path
                ORDER BY depth DESC
            """, (category_id,))
            
            rows = cur.fetchall()
            if rows:
                path_parts = [row['normalized_category'] for row in rows]
                return '/'.join(path_parts)
            return None
    except Exception as e:
        return None
    finally:
        if conn:
            conn.close()


def section_category_processing():
    """Section 1: Category Processing for Barbora"""
    st.header("📦 Category Processing")
    
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT category_id, name_lv, name_en, normalized_category, level, parent_category_id, barbora_category_code
            FROM normalized_categories
            ORDER BY level, name_lv
        """)
        all_categories = cur.fetchall()
    
    level1_cats = [c for c in all_categories if c['level'] == 1]
    level2_cats = [c for c in all_categories if c['level'] == 2]
    level3_cats = [c for c in all_categories if c['level'] == 3]
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        level1_options = {f"{c['name_lv']} ({c['name_en']})": c for c in level1_cats}
        selected_l1_name = st.selectbox("Level 1 Category", options=[""] + list(level1_options.keys()))
        selected_l1 = level1_options.get(selected_l1_name)
    
    with col2:
        if selected_l1:
            l2_filtered = [c for c in level2_cats if c['parent_category_id'] == selected_l1['category_id']]
            level2_options = {f"{c['name_lv']} ({c['name_en']})": c for c in l2_filtered}
            selected_l2_name = st.selectbox("Level 2 Category", options=[""] + list(level2_options.keys()))
            selected_l2 = level2_options.get(selected_l2_name)
        else:
            st.selectbox("Level 2 Category", options=["Select Level 1 first"], disabled=True)
            selected_l2 = None
    
    with col3:
        if selected_l2:
            l3_filtered = [c for c in level3_cats if c['parent_category_id'] == selected_l2['category_id']]
            level3_options = {f"{c['name_lv']} ({c['name_en']})": c for c in l3_filtered}
            selected_l3_name = st.selectbox("Level 3 Category", options=[""] + list(level3_options.keys()))
            selected_l3 = level3_options.get(selected_l3_name)
        else:
            st.selectbox("Level 3 Category", options=["Select Level 2 first"], disabled=True)
            selected_l3 = None
    
    selected_category = selected_l3 or selected_l2 or selected_l1
    
    if selected_category:
        category_path = get_category_path_for_url(selected_category['category_id'])
        st.info(f"**Selected:** {selected_category['name_lv']} | **URL Path:** `{category_path}`")
    
    col_opt1, col_opt2 = st.columns([1, 1])
    with col_opt1:
        force_update = st.checkbox("Force Update", help="Overwrite existing data")
    with col_opt2:
        priority = st.number_input("Priority", min_value=1, max_value=10, value=5, help="Higher = more urgent")
    
    col_btn1, col_btn2 = st.columns([1, 2])
    
    with col_btn1:
        queue_job = st.button("📥 Queue Job", type="primary", disabled=not selected_category)
    
    with col_btn2:
        if selected_category:
            st.caption(f"Will scrape products from: barbora.lv/{category_path}")
    
    if queue_job and selected_category:
        from barbora_parser import BarboraParser
        
        category_path = get_category_path_for_url(selected_category['category_id'])
        
        if not category_path:
            st.error("Could not build category path. Please select a valid category.")
        elif not selected_category.get('barbora_category_code'):
            st.error("This category doesn't have a Barbora category code. Please select a Level 3 category.")
        else:
            status_container = st.empty()
            progress_bar = st.progress(0)
            
            def update_status(msg):
                status_container.text(msg)
            
            with st.spinner("Collecting products from Barbora..."):
                try:
                    parser = BarboraParser(status_callback=update_status)
                    
                    total_count, total_pages = parser.get_total_products_count(category_path)
                    st.info(f"Found {total_count} products across {total_pages} pages")
                    
                    products = parser.extract_products_from_category(category_path)
                    valid_products = [p for p in products if p.sku and p.url]
                    
                    progress_bar.progress(50)
                    
                    if not valid_products:
                        st.error(f"No products found in category {selected_category['name_lv']}")
                    else:
                        cur = conn.cursor()
                        
                        try:
                            update_mode = 'full' if force_update else 'incremental'
                            
                            cur.execute("""
                                INSERT INTO category_processing_jobs 
                                (category_code, category_id, total_products, processed_count, status, priority, requested_by, update_mode)
                                VALUES (%s, %s, %s, 0, 'queued', %s, 'streamlit_ui', %s)
                                RETURNING id
                            """, (selected_category['barbora_category_code'], selected_category['category_id'], 
                                  len(valid_products), priority, update_mode))
                            
                            job_id = cur.fetchone()[0]
                            
                            progress_bar.progress(70)
                            
                            import json
                            for p in valid_products:
                                promo_json = json.dumps(p.promotion) if p.promotion else None
                                cur.execute("""
                                    INSERT INTO product_processing_log 
                                    (job_id, sku, product_url, status, price, retail_price, 
                                     price_per_unit, price_per_unit_type, is_available, promotion_data)
                                    VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s)
                                """, (job_id, p.sku, p.url, p.price, p.retail_price,
                                      p.comparative_unit_price, p.comparative_unit, p.is_available, promo_json))
                            
                            cur.execute("""
                                INSERT INTO job_events (job_id, event_type, message)
                                VALUES (%s, 'job_created', %s)
                            """, (job_id, f"Job created for {selected_category['name_lv']} with {len(valid_products)} products"))
                            
                            conn.commit()
                            
                            progress_bar.progress(100)
                            status_container.empty()
                            
                            st.success(f"Job #{job_id} created with {len(valid_products)} products!")
                            
                            with st.expander("View collected products"):
                                for i, p in enumerate(products[:10], 1):
                                    st.write(f"{i}. {p.name} - {p.price} EUR")
                                if len(products) > 10:
                                    st.caption(f"... and {len(products) - 10} more products")
                            
                        except psycopg2.IntegrityError as e:
                            conn.rollback()
                            if 'idx_unique_active_category' in str(e):
                                st.warning(f"Job already exists for this category")
                            else:
                                raise
                                
                except Exception as e:
                    st.error(f"Error: {str(e)}")
                    import traceback
                    with st.expander("Error details"):
                        st.code(traceback.format_exc())
                finally:
                    progress_bar.empty()
    
    st.divider()
    
    st.subheader("Queue All Level 3 Categories")
    
    all_force_update = st.checkbox("Force Update All", help="Overwrite existing data for all categories", key="all_force_update")
    
    col_all1, col_all2 = st.columns([1, 3])
    
    with col_all1:
        if st.button("Queue All Level 3 Categories", type="primary"):
            from barbora_parser import BarboraParser
            
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            try:
                cur.execute("""
                    WITH RECURSIVE category_paths AS (
                        SELECT 
                            c.category_id,
                            c.barbora_category_code,
                            c.name_lv,
                            c.normalized_category,
                            c.level,
                            c.parent_category_id,
                            c.normalized_category as path
                        FROM normalized_categories c
                        WHERE c.level = 1
                        
                        UNION ALL
                        
                        SELECT 
                            child.category_id,
                            child.barbora_category_code,
                            child.name_lv,
                            child.normalized_category,
                            child.level,
                            child.parent_category_id,
                            cp.path || '/' || child.normalized_category as path
                        FROM normalized_categories child
                        JOIN category_paths cp ON child.parent_category_id = cp.category_id
                    )
                    SELECT category_id, barbora_category_code, name_lv, path as category_path
                    FROM category_paths 
                    WHERE level = 3 AND barbora_category_code IS NOT NULL
                    ORDER BY name_lv
                """)
                all_l3_categories = cur.fetchall()
                
                if not all_l3_categories:
                    st.error("No level 3 categories with valid Barbora codes found")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    parser = BarboraParser(lambda msg: None)
                    update_mode = 'full' if all_force_update else 'incremental'
                    
                    total_jobs = 0
                    total_products = 0
                    skipped = 0
                    errors = 0
                    error_details = []
                    
                    for i, cat in enumerate(all_l3_categories):
                        progress_bar.progress((i + 1) / len(all_l3_categories))
                        status_text.text(f"Processing {cat['name_lv']}...")
                        
                        try:
                            category_path = get_category_path_for_url(cat['category_id'])
                            if not category_path:
                                errors += 1
                                error_details.append(f"{cat['name_lv']}: Missing category path (ID: {cat['category_id']})")
                                continue
                                
                            products = parser.extract_products_from_category(category_path)
                            valid_products = [p for p in products if p.sku and p.url]
                            
                            if valid_products:
                                cur.execute("""
                                    INSERT INTO category_processing_jobs 
                                    (category_code, category_id, total_products, processed_count, status, priority, requested_by, update_mode)
                                    VALUES (%s, %s, %s, 0, 'queued', 5, 'streamlit_bulk', %s)
                                    RETURNING id
                                """, (cat['barbora_category_code'], cat['category_id'], len(valid_products), update_mode))
                                
                                job_id = cur.fetchone()['id']
                                
                                import json
                                for p in valid_products:
                                    promo_json = json.dumps(p.promotion) if p.promotion else None
                                    cur.execute("""
                                        INSERT INTO product_processing_log 
                                        (job_id, sku, product_url, status, price, retail_price,
                                         price_per_unit, price_per_unit_type, is_available, promotion_data)
                                        VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s)
                                    """, (job_id, p.sku, p.url, p.price, p.retail_price,
                                          p.comparative_unit_price, p.comparative_unit, p.is_available, promo_json))
                                
                                cur.execute("""
                                    INSERT INTO job_events (job_id, event_type, message)
                                    VALUES (%s, 'job_created', %s)
                                """, (job_id, f"Bulk job for {cat['name_lv']} with {len(valid_products)} products"))
                                
                                conn.commit()
                                total_jobs += 1
                                total_products += len(valid_products)
                            else:
                                errors += 1
                                error_details.append(f"{cat['name_lv']}: No valid products found (path: {category_path})")
                                
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            skipped += 1
                        except Exception as e:
                            conn.rollback()
                            errors += 1
                            error_msg = f"{type(e).__name__}: {str(e)}"
                            error_details.append(f"{cat['name_lv']}: {error_msg[:100]}")
                        
                        time.sleep(0.5)
                    
                    status_text.empty()
                    progress_bar.empty()
                    
                    st.success(f"Created {total_jobs} jobs with {total_products} total products!")
                    if skipped > 0:
                        st.info(f"Skipped {skipped} categories (already have active jobs)")
                    if errors > 0:
                        st.warning(f"{errors} categories had errors")
                        with st.expander("View error details"):
                            for err in error_details[:50]:
                                st.text(err)
                            if len(error_details) > 50:
                                st.text(f"... and {len(error_details) - 50} more errors")
                    
            except Exception as e:
                st.error(f"Error: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
    
    with col_all2:
        st.caption(f"This will queue jobs for all {len(level3_cats)} level 3 categories. Each category will be processed by the worker.")
    
    conn.close()
    
    with st.expander("Help"):
        st.markdown("""
        **Category Processing** allows you to scrape product data from Barbora.lv:
        
        - Select a category using the dropdowns (Level 1 > Level 2 > Level 3)
        - Click "Queue Job" to start collecting products
        - Products are extracted from the `window.b_productList` JSON on each page
        - Toggle "Force Update" to overwrite existing product data
        
        **Data extracted per product:**
        - SKU, Name, Price, Brand
        - Category path, Image URLs
        - Unit pricing (per kg/l)
        - Availability status
        """)


def _render_nova_summary(db: ProductViewDatabase) -> None:
    """Render NOVA score distribution summary bar"""
    try:
        stats = db.get_nova_summary_stats()
    except Exception:
        return

    total = stats['total_products']
    scored = stats['scored_products']
    dist = stats['distribution']

    if not scored:
        return

    nova4 = dist.get(4, {})
    nova4_pct = nova4.get('pct_of_scored', 0)

    with st.expander(f"📊 NOVA Score Summary — {nova4_pct}% of scored products are ultra-processed (NOVA 4)", expanded=False):
        st.caption(f"{scored} of {total} products have a NOVA score")
        cols = st.columns(4)
        for i, (score, color, label) in enumerate([
            (1, _NOVA_COLORS[1], _NOVA_LABELS[1]),
            (2, _NOVA_COLORS[2], _NOVA_LABELS[2]),
            (3, _NOVA_COLORS[3], _NOVA_LABELS[3]),
            (4, _NOVA_COLORS[4], _NOVA_LABELS[4]),
        ]):
            info = dist.get(score, {'count': 0, 'pct_of_scored': 0.0})
            with cols[i]:
                st.markdown(
                    f'<div style="background:{color};color:white;font-weight:bold;'
                    f'padding:8px;border-radius:6px;text-align:center;">'
                    f'NOVA {score}<br>{info["pct_of_scored"]}%<br>'
                    f'<small>{info["count"]} products</small></div>',
                    unsafe_allow_html=True
                )
                st.caption(label)


def section_product_view():
    """Section 2: Product View with hierarchical categories and grid"""
    st.header("🛍️ Product Browser")
    
    # Check if viewing product details
    if st.session_state.selected_product_id:
        render_product_detail_view()
        return
    
    db = ProductViewDatabase()

    # NOVA summary stat
    _render_nova_summary(db)

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
        # Search by ID or SKU
        search_query = st.text_input("🔍 Meklēt pēc produkta ID vai SKU", placeholder="Ievadiet ID vai SKU...")
        
        if search_query.strip():
            # Search mode
            search_term = search_query.strip()
            search_sql = """
            SELECT p.product_id, p.sku, p.name, p.name_norm,
                   nc.name_lv as category_name,
                   (SELECT pp.photo_url FROM productphotos pp WHERE pp.product_id = p.product_id ORDER BY pp.is_primary DESC LIMIT 1) as photo_url,
                   latest_price.price, latest_price.is_available
            FROM products p
            LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
            LEFT JOIN LATERAL (
                SELECT price, is_available FROM product_price_history 
                WHERE product_id = p.product_id 
                ORDER BY recorded_at DESC LIMIT 1
            ) latest_price ON true
            WHERE p.product_id::text = %s OR p.sku = %s
            LIMIT 10
            """
            db._ensure_connection()
            with db.connection.cursor() as cursor:
                cursor.execute(search_sql, (search_term, search_term))
                search_results = cursor.fetchall()
            
            if search_results:
                st.success(f"Atrasti {len(search_results)} produkti")
                for prod in search_results:
                    col_img, col_info = st.columns([1, 4])
                    with col_img:
                        if prod['photo_url']:
                            st.image(prod['photo_url'], width=80)
                        else:
                            st.write("📷")
                    with col_info:
                        if st.button(f"**{prod['name']}**", key=f"search_{prod['product_id']}"):
                            st.session_state.selected_product_id = prod['product_id']
                            st.rerun()
                        st.caption(f"ID: {prod['product_id']} | SKU: {prod['sku']} | {prod['category_name'] or 'Nav kategorijas'}")
                        price_str = f"€{prod['price']:.2f}" if prod['price'] else "Nav cenas"
                        avail_str = "✅ Pieejams" if prod['is_available'] else "❌ Nav pieejams"
                        st.caption(f"{price_str} | {avail_str}")
                    st.divider()
            else:
                st.warning(f"Produkti ar ID vai SKU '{search_term}' nav atrasti")
            return
        
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
            SELECT name_lv, barbora_category_code 
            FROM normalized_categories 
            WHERE category_id = %s
            """
            db._ensure_connection()
            with db.connection.cursor() as cursor:
                cursor.execute(category_query, (st.session_state.selected_category_id,))
                cat_info = cursor.fetchone()
                if cat_info:
                    st.subheader(f"{cat_info['name_lv']} ({cat_info['barbora_category_code']})")
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


def save_nutrition_edits(product_id: int, category_id: int, ingredients_text: str,
                         energy_kj: float, energy_kcal: float, fat_total: float,
                         fat_saturated: float, carbs_total: float, carbs_sugars: float,
                         fiber: float, protein: float, salt: float, mark_manual: bool):
    """Save manually edited nutrition facts and recalculate Nutri-Score."""
    from nutriscore_calculator import NutriscoreCalculator
    
    db = ProductViewDatabase()
    db._ensure_connection()
    
    try:
        # Calculate new Nutri-Score
        calculator = NutriscoreCalculator(db.connection)
        
        result = calculator.calculate_single_product(
            energy_kj=energy_kj,
            sugars=carbs_sugars,
            salt=salt,
            saturated_fat=fat_saturated,
            protein=protein,
            fiber=fiber,
            total_fat=fat_total,
            fruits_veg_nuts=0,
            category_id=category_id,
            product_name=None,
            ingredients_text=ingredients_text
        )
        
        new_grade = result.get('grade', 'U')
        new_points = result.get('score', 0)
        
        # Update nutritionfacts table
        with db.connection.cursor() as cur:
            cur.execute("""
                UPDATE nutritionfacts SET
                    energy_kj = %s,
                    energy_kcal = %s,
                    fat_total = %s,
                    fat_saturated = %s,
                    carbs_total = %s,
                    carbs_sugars = %s,
                    fiber = %s,
                    protein = %s,
                    salt = %s,
                    nutri_score_grade = %s,
                    nutri_score_points = %s,
                    nutrition_manual_edit = %s
                WHERE product_id = %s
            """, (
                energy_kj, energy_kcal, fat_total, fat_saturated,
                carbs_total, carbs_sugars, fiber, protein, salt,
                new_grade, new_points, mark_manual, product_id
            ))
            db.connection.commit()
    except Exception as e:
        db.connection.rollback()
        raise e
    finally:
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

        # NOVA Score + inline override
        nova_score  = product.get('nova_score')
        nova_source = product.get('nova_source')
        product_id  = product['product_id']
        sku         = product['sku']

        if nova_score is not None:
            st.markdown(render_nova_badge(nova_score), unsafe_allow_html=True)
            source_label = _NOVA_SOURCE_LABELS.get(nova_source, nova_source or '')
            st.caption(f"NOVA source: {source_label}")

        with st.expander("✏️ Override NOVA score", expanded=False):
            new_score = st.selectbox(
                "Set score",
                options=[1, 2, 3, 4],
                index=(nova_score - 1) if nova_score else 3,
                format_func=lambda s: f"NOVA {s} — {_NOVA_LABELS[s]}",
                key=f"nova_override_sel_{product_id}",
            )
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("💾 Save", key=f"nova_override_save_{product_id}", use_container_width=True):
                    db.set_nova_override(product_id, new_score)
                    st.success(f"NOVA {new_score} saved")
                    st.rerun()
            with btn_col2:
                if nova_source == 'manual_override':
                    if st.button("↩️ Remove", key=f"nova_override_rm_{product_id}", use_container_width=True):
                        result = db.remove_nova_override(product_id, sku)
                        auto = result.get('nova_score')
                        if auto:
                            st.info(f"Restored: NOVA {auto} ({result.get('nova_source', '')})")
                        else:
                            st.info("Override removed — no automatic score found.")
                        st.rerun()

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
    
    # Manual edit indicator
    if product.get('nutrition_manual_edit'):
        st.info("✏️ Šis produkts ir manuāli rediģēts (aizsargāts no automātiskās pārrakstīšanas)")
    
    # Nutrition editing expander
    with st.expander("✏️ Rediģēt uzturvielu informāciju"):
        st.markdown("**Uzturvielu dati uz 100g/ml:**")
        
        # Initialize edit values from product
        edit_key_prefix = f"edit_{product['product_id']}_"
        
        col1, col2 = st.columns(2)
        
        with col1:
            energy_kj = st.number_input(
                "Enerģija (kJ)", 
                value=float(product.get('energy_kj') or 0),
                min_value=0.0,
                step=1.0,
                key=f"{edit_key_prefix}energy_kj"
            )
            energy_kcal = st.number_input(
                "Enerģija (kcal)", 
                value=float(product.get('energy_kcal') or 0),
                min_value=0.0,
                step=1.0,
                key=f"{edit_key_prefix}energy_kcal"
            )
            fat_total = st.number_input(
                "Tauki (g)", 
                value=float(product.get('fat_total') or 0),
                min_value=0.0,
                step=0.1,
                key=f"{edit_key_prefix}fat_total"
            )
            fat_saturated = st.number_input(
                "Piesātinātie tauki (g)", 
                value=float(product.get('fat_saturated') or 0),
                min_value=0.0,
                step=0.1,
                key=f"{edit_key_prefix}fat_saturated"
            )
            salt = st.number_input(
                "Sāls (g)", 
                value=float(product.get('salt') or 0),
                min_value=0.0,
                step=0.01,
                key=f"{edit_key_prefix}salt"
            )
        
        with col2:
            carbs_total = st.number_input(
                "Ogļhidrāti (g)", 
                value=float(product.get('carbs_total') or 0),
                min_value=0.0,
                step=0.1,
                key=f"{edit_key_prefix}carbs_total"
            )
            carbs_sugars = st.number_input(
                "Cukuri (g)", 
                value=float(product.get('carbs_sugars') or 0),
                min_value=0.0,
                step=0.1,
                key=f"{edit_key_prefix}carbs_sugars"
            )
            fiber = st.number_input(
                "Šķiedrvielas (g)", 
                value=float(product.get('fiber') or 0),
                min_value=0.0,
                step=0.1,
                key=f"{edit_key_prefix}fiber"
            )
            protein = st.number_input(
                "Olbaltumvielas (g)", 
                value=float(product.get('protein') or 0),
                min_value=0.0,
                step=0.1,
                key=f"{edit_key_prefix}protein"
            )
        
        # Checkbox for manual edit flag
        mark_manual = st.checkbox(
            "Atzīmēt kā manuāli rediģētu (novērsis automātisko pārrakstīšanu)",
            value=True,
            key=f"{edit_key_prefix}mark_manual"
        )
        
        # Save button
        if st.button("💾 Saglabāt un pārrēķināt Nutri-Score", type="primary", key=f"{edit_key_prefix}save"):
            save_nutrition_edits(
                product_id=product['product_id'],
                category_id=product.get('category_id'),
                ingredients_text=product.get('ingredients_text'),
                energy_kj=energy_kj,
                energy_kcal=energy_kcal,
                fat_total=fat_total,
                fat_saturated=fat_saturated,
                carbs_total=carbs_total,
                carbs_sugars=carbs_sugars,
                fiber=fiber,
                protein=protein,
                salt=salt,
                mark_manual=mark_manual
            )
            st.success("✅ Uzturvielu dati saglabāti un Nutri-Score pārrēķināts!")
            st.rerun()
    
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
    st.write(f"{product.get('category_name', 'N/A')} ({product.get('barbora_category_code', 'N/A')})")
    
    # Link to Barbora
    if product.get('barbora_url'):
        st.subheader("🔗 Saites")
        st.markdown(f"[Skatīt Barbora.lv]({product['barbora_url']})")
    
    db.close()


def section_nutrition_enrichment():
    """Section 3: Nutrition Data Enrichment from USDA"""
    from nutrition_enrichment_service import NutritionEnrichmentService, EnrichmentBatch
    
    st.header("🥗 Nutrition Data Enrichment")
    st.caption("Enrich products with missing nutrition data using USDA FoodData Central")
    
    if 'enrichment_batch' not in st.session_state:
        st.session_state.enrichment_batch = None
    if 'enrichment_processing' not in st.session_state:
        st.session_state.enrichment_processing = False
    if 'enrichment_log' not in st.session_state:
        st.session_state.enrichment_log = []
    if 'enrichment_log_buffer' not in st.session_state:
        st.session_state.enrichment_log_buffer = []
    
    import threading
    log_buffer = st.session_state.enrichment_log_buffer
    log_lock = threading.Lock()
    
    def log_callback(msg):
        with log_lock:
            log_buffer.append(msg)
    
    try:
        service = NutritionEnrichmentService(status_callback=log_callback)
        stats = service.get_enrichment_stats()
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Needs Enrichment", stats['needs_enrichment'])
        with col2:
            st.metric("Reviewed", stats['reviewed'])
        with col3:
            st.metric("From USDA", stats['from_usda'])
        with col4:
            st.metric("From Rimi", stats['from_rimi'])
        
        # Show scan button if no products are flagged but some need enrichment
        unflagged_count = service.get_unflagged_missing_count()
        if unflagged_count > 0:
            st.warning(f"Found {unflagged_count} products with missing nutrition data that aren't flagged for enrichment.")
            if st.button("🔍 Scan & Flag Products", type="primary"):
                with st.spinner("Scanning products with missing nutrition data..."):
                    result = service.scan_and_flag_products()
                    st.success(f"Flagged {result['flagged']} products for enrichment!")
                    st.rerun()
        
        st.divider()
        
        categories = service.get_categories_needing_enrichment()
        category_options = {"All Categories": None}
        for cat in categories:
            label = f"{cat['name_lv']} ({cat['product_count']})"
            category_options[label] = cat['category_id']
        
        col1, col2, col3, col4 = st.columns([1, 2, 1, 2])
        
        with col1:
            batch_size = st.selectbox("Batch Size", [10, 20, 30, 50], index=1)
        
        with col2:
            selected_category = st.selectbox("Category Filter", list(category_options.keys()), index=0)
            selected_category_id = category_options[selected_category]
        
        with col3:
            if st.button("🔄 Load Batch", type="primary", disabled=st.session_state.enrichment_processing):
                st.session_state.enrichment_log = []
                st.session_state.enrichment_log_buffer = []
                log_buffer.clear()
                st.session_state.enrichment_processing = True
                st.session_state.enrichment_category_id = selected_category_id
                st.rerun()
        
        with col4:
            if st.session_state.enrichment_batch:
                batch = st.session_state.enrichment_batch
                st.info(f"Batch: {batch.approved} approved, {batch.skipped} skipped, {batch.pending} pending, {batch.no_match} no match")
            if stats['skipped'] > 0:
                st.caption(f"📋 {stats['skipped']} products in skip list (sorted to end of batches)")
        
        if st.session_state.enrichment_processing and not st.session_state.enrichment_batch:
            with st.spinner("Loading and processing products..."):
                cat_id = st.session_state.get('enrichment_category_id')
                products = service.get_products_needing_enrichment(limit=batch_size, category_id=cat_id)
                if products:
                    batch = service.process_batch(products)
                    st.session_state.enrichment_batch = batch
                else:
                    st.success("No products need enrichment in this category!")
                st.session_state.enrichment_log = list(log_buffer)
                st.session_state.enrichment_processing = False
                st.rerun()
        
        if log_buffer:
            st.session_state.enrichment_log = list(log_buffer)
        
        if st.session_state.enrichment_log:
            with st.expander("Processing Log", expanded=False):
                for log in st.session_state.enrichment_log[-50:]:
                    st.text(log)
        
        if st.session_state.enrichment_batch:
            batch = st.session_state.enrichment_batch
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if st.button("✅ Approve All Matches", disabled=batch.pending == 0):
                    for match in batch.matches:
                        if match.status == 'pending' and match.usda_match:
                            service.save_enrichment(match)
                    st.rerun()
            with col2:
                if st.button("⏭️ Skip All Remaining"):
                    for match in batch.matches:
                        if match.status in ['pending', 'no_match']:
                            service.skip_product(match)
                    st.rerun()
            with col3:
                if st.button("🔄 Reprocess Skipped", disabled=batch.skipped == 0):
                    for match in batch.matches:
                        if match.status == 'skipped':
                            service.unskip_product(match)
                    st.rerun()
            with col4:
                if st.button("🆕 New Batch"):
                    st.session_state.enrichment_batch = None
                    st.session_state.enrichment_log = []
                    st.session_state.enrichment_log_buffer = []
                    log_buffer.clear()
                    st.rerun()
            
            st.divider()
            
            for i, match in enumerate(batch.matches):
                status_icon = {
                    'pending': '⏳',
                    'approved': '✅',
                    'skipped': '⏭️',
                    'no_match': '❌'
                }.get(match.status, '❓')
                
                with st.expander(f"{status_icon} {match.product.name} (SKU: {match.product.sku})", expanded=(match.status == 'pending')):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**Product Info:**")
                        st.write(f"**Name:** {match.product.name}")
                        st.write(f"**Category:** {match.product.category_name or 'N/A'}")
                        st.write(f"**Translation:** {match.translation.english}")
                        st.write(f"**Method:** {match.translation.method} ({match.translation.confidence:.0%})")
                    
                    with col2:
                        if match.usda_options:
                            st.markdown("**USDA Match Options:**")
                            
                            option_labels = [
                                f"{opt.description} (Score: {opt.score:.0f})"
                                for opt in match.usda_options
                            ]
                            
                            selected_idx = st.selectbox(
                                "Select match:",
                                options=range(len(option_labels)),
                                format_func=lambda x: option_labels[x],
                                index=match.selected_index,
                                key=f"select_{i}"
                            )
                            
                            if selected_idx != match.selected_index:
                                match.select_option(selected_idx)
                            
                            if match.usda_match:
                                st.write(f"**Data Type:** {match.usda_match.data_type}")
                                usda_url = f"https://fdc.nal.usda.gov/fdc-app.html#/food-details/{match.usda_match.fdc_id}/nutrients"
                                st.markdown(f"**USDA Link:** [FDC #{match.usda_match.fdc_id}]({usda_url})")
                                
                                if match.usda_match.nutrition:
                                    n = match.usda_match.nutrition
                                    st.markdown("**Nutrition (per 100g):**")
                                    ncol1, ncol2, ncol3 = st.columns(3)
                                    with ncol1:
                                        st.metric("Energy", f"{n.energy_kcal or 0:.0f} kcal")
                                        st.metric("Protein", f"{n.protein or 0:.1f}g")
                                    with ncol2:
                                        st.metric("Fat", f"{n.fat_total or 0:.1f}g")
                                        st.metric("Sat. Fat", f"{n.fat_saturated or 0:.1f}g")
                                    with ncol3:
                                        st.metric("Carbs", f"{n.carbs_total or 0:.1f}g")
                                        st.metric("Sugars", f"{n.carbs_sugars or 0:.1f}g")
                                    
                                    scol1, scol2 = st.columns(2)
                                    with scol1:
                                        st.metric("Salt", f"{n.salt or 0:.2f}g")
                                    with scol2:
                                        st.metric("Fiber", f"{n.fiber or 0:.1f}g")
                        else:
                            st.warning("No USDA match found")
                            st.info("Use custom search below to find a match")
                    
                    if match.status in ['pending', 'no_match', 'skipped']:
                        bcol1, bcol2, bcol3 = st.columns(3)
                        
                        with bcol1:
                            if match.usda_match and match.status == 'pending' and st.button("✅ Approve", key=f"approve_{i}"):
                                service.save_enrichment(match)
                                st.rerun()
                        
                        with bcol2:
                            if match.status in ['pending', 'no_match'] and st.button("⏭️ Skip", key=f"skip_{i}"):
                                service.skip_product(match)
                                st.rerun()
                            if match.status == 'skipped' and st.button("🔄 Unskip", key=f"unskip_{i}"):
                                service.unskip_product(match)
                                st.rerun()
                        
                        with bcol3:
                            custom_term = st.text_input("Custom search:", key=f"search_{i}", 
                                placeholder="e.g., pomegranate, lime, persimmon")
                            if custom_term and st.button("🔍 Search", key=f"dosearch_{i}"):
                                new_match = service.search_custom_term(match.product, custom_term)
                                batch.matches[i] = new_match
                                st.rerun()
        
    except Exception as e:
        st.error(f"Error initializing enrichment service: {str(e)}")
        st.info("Make sure USDA_API_KEY is set in secrets.")
        import traceback
        st.code(traceback.format_exc())


def section_change_report():
    """Section 4: Change Report - Compare current vs previous product state"""
    st.header("📊 Change Report")
    
    from change_report import ChangeReportGenerator
    
    try:
        report = ChangeReportGenerator()
        
        timestamps = report.get_update_timestamps()
        if timestamps['current_update']:
            current_str = timestamps['current_update'].strftime("%Y-%m-%d %H:%M")
            previous_str = timestamps['previous_update'].strftime("%Y-%m-%d %H:%M") if timestamps['previous_update'] else "N/A"
            st.caption(f"Comparing: **{current_str}** vs **{previous_str}**")
        
        stats = report.get_summary_stats()
        
        st.subheader("📈 Summary")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Products", stats.total_products)
        with col2:
            st.metric("New Products", stats.new_products, delta=f"+{stats.new_products}" if stats.new_products > 0 else None)
        with col3:
            st.metric("Price Changes", stats.price_changed)
        with col4:
            st.metric("Availability Changes", stats.availability_changed)
        
        col5, col6, col7, col8 = st.columns(4)
        with col5:
            st.metric("Price Increased", stats.price_increased, delta=f"↑ {stats.price_increased}", delta_color="inverse")
        with col6:
            st.metric("Price Decreased", stats.price_decreased, delta=f"↓ {stats.price_decreased}", delta_color="normal")
        with col7:
            st.metric("Became Available", stats.became_available, delta=f"+{stats.became_available}" if stats.became_available > 0 else None)
        with col8:
            st.metric("Became Unavailable", stats.became_unavailable, delta=f"-{stats.became_unavailable}" if stats.became_unavailable > 0 else None, delta_color="inverse")
        
        st.divider()
        
        tab1, tab2, tab3, tab4 = st.tabs(["💰 Price Changes", "📦 Availability Changes", "🆕 New Products", "📂 By Category"])
        
        with tab1:
            st.subheader("Price Changes")
            st.caption("Prices shown are effective prices (MansRimi discount price when available, otherwise regular price)")
            price_changes = report.get_price_changes(limit=100)
            
            if price_changes:
                import pandas as pd
                df = pd.DataFrame(price_changes)
                df['previous_price'] = df['previous_price'].fillna(0)
                df['current_price'] = df['current_price'].fillna(0)
                df['price_change_pct'] = df['price_change_pct'].fillna(0)
                
                st.write(f"**{stats.price_increased} price increases, {stats.price_decreased} price decreases** (showing top 100 by change magnitude)")
                
                def format_price_with_discount(row, price_col, has_discount_col, regular_price_col, discount_price_col):
                    """Format price with discount indicator if applicable"""
                    price = row[price_col]
                    has_discount = row.get(has_discount_col, False)
                    if has_discount:
                        regular = row.get(regular_price_col, 0) or 0
                        return f"{price:.2f} (was {regular:.2f})"
                    return f"{price:.2f}"
                
                df['previous_display'] = df.apply(
                    lambda r: format_price_with_discount(r, 'previous_price', 'previous_has_discount', 'previous_regular_price', 'previous_discount_price'),
                    axis=1
                )
                df['current_display'] = df.apply(
                    lambda r: format_price_with_discount(r, 'current_price', 'current_has_discount', 'current_regular_price', 'current_discount_price'),
                    axis=1
                )
                
                display_df = df[['name', 'category_name', 'previous_display', 'current_display', 'price_change_pct', 'barbora_url']].copy()
                display_df.columns = ['Product', 'Category', 'Previous (€)', 'Current (€)', 'Change (%)', 'Link']
                st.dataframe(
                    display_df, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Link": st.column_config.LinkColumn(
                            "Barbora",
                            display_text="Open",
                            help="Click to view product on Barbora website"
                        )
                    }
                )
            else:
                st.info("No price changes detected")
        
        with tab2:
            st.subheader("Availability Changes")
            avail_changes = report.get_availability_changes(limit=100)
            
            if avail_changes:
                import pandas as pd
                df = pd.DataFrame(avail_changes)
                df['status_change'] = df.apply(
                    lambda r: "🟢 Now Available" if r['current_available'] else "🔴 Now Unavailable", 
                    axis=1
                )
                
                st.write(f"**{stats.became_available} became available, {stats.became_unavailable} became unavailable** (showing top 100)")
                
                display_df = df[['name', 'category_name', 'status_change', 'current_price']].copy()
                display_df.columns = ['Product', 'Category', 'Status', 'Price (€)']
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No availability changes detected")
        
        with tab3:
            st.subheader("New Products")
            new_products = report.get_new_products(limit=100)
            
            if new_products:
                import pandas as pd
                df = pd.DataFrame(new_products)
                df['status'] = df['is_available'].apply(lambda x: "🟢 Available" if x else "🔴 Unavailable")
                
                display_df = df[['name', 'category_name', 'price', 'status']].copy()
                display_df.columns = ['Product', 'Category', 'Price (€)', 'Status']
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No new products detected")
        
        with tab4:
            st.subheader("Changes by Category")
            category_breakdown = report.get_category_breakdown()
            
            if category_breakdown:
                import pandas as pd
                df = pd.DataFrame(category_breakdown)
                df['total_changes'] = df['new_products'] + df['price_changed'] + df['availability_changed']
                
                display_df = df[['category_name', 'category_code', 'total_products', 'new_products', 'price_changed', 'availability_changed']].copy()
                display_df.columns = ['Category', 'Code', 'Total', 'New', 'Price Δ', 'Avail Δ']
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No category changes detected")
                
    except Exception as e:
        st.error(f"Error generating report: {str(e)}")
        import traceback
        st.code(traceback.format_exc())


def section_fiber_estimation():
    """Section: Fiber Estimation for Nutri-Score improvement"""
    st.subheader("🌾 Fiber Estimation")
    
    st.info("""
    Estimate fiber content for products missing fiber data to improve Nutri-Score accuracy.
    
    - Uses category defaults from AI analysis of typical fiber content
    - Exception rules override defaults for specific product types (whole grain, dark chocolate, etc.)
    - Products with existing fiber > 0 are skipped
    - Estimated fiber is marked `is_fiber_correct=FALSE` until manually verified
    """)
    
    from fiber_estimator import (
        FiberEstimator, get_fiber_stats, get_products_for_estimation,
        get_products_for_estimation_count, preview_fiber_estimates,
        apply_all_fiber_estimates
    )
    
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        st.error("DATABASE_URL not configured")
        return
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    try:
        stats = get_fiber_stats(conn)
    finally:
        conn.close()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Products", stats.get('total_products', 0))
    with col2:
        st.metric("Missing Fiber", stats.get('missing_fiber', 0))
    with col3:
        st.metric("Has Fiber", stats.get('has_fiber', 0))
    with col4:
        st.metric("Marked Correct", stats.get('marked_correct', 0))
    
    estimator = FiberEstimator()
    
    with st.expander("📋 Category Fiber Defaults"):
        defaults_df = pd.DataFrame([
            {"Category ID": k, "Fiber (g)": v} 
            for k, v in sorted(estimator.category_defaults.items())
        ])
        st.dataframe(defaults_df, use_container_width=True, hide_index=True, height=300)
    
    with st.expander("⚠️ Exception Rules"):
        exceptions_data = []
        for rule in estimator.exception_rules:
            exceptions_data.append({
                "Category Prefix": rule['category_id_prefix'],
                "Description": rule['category_description'],
                "Keywords": ", ".join(rule['keywords']),
                "Fiber (g)": rule['fiber'],
                "Reason": rule['reason']
            })
        exceptions_df = pd.DataFrame(exceptions_data)
        st.dataframe(exceptions_df, use_container_width=True, hide_index=True)
    
    st.divider()
    
    preview_limit = st.number_input("Preview limit (products to show)", min_value=10, max_value=500, value=50)
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔍 Preview Fiber Estimates", type="primary", use_container_width=True):
            with st.spinner("Calculating fiber estimates..."):
                estimates, total_count = preview_fiber_estimates(limit=preview_limit)
                
                if not estimates:
                    st.info("No products need fiber estimation (either all have fiber or no rimi_category_code mapping)")
                else:
                    st.success(f"**{total_count}** products ready for fiber estimation")
                    
                    preview_df = pd.DataFrame([{
                        'sku': e['sku'],
                        'name': e['name'][:50] if e['name'] else '',
                        'category': e['rimi_category_code'],
                        'old_fiber': e['old_fiber'] or 0,
                        'new_fiber': e['new_fiber'],
                        'match_type': e['match_type'],
                        'before_grade': e.get('before_grade', ''),
                        'new_grade': e.get('new_grade', '')
                    } for e in estimates])
                    
                    st.dataframe(preview_df, use_container_width=True, hide_index=True)
                    
                    st.session_state['fiber_estimates_ready'] = True
                    st.session_state['fiber_estimates_count'] = total_count
    
    with col2:
        ready_count = st.session_state.get('fiber_estimates_count', 0)
        button_label = f"✅ Apply All Estimates" if ready_count == 0 else f"✅ Apply All Estimates ({ready_count})"
        
        if st.button(button_label, use_container_width=True):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def progress_callback(processed, total):
                progress = min(processed / total, 1.0) if total > 0 else 0
                progress_bar.progress(progress)
                status_text.text(f"Applying fiber estimates to {processed}/{total} products...")
            
            status_text.text("Starting fiber estimation...")
            
            result = apply_all_fiber_estimates(progress_callback=progress_callback)
            
            progress_bar.progress(1.0)
            status_text.text("Complete!")
            
            if result.get('error'):
                st.error(result['error'])
            else:
                st.success(f"""
                **Results:**
                - Updated: **{result.get('updated', 0)}** products
                - Grade changed: **{result.get('grades_changed', 0)}** products
                """)
                
                st.session_state['fiber_estimates_ready'] = False
                st.session_state['fiber_estimates_count'] = 0


def section_quantity_backfill():
    """Section: Quantity Backfill — fill quantity_value / quantity_unit for existing products."""
    st.subheader("📦 Quantity Backfill")

    st.info(
        "Parses `quantity_value` and `quantity_unit` from product names for all products "
        "that currently have no quantity data. Products with a recognisable unit in their name "
        "(e.g. '500 g', '0.75 l', '20x2.25g', 'kg') will be updated. "
        "The remaining products will stay empty until they are re-scraped."
    )

    # --- Preview ---
    db = ProductViewDatabase()
    db._ensure_connection()
    with db.connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM products WHERE quantity_value IS NULL AND quantity_unit IS NULL")
        null_count = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) AS total FROM products")
        all_count = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) AS total FROM products WHERE quantity_value IS NOT NULL OR quantity_unit IS NOT NULL")
        filled_count = cur.fetchone()['total']

    col1, col2, col3 = st.columns(3)
    col1.metric("Total products", all_count)
    col2.metric("Already have quantity", filled_count)
    col3.metric("Missing quantity (will process)", null_count)

    if null_count == 0:
        st.success("All products already have quantity data.")
        return

    # --- Sample preview ---
    with st.expander("Preview: sample of products that will be parsed", expanded=False):
        from barbora_worker import BarboraWorker
        worker = BarboraWorker.__new__(BarboraWorker)  # no DB connection needed for parsing
        worker.nutriscore_calculator = None
        worker.ingredient_processor = None
        worker.fiber_estimator = None

        with db.connection.cursor() as cur:
            cur.execute("""
                SELECT name FROM products
                WHERE quantity_value IS NULL AND quantity_unit IS NULL
                ORDER BY RANDOM() LIMIT 20
            """)
            sample_rows = [dict(r) for r in cur.fetchall()]

        preview_data = []
        for row in sample_rows:
            v, u = worker._parse_quantity(row['name'])
            preview_data.append({
                'Name': row['name'],
                'Parsed value': str(v) if v is not None else '—',
                'Parsed unit': u if u else '—',
            })

        import pandas as pd
        st.dataframe(pd.DataFrame(preview_data), use_container_width=True)

    # --- Run ---
    if st.button("▶ Run Quantity Backfill", type="primary"):
        log_lines = []
        progress = st.progress(0)
        status_box = st.empty()

        def log(msg):
            log_lines.append(msg)
            status_box.text(msg)

        with st.spinner("Running backfill…"):
            from barbora_worker import BarboraWorker
            worker = BarboraWorker()
            result = worker.backfill_quantity_from_names(status_callback=log)

        progress.progress(1.0)

        if 'error' in result:
            st.error(f"Backfill failed: {result['error']}")
        else:
            st.success(
                f"Done — {result['updated']} products updated, "
                f"{result['skipped']} had no parseable pattern, "
                f"{result['failed']} errors."
            )
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Processed", result['total'])
            c2.metric("Updated", result['updated'])
            c3.metric("No pattern", result['skipped'])
            c4.metric("Errors", result['failed'])

        with st.expander("Log", expanded=False):
            st.text("\n".join(log_lines))


def section_fix_photos():
    """Section: Fix broken / missing product photos."""
    st.subheader("🖼️ Fix Broken Photos")

    st.info(
        "Checks every stored photo URL with a HEAD request, then re-scrapes the "
        "Barbora product page for any that are broken (non-200 or placeholder redirect). "
        "Products that have no photo at all are also scraped. "
        "If a re-scrape finds nothing, the existing rows are left untouched."
    )

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        st.error("DATABASE_URL not configured")
        return

    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM productphotos")
            total_photos = cur.fetchone()["n"]
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM products p
                WHERE p.barbora_url IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM productphotos ph WHERE ph.product_id = p.product_id
                  )
                """
            )
            no_photo_count = cur.fetchone()["n"]
    finally:
        conn.close()

    c1, c2 = st.columns(2)
    c1.metric("Stored photo URLs", f"{total_photos:,}")
    c2.metric("Products with no photo", f"{no_photo_count:,}")

    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        dry_run = st.checkbox("Dry-run (preview only, no DB writes)", value=False)
    with col_b:
        concurrency = st.slider("HEAD request threads", min_value=1, max_value=30, value=10)

    limit_enabled = st.checkbox("Limit scope (useful for testing)")
    limit_val = None
    if limit_enabled:
        limit_val = st.number_input(
            "Check only the first N photo rows",
            min_value=10, max_value=total_photos, value=min(500, total_photos), step=50
        )

    if not st.button("▶ Start Photo Fix", type="primary", use_container_width=True):
        return

    st.divider()

    phase1_label = st.empty()
    phase1_bar = st.progress(0.0)
    phase2_label = st.empty()
    phase2_bar = st.progress(0.0)
    log_box = st.empty()
    log_lines: list = []

    def log(msg: str):
        log_lines.append(msg)
        log_box.text("\n".join(log_lines[-20:]))

    phase1_total = [1]
    phase2_total = [1]

    def on_progress(done: int, total: int, phase: int = 1):
        if phase == 1:
            phase1_total[0] = max(total, 1)
            phase1_label.text(f"Phase 1 — verifying URLs: {done}/{total}")
            phase1_bar.progress(min(done / phase1_total[0], 1.0))
        else:
            phase2_total[0] = max(total, 1)
            phase2_label.text(f"Phase 2 — re-scraping: {done}/{total}")
            phase2_bar.progress(min(done / phase2_total[0], 1.0))

    from fix_broken_photos import run as run_photo_fix

    with st.spinner("Running photo fix…"):
        result = run_photo_fix(
            dry_run=dry_run,
            limit=int(limit_val) if limit_val else None,
            concurrency=concurrency,
            log=log,
            progress_callback=on_progress,
        )

    phase1_bar.progress(1.0)
    phase2_bar.progress(1.0)
    phase1_label.text("Phase 1 — done")
    phase2_label.text("Phase 2 — done")

    prefix = "🔍 DRY-RUN — " if dry_run else ""
    st.success(f"{prefix}Photo fix complete!")

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Photos checked", f"{result['total_checked']:,}")
    r2.metric("Broken found", f"{result['broken_found']:,}")
    r3.metric("Fixed", f"{result['fixed']:,}")
    r4.metric("Unresolvable", f"{result['unresolvable']:,}")

    r5, r6 = st.columns(2)
    r5.metric("Products had no photo", f"{result['no_photo_products']:,}")
    r6.metric("Missing now filled", f"{result['missing_scraped']:,}")

    with st.expander("Full log", expanded=False):
        st.text("\n".join(log_lines))


def section_nutriscore_recalculation():
    """Section: Nutri-Score Tools"""
    st.header("📊 Nutri-Score Tools")

    tool = st.radio(
        "Tool:",
        [
            "🔄 Recalculate Nutri-Score",
            "🌾 Fiber Estimation",
            "📦 Quantity Backfill",
            "🖼️ Fix Broken Photos",
        ],
        horizontal=True,
    )

    if tool == "🌾 Fiber Estimation":
        section_fiber_estimation()
        return

    if tool == "📦 Quantity Backfill":
        section_quantity_backfill()
        return

    if tool == "🖼️ Fix Broken Photos":
        section_fix_photos()
        return
    
    st.subheader("🔄 Recalculate Nutri-Score")
    
    st.info("""
    Recalculate Nutri-Score for products using the updated category mappings.
    This will update the `nutri_score_grade` and `nutri_score_points` in the database.
    """)
    
    from nutriscore_calculator import NutriscoreCalculator, FAT_UUIDS, CHEESE_UUIDS, FULL_FVN_UUIDS, HALF_FVN_UUIDS, BEVERAGE_UUIDS
    
    with st.expander("📋 Current Category Mappings (UUIDs)", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Fat Categories:** {len(FAT_UUIDS)} UUIDs")
            st.write(f"**Cheese Categories:** {len(CHEESE_UUIDS)} UUIDs")
            st.write(f"**Beverage Categories:** {len(BEVERAGE_UUIDS)} UUIDs")
        with col2:
            st.write(f"**100% Fruits/Veg/Nuts:** {len(FULL_FVN_UUIDS)} UUIDs")
            st.write(f"**50% Fruits/Veg/Nuts:** {len(HALF_FVN_UUIDS)} UUIDs")
    
    mode = st.radio(
        "Recalculation Mode:",
        ["Single Product (by SKU)", "By Category", "All Products"],
        horizontal=True
    )
    
    db = ProductViewDatabase()
    
    if mode == "Single Product (by SKU)":
        sku = st.text_input("Enter Product SKU:")
        
        if st.button("Recalculate Nutri-Score", type="primary") and sku:
            with st.spinner("Recalculating..."):
                result = recalculate_nutriscore_for_product(db, sku.strip())
                if result['success']:
                    details = result.get('details', {})
                    old_grade = details.get('old_grade')
                    new_grade = details.get('new_grade')
                    old_score = details.get('old_score')
                    new_score = details.get('new_score')
                    
                    changed = (old_grade != new_grade) or (str(old_score) != str(new_score))
                    
                    if changed:
                        st.success(f"✅ Score changed: {old_grade} ({old_score}) → {new_grade} ({new_score})")
                    else:
                        st.info(f"ℹ️ No change: {new_grade} ({new_score})")
                    
                    if details:
                        st.json(details)
                else:
                    st.error(f"❌ {result['message']}")
    
    elif mode == "By Category":
        db._ensure_connection()
        with db.connection.cursor() as cur:
            cur.execute("""
                SELECT barbora_category_code, name_lv
                FROM normalized_categories 
                WHERE level = 2
                ORDER BY name_lv
            """)
            categories = [dict(row) for row in cur.fetchall()]
        
        category_options = {c['name_lv']: c['barbora_category_code'] for c in categories}
        
        selected_category_name = st.selectbox("Select Category:", list(category_options.keys()))
        selected_category_code = category_options.get(selected_category_name)
        
        if st.button("Recalculate Nutri-Score for Category", type="primary") and selected_category_code:
            products = get_products_for_nutriscore_recalc(db, category_code=selected_category_code)
            
            if not products:
                st.warning("No products with nutrition data found in this category.")
            else:
                st.write(f"Found **{len(products)}** products with nutrition data in this category.")
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                results_placeholder = st.empty()
                
                success_count = 0
                changed_count = 0
                failed_count = 0
                skipped_count = 0
                
                for i, product in enumerate(products):
                    status_text.text(f"Processing {i+1}/{len(products)}: {product['name'][:50]}...")
                    result = recalculate_nutriscore_for_product_data(db, product)
                    
                    if result['success']:
                        success_count += 1
                        details = result.get('details', {})
                        old_grade = details.get('old_grade')
                        new_grade = details.get('new_grade')
                        old_score = details.get('old_score')
                        new_score = details.get('new_score')
                        if (old_grade != new_grade) or (str(old_score) != str(new_score)):
                            changed_count += 1
                    elif result.get('skipped'):
                        skipped_count += 1
                    else:
                        failed_count += 1
                    
                    progress_bar.progress((i + 1) / len(products))
                
                status_text.text("Recalculation complete!")
                results_placeholder.success(f"""
                **Results:**
                - ✅ Successfully processed: {success_count}
                - 🔄 Score changed: {changed_count}
                - ⏭️ Skipped (no nutrition data): {skipped_count}
                - ❌ Failed: {failed_count}
                """)
    
    else:  # All Products
        products = get_products_for_nutriscore_recalc(db)
        st.write(f"Found **{len(products)}** products with nutrition data.")
        
        st.warning("⚠️ This will recalculate Nutri-Score for all products. This may take several minutes.")
        
        if st.button("Recalculate All Nutri-Scores", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            results_placeholder = st.empty()
            
            success_count = 0
            changed_count = 0
            failed_count = 0
            skipped_count = 0
            
            for i, product in enumerate(products):
                status_text.text(f"Processing {i+1}/{len(products)}: {product['sku']} - {product['name'][:40]}...")
                result = recalculate_nutriscore_for_product_data(db, product)
                
                if result['success']:
                    success_count += 1
                    details = result.get('details', {})
                    old_grade = details.get('old_grade')
                    new_grade = details.get('new_grade')
                    old_score = details.get('old_score')
                    new_score = details.get('new_score')
                    if (old_grade != new_grade) or (str(old_score) != str(new_score)):
                        changed_count += 1
                elif result.get('skipped'):
                    skipped_count += 1
                else:
                    failed_count += 1
                
                progress_bar.progress((i + 1) / len(products))
            
            status_text.text("Recalculation complete!")
            results_placeholder.success(f"""
            **Results:**
            - ✅ Successfully processed: {success_count}
            - 🔄 Score changed: {changed_count}
            - ⏭️ Skipped (no nutrition data): {skipped_count}
            - ❌ Failed: {failed_count}
            """)


def get_products_for_nutriscore_recalc(db: ProductViewDatabase, category_code: str = None):
    """Get products with nutrition data for recalculation."""
    query = """
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            p.category_id,
            nc.barbora_category_code as category_code,
            nf.energy_kj,
            nf.carbs_sugars as sugars,
            nf.fat_saturated as saturated_fat,
            nf.fat_total,
            nf.salt,
            nf.protein,
            nf.fiber,
            nf.ingredients_text,
            nf.nutri_score_grade as current_grade,
            nf.nutri_score_points as current_score
        FROM products p
        JOIN nutritionfacts nf ON p.product_id = nf.product_id
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        WHERE nf.energy_kj IS NOT NULL
          AND nf.carbs_sugars IS NOT NULL
          AND nf.fat_saturated IS NOT NULL
          AND nf.salt IS NOT NULL
          AND nf.protein IS NOT NULL
    """
    
    params = []
    if category_code:
        query += """ AND (nc.barbora_category_code = %s 
            OR nc.category_id IN (
                SELECT c2.category_id FROM normalized_categories c2
                WHERE c2.parent_category_id = (
                    SELECT c3.category_id FROM normalized_categories c3
                    WHERE c3.barbora_category_code = %s
                )
            ))"""
        params.extend([category_code, category_code])
    
    query += " ORDER BY p.sku"
    
    db._ensure_connection()
    with db.connection.cursor() as cur:
        cur.execute(query, params if params else None)
        return [dict(row) for row in cur.fetchall()]


def recalculate_nutriscore_for_product(db: ProductViewDatabase, sku: str):
    """Recalculate Nutri-Score for a single product by SKU."""
    query = """
        SELECT 
            p.product_id,
            p.sku,
            p.name,
            nc.barbora_category_code as category_code,
            nf.energy_kj,
            nf.carbs_sugars as sugars,
            nf.fat_saturated as saturated_fat,
            nf.salt,
            nf.protein,
            nf.fiber,
            nf.nutri_score_grade as current_grade,
            nf.nutri_score_points as current_score
        FROM products p
        LEFT JOIN nutritionfacts nf ON p.product_id = nf.product_id
        LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
        WHERE p.sku = %s
    """
    
    db._ensure_connection()
    with db.connection.cursor() as cur:
        cur.execute(query, (sku,))
        row = cur.fetchone()
        
        if not row:
            return {'success': False, 'message': f'Product with SKU {sku} not found'}
        
        product = dict(row)
        return recalculate_nutriscore_for_product_data(db, product)


def recalculate_nutriscore_for_product_data(db: ProductViewDatabase, product: dict):
    """Recalculate Nutri-Score for a product using its data."""
    from nutriscore_calculator import NutriscoreCalculator
    
    required_fields = ['energy_kj', 'sugars', 'saturated_fat', 'salt', 'protein']
    for field in required_fields:
        if product.get(field) is None:
            return {'success': False, 'skipped': True, 'message': f'Missing required field: {field}'}
    
    db._ensure_connection()
    calculator = NutriscoreCalculator(db.connection)
    
    try:
        fiber_value = product.get('fiber')
        fiber_float = float(fiber_value) if fiber_value is not None else 0.0
        
        total_fat_value = product.get('fat_total')
        total_fat_float = float(total_fat_value) if total_fat_value is not None else None
        
        result = calculator.calculate_single_product(
            energy_kj=float(product['energy_kj']),
            sugars=float(product['sugars']),
            saturated_fat=float(product['saturated_fat']),
            salt=float(product['salt']),
            protein=float(product['protein']),
            fiber=fiber_float,
            total_fat=total_fat_float,
            category_id=product.get('category_id'),
            product_name=product.get('name'),
            ingredients_text=product.get('ingredients_text')
        )
        
        if result['success']:
            new_grade = result['grade']
            new_score = result['score']
            
            update_query = """
                UPDATE nutritionfacts 
                SET nutri_score_grade = %s, nutri_score_points = %s
                WHERE product_id = %s
            """
            
            db._ensure_connection()
            with db.connection.cursor() as cur:
                cur.execute(update_query, (new_grade, new_score, product['product_id']))
                db.connection.commit()
            
            old_grade = product.get('current_grade', 'N/A')
            old_score = product.get('current_score', 'N/A')
            
            return {
                'success': True,
                'message': f"Updated {product['sku']}: {old_grade} ({old_score}) → {new_grade} ({new_score})",
                'details': {
                    'sku': product['sku'],
                    'name': product['name'],
                    'category_id': product.get('category_id'),
                    'old_grade': old_grade,
                    'old_score': old_score,
                    'new_grade': new_grade,
                    'new_score': new_score,
                    'classification': result.get('classification', {})
                }
            }
        else:
            return {'success': False, 'message': result.get('error', 'Calculation failed')}
            
    except Exception as e:
        return {'success': False, 'message': str(e)}


def section_lightweight_update():
    """Section: Lightweight Price/Availability Update"""
    st.header("Lightweight Price Update")
    
    st.info("""
    Fast update of prices and availability from category listing pages (10-50x faster than full scraping).
    - Updates existing products' price, availability, and discount info
    - Detects new products and queues them for full scraping
    - Does NOT update nutrition, ingredients, or photos (use full scraping for that)
    """)
    
    from barbora_lightweight_updater import BarboraLightweightUpdater
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Run Lightweight Update")
        
        limit_categories = st.number_input(
            "Limit categories (0 = all)", 
            min_value=0, max_value=300, value=0,
            help="For testing: limit to first N categories. Set to 0 to process all."
        )
        
        if st.button("Start Lightweight Update", type="primary"):
            from datetime import datetime
            start_time = datetime.now()
            
            updater = BarboraLightweightUpdater(status_callback=lambda msg: None)
            
            categories = updater.get_all_level3_categories()
            if limit_categories > 0:
                categories = categories[:limit_categories]
            
            existing_skus = updater.get_existing_skus()
            
            st.write(f"Processing **{len(categories)}** categories, **{len(existing_skus)}** existing products in DB")
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            stats_placeholder = st.empty()
            
            summary = {
                'start_time': start_time.isoformat(),
                'categories_processed': 0,
                'products_checked': 0,
                'products_updated': 0,
                'price_changes': 0,
                'availability_changes': 0,
                'new_products_found': 0,
                'new_product_jobs_created': 0,
                'errors': []
            }
            
            for i, category in enumerate(categories):
                progress_bar.progress((i + 1) / len(categories))
                status_text.text(f"Processing {category['name_lv']}...")
                
                try:
                    stats = updater.process_category(category, existing_skus)
                    
                    summary['categories_processed'] += 1
                    summary['products_checked'] += stats.get('products_found', 0)
                    summary['products_updated'] += stats.get('updated', 0)
                    summary['price_changes'] += stats.get('price_changes', 0)
                    summary['availability_changes'] += stats.get('availability_changes', 0)
                    summary['new_products_found'] += stats.get('new', 0)
                    
                    if stats.get('new_job_id'):
                        summary['new_product_jobs_created'] += 1
                    
                    if stats.get('errors'):
                        summary['errors'].extend(stats['errors'][:2])
                        
                except Exception as e:
                    summary['errors'].append(f"{category['name_lv']}: {str(e)}")
                
                stats_placeholder.markdown(f"""
                **Progress:** {summary['categories_processed']}/{len(categories)} categories  
                **Products checked:** {summary['products_checked']}  
                **Updated:** {summary['products_updated']} | **Price changes:** {summary['price_changes']} | **Availability changes:** {summary['availability_changes']}  
                **New products:** {summary['new_products_found']} (jobs: {summary['new_product_jobs_created']})
                """)
                
                time.sleep(0.3)
            
            status_text.empty()
            progress_bar.empty()
            
            st.success(f"Completed! Updated {summary['products_updated']} products, found {summary['new_products_found']} new products")
            
            if summary['errors']:
                with st.expander(f"Errors ({len(summary['errors'])})"):
                    for err in summary['errors'][:20]:
                        st.write(f"- {err}")
            
            try:
                end_time = datetime.now()
                summary['end_time'] = end_time.isoformat()
                summary['duration_seconds'] = (end_time - start_time).total_seconds()
                run_id = updater.save_run_history(summary)
                st.info(f"Run saved to history (ID: {run_id}) - Duration: {summary['duration_seconds']:.1f}s")
            except Exception as e:
                st.warning(f"Could not save run history: {e}")
    
    with col2:
        st.subheader("Run History")
        
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor)
            cur = conn.cursor()
            cur.execute("""
                SELECT run_id, started_at, duration_seconds, 
                       categories_processed, products_updated, price_changes,
                       new_products_found, errors_count, status
                FROM lightweight_update_runs
                ORDER BY started_at DESC
                LIMIT 10
            """)
            runs = cur.fetchall()
            conn.close()
            
            if runs:
                for run in runs:
                    started = run['started_at']
                    if started:
                        started_str = started.strftime('%Y-%m-%d %H:%M') if hasattr(started, 'strftime') else str(started)[:16]
                    else:
                        started_str = 'N/A'
                    
                    duration = run['duration_seconds'] or 0
                    st.markdown(f"""
                    **Run #{run['run_id']}** - {started_str}  
                    {run['categories_processed']} cats | {run['products_updated']} updated | {run['price_changes']} price changes | {run['new_products_found']} new
                    """)
            else:
                st.write("No runs yet")
        except Exception as e:
            st.warning(f"Could not load history: {e}")


def section_ingredient_analysis():
    """Combined Ingredient Analysis with AI categorization and NOVA4 suspicion detection"""
    st.header("🧪 Combined Ingredient Analysis")

    if not _ANALYZER_AVAILABLE:
        st.error(
            "AI Analysis is temporarily unavailable due to a package issue on this server. "
            "All other parts of the app work normally.\n\n"
            f"**Technical detail:** `{_ANALYZER_ERROR}`"
        )
        return

    stats = get_analysis_stats()
    if stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Ingredients", stats['total'])
        with col2:
            st.metric("🌿 Natural", stats['natural_count'])
        with col3:
            st.metric("🏭 Processed", stats['processed_count'])
        with col4:
            st.metric("❓ Unanalyzed", stats['unanalyzed'])
        
        st.subheader("Suspicion Levels")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🔴 Avoid", stats['avoid_count'])
        with col2:
            st.metric("🟠 Limit", stats['limit_count'])
        with col3:
            st.metric("🟡 Caution", stats['caution_count'])
        with col4:
            st.metric("✅ Clean", stats['clean_count'])
    else:
        st.warning("Could not load ingredient statistics")
    
    st.divider()
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🧪 Run Test Batch (40 ingredients)", use_container_width=True):
            with st.spinner("Analyzing test batch..."):
                results = run_test_batch(batch_count=1)
                if results:
                    st.session_state.test_results = results
                    st.success(f"Analyzed {len(results)} ingredients")
                else:
                    st.info("No unanalyzed ingredients found")
    
    with col2:
        if st.button("🚀 Run Full Analysis", type="primary", use_container_width=True):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def update_progress(processed, total):
                if total > 0:
                    progress_bar.progress(processed / total)
                    status_text.text(f"Processed {processed}/{total} ingredients")
            
            result = run_full_analysis(progress_callback=update_progress)
            
            progress_bar.empty()
            status_text.empty()
            
            if result.get('error'):
                st.error(result['error'])
            elif result.get('message'):
                st.info(result['message'])
            else:
                st.success(f"Completed! Processed {result.get('processed', 0)} ingredients in {result.get('batches', 0)} batches")
    
    if 'test_results' in st.session_state and st.session_state.test_results:
        st.subheader("Test Results Preview")
        
        for result in st.session_state.test_results[:10]:
            suspicion = result.get('suspicion_level')
            if suspicion == 'avoid':
                icon = "🔴"
            elif suspicion == 'limit':
                icon = "🟠"
            elif suspicion == 'caution':
                icon = "🟡"
            elif suspicion == 'clean':
                icon = "✅"
            else:
                icon = "⚪"
            
            category_icon = "🏭" if result.get('is_processed') else ("🌿" if result.get('is_processed') == False else "❓")
            
            st.markdown(f"""
            {icon} {category_icon} **{result.get('clean_name', 'N/A')}**  
            Category: `{result.get('category')}` | Suspicion: `{suspicion or 'N/A'}` | Type: `{result.get('suspicion_category') or 'N/A'}`  
            {f"_{result.get('health_note')}_" if result.get('health_note') else ''}
            """)
    
    st.divider()
    
    with st.expander("🔧 Advanced Options"):
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🔄 Refresh Materialized View", use_container_width=True):
                with st.spinner("Refreshing view..."):
                    success = refresh_materialized_view()
                    if success:
                        st.success("Materialized view refreshed successfully")
                    else:
                        st.error("Failed to refresh materialized view")
        
        with col2:
            st.warning("Reset will clear all analysis data")
            if st.button("🗑️ Reset All Analysis", type="secondary", use_container_width=True):
                count = reset_all_analysis()
                st.info(f"Reset {count} ingredients for re-analysis")
                st.rerun()
        
        st.info(f"Batch size: {BATCH_SIZE} ingredients per AI call")
        st.caption("Cost: ~$0.005-0.02 per batch using Replit AI Integrations (billed to credits)")


def section_nova_override():
    """Manual NOVA score override tool."""
    st.header("🏷️ NOVA Score Overrides")
    st.caption(
        "Correct wrong NOVA scores by setting a manual override. "
        "Manual overrides survive automatic re-scoring runs. "
        "Removing an override restores the automatic score."
    )

    db = ProductViewDatabase()

    tab_set, tab_list = st.tabs(["✏️ Set Override", "📋 Current Overrides"])

    # ── Tab 1: Search & override ──────────────────────────────────────────────
    with tab_set:
        st.subheader("Find a product")
        query = st.text_input(
            "Search by SKU or product name",
            placeholder="e.g. 12345 or Maize bread",
            key="nova_override_search",
        )

        if query and len(query) >= 2:
            results = db.search_products_for_nova(query)
            if not results:
                st.info("No products found — try a different search term.")
            else:
                st.caption(f"{len(results)} product(s) found (max 30 shown)")

                for prod in results:
                    pid   = prod["product_id"]
                    sku   = prod["sku"]
                    name  = prod["name"] or "(no name)"
                    cur_score  = prod["nova_score"]
                    cur_source = prod["nova_source"] or "—"

                    with st.expander(f"{name}  |  SKU {sku}", expanded=False):
                        col_info, col_form = st.columns([1, 1])

                        with col_info:
                            st.markdown("**Current NOVA score**")
                            if cur_score:
                                st.markdown(render_nova_badge(cur_score), unsafe_allow_html=True)
                                source_label = _NOVA_SOURCE_LABELS.get(cur_source, cur_source)
                                st.caption(f"Source: {source_label}")
                            else:
                                st.write("Not scored yet")

                        with col_form:
                            new_score = st.selectbox(
                                "Set NOVA score",
                                options=[1, 2, 3, 4],
                                index=(cur_score - 1) if cur_score else 3,
                                format_func=lambda s: f"NOVA {s} — {_NOVA_LABELS[s]}",
                                key=f"nova_sel_{pid}",
                            )
                            if st.button(
                                "💾 Save override",
                                key=f"nova_save_{pid}",
                                type="primary",
                            ):
                                db.set_nova_override(pid, new_score)
                                st.success(
                                    f"✓ {name} set to NOVA {new_score} (manual override)"
                                )
                                st.rerun()
        elif query:
            st.caption("Type at least 2 characters to search.")

    # ── Tab 2: List & remove overrides ───────────────────────────────────────
    with tab_list:
        overrides = db.get_nova_overrides()

        if not overrides:
            st.info("No manual overrides set.")
        else:
            st.caption(f"{len(overrides)} manual override(s)")

            for prod in overrides:
                pid  = prod["product_id"]
                sku  = prod["sku"]
                name = prod["name"] or "(no name)"
                score = prod["nova_score"]

                col_name, col_badge, col_btn = st.columns([3, 1, 1])
                with col_name:
                    st.write(f"**{name}**  |  SKU {sku}")
                with col_badge:
                    if score:
                        st.markdown(render_nova_badge(score), unsafe_allow_html=True)
                with col_btn:
                    if st.button("🗑️ Remove", key=f"nova_rm_{pid}"):
                        result = db.remove_nova_override(pid, sku)
                        auto_score = result.get("nova_score")
                        if auto_score:
                            st.success(
                                f"Override removed — auto-assigned NOVA {auto_score} "
                                f"({result.get('nova_source', '')})"
                            )
                        else:
                            st.info("Override removed — no automatic score found for this product.")
                        st.rerun()

    db.close()


def main():
    st.title("🛒 Maxima Product Scraper")
    
    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
    
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
    
    with col3:
        if st.button("🥗 Nutrition Enrichment", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'nutrition_enrichment' else "secondary"):
            st.session_state.view_mode = 'nutrition_enrichment'
            st.rerun()
    
    with col4:
        if st.button("📊 Change Report", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'change_report' else "secondary"):
            st.session_state.view_mode = 'change_report'
            st.rerun()
    
    with col5:
        if st.button("🔄 Nutri-Score", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'nutriscore_recalc' else "secondary"):
            st.session_state.view_mode = 'nutriscore_recalc'
            st.rerun()
    
    with col6:
        if st.button("⚡ Lightweight Update", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'lightweight_update' else "secondary"):
            st.session_state.view_mode = 'lightweight_update'
            st.rerun()
    
    with col7:
        if st.button("🧪 Ingredients AI", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'ingredient_analysis' else "secondary"):
            st.session_state.view_mode = 'ingredient_analysis'
            st.rerun()
    
    st.divider()
    
    if st.session_state.view_mode == 'category_processing':
        section_category_processing()
    elif st.session_state.view_mode == 'product_view':
        section_product_view()
    elif st.session_state.view_mode == 'change_report':
        section_change_report()
    elif st.session_state.view_mode == 'nutriscore_recalc':
        section_nutriscore_recalculation()
    elif st.session_state.view_mode == 'lightweight_update':
        section_lightweight_update()
    elif st.session_state.view_mode == 'ingredient_analysis':
        section_ingredient_analysis()
    else:
        section_nutrition_enrichment()


if __name__ == "__main__":
    main()
