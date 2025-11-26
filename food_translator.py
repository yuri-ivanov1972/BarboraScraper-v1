"""
Food Name Translator: Latvian to English

Provides translation of Latvian food names to English for USDA API search.
Uses a local dictionary for common terms with optional Google Cloud Translation fallback.
"""

import os
import re
from typing import Optional, Tuple
from dataclasses import dataclass


LATVIAN_TO_ENGLISH = {
    'āboli': 'apples',
    'ābols': 'apple',
    'apelsīni': 'oranges',
    'apelsīns': 'orange',
    'aprikozes': 'apricots',
    'aprikoze': 'apricot',
    'arbūzi': 'watermelon',
    'arbūzs': 'watermelon',
    'avenes': 'raspberries',
    'avene': 'raspberry',
    'avokado': 'avocado',
    'baklažāni': 'eggplant',
    'baklažāns': 'eggplant',
    'banāni': 'bananas',
    'banāns': 'banana',
    'biezpiens': 'cottage cheese',
    'bietes': 'beets',
    'biete': 'beet',
    'brokoļi': 'broccoli',
    'bumbieri': 'pears',
    'bumbieris': 'pear',
    'burkāni': 'carrots',
    'burkāns': 'carrot',
    'citroni': 'lemons',
    'citrons': 'lemon',
    'cukini': 'zucchini',
    'dzērvenes': 'cranberries',
    'dzērvene': 'cranberry',
    'greipfrūti': 'grapefruit',
    'greipfrūts': 'grapefruit',
    'ķirbji': 'pumpkin',
    'ķirbis': 'pumpkin',
    'dārzeņi': 'vegetables',
    'dilles': 'dill',
    'gaļa': 'meat',
    'gurķi': 'cucumbers',
    'gurķis': 'cucumber',
    'ingvers': 'ginger',
    'jogurts': 'yogurt',
    'kabači': 'squash',
    'kāposti': 'cabbage',
    'kartupeļi': 'potatoes',
    'kartupelis': 'potato',
    'ķiploki': 'garlic',
    'ķiploks': 'garlic',
    'ķirši': 'cherries',
    'ķirsis': 'cherry',
    'kivi': 'kiwi',
    'krējums': 'sour cream',
    'lapu salāti': 'leaf lettuce',
    'lauki': 'field',
    'lejami': 'pourable',
    'lasis': 'salmon',
    'laša': 'salmon',
    'liellopa': 'beef',
    'liellopu': 'beef',
    'lietoņi': 'nectarines',
    'lietoņa': 'nectarine',
    'maize': 'bread',
    'mango': 'mango',
    'mandarīni': 'mandarins',
    'mandarīns': 'mandarin',
    'medus': 'honey',
    'mellenes': 'blueberries',
    'mellene': 'blueberry',
    'melone': 'melon',
    'mērce': 'sauce',
    'milti': 'flour',
    'persiki': 'peaches',
    'persiks': 'peach',
    'pomelo': 'pomelo',
    'olas': 'eggs',
    'ola': 'egg',
    'olīveļļa': 'olive oil',
    'olīvas': 'olives',
    'papriki': 'bell peppers',
    'paprika': 'bell pepper',
    'pētersīļi': 'parsley',
    'piens': 'milk',
    'piena': 'milk',
    'pipari': 'pepper',
    'plūmes': 'plums',
    'plūme': 'plum',
    'pupiņas': 'beans',
    'pupas': 'beans',
    'rabarberi': 'rhubarb',
    'redīsi': 'radishes',
    'redīss': 'radish',
    'rieksti': 'nuts',
    'rieksts': 'nut',
    'rīsi': 'rice',
    'rozīnes': 'raisins',
    'rukola': 'arugula',
    'salāti': 'lettuce',
    'salāts': 'lettuce',
    'saldējums': 'ice cream',
    'selerija': 'celery',
    'siers': 'cheese',
    'sīpoli': 'onions',
    'sīpols': 'onion',
    'spināti': 'spinach',
    'sulas': 'juice',
    'sula': 'juice',
    'sēnes': 'mushrooms',
    'sēne': 'mushroom',
    'šampinjoni': 'button mushrooms',
    'tomāti': 'tomatoes',
    'tomāts': 'tomato',
    'ūdens': 'water',
    'vīnogas': 'grapes',
    'vīnoga': 'grape',
    'vistas': 'chicken',
    'vista': 'chicken',
    'zemeņi': 'strawberries',
    'zemene': 'strawberry',
    'zivis': 'fish',
    'zivs': 'fish',
    'žāvēts': 'dried',
    'sālīts': 'salted',
    'marinēts': 'marinated',
    'kūpināts': 'smoked',
    'svaigs': 'fresh',
    'saldēts': 'frozen',
    'konservēts': 'canned',
    'bio': 'organic',
    'ekoloģisks': 'organic',
    'zaļi': 'green',
    'zaļš': 'green',
    'sarkani': 'red',
    'sarkans': 'red',
    'dzelteni': 'yellow',
    'dzeltens': 'yellow',
    'balti': 'white',
    'balts': 'white',
    'melni': 'black',
    'melns': 'black',
    'sviests': 'butter',
    'sviestsmaize': 'butter bread',
    'pankūkas': 'pancakes',
    'makaroni': 'pasta',
    'nūdeles': 'noodles',
    'cūkgaļa': 'pork',
    'jēra': 'lamb',
    'jērs': 'lamb',
    'tītars': 'turkey',
    'pīle': 'duck',
    'aknas': 'liver',
    'desa': 'sausage',
    'šķiņķis': 'ham',
    'bekons': 'bacon',
    'zirņi': 'peas',
    'pupas': 'beans',
    'lēcas': 'lentils',
    'auzu': 'oat',
    'auzas': 'oats',
    'griķi': 'buckwheat',
    'manna': 'semolina',
    'kuskuss': 'couscous',
    'kefīrs': 'kefir',
    'paniņas': 'buttermilk',
    'skābais': 'sour',
    'saldais': 'sweet',
    'rūgts': 'bitter',
    'pikantas': 'spicy',
    'cepts': 'fried',
    'vārīts': 'boiled',
    'sautēts': 'sauteed',
    'grilēts': 'grilled',
    'cepti': 'fried',
    'vārīti': 'boiled',
    'fasēti': 'packaged',
    'fasēts': 'packaged',
    'sverami': 'bulk',
    'sverams': 'bulk',
    'gabals': 'piece',
    'gab': 'piece',
    'maisījums': 'mix',
    'pulveris': 'powder',
    'granulas': 'granules',
    'pārslas': 'flakes',
    'sīrups': 'syrup',
    'eļļa': 'oil',
    'etiķis': 'vinegar',
    'sāls': 'salt',
    'cukurs': 'sugar',
    'kanēlis': 'cinnamon',
    'piparmētra': 'peppermint',
    'baziliks': 'basil',
    'oregano': 'oregano',
    'rozmarīns': 'rosemary',
    'timiāns': 'thyme',
    'lauru': 'bay',
    'laurus': 'bay leaves',
    'kurkuma': 'turmeric',
    'karijs': 'curry',
    'ķimenes': 'caraway',
    'muskatrieksts': 'nutmeg',
    'krustnagliņas': 'cloves',
    'ingvera': 'ginger',
    'čili': 'chili',
    'pelēki': 'grey',
    'pelēks': 'grey',
    'krāsains': 'colored',
    'dabīgs': 'natural',
    'mākslīgs': 'artificial',
    'bezglutēna': 'gluten-free',
    'vegāns': 'vegan',
    'veģetārs': 'vegetarian',
    'laktozes': 'lactose',
    'bez': 'without',
    'ar': 'with',
    'sausais': 'dry',
    'mitrs': 'moist',
    'mīksts': 'soft',
    'ciets': 'hard',
    'kraukšķīgs': 'crispy',
    'žāvēti': 'dried',
    'kandēti': 'candied',
    'plānais': 'thin',
    'biezais': 'thick',
    'smalkais': 'fine',
    'rupjais': 'coarse',
    'pilngraudu': 'whole grain',
    'baltmaize': 'white bread',
    'rudzu': 'rye',
    'kviešu': 'wheat',
    'speltas': 'spelt',
    'kukurūzas': 'corn',
    'rīsu': 'rice',
    'kartupeļu': 'potato',
    'sojā': 'soy',
    'sojas': 'soy',
    'kokosriekstu': 'coconut',
    'kokoss': 'coconut',
    'mandeles': 'almonds',
    'mandele': 'almond',
    'valrieksti': 'walnuts',
    'valrieksts': 'walnut',
    'lazdu': 'hazelnut',
    'lazdas': 'hazelnuts',
    'zemesrieksti': 'peanuts',
    'zemesrieksts': 'peanut',
    'pistācijas': 'pistachios',
    'keškjū': 'cashews',
    'ananāss': 'pineapple',
    'ananāsi': 'pineapple',
    'papaja': 'papaya',
    'granātābols': 'pomegranate',
    'persiki': 'peaches',
    'persiks': 'peach',
    'nektarīns': 'nectarine',
    'aprikozes': 'apricots',
    'aprikoze': 'apricot',
    'mellenes': 'blueberries',
    'mellene': 'blueberry',
    'avenes': 'raspberries',
    'avene': 'raspberry',
    'kazenes': 'blackberries',
    'kazene': 'blackberry',
    'dzērvenes': 'cranberries',
    'dzērvene': 'cranberry',
    'upenes': 'black currants',
    'jāņogas': 'red currants',
    'ērkšķogas': 'gooseberries',
    'dateles': 'dates',
    'datele': 'date',
    'vīģes': 'figs',
    'vīģe': 'fig',
}

WEIGHT_PATTERNS = [
    r'\b(\d+(?:[.,]\d+)?)\s*kg\b',
    r'\b(\d+(?:[.,]\d+)?)\s*g\b',
    r'\b(\d+(?:[.,]\d+)?)\s*ml\b',
    r'\b(\d+(?:[.,]\d+)?)\s*l\b',
    r'\b(\d+(?:[.,]\d+)?)\s*gab\.?\b',
    r'\b(\d+(?:[.,]\d+)?)\s*gb\.?\b',
    r'\b(\d+(?:[.,]\d+)?)\s*tk\.?\b',
    r'\bkg\b',
    r'\bgab\b',
    r'\bgb\b',
    r'\bI Love Eco\b',
    r'\bBIO\b',
    r'\bECO\b',
    r'\bRIMI\b',
    r'\bLauksaimniecība\s+ES\b',
    r'\b\d+-\d+g/gab\b',
    r'sverami?\b',
    r'\bA/M\b',
    r'\bA/LM\b',
    r'\bA/LMS\b',
    r'\bA/ML\b',
    r'\bA/S\b',
    r'\bNr\.?\s*\d+\b',
    r'\bOluksne\b',
    r'\bkūtī\b',
    r'\bdētas\b',
    r'\blauksaimniecības\b',
    r'\bbioloģiskās\b',
    r'\bbrīv\.?apst\.?\b',
    r'\bb/k\b',
    r'\bITUM\b',
    r'\b\d+\.\s*šķ\.?\b',
    r'\bgaišās\b',
    r'\btumšās\b',
    r'\bsarkanās\b',
    r'\bzaļās\b',
    r'\bSprīdīši\b',
    r'\bGranny\s+Smith\b',
    r'\bRoyal\s+Gala\b',
    r'\bGolden\b',
    r'\bFuji\b',
    r'\bPink\s+Lady\b',
    r'\bRed\s+Delicious\b',
    r'\bConference\b',
    r'\bPackham\b',
    r'\bAbate\s+Fetel\b',
    r'\bWilliams\b',
    r'\bComice\b',
    r'\bBartlett\b',
    r'\b\d+-\d+\s*mm\b',
    r'\b1\.šķira\b',
    r'\b2\.šķira\b',
]


@dataclass
class TranslationResult:
    """Result of food name translation"""
    original: str
    english: str
    method: str
    confidence: float
    
    def to_dict(self):
        return {
            'original': self.original,
            'english': self.english,
            'method': self.method,
            'confidence': self.confidence
        }


class FoodTranslator:
    """
    Translates Latvian food names to English
    
    Uses a local dictionary for common terms with optional Google Cloud Translation fallback.
    """
    
    def __init__(self, google_api_key: Optional[str] = None, status_callback=None):
        self.google_api_key = google_api_key or os.environ.get('GOOGLE_TRANSLATE_API_KEY')
        self.status_callback = status_callback or print
        self.dictionary = LATVIAN_TO_ENGLISH
        self._google_client = None
    
    def _normalize_name(self, name: str) -> str:
        """Remove weight, quantity, and brand patterns from product name"""
        normalized = name.lower()
        
        for pattern in WEIGHT_PATTERNS:
            normalized = re.sub(pattern, ' ', normalized, flags=re.IGNORECASE)
        
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def _translate_with_dictionary(self, text: str) -> Tuple[str, float]:
        """Translate using local dictionary
        
        Uses exact matching first, then careful partial matching with:
        - Minimum word length requirements to prevent false positives
        - Overlap threshold to ensure meaningful matches
        """
        words = text.lower().split()
        translated_words = []
        matches = 0
        
        for word in words:
            word_clean = word.strip('.,;:!?()[]{}')
            
            if not word_clean:
                continue
            
            if word_clean in self.dictionary:
                translated_words.append(self.dictionary[word_clean])
                matches += 1
            else:
                found_partial = False
                
                if len(word_clean) >= 4:
                    for lv, en in self.dictionary.items():
                        if len(lv) >= 4:
                            if lv in word_clean:
                                overlap_ratio = len(lv) / len(word_clean)
                                if overlap_ratio >= 0.6:
                                    translated_words.append(en)
                                    matches += 0.7
                                    found_partial = True
                                    break
                            elif word_clean in lv:
                                overlap_ratio = len(word_clean) / len(lv)
                                if overlap_ratio >= 0.6:
                                    translated_words.append(en)
                                    matches += 0.7
                                    found_partial = True
                                    break
                
                if not found_partial:
                    if word_clean.isalpha() and len(word_clean) > 2:
                        translated_words.append(word_clean)
        
        confidence = matches / len(words) if words else 0
        return ' '.join(translated_words), min(confidence, 1.0)
    
    def _translate_with_google(self, text: str) -> Optional[str]:
        """Translate using Google Cloud Translation API"""
        if not self.google_api_key:
            return None
        
        try:
            import requests
            
            url = "https://translation.googleapis.com/language/translate/v2"
            params = {
                'key': self.google_api_key,
                'q': text,
                'source': 'lv',
                'target': 'en',
                'format': 'text'
            }
            
            response = requests.post(url, data=params, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                translated = result['data']['translations'][0]['translatedText']
                self.status_callback(f"🌐 Google translated: '{text}' → '{translated}'")
                return translated
            else:
                self.status_callback(f"⚠️ Google Translate error: {response.status_code}")
                return None
                
        except Exception as e:
            self.status_callback(f"⚠️ Google Translate failed: {str(e)}")
            return None
    
    def translate(self, product_name: str, use_google_fallback: bool = True) -> TranslationResult:
        """
        Translate a Latvian product name to English
        
        Args:
            product_name: Latvian product name (e.g., "Ingvers kg")
            use_google_fallback: Whether to use Google Translate for unknown terms
            
        Returns:
            TranslationResult with English name and confidence
        """
        normalized = self._normalize_name(product_name)
        self.status_callback(f"🔤 Translating: '{product_name}' → normalized: '{normalized}'")
        
        dict_translation, confidence = self._translate_with_dictionary(normalized)
        
        if confidence >= 0.7:
            self.status_callback(f"✅ Dictionary translation: '{dict_translation}' (confidence: {confidence:.0%})")
            return TranslationResult(
                original=product_name,
                english=dict_translation,
                method='dictionary',
                confidence=confidence
            )
        
        if use_google_fallback and self.google_api_key:
            google_translation = self._translate_with_google(normalized)
            if google_translation:
                return TranslationResult(
                    original=product_name,
                    english=google_translation,
                    method='google',
                    confidence=0.9
                )
        
        if dict_translation:
            self.status_callback(f"⚠️ Partial dictionary translation: '{dict_translation}' (confidence: {confidence:.0%})")
            return TranslationResult(
                original=product_name,
                english=dict_translation,
                method='dictionary_partial',
                confidence=confidence
            )
        
        self.status_callback(f"⚠️ No translation found, using normalized: '{normalized}'")
        return TranslationResult(
            original=product_name,
            english=normalized,
            method='passthrough',
            confidence=0.1
        )
    
    def add_to_dictionary(self, latvian: str, english: str):
        """Add a new translation to the dictionary"""
        self.dictionary[latvian.lower()] = english.lower()
        self.status_callback(f"📚 Added to dictionary: '{latvian}' → '{english}'")


def test_translator():
    """Test the food translator"""
    translator = FoodTranslator()
    
    test_names = [
        "Ingvers kg",
        "Burkāni sverami kg",
        "Cukini zaļi 325-375g/gab kg",
        "Ķirbji sviesta kg",
        "Tomāti sarkani kg",
        "Banāni 1kg",
        "Āboli Jonagold kg",
        "Biezpiens 9% 400g",
        "Vistas fileja kg",
        "Lasis svaigs kg"
    ]
    
    print("Testing food name translations:\n")
    for name in test_names:
        result = translator.translate(name, use_google_fallback=False)
        print(f"  {name}")
        print(f"    → {result.english} ({result.method}, {result.confidence:.0%})")
        print()


if __name__ == "__main__":
    test_translator()
