REVOKE CREATE ON SCHEMA public FROM PUBLIC;
\getenv trading_user TRADING_DB_USER
\getenv trading_schema TRADING_DB_SCHEMA
\getenv trading_password TRADING_DB_PASSWORD
CREATE ROLE :"trading_user" LOGIN PASSWORD :'trading_password';
CREATE SCHEMA :"trading_schema" AUTHORIZATION :"trading_user";
ALTER ROLE :"trading_user" SET search_path TO :"trading_schema";
\getenv market_user MARKET_DATA_DB_USER
\getenv market_schema MARKET_DATA_DB_SCHEMA
\getenv market_password MARKET_DATA_DB_PASSWORD
CREATE ROLE :"market_user" LOGIN PASSWORD :'market_password';
CREATE SCHEMA :"market_schema" AUTHORIZATION :"market_user";
ALTER ROLE :"market_user" SET search_path TO :"market_schema";
\getenv valuation_user VALUATION_DB_USER
\getenv valuation_schema VALUATION_DB_SCHEMA
\getenv valuation_password VALUATION_DB_PASSWORD
CREATE ROLE :"valuation_user" LOGIN PASSWORD :'valuation_password';
CREATE SCHEMA :"valuation_schema" AUTHORIZATION :"valuation_user";
ALTER ROLE :"valuation_user" SET search_path TO :"valuation_schema";
