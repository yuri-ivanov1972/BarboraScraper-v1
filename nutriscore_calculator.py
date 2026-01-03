"""
Standalone Nutriscore Calculator Module for Barbora products.

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
        category_id=309
    )
    print(f"Nutriscore: {result['grade']} (Score: {result['score']})")
"""

from typing import Dict, Tuple, Any, Optional

FAT_CATEGORIES: set[int] = {
    26,   # Citas eļļas
    28,   # Olīveļļa
    29,   # Rapšu eļļa
    30,   # Saulespuķu eļļa
    323,  # Sviests, margarīns un tauki
    324,  # Margarīns un tauku maisījumi
    325,  # Sviests
}

CHEESE_CATEGORIES: set[int] = {
    309,  # Cietais siers
    310,  # Fermentēts siers
    311,  # Fetas un brinzas siers
    312,  # Kausētais siers
    313,  # Kazas un aitas siers
    314,  # Krēmveida siers
    315,  # Mascarpone un ricotta siers
    316,  # Mozzarella un burrata siers
    317,  # Pelējuma siers
    318,  # Siers šķēlēs un rīvēts
    319,  # Uzkodu siers un sieru nūjiņas
}

FULL_FVN_CATEGORIES: set[int] = {
    3,    # Avokado
    4,    # Banāni
    5,    # Citrusaugļi
    6,    # Eksotiskie augļi un kauleņi
    7,    # Melones un arbūzi
    8,    # Sezoniāli augļi un ogas
    9,    # Vīnogas un ogas
    10,   # Āboli un bumbieri
    12,   # Apstrādāti dārzeņi
    13,   # Bietes un citi sakņaugi
    14,   # Garšaugi
    15,   # Gurķi un tomāti
    16,   # Kartupeļi, burkāni un kāposti
    17,   # Kukurūza, zirņi, pupas un sparģeļi
    18,   # Paprika un baklažāni
    19,   # Salāti un to maisījumi
    20,   # Sīpoli, puravi un ķiploki
    21,   # Ķirbji un cukini
    120,  # Citi rieksti
    121,  # Indijas rieksti un pistācijas
    122,  # Lazdu rieksti un valrieksti
    123,  # Mandeles
    124,  # Riekstu maisījumi
    125,  # Riekstu, žāvētu augļu un ogu maisījums
    126,  # Sēklas
    127,  # Zemesrieksti
    128,  # Žāvēti augļi un ogas
    342,  # Saldētas ogas
    343,  # Saldēti dārzeņi, sēnes un to maisījumi
    344,  # Saldēti kartupeļi
}

HALF_FVN_CATEGORIES: set[int] = {
    55,   # Citi konservēti dārzeņi
    57,   # Konservēta kukurūza
    58,   # Konservētas bietes
    59,   # Konservētas ogas un augļi
    61,   # Konservēti dārzeņu maisījumi
    62,   # Konservēti gurķi
    63,   # Konservēti pipari
    64,   # Konservēti pākšaugi
    65,   # Konservēti tomāti
    66,   # Konservēti zaļie zirnīši
    67,   # Konservēti ēdieni un zupas
    69,   # Melnās un citas olīvas
    70,   # Zaļās olīvas
}

BEVERAGE_CATEGORIES: set[int] = {
    184,  # Bezalkoholiskais alus un sidrs
    185,  # Bezalkoholiskais vīns
    187,  # Enerģijas dzērieni
    188,  # Izotoniskie dzērieni
    190,  # Gāzētas limonādes
    191,  # Kombuča
    192,  # Kvass
    193,  # Ledus tējas
    194,  # Negāzētas limonādes
    196,  # Nektāri
    197,  # Smūtiji un augļu kokteiļi
    198,  # Sulas
    199,  # Sulu dzērieni
    200,  # Svaigi spiesta sula
    202,  # Gāzēts ūdens
    203,  # Negāzēts ūdens
}


def convert_salt_to_sodium(salt: float) -> float:
    """Convert salt (g) to sodium (mg)"""
    return salt * 400


def calculate_nutriscore(energy_kj: float, sugars: float, saturated_fat: float, 
                        sodium: float, protein: float, fiber: float = 0, 
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
    
    if fruits_veg_nuts <= 40:
        fvn_points = 0
    elif fruits_veg_nuts <= 60:
        fvn_points = 1
    elif fruits_veg_nuts <= 80:
        fvn_points = 2
    else:
        fvn_points = 5
    
    negative_points = energy_points + sugars_points + saturated_fat_points + sodium_points
    positive_points = fiber_points + protein_points + fvn_points
    
    if is_beverage:
        positive_points = fiber_points
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
        if is_fat or is_cheese:
            if negative_points < 11:
                positive_points = fiber_points + fvn_points
            else:
                positive_points = fiber_points + protein_points + fvn_points
        
        final_score = negative_points - positive_points
        
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
    """Standalone calculator for Nutri-Score calculations."""
    
    def __init__(self):
        self.fat_categories = FAT_CATEGORIES
        self.cheese_categories = CHEESE_CATEGORIES
        self.full_fvn_categories = FULL_FVN_CATEGORIES
        self.half_fvn_categories = HALF_FVN_CATEGORIES
        self.beverage_categories = BEVERAGE_CATEGORIES
    
    def calculate_single_product(self, energy_kj: float, sugars: float, 
                               saturated_fat: float, salt: float, protein: float,
                               fiber: float = 0, fruits_veg_nuts: int = 0,
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
            category_id: Product category ID (optional, integer)
        
        Returns:
            Dictionary with score, grade, and detailed breakdown
        """
        try:
            sodium = convert_salt_to_sodium(salt)
            
            if category_id is not None:
                is_beverage = category_id in self.beverage_categories
                is_fat = category_id in self.fat_categories
                is_cheese = category_id in self.cheese_categories
                if category_id in self.full_fvn_categories:
                    fruits_veg_nuts = 100
                elif category_id in self.half_fvn_categories:
                    fruits_veg_nuts = 50
            else:
                is_beverage = False
                is_fat = False
                is_cheese = False
            
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
