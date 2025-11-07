"""
Database Configuration Manager
Handles switching between development (single DB) and production (separate DBs) environments.
"""
import os
from typing import Optional


class DatabaseConfig:
    """Centralized database configuration for dev/prod environment switching"""
    
    def __init__(self):
        self.environment = os.getenv('ENVIRONMENT', 'production').lower()
        self.dev_mode = self.environment in ['development', 'dev'] or os.getenv('DEV_MODE', '').lower() in ['true', '1', 'yes']
        
        # Single database URL for both development and production
        # This app uses a single PostgreSQL database for all data
        self.database_url = os.getenv('DATABASE_URL')
        
        # Legacy support for separate production databases (optional)
        self.prod_categories_db_url = os.getenv('CATEGORIES_DB_URL') 
        self.prod_products_db_url = os.getenv('PRODUCTS_DB_URL')
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode"""
        return self.dev_mode
        
    @property 
    def categories_db_url(self) -> str:
        """Get categories database URL for current environment"""
        # Use separate production DB if configured, otherwise use single DATABASE_URL
        if not self.is_development and self.prod_categories_db_url:
            return self.prod_categories_db_url
        
        if not self.database_url:
            raise ValueError("DATABASE_URL must be set")
        return self.database_url
    
    @property
    def products_db_url(self) -> str:
        """Get products database URL for current environment"""
        # Use separate production DB if configured, otherwise use single DATABASE_URL
        if not self.is_development and self.prod_products_db_url:
            return self.prod_products_db_url
            
        if not self.database_url:
            raise ValueError("DATABASE_URL must be set")
        return self.database_url
    
    def get_environment_info(self) -> dict:
        """Get current environment configuration info"""
        return {
            'environment': self.environment,
            'is_development': self.is_development,
            'dev_mode': self.dev_mode,
            'has_database_url': bool(self.database_url),
            'has_prod_categories': bool(self.prod_categories_db_url),
            'has_prod_products': bool(self.prod_products_db_url),
            'using_single_db': bool(self.database_url) and not (self.prod_categories_db_url or self.prod_products_db_url)
        }


# Global instance for easy import
db_config = DatabaseConfig()