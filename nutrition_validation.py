"""Rule-based consistency checks between Barbora ingredients and nutrition facts.

The validator is deliberately separate from scraping and nutrition enrichment:
it reports suspicious records without changing the source data.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import Json, RealDictCursor, execute_batch


NUTRITION_VALIDATION_CONFIG: Dict[str, Any] = {
    "severity_thresholds": {"low": 1, "medium": 5, "high": 10},
    "energy_relative_threshold": 0.20,
    "energy_absolute_threshold_kcal": 50.0,
    "low_salt_threshold": 0.1,
    "trace_percentage_threshold": 1.0,
    "strong_percentage_threshold": 5.0,
    "weights": {
        "dairy_saturated_zero": 10,
        "fat_zero": 10,
        "saturated_fat_zero": 10,
        "sugar_zero": 10,
        "carbohydrate_zero": 10,
        "fruit_sugars_zero": 2,
        "salt_zero": 10,
        "salty_low_salt": 5,
        "protein_zero": 10,
        "nuts_fat_zero": 10,
        "cocoa_nutrient_zero": 5,
        "mathematical_impossible": 10,
        "energy_inconsistent": 5,
        "zero_cluster": 5,
    },
}


# The English terms are retained because some labels and imported records use
# them. Latvian terms are included alongside them rather than transliterated,
# so matching remains correct for Latvian characters.
INGREDIENT_GROUPS: Dict[str, Sequence[str]] = {
    "dairy": (
        "milk", "whole milk", "cream", "butter", "milk fat", "milk powder",
        "whole milk powder", "cheese", "whey", "whey powder", "condensed milk",
        "piens", "pilnpiens", "krējums", "sviests", "piena tauki",
        "piena pulveris", "siers", "sūkalas", "sūkalu pulveris",
        "iebiezināts piens",
    ),
    "fat": (
        "vegetable oil", "sunflower oil", "rapeseed oil", "canola oil",
        "olive oil", "coconut oil", "palm oil", "cocoa butter", "butter",
        "milk fat", "augu eļļa", "saulespuķu eļļa", "rapšu eļļa",
        "olīveļļa", "kokosriekstu eļļa", "palmu eļļa", "kakao sviests",
        "sviests", "piena tauki",
    ),
    "saturated_fat": (
        "coconut oil", "palm oil", "palm kernel oil", "butter", "milk fat",
        "cream", "cocoa butter", "kokosriekstu eļļa", "palmu eļļa",
        "palmu kodolu eļļa", "sviests", "piena tauki", "krējums",
        "kakao sviests",
    ),
    "sugar": (
        "sugar", "sucrose", "glucose", "fructose", "glucose syrup",
        "glucose-fructose syrup", "fructose syrup", "invert syrup",
        "corn syrup", "honey", "molasses", "caramel syrup", "cukurs",
        "saharoze", "glikoze", "fruktoze", "glikozes sīrups",
        "glikozes-fruktozes sīrups", "fruktozes sīrups", "invertcukura sīrups",
        "kukurūzas sīrups", "medus", "melase", "karameļu sīrups",
    ),
    "carbohydrate": (
        "wheat flour", "flour", "starch", "potato starch", "corn starch",
        "rice", "rice flour", "oats", "oat flour", "wheat", "barley", "rye",
        "cereals", "maltodextrin", "kviešu milti", "milti", "ciete",
        "kartupeļu ciete", "kukurūzas ciete", "rīsi", "rīsu milti", "auzas",
        "auzu milti", "kvieši", "mieži", "rudzi", "graudaugi", "maltodekstrīns",
    ),
    "fruit": (
        "fruit", "berries", "fruit puree", "fruit juice", "apple", "banana",
        "strawberry", "raspberry", "blueberry", "grape", "dates", "raisins",
        "dried fruit", "augļi", "ogas", "augļu biezenis", "augļu sula",
        "ābols", "banāns", "zemen", "aven", "mellen", "vīnog", "datel",
        "rozīn", "žāvēti augļi",
    ),
    "salt": (
        "salt", "sodium chloride", "sea salt", "rock salt", "sāls",
        "nātrija hlorīds", "jūras sāls", "akmens sāls",
    ),
    "salty": (
        "soy sauce", "brine", "salted cheese", "cured meat", "smoked meat",
        "salted fish", "pickled products", "sojas mērce", "sālījums",
        "sālīts siers", "sālīta gaļa", "kūpināta gaļa", "sālīta zivs",
        "marinēti produkti",
    ),
    "protein": (
        "meat", "beef", "pork", "chicken", "turkey", "fish", "tuna", "salmon",
        "egg", "egg white", "cheese", "whey protein", "milk protein",
        "soy protein", "pea protein", "protein isolate", "protein concentrate",
        "legumes", "gaļa", "liellopa gaļa", "cūkgaļa", "vista", "tītars",
        "zivs", "tuncis", "lasis", "ola", "olu baltums", "siers",
        "sūkalu proteīns", "piena proteīns", "sojas proteīns",
        "zirņu proteīns", "olbaltumvielu izolāts", "olbaltumvielu koncentrāts",
        "pākšaugi",
    ),
    "nuts": (
        "almonds", "peanuts", "hazelnuts", "walnuts", "cashews", "pistachios",
        "sunflower seeds", "pumpkin seeds", "sesame", "chia", "flax",
        "mandeles", "zemesrieksti", "lazdu rieksti", "valrieksti",
        "kastaņi", "pistācijas", "saulespuķu sēklas", "ķirbju sēklas",
        "sezams", "čia", "linsēklas",
    ),
    "cocoa": (
        "cocoa", "cocoa powder", "cocoa mass", "chocolate", "dark chocolate",
        "milk chocolate", "cocoa butter", "kakao", "kakao pulveris",
        "kakao masa", "šokolāde", "tumšā šokolāde", "piena šokolāde",
        "kakao sviests",
    ),
}

POLYOL_TERMS: Sequence[str] = (
    "polyol", "polyols", "sugar alcohol", "sweetener",
    "sorbitol", "mannitol", "xylitol", "erythritol", "maltitol",
    "isomalt", "lactitol", "glycerol", "polydextrose",
    "poliols", "cukura spirts", "saldinātājs", "sorbīts", "mannīts",
    "ksilīts", "eritritols", "maltīts", "isomalts", "laktitols",
    "glicerīns", "polidekstroze",
    "e420", "e421", "e953", "e965", "e966", "e967", "e968",
)


def normalize_ingredient_text(text: Optional[str]) -> str:
    """Normalize whitespace and case while preserving Latvian characters."""
    if not text:
        return ""
    normalized = text.casefold().replace("\u00a0", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _remove_advisory_text(text: str) -> str:
    """Remove advisory cross-contact statements from ingredient evidence."""
    advisory = (
        r"may\s+contain|may\s+also\s+contain|var\s+saturēt|var\s+būt\s+"
        r"sastāvā|var\s+būt\s+klāt|var\s+ietvert"
    )
    # Remove until a likely boundary. This intentionally errs on the side of
    # excluding evidence rather than treating an advisory allergen as definite.
    return re.sub(rf"(?i)(?:{advisory})[^.;]*(?:[.;]|$)", " ", text)


def _remove_zero_compatible_phrases(text: str) -> str:
    """Exclude explicitly fat-free dairy phrases from dairy-fat evidence."""
    phrases = (
        "skimmed milk", "skim milk", "fat-free milk", "non-fat milk",
        "vājpiens", "attaukots piens", "beztauku piens",
    )
    for phrase in phrases:
        text = _term_pattern(phrase).sub(" ", text)
    return text


@lru_cache(maxsize=None)
def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.casefold()).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![\w]){escaped}(?![\w])", re.IGNORECASE | re.UNICODE)


def extract_ingredient_evidence(text: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Return matched ingredient groups and optional percentages.

    Matching uses Unicode-aware token boundaries rather than raw substring
    checks, which prevents terms such as "salt" from matching arbitrary words.
    """
    normalized = _remove_zero_compatible_phrases(
        _remove_advisory_text(normalize_ingredient_text(text))
    )
    evidence: Dict[str, List[Dict[str, Any]]] = {}
    for group, terms in INGREDIENT_GROUPS.items():
        matches: List[Dict[str, Any]] = []
        seen_terms = set()
        for term in sorted(terms, key=len, reverse=True):
            if term in seen_terms:
                continue
            for match in _term_pattern(term).finditer(normalized):
                before = normalized[max(0, match.start() - 12):match.start()]
                after = normalized[match.end():match.end() + 12]
                percentage_match = re.search(
                    r"(\d+(?:[.,]\d+)?)\s*%\s*$", before
                ) or re.match(
                    r"^\s*(?:\(\s*)?(\d+(?:[.,]\d+)?)\s*%(?:\s*\))?",
                    after,
                )
                matches.append({
                    "term": term,
                    "percentage": (
                        float(percentage_match.group(1).replace(",", "."))
                        if percentage_match else None
                    ),
                })
                seen_terms.add(term)
                break
        if matches:
            evidence[group] = matches
    return evidence


def _value(product: Dict[str, Any], key: str) -> Optional[float]:
    value = product.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _contains_polyol_or_sweetener(ingredients_text: Any) -> bool:
    normalized = normalize_ingredient_text(ingredients_text)
    return any(_term_pattern(term).search(normalized) for term in POLYOL_TERMS)


def is_safe_barbora_url(url: Any) -> bool:
    """Allow only absolute HTTP(S) links hosted on Barbora."""
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return False
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and (
            hostname == "barbora.lv"
            or hostname.endswith(".barbora.lv")
        )
    )


def _reason(
    rule: str,
    severity: str,
    evidence: Iterable[Dict[str, Any]],
    nutrition_field: str,
    nutrition_value: Any,
    message: str,
) -> Dict[str, Any]:
    percentages = {
        item["term"]: item["percentage"]
        for item in evidence if item.get("percentage") is not None
    }
    return {
        "rule": rule,
        "severity": severity,
        "ingredient_evidence": [item["term"] for item in evidence],
        "ingredient_percentages": percentages,
        "nutrition_field": nutrition_field,
        "nutrition_value": nutrition_value,
        "message": message,
    }


def _score_level(score: int, config: Dict[str, Any]) -> str:
    thresholds = config["severity_thresholds"]
    if score >= thresholds["high"]:
        return "high"
    if score >= thresholds["medium"]:
        return "medium"
    if score >= thresholds["low"]:
        return "low"
    return "none"


def validate_product(
    product: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate one product and return a persistence-ready result."""
    config = config or NUTRITION_VALIDATION_CONFIG
    evidence = extract_ingredient_evidence(
        product.get("ingredients_text") or product.get("ingredients")
    )
    reasons: List[Dict[str, Any]] = []
    score = 0
    added_keys = set()

    def ingredient_strength(group: str) -> Optional[str]:
        group_evidence = evidence.get(group, [])
        if any(item.get("percentage") is None for item in group_evidence):
            return "medium"
        percentages = [
            item["percentage"] for item in group_evidence
            if item.get("percentage") is not None
        ]
        if percentages and max(percentages) < config["trace_percentage_threshold"]:
            return None
        if percentages and max(percentages) >= config["strong_percentage_threshold"]:
            return "high"
        return "medium"

    def add(
        rule: str,
        severity: str,
        group: str,
        field: str,
        value: Any,
        weight_key: str,
        message: str,
        percentage_sensitive: bool = False,
    ) -> None:
        nonlocal score
        key = (rule, field)
        if key in added_keys or group not in evidence:
            return
        group_evidence = evidence[group]
        reason_severity = severity
        reason_weight = config["weights"][weight_key]
        if percentage_sensitive:
            strength = ingredient_strength(group)
            if strength is None:
                return
            if severity == "high" and strength == "medium":
                reason_severity = "medium"
                reason_weight = config["severity_thresholds"]["medium"]
        added_keys.add(key)
        reasons.append(_reason(
            rule, reason_severity, group_evidence, field, value, message
        ))
        score += reason_weight

    fat = _value(product, "fat_total")
    saturated = _value(product, "fat_saturated")
    carbs = _value(product, "carbs_total")
    sugars = _value(product, "carbs_sugars")
    protein = _value(product, "protein")
    salt = _value(product, "salt")
    energy_kcal = _value(product, "energy_kcal")
    energy_kj = _value(product, "energy_kj")

    if saturated is not None and fat is not None and saturated > fat:
        reasons.append(_reason(
            "saturated_fat_exceeds_total_fat", "high", [], "fat_saturated",
            saturated, "Saturated fat cannot exceed total fat."
        ))
        score += config["weights"]["mathematical_impossible"]
    if sugars is not None and carbs is not None and sugars > carbs:
        reasons.append(_reason(
            "sugars_exceed_carbohydrates", "high", [], "carbs_sugars",
            sugars, "Sugars cannot exceed total carbohydrates."
        ))
        score += config["weights"]["mathematical_impossible"]

    if "dairy" in evidence and saturated == 0:
        add(
            "milk_present_but_saturated_fat_zero", "high", "dairy",
            "fat_saturated", saturated, "dairy_saturated_zero",
            "Dairy ingredients are present but saturated fat is reported as zero.",
            percentage_sensitive=True,
        )
    if "fat" in evidence and fat == 0:
        add(
            "fat_ingredient_present_but_fat_zero", "high", "fat",
            "fat_total", fat, "fat_zero",
            "A fat or oil ingredient is present but total fat is reported as zero.",
            percentage_sensitive=True,
        )
    if "saturated_fat" in evidence and saturated == 0:
        add(
            "high_saturated_fat_ingredient_but_saturated_fat_zero", "high",
            "saturated_fat", "fat_saturated", saturated, "saturated_fat_zero",
            "A strongly saturated-fat-rich ingredient is present but saturated fat is zero.",
            percentage_sensitive=True,
        )
    if "sugar" in evidence and sugars == 0:
        add(
            "sugar_ingredient_present_but_sugars_zero", "high", "sugar",
            "carbs_sugars", sugars, "sugar_zero",
            "A direct sugar ingredient is present but sugars are reported as zero.",
            percentage_sensitive=True,
        )
    if "carbohydrate" in evidence and carbs == 0:
        add(
            "carbohydrate_ingredient_present_but_carbohydrates_zero", "high",
            "carbohydrate", "carbs_total", carbs, "carbohydrate_zero",
            "A carbohydrate-rich ingredient is present but carbohydrates are zero.",
            percentage_sensitive=True,
        )
    if "fruit" in evidence and sugars == 0:
        add(
            "fruit_present_but_sugars_zero", "low", "fruit", "carbs_sugars",
            sugars, "fruit_sugars_zero",
            "Fruit evidence is present but sugars are reported as zero.",
            percentage_sensitive=True,
        )
    if "salt" in evidence and salt == 0:
        add(
            "salt_present_but_salt_zero", "high", "salt", "salt", salt,
            "salt_zero", "Salt is present but salt is reported as zero.",
            percentage_sensitive=True,
        )
    if "salty" in evidence and salt is not None and salt <= config["low_salt_threshold"]:
        add(
            "salty_ingredient_but_low_salt", "medium", "salty", "salt", salt,
            "salty_low_salt",
            "A salty ingredient is present but salt is unusually low.",
            percentage_sensitive=True,
        )
    if "protein" in evidence and protein == 0:
        add(
            "protein_ingredient_present_but_protein_zero", "high", "protein",
            "protein", protein, "protein_zero",
            "A protein-rich ingredient is present but protein is reported as zero.",
            percentage_sensitive=True,
        )
    if "nuts" in evidence and fat == 0:
        add(
            "nuts_or_seeds_present_but_fat_zero", "high", "nuts", "fat_total",
            fat, "nuts_fat_zero",
            "Nuts or seeds are present but total fat is reported as zero.",
            percentage_sensitive=True,
        )
    for field, label in (
        ("fat_total", "total fat"), ("fat_saturated", "saturated fat"),
        ("carbs_sugars", "sugars"),
    ):
        nutrient_value = _value(product, field)
        if "cocoa" in evidence and nutrient_value == 0:
            add(
                f"cocoa_present_but_{field}_zero", "medium", "cocoa", field,
                nutrient_value, "cocoa_nutrient_zero",
                f"Cocoa or chocolate is present but {label} is reported as zero.",
                percentage_sensitive=True,
            )

    declared_kcal = energy_kcal
    if declared_kcal is None and energy_kj is not None:
        declared_kcal = energy_kj / 4.184
    fiber = _value(product, "fiber")
    if (
        declared_kcal is not None
        and all(v is not None for v in (fat, carbs, protein))
        and not _contains_polyol_or_sweetener(
            product.get("ingredients_text") or product.get("ingredients")
        )
    ):
        estimated_kcal = protein * 4 + carbs * 4 + fat * 9
        if fiber is not None:
            estimated_kcal += fiber * 2
        difference = estimated_kcal - declared_kcal
        if (
            declared_kcal > 0
            # Stored nutrition has no alcohol/polyol/organic-acid fields. Those
            # can legitimately make declared energy higher than this estimate,
            # so only an estimate that substantially exceeds the declaration is
            # considered suspicious.
            and difference / declared_kcal > config["energy_relative_threshold"]
            and difference > config["energy_absolute_threshold_kcal"]
        ):
            reasons.append(_reason(
                "energy_inconsistent_with_macronutrients", "medium", [],
                "energy_kcal", declared_kcal,
                f"Estimated energy ({estimated_kcal:.1f} kcal) substantially exceeds "
                f"declared energy ({declared_kcal:.1f} kcal)."
            ))
            score += config["weights"]["energy_inconsistent"]

    meaningful_zero_fields = [
        reason["nutrition_field"] for reason in reasons
        if reason["nutrition_field"] in {
            "fat_saturated", "fat_total", "carbs_sugars",
            "carbs_total", "protein", "salt",
        }
        and reason["rule"] != "energy_inconsistent_with_macronutrients"
    ]
    if "dairy" in evidence and fat == 0 and ingredient_strength("dairy"):
        meaningful_zero_fields.append("fat_total")
    if len(set(meaningful_zero_fields)) >= 3:
        reasons.append(_reason(
            "multiple_nutrition_values_inconsistent_with_ingredients", "medium",
            [], "multiple", len(set(meaningful_zero_fields)),
            "Several meaningful ingredients correspond to nutrition values reported as zero.",
        ))
        score += config["weights"]["zero_cluster"]

    return {
        "product_id": product.get("product_id"),
        "suspicion_level": _score_level(score, config),
        "suspicion_score": score,
        "reasons": reasons,
        "checked_at": datetime.now(timezone.utc),
    }


class NutritionValidationService:
    """Persistence and catalogue operations for nutrition validation."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.environ["DATABASE_URL"]

    def _connect(self):
        return psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)

    def ensure_schema(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS nutrition_validation (
                        id SERIAL PRIMARY KEY,
                        product_id INTEGER NOT NULL UNIQUE
                            REFERENCES products(product_id) ON DELETE CASCADE,
                        suspicion_level VARCHAR(10) NOT NULL
                            CHECK (suspicion_level IN ('none', 'low', 'medium', 'high')),
                        suspicion_score NUMERIC NOT NULL DEFAULT 0,
                        reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
                        checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_nutrition_validation_level_score
                    ON nutrition_validation (suspicion_level, suspicion_score DESC)
                """)
            conn.commit()
        finally:
            conn.close()

    def count_products(self) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS count FROM products")
                return int(cur.fetchone()["count"])
        finally:
            conn.close()

    def fetch_product_page(
        self,
        after_product_id: int = 0,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.product_id, p.name, p.sku, p.ingredients,
                           nf.ingredients_text, nf.energy_kcal, nf.energy_kj,
                           nf.fat_total, nf.fat_saturated, nf.carbs_total,
                           nf.carbs_sugars, nf.protein, nf.salt, nf.fiber,
                           nc.name_lv AS category_name
                    FROM products p
                    LEFT JOIN nutritionfacts nf ON nf.product_id = p.product_id
                    LEFT JOIN normalized_categories nc ON nc.category_id = p.category_id
                    WHERE p.product_id > %s
                    ORDER BY p.product_id
                    LIMIT %s
                """, (after_product_id, limit))
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def save_result(self, result: Dict[str, Any], conn=None) -> None:
        own_connection = conn is None
        conn = conn or self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO nutrition_validation
                        (product_id, suspicion_level, suspicion_score, reasons, checked_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (product_id) DO UPDATE SET
                        suspicion_level = EXCLUDED.suspicion_level,
                        suspicion_score = EXCLUDED.suspicion_score,
                        reasons = EXCLUDED.reasons,
                        checked_at = EXCLUDED.checked_at
                """, (
                    result["product_id"], result["suspicion_level"],
                    result["suspicion_score"], Json(result["reasons"]),
                    result["checked_at"],
                ))
            if own_connection:
                conn.commit()
        finally:
            if own_connection:
                conn.close()

    def validate_all(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        self.ensure_schema()
        total = self.count_products()
        errors: List[str] = []
        processed = 0
        after_product_id = 0
        conn = self._connect()
        try:
            while True:
                products = self.fetch_product_page(after_product_id, limit=500)
                if not products:
                    break
                page_results: List[Dict[str, Any]] = []
                for product in products:
                    try:
                        page_results.append(validate_product(product))
                        processed += 1
                        if progress_callback:
                            progress_callback(
                                processed, total, product.get("name", "")
                            )
                    except Exception as exc:
                        errors.append(f"{product.get('product_id')}: {exc}")
                with conn.cursor() as cur:
                    execute_batch(cur, """
                        INSERT INTO nutrition_validation
                            (product_id, suspicion_level, suspicion_score, reasons, checked_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (product_id) DO UPDATE SET
                            suspicion_level = EXCLUDED.suspicion_level,
                            suspicion_score = EXCLUDED.suspicion_score,
                            reasons = EXCLUDED.reasons,
                            checked_at = EXCLUDED.checked_at
                    """, [
                        (
                            result["product_id"], result["suspicion_level"],
                            result["suspicion_score"], Json(result["reasons"]),
                            result["checked_at"],
                        )
                        for result in page_results
                    ], page_size=250)
                conn.commit()
                after_product_id = products[-1]["product_id"]
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {"checked": processed, "total": total, "errors": errors}

    def get_summary(self) -> Dict[str, Any]:
        self.ensure_schema()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT suspicion_level, COUNT(*) AS count
                    FROM nutrition_validation
                    GROUP BY suspicion_level
                """)
                levels = {row["suspicion_level"]: int(row["count"]) for row in cur.fetchall()}
                cur.execute("""
                    SELECT reason->>'rule' AS rule, COUNT(*) AS count
                    FROM nutrition_validation nv
                    CROSS JOIN LATERAL jsonb_array_elements(nv.reasons) AS reason
                    WHERE reason->>'rule' IS NOT NULL
                    GROUP BY reason->>'rule'
                    ORDER BY count DESC, rule
                """)
                rule_counts = {
                    row["rule"]: int(row["count"]) for row in cur.fetchall()
                }
                total = sum(levels.values())
                return {
                    "total": total,
                    "levels": {level: levels.get(level, 0)
                               for level in ("none", "low", "medium", "high")},
                    "rules": rule_counts,
                }
        finally:
            conn.close()

    def get_results(
        self,
        level: Optional[str] = None,
        search: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        self.ensure_schema()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT nv.product_id, p.name, p.sku, p.barbora_url,
                           nc.name_lv AS category_name,
                           nv.suspicion_level, nv.suspicion_score,
                           nv.reasons, nv.checked_at
                    FROM nutrition_validation nv
                    JOIN products p ON p.product_id = nv.product_id
                    LEFT JOIN normalized_categories nc ON nc.category_id = p.category_id
                """
                params: List[Any] = []
                filters = []
                if level and level != "all":
                    filters.append("nv.suspicion_level = %s")
                    params.append(level)
                if search.strip():
                    filters.append(
                        "(p.name ILIKE %s OR p.sku ILIKE %s OR "
                        "p.product_id::text = %s)"
                    )
                    term = f"%{search.strip()}%"
                    params.extend((term, term, search.strip()))
                if filters:
                    query += " WHERE " + " AND ".join(filters)
                query += (
                    " ORDER BY nv.suspicion_score DESC, p.name "
                    "LIMIT %s OFFSET %s"
                )
                params.extend((limit, offset))
                cur.execute(query, tuple(params))
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def get_result_count(
        self,
        level: Optional[str] = None,
        search: str = "",
    ) -> int:
        self.ensure_schema()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT COUNT(*) AS count
                    FROM nutrition_validation nv
                    JOIN products p ON p.product_id = nv.product_id
                """
                filters = []
                params: List[Any] = []
                if level and level != "all":
                    filters.append("nv.suspicion_level = %s")
                    params.append(level)
                if search.strip():
                    filters.append(
                        "(p.name ILIKE %s OR p.sku ILIKE %s OR "
                        "p.product_id::text = %s)"
                    )
                    term = f"%{search.strip()}%"
                    params.extend((term, term, search.strip()))
                if filters:
                    query += " WHERE " + " AND ".join(filters)
                cur.execute(query, tuple(params))
                return int(cur.fetchone()["count"])
        finally:
            conn.close()
