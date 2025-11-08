#!/usr/bin/env python3
"""
Progress Manager - Handles processing progress tracking and resume capability
Enables chunked processing with checkpoint saves for large categories
"""
import psycopg2
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from database_config import get_db_connection

class ProgressManager:
    """Manages processing job tracking for resume capability"""
    
    def __init__(self, status_callback=None):
        self.status_callback = status_callback or (lambda x: None)
    
    def create_job(self, category_code: str, category_id: Optional[int], total_products: int, all_skus: List[str]) -> int:
        """
        Create a new processing job and log all SKUs as pending
        
        Args:
            category_code: Rimi category code
            category_id: Database category ID
            total_products: Total number of products to process
            all_skus: List of all product SKUs to process
            
        Returns:
            job_id: The created job ID
        """
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Create job record
            cur.execute("""
                INSERT INTO category_processing_jobs 
                (category_code, category_id, total_products, processed_count, status)
                VALUES (%s, %s, %s, 0, 'in_progress')
                RETURNING id
            """, (category_code, category_id, total_products))
            
            job_id = cur.fetchone()[0]
            
            # Log all SKUs as pending
            for sku in all_skus:
                cur.execute("""
                    INSERT INTO product_processing_log (job_id, sku, status)
                    VALUES (%s, %s, 'pending')
                """, (job_id, sku))
            
            conn.commit()
            self.status_callback(f"✓ Created processing job #{job_id} for {len(all_skus)} products")
            return job_id
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.status_callback(f"✗ Error creating job: {str(e)}")
            raise
        finally:
            if conn:
                conn.close()
    
    def get_pending_skus(self, job_id: int) -> List[str]:
        """
        Get list of SKUs that haven't been processed yet for a job
        Includes SKUs in 'pending', 'failed', and 'processing' states
        (processing state means they were interrupted mid-processing)
        
        Args:
            job_id: The processing job ID
            
        Returns:
            List of pending SKU strings
        """
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Include 'processing' status to handle interrupted chunks
            cur.execute("""
                SELECT sku FROM product_processing_log
                WHERE job_id = %s AND status IN ('pending', 'failed', 'processing')
                ORDER BY id
            """, (job_id,))
            
            skus = [row[0] for row in cur.fetchall()]
            return skus
            
        except Exception as e:
            self.status_callback(f"✗ Error getting pending SKUs: {str(e)}")
            return []
        finally:
            if conn:
                conn.close()
    
    def reset_stale_processing_records(self, job_id: int) -> int:
        """
        Reset any SKUs stuck in 'processing' state back to 'pending'
        This handles cases where processing was interrupted mid-chunk
        
        Args:
            job_id: The processing job ID
            
        Returns:
            Number of records reset
        """
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                UPDATE product_processing_log
                SET status = 'pending', error_message = 'Reset from interrupted processing'
                WHERE job_id = %s AND status = 'processing'
            """, (job_id,))
            
            reset_count = cur.rowcount
            conn.commit()
            
            if reset_count > 0:
                self.status_callback(f"✓ Reset {reset_count} interrupted SKUs back to pending")
            
            return reset_count
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.status_callback(f"✗ Error resetting stale processing records: {str(e)}")
            return 0
        finally:
            if conn:
                conn.close()
    
    def update_product_status(self, job_id: int, sku: str, status: str, error_message: Optional[str] = None):
        """
        Update the processing status of a single product
        
        Args:
            job_id: The processing job ID
            sku: Product SKU
            status: New status ('processing', 'completed', 'failed', 'skipped')
            error_message: Optional error message if failed
        """
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                UPDATE product_processing_log
                SET status = %s, error_message = %s, processed_at = CURRENT_TIMESTAMP
                WHERE job_id = %s AND sku = %s
            """, (status, error_message, job_id, sku))
            
            conn.commit()
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.status_callback(f"✗ Error updating product status: {str(e)}")
        finally:
            if conn:
                conn.close()
    
    def update_job_progress(self, job_id: int):
        """
        Update job progress based on completed products
        
        Args:
            job_id: The processing job ID
        """
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Count completed products
            cur.execute("""
                SELECT COUNT(*) FROM product_processing_log
                WHERE job_id = %s AND status IN ('completed', 'skipped')
            """, (job_id,))
            
            completed_count = cur.fetchone()[0]
            
            # Update job progress
            cur.execute("""
                UPDATE category_processing_jobs
                SET processed_count = %s, last_updated = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (completed_count, job_id))
            
            conn.commit()
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.status_callback(f"✗ Error updating job progress: {str(e)}")
        finally:
            if conn:
                conn.close()
    
    def complete_job(self, job_id: int):
        """
        Mark a job as completed
        
        Args:
            job_id: The processing job ID
        """
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                UPDATE category_processing_jobs
                SET status = 'completed', 
                    completed_at = CURRENT_TIMESTAMP,
                    last_updated = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (job_id,))
            
            conn.commit()
            self.status_callback(f"✓ Job #{job_id} marked as completed")
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.status_callback(f"✗ Error completing job: {str(e)}")
        finally:
            if conn:
                conn.close()
    
    def fail_job(self, job_id: int):
        """
        Mark a job as failed
        
        Args:
            job_id: The processing job ID
        """
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                UPDATE category_processing_jobs
                SET status = 'failed', last_updated = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (job_id,))
            
            conn.commit()
            self.status_callback(f"✗ Job #{job_id} marked as failed")
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.status_callback(f"✗ Error failing job: {str(e)}")
        finally:
            if conn:
                conn.close()
    
    def find_incomplete_job(self, category_code: str) -> Optional[Dict]:
        """
        Find an incomplete processing job for a category
        
        Args:
            category_code: Rimi category code
            
        Returns:
            Dictionary with job details or None if no incomplete job found
        """
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT id, category_code, category_id, total_products, processed_count, 
                       status, started_at, last_updated
                FROM category_processing_jobs
                WHERE category_code = %s AND status = 'in_progress'
                ORDER BY last_updated DESC
                LIMIT 1
            """, (category_code,))
            
            row = cur.fetchone()
            if row:
                return {
                    'job_id': row[0],
                    'category_code': row[1],
                    'category_id': row[2],
                    'total_products': row[3],
                    'processed_count': row[4],
                    'status': row[5],
                    'started_at': row[6],
                    'last_updated': row[7]
                }
            return None
            
        except Exception as e:
            self.status_callback(f"✗ Error finding incomplete job: {str(e)}")
            return None
        finally:
            if conn:
                conn.close()
    
    def get_job_statistics(self, job_id: int) -> Dict:
        """
        Get detailed statistics for a processing job
        
        Args:
            job_id: The processing job ID
            
        Returns:
            Dictionary with job statistics
        """
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Get job details
            cur.execute("""
                SELECT category_code, total_products, processed_count, status
                FROM category_processing_jobs
                WHERE id = %s
            """, (job_id,))
            
            job_row = cur.fetchone()
            if not job_row:
                return {}
            
            # Get status breakdown
            cur.execute("""
                SELECT status, COUNT(*) 
                FROM product_processing_log
                WHERE job_id = %s
                GROUP BY status
            """, (job_id,))
            
            status_counts = dict(cur.fetchall())
            
            return {
                'job_id': job_id,
                'category_code': job_row[0],
                'total_products': job_row[1],
                'processed_count': job_row[2],
                'job_status': job_row[3],
                'pending': status_counts.get('pending', 0),
                'completed': status_counts.get('completed', 0),
                'failed': status_counts.get('failed', 0),
                'skipped': status_counts.get('skipped', 0)
            }
            
        except Exception as e:
            self.status_callback(f"✗ Error getting job statistics: {str(e)}")
            return {}
        finally:
            if conn:
                conn.close()
