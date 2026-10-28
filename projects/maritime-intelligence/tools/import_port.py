"""Import an operator-reviewed GeoJSON Feature. No fabricated production boundaries."""

import argparse
import json

from v1.adapters.postgres import PostgresRepository
from v1.settings import Settings

parser = argparse.ArgumentParser()
parser.add_argument("file")
parser.add_argument("--id", required=True)
parser.add_argument("--version", type=int, required=True)
parser.add_argument("--provenance", required=True)
args = parser.parse_args()
feature = json.loads(open(args.file).read())
geometry = feature["geometry"]
if geometry["type"] not in {"Polygon", "MultiPolygon"}:
    raise ValueError("A Polygon or MultiPolygon is required")
repo = PostgresRepository(Settings.load())
with repo.connect() as conn:
    conn.execute("UPDATE port_areas SET active=false WHERE id=%s", (args.id,))
    conn.execute(
        """INSERT INTO port_areas(id,version,name,provenance,boundary)
        VALUES (%s,%s,%s,%s,ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)))""",
        (
            args.id,
            args.version,
            feature.get("properties", {}).get("name", args.id),
            args.provenance,
            json.dumps(geometry),
        ),
    )
print(f"Imported {args.id} version {args.version}; historical visits were not recomputed")
