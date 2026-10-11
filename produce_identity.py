"""Conservative produce identity rules, not unrestricted fuzzy name matching."""

import re
import unicodedata
from dataclasses import dataclass, field


def fold(text):
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


# Token-start stems accommodate Latvian declensions without substring collisions.
FAMILIES = {
    "kiwiberry": r"kivi og",
    "cactus_fig": r"kaktusvig",
    "persimmon": r"hurm", "kiwi": r"kivi", "plum": r"plum",
    "pomegranate": r"granatabol", "pineapple": r"ananas",
    "mango": r"mango", "avocado": r"avokado", "coconut": r"kokosriekst", "passionfruit": r"pasiflor",
    "granadilla": r"granadill", "dragonfruit": r"pitaij|pitahaj",
    "tamarillo": r"tamarill", "longan": r"longan", "rambutan": r"rambutan",
    "starfruit": r"karambol", "fig": r"vig", "quince": r"cidonij",
    "mandarin": r"mandarin", "orange": r"apelsin", "lemon": r"citron(?:i|s)\b",
    "lime": r"laim", "pomelo": r"pomelo", "grapefruit": r"greipfrut",
    "lychee": r"licij", "feijoa": r"feihoj", "cherimoya": r"cerimoj",
    "kumquat": r"kumkvat", "kiwano": r"kivano",
    "raspberry": r"aven", "currant": r"janog", "blackberry": r"kazen",
    "blueberry": r"mellen|krummellen", "cranberry": r"dzerven",
    "strawberry": r"zemen", "gooseberry": r"erkskog", "grape": r"vinog",
    "physalis": r"fizal", "apple": r"abol", "pear": r"bumbier",
    "melon": r"melon", "watermelon": r"arbuz", "apricot": r"aprikoz",
    "peach": r"persik", "nectarine": r"nektarin", "cherry": r"kirs",
    "banana": r"banan", "aronia": r"aronij",
    "dill": r"dill", "spring_onion": r"locin|loki\b",
    "parsley": r"petersil", "mint": r"piparmetr", "coriander": r"koriandr",
    "chive": r"maurlok", "fennel": r"fenhel", "sage": r"salvij",
    "turmeric": r"kurkum", "basil": r"bazilik", "thyme": r"timian",
    "lemongrass": r"citronzal", "rosemary": r"rozmarin",
    "oregano": r"rauden|oregano", "marjoram": r"majoran",
    "asparagus": r"spargel", "pea": r"zirn|cukurzir", "corn": r"kukuruz",
    "bean": r"pupin|pupas\b", "celery": r"selerij",
    "chili": r"cili|pipar(?:i|s|u)\b|halapen|jalapen",
    "pepper": r"paprik", "eggplant": r"baklazan",
    "spinach": r"spinat", "arugula": r"rukol",
    "bok_choy": r"pak choi|pak choy", "radicchio": r"radicchio",
    "lettuce": r"salat", "cabbage": r"kapost",
    "champignon": r"sampinjon|portobell|portabell",
    "oyster_mushroom": r"austersen|austeres", "shimeji": r"shimeji",
    "enoki": r"enoki", "shiitake": r"sitake|shiitake",
    "king_oyster": r"eringi", "chanterelle": r"gailen",
    "onion": r"sipol", "garlic": r"kiplok", "leek": r"purav",
    "zucchini": r"cukini", "squash": r"kabac", "pumpkin": r"kirbj|kirbis",
    "radish": r"redis", "broccoli": r"brokol", "alfalfa": r"lucern",
    "sunflower": r"saulespuk", "wheatgrass": r"kviesu zelmen",
    "mustard": r"sinepj", "cucumber": r"gurk", "tomato": r"tomat",
    "beet": r"biet", "carrot": r"burkan", "potato": r"kartupel",
    "cauliflower": r"ziedkapost", "kohlrabi": r"kolrab",
    "parsnip": r"pastinak", "swede": r"kalis\b", "black_radish": r"rutk",
    "jerusalem_artichoke": r"topinambur", "artichoke": r"artisok",
    "rhubarb": r"rabarber",
}

CULTIVARS = {
    "apple": {
        "golden": r"golden", "rubis_gold": r"rubis gold", "granny_smith": r"granny smith",
        "royal_gala": r"royal gala", "gala": r"\bgala\b",
        "red_delicious": r"red delicious|chief", "champion": r"champion",
        "red_prince": r"red prince|jonaprince", "crimson_snow": r"crimson snow",
        **{v.replace(" ", "_"): re.escape(v) for v in (
            "kanzi", "tessa", "giga", "primo", "dolce vita", "green star",
            "gloster", "inored story", "magic star")},
    },
    "pear": {v: re.escape(v) for v in ("conference", "lucas", "williams", "forelle", "guyot", "migo", "nashi")},
    "grape": {
        "sultana": r"sultan", "red_globe": r"red globe", "moldova": r"moldova",
        "sweet_globe": r"sweet globe", "sweet_celebration": r"sweet celebration",
        "thompson": r"thompson", "vittoria": r"vittoria", "magenta": r"magenta",
        **{v.replace(" ", "_"): re.escape(v) for v in (
            "itum", "crimson", "melanie", "saphire", "sable", "candy snaps",
            "cotton candy", "muscat beauty")},
    },
    "melon": {
        "honey_dew": r"honey dew", "cantaloupe": r"canta loupe|kantalupe",
        "galia": r"galia", "piel_de_sapo": r"piel de sapo",
        "central_asian": r"vidusazij",
        **{v.replace(" ", "_"): re.escape(v) for v in (
            "obinavot", "shahnazar", "limelon",
            "orange candy", "snowball", "gwanipa")},
    },
    "pumpkin": {"butternut": r"sviesta", "nut": r"riekstu",
                "hokkaido": r"hokkaido|hokaido", "spaghetti": r"spaget",
                "muscat": r"muskata"},
    "chili": {"jalapeno": r"halapen|jalapen", "habanero": r"habanero",
              "carolina_reaper": r"carolina reaper", "padron": r"padron",
              "rawitt": r"rawitt|rowit|bird.s eye", "naga": r"naga", "cayenne": r"cayenne"},
    "lettuce": {"iceberg": r"iceberg|ledus", "romaine": r"roman",
                "frillice": r"frillice", "classic": r"classic",
                **{v: v for v in ("crunchita", "sabrosa", "gentile")}},
    "persimmon": {"persimon": r"persimon"},
    "mango": {"osteen": r"osteen"},
    "dragonfruit": {}, "kiwi": {}, "pepper": {},
}

COLORS = {
    "red": r"sarkan|sark\.|rosso|\bred\b", "yellow": r"dzelten|yellow",
    "green": r"zal(?:i|a|ie|as|ais)|gais|green", "white": r"balt|white",
    "brown": r"brun|brown", "dark": r"tums|dark", "orange": r"oranz",
    "purple": r"violet|purple",
}

HERBS = {"dill", "parsley", "mint", "coriander", "chive", "sage", "basil",
         "thyme", "rosemary", "oregano", "marjoram", "spring_onion"}
MUSHROOMS = {"champignon", "oyster_mushroom", "shimeji", "enoki", "shiitake",
             "king_oyster", "chanterelle"}


@dataclass
class Identity:
    family: str = ""
    attributes: dict = field(default_factory=dict)
    stage: str = "mature_raw"
    scope: str = "eligible"
    reason: str = ""


def hits(pattern, text):
    return re.search(rf"\b(?:{pattern})", text) is not None


def identify(row):
    name = fold(row["product"]["name"])
    path = fold(row.get("category_path", ""))
    if re.search(r"\b(?:apstradati|parstradatie) darzen", path):
        return Identity(scope="excluded", reason="Processed-vegetable category")
    if hits(r"dekorativ|halloween|ciekur", name):
        return Identity(scope="excluded", reason="Decorative/non-food or ambiguous ornamental item")
    if hits(r"varit|salde|zavet|marine|konserv|pudercukur|kalt|sagriezt|maltas|sul[a-z]*\b|biezen|salit|kupinat", name):
        return Identity(scope="excluded", reason="Processed/preserved/cut/ground form outside fresh unprocessed scope")
    if hits(r"datel|deglet|tamarind|kokosriekstu gabal|burkanu salmin|melnie", name):
        return Identity(scope="review", reason="Freshness/processing or edible portion needs confirmation")
    if hits(r"maisij|komplekt|mix|izlase", name):
        # A matching marketed blend is review-only; never infer proportions.
        blend = ""
        for key, pattern in {
            "family_salad": r"family", "oriental_salad": r"oriental",
            "trio_sprouts": r"super trio", "herbs_fish": r"ziv",
            "herbs_poultry": r"putnu|majputnu", "herbs_meat": r"galai",
            "herb_bundle": r"zalumu komplekt", "pepper_mix": r"paprika.*mix",
            "grape_mix": r"vinog.*(?:mix|izlase)", "leaf_mix": r"salati lapu mix",
        }.items():
            if hits(pattern, name):
                blend = key
                break
        return Identity("mixture", {"blend": blend} if blend else {},
                        scope="review", reason="Blend composition/proportions unverified; no single-ingredient substitution")
    families = [family for family, pattern in FAMILIES.items() if hits(pattern, name)]
    # Prefer the specific identity over a generic term present in its name.
    for specific, generic in (("kiwiberry", "kiwi"), ("cactus_fig", "fig"),
                              ("radicchio", "lettuce"), ("bok_choy", "lettuce"),
                              ("wheatgrass", "wheat")):
        if specific in families and generic in families:
            families.remove(generic)
    if "pepper" in families and "chili" in families:
        if hits(r"padron", name):
            families.remove("pepper")
        else:
            families.remove("chili")
    if "onion" in families and "banana" in families and hits(r"shallot", name):
        families.remove("banana")  # Banana shallot is an onion, not a fruit blend.
    if "tomato" in families:
        families = [f for f in families if f not in {"plum", "cherry", "raspberry"}]
    if "sugar_pea" in families or ("pea" in families and hits(r"salatu cukurzir", name)):
        families = [f for f in families if f != "lettuce"]
    if len(families) != 1:
        return Identity(scope="review", reason="Produce identity unresolved or multiple ingredients")
    family = families[0]
    attrs = {}
    for cultivar, pattern in CULTIVARS.get(family, {}).items():
        if hits(pattern, name):
            attrs["cultivar"] = cultivar
            break
    # Color is relevant for these forms, not for a strawberry's gift-box color.
    if family in {"kiwi", "plum", "grape", "melon", "watermelon", "pepper", "chili",
                  "eggplant", "onion", "champignon", "shimeji", "dragonfruit",
                  "zucchini", "cabbage", "radish", "nectarine", "peach", "asparagus"}:
        for color, pattern in COLORS.items():
            if hits(pattern, name):
                attrs["color"] = color
                break
    if family == "kiwi" and hits(r"gold", name):
        attrs.setdefault("color", "yellow")
    if family == "pear" and hits(r"red bartlett", name):
        attrs.update(cultivar="williams", color="red")
    if family == "pear" and attrs.get("cultivar") == "nashi":
        family = "asian_pear"
    if family == "melon" and hits(r"honey dew", name):
        attrs["cultivar"] = "honey_dew"
    if family == "eggplant" and hits(r"japan|graffiti", name):
        attrs["cultivar"] = "japanese" if hits(r"japan", name) else "graffiti"
    if family in {"peach", "nectarine"} and hits(r"plakan|paragv|paraguay|platerina", name):
        attrs["shape"] = "flat"
    if family in {"chili", "pepper"} and hits(r"padron", name):
        family = "chili"
        attrs["cultivar"] = "padron"
    if family == "pepper":
        if hits(r"gar[a-z]* sald|sald[a-z]* gar|konisk|palermo|minikapya", name):
            attrs["shape"] = "long"
        if hits(r"mini|mazas|tribelli|sweet bite", name):
            attrs["size_form"] = "mini"
    if family == "champignon" and hits(r"portobell|portabell", name):
        attrs["cultivar"] = "portobello"
    if family == "onion":
        if hits(r"salot|shallot", name):
            attrs["cultivar"] = "shallot"
        elif hits(r"sald", name):
            attrs["cultivar"] = "sweet"
    if family == "garlic" and hits(r"solo", name):
        attrs["cultivar"] = "solo"
    if family in {"grape", "watermelon", "pepper"}:
        if re.search(r"\bb/k\b|\bbez (?:kaulin|sekl)", name):
            attrs["seeds"] = "seedless"
        elif hits(r"ar sekl|ar kaulin", name):
            attrs["seeds"] = "seeded"
    if family == "celery":
        attrs["part"] = "stalk" if hits(r"kati", name) else "root" if hits(r"sakne", name) else ""
    if family == "bean":
        family = "green_bean" if hits(r"zal|haricot|paksu", name) else "butter_bean" if hits(r"sviesta", name) else "fava" if hits(r"lielas pupas", name) else "bean"
    if family == "pea":
        family = "sugar_pea" if hits(r"cukurzir", name) else "pea"
        if hits(r"paksti", name):
            attrs["part"] = "in_pods"
    if family == "corn" and hits(r"mini", name):
        attrs["part"] = "baby_corn"
    if family == "basil":
        if hits(r"taizeme|tums", name):
            attrs["cultivar"] = "thai" if hits(r"taizeme", name) else "dark"
    if family in {"mango", "kiwi", "avocado", "pineapple"}:
        if hits(r"nenogatavin", name):
            attrs["ripeness"] = "unripe"
        elif hits(r"nogatavin", name):
            attrs["ripeness"] = "ripe"
    stage = "microgreen" if hits(r"mikrozal", name) else "sprout" if hits(r"asni|digsti", name) else "mature_raw"
    if family == "wheatgrass":
        stage = "microgreen"
    return Identity(family, attrs, stage)


def compatible(target, source):
    """Missing specificity requires review; contradictory specificity is rejected."""
    if not target.family or target.family != source.family or target.stage != source.stage:
        return None
    if target.family == "mixture":
        blend = target.attributes.get("blend")
        return ["Blend composition unverified"] if blend and blend == source.attributes.get("blend") else None
    differences = []
    for key in target.attributes.keys() | source.attributes.keys():
        left, right = target.attributes.get(key), source.attributes.get(key)
        if left and right and left != right:
            return None
        if left != right:
            differences.append(f"{key} unspecified on {'target' if not left else 'source'}")
    return sorted(differences)
