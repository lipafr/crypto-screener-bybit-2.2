-- ============================================
-- CoinGecko Integration Tables
-- ============================================

-- Справочник монет CoinGecko
-- Обновляется раз в неделю при синхронизации
CREATE TABLE IF NOT EXISTS coingecko_coins (
    coingecko_id TEXT PRIMARY KEY,       -- "bitcoin", "ethereum", etc.
    symbol TEXT NOT NULL,                -- "btc", "eth", etc.
    name TEXT,                           -- "Bitcoin", "Ethereum", etc.
    last_updated INTEGER NOT NULL,       -- timestamp последнего обновления списка
    UNIQUE(symbol)
);

CREATE INDEX IF NOT EXISTS idx_coingecko_coins_symbol 
    ON coingecko_coins(symbol);

-- Маппинг Bybit символов на CoinGecko ID
-- Обновляется инкрементально
CREATE TABLE IF NOT EXISTS symbol_mapping (
    bybit_symbol TEXT PRIMARY KEY,       -- "BTC/USDT", "ETH/USDT:USDT", etc.
    coingecko_id TEXT,                   -- "bitcoin" или NULL если не найден
    market TEXT NOT NULL,                -- "spot" или "futures"
    status TEXT NOT NULL,                -- "found", "not_found", "pending"
    last_check INTEGER NOT NULL,         -- timestamp последней проверки
    sync_batch_id TEXT,                  -- ID батча синхронизации (например "2026-W03")
    FOREIGN KEY (coingecko_id) REFERENCES coingecko_coins(coingecko_id)
);

CREATE INDEX IF NOT EXISTS idx_symbol_mapping_status 
    ON symbol_mapping(status);

CREATE INDEX IF NOT EXISTS idx_symbol_mapping_batch 
    ON symbol_mapping(sync_batch_id);

CREATE INDEX IF NOT EXISTS idx_symbol_mapping_coingecko 
    ON symbol_mapping(coingecko_id);

-- Кэш данных о капитализации
-- Обновляется hourly для топ-100, on-demand для остальных
CREATE TABLE IF NOT EXISTS market_cap_cache (
    coingecko_id TEXT PRIMARY KEY,
    
    -- Basic info
    name TEXT,
    symbol TEXT,
    
    -- Price data
    current_price REAL,
    price_change_24h REAL,
    price_change_percentage_24h REAL,
    price_change_percentage_7d REAL,
    
    -- Market cap
    market_cap REAL,
    market_cap_rank INTEGER,
    market_cap_change_24h REAL,
    market_cap_change_percentage_24h REAL,
    
    -- Volume
    total_volume_24h REAL,
    
    -- Supply
    circulating_supply REAL,
    total_supply REAL,
    max_supply REAL,
    
    -- ATH/ATL
    ath REAL,
    ath_change_percentage REAL,
    ath_date INTEGER,
    atl REAL,
    atl_change_percentage REAL,
    atl_date INTEGER,
    
    -- Metadata
    last_updated INTEGER NOT NULL,      -- timestamp из CoinGecko API
    cached_at INTEGER NOT NULL,         -- когда мы сохранили в БД
    ttl INTEGER NOT NULL DEFAULT 3600,  -- время жизни кэша (секунды)
    
    FOREIGN KEY (coingecko_id) REFERENCES coingecko_coins(coingecko_id)
);

CREATE INDEX IF NOT EXISTS idx_market_cap_cache_rank 
    ON market_cap_cache(market_cap_rank);

CREATE INDEX IF NOT EXISTS idx_market_cap_cache_updated 
    ON market_cap_cache(cached_at);

-- Статус синхронизации CoinGecko
-- Хранит состояние текущей/последней синхронизации
CREATE TABLE IF NOT EXISTS sync_status (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Только одна запись
    
    -- Текущая синхронизация
    sync_state TEXT NOT NULL DEFAULT 'idle',  -- 'idle', 'in_progress', 'completed', 'failed'
    sync_started_at INTEGER,                  -- timestamp начала
    sync_completed_at INTEGER,                -- timestamp завершения
    sync_error TEXT,                          -- текст ошибки если провалилась
    
    -- Прогресс
    total_symbols INTEGER DEFAULT 0,
    processed_symbols INTEGER DEFAULT 0,
    failed_symbols INTEGER DEFAULT 0,
    
    -- Последняя успешная синхронизация
    last_full_sync_at INTEGER,                -- timestamp последней ПОЛНОЙ синхронизации
    last_full_sync_symbols INTEGER,           -- сколько символов обработано
    last_full_sync_week TEXT,                 -- неделя синхронизации (например "2026-W03")
    
    -- Планирование
    next_sync_at INTEGER,                     -- timestamp следующей синхронизации
    
    -- API usage tracking
    api_calls_minute INTEGER DEFAULT 0,
    api_minute_window_start INTEGER,          -- timestamp начала минуты
    
    api_calls_month INTEGER DEFAULT 0,
    api_month_start INTEGER,                  -- timestamp начала месяца (1 число)
    
    last_api_error TEXT,                      -- последняя ошибка API
    last_api_error_at INTEGER                 -- timestamp последней ошибки
);

-- Инициализация sync_status с дефолтными значениями
INSERT OR IGNORE INTO sync_status (id, sync_state) VALUES (1, 'idle');

-- ============================================
-- Existing tables (for reference)
-- ============================================

-- Добавить поле coingecko_enabled в settings если еще нет
-- ALTER TABLE settings ADD COLUMN coingecko_enabled BOOLEAN DEFAULT 1;
