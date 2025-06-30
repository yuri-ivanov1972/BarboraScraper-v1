
# Product Database Schema Documentation

## Overview
This database contains product information, nutrition facts, price history, and ingredient analysis for a grocery product management system.

## Tables

### 1. products
Main product information table.

```sql
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    name_norm TEXT GENERATED ALWAYS AS (
        trim(
            regexp_replace(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            regexp_replace(
                                regexp_replace(
                                    regexp_replace(
                                        regexp_replace(
                                            regexp_replace(
                                                regexp_replace(
                                                    regexp_replace(
                                                        regexp_replace(
                                                            regexp_replace(
                                                                regexp_replace(
                                                                    regexp_replace(lower(name),
                                                                    'ā', 'a', 'g'),
                                                                'č', 'c', 'g'),
                                                            'ē', 'e', 'g'),
                                                        'ģ', 'g', 'g'),
                                                    'ī', 'i', 'g'),
                                                'ķ', 'k', 'g'),
                                            'ļ', 'l', 'g'),
                                        'ņ', 'n', 'g'),
                                    'š', 's', 'g'),
                                'ū', 'u', 'g'),
                            'ž', 'z', 'g'),
                        'Ā|Č|Ē|Ģ|Ī|Ķ|Ļ|Ņ|Š|Ū|Ž', '', 'g'),
                    '\.', ' ', 'g'),
                ',', ' ', 'g'),
            '\s+', ' ', 'g')
        )
    ) STORED,
    rimi_url TEXT UNIQUE,
    category_id INTEGER NOT NULL,
    quantity_value DECIMAL(10,2),
    quantity_unit VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

**Indexes:**
- `idx_products_sku` ON products(sku)
- `idx_products_name` ON products USING gin(name gin_trgm_ops)
- `idx_products_category_id` ON products(category_id)

### 2. nutritionfacts
Nutritional information for products.

```sql
CREATE TABLE nutritionfacts (
    nutrition_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL UNIQUE REFERENCES products(product_id),
    ingredients_text TEXT,
    energy_kcal INTEGER,
    energy_kj INTEGER,
    fat_total DECIMAL(10, 2),
    fat_saturated DECIMAL(10, 2),
    carbs_total DECIMAL(10, 2),
    carbs_sugars DECIMAL(10, 2),
    protein DECIMAL(10, 2),
    salt DECIMAL(10, 2),
    fiber DECIMAL(10, 2),
    nutri_score_grade CHAR(1),
    nutri_score_points INTEGER,
    data_source_date TIMESTAMP WITH TIME ZONE
);
```

**Indexes:**
- `idx_nutrition_product_id` ON nutritionfacts(product_id)
- `idx_nutrition_carbs_sugars` ON nutritionfacts(carbs_sugars)
- `idx_nutrition_protein` ON nutritionfacts(protein)
- `idx_nutrition_nutri_score` ON nutritionfacts(nutri_score_grade)

### 3. product_price_history
Price and availability tracking over time.

```sql
CREATE TABLE product_price_history (
    price_history_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    price DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    is_available BOOLEAN NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    data_source VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

**Indexes:**
- `idx_price_history_product_id` ON product_price_history(product_id)
- `idx_price_history_recorded_at` ON product_price_history(recorded_at)
- `idx_price_history_product_recorded` ON product_price_history(product_id, recorded_at)
- `idx_price_history_availability` ON product_price_history(is_available)
- `idx_price_history_data_source` ON product_price_history(data_source)

### 4. productphotos
Product image storage.

```sql
CREATE TABLE productphotos (
    photo_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    photo_url TEXT NOT NULL,
    alt_text TEXT,
    is_primary BOOLEAN DEFAULT false
);
```

**Indexes:**
- `idx_photos_product_id` ON productphotos(product_id)

### 5. ingredient_analysis
Unique ingredients and their frequency across products.

```sql
CREATE TABLE ingredient_analysis (
    id SERIAL PRIMARY KEY,
    ingredient TEXT NOT NULL UNIQUE,
    frequency INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

**Indexes:**
- `idx_ingredient_analysis_freq` ON ingredient_analysis(frequency DESC)

### 6. ingredient_product_mapping
Many-to-many relationship between ingredients and products.

```sql
CREATE TABLE ingredient_product_mapping (
    ingredient_id INTEGER NOT NULL REFERENCES ingredient_analysis(id),
    product_sku TEXT NOT NULL REFERENCES products(sku),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ingredient_id, product_sku)
);
```

**Indexes:**
- `idx_ingredient_product_mapping_ingredient` ON ingredient_product_mapping(ingredient_id)

## Relationships

- `products` ↔ `nutritionfacts` (1:1 via product_id)
- `products` ↔ `productphotos` (1:many via product_id)
- `products` ↔ `product_price_history` (1:many via product_id)
- `products` ↔ `ingredient_product_mapping` (many:many via sku)
- `ingredient_analysis` ↔ `ingredient_product_mapping` (1:many via ingredient_id)

## Common API Endpoints Data Models

### Product Detail Response
```json
{
  "product_id": 123,
  "sku": "PROD-123",
  "name": "Product Name",
  "category_id": 5,
  "quantity_value": 500.00,
  "quantity_unit": "g",
  "nutrition": {
    "energy_kcal": 350,
    "energy_kj": 1465,
    "fat_total": 12.5,
    "fat_saturated": 3.2,
    "carbs_total": 45.0,
    "carbs_sugars": 8.5,
    "protein": 8.0,
    "salt": 1.2,
    "fiber": 3.5,
    "nutri_score_grade": "B",
    "nutri_score_points": 8
  },
  "current_price": {
    "price": 2.99,
    "currency": "EUR",
    "is_available": true,
    "recorded_at": "2025-06-27T10:00:00Z"
  },
  "photos": [
    {
      "photo_url": "https://example.com/photo.jpg",
      "alt_text": "Product image",
      "is_primary": true
    }
  ],
  "ingredients": ["flour", "sugar", "eggs"]
}
```

### Price History Response
```json
{
  "product_id": 123,
  "price_history": [
    {
      "price": 2.99,
      "currency": "EUR",
      "is_available": true,
      "recorded_at": "2025-06-27T10:00:00Z",
      "data_source": "rimi_scraper"
    }
  ]
}
```

## Database Configuration

**Required Extensions:**
- `pg_trgm` (for text search functionality)

**Connection Requirements:**
- PostgreSQL 12+
- UTF-8 encoding
- Timezone support enabled

## Notes for Integration

1. **SKU Field**: Use `sku` as the primary identifier for API integrations
2. **Nutrition Values**: All nutrition values are per 100g/100ml
3. **Currency**: Currently only EUR is supported
4. **Text Search**: Use `name_norm` field for normalized text searches
5. **Price Tracking**: `recorded_at` is the timestamp when price was observed
6. **Ingredients**: Stored as denormalized text in `nutritionfacts.ingredients_text` and normalized in `ingredient_analysis` table
