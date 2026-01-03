"""
Standalone Nutriscore Calculator Module for Barbora products.

Uses stable barbora_category_code UUIDs that are resolved to category_ids at runtime,
ensuring the calculator works correctly across different database environments.

Usage:
    from nutriscore_calculator import NutriscoreCalculator
    
    calculator = NutriscoreCalculator(db_connection)
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

import logging
from typing import Dict, Tuple, Any, Optional, Set

logger = logging.getLogger(__name__)

FAT_UUIDS = {
    "82bdf37f-0ae4-4378-bfef-900375252dee",  # Citas eļļas
    "0e665244-fbd5-4377-87b2-90dca75126ad",  # Olīveļļa
    "8ebcb99a-d6a6-4eae-ada3-b3baf7dd8265",  # Rapšu eļļa
    "ea75df6a-bc3a-4c36-a9a2-ab77bcb6523d",  # Saulespuķu eļļa
    "6d8f2e23-9a3c-4e4e-a9f1-d64a8b1ad92e",  # Sviests, margarīns un tauki
    "02ad3df5-c8f4-4415-89f1-ae3aace9acbc",  # Margarīns un tauku maisījumi
    "02c640fc-7b5c-46b0-b204-ffc9f8cd39d2",  # Sviests
}

CHEESE_UUIDS = {
    "60a69a0d-7313-4d4d-858f-f1014830d3a7",  # Cietais siers
    "7859597e-bde9-4ea5-a911-ad8df3ac0864",  # Fermentēts siers
    "9c56b5bf-6c5d-413d-b5bf-1195264a8059",  # Fetas un brinzas siers
    "e2b42f26-59fe-47dd-900f-9544f7b2e7e2",  # Kausētais siers
    "2ef8b53c-2486-40ab-8915-8490839f36e8",  # Kazas un aitas siers
    "3102d5e5-819a-4525-b40c-dcd30e2d5708",  # Krēmveida siers
    "d5a99c62-1c21-47e5-8948-de69713c644a",  # Mascarpone un ricotta siers
    "ea4d5c46-a5ed-4868-9340-83ca34d40892",  # Mozzarella un burrata siers
    "5beae799-013e-4ec3-ac42-50a49d8aed71",  # Pelējuma siers
    "2cc83cf6-ed23-45de-813e-9d6316e86d47",  # Siers šķēlēs un rīvēts
    "2728994f-cdd0-46d9-becb-0b3a403e8439",  # Uzkodu siers un sieru nūjiņas
}

FULL_FVN_UUIDS = {
    "4bfe5ffe-dfc8-4cd5-9054-bdc61d10b130",  # Avokado
    "acfc2a12-c22d-48ea-a025-a7cc4fbf1f65",  # Banāni
    "690e3c1b-b177-497d-add3-48b8f7f2c145",  # Citrusaugļi
    "39b755d4-023b-4142-971b-55c7e8136462",  # Eksotiskie augļi un kauleņi
    "c51b4b69-32ca-4896-ac5f-0ead537dca2f",  # Melones un arbūzi
    "dc736b3c-14c5-4078-adf5-92e331feffb9",  # Sezoniāli augļi un ogas
    "bfc96f6f-9786-481e-90c2-e73dd5d6a8f5",  # Vīnogas un ogas
    "c5c7b6b4-ef9a-4aff-bd22-e2bfcc0becd7",  # Āboli un bumbieri
    "4f52d3a4-3fee-4a9e-83ec-bc56e9c8ce99",  # Apstrādāti dārzeņi
    "da12eae2-be76-4866-9c66-e61a4149559c",  # Bietes un citi sakņaugi
    "70b72b86-831a-49eb-992b-7a5dd3af6df5",  # Garšaugi
    "04005a5f-97ea-403c-9d25-881915e200f3",  # Gurķi un tomāti
    "eba0385d-f74e-46ab-af48-d91c711b8dd0",  # Kartupeļi, burkāni un kāposti
    "ceba5b58-2abe-4088-8f2f-86fee6f16355",  # Kukurūza, zirņi, pupas un sparģeļi
    "21889904-01ae-4563-ae47-106650f6d71c",  # Paprika un baklažāni
    "e343e087-e2d9-4ae7-80e8-10418ff6f57e",  # Salāti un to maisījumi
    "0a2cd005-c836-421c-af9a-a9acd4a2fe31",  # Sīpoli, puravi un ķiploki
    "ede544ad-3ea5-4769-876a-4e3c8f55de1b",  # Ķirbji un cukini
    "0d58756a-3c50-42df-8f38-ec58c7d64384",  # Citi rieksti
    "c089dd7c-d268-48bd-90a6-e7126313be39",  # Indijas rieksti un pistācijas
    "3f82368e-d22b-4307-b3d5-462d25c08b5b",  # Lazdu rieksti un valrieksti
    "3fdea35f-ff21-4704-b2b6-6e3ba19ce68b",  # Mandeles
    "690656fa-9612-44f6-af15-237c42ea3fa5",  # Riekstu maisījumi
    "4e231793-7e4d-4c2d-a2af-385a62445101",  # Riekstu, žāvētu augļu un ogu maisījums
    "5cb60ee1-90df-4402-93af-84c5f89f3b8f",  # Sēklas
    "b3e42b5b-3596-481e-8da1-143f4f0ef301",  # Zemesrieksti
    "b1555bcf-a89b-4cd6-adf5-0d602c992e20",  # Žāvēti augļi un ogas
    "6f85cab0-4e23-4449-9db6-7968869b0d08",  # Saldētas ogas
    "484b4f6a-8a4f-406a-a19f-365238a752f1",  # Saldēti dārzeņi, sēnes un to maisījumi
    "45d05ce2-9b45-4619-88fe-8b28b6523eea",  # Saldēti kartupeļi
}

HALF_FVN_UUIDS = {
    "138145ac-f69d-44b2-8fc4-79f8c984c08f",  # Citi konservēti dārzeņi
    "d8699f03-bcf1-49d0-b9f5-957399f6aa3a",  # Konservēta kukurūza
    "df66e7d7-377c-45be-bb86-c32a50cdec3a",  # Konservētas bietes
    "0bb340da-948a-4ea6-bf56-5dc164c1b02e",  # Konservētas ogas un augļi
    "79c3de9b-3591-4193-8cdd-e5c9920d125d",  # Konservēti dārzeņu maisījumi
    "b25eced0-a507-4ee1-98de-a38167a120ce",  # Konservēti gurķi
    "e0b4074e-efb0-4f8f-a96f-33f6358c4d4d",  # Konservēti pipari
    "a8c9e06e-f84a-4fc7-80bf-15bc93ca65bb",  # Konservēti pākšaugi
    "1a510752-a579-4951-9472-c2130bb2651f",  # Konservēti tomāti
    "90bd4204-53cf-45d0-9dc0-6e19368776ea",  # Konservēti zaļie zirnīši
    "fffd12c7-05e9-47a5-aa81-b5b58fd473aa",  # Konservēti ēdieni un zupas
    "23ac3164-1fc2-4b11-af27-482953fe7862",  # Melnās un citas olīvas
    "9900fc65-c0c3-4dc5-b4d3-1e728d280dfd",  # Zaļās olīvas
}

BEVERAGE_UUIDS = {
    "fa93b0ae-32b7-4f29-975d-b7642a4bbbd0",  # Bezalkoholiskais alus un sidrs
    "b8609cdf-1a72-48c0-9603-15ec908b3303",  # Bezalkoholiskais vīns
    "1649ce5a-2a76-4bf1-a87a-d1f6de063d3d",  # Enerģijas dzērieni
    "59f2adf3-a686-4ce7-b293-f058d4de3d77",  # Izotoniskie dzērieni
    "bc66bfa2-b0d3-48d4-aea1-606be2b0c10d",  # Gāzētas limonādes
    "88d94d0e-a7f0-4e58-b96a-6c7161bd27c8",  # Kombuča
    "a2174cd0-0aaf-448c-ba9f-848858f2554a",  # Kvass
    "3c191791-31a2-4498-9f76-326777dc5fce",  # Ledus tējas
    "b81dec79-5693-494c-b4c7-7bee877db266",  # Negāzētas limonādes
    "7501000d-d8bd-4f28-bdff-8c40b55bb7ab",  # Nektāri
    "2abba27f-658e-4356-860e-1ab3c00363a9",  # Smūtiji un augļu kokteiļi
    "84e6b16a-6acf-4e72-a248-925d35c2ef0d",  # Sulas
    "ec6ae6e9-7d1e-42a1-8316-c75772ca09ef",  # Sulu dzērieni
    "883c1354-e340-4c49-9e85-b8971d422e90",  # Svaigi spiesta sula
    "b6052c83-b534-4164-b9d0-a9f4b87be6a3",  # Gāzēts ūdens
    "5eb3ded3-9968-4e75-8bde-9157dc30c8df",  # Negāzēts ūdens
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


def load_category_ids(conn) -> Dict[str, Set[int]]:
    """
    Load category_ids from database by resolving stable UUIDs.
    
    Args:
        conn: Database connection (psycopg2 connection object)
    
    Returns:
        Dictionary with category sets: fat, cheese, full_fvn, half_fvn, beverage
    
    Raises:
        ValueError: If any expected UUIDs are missing from the database
    """
    all_uuids = FAT_UUIDS | CHEESE_UUIDS | FULL_FVN_UUIDS | HALF_FVN_UUIDS | BEVERAGE_UUIDS
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT category_id, barbora_category_code 
            FROM normalized_categories 
            WHERE barbora_category_code = ANY(%s)
        """, (list(all_uuids),))
        
        rows = cur.fetchall()
    
    uuid_to_id = {row[1]: row[0] for row in rows}
    
    missing = all_uuids - set(uuid_to_id.keys())
    if missing:
        raise ValueError(f"Missing {len(missing)} category UUIDs in database: {list(missing)[:5]}...")
    
    return {
        'fat': {uuid_to_id[u] for u in FAT_UUIDS},
        'cheese': {uuid_to_id[u] for u in CHEESE_UUIDS},
        'full_fvn': {uuid_to_id[u] for u in FULL_FVN_UUIDS},
        'half_fvn': {uuid_to_id[u] for u in HALF_FVN_UUIDS},
        'beverage': {uuid_to_id[u] for u in BEVERAGE_UUIDS},
    }


class NutriscoreCalculator:
    """Standalone calculator for Nutri-Score calculations."""
    
    def __init__(self, db_connection=None):
        """
        Initialize the calculator.
        
        Args:
            db_connection: Optional database connection. If provided, category IDs
                          are loaded dynamically from the database using stable UUIDs.
                          If None, categories won't be detected (all products treated as regular food).
        """
        if db_connection:
            categories = load_category_ids(db_connection)
            self.fat_categories = categories['fat']
            self.cheese_categories = categories['cheese']
            self.full_fvn_categories = categories['full_fvn']
            self.half_fvn_categories = categories['half_fvn']
            self.beverage_categories = categories['beverage']
            self._initialized = True
        else:
            logger.warning(
                "NutriscoreCalculator initialized without database connection. "
                "Category detection (beverage/fat/cheese/FVN) will be disabled. "
                "Pass a db_connection for accurate Nutri-Score calculations."
            )
            self.fat_categories = set()
            self.cheese_categories = set()
            self.full_fvn_categories = set()
            self.half_fvn_categories = set()
            self.beverage_categories = set()
            self._initialized = False
    
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
