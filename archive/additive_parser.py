import re
from typing import List, Dict, Optional
from dataclasses import dataclass
import logging

@dataclass
class Additive:
    """
    Data class representing a food additive (E-number)
    """
    e_number: str
    name: Optional[str] = None
    description: Optional[str] = None
    safety_rating: Optional[str] = None
    source_url: Optional[str] = None

class AdditiveParser:
    def __init__(self):
        # Pattern matches:
        # - E followed by optional hyphen/space
        # - 3-4 digits (all valid E-numbers are in this range)
        # - Case insensitive
        # Examples: E100, E-100, e 100, E1001
        self.e_number_pattern = re.compile(r'E-?\s*\d{3,4}[a-z]?', re.IGNORECASE)
        self.logger = logging.getLogger(__name__)

    def extract_e_numbers(self, ingredients: str) -> List[str]:
        """
        Extract E-numbers from ingredients text.

        Args:
            ingredients (str): Raw ingredients text from product

        Returns:
            List[str]: List of standardized E-numbers (e.g., ['E100', 'E501'])

        Example:
            >>> parser = AdditiveParser()
            >>> parser.extract_e_numbers("Contains E-501, emulsifiers (E322, E500ii)")
            ['E501', 'E322', 'E500']
        """
        if not ingredients:
            return []

        try:
            # Find all matches in the text
            matches = self.e_number_pattern.findall(ingredients)

            # Process and standardize each match
            standardized = []
            for match in matches:
                # Remove spaces, hyphens and convert to uppercase
                e_number = self._standardize_e_number(match)
                if e_number:
                    standardized.append(e_number)

            # Remove duplicates and sort
            return sorted(list(set(standardized)))

        except Exception as e:
            self.logger.error(f"Error extracting E-numbers from ingredients: {str(e)}")
            return []

    def _standardize_e_number(self, e_number: str) -> str:
        """
        Standardize E-number format by removing spaces, hyphens and converting to uppercase.
        Also handles special cases and variants.

        Args:
            e_number (str): Raw E-number string

        Returns:
            str: Standardized E-number
        """
        try:
            # Remove all spaces and hyphens, convert to uppercase
            cleaned = ''.join(e_number.split()).upper()

            # Extract just the numeric part (and any letter suffix)
            match = re.match(r'E(\d{3,4}[A-Z]?)', cleaned)
            if match:
                number = match.group(1)
                return f'E{number}'

            return None

        except Exception as e:
            self.logger.error(f"Error standardizing E-number {e_number}: {str(e)}")
            return None

    def parse_ingredients_for_additives(self, ingredients: str) -> List[Dict[str, str]]:
        """
        Parse ingredients text and return detailed information about found additives.

        Args:
            ingredients (str): Raw ingredients text

        Returns:
            List[Dict[str, str]]: List of dictionaries containing E-number and context

        Example:
            >>> parser = AdditiveParser()
            >>> parser.parse_ingredients_for_additives("Contains emulsifier (E322)")
            [{'e_number': 'E322', 'context': 'emulsifier'}]
        """
        if not ingredients:
            return []

        try:
            results = []
            # Find positions of all E-numbers
            for match in self.e_number_pattern.finditer(ingredients.lower()):
                e_number = self._standardize_e_number(match.group())
                if not e_number:
                    continue

                # Get context (20 characters before and after)
                start = max(0, match.start() - 20)
                end = min(len(ingredients), match.end() + 20)
                context = ingredients[start:end].strip()

                # Try to extract function (text in parentheses or before E-number)
                function = None
                context_before = ingredients[start:match.start()].strip()
                parentheses_match = re.search(r'\((.*?)\)', context_before)
                if parentheses_match:
                    function = parentheses_match.group(1).strip()

                results.append({
                    'e_number': e_number,
                    'context': context,
                    'function': function
                })

            return results

        except Exception as e:
            self.logger.error(f"Error parsing ingredients for additives: {str(e)}")
            return []

# Example usage:
if __name__ == "__main__":
    parser = AdditiveParser()
    test_ingredients = "Contains emulsifiers (E322, E500ii), color (E160), and preservative E-501"
    additives = parser.extract_e_numbers(test_ingredients)
    print(f"Found additives: {additives}")

    detailed = parser.parse_ingredients_for_additives(test_ingredients)
    for additive in detailed:
        print(f"\nE-number: {additive['e_number']}")
        print(f"Context: {additive['context']}")
        if additive['function']:
            print(f"Function: {additive['function']}")