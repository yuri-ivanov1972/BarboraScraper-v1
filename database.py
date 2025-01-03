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
            if self.conn:  # Check if the connection is established
                with self.conn.cursor() as cur:
                    # Create table if it doesn't exist (removed DROP TABLE)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS products (
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
            else:
                logging.error("Database connection is not established.")
                raise Exception("Database connection error")        
        except Exception as e:
            logging.error(f"Table creation error: {str(e)}")
            raise

    def save_products(self, products):
        """Save product data to database"""
        try:
            if self.conn:  # Check if the connection is established
                with self.conn.cursor() as cur:
                    # Insert new data without clearing existing data
                    for product in products:
                        cur.execute("""
                            INSERT INTO products (name, price, price_per_unit, product_url, image_url, sku, category)
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
            else:
                logging.error("Database connection is not established.")
                raise Exception("Database connection error")        
        except Exception as e:
            logging.error(f"Data insertion error: {str(e)}")
            raise

    def get_products(self):
        """Retrieve all products from database"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM products ORDER BY created_at DESC, name")
                return cur.fetchall()
        except Exception as e:
            logging.error(f"Data retrieval error: {str(e)}")
            raise

    def get_last_update_time(self):
        """Get the most recent created_at timestamp"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT MAX(created_at) FROM products")
                result = cur.fetchone()
                return result[0] if result and result[0] else None
        except Exception as e:
            logging.error(f"Error getting last update time: {str(e)}")
            return None

    def __del__(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()