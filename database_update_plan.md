# Database Update Plan - One-Time Implementation (UPDATED)

## Overview
This plan implements a comprehensive database update system that will:
1. Add new products with complete information (nutrition, photos, prices)
2. Update product availability tracking  
3. Update product prices with historical tracking
4. Handle ingredient analysis and mapping
5. **Calculate nutri-scores using provided nutriscore_calculator.py module**

## Database Analysis

### Current Schema Structure
- **products**: Main product table with SKU, name, category, quantity
- **nutritionfacts**: 1:1 nutrition data with products
- **product_price_history**: Price tracking with availability flags
- **productphotos**: Product images with primary photo designation
- **ingredient_analysis**: Unique ingredients with frequency tracking
- **ingredient_product_mapping**: Many-to-many ingredient-product relationships

### Key Features Identified
- Generated `name_norm` field for text search optimization
- Price history with `recorded_at` timestamps
- `is_available` boolean for availability tracking
- `data_source` field for tracking update sources
- Nutri-score fields (will be updated separately as requested)

## Implementation Plan

### Phase 1: Database Update Engine (Core)
Create `database_updater.py` with these components:

#### 1.1 Product Management
- **Add New Products**: Insert into `products` table with SKU validation
- **Update Existing Products**: Handle name, category, quantity changes
- **SKU Conflict Resolution**: Handle duplicate SKUs gracefully

#### 1.2 Nutrition Data Integration
- **New Nutrition Records**: Link to products via `product_id`
- **Update Existing Nutrition**: Update all nutrition fields including nutri-score calculation
- **Nutri-Score Calculation**: Use provided `nutriscore_calculator.py` module for automatic scoring
- **Ingredients Processing**: Extract and normalize ingredients text

#### 1.3 Price History Tracking
- **Price Updates**: Insert new records in `product_price_history`
- **Availability Updates**: Track `is_available` changes with timestamps
- **Data Source Tracking**: Tag updates with 'rimi_scraper' source
- **Currency Handling**: Default to EUR as per schema

#### 1.4 Photo Management
- **Photo URLs**: Extract and store product images
- **Primary Photo Logic**: Set first photo as primary
- **Duplicate Prevention**: Check existing photos before insertion

### Phase 2: Nutrition and Scoring Engine
Create `nutrition_processor.py`:

#### 2.1 Nutri-Score Integration
- **Calculator Import**: Use provided `NutriscoreCalculator` class
- **Category Mapping**: Map product categories to nutri-score classifications
- **Score Calculation**: Automatically calculate grades for products with nutrition data
- **Database Updates**: Store calculated scores and points in `nutri_score_grade` and `nutri_score_points` fields

#### 2.2 Ingredient Analysis Engine
- **Text Parsing**: Extract individual ingredients from nutrition text (for new products only)
- **Normalization**: Clean and standardize ingredient names
- **Frequency Calculation**: Update ingredient counts across products
- **Mapping Management**: Maintain many-to-many relationships

### Phase 3: Integration Layer
Create `update_coordinator.py`:

#### 3.1 Data Flow Management
- **Rimi Scraper Integration**: Connect with existing scraper system
- **Transaction Management**: Ensure data consistency
- **Error Handling**: Rollback on failures, log issues
- **Progress Tracking**: Status updates and completion reporting

#### 3.2 Conflict Resolution
- **SKU Matching**: Handle existing vs new product conflicts
- **Price Registration**: Register all price changes without user review
- **Availability Logic**: Mark disappeared products as unavailable
- **Data Quality Checks**: Validate required fields

### Phase 4: Update Operations
Create specific update handlers:

#### 4.1 New Product Addition
```python
def add_new_product(product_data):
    # Insert into products table
    # Add nutrition facts if available
    # Calculate nutri-score using nutriscore_calculator
    # Add product photos (no URL validation)
    # Create initial price history record
    # Process ingredients for new products only
```

#### 4.2 Price and Availability Updates
```python
def update_product_status(sku, price, availability):
    # Insert new price history record (all changes tracked)
    # Update availability flag
    # Track data source and timestamp
    # Do NOT trigger ingredient reprocessing
```

#### 4.3 Disappeared Product Handling
```python
def mark_products_unavailable(missing_skus):
    # Set is_available = false in product_price_history
    # Record timestamp of unavailability
    # Preserve all historical data
```

#### 4.3 Batch Update Processing
```python
def process_category_updates(category_code):
    # Get all products from scraper
    # Compare with database
    # Apply updates in batches
    # Generate update report
```

## Technical Specifications

### Database Connections
- Use existing DATABASE_URL environment variable
- Connection pooling for efficient operations
- Transaction management for data consistency

### Data Validation
- SKU format validation
- Price range validation (0.01 - 999.99 EUR)
- URL validation for photos
- Nutrition value range checks

### Performance Considerations
- Batch INSERT operations for multiple products
- Index usage optimization for SKU lookups
- Prepared statements for repeated operations
- Connection pooling to handle concurrent updates
- No photo URL validation to minimize external requests
- Ingredient processing only for new products (not price updates)

### Error Handling
- Database constraint violations
- Network timeouts during photo URL validation
- Invalid nutrition data formats
- Rollback mechanisms for failed transactions

## Integration with Existing System

### Scraper Integration
- Use existing `ProductMatcher` for product comparison
- Leverage `RimiParser` for data extraction
- Maintain existing price parsing logic

### Database Integration
- Use existing `DatabaseConnection` class as base
- Extend with update-specific methods
- Preserve existing read-only operations

## Update Process Flow

### 1. Discovery Phase
```
Scraper → Category Analysis → Product Comparison → New/Changed Products List
```

### 2. Update Phase
```
New Products → Add to Database → Nutrition + Photos + Price
Changed Products → Update Records → Price History → Availability
```

### 3. Validation Phase
```
Data Integrity Checks → Constraint Validation → Update Reports
```

## Monitoring and Reporting

### Update Statistics
- Products added: count and SKU list
- Products updated: count and change summary
- Prices updated: count and average change
- Availability changes: count and status distribution

### Error Reporting
- Failed insertions with reasons
- Validation errors with details
- Network issues and retries
- Database constraint violations

## Security Considerations

### Data Protection
- Input sanitization for all text fields
- SQL injection prevention via parameterized queries
- URL validation for photo links
- Transaction isolation levels

### Access Control
- Database user permissions for insert/update operations
- Audit trail via created_at/updated_at timestamps
- Data source tracking for accountability

## Deployment Strategy

### Testing Phase
- Test with small category (SH-12-1-1) containing 4 products
- Validate all update operations
- Verify data integrity and constraints

### Production Phase
- Process larger categories incrementally
- Monitor performance and error rates
- Generate comprehensive update reports

## Timeline Estimate

### Development: 4-6 hours
- Database updater core: 2 hours
- Ingredient processor: 1 hour  
- Integration layer: 1-2 hours
- Testing and validation: 1 hour

### Deployment: 1-2 hours
- Initial testing with small dataset
- Full category processing
- Validation and reporting

## Next Steps After Approval

1. Implement database updater core functionality
2. Create ingredient processing engine
3. Build integration layer with existing scraper
4. Test with small dataset (SH-12-1-1)
5. Generate test update report
6. Request approval for full deployment

## Updated Implementation Based on Feedback

### 1. Nutri-Score Integration
- **Module Usage**: Import and use provided `nutriscore_calculator.py`
- **Automatic Calculation**: Calculate nutri-scores for all products with nutrition data
- **Category Mapping**: Use category codes for proper classification (beverages, fats, cheese, fruits/vegetables)
- **Database Storage**: Update `nutri_score_grade` and `nutri_score_points` fields

### 2. Product Availability Management
- **Disappeared Products**: Mark as unavailable (`is_available = false`)
- **Historical Preservation**: Keep all existing data, only update availability status
- **Timestamp Tracking**: Record when products became unavailable

### 3. Price Change Handling
- **Universal Registration**: Register all price changes without review thresholds
- **No Manual Review**: Automatic processing of all price updates
- **Complete History**: Maintain full price change timeline

### 4. Request Minimization
- **No Photo URL Validation**: Store URLs without attempting to fetch them
- **Efficient Scraping**: Use existing scraper data without additional requests

### 5. Ingredient Processing Scope
- **New Products Only**: Process ingredients only for newly added products
- **Price Update Isolation**: Price changes do not trigger ingredient reprocessing
- **Performance Optimization**: Reduce processing overhead for existing products

## Enhanced Architecture

### Core Components
1. **Database Updater** (`database_updater.py`)
   - Product CRUD with SKU validation
   - Nutrition data integration with nutri-score calculation
   - Price history management (all changes tracked)
   - Photo URL storage (no validation)

2. **Nutrition Processor** (`nutrition_processor.py`)
   - `NutriscoreCalculator` integration
   - Category-based classification logic
   - Automatic score calculation and storage

3. **Ingredient Processor** (`ingredient_processor.py`)
   - New product ingredient analysis only
   - Text parsing and normalization
   - Frequency updates and mapping

4. **Update Coordinator** (`update_coordinator.py`)
   - Scraper integration
   - Unavailability marking for missing products
   - Transaction management and reporting

This updated plan addresses all your feedback points and provides a streamlined, efficient update system.