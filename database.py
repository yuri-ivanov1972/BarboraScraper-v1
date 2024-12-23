import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

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
            with self.conn.cursor() as cur:
                # Drop and recreate the table to add the image_url column
                cur.execute("""
                    DROP TABLE IF EXISTS products;
                    CREATE TABLE products (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        price DECIMAL(10, 2) NOT NULL,
                        price_per_unit VARCHAR(50),
                        product_url TEXT,
                        image_url TEXT,
                        sku VARCHAR(50),
                        category TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
        except Exception as e:
            logging.error(f"Table creation error: {str(e)}")
            raise

    def save_products(self, products):
        """Save product data to database"""
        try:
            with self.conn.cursor() as cur:
                # Clear existing data
                cur.execute("TRUNCATE TABLE products")

                # Insert new data
                for product in products:
                    cur.execute("""
                        INSERT INTO products (name, price, price_per_unit, product_url, image_url, sku, category)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        product['name'],
                        product['price'],
                        product.get('price_per_unit'),
                        product.get('product_url'),
                        product.get('image_url'),  # Add image_url field
                        product.get('sku'),
                        product.get('category')
                    ))
        except Exception as e:
            logging.error(f"Data insertion error: {str(e)}")
            raise

    def get_products(self):
        """Retrieve all products from database"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM products ORDER BY name")
                return cur.fetchall()
        except Exception as e:
            logging.error(f"Data retrieval error: {str(e)}")
            raise

    def __del__(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()