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

from typing import Dict, List, Tuple, Any, Optional
import json

# Category mappings for product classification
FAT_CATEGORIES = {
    'SH-2-4-1', 'SH-2-4-2', 'SH-2-4-3', 'SH-2-4-4', 'SH-2-4-5',
    'SH-2-4-6', 'SH-2-4-7', 'SH-2-4-8', 'SH-2-4-9', 'SH-2-4-10'
}

CHEESE_CATEGORIES = {
    'SH-2-3-1', 'SH-2-3-2', 'SH-2-3-3', 'SH-2-3-4', 'SH-2-3-5',
    'SH-2-3-6', 'SH-2-3-7', 'SH-2-3-8', 'SH-2-3-9', 'SH-2-3-10'
}

FULL_FVN_CATEGORIES = {
    'SH-1-1', 'SH-1-2', 'SH-1-3', 'SH-1-4', 'SH-1-5',
    'SH-1-6', 'SH-1-7', 'SH-1-8', 'SH-1-9', 'SH-1-10'
}

HALF_FVN_CATEGORIES = {
    'SH-1-11', 'SH-1-12', 'SH-1-13', 'SH-1-14', 'SH-1-15'
}


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
    
    def calculate_single_product(self, energy_kj: float, sugars: float, 
                               saturated_fat: float, salt: float, protein: float,
                               fiber: int = 0, fruits_veg_nuts: int = 0,
                               category_code: Optional[str] = None) -> Dict[str, Any]:
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
            category_code: Product category code (optional)
        
        Returns:
            Dictionary with score, grade, and detailed breakdown
        """
        try:
            # Convert salt to sodium
            sodium = convert_salt_to_sodium(salt)
            
            # Determine product classification
            is_beverage = category_code and category_code.startswith('SH-5') if category_code else False
            is_fat = category_code in self.fat_categories if category_code else False
            is_cheese = category_code in self.cheese_categories if category_code else False
            
            # Adjust fruits/vegetables/nuts percentage based on category
            if category_code in self.full_fvn_categories:
                fruits_veg_nuts = 100
            elif category_code in self.half_fvn_categories:
                fruits_veg_nuts = 50
            
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