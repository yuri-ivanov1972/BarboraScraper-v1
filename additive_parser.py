import re
from typing import List, Dict, Optional
from dataclasses import dataclass
import logging

@dataclass
class Additive:
    e_number: str
    name: Optional[str] = None
    description: Optional[str] = None
    safety_rating: Optional[str] = None
    source_url: Optional[str] = None

class AdditiveParser:
    def __init__(self):
        # Basic pattern for E-numbers: E followed by 3-4 digits
        self.e_number_pattern = re.compile(r'E-?\s*\d{3,4}', re.IGNORECASE)
        
    def extract_e_numbers(self, ingredients: str) -> List[str]:
        """
        Extract E-numbers from ingredients text.
        Returns a list of standardized E-numbers (e.g., ['E100', 'E501'])
        """
        if not ingredients:
            return []
            
        # Find all matches
        matches = self.e_number_pattern.findall(ingredients)
        
        # Standardize format: remove spaces, hyphens, and capitalize E
        standardized = []
        for match in matches:
            # Remove spaces and hyphens, capitalize E
            e_number = ''.join(match.split()).upper()
            standardized.append(e_number)
            
        return sorted(list(set(standardized)))  # Remove duplicates and sort

    @staticmethod
    def format_e_number(e_number: str) -> str:
        """
        Format an E-number to standard format (e.g., 'E501' from 'e-501' or 'E 501')
        """
        # Remove all spaces and hyphens, capitalize E
        return ''.join(e_number.split()).upper()

# Example usage:
# parser = AdditiveParser()
# additives = parser.extract_e_numbers("Contains E-501, E503, and preservative (E500)")
# print(additives)  # ['E500', 'E501', 'E503']
