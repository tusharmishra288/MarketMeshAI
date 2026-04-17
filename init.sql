-- Database Initialization Script
-- Creates tables for MarketMesh AI

-- Companies table
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    region VARCHAR(50) NOT NULL,
    company_name VARCHAR(255),
    sector VARCHAR(100),
    industry VARCHAR(100),
    market_cap BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, exchange)
);

-- Historical prices table
CREATE TABLE IF NOT EXISTS historical_prices (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    open DECIMAL(18, 4),
    high DECIMAL(18, 4),
    low DECIMAL(18, 4),
    close DECIMAL(18, 4),
    volume BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, exchange, date)
);

-- Fundamentals table
CREATE TABLE IF NOT EXISTS fundamentals (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    pe_ratio DECIMAL(10, 2),
    market_cap BIGINT,
    dividend_yield DECIMAL(6, 4),
    profit_margin DECIMAL(6, 4),
    roe DECIMAL(6, 4),
    debt_to_equity DECIMAL(10, 2),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, exchange)
);

-- Data quality scores table
CREATE TABLE IF NOT EXISTS data_quality (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    overall_score DECIMAL(5, 2),
    completeness DECIMAL(5, 2),
    consistency DECIMAL(5, 2),
    freshness DECIMAL(5, 2),
    anomaly_score DECIMAL(5, 2),
    validation_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);
CREATE INDEX IF NOT EXISTS idx_companies_exchange ON companies(exchange);
CREATE INDEX IF NOT EXISTS idx_historical_ticker_date ON historical_prices(ticker, date);
CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker ON fundamentals(ticker);

-- Insert sample data for testing
INSERT INTO companies (ticker, exchange, region, company_name, sector) VALUES
('AAPL', 'NASDAQ', 'americas', 'Apple Inc.', 'Technology'),
('MSFT', 'NASDAQ', 'americas', 'Microsoft Corporation', 'Technology'),
('GOOGL', 'NASDAQ', 'americas', 'Alphabet Inc.', 'Technology')
ON CONFLICT (ticker, exchange) DO NOTHING;

-- Watchlist table
CREATE TABLE IF NOT EXISTS watchlists (
    id        SERIAL PRIMARY KEY,
    ticker    VARCHAR(20) NOT NULL,
    exchange  VARCHAR(20) NOT NULL,
    added_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, exchange)
);

-- Price alerts table
CREATE TABLE IF NOT EXISTS price_alerts (
    id         SERIAL PRIMARY KEY,
    ticker     VARCHAR(20) NOT NULL,
    exchange   VARCHAR(20) NOT NULL,
    threshold  DECIMAL(18,4) NOT NULL,
    direction  VARCHAR(4) NOT NULL CHECK(direction IN ('up','down')),
    triggered  BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_watchlists_ticker ON watchlists(ticker);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker     ON price_alerts(ticker);

COMMENT ON TABLE companies        IS 'Master table of all tracked companies across 31 exchanges';
COMMENT ON TABLE historical_prices IS 'Daily OHLCV data for all companies';
COMMENT ON TABLE fundamentals      IS 'Company fundamental metrics updated quarterly';
COMMENT ON TABLE data_quality      IS 'Multi-source validation scores for data accuracy';
COMMENT ON TABLE watchlists        IS 'User watchlist — persists across sessions via PostgreSQL';
COMMENT ON TABLE price_alerts      IS 'User-defined price alerts; checked on quote fetch';
