-- This describes source snapshots, not final settlement or a deduplicated market curve.
SELECT dataset, source_file_date, count(*) AS records,
       count(DISTINCT record_id) AS distinct_records,
       count(DISTINCT source_file) AS source_files,
       count(DISTINCT national_grid_bm_unit) AS national_grid_bm_units,
       count(*) FILTER (WHERE bm_unit IS NULL) AS unmapped_bm_unit_records,
       min(time_from) AS earliest_interval, max(time_to) AS latest_interval
FROM elexon
GROUP BY dataset, source_file_date;
