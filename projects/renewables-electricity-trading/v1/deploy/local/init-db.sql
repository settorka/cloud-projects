\getenv trading_password TRADING_DB_PASSWORD
\getenv market_password MARKET_DATA_DB_PASSWORD
\getenv valuation_password VALUATION_DB_PASSWORD
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE ROLE trading LOGIN PASSWORD :'trading_password';
CREATE ROLE market_data LOGIN PASSWORD :'market_password';
CREATE ROLE valuation LOGIN PASSWORD :'valuation_password';
CREATE SCHEMA trading AUTHORIZATION trading;
CREATE SCHEMA market_data AUTHORIZATION market_data;
CREATE SCHEMA valuation AUTHORIZATION valuation;
ALTER ROLE trading SET search_path TO trading;
ALTER ROLE market_data SET search_path TO market_data;
ALTER ROLE valuation SET search_path TO valuation;
