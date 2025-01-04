import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from decimal import Decimal
from dataclasses import asdict
from scraper import NutritionalInfo
from typing import Optional, Dict

class Database:
    def __init__(self):
        self.conn = None
        self.connect()
        self.create_tables()

    def connect(self):
        """Establish database connection using environment variables"""
        try:
            self.conn = psycopg2.connect(
                host=os.getenv('PGHOST'),
                database=os.getenv('PGDATABASE'),
                user=os.getenv('PGUSER'),
                password=os.getenv('PGPASSWORD'),
                port=os.getenv('PGPORT')
            )
            self.conn.autocommit = True
        except Exception as e:
            logging.error(f"Database connection error: {str(e)}")
            raise

    def create_tables(self):
        """Create the required tables if they don't exist"""
        try:             
            if self.conn:  # Check if the connection is established
                with self.conn.cursor() as cur:
                    # Create table if it doesn't exist
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

            else:
                logging.error("Database connection is not established.")
                raise Exception("Database connection error")        
        except Exception as e:
            logging.error(f"Table creation error: {str(e)}")
            raise

    def save_products(self, products):
        """Save product data to database, updating existing records if needed"""
        try:
            if not self.conn:
                raise Exception("Database connection is not established.")

            new_products = 0
            updated_products = 0

            with self.conn.cursor() as cur:
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
        """Retrieve all products from database"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM products ORDER BY updated_at DESC, name")
                return cur.fetchall()
        except Exception as e:
            logging.error(f"Data retrieval error: {str(e)}")
            raise

    def get_last_update_time(self):
        """Get the most recent updated_at timestamp"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT MAX(updated_at) FROM products")
                result = cur.fetchone()
                return result[0] if result and result[0] else None
        except Exception as e:
            logging.error(f"Error getting last update time: {str(e)}")
            return None

    def save_product_nutrition(self, sku: str, nutrition: NutritionalInfo) -> None:
        """Save or update nutritional information for a product"""
        try:
            if not self.conn:
                raise Exception("Database connection is not established")

            with self.conn.cursor() as cur:
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
            if not self.conn:
                raise Exception("Database connection is not established")

            new_products = 0
            updated_products = 0
            new_nutrition = 0
            updated_nutrition = 0
            needs_review = 0

            with self.conn.cursor() as cur:
                for item in products_with_nutrition:
                    product = item['product']
                    nutrition = item['nutrition']

                    # Save product first
                    cur.execute("""
                        SELECT id FROM products WHERE sku = %s
                    """, (product.get('sku'),))

                    if cur.fetchone():
                        # Update existing product
                        # Compare values to see if update is needed
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

                            # Force update if quantity or country fields are NULL in database
                            should_update = (current_values != db_values or 
                                              db_values['quantity_value'] is None or 
                                              db_values['quantity_unit'] is None or 
                                              db_values['country_code'] is None)

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
                                logging.info(f"Updated product {product['name']} (SKU: {product.get('sku')})")
                                logging.info(f"Old values: {db_values}")
                                logging.info(f"New values: {current_values}")
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
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
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
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
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

    def __del__(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()