"""
Nutri-Score 2.0 (2024) Calculator Module for Barbora products.

Uses stable barbora_category_code UUIDs that are resolved to category_ids at runtime,
ensuring the calculator works correctly across different database environments.

Supports 5 product categories:
1. General Foods (cereals, ready meals, etc.)
2. Red Meat (capped protein points at 2)
3. Cheese (exempt from protein block)
4. Fats, Oils, Nuts, and Seeds (energy from saturates, sat/fat ratio)
5. Beverages (stricter thresholds, sweetener penalty)

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

FATS_OILS_NUTS_UUIDS = {
    "6d8f2e23-9a3c-4e4e-a9f1-d64a8b1ad92e",  # Sviests, margarīns un tauki
    "02ad3df5-c8f4-4415-89f1-ae3aace9acbc",  # Margarīns un tauku maisījumi
    "02c640fc-7b5c-46b0-b204-ffc9f8cd39d2",  # Sviests
    "82bdf37f-0ae4-4378-bfef-900375252dee",  # Citas eļļas
    "0e665244-fbd5-4377-87b2-90dca75126ad",  # Olīveļļa
    "8ebcb99a-d6a6-4eae-ada3-b3baf7dd8265",  # Rapšu eļļa
    "ea75df6a-bc3a-4c36-a9a2-ab77bcb6523d",  # Saulespuķu eļļa
    "0d58756a-3c50-42df-8f38-ec58c7d64384",  # Citi rieksti
    "c089dd7c-d268-48bd-90a6-e7126313be39",  # Indijas rieksti un pistācijas
    "3f82368e-d22b-4307-b3d5-462d25c08b5b",  # Lazdu rieksti un valrieksti
    "3fdea35f-ff21-4704-b2b6-6e3ba19ce68b",  # Mandeles
    "690656fa-9612-44f6-af15-237c42ea3fa5",  # Riekstu maisījumi
    "4e231793-7e4d-4c2d-a2af-385a62445101",  # Riekstu, žāvētu augļu un ogu maisījums
    "5cb60ee1-90df-4402-93af-84c5f89f3b8f",  # Sēklas
    "b3e42b5b-3596-481e-8da1-143f4f0ef301",  # Zemesrieksti
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

RED_MEAT_UUIDS = {
    "abd4343d-fe64-44a2-a71e-1f92bc3184ae",  # Beef
    "4d9f45f0-b3cc-4b0e-957e-4fa62c97e738",  # Fresh Meat Offal
    "2f783c48-b4a3-4b18-b936-2dd6af8d8230",  # Minced Meat
    "7e2875e7-1e17-4665-bb8a-8c1fb81f1a6d",  # Pork
    "1a1cba9b-7a13-4adf-a67c-e36d653f738e",  # Marinated Meat
    "24bb04d5-9f07-40be-9071-6dbc24933d24",  # Meat Patties and Sausages
    "af928dc4-f58b-4470-a00c-5b656012066e",  # Bacon
    "35131216-445c-4e6d-8e66-35455b906912",  # Boiled Sausages
    "8d42e1a7-a023-4029-82b1-4036f9750929",  # Boiled, Fried and Salted Products
    "81e2c982-943f-4c21-a5c0-60f628fb26b6",  # Canned Meat and Poultry
    "b3225e7c-9a93-49e9-9a05-15a35cb49e72",  # Cold Smoked Products
    "5fff304a-d0e5-4ec9-8e41-91deb8328dbd",  # Cold Smoked Sausages
    "3e3faae4-ae39-4cd6-ac2d-70d03b8cea7c",  # Dried Meat Products
    "35c578cc-4dba-42e8-9239-aae8bbd5ebd3",  # Frankfurters and Vienna Sausages
    "164c7968-66fe-4b48-b855-ee9f2fd7c12b",  # Grill Sausages
    "d4bfd933-c75f-467a-becc-bbc12d26aede",  # Hot Smoked Products
    "4d7f9ee5-ce5c-4a75-9507-ba1a6677c4aa",  # Hot Smoked Sausages
    "b392f16a-a0fa-425e-9ec5-a489d56035ac",  # Meat Snacks
    "11409413-6a08-4ff5-bca2-2760b22273f2",  # Pates
    "251f2e3e-a759-42aa-8e16-872a48dcea82",  # Sliced Sausages
}

FULL_FVN_UUIDS = {
    "c5c7b6b4-ef9a-4aff-bd22-e2bfcc0becd7",  # Āboli un bumbieri
    "4bfe5ffe-dfc8-4cd5-9054-bdc61d10b130",  # Avokado
    "acfc2a12-c22d-48ea-a025-a7cc4fbf1f65",  # Banāni
    "690e3c1b-b177-497d-add3-48b8f7f2c145",  # Citrusaugļi
    "39b755d4-023b-4142-971b-55c7e8136462",  # Eksotiskie augļi un kauleņi
    "c51b4b69-32ca-4896-ac5f-0ead537dca2f",  # Melones un arbūzi
    "dc736b3c-14c5-4078-adf5-92e331feffb9",  # Sezoniāli augļi un ogas
    "bfc96f6f-9786-481e-90c2-e73dd5d6a8f5",  # Vīnogas un ogas
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
    "186d02c0-60c8-479c-9f84-f3729c43494b",  # Plant-Based Drinks
    "40956cf9-dd22-4337-9b46-2137da7290d2",  # Pasteurized Milk
    "2aa06dc3-7718-4338-b553-7fd554acb9d3",  # Milk and Probiotic Drinks
    "00a8a8d1-c2ce-4c70-bb31-489b0eb59ce6",  # Fresh Milk
    "dba4a762-f88e-418d-a434-896552b7e779",  # UHT Milk
    "4f93ccdf-77c9-408d-ad87-20391ae8fe63",  # Kefir and Kefir Drinks
    "16418c99-3f2f-4884-b8b7-68fe09d1f9bb",  # Buttermilk
}

LATVIAN_SWEETENER_INDICATORS = [
    'saldināšanas līdzeklis', 'saldinātājs', 'saldinātāji',
    'aspartāms', 'aspartam',
    'acesulfāms', 'acesulfāms k', 'acesulfam',
    'sukraloze', 'sukraloz', 'sucralose',
    'saharīns', 'sacharin',
    'ciklamāts', 'ciklamāt', 'cyclamate',
    'neotāms', 'neotam',
    'advantāms', 'advantam',
    'stevijas glikozīdi', 'stevia', 'steviol',
    'taumatīns', 'thaumatin',
    'maltīts', 'maltitol',
    'sorbīts', 'sorbitol',
    'ksilitols', 'xylitol',
    'eritritols', 'erythritol',
    'izomaltīts', 'isomalt',
    'mannīts', 'mannitol',
    'zero', 'light', 'diet', 'bez cukura', 'sugar free', 'sugar-free',
    'bezkaloriju', 'bez kalorijām',
    'e950', 'e951', 'e952', 'e953', 'e954', 'e955',
    'e957', 'e959', 'e960', 'e961', 'e962', 'e965',
    'e966', 'e967', 'e968', 'e969',
]


def get_points(value: float, thresholds: list) -> int:
    """Helper to determine points based on a list of upper limits."""
    for points, limit in enumerate(thresholds):
        if value <= limit:
            return points
    return len(thresholds)


def convert_salt_to_sodium(salt: float) -> float:
    """Convert salt (g) to sodium (mg)"""
    return salt * 400


def calculate_nutriscore_2024(
    category: str,
    energy_kj: float,
    sugars_g: float,
    sat_fat_g: float,
    salt_g: float,
    protein_g: float,
    fiber_g: float = 0,
    fvl_pct: float = 0,
    total_fat_g: Optional[float] = None,
    has_sweeteners: bool = False
) -> Dict[str, Any]:
    """
    Calculate Nutri-Score 2.0 (2024 official algorithm).
    
    Args:
        category: 'general', 'red_meat', 'cheese', 'fats_oils_nuts', 'beverage'
        energy_kj: Energy in kJ/100g
        sugars_g: Sugars in g/100g
        sat_fat_g: Saturated fat in g/100g
        salt_g: Salt in g/100g
        protein_g: Protein in g/100g
        fiber_g: Fiber in g/100g
        fvl_pct: Fruits/vegetables/legumes percentage (0-100)
        total_fat_g: Total fat in g/100g (required for fats_oils_nuts category)
        has_sweeteners: Whether product contains artificial sweeteners (beverages)
    
    Returns:
        Dictionary with grade, score, n_points, p_points, p_status, components
    """
    t_energy_gen = [335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350]
    t_sugar_gen = [3.4, 6.8, 10, 14, 17, 20, 24, 27, 31, 34, 37, 41, 44, 48, 51]
    t_satfat_gen = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    t_salt_gen = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0,
                  2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0]
    
    t_energy_bev = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270]
    t_sugar_bev = [0, 0.5, 2, 3.5, 5, 6, 7, 8, 9, 10]
    t_salt_bev = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5,
                  0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]
    
    t_fiber_gen = [0.7, 1.4, 2.1, 2.8, 3.5]
    t_protein_gen = [1.2, 2.4, 3.6, 4.8, 6.0, 7.2, 8.4]
    t_fvl_gen = [40, 60, 80]
    
    t_protein_bev = [1.2, 2.1, 3.0, 3.9, 4.8, 5.7, 6.6]
    t_fvl_bev = [40, 60, 80]
    
    p_sweetener = 0
    protein_status = "included"
    
    if category == 'beverage':
        p_energy = get_points(energy_kj, t_energy_bev)
        p_sugar = get_points(sugars_g, t_sugar_bev)
        p_salt = get_points(salt_g, t_salt_bev)
        p_satfat = get_points(sat_fat_g, t_satfat_gen)
        p_sweetener = 4 if has_sweeteners else 0
        total_n = p_energy + p_sugar + p_salt + p_satfat + p_sweetener
        
        p_protein = get_points(protein_g, t_protein_bev)
        p_fiber = get_points(fiber_g, t_fiber_gen)
        fvl_raw = get_points(fvl_pct, t_fvl_bev)
        p_fvl = [0, 2, 4, 6][fvl_raw] if fvl_raw <= 3 else 6
        total_p = p_protein + p_fiber + p_fvl
        
    elif category == 'fats_oils_nuts':
        energy_from_satfat = sat_fat_g * 37
        p_energy = get_points(energy_from_satfat, [120 * i for i in range(1, 11)])
        
        if total_fat_g and total_fat_g > 0:
            ratio = (sat_fat_g / total_fat_g) * 100
        else:
            ratio = 0
        p_satfat = get_points(ratio, [10, 16, 22, 28, 34, 40, 46, 52, 58, 64])
        
        p_sugar = get_points(sugars_g, t_sugar_gen)
        p_salt = get_points(salt_g, t_salt_gen)
        total_n = p_energy + p_sugar + p_salt + p_satfat
        
        p_protein = get_points(protein_g, t_protein_gen)
        p_fiber = get_points(fiber_g, t_fiber_gen)
        fvl_raw = get_points(fvl_pct, t_fvl_gen)
        p_fvl = 5 if fvl_raw == 3 else fvl_raw
        total_p = p_protein + p_fiber + p_fvl
        
    else:
        p_energy = get_points(energy_kj, t_energy_gen)
        p_sugar = get_points(sugars_g, t_sugar_gen)
        p_satfat = get_points(sat_fat_g, t_satfat_gen)
        p_salt = get_points(salt_g, t_salt_gen)
        total_n = p_energy + p_sugar + p_satfat + p_salt
        
        p_protein = get_points(protein_g, t_protein_gen)
        if category == 'red_meat':
            p_protein = min(p_protein, 2)
            protein_status = f"capped_at_2 (was {get_points(protein_g, t_protein_gen)})"
        
        p_fiber = get_points(fiber_g, t_fiber_gen)
        fvl_raw = get_points(fvl_pct, t_fvl_gen)
        p_fvl = 5 if fvl_raw == 3 else fvl_raw
        total_p = p_protein + p_fiber + p_fvl
    
    final_score = total_n - total_p
    
    if category not in ['cheese', 'beverage']:
        if total_n >= 11 and p_fvl < 5:
            final_score = total_n - (p_fiber + p_fvl)
            protein_status = f"blocked (N={total_n}, FVL={p_fvl})"
            total_p = p_fiber + p_fvl
    
    if category == 'beverage':
        if energy_kj == 0 and sugars_g == 0 and not has_sweeteners:
            grade = "A"
        elif final_score <= 2:
            grade = "B"
        elif final_score <= 6:
            grade = "C"
        elif final_score <= 9:
            grade = "D"
        else:
            grade = "E"
    elif category == 'fats_oils_nuts':
        if final_score <= -6:
            grade = "A"
        elif final_score <= 2:
            grade = "B"
        elif final_score <= 10:
            grade = "C"
        elif final_score <= 18:
            grade = "D"
        else:
            grade = "E"
    else:
        if final_score <= -1:
            grade = "A"
        elif final_score <= 2:
            grade = "B"
        elif final_score <= 10:
            grade = "C"
        elif final_score <= 18:
            grade = "D"
        else:
            grade = "E"
    
    components = {
        'energy_points': p_energy,
        'sugar_points': p_sugar,
        'satfat_points': p_satfat,
        'salt_points': p_salt,
        'sweetener_points': p_sweetener,
        'protein_points': p_protein,
        'fiber_points': p_fiber,
        'fvl_points': p_fvl,
        'negative_total': total_n,
        'positive_total': total_p,
    }
    
    return {
        'grade': grade,
        'score': final_score,
        'n_points': total_n,
        'p_points': total_p,
        'protein_status': protein_status,
        'components': components
    }


def load_category_ids(conn) -> Dict[str, Set[int]]:
    """
    Load category_ids from database by resolving stable UUIDs.
    
    Args:
        conn: Database connection (psycopg2 connection object)
    
    Returns:
        Dictionary with category sets: fats_oils_nuts, cheese, red_meat, full_fvn, half_fvn, beverage
    
    Raises:
        ValueError: If any expected UUIDs are missing from the database
    """
    all_uuids = FATS_OILS_NUTS_UUIDS | CHEESE_UUIDS | RED_MEAT_UUIDS | FULL_FVN_UUIDS | HALF_FVN_UUIDS | BEVERAGE_UUIDS
    
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
        logger.warning(f"Missing {len(missing)} category UUIDs in database: {list(missing)[:5]}...")
    
    return {
        'fats_oils_nuts': {uuid_to_id[u] for u in FATS_OILS_NUTS_UUIDS if u in uuid_to_id},
        'cheese': {uuid_to_id[u] for u in CHEESE_UUIDS if u in uuid_to_id},
        'red_meat': {uuid_to_id[u] for u in RED_MEAT_UUIDS if u in uuid_to_id},
        'full_fvn': {uuid_to_id[u] for u in FULL_FVN_UUIDS if u in uuid_to_id},
        'half_fvn': {uuid_to_id[u] for u in HALF_FVN_UUIDS if u in uuid_to_id},
        'beverage': {uuid_to_id[u] for u in BEVERAGE_UUIDS if u in uuid_to_id},
    }


def detect_sweeteners(product_name: Optional[str], ingredients_text: Optional[str] = None) -> bool:
    """Detect if product likely contains artificial sweeteners based on name/ingredients.
    
    Uses LATVIAN_SWEETENER_INDICATORS which includes:
    - Latvian sweetener names (saldināšanas līdzeklis, aspartāms, sukraloze, etc.)
    - English equivalents for international products
    - E-numbers for artificial sweeteners (E950-E969)
    - Marketing terms (zero, light, diet, bez cukura)
    """
    text_to_check = (product_name or '').lower()
    if ingredients_text:
        text_to_check += ' ' + ingredients_text.lower()
    
    return any(indicator in text_to_check for indicator in LATVIAN_SWEETENER_INDICATORS)


class NutriscoreCalculator:
    """
    Nutri-Score 2.0 (2024) Calculator.
    Supports 5 categories: general, beverage, red_meat, cheese, fats_oils_nuts.
    """
    
    def __init__(self, db_connection=None):
        """
        Initialize the calculator.
        
        Args:
            db_connection: Optional database connection. If provided, category IDs
                          are loaded dynamically from the database using stable UUIDs.
                          If None, categories won't be detected (all products treated as general).
        """
        if db_connection:
            categories = load_category_ids(db_connection)
            self.fats_oils_nuts_categories = categories['fats_oils_nuts']
            self.cheese_categories = categories['cheese']
            self.red_meat_categories = categories['red_meat']
            self.full_fvn_categories = categories['full_fvn']
            self.half_fvn_categories = categories['half_fvn']
            self.beverage_categories = categories['beverage']
            self._initialized = True
        else:
            logger.warning(
                "NutriscoreCalculator initialized without database connection. "
                "Category detection (beverage/fat/cheese/red_meat/FVN) will be disabled. "
                "Pass a db_connection for accurate Nutri-Score calculations."
            )
            self.fats_oils_nuts_categories = set()
            self.cheese_categories = set()
            self.red_meat_categories = set()
            self.full_fvn_categories = set()
            self.half_fvn_categories = set()
            self.beverage_categories = set()
            self._initialized = False
    
    def _determine_category(self, category_id: Optional[int]) -> str:
        """Determine the Nutri-Score category based on product category ID."""
        if not category_id:
            return 'general'
        
        if category_id in self.beverage_categories:
            return 'beverage'
        
        if category_id in self.fats_oils_nuts_categories:
            return 'fats_oils_nuts'
        
        if category_id in self.cheese_categories:
            return 'cheese'
        
        if category_id in self.red_meat_categories:
            return 'red_meat'
        
        return 'general'
    
    def _get_fvl_percentage(self, category_id: Optional[int]) -> float:
        """Get fruits/vegetables/legumes percentage based on category."""
        if not category_id:
            return 0
        
        if category_id in self.full_fvn_categories:
            return 100
        
        if category_id in self.half_fvn_categories:
            return 50
        
        return 0
    
    def calculate_single_product(
        self,
        energy_kj: float,
        sugars: float,
        saturated_fat: float,
        salt: float,
        protein: float,
        fiber: float = 0,
        total_fat: Optional[float] = None,
        fruits_veg_nuts: float = 0,
        category_id: Optional[int] = None,
        product_name: Optional[str] = None,
        ingredients_text: Optional[str] = None,
        has_sweeteners: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Calculate Nutri-Score for a single product using 2024 algorithm.
        
        Args:
            energy_kj: Energy in kJ/100g
            sugars: Sugars in g/100g
            saturated_fat: Saturated fat in g/100g
            salt: Salt in g/100g
            protein: Protein in g/100g
            fiber: Fiber in g/100g (default: 0)
            total_fat: Total fat in g/100g (needed for oils/fats calculation)
            fruits_veg_nuts: % fruits/vegetables/nuts (default: 0, auto-detected from category)
            category_id: Product category ID (integer)
            product_name: Product name (for sweetener detection)
            ingredients_text: Ingredients list (for sweetener detection)
            has_sweeteners: Override sweetener detection (True/False/None=auto)
        
        Returns:
            Dictionary with score, grade, and detailed breakdown
        """
        try:
            ns_category = self._determine_category(category_id)
            
            fvl_pct = fruits_veg_nuts
            if fvl_pct == 0:
                fvl_pct = self._get_fvl_percentage(category_id)
            
            if has_sweeteners is None and ns_category == 'beverage':
                has_sweeteners = detect_sweeteners(product_name, ingredients_text)
            else:
                has_sweeteners = has_sweeteners or False
            
            result = calculate_nutriscore_2024(
                category=ns_category,
                energy_kj=energy_kj or 0,
                sugars_g=sugars or 0,
                sat_fat_g=saturated_fat or 0,
                salt_g=salt or 0,
                protein_g=protein or 0,
                fiber_g=fiber or 0,
                fvl_pct=fvl_pct,
                total_fat_g=total_fat,
                has_sweeteners=has_sweeteners
            )
            
            return {
                'success': True,
                'score': result['score'],
                'grade': result['grade'],
                'n_points': result['n_points'],
                'p_points': result['p_points'],
                'protein_status': result['protein_status'],
                'components': result['components'],
                'classification': {
                    'nutriscore_category': ns_category,
                    'is_beverage': ns_category == 'beverage',
                    'is_fats_oils_nuts': ns_category == 'fats_oils_nuts',
                    'is_cheese': ns_category == 'cheese',
                    'is_red_meat': ns_category == 'red_meat',
                    'fruits_veg_nuts_percent': fvl_pct,
                    'has_sweeteners': has_sweeteners
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def batch_calculate(self, products: list) -> list:
        """
        Calculate Nutri-Score for multiple products.
        
        Args:
            products: List of dicts with keys matching calculate_single_product params
        
        Returns:
            List of results with product_id and score info
        """
        results = []
        for product in products:
            product_id = product.get('product_id')
            result = self.calculate_single_product(
                energy_kj=product.get('energy_kj', 0),
                sugars=product.get('sugars', 0),
                saturated_fat=product.get('saturated_fat', 0),
                salt=product.get('salt', 0),
                protein=product.get('protein', 0),
                fiber=product.get('fiber', 0),
                total_fat=product.get('total_fat'),
                fruits_veg_nuts=product.get('fruits_veg_nuts', 0),
                category_id=product.get('category_id'),
                product_name=product.get('product_name'),
                ingredients_text=product.get('ingredients_text'),
                has_sweeteners=product.get('has_sweeteners')
            )
            result['product_id'] = product_id
            results.append(result)
        return results


def calculate_nutriscore(
    energy_kj: float,
    sugars: float,
    saturated_fat: float,
    sodium: float,
    protein: float,
    fiber: float = 0,
    fruits_veg_nuts: float = 0,
    is_beverage: bool = False,
    is_fat: bool = False,
    is_cheese: bool = False,
    is_red_meat: bool = False
) -> Tuple[int, str, Dict[str, int]]:
    """
    Backward-compatible wrapper for legacy code.
    
    DEPRECATED: Use NutriscoreCalculator.calculate_single_product() instead.
    
    This function maintains the old interface (sodium in mg, returns tuple)
    while using the new 2024 algorithm internally.
    
    Args:
        energy_kj: Energy in kJ/100g
        sugars: Sugars in g/100g
        saturated_fat: Saturated fat in g/100g
        sodium: Sodium in mg/100g (will be converted back to salt)
        protein: Protein in g/100g
        fiber: Fiber in g/100g
        fruits_veg_nuts: % fruits/vegetables/nuts
        is_beverage: True if beverage
        is_fat: True if fat/oil/nuts
        is_cheese: True if cheese
        is_red_meat: True if red meat
    
    Returns:
        Tuple of (numeric_score, letter_grade, component_scores)
    """
    salt_g = sodium / 400 if sodium else 0
    
    if is_beverage:
        category = 'beverage'
    elif is_fat:
        category = 'fats_oils_nuts'
    elif is_cheese:
        category = 'cheese'
    elif is_red_meat:
        category = 'red_meat'
    else:
        category = 'general'
    
    result = calculate_nutriscore_2024(
        category=category,
        energy_kj=energy_kj or 0,
        sugars_g=sugars or 0,
        sat_fat_g=saturated_fat or 0,
        salt_g=salt_g,
        protein_g=protein or 0,
        fiber_g=fiber or 0,
        fvl_pct=fruits_veg_nuts or 0,
        total_fat_g=None,
        has_sweeteners=False
    )
    
    components = {
        'negative_points': result['n_points'],
        'positive_points': result['p_points'],
        'energy_points': result['components']['energy_points'],
        'sugars_points': result['components']['sugar_points'],
        'saturated_fat_points': result['components']['satfat_points'],
        'sodium_points': result['components']['salt_points'],
        'protein_points': result['components']['protein_points'],
        'fiber_points': result['components']['fiber_points'],
        'fvn_points': result['components']['fvl_points']
    }
    
    return result['score'], result['grade'], components


FAT_UUIDS = FATS_OILS_NUTS_UUIDS
FAT_CATEGORIES = FATS_OILS_NUTS_UUIDS
FULL_FVN_CATEGORIES = FULL_FVN_UUIDS
HALF_FVN_CATEGORIES = HALF_FVN_UUIDS


if __name__ == '__main__':
    print("Nutri-Score 2024 Calculator - Test Examples")
    print("=" * 70)
    
    print("\n1. High-fiber cereal (General category):")
    result = calculate_nutriscore_2024(
        category='general',
        energy_kj=1801, sugars_g=24, sat_fat_g=0.5, salt_g=0.3,
        protein_g=13, fiber_g=16, fvl_pct=0
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']}, P={result['p_points']}, Protein: {result['protein_status']}")
    
    print("\n2. Camembert cheese (Cheese category - protein not blocked):")
    result = calculate_nutriscore_2024(
        category='cheese',
        energy_kj=1200, sugars_g=0.5, sat_fat_g=18, salt_g=1.5,
        protein_g=20, fiber_g=0, fvl_pct=0
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']}, P={result['p_points']}, Protein: {result['protein_status']}")
    
    print("\n3. Olive oil (Fats/Oils category - uses sat/fat ratio):")
    result = calculate_nutriscore_2024(
        category='fats_oils_nuts',
        energy_kj=3700, sugars_g=0, sat_fat_g=14, salt_g=0,
        protein_g=0, fiber_g=0, total_fat_g=100, fvl_pct=0
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']}, P={result['p_points']}")
    
    print("\n4. Diet Cola (Beverage with sweeteners - +4 penalty):")
    result = calculate_nutriscore_2024(
        category='beverage',
        energy_kj=4, sugars_g=0, sat_fat_g=0, salt_g=0,
        protein_g=0, fiber_g=0, fvl_pct=0, has_sweeteners=True
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']} (includes +4 sweetener), P={result['p_points']}")
    
    print("\n5. Water (Beverage - only A-grade beverage):")
    result = calculate_nutriscore_2024(
        category='beverage',
        energy_kj=0, sugars_g=0, sat_fat_g=0, salt_g=0,
        protein_g=0, fiber_g=0, fvl_pct=0, has_sweeteners=False
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    
    print("\n6. Beef steak (Red Meat - protein capped at 2):")
    result = calculate_nutriscore_2024(
        category='red_meat',
        energy_kj=800, sugars_g=0, sat_fat_g=5, salt_g=0.2,
        protein_g=25, fiber_g=0, fvl_pct=0
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']}, P={result['p_points']}, Protein: {result['protein_status']}")
    
    print("\n7. Fresh apple (100% FVL):")
    result = calculate_nutriscore_2024(
        category='general',
        energy_kj=218, sugars_g=10.4, sat_fat_g=0.03, salt_g=0.001,
        protein_g=0.3, fiber_g=2.4, fvl_pct=100
    )
    print(f"   Grade: {result['grade']}, Score: {result['score']}")
    print(f"   N={result['n_points']}, P={result['p_points']}")
    
    print("\n" + "=" * 70)
    print("All tests completed successfully!")
