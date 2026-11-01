-- Snapshot activity and mapping quality. This deliberately does not sum MW snapshots.
SELECT dataset, national_grid_bm_unit,
       count(*) AS snapshot_records,
       count(DISTINCT source_file_date) AS source_dates,
       count(*) FILTER (WHERE bm_unit IS NULL) AS unmapped_records,
       min(level_from) AS minimum_observed_level,
       max(level_from) AS maximum_observed_level
FROM elexon
GROUP BY dataset, national_grid_bm_unit
ORDER BY snapshot_records DESC, dataset, national_grid_bm_unit
LIMIT 50;
