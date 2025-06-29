"""
Ingredient Deduplicator - Tool to find and merge duplicate ingredients
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import re
from typing import List, Dict, Tuple

class IngredientDeduplicator:
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or print
        self.conn = None
        self._connect()
    
    def _connect(self):
        """Establish database connection"""
        try:
            db_url = os.getenv('PRODUCTS_DB_URL')
            self.conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
            self.status_callback("Deduplicator connected to database")
        except Exception as e:
            self.status_callback(f"Database connection failed: {str(e)}")
    
    def _normalize_for_comparison(self, ingredient: str) -> str:
        """Normalize ingredient for comparison"""
        # Convert to lowercase
        normalized = ingredient.lower().strip()
        
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Remove common punctuation variations
        normalized = re.sub(r'[.,;:!?]$', '', normalized)
        
        return normalized
    
    def find_duplicate_groups(self) -> List[Dict]:
        """Find groups of ingredients that are likely duplicates"""
        try:
            cursor = self.conn.cursor()
            
            # Get all ingredients
            cursor.execute("SELECT id, ingredient, frequency FROM ingredient_analysis ORDER BY ingredient")
            ingredients = cursor.fetchall()
            
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
            
            cursor.close()
            return duplicates
            
        except Exception as e:
            self.status_callback(f"Error finding duplicates: {str(e)}")
            return []
    
    def merge_duplicate_group(self, group: Dict) -> bool:
        """Merge a group of duplicate ingredients"""
        try:
            cursor = self.conn.cursor()
            
            primary = group['primary']
            duplicates = group['duplicates']
            
            self.status_callback(f"Merging duplicates into '{primary['ingredient']}' (ID: {primary['id']})")
            
            # Update product mappings to point to primary ingredient
            for dup in duplicates:
                cursor.execute("""
                    UPDATE ingredient_product_mapping 
                    SET ingredient_id = %s 
                    WHERE ingredient_id = %s
                """, (primary['id'], dup['id']))
                
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
            
            self.conn.commit()
            
            self.status_callback(f"  Merged {len(duplicates)} duplicates, new frequency: {total_frequency}")
            return True
            
        except Exception as e:
            self.conn.rollback()
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
        try:
            normalized_input = self._normalize_for_comparison(ingredient_name)
            
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT id, ingredient, frequency 
                FROM ingredient_analysis 
                WHERE LOWER(ingredient) = %s
            """, (normalized_input,))
            
            result = cursor.fetchone()
            cursor.close()
            
            if result:
                return result['id']
            
            return None
            
        except Exception as e:
            self.status_callback(f"Error finding similar ingredient: {str(e)}")
            return None
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.status_callback("Deduplicator connection closed")


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