# Rimi Product Scraper

## Overview

This is a Streamlit web application that scrapes product data from Rimi (a Baltic grocery store chain) and analyzes food additives (E-numbers) in ingredients. The application extracts product information, nutritional data, and identifies potentially harmful food additives, storing everything in a PostgreSQL database for analysis and reporting.

## System Architecture

The application follows a modular Python architecture with clear separation of concerns:

- **Frontend**: Streamlit web interface for user interaction and data visualization
- **Backend**: Python modules handling web scraping, data processing, and database operations
- **Database**: PostgreSQL for persistent storage of products, nutritional data, and additives
- **Parsing Engine**: Custom E-number extraction and ingredient analysis

## Key Components

### 1. Web Scraper (`scraper.py`)
- **Purpose**: Extracts product data from Rimi's e-commerce website
- **Features**: 
  - Handles dynamic content and JavaScript-rendered pages
  - Extracts product names, SKUs, prices, ingredients, and nutritional information
  - Includes country mapping for product origin identification
  - Implements retry logic and error handling for robust scraping

### 2. Additive Parser (`additive_parser.py`)
- **Purpose**: Identifies and extracts E-numbers (food additives) from ingredient lists
- **Features**:
  - Uses regex patterns to match various E-number formats (E100, E-100, e 100, etc.)
  - Standardizes E-number format for consistent database storage
  - Handles edge cases and provides detailed context extraction

### 3. Additive Manager (`additive_manager.py`)
- **Purpose**: Orchestrates the processing and storage of food additives
- **Features**:
  - Processes product ingredients to find additives
  - Manages database operations for additive storage
  - Provides statistics and logging for processing operations

### 4. Database Layer (`database.py`)
- **Purpose**: Handles all database operations and connection management
- **Features**:
  - Connection pooling for efficient database access
  - Auto-retry logic for connection failures
  - Schema creation and maintenance
  - Support for storing products, nutritional data, and additives

### 5. Streamlit Interface (`main.py`)
- **Purpose**: Provides web-based user interface for the application
- **Features**:
  - Product search and scraping interface
  - Data visualization and analysis tools
  - Caching for improved performance
  - Real-time processing feedback

### 6. Testing Suite (`test_parser.py`)
- **Purpose**: Validates E-number extraction functionality
- **Features**: Tests real-world ingredient examples to ensure accurate parsing

## Data Flow

1. **User Input**: User provides Rimi product URLs through the Streamlit interface
2. **Web Scraping**: RimiScraper extracts product data from the provided URLs
3. **Data Processing**: Product information is parsed and validated
4. **Additive Analysis**: AdditiveParser identifies E-numbers in ingredient lists
5. **Database Storage**: All processed data is stored in PostgreSQL
6. **Visualization**: Results are displayed through the Streamlit interface with analytics

## External Dependencies

### Core Libraries
- **Streamlit**: Web application framework for the user interface
- **BeautifulSoup4**: HTML parsing for web scraping
- **psycopg2**: PostgreSQL database adapter
- **requests**: HTTP library for web requests
- **pandas**: Data manipulation and analysis

### Additional Dependencies
- **trafilatura**: Text extraction from web pages
- **openai**: AI integration capabilities (future enhancement)
- **urllib3**: HTTP client library with retry support

## Deployment Strategy

The application is configured for deployment on Replit with the following setup:

- **Runtime**: Python 3.11 with PostgreSQL 16
- **Port Configuration**: Streamlit runs on port 5000, exposed as port 80
- **Auto-scaling**: Configured for autoscale deployment target
- **Workflow**: Automated setup with package installation and service startup

### Environment Setup
- PostgreSQL database with automatic connection pooling
- Environment variables for database credentials
- Streamlit configuration for headless operation

## Database Schema

The application uses a PostgreSQL database with the following key tables:

- **Products**: Stores basic product information (SKU, name, price, etc.)
- **Nutritional Information**: Detailed nutrition data per product
- **Additives**: E-number catalog with safety information
- **Product-Additive Relationships**: Links products to their contained additives

## Recent Changes

- **June 29, 2025**: Fixed nutrition data parsing and database storage issues
  - Identified and resolved Latvian nutrition label parsing problems with "tostarp" (including) prefixes
  - Fixed field name mapping between extraction code and Streamlit display interface
  - Corrected database connection issues to use proper PRODUCTS_DB_URL with nutritionfacts table
  - Successfully implemented complete nutrition data extraction: Fat, Saturated Fat, Carbohydrates, Sugar
  - Verified Product Manager displays accurate nutrition values from database
  - Added comprehensive debug logging for nutrition extraction process
  - Fixed availability detection logic: Products with €0.00 price now correctly marked as unavailable in price history
  - Resolved hardcoded availability settings in both product updates and new product creation
  - Fixed quantity extraction and database storage issues: Enhanced regex pattern to handle Latvian units (gb → gab for pieces)
  - Implemented comprehensive quantity data population: 99.7% coverage preserving existing Latvian vocabulary
  - Products with fixed quantities show values and units in Latvian (e.g., "10 gab"), products sold by weight show unit only (kg)
  - Corrected field mapping between processing results and Streamlit display interface for quantity information
  - Fixed nutri-score calculation for new products: Enhanced conditional logic to detect missing nutri-scores properly
  - Integrated automatic nutri-score calculation using nutriscore_calculator module for products with complete nutrition data
  - Product Manager now displays nutri-score information (grade and points) for products with nutrition facts
  - Fixed ingredient mapping system: Resolved case sensitivity issues in ingredient_processor.py (preserved original case instead of title case)
  - Enhanced ingredient extraction for single-ingredient products like "olas" (eggs) with proper normalization
  - Integrated ingredient processing into database update workflow for all new products
  - Product Manager now displays ingredient analysis with mappings to ingredient_analysis table and frequency data
  - Successfully mapped product 4007406 ingredient "olas" to ingredient_analysis id=45 with frequency tracking
  - Fixed price parsing for multi-line formats: Enhanced regex to handle newlines and reconstruct prices like "3\n59" → "€3.59"
  - Fixed ingredient processing database constraint errors: Added ON CONFLICT handling and case-insensitive matching
  - Enhanced ingredient extraction for compound ingredients: "vistas OLAS" now correctly maps to "olas" (main ingredient)
  - Integrated ingredient processing into update workflow: Both new products and updates now process ingredients automatically
  - Successfully resolved product 999409 issues: Price €3.59 (was €0.00), availability True (was False), ingredient "olas" mapped correctly
  - Fixed database sequence constraint violations: Implemented manual ID assignment to bypass broken ingredient_analysis sequence
  - Resolved ingredient processing errors for products with complex ingredients like "ieraugs. Lauksaimniecība ES" and "LV-BIO-02"
  - Enhanced ingredient processor with retry logic and robust error handling for database constraint conflicts
  - Successfully tested complete fix with product 961367: All 3 ingredients processed correctly (VĀJPIENS, ieraugs, LV-BIO-02)
  - System now handles all ingredient processing scenarios without database constraint violations
  - Implemented ingredient deduplicator tool: Created comprehensive duplicate detection and merging system
  - Fixed ingredient normalization completely: All case variations now map to existing ingredients (e.g., "VĀJPIENS" → "vājpiens" ID 2684)
  - Cleaned up duplicate ingredients: Merged "VĀJPIENS" (ID 15618) into existing "vājpiens" (ID 2684) with frequency 82
  - Enhanced ingredient processor with similarity checking: Prevents creation of duplicates before database insertion
  - Verified zero duplicate ingredients remain: Database is clean with proper case-insensitive ingredient matching
  - Successfully tested complete workflow: Product 961367 processes correctly with all 3 ingredients mapped to existing records
  - Resolved all ingredient normalization issues: Enhanced deduplicator found and merged 79 duplicate ingredient groups automatically
  - Fixed certification information handling: "ieraugs. Lauksaimniecība ES" now correctly normalizes to "ieraugs" (ID 566) instead of creating duplicates
  - Cleaned database completely: All case variations and certification suffixes now map to existing base ingredients
  - System now handles all Latvian certification patterns: "Lauksaimniecība ES", "LV-BIO-XX", "bioloģisks" properly stripped during normalization
  - Final verification successful: Product 961367 shows perfect ingredient mapping (vājpiens→ID 2684, ieraugs→ID 566, LV-BIO-02→ID 15620)
  - Implemented proper tokenization approach: Instead of string-based regex stripping, system now splits ingredients into tokens first
  - Enhanced ingredient processing: "ieraugs. Lauksaimniecība ES" → ["ieraugs.", "Lauksaimniecība", "ES"] → filters certification tokens → keeps only "ieraugs"
  - Token-based filtering system: Maintains comprehensive list of certification tokens (Lauksaimniecība, ES, bio, bioloģisks, etc.) for precise filtering
  - Improved maintainability: Easy to extend with new certification patterns without complex regex modifications

- **June 28, 2025**: Implemented comprehensive database update system with complete nutrition data extraction
  - Created database updater with nutri-score calculation using provided nutriscore_calculator.py module
  - Added ingredient processor for new products only (not price updates)
  - Implemented update coordinator for complete workflow orchestration
  - Added conditional nutri-score calculation (only for new products without existing scores)
  - Created tracking system for products without nutrition facts (fruits/vegetables)
  - Integrated automatic price change registration without review thresholds
  - Added product unavailability marking for disappeared products
  - Implemented Streamlit interface for database updates with safety confirmations
  - Fixed Streamlit database update button by separating from nested button structure
  - Fixed category assignment logic to use normalized_categories table for proper category_id mapping
  - Implemented complete nutrition data scraping from product pages including ingredients and nutritional facts
  - Added extraction of Latvian nutrition labels (Sastāvdaļas, Uzturvērtība) with proper data conversion
  - System now supports full CRUD operations with automatic nutrition data extraction and nutri-score calculation

- **June 25, 2025**: Implemented exact hierarchical matching, precise product counting, and detailed product comparison
  - Removed all fuzzy logic with category-specific URL patterns
  - Removed dynamic pattern detection by analyzing sample products
  - Implemented exact matching using normalized_categories table with parent_category_id and level fields
  - Added recursive category tree traversal for subcategories when level < 3
  - Fixed website product counting: For pages > 1: (Total pages - 1) × 20 + actual products on last page
  - For single page categories: direct product count without estimation
  - Fixed pagination parsing to handle UI patterns where only some page numbers are displayed (e.g., 1,2,3...72)
  - Confirmed SH-13 legitimately has 72 pages with 1,429 products total
  - Added detailed product-by-product comparison logic with exact SKU matching
  - Identifies new products (on website, not in database) and missing products (in database, not on website)
  - Detects changes in product names, prices, and URLs between website and database
  - Provides CSV export functionality for detailed comparison results
  - Fixed price parsing prioritizing HTML structure over JSON data (addresses JSON data discrepancies)
  - Clean hierarchical database matching based on category structure
  - System now provides exact product counts and detailed product matching instead of estimates

## Changelog

- June 24, 2025. Initial setup
- June 24, 2025. Enhanced system with external database integration

## User Preferences

Preferred communication style: Simple, everyday language.
Preferred approach: Simplified category-by-category analysis in read-only mode without database modifications.