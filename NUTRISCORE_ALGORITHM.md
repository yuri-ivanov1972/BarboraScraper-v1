# Nutri-Score 2.0 (2024) — Algorithm Reference

Complete technical reference for building a standalone Nutri-Score calculator.  
Official source: [Santé Publique France](https://www.santepubliquefrance.fr/determinants-de-sante/nutrition-et-activite-physique/nutri-score)  
Scientific paper: [Nature Food, Feb 2024](https://doi.org/10.1038/s43016-024-00920-3)

Boundary/fats corrections checked against [Santé publique France's updated-algorithm
FAQ, 17 March 2025, tables 7–8](https://www.santepubliquefrance.fr/sites/default/files/rdd/document/FAQ-updatedAlgo-V11.pdf).
This reference describes the project's implementation, including the separately
retained general-food five-FVL-point protein exemption noted in §8.

---

## 1. Overview

The Nutri-Score ranks food products from **A** (best) to **E** (worst) using a points-based algorithm applied to nutritional values per 100 g (or 100 ml for beverages).

**Formula:**
```
Final Score = N_points − P_points
```

- **N (negative)** — energy, sugars, saturated fat, salt. Higher = worse.
- **P (positive)** — protein, fiber, fruits/vegetables/legumes. Higher = better.

---

## 2. Product Categories

Every product must be assigned to one of five categories before calculating. The category determines which scoring tables and special rules apply.

| Category | Examples |
|---|---|
| `general` | Cereals, ready meals, yoghurt, snacks, bread, pasta, dairy (non-beverage) |
| `beverage` | Water, juices, sodas, milk, plant drinks, energy drinks, smoothies |
| `cheese` | All hard, soft, and processed cheese varieties |
| `red_meat` | Beef, pork, lamb, processed meat, sausages, bacon, deli meats |
| `fats_oils_nuts` | Butter, margarine, all vegetable oils, nuts, seeds |

---

## 3. Input Values

All values are **per 100 g** (solids) or **per 100 ml** (beverages).

| Parameter | Unit | Notes |
|---|---|---|
| `energy_kj` | kJ | Use kJ, not kcal |
| `sugars_g` | g | Total sugars |
| `saturated_fat_g` | g | Saturated fat only |
| `salt_g` | g | Direct salt. To convert from sodium: `salt = Na(mg) × 2.5 / 1000` |
| `protein_g` | g | Total protein |
| `fiber_g` | g | Dietary fiber (default 0 if unknown) |
| `total_fat_g` | g | Required only for `fats_oils_nuts` category |
| `fvl_percent` | % | % fruit / vegetables / legumes content (see §6) |
| `has_sweeteners` | bool | Beverages only. True if artificial sweeteners present |

---

## 4. Negative Points (N)

### 4a. General / Cheese / Red Meat

| Component | Thresholds (points 0 → max) | Max pts |
|---|---|---|
| Energy (kJ) | 335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350 | 10 |
| Sugars (g) | 3.4, 6.8, 10, 14, 17, 20, 24, 27, 31, 34, 37, 41, 44, 48, 51 | 15 |
| Saturated fat (g) | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 | 10 |
| Salt (g) | 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0 | 20 |

**How to read the table:** if the value is ≤ threshold[0], score = 0; if ≤ threshold[1], score = 1; and so on. If value exceeds all thresholds, score = number of thresholds.

Example — Sugars 26.8 g: exceeds 24 (index 6) but ≤ 27 (index 7) → **7 points**

### 4b. Beverages

| Component | Thresholds | Max pts |
|---|---|---|
| Energy (kJ) | 30, 90, 150, 210, 240, 270, 300, 330, 360, 390 | 10 |
| Sugars (g) | 0.5, 2, 3.5, 5, 6, 7, 8, 9, 10, 11 | 10 |
| Saturated fat (g) | same as general | 10 |
| Salt (g) | same as general | 20 |
| **Sweetener penalty** | **+4 pts flat if any artificial sweetener is present** | — |

### 4c. Fats / Oils / Nuts (different approach for energy and sat fat)

Instead of using raw energy and saturated fat values, two modified indicators are used:

**Energy from saturated fat** (replaces energy component):
```
energy_from_satfat = saturated_fat_g × 37
thresholds: 120, 240, 360, 480, 600, 720, 840, 960, 1080, 1200  (kJ)
```

**Saturated fat / total fat ratio** (replaces sat fat component):
```
ratio = (saturated_fat_g / total_fat_g) × 100
thresholds: 10, 16, 22, 28, 34, 40, 46, 52, 58, 64  (%)
```

Unlike the inclusive nutrient tables, these ratio thresholds are **strict upper
bounds**: <10% → 0 points; [10,16) → 1; [16,22) → 2; [22,28) → 3;
[28,34) → 4; [34,40) → 5; [40,46) → 6; [46,52) → 7; [52,58) → 8;
[58,64) → 9; >=64% → 10. Exact boundaries enter the higher band.
The calculators compare decimal cross-products exactly rather than dividing
binary floats or changing the shared inclusive-threshold helper. The existing
fallback of zero ratio points for absent/nonpositive total fat is unchanged.

Sugars and salt use the same general tables.

---

## 5. Positive Points (P)

### 5a. General / Cheese / Red Meat / Fats

| Component | Thresholds | Max pts |
|---|---|---|
| Fiber (g) | 3.0, 4.1, 5.2, 6.3, 7.4 | 5 |
| Protein (g) | 2.4, 4.8, 7.2, 9.6, 12, 14, 17 | 7 |
| FVL (%) | 40, 60, 80 → mapped to 0, 1, 2, 5 pts | 5 |

FVL point mapping (general / fats):
```
fvl_raw = 0 (≤40%)  → 0 pts
fvl_raw = 1 (≤60%)  → 1 pt
fvl_raw = 2 (≤80%)  → 2 pts
fvl_raw = 3 (>80%)  → 5 pts
```

### 5b. Beverages

| Component | Thresholds | Max pts |
|---|---|---|
| Fiber (g) | 3, 4.1, 5.2, 6.3, 7.4 | 5 |
| Protein (g) | 1.2, 1.5, 1.8, 2.1, 2.4, 2.7, 3.0 | 7 |
| FVL (%) | 40, 60, 80 → mapped to 0, 2, 4, 6 pts | 6 |

FVL point mapping (beverages):
```
fvl_raw = 0 (≤40%)  → 0 pts
fvl_raw = 1 (≤60%)  → 2 pts
fvl_raw = 2 (≤80%)  → 4 pts
fvl_raw = 3 (>80%)  → 6 pts
```

---

## 6. Fruits / Vegetables / Legumes (FVL) Percentage

The FVL % must be estimated per product type. Common conventions:

| Product type | FVL % |
|---|---|
| Fresh / frozen fruits and vegetables | 100% |
| 100% fruit juice | 100% |
| Canned / preserved vegetables | 50% |
| Canned fruit in juice/syrup | 50% |
| Tomato-based sauces | depends on recipe |
| Mixed dishes with vegetables | depends on recipe |
| All other products | 0% |

Avocado and olives count as FVL. In the fats/oils/nuts/seeds scoring category,
qualifying oils derived from the **entire edible part** of FVL ingredients also
count, including **olive, avocado and soybean oils**. **Grapeseed oil does not
qualify.** Nuts and seeds do not count merely because they belong to this scoring
category.

Use verified composition or an explicitly supplied percentage; do not infer a
percentage from the product name or automatically replace manual values.
These guidance corrections do **not** change the application's existing category
defaults or saved percentages.

---

## 7. Special Category Rules

### 7a. Cheese — Protein never blocked
For cheese, protein **always contributes** to positive points, regardless of how high the N-score is. See §8 for the blocking rule that applies to other categories.

### 7b. Red Meat — Protein capped at 2 points
Even if the protein value would earn more than 2 points, only 2 points maximum are awarded.

```python
protein_pts = min(protein_pts, 2)
```

### 7c. Beverages — Water / plain drinks get automatic A
If a beverage has `energy_kj = 0` AND `sugars_g = 0` AND no artificial sweeteners, it is automatically graded **A** regardless of the numerical score.

---

## 8. Protein Blocking Rule

### General / Red Meat

The following existing rule applies to `general` and `red_meat` only (NOT cheese,
beverage or fats/oils/nuts/seeds):

If the total negative score is high AND the product has little or no fruit/vegetable content, protein points are excluded from the final calculation. This prevents ultra-processed products from compensating a bad profile by adding protein.

**Condition:**
```
if N_total >= 11 AND fvl_pts < 5:
    final_score = N_total − (fiber_pts + fvl_pts)   # protein excluded
else:
    final_score = N_total − (protein_pts + fiber_pts + fvl_pts)
```

**Separate concern, intentionally not corrected here:** the cited 2025 FAQ's
general-case calculation (printed page 28) excludes protein at N >= 11 without
the five-FVL-point exemption. This project retains its existing `fvl_pts < 5`
condition as explicitly requested. Reviewing/changing it requires separate scope.

### Fats / Oils / Nuts / Seeds

Use this category's own negative total N:
- N < 7: protein, fiber and FVL points all contribute.
- N >= 7: protein contributes **zero**, even with five FVL points.
  Positive total = fiber points + FVL points, and final score = N - positive total.

The returned fats-category protein component and explanation show its effective
contribution, not excluded raw protein points. Saturated-fat energy still uses
37 kJ per gram and the existing inclusive 120-kJ intervals.

---

## 9. Grade Thresholds

### General / Cheese / Red Meat

| Grade | Score range | Color |
|---|---|---|
| A | < 1 (integer scores ≤ 0) | Dark green |
| B | 1 to 2 | Light green |
| C | 3 to 10 | Yellow |
| D | 11 to 18 | Orange |
| E | ≥ 19 | Red |

### Fats / Oils / Nuts

| Grade | Score range |
|---|---|
| A | ≤ −6 |
| B | −5 to 2 |
| C | 3 to 10 |
| D | 11 to 18 |
| E | ≥ 19 |

### Beverages

| Grade | Score range |
|---|---|
| A | energy=0, sugars=0, no sweeteners |
| B | ≤ 2 |
| C | 3 to 6 |
| D | 7 to 9 |
| E | ≥ 10 |

---

## 10. Worked Examples

### Example 1 — Nestle Corn Flakes (General)

| Input | Value |
|---|---|
| Energy | 1678 kJ |
| Sugars | 26.8 g |
| Saturated fat | 1.0 g |
| Salt | 0.93 g |
| Protein | 7.6 g |
| Fiber | 8.0 g |
| FVL | 0% |

**N points:**
- Energy 1678 kJ → threshold[4]=1675 < 1678 ≤ threshold[5]=2010 → **5 pts**
- Sugars 26.8 g → threshold[6]=24 < 26.8 ≤ threshold[7]=27 → **7 pts**
- Sat fat 1.0 g → ≤ threshold[0]=1 → **0 pts**
- Salt 0.93 g → threshold[3]=0.8 < 0.93 ≤ threshold[4]=1.0 → **4 pts**
- **Total N = 16**

**P points (before blocking):**
- Protein 7.6 g → threshold[2]=7.2 < 7.6 ≤ threshold[3]=9.6 → **3 pts**
- Fiber 8.0 g → > threshold[4]=7.4 (max) → **5 pts**
- FVL 0% → **0 pts**
- **Total P (raw) = 8**

**Protein blocking check:**
- N=16 ≥ 11 ✓ and FVL=0 < 5 ✓ → **protein blocked**
- Final score = 16 − (5 + 0) = **11**
- Total P (actual) = 5

**Grade:** 11 is in range 11–18 → **D**

---

### Example 2 — Still water (Beverage)

Energy = 0, Sugars = 0, no sweeteners → automatic **A**

---

### Example 3 — Diet cola (Beverage with sweeteners)

| N components | Points |
|---|---|
| Energy ~4 kJ → 0 | 0 |
| Sugars 0 g → 0 | 0 |
| Sat fat 0 g → 0 | 0 |
| Salt 0 g → 0 | 0 |
| Sweetener penalty | +4 |
| **Total N** | **4** |

P = 0. Score = 4 − 0 = 4. Grade = **C** (3–6 range for beverages).

---

### Example 4 — Olive oil (Fats/Oils/Nuts)

| Input | Value |
|---|---|
| Saturated fat | 14 g |
| Total fat | 100 g |

- Energy from sat fat = 14 × 37 = 518 kJ → threshold[3]=480 < 518 ≤ threshold[4]=600 → **4 pts**
- Sat/fat ratio = 14/100 × 100 = 14% → 10 ≤ 14 < 16 → **1 pt**
- Sugars 0, Salt 0 → **0 pts each**
- **Total N = 5**

With **explicit input FVL=0**, P = 0 and score = 5 − 0 = **5**, giving **C**.
This illustrates an input, not an assertion that olive oil is ineligible for FVL.
If a qualifying oil's verified FVL percentage is explicitly 100%, FVL earns five
points: N=5 <7, P=5, score=0 and fats-category grade **B**. This correction does
not automatically change the stored/default FVL percentage for oils.

---

## 11. Sweetener Detection Keywords

A product is flagged as containing sweeteners if any of the following appear in the name or ingredient list (case-insensitive):

```
Latvian:  saldināšanas līdzeklis, saldinātājs, aspartāms, acesulfāms k,
          sukraloze, saharīns, ciklamāts, neotāms, stevijas glikozīdi,
          maltīts, sorbīts, ksilitols, eritritols, izomaltīts, mannīts,
          bez cukura, bezkaloriju

English:  aspartam, acesulfam, sucralose, sacharin, cyclamate, neotam,
          advantam, stevia, steviol, thaumatin, maltitol, sorbitol,
          xylitol, erythritol, isomalt, mannitol, sweetener,
          zero, light, diet, sugar free, sugar-free

E-numbers: E950, E951, E952, E953, E954, E955, E957, E959,
           E960, E961, E962, E965, E966, E967, E968, E969
```

---

## 12. Using the Standalone Module

The file `nutriscore_standalone.py` (in this repo) is a complete, self-contained implementation with no external dependencies. Copy it into any Python project.

```python
from nutriscore_standalone import calculate, ProductCategory, sodium_mg_to_salt_g

# Basic usage
result = calculate(
    category=ProductCategory.GENERAL,
    energy_kj=1678,
    sugars_g=26.8,
    saturated_fat_g=1.0,
    salt_g=0.93,          # direct salt in g
    protein_g=7.6,
    fiber_g=8.0,
)
print(result.grade)       # "D"
print(result.score)       # 11
print(result.color)       # "orange"
print(result.summary)     # full breakdown text

# If you only have sodium (mg), convert first
salt = sodium_mg_to_salt_g(372)   # → 0.93 g

# Beverage with auto-detected sweeteners
result = calculate(
    category=ProductCategory.BEVERAGE,
    energy_kj=4,
    sugars_g=0,
    saturated_fat_g=0,
    salt_g=0,
    protein_g=0,
    ingredients_text="carbonated water, aspartam, acesulfam K, flavourings",
)
print(result.grade)       # "C"
print(result.has_sweeteners)  # True

# Cheese (protein blocking never applies)
result = calculate(
    category=ProductCategory.CHEESE,
    energy_kj=1200,
    sugars_g=0.5,
    saturated_fat_g=18.0,
    salt_g=1.5,
    protein_g=20.0,
)
print(result.components.protein_status)  # "included"

# Fats/oils (requires total_fat_g)
result = calculate(
    category=ProductCategory.FATS_OILS_NUTS,
    energy_kj=3700,
    sugars_g=0,
    saturated_fat_g=14.0,
    salt_g=0,
    protein_g=0,
    total_fat_g=100.0,
)
print(result.grade)       # "C"
```

### Result object fields

```python
result.grade          # str  — "A", "B", "C", "D", or "E"
result.score          # int  — final numeric score
result.color          # str  — "dark green", "light green", "yellow", "orange", "red"
result.category       # ProductCategory enum
result.has_sweeteners # bool
result.fvl_percent    # float — FVL % used in the calculation
result.summary        # str  — human-readable full breakdown

result.components.energy_pts         # int
result.components.sugars_pts         # int
result.components.saturated_fat_pts  # int
result.components.salt_pts           # int
result.components.sweetener_pts      # int (beverages only)
result.components.total_negative     # int  — N
result.components.protein_pts        # int
result.components.fiber_pts          # int
result.components.fvl_pts            # int
result.components.total_positive     # int  — P (after blocking if applicable)
result.components.protein_blocked    # bool
result.components.protein_status     # str  — "included", "blocked (...)", "capped at 2 (...)"
```

### Existing saved scores

Changing calculator code does not update previously saved grades or points.
**Existing saved scores require a separately approved recalculation.** This
correction does not deploy, modify production data or run a bulk recalculation.

---

## 13. Building a Web UI (similar to eclarion.com)

The [Eclarion Nutri-Score Calculator](https://www.eclarion.com/nutriscore-calculator/) provides a reference for a clean web UI. Suggested components:

### Input form
- Category dropdown (5 options)
- Nutrition fields: energy (kcal + auto-convert to kJ, or direct kJ input), sugars, saturated fat, salt/sodium, protein, fiber, total fat
- FVL percentage slider or dropdown
- Sweetener checkbox (beverages)

### Output display
- Large grade badge (A–E) with appropriate color
- Numeric score
- Bar chart or table showing component breakdown:
  - N components: energy, sugars, sat fat, salt (+ sweetener for beverages)
  - P components: protein, fiber, FVL
- Protein status note (included / blocked / capped)
- Brief explanatory text per grade

### Tech stack options
- **Python**: Streamlit (fastest to build), FastAPI + React/Vue, Flask
- **JavaScript**: React + a REST API, or purely client-side JS
- **No-code friendly**: Streamlit handles both UI and logic in pure Python

### kcal → kJ conversion
```python
energy_kj = energy_kcal * 4.184
```
