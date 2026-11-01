-- Prices across published BOD snapshots, not a weighted or executable market price.
SELECT source_file_date, count(*) AS snapshot_records,
       min(bid) AS minimum_bid, max(bid) AS maximum_bid,
       min(offer) AS minimum_offer, max(offer) AS maximum_offer,
       count(*) FILTER (WHERE bid < 0 OR offer < 0) AS negative_price_records
FROM elexon
WHERE dataset = 'BOD'
GROUP BY source_file_date
ORDER BY source_file_date;
