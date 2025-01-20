from typing import List, Dict, Optional
import logging
from database import Database
from additive_parser import AdditiveParser, Additive

class AdditiveManager:
    def __init__(self, db: Database):
        self.db = db
        self.parser = AdditiveParser()
        
    def process_product_ingredients(self, sku: str, ingredients: str) -> Dict:
        """
        Process ingredients for a product and store found additives
        Returns statistics about the operation
        """
        try:
            # Extract E-numbers from ingredients
            e_numbers = self.parser.extract_e_numbers(ingredients)
            
            stats = {
                'processed': True,
                'product_sku': sku,
                'additives_found': len(e_numbers),
                'additives': e_numbers
            }
            
            # Store in database (implementation needed)
            conn = self.db.get_connection()
            try:
                with conn.cursor() as cur:
                    # Store each additive if it doesn't exist
                    for e_number in e_numbers:
                        # Check if additive exists
                        cur.execute(
                            "INSERT INTO additives (e_number) VALUES (%s) ON CONFLICT (e_number) DO NOTHING",
                            (e_number,)
                        )
                        
                        # Get additive_id
                        cur.execute(
                            "SELECT id FROM additives WHERE e_number = %s",
                            (e_number,)
                        )
                        additive_id = cur.fetchone()[0]
                        
                        # Create relationship
                        cur.execute("""
                            INSERT INTO product_additives (product_sku, additive_id)
                            VALUES (%s, %s)
                            ON CONFLICT (product_sku, additive_id) DO NOTHING
                        """, (sku, additive_id))
                        
            finally:
                self.db.return_connection(conn)
                
            return stats
            
        except Exception as e:
            logging.error(f"Error processing additives for product {sku}: {str(e)}")
            return {
                'processed': False,
                'product_sku': sku,
                'error': str(e)
            }
    
    def get_product_additives(self, sku: str) -> List[Additive]:
        """
        Get all additives for a specific product
        """
        conn = self.db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.* FROM additives a
                    JOIN product_additives pa ON pa.additive_id = a.id
                    WHERE pa.product_sku = %s
                    ORDER BY a.e_number
                """, (sku,))
                rows = cur.fetchall()
                
                return [
                    Additive(
                        e_number=row[1],
                        name=row[2],
                        description=row[3],
                        safety_rating=row[4],
                        source_url=row[5]
                    )
                    for row in rows
                ]
        finally:
            self.db.return_connection(conn)

# Example usage:
# manager = AdditiveManager(db)
# stats = manager.process_product_ingredients("12345", "Contains E-501, E503...")
# additives = manager.get_product_additives("12345")
