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

- **June 25, 2025**: Implemented exact hierarchical matching and precise product counting
  - Removed all fuzzy logic with category-specific URL patterns
  - Removed dynamic pattern detection by analyzing sample products
  - Implemented exact matching using normalized_categories table with parent_category_id and level fields
  - Added recursive category tree traversal for subcategories when level < 3
  - Fixed website product counting: For pages > 1: (Total pages - 1) × 20 + actual products on last page
  - For single page categories: direct product count without estimation
  - Fixed pagination parsing bug with binary search for actual last page when large gaps detected
  - Handles pagination display bugs (e.g., SH-13 showing 2,3,72 instead of continuous pages)
  - Fixed price parsing using JSON data attributes (€3.49 instead of malformed 349€)
  - Clean hierarchical database matching based on category structure
  - System now provides exact product counts instead of estimates

## Changelog

- June 24, 2025. Initial setup
- June 24, 2025. Enhanced system with external database integration

## User Preferences

Preferred communication style: Simple, everyday language.
Preferred approach: Simplified category-by-category analysis in read-only mode without database modifications.