"""
Standalone Nutriscore Calculator Module
Can be imported and used by other Replit applications for nutrition score calculations.

Usage:
    from nutriscore_calculator import NutriscoreCalculator
    
    calculator = NutriscoreCalculator()
    result = calculator.calculate_single_product(
        energy_kj=1500,
        sugars=10.5,
        saturated_fat=3.2,
        salt=1.8,
        protein=12.0,
        fiber=5,
        category_code="SH-2-1-1"
    )
    print(f"Nutriscore: {result['grade']} (Score: {result['score']})")
"""

from typing import Dict, Tuple, Any, Optional

# Category mappings for product classification
FAT_CATEGORIES = {
    'SH-11-7-16',  # Margarines
    'SH-11-7-17',  # Butter
    'SH-11-7-18',  # Butter with additives
    'SH-11-7-19',  # Fat mixtures
    'SH-4-3-14',   # Coconut oil
    'SH-4-3-15',   # Olive oil
    'SH-4-3-16',   # Rapeseed oil
    'SH-4-3-17',   # Sunflower oil
    'SH-4-3-18'    # Special and other oils
}

CHEESE_CATEGORIES = {
    'SH-11-9-25',  # Hard cheese
    'SH-11-9-26',  # Fermented cheese
    'SH-11-9-27',  # Feta, Mozzarella cheese
    'SH-11-9-28',  # Processed cheese
    'SH-11-9-29',  # Goat, sheep cheese
    'SH-11-9-30',  # Cream cheese
    'SH-11-9-31',  # Other cheese
    'SH-11-9-32'   # Blue cheese
}

FULL_FVN_CATEGORIES = {
    'SH-12-4-10',  # Frozen fruits and berries
    'SH-12-4-11',  # Frozen vegetables and mixtures
    'SH-12-4-12',  # Frozen potatoes
    'SH-13-9-17',  # Nuts and dried fruits - Others
    'SH-13-9-18',  # Nuts and dried fruits - Nuts
    'SH-13-9-20',  # Nuts and dried fruits - Seeds
    'SH-13-9-21',  # Nuts and dried fruits - Dried fruits and berries
    'SH-13-9-23',  # Nuts and dried fruits - Dried fruit and nut mixes
    'SH-2-1-2',    # Fruits - Apples and pears
    'SH-2-1-3',    # Fruits - Bananas
    'SH-2-1-4',    # Fruits - Citrus fruits
    'SH-2-1-5',    # Fruits - Exotic fruits
    'SH-2-1-6',    # Fruits - Melons and watermelons
    'SH-2-1-7',    # Fruits - Stone fruits
    'SH-2-1-9',    # Fruits - Berries
    'SH-2-2',      # Vegetables
    'SH-2-2-10',   # Vegetables - Beets and other root vegetables
    'SH-2-2-12',   # Vegetables - Cucumbers and tomatoes
    'SH-2-2-13',   # Vegetables - Potatoes and carrots
    'SH-2-2-14',   # Vegetables - Legumes, corn and asparagus
    'SH-2-2-16',   # Vegetables - Peppers
    'SH-2-2-17',   # Vegetables - Processed vegetables
    'SH-2-2-18',   # Vegetables - Cabbage and lettuce
    'SH-2-2-19',   # Vegetables - Onions, leeks and garlic
    'SH-2-2-20',   # Vegetables - Herbs
    'SH-2-2-9'     # Vegetables - Pumpkins and squash
}

HALF_FVN_CATEGORIES = {
    'SH-4-10-55',  # Canned products - Other canned vegetables
    'SH-4-10-57',  # Canned products - Canned corn
    'SH-4-10-58',  # Canned products - Canned peppers
    'SH-4-10-59',  # Canned products - Canned beets
    'SH-4-10-60',  # Canned products - Canned olives
    'SH-4-10-62',  # Canned products - Canned fruits and berries
    'SH-4-10-63',  # Canned products - Canned purees
    'SH-4-10-65',  # Canned products - Canned cucumbers
    'SH-4-10-66',  # Canned products - Canned legumes
    'SH-4-10-67',  # Canned products - Canned tomatoes
    'SH-4-10-68',  # Canned products - Canned peas
    'SH-4-12-85'   # Sauces - Tomato sauces and pastes
}

BARBORA_FAT_CATEGORIES: set[int] = set()
BARBORA_CHEESE_CATEGORIES: set[int] = set()
BARBORA_FULL_FVN_CATEGORIES: set[int] = set()
BARBORA_HALF_FVN_CATEGORIES: set[int] = set()
BARBORA_BEVERAGE_CATEGORIES: set[int] = set()


def convert_salt_to_sodium(salt: float) -> float:
    """Convert salt (g) to sodium (mg)"""
    return salt * 400


def calculate_nutriscore(energy_kj: float, sugars: float, saturated_fat: float, 
                        sodium: float, protein: float, fiber: int = 0, 
                        fruits_veg_nuts: int = 0, is_beverage: bool = False, 
                        is_fat: bool = False, is_cheese: bool = False) -> Tuple[int, str, Dict[str, int]]:
    """
    Calculate Nutri-Score for a food product.

    Parameters:
    - energy_kj: Energy in kJ/100g
    - sugars: Sugars in g/100g
    - saturated_fat: Saturated fat in g/100g
    - sodium: Sodium in mg/100g (calculated from salt by multiplying by 400)
    - protein: Protein in g/100g
    - fiber: Fiber in g/100g (optional)
    - fruits_veg_nuts: Percentage of fruits, vegetables, nuts (optional)
    - is_beverage: Boolean, True if product is a beverage
    - is_fat: Boolean, True if product is added fat (oils, butter, etc.)
    - is_cheese: Boolean, True if product is cheese (special protein calculation)

    Returns:
    - tuple: (numeric_score, letter_grade, component_scores)
    """
    
    # Energy points (kJ/100g)
    if energy_kj <= 335:
        energy_points = 0
    elif energy_kj <= 670:
        energy_points = 1
    elif energy_kj <= 1005:
        energy_points = 2
    elif energy_kj <= 1340:
        energy_points = 3
    elif energy_kj <= 1675:
        energy_points = 4
    elif energy_kj <= 2010:
        energy_points = 5
    elif energy_kj <= 2345:
        energy_points = 6
    elif energy_kj <= 2680:
        energy_points = 7
    elif energy_kj <= 3015:
        energy_points = 8
    elif energy_kj <= 3350:
        energy_points = 9
    else:
        energy_points = 10
    
    # Sugars points (g/100g)
    if sugars <= 4.5:
        sugars_points = 0
    elif sugars <= 9:
        sugars_points = 1
    elif sugars <= 13.5:
        sugars_points = 2
    elif sugars <= 18:
        sugars_points = 3
    elif sugars <= 22.5:
        sugars_points = 4
    elif sugars <= 27:
        sugars_points = 5
    elif sugars <= 31:
        sugars_points = 6
    elif sugars <= 36:
        sugars_points = 7
    elif sugars <= 40:
        sugars_points = 8
    elif sugars <= 45:
        sugars_points = 9
    else:
        sugars_points = 10
    
    # Saturated fat points (g/100g)
    if saturated_fat <= 1:
        saturated_fat_points = 0
    elif saturated_fat <= 2:
        saturated_fat_points = 1
    elif saturated_fat <= 3:
        saturated_fat_points = 2
    elif saturated_fat <= 4:
        saturated_fat_points = 3
    elif saturated_fat <= 5:
        saturated_fat_points = 4
    elif saturated_fat <= 6:
        saturated_fat_points = 5
    elif saturated_fat <= 7:
        saturated_fat_points = 6
    elif saturated_fat <= 8:
        saturated_fat_points = 7
    elif saturated_fat <= 9:
        saturated_fat_points = 8
    elif saturated_fat <= 10:
        saturated_fat_points = 9
    else:
        saturated_fat_points = 10
    
    # Sodium points (mg/100g)
    if sodium <= 90:
        sodium_points = 0
    elif sodium <= 180:
        sodium_points = 1
    elif sodium <= 270:
        sodium_points = 2
    elif sodium <= 360:
        sodium_points = 3
    elif sodium <= 450:
        sodium_points = 4
    elif sodium <= 540:
        sodium_points = 5
    elif sodium <= 630:
        sodium_points = 6
    elif sodium <= 720:
        sodium_points = 7
    elif sodium <= 810:
        sodium_points = 8
    elif sodium <= 900:
        sodium_points = 9
    else:
        sodium_points = 10
    
    # Fiber points (g/100g)
    if fiber <= 0.9:
        fiber_points = 0
    elif fiber <= 1.9:
        fiber_points = 1
    elif fiber <= 2.8:
        fiber_points = 2
    elif fiber <= 3.7:
        fiber_points = 3
    elif fiber <= 4.7:
        fiber_points = 4
    else:
        fiber_points = 5
    
    # Protein points (g/100g)
    if protein <= 1.6:
        protein_points = 0
    elif protein <= 3.2:
        protein_points = 1
    elif protein <= 4.8:
        protein_points = 2
    elif protein <= 6.4:
        protein_points = 3
    elif protein <= 8.0:
        protein_points = 4
    else:
        protein_points = 5
    
    # Fruits, vegetables, nuts points (%)
    if fruits_veg_nuts <= 40:
        fvn_points = 0
    elif fruits_veg_nuts <= 60:
        fvn_points = 1
    elif fruits_veg_nuts <= 80:
        fvn_points = 2
    else:
        fvn_points = 5
    
    # Calculate total negative and positive points
    negative_points = energy_points + sugars_points + saturated_fat_points + sodium_points
    positive_points = fiber_points + protein_points + fvn_points
    
    # Special rules for different product types
    if is_beverage:
        # For beverages, only water and fiber count as positive points
        positive_points = fiber_points
        # Different thresholds for beverages
        final_score = negative_points - positive_points
        
        if final_score <= 1:
            grade = 'B'
        elif final_score <= 5:
            grade = 'C'
        elif final_score <= 9:
            grade = 'D'
        else:
            grade = 'E'
    else:
        # For regular foods
        if is_fat or is_cheese:
            # For fats and cheese, protein points are only awarded if negative points are >= 11
            if negative_points < 11:
                positive_points = fiber_points + fvn_points
            else:
                positive_points = fiber_points + protein_points + fvn_points
        
        final_score = negative_points - positive_points
        
        # Determine grade based on final score
        if final_score <= -1:
            grade = 'A'
        elif final_score <= 2:
            grade = 'B'
        elif final_score <= 10:
            grade = 'C'
        elif final_score <= 18:
            grade = 'D'
        else:
            grade = 'E'
    
    # Component breakdown for debugging
    components = {
        'negative_points': negative_points,
        'positive_points': positive_points,
        'energy_points': energy_points,
        'sugars_points': sugars_points,
        'saturated_fat_points': saturated_fat_points,
        'sodium_points': sodium_points,
        'protein_points': protein_points,
        'fiber_points': fiber_points,
        'fvn_points': fvn_points
    }
    
    return final_score, grade, components


class NutriscoreCalculator:
    """
    Standalone calculator for Nutri-Score calculations.
    Can be used by other Replit applications.
    """
    
    def __init__(self):
        self.fat_categories = FAT_CATEGORIES
        self.cheese_categories = CHEESE_CATEGORIES
        self.full_fvn_categories = FULL_FVN_CATEGORIES
        self.half_fvn_categories = HALF_FVN_CATEGORIES
        self.barbora_fat_categories = BARBORA_FAT_CATEGORIES
        self.barbora_cheese_categories = BARBORA_CHEESE_CATEGORIES
        self.barbora_full_fvn_categories = BARBORA_FULL_FVN_CATEGORIES
        self.barbora_half_fvn_categories = BARBORA_HALF_FVN_CATEGORIES
        self.barbora_beverage_categories = BARBORA_BEVERAGE_CATEGORIES
    
    def calculate_single_product(self, energy_kj: float, sugars: float, 
                               saturated_fat: float, salt: float, protein: float,
                               fiber: float = 0, fruits_veg_nuts: int = 0,
                               category_code: Optional[str] = None,
                               category_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Calculate nutriscore for a single product.
        
        Args:
            energy_kj: Energy in kJ/100g
            sugars: Sugars in g/100g
            saturated_fat: Saturated fat in g/100g
            salt: Salt in g/100g (will be converted to sodium)
            protein: Protein in g/100g
            fiber: Fiber in g/100g (optional, default: 0)
            fruits_veg_nuts: % fruits/vegetables/nuts (optional, default: 0)
            category_code: Product category code for Rimi (optional, string like 'SH-x-x-x')
            category_id: Product category ID for Barbora (optional, integer)
        
        Returns:
            Dictionary with score, grade, and detailed breakdown
        """
        try:
            # Convert salt to sodium
            sodium = convert_salt_to_sodium(salt)
            
            # Determine product classification - check Barbora category_id first, then Rimi category_code
            if category_id is not None:
                is_beverage = category_id in self.barbora_beverage_categories
                is_fat = category_id in self.barbora_fat_categories
                is_cheese = category_id in self.barbora_cheese_categories
                if category_id in self.barbora_full_fvn_categories:
                    fruits_veg_nuts = 100
                elif category_id in self.barbora_half_fvn_categories:
                    fruits_veg_nuts = 50
            elif category_code:
                is_beverage = category_code.startswith('SH-5')
                is_fat = category_code in self.fat_categories
                is_cheese = category_code in self.cheese_categories
                if category_code in self.full_fvn_categories:
                    fruits_veg_nuts = 100
                elif category_code in self.half_fvn_categories:
                    fruits_veg_nuts = 50
            else:
                is_beverage = False
                is_fat = False
                is_cheese = False
            
            # Calculate nutriscore
            score, grade, components = calculate_nutriscore(
                energy_kj=energy_kj,
                sugars=sugars,
                saturated_fat=saturated_fat,
                sodium=sodium,
                protein=protein,
                fiber=fiber,
                fruits_veg_nuts=fruits_veg_nuts,
                is_beverage=is_beverage,
                is_fat=is_fat,
                is_cheese=is_cheese
            )
            
            return {
                'success': True,
                'score': score,
                'grade': grade,
                'components': components,
                'classification': {
                    'is_beverage': is_beverage,
                    'is_fat': is_fat,
                    'is_cheese': is_cheese,
                    'fruits_veg_nuts_percent': fruits_veg_nuts
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }