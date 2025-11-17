# Rimi Product Scraper

## Overview
This Streamlit web application scrapes product data from Rimi, a Baltic grocery store chain, to analyze food additives (E-numbers) in ingredients. It extracts product information, nutritional data, and identifies potentially harmful food additives, storing the data in a PostgreSQL database for analysis and reporting. The project aims to provide comprehensive insights into product composition and additive content.

## User Preferences
Preferred communication style: Simple, everyday language.
Preferred approach: Simplified category-by-category analysis in read-only mode without database modifications.

**CRITICAL DEVELOPMENT RULE**: Always check existing database schema FIRST before making any assumptions about table names, field names, or database structure. Use SQL queries to verify actual schema before writing code that references database tables/columns.

**CRITICAL COMMUNICATION RULE**: NEVER invent, assume, or imagine facts, data, category names, product information, or system details. When you don't know something factual about the system, Rimi categories, product data, or any other concrete information:
1. Explicitly state "I don't know" or "I need to check"  
2. Ask the user directly for the correct information
3. Use available tools to verify facts from actual data sources
4. Do not provide examples or suggestions based on assumptions
5. Do not create placeholder lists or fictional category mappings

## System Architecture

### Deployment Architecture (Dual Deployment)

The system uses a **dual deployment strategy** to optimize costs and performance:

| Component | Deployment Type | Purpose | Cost Model |
|-----------|----------------|---------|------------|
| **Streamlit UI** | Autoscale | User interface, on-demand access | Pay-per-use (scales to zero when idle) |
| **Worker System** | Reserved VM | 24/7 background processing, daily auto-updates | Flat $20/month (0.5 vCPU / 2GB RAM) |

**Why Dual Deployment:**
- Worker runs continuously → Reserved VM provides flat-rate pricing ($20/month vs. $60-100+/month on Autoscale)
- Streamlit UI only active during user sessions → Autoscale scales to zero, minimizing compute unit costs
- Scheduled daily updates at 2am Latvia time avoid Rimi's midnight maintenance window
- Total cost: ~$23-26/month (vs. $80-120+/month with single Autoscale deployment)

**See:** `RESERVED_VM_SETUP.md` for complete migration guide and setup instructions.

### Application Architecture

The application features a modular Python architecture comprising:
- **Frontend**: Streamlit for the user interface and job queueing (runs on Autoscale).
- **Worker System**: Standalone CLI worker (`worker.py`) for background category processing (runs on Reserved VM), independent of Streamlit sessions.
- **Job Queue**: PostgreSQL-based job queue with worker registration, heartbeat monitoring, and stale job reassignment.
- **Backend**: Python modules for web scraping, data processing, and database interactions.
- **Database**: PostgreSQL for persistent storage of product, nutritional, and additive data (shared between both deployments).
- **Parsing Engine**: Custom logic for E-number extraction and ingredient analysis.

**Key Technical Implementations:**
- **Web Scraping**: Handles dynamic content, extracts product details (name, SKU, price, ingredients, nutrition), and includes retry logic.
- **Additive Processing**: Identifies and standardizes E-numbers from ingredient lists using regex, managing database storage.
- **Database Management**: Utilizes connection pooling, auto-retry logic, and supports schema creation for products, nutritional data, and additives.
- **Streamlit Interface**: Provides a web UI for product search, scraping, data visualization, and real-time feedback, with caching for performance.
- **Data Flow**: User input (Rimi URLs) triggers scraping, followed by data processing, additive analysis, PostgreSQL storage, and Streamlit visualization.
- **UI/UX Decisions**: The Streamlit interface focuses on clear presentation of product data, nutritional information, and additive analysis.
- **Deployment**: Configured for Replit with Python 3.11, PostgreSQL 16, Streamlit on port 5000 (exposed as 80), and autoscale deployment.
- **Database Schema**: Key tables include `Products` (SKU, name, price), `Nutritional Information` (detailed nutrition), `Additives` (E-number catalog), and `Product-Additive Relationships`.
  - **Enrichment Tracking**: Products table includes columns for nutrition data enrichment:
    - `nutrition_source`: Tracks data origin ('rimi_scraped', 'ai_generated', 'manual_entry')
    - `needs_enrichment`: Flags products requiring AI enrichment for missing nutrition data
    - `enrichment_reviewed`: Tracks manual review status of AI-generated nutrition data
- **Core Features**:
    - Complete photo extraction and storage from Rimi's CDN, distinguishing between parsing and database saving failures.
    - Robust nutrition data parsing, including handling Latvian labels and Unicode characters, with auto-calculation of nutri-scores.
    - Comprehensive quantity extraction and storage for various units.
    - Enhanced ingredient processing with normalization, deduplication, and handling of certification patterns (e.g., "Lauksaimniecība ES").
    - Accurate price parsing, handling multi-line formats.
    - Hierarchical category matching for precise product counting and comparison, identifying new, missing, and changed products.
    - Robust database connection management with retry logic and health checks.
    - Batch processing system with thread-safe connection pooling and Streamlit interface.
    - Corruption fix system for data integrity, including force update capabilities for null values and incorrect categories.
    - **Standalone Worker System**:
      - Background processing via `worker.py` CLI independent of Streamlit sessions
      - Job queue with priority scheduling, heartbeat monitoring, and fault tolerance
      - Prevents SessionInfo errors by decoupling processing from web session lifecycle
      - Supports overnight processing of 9000+ products
      - Worker registration with hostname/PID tracking and graceful shutdown
      - Stale job reassignment when workers die (heartbeat timeout: 2x interval)
      - Job event logging for lifecycle tracking and debugging
      - Usage: `python worker.py --resume-all --heartbeat-interval 30 --chunk-size 15`

## External Dependencies
- **Streamlit**: Web application framework.
- **BeautifulSoup4**: HTML parsing.
- **psycopg2**: PostgreSQL adapter.
- **requests**: HTTP library.
- **pandas**: Data manipulation.
- **trafilatura**: Text extraction from web pages.
- **urllib3**: HTTP client with retry support.
- **openai**: (Future enhancement) AI integration.