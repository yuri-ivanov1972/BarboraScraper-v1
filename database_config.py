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
        
        # Development: single database URL
        self.dev_database_url = os.getenv('DATABASE_URL')
        
        # Production: separate database URLs
        self.prod_categories_db_url = os.getenv('CATEGORIES_DB_URL') 
        self.prod_products_db_url = os.getenv('PRODUCTS_DB_URL')
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode"""
        return self.dev_mode
        
    @property 
    def categories_db_url(self) -> str:
        """Get categories database URL for current environment"""
        if self.is_development:
            if not self.dev_database_url:
                raise ValueError("DATABASE_URL must be set for development environment")
            return self.dev_database_url
        else:
            if not self.prod_categories_db_url:
                raise ValueError("CATEGORIES_DB_URL must be set for production environment")
            return self.prod_categories_db_url
    
    @property
    def products_db_url(self) -> str:
        """Get products database URL for current environment"""
        if self.is_development:
            if not self.dev_database_url:
                raise ValueError("DATABASE_URL must be set for development environment")
            return self.dev_database_url
        else:
            if not self.prod_products_db_url:
                raise ValueError("PRODUCTS_DB_URL must be set for production environment")
            return self.prod_products_db_url
    
    def get_environment_info(self) -> dict:
        """Get current environment configuration info"""
        return {
            'environment': self.environment,
            'is_development': self.is_development,
            'dev_mode': self.dev_mode,
            'has_dev_database': bool(self.dev_database_url),
            'has_prod_categories': bool(self.prod_categories_db_url),
            'has_prod_products': bool(self.prod_products_db_url)
        }


# Global instance for easy import
db_config = DatabaseConfig()