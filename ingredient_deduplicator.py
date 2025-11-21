"""
Ingredient Deduplicator - Tool to find and merge duplicate ingredients
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import re
from typing import List, Dict, Tuple

class IngredientDeduplicator:
    def __init__(self, status_callback=None, existing_connection=None, connection_pool=None):
        self.status_callback = status_callback or print
        
        # Support both old single connection and new connection pool approach
        if connection_pool:
            self.connection_pool = connection_pool
            self.conn = None  # We'll get connections from pool as needed
            self.is_shared_connection = False
            self.status_callback("Deduplicator using thread-safe connection pool")
        elif existing_connection:
            self.conn = existing_connection
            self.connection_pool = None
            self.is_shared_connection = True
            self.status_callback("Deduplicator using shared database connection")
        else:
            # Fallback: create own connection
            self.conn = None
            self.connection_pool = None
            self.is_shared_connection = False
            self._connect()
    
    def _connect(self):
        """Establish database connection (fallback method)"""
        try:
            from database_config import db_config
            db_url = db_config.products_db_url
            self.conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
            self.status_callback("Deduplicator connected to database")
        except Exception as e:
            self.status_callback(f"Database connection failed: {str(e)}")
    
    def _get_connection(self):
        """Get a database connection (from pool or direct)"""
        if self.connection_pool:
            return self.connection_pool.getconn()
        else:
            return self.conn
    
    def _return_connection(self, conn, close_on_error=False):
        """Return connection to pool or do nothing for direct connection"""
        if self.connection_pool:
            self.connection_pool.putconn(conn, close=close_on_error)
        # For direct connections, we don't need to return anything
    
    def _normalize_for_comparison(self, ingredient: str) -> str:
        """Normalize ingredient for comparison - should match the processor normalization"""
        # Use the same normalization as ingredient processor
        try:
            # Remove parenthetical information
            ingredient = re.sub(r'\([^)]*\)', '', ingredient)
            
            # Remove percentages
            ingredient = re.sub(r'\d+%', '', ingredient)
            
            # Remove certification and origin information (case insensitive)
            ingredient = re.sub(r'\.\s*(lauksaimniecība\s+es|lv-bio-\d+|es|eu|organic|bio).*', '', ingredient, flags=re.IGNORECASE)
            ingredient = re.sub(r'\s+(lauksaimniecība\s+es|lv-bio-\d+|es|eu|organic|bio).*', '', ingredient, flags=re.IGNORECASE)
            
            # Remove extra whitespace
            ingredient = re.sub(r'\s+', ' ', ingredient).strip()
            
            # Remove leading/trailing punctuation
            ingredient = ingredient.strip('.,;:')
            
            # Convert to lowercase for consistent matching
            return ingredient.lower()
            
        except Exception as e:
            return ingredient.lower().strip()
    
    def find_duplicate_groups(self) -> List[Dict]:
        """Find groups of ingredients that are likely duplicates"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Get all ingredients
            cursor.execute("SELECT id, ingredient, frequency FROM ingredient_analysis ORDER BY ingredient")
            ingredients = cursor.fetchall()
            cursor.close()
            
            # Group by normalized form
            groups = {}
            for ing in ingredients:
                normalized = self._normalize_for_comparison(ing['ingredient'])
                if normalized not in groups:
                    groups[normalized] = []
                groups[normalized].append(dict(ing))
            
            # Find groups with multiple entries (duplicates)
            duplicates = []
            for normalized, group in groups.items():
                if len(group) > 1:
                    # Sort by frequency (descending) to identify the primary ingredient
                    group.sort(key=lambda x: x['frequency'], reverse=True)
                    duplicates.append({
                        'normalized': normalized,
                        'ingredients': group,
                        'primary': group[0],  # Highest frequency
                        'duplicates': group[1:]  # Others to merge
                    })
            
            self._return_connection(conn)
            return duplicates
            
        except Exception as e:
            if conn:
                self._return_connection(conn, close_on_error=True)
            self.status_callback(f"Error finding duplicates: {str(e)}")
            return []
    
    def merge_duplicate_group(self, group: Dict) -> bool:
        """Merge a group of duplicate ingredients"""
        conn = None
        try:
            conn = self._get_connection()
            # Disable autocommit for transaction handling
            conn.autocommit = False
            
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            primary = group['primary']
            duplicates = group['duplicates']
            
            self.status_callback(f"Merging duplicates into '{primary['ingredient']}' (ID: {primary['id']})")
            
            # Update product mappings to point to primary ingredient
            for dup in duplicates:
                # Use INSERT ... ON CONFLICT to handle duplicate mappings
                cursor.execute("""
                    INSERT INTO ingredient_product_mapping (ingredient_id, product_sku)
                    SELECT %s, product_sku FROM ingredient_product_mapping WHERE ingredient_id = %s
                    ON CONFLICT (ingredient_id, product_sku) DO NOTHING
                """, (primary['id'], dup['id']))
                
                # Delete old mappings
                cursor.execute("""
                    DELETE FROM ingredient_product_mapping WHERE ingredient_id = %s
                """, (dup['id'],))
                
                self.status_callback(f"  Moved mappings from '{dup['ingredient']}' (ID: {dup['id']})")
            
            # Update frequency of primary ingredient
            total_frequency = primary['frequency'] + sum(d['frequency'] for d in duplicates)
            cursor.execute("""
                UPDATE ingredient_analysis 
                SET frequency = %s 
                WHERE id = %s
            """, (total_frequency, primary['id']))
            
            # Delete duplicate ingredients
            duplicate_ids = [d['id'] for d in duplicates]
            cursor.execute("""
                DELETE FROM ingredient_analysis 
                WHERE id = ANY(%s)
            """, (duplicate_ids,))
            
            conn.commit()
            cursor.close()
            
            # Restore autocommit and return connection
            conn.autocommit = True
            self._return_connection(conn)
            
            self.status_callback(f"  Merged {len(duplicates)} duplicates, new frequency: {total_frequency}")
            return True
            
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                    conn.autocommit = True  # Restore autocommit
                    self._return_connection(conn, close_on_error=True)
                except:
                    self._return_connection(conn, close_on_error=True)
            self.status_callback(f"Error merging group: {str(e)}")
            return False
    
    def clean_all_duplicates(self) -> Dict:
        """Find and clean all duplicate ingredients"""
        duplicate_groups = self.find_duplicate_groups()
        
        stats = {
            'groups_found': len(duplicate_groups),
            'groups_merged': 0,
            'ingredients_removed': 0
        }
        
        for group in duplicate_groups:
            if self.merge_duplicate_group(group):
                stats['groups_merged'] += 1
                stats['ingredients_removed'] += len(group['duplicates'])
        
        return stats
    
    def find_ingredient_by_similarity(self, ingredient_name: str) -> int:
        """Find existing ingredient by similarity (for preventing future duplicates)"""
        conn = None
        try:
            normalized_input = self._normalize_for_comparison(ingredient_name)
            
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, ingredient, frequency 
                FROM ingredient_analysis 
                WHERE LOWER(ingredient) = %s
            """, (normalized_input,))
            
            result = cursor.fetchone()
            cursor.close()
            
            if result:
                ingredient_id = result[0]
                self._return_connection(conn)
                return ingredient_id
            
            self._return_connection(conn)
            return None
            
        except Exception as e:
            if conn:
                self._return_connection(conn, close_on_error=True)
            self.status_callback(f"Error finding similar ingredient: {str(e)}")
            return None
    
    def close(self):
        """Close database connection (only if not shared)"""
        if self.conn and not self.is_shared_connection:
            self.conn.close()
            self.status_callback("Deduplicator connection closed")
        elif self.is_shared_connection:
            self.status_callback("Deduplicator using shared connection - not closing")


def run_ingredient_cleanup():
    """Main cleanup function"""
    def status_callback(msg):
        print(f"[CLEANUP] {msg}")
    
    deduplicator = IngredientDeduplicator(status_callback)
    
    print("=== INGREDIENT DEDUPLICATION CLEANUP ===")
    
    # Find and show duplicates
    duplicates = deduplicator.find_duplicate_groups()
    print(f"\nFound {len(duplicates)} duplicate groups:")
    
    for group in duplicates:
        print(f"\nGroup: '{group['normalized']}'")
        print(f"  Primary: {group['primary']['ingredient']} (ID: {group['primary']['id']}, freq: {group['primary']['frequency']})")
        for dup in group['duplicates']:
            print(f"  Duplicate: {dup['ingredient']} (ID: {dup['id']}, freq: {dup['frequency']})")
    
    # Clean up duplicates
    print("\n=== CLEANING UP DUPLICATES ===")
    stats = deduplicator.clean_all_duplicates()
    
    print(f"\nCleanup Results:")
    print(f"  Groups found: {stats['groups_found']}")
    print(f"  Groups merged: {stats['groups_merged']}")
    print(f"  Duplicate ingredients removed: {stats['ingredients_removed']}")
    
    deduplicator.close()
    return stats

if __name__ == "__main__":
    run_ingredient_cleanup()