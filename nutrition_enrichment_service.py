"""
Nutrition Enrichment Service

Orchestrates the nutrition data enrichment workflow:
1. Get products needing enrichment from database
2. Translate Latvian names to English
3. Search USDA for nutrition data
4. Present matches for manual review
5. Save approved data to database
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from food_translator import FoodTranslator, TranslationResult
from usda_enrichment import USDAClient, USDAFoodMatch, NutritionData
from nutriscore_calculator import calculate_nutriscore
from enrichment_availability import LATEST_AVAILABLE_SQL, QUEUE_ELIGIBLE_SQL


@dataclass
class ProductForEnrichment:
    """Product that needs nutrition data enrichment"""
    product_id: int
    sku: str
    name: str
    category_name: Optional[str] = None
    current_nutrition: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            'product_id': self.product_id,
            'sku': self.sku,
            'name': self.name,
            'category_name': self.category_name,
            'current_nutrition': self.current_nutrition
        }


@dataclass 
class EnrichmentMatch:
    """A product with its USDA match options for review"""
    product: ProductForEnrichment
    translation: TranslationResult
    usda_options: List[USDAFoodMatch] = field(default_factory=list)
    selected_index: int = 0
    status: str = 'pending'
    
    @property
    def usda_match(self) -> Optional[USDAFoodMatch]:
        """Get the currently selected USDA match"""
        if self.usda_options and 0 <= self.selected_index < len(self.usda_options):
            return self.usda_options[self.selected_index]
        return None
    
    def select_option(self, index: int):
        """Select a different USDA match option"""
        if 0 <= index < len(self.usda_options):
            self.selected_index = index
    
    def to_dict(self) -> Dict:
        return {
            'product': self.product.to_dict(),
            'translation': self.translation.to_dict(),
            'usda_options': [opt.to_dict() for opt in self.usda_options],
            'selected_index': self.selected_index,
            'usda_match': self.usda_match.to_dict() if self.usda_match else None,
            'status': self.status
        }


@dataclass
class EnrichmentBatch:
    """A batch of products for enrichment review"""
    matches: List[EnrichmentMatch] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    @property
    def total(self) -> int:
        return len(self.matches)
    
    @property
    def pending(self) -> int:
        return sum(1 for m in self.matches if m.status == 'pending')
    
    @property
    def approved(self) -> int:
        return sum(1 for m in self.matches if m.status == 'approved')
    
    @property
    def skipped(self) -> int:
        return sum(1 for m in self.matches if m.status == 'skipped')
    
    @property
    def no_match(self) -> int:
        return sum(1 for m in self.matches if m.status == 'no_match')


class NutritionEnrichmentService:
    """
    Service for enriching product nutrition data from USDA
    
    Usage:
        service = NutritionEnrichmentService()
        
        # Get products needing enrichment
        products = service.get_products_needing_enrichment(limit=20)
        
        # Process batch
        batch = service.process_batch(products)
        
        # Review and approve
        for match in batch.matches:
            if match.usda_match:
                service.approve_match(match)
            else:
                service.skip_match(match)
    """
    
    def __init__(self, status_callback=None):
        self._raw_callback = status_callback or print
        self._callback_lock = threading.Lock()
        self.db_url = os.environ.get('DATABASE_URL')
        
        self._google_key = os.environ.get('GOOGLE_TRANSLATE_API_KEY')
        self.translator = FoodTranslator(google_api_key=self._google_key, status_callback=self.status_callback)
        self.usda_client = USDAClient(status_callback=self.status_callback)
        self._translation_cache = {}
        self._cache_lock = threading.Lock()
    
    def status_callback(self, msg: str):
        """Thread-safe status callback"""
        with self._callback_lock:
            self._raw_callback(msg)
    
    def _create_thread_clients(self):
        """Create thread-local translator and USDA client"""
        translator = FoodTranslator(google_api_key=self._google_key, status_callback=self.status_callback)
        usda_client = USDAClient(status_callback=self.status_callback)
        return translator, usda_client
        
    def _get_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.db_url)
    
    def _get_cache_key(self, name: str, category: Optional[str] = None) -> str:
        """Generate cache key from product name and category"""
        import hashlib
        key = f"{name.lower().strip()}|{category or ''}"
        return hashlib.sha256(key.encode()).hexdigest()[:32]
    
    def _prefetch_translations(self, products: List[ProductForEnrichment]):
        """Prefetch all translations from DB cache in one query"""
        cache_keys = [(self._get_cache_key(p.name, p.category_name), p.name) for p in products]
        keys_only = [k[0] for k in cache_keys]
        
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT product_name_hash, product_name, english_translation, translation_method, confidence
                    FROM translation_cache
                    WHERE product_name_hash = ANY(%s)
                """, (keys_only,))
                rows = cur.fetchall()
                
                with self._cache_lock:
                    for row in rows:
                        result = TranslationResult(
                            original=row['product_name'],
                            english=row['english_translation'],
                            method=f"cache:{row['translation_method']}",
                            confidence=float(row['confidence']) if row['confidence'] else 0.8
                        )
                        self._translation_cache[row['product_name_hash']] = result
                
                self.status_callback(f"📚 Prefetched {len(rows)} translations from cache")
        finally:
            conn.close()
    
    def _get_cached_translation(self, name: str, category: Optional[str] = None) -> Optional[TranslationResult]:
        """Check in-memory cache for existing translation"""
        cache_key = self._get_cache_key(name, category)
        
        with self._cache_lock:
            return self._translation_cache.get(cache_key)
    
    def _save_translation_cache(self, name: str, category: Optional[str], result: TranslationResult):
        """Save translation to in-memory cache (DB save is batched)"""
        cache_key = self._get_cache_key(name, category)
        
        with self._cache_lock:
            self._translation_cache[cache_key] = result
            if not hasattr(self, '_pending_cache_saves'):
                self._pending_cache_saves = []
            self._pending_cache_saves.append((cache_key, name, category, result))
    
    def _flush_translation_cache(self):
        """Batch save pending translations to database"""
        with self._cache_lock:
            pending = getattr(self, '_pending_cache_saves', [])
            self._pending_cache_saves = []
        
        if not pending:
            return
        
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                for cache_key, name, category, result in pending:
                    try:
                        cur.execute("""
                            INSERT INTO translation_cache (product_name_hash, product_name, category_name, english_translation, translation_method, confidence)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (product_name_hash) DO NOTHING
                        """, (cache_key, name, category, result.english, result.method, result.confidence))
                    except Exception as e:
                        self.status_callback(f"⚠️ Cache save error: {str(e)[:50]}")
            conn.commit()
            self.status_callback(f"💾 Saved {len(pending)} translations to cache")
        except Exception as e:
            self.status_callback(f"⚠️ Cache flush error: {str(e)[:50]}")
        finally:
            conn.close()
    
    def get_enrichment_stats(self) -> Dict[str, int]:
        """Get statistics about products needing enrichment"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT 
                        COUNT(*) FILTER (WHERE {QUEUE_ELIGIBLE_SQL}) as needs_enrichment,
                        COUNT(*) FILTER (WHERE enrichment_reviewed = TRUE) as reviewed,
                        COUNT(*) FILTER (WHERE nutrition_source = 'usda_api') as from_usda,
                        COUNT(*) FILTER (WHERE nutrition_source = 'rimi_scraped') as from_rimi,
                        COUNT(*) FILTER (WHERE {QUEUE_ELIGIBLE_SQL} AND enrichment_skipped IS TRUE) as skipped,
                        COUNT(*) as total
                    FROM products p
                """)
                row = cur.fetchone()
                return {
                    'needs_enrichment': row[0] or 0,
                    'reviewed': row[1] or 0,
                    'from_usda': row[2] or 0,
                    'from_rimi': row[3] or 0,
                    'skipped': row[4] or 0,
                    'total': row[5] or 0
                }
        finally:
            conn.close()
    
    def scan_and_flag_products(self) -> Dict[str, int]:
        """
        Scan for products with missing nutrition data and flag them for enrichment.
        Returns count of newly flagged products.
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # Find products with missing/empty nutrition data that aren't already flagged
                cur.execute(f"""
                    UPDATE products p
                    SET needs_enrichment = TRUE, updated_at = NOW()
                    FROM nutritionfacts nf
                    WHERE p.product_id = nf.product_id
                      AND (p.needs_enrichment IS NULL OR p.needs_enrichment = FALSE)
                      AND (p.enrichment_reviewed IS NULL OR p.enrichment_reviewed = FALSE)
                      AND {LATEST_AVAILABLE_SQL}
                      AND (
                          (nf.energy_kj IS NULL OR nf.energy_kj = 0)
                          AND (nf.energy_kcal IS NULL OR nf.energy_kcal = 0)
                      )
                    RETURNING p.product_id
                """)
                flagged_ids = cur.fetchall()
                flagged_count = len(flagged_ids)
                conn.commit()
                
                self.status_callback(f"Flagged {flagged_count} products for enrichment")
                
                return {
                    'flagged': flagged_count
                }
        finally:
            conn.close()
    
    def get_unflagged_missing_count(self) -> int:
        """Get count of products with missing nutrition that aren't flagged yet"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT COUNT(*)
                    FROM products p
                    JOIN nutritionfacts nf ON p.product_id = nf.product_id
                    WHERE (p.needs_enrichment IS NULL OR p.needs_enrichment = FALSE)
                      AND (p.enrichment_reviewed IS NULL OR p.enrichment_reviewed = FALSE)
                      AND {LATEST_AVAILABLE_SQL}
                      AND (
                          (nf.energy_kj IS NULL OR nf.energy_kj = 0)
                          AND (nf.energy_kcal IS NULL OR nf.energy_kcal = 0)
                      )
                """)
                return cur.fetchone()[0] or 0
        finally:
            conn.close()
    
    def get_categories_needing_enrichment(self) -> List[dict]:
        """Get categories that have products needing enrichment"""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT 
                        nc.category_id,
                        nc.name_lv,
                        COUNT(p.product_id) as product_count
                    FROM normalized_categories nc
                    JOIN products p ON p.category_id = nc.category_id
                    WHERE {QUEUE_ELIGIBLE_SQL}
                    GROUP BY nc.category_id, nc.name_lv
                    ORDER BY nc.name_lv
                """)
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
    
    def get_products_needing_enrichment(self, limit: int = 20, offset: int = 0, category_id: Optional[int] = None) -> List[ProductForEnrichment]:
        """Get products that need nutrition data enrichment, optionally filtered by category"""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                category_filter = ""
                params = []
                if category_id is not None:
                    category_filter = "AND p.category_id = %s"
                    params.append(category_id)
                params.extend([limit, offset])
                
                cur.execute(f"""
                    SELECT 
                        p.product_id,
                        p.sku,
                        p.name,
                        nc.name_lv as category_name,
                        nf.energy_kcal,
                        nf.fat_total,
                        nf.fat_saturated,
                        nf.carbs_total,
                        nf.carbs_sugars,
                        nf.protein,
                        nf.salt,
                        nf.fiber,
                        COALESCE(p.enrichment_skipped, FALSE) as enrichment_skipped
                    FROM products p
                    LEFT JOIN normalized_categories nc ON p.category_id = nc.category_id
                    LEFT JOIN nutritionfacts nf ON p.product_id = nf.product_id
                    WHERE {QUEUE_ELIGIBLE_SQL}
                      {category_filter}
                    ORDER BY COALESCE(p.enrichment_skipped, FALSE) ASC, p.product_id
                    LIMIT %s OFFSET %s
                """, params)
                
                rows = cur.fetchall()
                products = []
                
                for row in rows:
                    current_nutrition = {
                        'energy_kcal': float(row['energy_kcal']) if row['energy_kcal'] else None,
                        'fat_total': float(row['fat_total']) if row['fat_total'] else None,
                        'fat_saturated': float(row['fat_saturated']) if row['fat_saturated'] else None,
                        'carbs_total': float(row['carbs_total']) if row['carbs_total'] else None,
                        'carbs_sugars': float(row['carbs_sugars']) if row['carbs_sugars'] else None,
                        'protein': float(row['protein']) if row['protein'] else None,
                        'salt': float(row['salt']) if row['salt'] else None,
                        'fiber': float(row['fiber']) if row['fiber'] else None,
                    }
                    
                    products.append(ProductForEnrichment(
                        product_id=row['product_id'],
                        sku=row['sku'],
                        name=row['name'],
                        category_name=row['category_name'],
                        current_nutrition=current_nutrition
                    ))
                
                self.status_callback(f"📦 Loaded {len(products)} products needing enrichment")
                return products
                
        finally:
            conn.close()
    
    def refresh_batch_availability(self, batch: EnrichmentBatch) -> int:
        """Prune stale cached entries, preserving matches/options for eligible products."""
        if not batch.matches:
            return 0
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT p.product_id, p.needs_enrichment,
                           COALESCE(p.enrichment_reviewed, FALSE)
                    FROM products p
                    WHERE p.product_id=ANY(%s) AND {LATEST_AVAILABLE_SQL}
                """, ([m.product.product_id for m in batch.matches],))
                available = {pid: needs and not reviewed for pid, needs, reviewed in cur.fetchall()}
            original_count = batch.total
            batch.matches = [m for m in batch.matches if m.product.product_id in available
                             and (m.status == "approved" or available[m.product.product_id])]
            return original_count - batch.total
        finally:
            conn.close()

    def _lock_eligible_product(self, cur, product_id: int) -> bool:
        """Recheck availability/eligibility before an explicit batch action writes."""
        cur.execute(f"""
            SELECT p.product_id FROM products p
            WHERE p.product_id=%s AND {QUEUE_ELIGIBLE_SQL}
            FOR UPDATE OF p
        """, (product_id,))
        return cur.fetchone() is not None

    def process_single_product(self, product: ProductForEnrichment, num_options: int = 5, 
                               translator=None, usda_client=None) -> EnrichmentMatch:
        """Process a single product: translate and search USDA for multiple options"""
        self.status_callback(f"\n🔄 Processing: {product.name} (SKU: {product.sku})")
        
        _translator = translator or self.translator
        _usda_client = usda_client or self.usda_client
        
        cached = self._get_cached_translation(product.name, product.category_name)
        if cached:
            self.status_callback(f"📚 Cache hit: '{cached.english}'")
            translation = cached
        else:
            translation = _translator.translate(product.name, category_name=product.category_name)
            self._save_translation_cache(product.name, product.category_name, translation)
        
        usda_options = _usda_client.search_and_get_top_matches(translation.english, num_options=num_options)
        
        match = EnrichmentMatch(
            product=product,
            translation=translation,
            usda_options=usda_options,
            selected_index=0,
            status='pending' if usda_options else 'no_match'
        )
        
        if usda_options:
            self.status_callback(f"✅ Found {len(usda_options)} options. Top: {usda_options[0].description} (Score: {usda_options[0].score:.1f})")
        else:
            self.status_callback(f"⚠️ No USDA match found for '{translation.english}'")
        
        return match
    
    def process_batch(self, products: List[ProductForEnrichment], max_workers: int = 3) -> EnrichmentBatch:
        """Process a batch of products for enrichment using parallel processing"""
        batch = EnrichmentBatch()
        
        self.status_callback(f"\n{'='*50}")
        self.status_callback(f"🚀 Processing batch of {len(products)} products (parallel, {max_workers} workers)")
        self.status_callback(f"{'='*50}")
        
        self._prefetch_translations(products)
        
        results_lock = threading.Lock()
        completed_count = [0]
        thread_clients = threading.local()
        
        def get_thread_clients():
            if not hasattr(thread_clients, 'translator'):
                thread_clients.translator, thread_clients.usda_client = self._create_thread_clients()
            return thread_clients.translator, thread_clients.usda_client
        
        def process_with_index(args):
            idx, product = args
            try:
                translator, usda_client = get_thread_clients()
                match = self.process_single_product(product, translator=translator, usda_client=usda_client)
                with results_lock:
                    completed_count[0] += 1
                    self.status_callback(f"✓ [{completed_count[0]}/{len(products)}] {product.name[:40]}...")
                return idx, match
            except Exception as e:
                with results_lock:
                    self.status_callback(f"⚠️ Thread error for {product.name[:30]}: {str(e)[:100]}")
                raise
        
        indexed_products = list(enumerate(products))
        results = [None] * len(products)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_with_index, item): item[0] for item in indexed_products}
            
            for future in as_completed(futures):
                try:
                    idx, match = future.result()
                    results[idx] = match
                except Exception as e:
                    idx = futures.get(future, -1)
                    self.status_callback(f"⚠️ Error processing product {idx}: {str(e)[:100]}")
        
        self._flush_translation_cache()
        
        batch.matches = [r for r in results if r is not None]
        
        self.status_callback(f"\n{'='*50}")
        self.status_callback(f"📊 Batch complete: {batch.total} total, {batch.pending} pending, {batch.no_match} no match")
        self.status_callback(f"{'='*50}")
        
        return batch
    
    def search_custom_term(self, product: ProductForEnrichment, search_term: str, num_options: int = 5) -> EnrichmentMatch:
        """Search USDA with a custom term provided by user"""
        self.status_callback(f"🔍 Custom search for '{search_term}'")
        
        usda_options = self.usda_client.search_and_get_top_matches(search_term, num_options=num_options)
        
        translation = TranslationResult(
            original=product.name,
            english=search_term,
            method='manual',
            confidence=1.0
        )
        
        return EnrichmentMatch(
            product=product,
            translation=translation,
            usda_options=usda_options,
            selected_index=0,
            status='pending' if usda_options else 'no_match'
        )
    
    def save_enrichment(self, match: EnrichmentMatch) -> bool:
        """Save approved enrichment data to database"""
        if not match.usda_match or not match.usda_match.nutrition:
            self.status_callback(f"❌ Cannot save: no nutrition data for {match.product.sku}")
            return False
        
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                if not self._lock_eligible_product(cur, match.product.product_id):
                    conn.rollback()
                    self.status_callback("Product is no longer available or awaiting enrichment; reload the batch.")
                    return False
                nutrition = match.usda_match.nutrition
                
                usda_fdc_id = match.usda_match.fdc_id
                
                cur.execute("""
                    UPDATE nutritionfacts
                    SET 
                        energy_kcal = %s,
                        energy_kj = %s,
                        fat_total = %s,
                        fat_saturated = %s,
                        carbs_total = %s,
                        carbs_sugars = %s,
                        protein = %s,
                        salt = %s,
                        fiber = %s,
                        is_fiber_correct = CASE WHEN %s IS NOT NULL AND %s > 0 THEN TRUE ELSE is_fiber_correct END,
                        usda_fdc_id = %s,
                        data_source_date = NOW()
                    WHERE product_id = %s
                """, (
                    nutrition.energy_kcal,
                    nutrition.energy_kj,
                    nutrition.fat_total,
                    nutrition.fat_saturated,
                    nutrition.carbs_total,
                    nutrition.carbs_sugars,
                    nutrition.protein,
                    nutrition.salt,
                    nutrition.fiber,
                    nutrition.fiber,
                    nutrition.fiber,
                    usda_fdc_id,
                    match.product.product_id
                ))
                
                if cur.rowcount == 0:
                    cur.execute("""
                        INSERT INTO nutritionfacts 
                        (product_id, energy_kcal, energy_kj, fat_total, fat_saturated, 
                         carbs_total, carbs_sugars, protein, salt, fiber, usda_fdc_id, data_source_date, is_fiber_correct)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                    """, (
                        match.product.product_id,
                        nutrition.energy_kcal,
                        nutrition.energy_kj,
                        nutrition.fat_total,
                        nutrition.fat_saturated,
                        nutrition.carbs_total,
                        nutrition.carbs_sugars,
                        nutrition.protein,
                        nutrition.salt,
                        nutrition.fiber,
                        usda_fdc_id,
                        nutrition.fiber is not None and nutrition.fiber > 0
                    ))
                
                cur.execute("""
                    UPDATE products
                    SET 
                        nutrition_source = 'usda_api',
                        needs_enrichment = FALSE,
                        enrichment_reviewed = TRUE,
                        updated_at = NOW()
                    WHERE product_id = %s
                """, (match.product.product_id,))
                
                nutri_score, nutri_grade = self._calculate_nutriscore(nutrition)
                
                if nutri_score is not None:
                    cur.execute("""
                        UPDATE nutritionfacts
                        SET 
                            nutri_score_points = %s,
                            nutri_score_grade = %s
                        WHERE product_id = %s
                    """, (nutri_score, nutri_grade, match.product.product_id))
                    self.status_callback(f"📊 Nutri-Score: {nutri_grade} ({nutri_score} points)")
                
                conn.commit()
                
                match.status = 'approved'
                self.status_callback(f"✅ Saved enrichment for {match.product.sku}: {match.product.name}")
                return True
                
        except Exception as e:
            conn.rollback()
            self.status_callback(f"❌ Error saving enrichment: {str(e)}")
            return False
        finally:
            conn.close()
    
    def skip_product(self, match: EnrichmentMatch, mark_reviewed: bool = False) -> bool:
        """Skip a product - marks as skipped for later review (sorted to end of batches)"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                if not self._lock_eligible_product(cur, match.product.product_id):
                    conn.rollback()
                    self.status_callback("Product is no longer available or awaiting enrichment; reload the batch.")
                    return False
                cur.execute("""
                    UPDATE products
                    SET 
                        enrichment_skipped = TRUE,
                        updated_at = NOW()
                    WHERE product_id = %s
                """, (match.product.product_id,))
                conn.commit()
                
                match.status = 'skipped'
                self.status_callback(f"⏭️ Skipped: {match.product.sku} - {match.product.name}")
                return True
                
        except Exception as e:
            conn.rollback()
            self.status_callback(f"❌ Error skipping product: {str(e)}")
            return False
        finally:
            conn.close()
    
    def unskip_product(self, match: EnrichmentMatch) -> bool:
        """Unskip a product - brings it back to normal queue position"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                if not self._lock_eligible_product(cur, match.product.product_id):
                    conn.rollback()
                    self.status_callback("Product is no longer available or awaiting enrichment; reload the batch.")
                    return False
                cur.execute("""
                    UPDATE products
                    SET 
                        enrichment_skipped = FALSE,
                        updated_at = NOW()
                    WHERE product_id = %s
                """, (match.product.product_id,))
                conn.commit()
                
                match.status = 'pending' if match.usda_options else 'no_match'
                self.status_callback(f"🔄 Unskipped: {match.product.sku} - {match.product.name}")
                return True
                
        except Exception as e:
            conn.rollback()
            self.status_callback(f"❌ Error unskipping product: {str(e)}")
            return False
        finally:
            conn.close()
    
    def _calculate_nutriscore(self, nutrition: NutritionData) -> tuple:
        """Calculate nutri-score points and grade from nutrition data
        
        Returns:
            Tuple of (score_points, grade) or (None, None) if calculation not possible
        """
        try:
            energy_kj = nutrition.energy_kj or (nutrition.energy_kcal * 4.184 if nutrition.energy_kcal else 0)
            sugars = nutrition.carbs_sugars or 0
            saturated_fat = nutrition.fat_saturated or 0
            sodium = (nutrition.salt or 0) * 400
            protein = nutrition.protein or 0
            fiber = nutrition.fiber or 0
            
            if energy_kj == 0 and sugars == 0 and saturated_fat == 0:
                self.status_callback("⚠️ Insufficient data for Nutri-Score calculation")
                return (None, None)
            
            score, grade, _ = calculate_nutriscore(
                energy_kj=energy_kj,
                sugars=sugars,
                saturated_fat=saturated_fat,
                sodium=sodium,
                protein=protein,
                fiber=fiber,
                fruits_veg_nuts=0,
                is_beverage=False,
                is_fat=False,
                is_cheese=False
            )
            
            return (score, grade)
            
        except Exception as e:
            self.status_callback(f"⚠️ Error calculating Nutri-Score: {str(e)}")
            return (None, None)


def test_enrichment_service():
    """Test the enrichment service"""
    try:
        service = NutritionEnrichmentService()
        
        print("Testing enrichment service...\n")
        
        stats = service.get_enrichment_stats()
        print(f"Enrichment stats: {stats}\n")
        
        products = service.get_products_needing_enrichment(limit=3)
        
        if products:
            print(f"\nProcessing {len(products)} products...")
            batch = service.process_batch(products)
            
            print(f"\nBatch results:")
            for match in batch.matches:
                print(f"  - {match.product.name}")
                print(f"    Translation: {match.translation.english}")
                if match.usda_match:
                    print(f"    USDA Match: {match.usda_match.description}")
                    if match.usda_match.nutrition:
                        n = match.usda_match.nutrition
                        print(f"    Nutrition: {n.energy_kcal} kcal, {n.protein}g protein")
                else:
                    print(f"    No match found")
        else:
            print("No products need enrichment")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_enrichment_service()
