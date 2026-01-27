"""
USDA FoodData Central API Client

Provides nutrition data enrichment from USDA's FoodData Central database.
API Documentation: https://app.swaggerhub.com/apis/fdcnal/food-data_central_api/1.0.1

Rate Limits: 1,000 requests per hour with registered API key
"""

import os
import time
import requests
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class NutritionData:
    """Nutrition data extracted from USDA"""
    energy_kcal: Optional[float] = None
    energy_kj: Optional[float] = None
    fat_total: Optional[float] = None
    fat_saturated: Optional[float] = None
    carbs_total: Optional[float] = None
    carbs_sugars: Optional[float] = None
    protein: Optional[float] = None
    salt: Optional[float] = None
    fiber: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Optional[float]]:
        return {
            'energy_kcal': self.energy_kcal,
            'energy_kj': self.energy_kj,
            'fat_total': self.fat_total,
            'fat_saturated': self.fat_saturated,
            'carbs_total': self.carbs_total,
            'carbs_sugars': self.carbs_sugars,
            'protein': self.protein,
            'salt': self.salt,
            'fiber': self.fiber
        }
    
    def is_complete(self) -> bool:
        """Check if we have all required fields for nutri-score calculation"""
        required = [self.energy_kcal, self.fat_saturated, self.carbs_sugars, self.protein, self.salt]
        return all(v is not None for v in required)


@dataclass
class USDAFoodMatch:
    """A food match from USDA search"""
    fdc_id: int
    description: str
    data_type: str
    score: float
    brand_owner: Optional[str] = None
    nutrition: Optional[NutritionData] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'fdc_id': self.fdc_id,
            'description': self.description,
            'data_type': self.data_type,
            'score': self.score,
            'brand_owner': self.brand_owner,
            'nutrition': self.nutrition.to_dict() if self.nutrition else None
        }


class USDAClient:
    """
    Client for USDA FoodData Central API
    
    Usage:
        client = USDAClient()
        matches = client.search_food("ginger")
        if matches:
            nutrition = client.get_nutrition(matches[0].fdc_id)
    """
    
    BASE_URL = "https://api.nal.usda.gov/fdc/v1"
    
    NUTRIENT_IDS = {
        'energy_kcal': 1008,
        'energy_kj': 1062,
        'fat_total': 1004,
        'fat_saturated': 1258,
        'carbs_total': 1005,
        'carbs_sugars': 2000,
        'protein': 1003,
        'sodium': 1093,
        'fiber': 1079,
    }
    
    PREFERRED_DATA_TYPES = ['Foundation', 'SR Legacy', 'Survey (FNDDS)']
    
    def __init__(self, api_key: Optional[str] = None, status_callback=None):
        self.api_key = api_key or os.environ.get('USDA_API_KEY')
        if not self.api_key:
            raise ValueError("USDA_API_KEY not found in environment or provided")
        
        self.status_callback = status_callback or print
        self.request_count = 0
        self.hour_start = datetime.now()
        self.session = requests.Session()
        self.session.headers.update({
            'X-Api-Key': self.api_key,
            'Content-Type': 'application/json'
        })
    
    def _check_rate_limit(self):
        """Ensure we don't exceed 1000 requests per hour"""
        now = datetime.now()
        if now - self.hour_start > timedelta(hours=1):
            self.request_count = 0
            self.hour_start = now
        
        if self.request_count >= 950:
            wait_time = (self.hour_start + timedelta(hours=1) - now).seconds
            self.status_callback(f"⚠️ Rate limit approaching. Waiting {wait_time}s...")
            time.sleep(wait_time + 5)
            self.request_count = 0
            self.hour_start = datetime.now()
        
        self.request_count += 1
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        """Make an API request with error handling"""
        self._check_rate_limit()
        
        url = f"{self.BASE_URL}{endpoint}"
        
        try:
            if method == 'GET':
                response = self.session.get(url, params=kwargs.get('params'), timeout=30)
            else:
                response = self.session.post(url, json=kwargs.get('json'), timeout=30)
            
            remaining = response.headers.get('X-RateLimit-Remaining', 'N/A')
            self.status_callback(f"📊 USDA API: {remaining} requests remaining this hour")
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                self.status_callback("⚠️ Rate limit exceeded. Waiting 60s...")
                time.sleep(60)
                return self._make_request(method, endpoint, **kwargs)
            else:
                self.status_callback(f"❌ USDA API error: {response.status_code} - {response.text[:200]}")
                return None
                
        except requests.exceptions.Timeout:
            self.status_callback("⚠️ USDA API timeout, retrying...")
            time.sleep(2)
            return self._make_request(method, endpoint, **kwargs)
        except Exception as e:
            self.status_callback(f"❌ USDA API request failed: {str(e)}")
            return None
    
    def search_food(self, query: str, page_size: int = 5) -> List[USDAFoodMatch]:
        """
        Search for foods matching the query
        
        Args:
            query: Food name to search (in English)
            page_size: Number of results to return (default 5)
            
        Returns:
            List of USDAFoodMatch objects sorted by relevance
        """
        self.status_callback(f"🔍 Searching USDA for: '{query}'")
        
        search_params = {
            "query": query,
            "dataType": self.PREFERRED_DATA_TYPES,
            "pageSize": page_size,
            "pageNumber": 1,
            "sortBy": "score",
            "sortOrder": "desc"
        }
        
        result = self._make_request('POST', '/foods/search', json=search_params)
        
        if not result or 'foods' not in result:
            self.status_callback(f"⚠️ No results found for '{query}'")
            return []
        
        matches = []
        for food in result['foods']:
            match = USDAFoodMatch(
                fdc_id=food['fdcId'],
                description=food.get('description', 'Unknown'),
                data_type=food.get('dataType', 'Unknown'),
                score=food.get('score', 0),
                brand_owner=food.get('brandOwner')
            )
            
            if 'foodNutrients' in food:
                match.nutrition = self._parse_nutrients(food['foodNutrients'])
            
            matches.append(match)
        
        self.status_callback(f"✅ Found {len(matches)} matches for '{query}'")
        return matches
    
    def get_food_details(self, fdc_id: int, original_score: float = 0) -> Optional[USDAFoodMatch]:
        """
        Get detailed nutrition data for a specific food
        
        Args:
            fdc_id: USDA FoodData Central ID
            original_score: Original relevance score from search results (preserved)
            
        Returns:
            USDAFoodMatch with complete nutrition data
        """
        self.status_callback(f"📥 Fetching USDA food details for FDC ID: {fdc_id}")
        
        result = self._make_request('GET', f'/food/{fdc_id}', params={'format': 'full'})
        
        if not result:
            return None
        
        match = USDAFoodMatch(
            fdc_id=result.get('fdcId', fdc_id),
            description=result.get('description', 'Unknown'),
            data_type=result.get('dataType', 'Unknown'),
            score=original_score,
            brand_owner=result.get('brandOwner')
        )
        
        if 'foodNutrients' in result:
            match.nutrition = self._parse_nutrients(result['foodNutrients'])
        
        return match
    
    def _parse_nutrients(self, nutrients: List[Dict]) -> NutritionData:
        """Parse nutrition data from USDA response
        
        USDA has different formats:
        - Search results: {'nutrientId': 1003, 'nutrientName': 'Protein', 'value': 10.7}
        - Food details: {'nutrient': {'id': 1003, 'name': 'Protein'}, 'amount': 10.7}
        """
        nutrition = NutritionData()
        
        nutrient_map = {}
        for nutrient in nutrients:
            nutrient_id = None
            amount = None
            
            if 'nutrient' in nutrient and isinstance(nutrient['nutrient'], dict):
                nutrient_id = nutrient['nutrient'].get('id')
                amount = nutrient.get('amount')
            else:
                nutrient_id = nutrient.get('nutrientId') or nutrient.get('number')
                amount = nutrient.get('amount') or nutrient.get('value')
            
            if nutrient_id and amount is not None:
                nutrient_map[int(nutrient_id)] = amount
        
        nutrition.energy_kcal = nutrient_map.get(self.NUTRIENT_IDS['energy_kcal'])
        nutrition.energy_kj = nutrient_map.get(self.NUTRIENT_IDS['energy_kj'])
        nutrition.fat_total = nutrient_map.get(self.NUTRIENT_IDS['fat_total'])
        nutrition.fat_saturated = nutrient_map.get(self.NUTRIENT_IDS['fat_saturated'])
        nutrition.carbs_total = nutrient_map.get(self.NUTRIENT_IDS['carbs_total'])
        nutrition.carbs_sugars = nutrient_map.get(self.NUTRIENT_IDS['carbs_sugars'])
        nutrition.protein = nutrient_map.get(self.NUTRIENT_IDS['protein'])
        nutrition.fiber = nutrient_map.get(self.NUTRIENT_IDS['fiber'])
        
        sodium_mg = nutrient_map.get(self.NUTRIENT_IDS['sodium'])
        if sodium_mg is not None:
            nutrition.salt = round(sodium_mg * 2.5 / 1000, 3)
        
        if nutrition.energy_kcal and not nutrition.energy_kj:
            nutrition.energy_kj = round(nutrition.energy_kcal * 4.184, 1)
        elif nutrition.energy_kj and not nutrition.energy_kcal:
            nutrition.energy_kcal = round(nutrition.energy_kj / 4.184, 1)
        
        return nutrition
    
    def search_and_get_best_match(self, query: str) -> Optional[USDAFoodMatch]:
        """
        Search for food and return the best match with full nutrition data
        
        Args:
            query: Food name to search (in English)
            
        Returns:
            Best matching USDAFoodMatch with nutrition data, or None if no match
        """
        matches = self.search_food(query, page_size=3)
        
        if not matches:
            return None
        
        best_match = matches[0]
        
        if best_match.nutrition and best_match.nutrition.is_complete():
            return best_match
        
        detailed = self.get_food_details(best_match.fdc_id, original_score=best_match.score)
        if detailed:
            return detailed
        
        return best_match
    
    def search_and_get_top_matches(self, query: str, num_options: int = 3) -> List[USDAFoodMatch]:
        """
        Search for food and return multiple matches with full nutrition data
        
        Args:
            query: Food name to search (in English)
            num_options: Number of options to return (default 3)
            
        Returns:
            List of USDAFoodMatch objects with nutrition data, prioritizing "raw" items
        """
        matches = self.search_food(query, page_size=num_options + 2)
        
        if not matches:
            return []
        
        detailed_matches = []
        for match in matches:
            if match.nutrition and match.nutrition.is_complete():
                detailed_matches.append(match)
            else:
                detailed = self.get_food_details(match.fdc_id, original_score=match.score)
                if detailed:
                    detailed_matches.append(detailed)
                else:
                    detailed_matches.append(match)
        
        valid_matches = []
        for match in detailed_matches:
            if match.nutrition and match.nutrition.energy_kcal and match.nutrition.energy_kcal > 0:
                valid_matches.append(match)
            elif not match.nutrition or match.nutrition.energy_kcal is None:
                pass
            else:
                self.status_callback(f"⚠️ Skipping '{match.description}' - zero energy (bad data)")
        
        def sort_key(m):
            desc_lower = m.description.lower()
            is_raw = 1 if 'raw' in desc_lower else 0
            return (-is_raw, -m.score)
        
        valid_matches.sort(key=sort_key)
        
        return valid_matches[:num_options]


def test_usda_client():
    """Test the USDA client"""
    try:
        client = USDAClient()
        
        print("Testing USDA API connection...")
        matches = client.search_food("ginger root", page_size=3)
        
        if matches:
            print(f"\nFound {len(matches)} matches:")
            for match in matches:
                print(f"  - {match.description} (Score: {match.score:.1f})")
                if match.nutrition:
                    print(f"    Energy: {match.nutrition.energy_kcal} kcal")
                    print(f"    Protein: {match.nutrition.protein} g")
        else:
            print("No matches found")
            
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_usda_client()
