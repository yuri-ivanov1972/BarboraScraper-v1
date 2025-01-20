import logging
from additive_parser import AdditiveParser

def test_real_examples():
    parser = AdditiveParser()
    logging.basicConfig(level=logging.INFO)

    # Real examples from our database
    examples = [
        "kāposti 68%, burkāni 18%, rapšu eļļa, etiķis(ūdens, skābuma regulētājs: etiķskābe E260), cukurs, sāls",
        "LAŠA fileja 43%, SIERS (PIENS, pienskābes baktēriju kultūras, biezinātājs E412, sāls, renīns)",
        "cāļu krūtiņas mazā fileja 82%, jogurts(PIENS, KRĒJUMS, ieraugs), garšvielu maisījums(sāls, garšvielas (sīpoli, baltie pipari, ķiploki, kurkuma, koriandrs, ķimenes, ingvers, oregano, fenhelis, sierāboliņš un čilli), konservants E262, dekstroze, hidrolizēti augu proteīni",
        "KVIEŠU milti, raugs, sāls, SEZAMA sēklas, konservants E282, emulgators E472e"  # Added test for Kliņģeris
    ]

    print("=== Testing E-number Extraction ===\n")
    for i, ingredient_text in enumerate(examples, 1):
        print(f"\nExample {i}:")
        print(f"Input: {ingredient_text[:100]}...")

        # Basic extraction
        e_numbers = parser.extract_e_numbers(ingredient_text)
        print(f"Found E-numbers: {e_numbers}")

        # Detailed parsing with context
        details = parser.parse_ingredients_for_additives(ingredient_text)
        print("\nDetailed Analysis:")
        for detail in details:
            print(f"- E-number: {detail['e_number']}")
            print(f"  Context: {detail['context']}")
            if detail['function']:
                print(f"  Function: {detail['function']}")

if __name__ == "__main__":
    test_real_examples()