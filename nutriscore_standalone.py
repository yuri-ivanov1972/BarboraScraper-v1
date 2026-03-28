"""
Nutri-Score 2.0 (2024 Official Algorithm) — Standalone Calculator
===================================================================
Self-contained module. No database or external dependencies required.

Supports 5 product categories:
  1. general       — Most foods (cereals, ready meals, dairy, snacks, etc.)
  2. beverage      — All drinks including milk, plant drinks, juices, sodas
  3. cheese        — All cheese varieties
  4. red_meat      — Beef, pork, processed meat, sausages
  5. fats_oils_nuts — Butter, margarine, oils, nuts, seeds

Usage:
    from nutriscore_standalone import calculate, ProductCategory

    result = calculate(
        category=ProductCategory.GENERAL,
        energy_kj=1678,
        sugars_g=26.8,
        saturated_fat_g=1.0,
        salt_g=0.93,
        protein_g=7.6,
        fiber_g=8.0,
    )
    print(result.grade)    # "D"
    print(result.score)    # 11
    print(result.summary)  # human-readable breakdown

Official source:
    Santé Publique France — https://www.santepubliquefrance.fr/determinants-de-sante/nutrition-et-activite-physique/nutri-score
    Scientific paper (Nature Food, 2024) — https://doi.org/10.1038/s43016-024-00920-3
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums & Data Classes
# ---------------------------------------------------------------------------

class ProductCategory(str, Enum):
    GENERAL = "general"
    BEVERAGE = "beverage"
    CHEESE = "cheese"
    RED_MEAT = "red_meat"
    FATS_OILS_NUTS = "fats_oils_nuts"


@dataclass
class NutriscoreComponents:
    """Points breakdown for each nutrient component."""
    # Negative (bad) components
    energy_pts: int = 0
    sugars_pts: int = 0
    saturated_fat_pts: int = 0
    salt_pts: int = 0
    sweetener_pts: int = 0       # beverages only: +4 if artificial sweeteners present
    total_negative: int = 0

    # Positive (good) components
    protein_pts: int = 0
    fiber_pts: int = 0
    fvl_pts: int = 0             # fruits / vegetables / legumes
    total_positive: int = 0

    # Protein blocking
    protein_blocked: bool = False
    protein_status: str = "included"


@dataclass
class NutriscoreResult:
    """Full result of a Nutri-Score calculation."""
    grade: str                        # "A" through "E"
    score: int                        # final numeric score
    category: ProductCategory
    components: NutriscoreComponents = field(default_factory=NutriscoreComponents)
    has_sweeteners: bool = False
    fvl_percent: float = 0.0

    @property
    def color(self) -> str:
        return {
            "A": "dark green",
            "B": "light green",
            "C": "yellow",
            "D": "orange",
            "E": "red",
        }[self.grade]

    @property
    def summary(self) -> str:
        c = self.components
        lines = [
            f"Nutri-Score {self.grade}  (score: {self.score})  [{self.color}]",
            f"Category   : {self.category.value}",
            f"",
            f"Negative points  (N = {c.total_negative})",
            f"  Energy          : {c.energy_pts} pts",
            f"  Sugars          : {c.sugars_pts} pts",
            f"  Saturated fat   : {c.saturated_fat_pts} pts",
            f"  Salt            : {c.salt_pts} pts",
        ]
        if c.sweetener_pts:
            lines.append(f"  Sweetener penalty: {c.sweetener_pts} pts")
        lines += [
            f"",
            f"Positive points  (P = {c.total_positive})",
            f"  Protein         : {c.protein_pts} pts  [{c.protein_status}]",
            f"  Fiber           : {c.fiber_pts} pts",
            f"  Fruit/Veg/Legumes: {c.fvl_pts} pts  ({self.fvl_percent:.0f}%)",
            f"",
            f"Final score = N - P = {c.total_negative} - {c.total_positive} = {self.score}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scoring tables (all per 100 g / 100 ml)
# ---------------------------------------------------------------------------

# Negative components — General / Red Meat / Cheese
_T_ENERGY_GEN   = [335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350]   # kJ
_T_SUGARS_GEN   = [3.4, 6.8, 10, 14, 17, 20, 24, 27, 31, 34, 37, 41, 44, 48, 51]  # g
_T_SATFAT_GEN   = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]                               # g
_T_SALT_GEN     = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0,
                   2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0]           # g

# Negative components — Beverages
_T_ENERGY_BEV   = [30, 90, 150, 210, 240, 270, 300, 330, 360, 390]              # kJ
_T_SUGARS_BEV   = [0.5, 2, 3.5, 5, 6, 7, 8, 9, 10, 11]                         # g

# Positive components — General / Red Meat / Cheese
_T_FIBER_GEN    = [3.0, 4.1, 5.2, 6.3, 7.4]                                     # g (0–5 pts)
_T_PROTEIN_GEN  = [2.4, 4.8, 7.2, 9.6, 12, 14, 17]                             # g (0–7 pts)
_T_FVL_GEN      = [40, 60, 80]                                                   # % (0→0, 1→1, 2→2, 3→5)

# Positive components — Beverages
_T_FIBER_BEV    = [3, 4.1, 5.2, 6.3, 7.4]                                       # g
_T_PROTEIN_BEV  = [1.2, 1.5, 1.8, 2.1, 2.4, 2.7, 3.0]                         # g
_T_FVL_BEV      = [40, 60, 80]                                                   # %

# Fats / Oils / Nuts — saturated fat expressed as energy (sat_fat_g × 37 kJ)
_T_SATFAT_FAT_ENERGY = [i * 120 for i in range(1, 11)]                          # 120..1200 kJ
# Fats / Oils / Nuts — ratio saturated/total fat (%)
_T_SATFAT_RATIO = [10, 16, 22, 28, 34, 40, 46, 52, 58, 64]


# ---------------------------------------------------------------------------
# Sweetener keywords (Latvian + English + E-numbers)
# ---------------------------------------------------------------------------

_SWEETENER_KEYWORDS = [
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
    'sweetener', 'artificial sweetener',
    'zero', 'light', 'diet', 'bez cukura', 'sugar free', 'sugar-free',
    'bezkaloriju', 'bez kalorijām',
    'e950', 'e951', 'e952', 'e953', 'e954', 'e955',
    'e957', 'e959', 'e960', 'e961', 'e962', 'e965',
    'e966', 'e967', 'e968', 'e969',
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pts(value: float, thresholds: list) -> int:
    """
    Return points for a value against an ordered list of upper limits.
    Points = index of the first threshold the value does NOT exceed.
    If value exceeds all thresholds → points = len(thresholds).
    """
    for pts, limit in enumerate(thresholds):
        if value <= limit:
            return pts
    return len(thresholds)


def detect_sweeteners(product_name: str = "", ingredients_text: str = "") -> bool:
    """
    Return True if the product likely contains artificial sweeteners.
    Checks product name and ingredients against a keyword list.
    """
    text = (product_name + " " + ingredients_text).lower()
    return any(kw in text for kw in _SWEETENER_KEYWORDS)


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def calculate(
    category: ProductCategory,
    energy_kj: float,
    sugars_g: float,
    saturated_fat_g: float,
    salt_g: float,
    protein_g: float,
    fiber_g: float = 0.0,
    total_fat_g: Optional[float] = None,
    fvl_percent: float = 0.0,
    has_sweeteners: Optional[bool] = None,
    product_name: str = "",
    ingredients_text: str = "",
) -> NutriscoreResult:
    """
    Calculate Nutri-Score 2.0 (2024 algorithm) for a single product.

    Parameters
    ----------
    category         : ProductCategory enum value
    energy_kj        : Energy in kJ per 100 g (or 100 ml for beverages)
    sugars_g         : Total sugars in g per 100 g
    saturated_fat_g  : Saturated fat in g per 100 g
    salt_g           : Salt in g per 100 g  (NOT sodium — multiply Na(mg) × 0.0025)
    protein_g        : Protein in g per 100 g
    fiber_g          : Dietary fiber in g per 100 g  (default 0)
    total_fat_g      : Total fat in g per 100 g (required for fats_oils_nuts)
    fvl_percent      : % of fruit / vegetables / legumes in the product (0–100)
                       Use 100 for fresh fruit/veg, 50 for canned/preserved,
                       0 for everything else.
    has_sweeteners   : True/False override; None = auto-detect from text
    product_name     : Used for sweetener auto-detection (beverages)
    ingredients_text : Used for sweetener auto-detection (beverages)

    Returns
    -------
    NutriscoreResult with grade (A–E), score, and full components breakdown.
    """
    # --- Sweetener detection (beverages only) ---
    if has_sweeteners is None:
        if category == ProductCategory.BEVERAGE:
            has_sweeteners = detect_sweeteners(product_name, ingredients_text)
        else:
            has_sweeteners = False

    c = NutriscoreComponents()

    # -----------------------------------------------------------------------
    # N points (negative / bad nutrients)
    # -----------------------------------------------------------------------
    if category == ProductCategory.BEVERAGE:
        c.energy_pts       = _pts(energy_kj,       _T_ENERGY_BEV)
        c.sugars_pts       = _pts(sugars_g,         _T_SUGARS_BEV)
        c.saturated_fat_pts= _pts(saturated_fat_g,  _T_SATFAT_GEN)
        c.salt_pts         = _pts(salt_g,           _T_SALT_GEN)
        c.sweetener_pts    = 4 if has_sweeteners else 0
        c.total_negative   = (c.energy_pts + c.sugars_pts +
                              c.saturated_fat_pts + c.salt_pts + c.sweetener_pts)

    elif category == ProductCategory.FATS_OILS_NUTS:
        energy_from_sat    = saturated_fat_g * 37
        c.energy_pts       = _pts(energy_from_sat, _T_SATFAT_FAT_ENERGY)
        ratio              = (saturated_fat_g / total_fat_g * 100
                              if total_fat_g and total_fat_g > 0 else 0)
        c.saturated_fat_pts= _pts(ratio,            _T_SATFAT_RATIO)
        c.sugars_pts       = _pts(sugars_g,         _T_SUGARS_GEN)
        c.salt_pts         = _pts(salt_g,           _T_SALT_GEN)
        c.total_negative   = (c.energy_pts + c.sugars_pts +
                              c.saturated_fat_pts + c.salt_pts)

    else:   # general / cheese / red_meat
        c.energy_pts       = _pts(energy_kj,        _T_ENERGY_GEN)
        c.sugars_pts       = _pts(sugars_g,          _T_SUGARS_GEN)
        c.saturated_fat_pts= _pts(saturated_fat_g,   _T_SATFAT_GEN)
        c.salt_pts         = _pts(salt_g,            _T_SALT_GEN)
        c.total_negative   = (c.energy_pts + c.sugars_pts +
                              c.saturated_fat_pts + c.salt_pts)

    # -----------------------------------------------------------------------
    # P points (positive / good nutrients)
    # -----------------------------------------------------------------------
    if category == ProductCategory.BEVERAGE:
        c.protein_pts  = _pts(protein_g,  _T_PROTEIN_BEV)
        c.fiber_pts    = _pts(fiber_g,    _T_FIBER_BEV)
        fvl_raw        = _pts(fvl_percent, _T_FVL_BEV)
        c.fvl_pts      = [0, 2, 4, 6][fvl_raw] if fvl_raw <= 3 else 6
    elif category == ProductCategory.FATS_OILS_NUTS:
        c.protein_pts  = _pts(protein_g,  _T_PROTEIN_GEN)
        c.fiber_pts    = _pts(fiber_g,    _T_FIBER_GEN)
        fvl_raw        = _pts(fvl_percent, _T_FVL_GEN)
        c.fvl_pts      = 5 if fvl_raw == 3 else fvl_raw
    else:   # general / cheese / red_meat
        protein_raw    = _pts(protein_g,  _T_PROTEIN_GEN)
        if category == ProductCategory.RED_MEAT:
            c.protein_pts   = min(protein_raw, 2)
            c.protein_status = (f"capped at 2 (raw was {protein_raw})"
                                if protein_raw > 2 else "included")
        else:
            c.protein_pts   = protein_raw
        c.fiber_pts    = _pts(fiber_g,    _T_FIBER_GEN)
        fvl_raw        = _pts(fvl_percent, _T_FVL_GEN)
        c.fvl_pts      = 5 if fvl_raw == 3 else fvl_raw

    c.total_positive = c.protein_pts + c.fiber_pts + c.fvl_pts

    # -----------------------------------------------------------------------
    # Preliminary score
    # -----------------------------------------------------------------------
    score = c.total_negative - c.total_positive

    # -----------------------------------------------------------------------
    # Protein blocking rule
    # Applies to: general and red_meat (NOT cheese, NOT beverage)
    # Rule: if N >= 11 AND fvl_pts < 5, protein does NOT count
    # -----------------------------------------------------------------------
    if category not in (ProductCategory.CHEESE, ProductCategory.BEVERAGE):
        if c.total_negative >= 11 and c.fvl_pts < 5:
            c.protein_blocked = True
            c.protein_status  = f"blocked (N={c.total_negative}, FVL={c.fvl_pts})"
            c.total_positive  = c.fiber_pts + c.fvl_pts
            score             = c.total_negative - c.total_positive

    # -----------------------------------------------------------------------
    # Grade thresholds
    # -----------------------------------------------------------------------
    if category == ProductCategory.BEVERAGE:
        # Water / plain unsweetened beverages → always A
        if energy_kj == 0 and sugars_g == 0 and not has_sweeteners:
            grade = "A"
        elif score <= 2:
            grade = "B"
        elif score <= 6:
            grade = "C"
        elif score <= 9:
            grade = "D"
        else:
            grade = "E"

    elif category == ProductCategory.FATS_OILS_NUTS:
        if score <= -6:
            grade = "A"
        elif score <= 2:
            grade = "B"
        elif score <= 10:
            grade = "C"
        elif score <= 18:
            grade = "D"
        else:
            grade = "E"

    else:   # general / cheese / red_meat  (same thresholds)
        if score <= -1:
            grade = "A"
        elif score <= 2:
            grade = "B"
        elif score <= 10:
            grade = "C"
        elif score <= 18:
            grade = "D"
        else:
            grade = "E"

    return NutriscoreResult(
        grade=grade,
        score=score,
        category=category,
        components=c,
        has_sweeteners=has_sweeteners,
        fvl_percent=fvl_percent,
    )


# ---------------------------------------------------------------------------
# Convenience: sodium → salt conversion
# ---------------------------------------------------------------------------

def sodium_mg_to_salt_g(sodium_mg: float) -> float:
    """Convert sodium (mg/100g) to salt (g/100g). Salt = Na × 2.5 / 1000."""
    return sodium_mg * 2.5 / 1000


# ---------------------------------------------------------------------------
# Self-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Nutri-Score 2.0 (2024) — Standalone Calculator Demo")
    print("=" * 60)

    tests = [
        {
            "label": "Corn Flakes with honey & nuts (General)",
            "kwargs": dict(
                category=ProductCategory.GENERAL,
                energy_kj=1678, sugars_g=26.8, saturated_fat_g=1.0,
                salt_g=0.93, protein_g=7.6, fiber_g=8.0,
            ),
            "expected": ("D", 11),
        },
        {
            "label": "High-fiber bran cereal (General)",
            "kwargs": dict(
                category=ProductCategory.GENERAL,
                energy_kj=1180, sugars_g=18.0, saturated_fat_g=0.8,
                salt_g=0.6, protein_g=12.0, fiber_g=14.0,
            ),
            "expected": None,
        },
        {
            "label": "Camembert cheese (Cheese — protein never blocked)",
            "kwargs": dict(
                category=ProductCategory.CHEESE,
                energy_kj=1200, sugars_g=0.5, saturated_fat_g=18.0,
                salt_g=1.5, protein_g=20.0, fiber_g=0.0,
            ),
            "expected": None,
        },
        {
            "label": "Olive oil (Fats/Oils/Nuts — uses sat/fat ratio)",
            "kwargs": dict(
                category=ProductCategory.FATS_OILS_NUTS,
                energy_kj=3700, sugars_g=0.0, saturated_fat_g=14.0,
                salt_g=0.0, protein_g=0.0, fiber_g=0.0, total_fat_g=100.0,
            ),
            "expected": None,
        },
        {
            "label": "Diet cola (Beverage — sweetener +4 penalty)",
            "kwargs": dict(
                category=ProductCategory.BEVERAGE,
                energy_kj=4, sugars_g=0.0, saturated_fat_g=0.0,
                salt_g=0.0, protein_g=0.0, has_sweeteners=True,
            ),
            "expected": None,
        },
        {
            "label": "Still water (Beverage — only A-grade beverage)",
            "kwargs": dict(
                category=ProductCategory.BEVERAGE,
                energy_kj=0, sugars_g=0.0, saturated_fat_g=0.0,
                salt_g=0.0, protein_g=0.0,
            ),
            "expected": ("A", 0),
        },
        {
            "label": "Beef steak (Red Meat — protein capped at 2 pts)",
            "kwargs": dict(
                category=ProductCategory.RED_MEAT,
                energy_kj=800, sugars_g=0.0, saturated_fat_g=5.0,
                salt_g=0.2, protein_g=25.0, fiber_g=0.0,
            ),
            "expected": None,
        },
        {
            "label": "Fresh apple (General — 100% FVL unlocks protein)",
            "kwargs": dict(
                category=ProductCategory.GENERAL,
                energy_kj=218, sugars_g=10.4, saturated_fat_g=0.03,
                salt_g=0.001, protein_g=0.3, fiber_g=2.4, fvl_percent=100,
            ),
            "expected": ("A", -2),
        },
    ]

    for t in tests:
        r = calculate(**t["kwargs"])
        status = ""
        if t["expected"]:
            ok = (r.grade == t["expected"][0] and r.score == t["expected"][1])
            status = " ✓" if ok else f" ✗ expected {t['expected']}"
        print(f"\n{t['label']}")
        print(f"  Grade: {r.grade}   Score: {r.score}   ({r.color}){status}")
        print(f"  N={r.components.total_negative}  P={r.components.total_positive}"
              f"  protein={r.components.protein_status}")

    print("\n" + "=" * 60)
    print("Done.")
