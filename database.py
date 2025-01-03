import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from decimal import Decimal

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
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

    def __del__(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()