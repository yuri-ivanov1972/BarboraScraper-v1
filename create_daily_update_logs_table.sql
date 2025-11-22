-- Create daily_update_logs table to store historical update statistics
-- This table tracks automated daily updates and manual update runs

CREATE TABLE IF NOT EXISTS daily_update_logs (
    id SERIAL PRIMARY KEY,
    update_type VARCHAR(50) NOT NULL DEFAULT 'daily',  -- daily, manual, on-demand
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    duration_minutes DECIMAL(10, 2),
    
    -- Job statistics
    categories_processed INTEGER DEFAULT 0,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    
    -- Product statistics
    products_added INTEGER DEFAULT 0,
    products_updated INTEGER DEFAULT 0,
    products_removed INTEGER DEFAULT 0,
    
    -- Change tracking
    price_changes_count INTEGER DEFAULT 0,
    availability_changes JSONB,  -- Store detailed availability changes
    ingredient_changes_count INTEGER DEFAULT 0,
    nutrition_changes_count INTEGER DEFAULT 0,
    photo_changes_count INTEGER DEFAULT 0,
    
    -- Error tracking
    errors_count INTEGER DEFAULT 0,
    error_details JSONB,  -- Store error details
    
    -- Summary
    summary TEXT,  -- Human-readable summary
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_daily_update_logs_start_time ON daily_update_logs(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_daily_update_logs_update_type ON daily_update_logs(update_type);
CREATE INDEX IF NOT EXISTS idx_daily_update_logs_created_at ON daily_update_logs(created_at DESC);

-- Add comments
COMMENT ON TABLE daily_update_logs IS 'Historical log of daily automated updates and manual update runs';
COMMENT ON COLUMN daily_update_logs.update_type IS 'Type of update: daily, manual, on-demand';
COMMENT ON COLUMN daily_update_logs.availability_changes IS 'JSON object with back_in_stock and out_of_stock counts';
COMMENT ON COLUMN daily_update_logs.error_details IS 'JSON array of error details with category, message, and timestamp';
