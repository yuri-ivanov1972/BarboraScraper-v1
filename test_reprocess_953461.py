#!/usr/bin/env python3
"""Test reprocessing SKU 953461 with correct availability"""

from enhanced_update_coordinator import EnhancedUpdateCoordinator

def status_print(msg):
    print(f"[TEST] {msg}")

print("="*60)
print("Reprocessing SKU 953461 to test availability fix")
print("="*60)

coordinator = EnhancedUpdateCoordinator(status_print)
result = coordinator.process_single_product_enhanced("953461", force_update=True)

print("\n" + "="*60)
print("RESULT:")
print("="*60)
print(f"Success: {result.success}")
print(f"Operation: {result.operation}")
if result.errors:
    print(f"Errors: {result.errors}")

coordinator.close()

# Verify in database
print("\n" + "="*60)
print("VERIFICATION - Checking database:")
print("="*60)

import psycopg2
import os

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("""
    SELECT price, is_available, created_at 
    FROM product_price_history pph
    JOIN products p ON pph.product_id = p.product_id
    WHERE p.sku = '953461'
    ORDER BY created_at DESC
    LIMIT 1
""")
result = cur.fetchone()
if result:
    price, is_available, created_at = result
    print(f"Latest price history: price={price}, is_available={is_available}, created_at={created_at}")
    if is_available == False:
        print("✅ PASS: is_available correctly set to FALSE")
    else:
        print("❌ FAIL: is_available should be FALSE but got TRUE")
else:
    print("❌ No price history found")

cur.close()
conn.close()
