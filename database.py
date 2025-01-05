import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
import logging
from decimal import Decimal
from dataclasses import asdict
from scraper import NutritionalInfo
from typing import Optional, Dict
import time
from contextlib import contextmanager
import json

class Database:
    def __init__(self):
        self.pool = None
        self.max_retries = 3
        self.retry_delay = 1  # seconds
        self.connect()
        self.create_tables()

    def connect(self):
        """Establish database connection pool using environment variables"""
        try:
            if self.pool is None:
                self.pool = psycopg2.pool.SimpleConnectionPool(
                    minconn=1,
                    maxconn=10,
                    host=os.getenv('PGHOST'),
                    database=os.getenv('PGDATABASE'),
                    user=os.getenv('PGUSER'),
                    password=os.getenv('PGPASSWORD'),
                    port=os.getenv('PGPORT')
                )
                if self.pool:
                    logging.info("Database connection pool established successfully")
                else:
                    raise Exception("Failed to create connection pool")
        except Exception as e:
            logging.error(f"Database connection error: {str(e)}")
            self.pool = None
            raise

    @contextmanager
    def get_connection(self):
        """Get a connection from the pool with retry logic"""
        conn = None
        try:
            for attempt in range(self.max_retries):
                try:
                    if self.pool is None:
                        self.connect()
                    if self.pool:
                        conn = self.pool.getconn()
                        if conn:
                            conn.autocommit = True
                            yield conn
                            return
                    raise psycopg2.OperationalError("Could not get connection from pool")
                except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                    if attempt < self.max_retries - 1:
                        logging.warning(f"Database connection attempt {attempt + 1} failed: {str(e)}")
                        time.sleep(self.retry_delay)
                        # Force reconnection
                        if self.pool:
                            try:
                                self.pool.closeall()
                            except Exception:
                                pass
                        self.pool = None
                    else:
                        raise
            raise Exception(f"Failed to get database connection after {self.max_retries} attempts")
        except Exception as e:
            logging.error(f"Database connection error: {str(e)}")
            raise
        finally:
            if conn and self.pool:
                try:
                    self.pool.putconn(conn)
                except Exception as e:
                    logging.error(f"Error returning connection to pool: {str(e)}")

    def create_tables(self):
        """Create the required tables if they don't exist"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS products (
                            id SERIAL PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            price DECIMAL(10, 2) NOT NULL,
                            price_per_unit VARCHAR(50),
                            product_url TEXT,
                            image_url TEXT,
                            sku VARCHAR(50) UNIQUE,
                            category TEXT,
                            quantity_value DECIMAL(10,2),
                            quantity_unit VARCHAR(50),
                            country_code VARCHAR(2),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS product_nutrition (
                            id SERIAL PRIMARY KEY,
                            sku VARCHAR(50) UNIQUE REFERENCES products(sku),
                            ingredients TEXT,
                            energy_kj DECIMAL(10,2),
                            energy_kcal DECIMAL(10,2),
                            fat DECIMAL(10,2),
                            saturated_fat DECIMAL(10,2),
                            carbohydrates DECIMAL(10,2),
                            sugars DECIMAL(10,2),
                            protein DECIMAL(10,2),
                            salt DECIMAL(10,2),
                            needs_review BOOLEAN DEFAULT FALSE,
                            review_notes TEXT,
                            serving_size_unit VARCHAR(50),
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS scraping_sessions (
                            id SERIAL PRIMARY KEY,
                            category_url TEXT NOT NULL,
                            total_pages INT NOT NULL,
                            status VARCHAR(50) NOT NULL,
                            products_scraped INT NOT NULL DEFAULT 0,
                            last_page_scraped INT NOT NULL DEFAULT 0,
                            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            end_time TIMESTAMP,
                            error_message TEXT,
                            session_metadata JSONB,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
        except Exception as e:
            logging.error(f"Table creation error: {str(e)}")
            raise

    def save_products(self, products):
        """Save product data to database, updating existing records if needed"""
        try:
            new_products = 0
            updated_products = 0

            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    for product in products:
                        # Check if product exists
                        cur.execute("""
                            SELECT id, name, price, price_per_unit, product_url, image_url, category 
                            FROM products 
                            WHERE sku = %s
                        """, (product.get('sku'),))

                        existing_product = cur.fetchone()

                        if existing_product:
                            # Compare values to see if update is needed
                            current_values = {
                                'name': product['name'],
                                'price': Decimal(str(product['price'])),
                                'price_per_unit': product.get('price_per_unit'),
                                'product_url': product.get('product_url'),
                                'image_url': product.get('image_url'),
                                'category': product.get('category')
                            }

                            db_values = {
                                'name': existing_product[1],
                                'price': existing_product[2],
                                'price_per_unit': existing_product[3],
                                'product_url': existing_product[4],
                                'image_url': existing_product[5],
                                'category': existing_product[6]
                            }

                            if current_values != db_values:
                                # Update existing product if data has changed
                                cur.execute("""
                                    UPDATE products 
                                    SET name = %s, 
                                        price = %s, 
                                        price_per_unit = %s, 
                                        product_url = %s, 
                                        image_url = %s, 
                                        category = %s,
                                        updated_at = CURRENT_TIMESTAMP
                                    WHERE sku = %s
                                """, (
                                    product['name'],
                                    product['price'],
                                    product.get('price_per_unit'),
                                    product.get('product_url'),
                                    product.get('image_url'),
                                    product.get('category'),
                                    product.get('sku')
                                ))
                                updated_products += 1
                        else:
                            # Insert new product
                            cur.execute("""
                                INSERT INTO products 
                                (name, price, price_per_unit, product_url, image_url, sku, category)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """, (
                                product['name'],
                                product['price'],
                                product.get('price_per_unit'),
                                product.get('product_url'),
                                product.get('image_url'),
                                product.get('sku'),
                                product.get('category')
                            ))
                            new_products += 1

            return new_products, updated_products

        except Exception as e:
            logging.error(f"Data insertion error: {str(e)}")
            raise

    def get_products(self):
        """Retrieve all products from database with retry logic"""
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM products ORDER BY updated_at DESC, name")
                    return cur.fetchall()
        except Exception as e:
            logging.error(f"Data retrieval error: {str(e)}")
            raise

    def get_last_update_time(self):
        """Get the most recent updated_at timestamp with retry logic"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT MAX(updated_at) FROM products")
                    result = cur.fetchone()
                    return result[0] if result and result[0] else None
        except Exception as e:
            logging.error(f"Error getting last update time: {str(e)}")
            return None

    def save_product_nutrition(self, sku: str, nutrition: NutritionalInfo) -> None:
        """Save or update nutritional information for a product with retry logic"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if nutrition info exists
                    cur.execute("""
                        SELECT id FROM product_nutrition WHERE sku = %s
                    """, (sku,))

                    exists = cur.fetchone()

                    if exists:
                        # Update existing record
                        cur.execute("""
                            UPDATE product_nutrition
                            SET ingredients = %s,
                                energy_kj = %s,
                                energy_kcal = %s,
                                fat = %s,
                                saturated_fat = %s,
                                carbohydrates = %s,
                                sugars = %s,
                                protein = %s,
                                salt = %s,
                                needs_review = %s,
                                review_notes = %s,
                                serving_size_unit = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE sku = %s
                        """, (
                            nutrition.ingredients,
                            nutrition.energy_kj,
                            nutrition.energy_kcal,
                            nutrition.fat,
                            nutrition.saturated_fat,
                            nutrition.carbohydrates,
                            nutrition.sugars,
                            nutrition.protein,
                            nutrition.salt,
                            nutrition.needs_review,
                            nutrition.review_notes,
                            nutrition.serving_size_unit,
                            sku
                        ))
                    else:
                        # Insert new record
                        cur.execute("""
                            INSERT INTO product_nutrition
                            (sku, ingredients, energy_kj, energy_kcal, fat, saturated_fat,
                            carbohydrates, sugars, protein, salt, needs_review, review_notes,
                            serving_size_unit)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            sku,
                            nutrition.ingredients,
                            nutrition.energy_kj,
                            nutrition.energy_kcal,
                            nutrition.fat,
                            nutrition.saturated_fat,
                            nutrition.carbohydrates,
                            nutrition.sugars,
                            nutrition.protein,
                            nutrition.salt,
                            nutrition.needs_review,
                            nutrition.review_notes,
                            nutrition.serving_size_unit
                        ))

        except Exception as e:
            logging.error(f"Error saving nutrition data: {str(e)}")
            raise

    def save_products_with_nutrition(self, products_with_nutrition):
        """Save both product and nutrition data"""
        try:
            new_products = 0
            updated_products = 0
            new_nutrition = 0
            updated_nutrition = 0
            needs_review = 0

            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    for item in products_with_nutrition:
                        product = item['product']
                        nutrition = item['nutrition']

                        # Extra logging for problematic SKUs
                        is_problematic = product.get('sku') in ['2000324', '2000330', '2000511']
                        if is_problematic:
                            logging.info(f"\n=== Processing problematic SKU: {product.get('sku')} ===")
                            logging.info(f"Input product data: {product}")

                        # Save product first
                        cur.execute("""
                            SELECT name, price, price_per_unit, product_url, image_url, 
                                   category, quantity_value, quantity_unit, country_code 
                            FROM products 
                            WHERE sku = %s
                        """, (product.get('sku'),))

                        existing = cur.fetchone()
                        if existing:
                            db_values = {
                                'name': existing[0],
                                'price': existing[1],
                                'price_per_unit': existing[2],
                                'product_url': existing[3],
                                'image_url': existing[4],
                                'category': existing[5],
                                'quantity_value': existing[6],
                                'quantity_unit': existing[7],
                                'country_code': existing[8]
                            }

                            current_values = {
                                'name': product['name'],
                                'price': Decimal(str(product['price'])),
                                'price_per_unit': product.get('price_per_unit'),
                                'product_url': product.get('product_url'),
                                'image_url': product.get('image_url'),
                                'category': product.get('category'),
                                'quantity_value': product.get('quantity_value'),
                                'quantity_unit': product.get('quantity_unit'),
                                'country_code': product.get('country_code')
                            }

                            # Force update if quantity or country fields are NULL in database
                            should_update = (current_values != db_values or 
                                               db_values['quantity_value'] is None or 
                                               db_values['quantity_unit'] is None or 
                                               db_values['country_code'] is None)

                            if is_problematic:
                                logging.info(f"Database values: {db_values}")
                                logging.info(f"Current values: {current_values}")
                                logging.info(f"Should update: {should_update}")

                            if should_update:
                                # Update existing product if data has changed
                                cur.execute("""
                                    UPDATE products 
                                    SET name = %s, 
                                        price = %s, 
                                        price_per_unit = %s, 
                                        product_url = %s, 
                                        image_url = %s, 
                                        category = %s,
                                        quantity_value = %s,
                                        quantity_unit = %s,
                                        country_code = %s,
                                        updated_at = CURRENT_TIMESTAMP
                                    WHERE sku = %s
                                """, (
                                    product['name'],
                                    product['price'],
                                    product.get('price_per_unit'),
                                    product.get('product_url'),
                                    product.get('image_url'),
                                    product.get('category'),
                                    product.get('quantity_value'),
                                    product.get('quantity_unit'),
                                    product.get('country_code'),
                                    product.get('sku')
                                ))
                                if is_problematic:
                                    logging.info(f"Updated problematic SKU: {product.get('sku')}")
                                updated_products += 1
                        else:
                            # Insert new product
                            cur.execute("""
                                INSERT INTO products 
                                (name, price, price_per_unit, product_url, image_url, sku, category,
                                 quantity_value, quantity_unit, country_code)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                product['name'],
                                product['price'],
                                product.get('price_per_unit'),
                                product.get('product_url'),
                                product.get('image_url'),
                                product.get('sku'),
                                product.get('category'),
                                product.get('quantity_value'),
                                product.get('quantity_unit'),
                                product.get('country_code')
                            ))
                            new_products += 1

                        # Save nutrition data
                        cur.execute("""
                            SELECT id FROM product_nutrition WHERE sku = %s
                        """, (product.get('sku'),))

                        if nutrition.needs_review:
                            needs_review += 1

                        if cur.fetchone():
                            self.save_product_nutrition(product.get('sku'), nutrition)
                            updated_nutrition += 1
                        else:
                            self.save_product_nutrition(product.get('sku'), nutrition)
                            new_nutrition += 1

            return {
                'new_products': new_products,
                'updated_products': updated_products,
                'new_nutrition': new_nutrition,
                'updated_nutrition': updated_nutrition,
                'needs_review': needs_review
            }

        except Exception as e:
            logging.error(f"Error saving products with nutrition: {str(e)}")
            raise

    def get_product_nutrition(self, sku: str) -> Optional[Dict]:
        """Retrieve nutritional information for a specific product"""
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT n.*, p.name as product_name, p.category
                        FROM product_nutrition n
                        JOIN products p ON p.sku = n.sku
                        WHERE n.sku = %s
                    """, (sku,))
                    return cur.fetchone()
        except Exception as e:
            logging.error(f"Error retrieving nutrition data: {str(e)}")
            raise

    def get_products_needing_review(self):
        """Retrieve all products that need nutrition data review"""
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT p.name, p.sku, p.category, n.review_notes, n.serving_size_unit
                        FROM products p
                        JOIN product_nutrition n ON p.sku = n.sku
                        WHERE n.needs_review = true
                        ORDER BY p.category, p.name
                    """)
                    return cur.fetchall()
        except Exception as e:
            logging.error(f"Error retrieving products needing review: {str(e)}")
            raise

    def create_scraping_session(self, category_url: str, total_pages: int) -> int:
        """Create a new scraping session and return its ID"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO scraping_sessions
                        (category_url, total_pages, status, products_scraped, last_page_scraped)
                        VALUES (%s, %s, 'started', 0, 0)
                        RETURNING id
                    """, (category_url, total_pages))
                    session_id = cur.fetchone()[0]
                    return session_id
        except Exception as e:
            logging.error(f"Error creating scraping session: {str(e)}")
            raise

    def update_scraping_progress(self, session_id: int, page: int, products_count: int, 
                               status: str = 'in_progress', error_message: str = None,
                               metadata: dict = None) -> None:
        """Update the progress of a scraping session"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    end_time = 'CURRENT_TIMESTAMP' if status in ['completed', 'failed'] else 'NULL'
                    cur.execute(f"""
                        UPDATE scraping_sessions
                        SET last_page_scraped = %s,
                            products_scraped = %s,
                            status = %s,
                            error_message = %s,
                            session_metadata = %s,
                            end_time = {end_time},
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (page, products_count, status, error_message, 
                          json.dumps(metadata) if metadata else None, session_id))
        except Exception as e:
            logging.error(f"Error updating scraping progress: {str(e)}")
            raise

    def get_last_successful_page(self, category_url: str) -> int:
        """Get the last successfully scraped page for a category"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT last_page_scraped
                        FROM scraping_sessions
                        WHERE category_url = %s
                        AND status IN ('completed', 'in_progress')
                        ORDER BY updated_at DESC
                        LIMIT 1
                    """, (category_url,))
                    result = cur.fetchone()
                    return result[0] if result else 0
        except Exception as e:
            logging.error(f"Error getting last successful page: {str(e)}")
            return 0

    def get_scraped_products_skus(self, category_url: str) -> set:
        """Get SKUs of products that were already scraped in the last successful session"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT p.sku
                        FROM products p
                        JOIN scraping_sessions s ON s.category_url = %s
                        WHERE s.status IN ('completed', 'in_progress')
                        AND p.created_at >= s.start_time
                        AND s.id = (
                            SELECT id
                            FROM scraping_sessions
                            WHERE category_url = %s
                            AND status IN ('completed', 'in_progress')
                            ORDER BY updated_at DESC
                            LIMIT 1
                        )
                    """, (category_url, category_url))
                    return {row[0] for row in cur.fetchall()}
        except Exception as e:
            logging.error(f"Error getting scraped products: {str(e)}")
            return set()

    def __del__(self):
        """Close all database connections"""
        if self.pool:
            try:
                self.pool.closeall()
                logging.info("Database connections closed")
            except Exception as e:
                logging.error(f"Error closing database connections: {str(e)}")