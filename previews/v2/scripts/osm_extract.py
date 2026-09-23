#!/usr/bin/env python3
"""Convert a bounded OSM XML snapshot into compact building and road GeoJSON."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def convert(source: Path) -> dict:
    root = ET.parse(source).getroot()
    nodes: dict[str, list[float]] = {}
    ways: list[ET.Element] = []

    for node in root.findall("node"):
        node_id = node.get("id")
        lat, lon = node.get("lat"), node.get("lon")
        if node_id and lat and lon:
            nodes[node_id] = [float(lon), float(lat)]
    ways.extend(root.findall("way"))

    features: list[dict] = []
    for way in ways:
        tags = {tag.get("k"): tag.get("v") for tag in way.findall("tag")}
        refs = [nd.get("ref") for nd in way.findall("nd")]
        coordinates = [nodes[ref] for ref in refs if ref in nodes]
        if len(coordinates) < 2:
            continue
        way_id = way.get("id")
        common = {"osm_id": way_id, "name": tags.get("name")}

        building = tags.get("building")
        if building and building.lower() != "no" and len(coordinates) >= 4 and coordinates[0] == coordinates[-1]:
            explicit_height = number(tags.get("height"))
            levels = number(tags.get("building:levels"))
            if explicit_height and 2 <= explicit_height <= 500:
                height, height_source = explicit_height, "osm:height"
            elif levels and 1 <= levels <= 100:
                height, height_source = levels * 3.0, "osm:building:levels×3m"
            else:
                height, height_source = 12.0, "visual-fallback:12m"
            features.append({
                "type": "Feature",
                "id": f"way/{way_id}",
                "properties": {
                    **common,
                    "kind": "building",
                    "building": building,
                    "height_m": round(height, 1),
                    "height_source": height_source,
                    "levels": levels,
                },
                "geometry": {"type": "Polygon", "coordinates": [coordinates]},
            })

        highway = tags.get("highway")
        if highway:
            features.append({
                "type": "Feature",
                "id": f"way/{way_id}/road",
                "properties": {
                    **common,
                    "kind": "road",
                    "highway": highway,
                    "surface": tags.get("surface"),
                    "lanes": number(tags.get("lanes")),
                },
                "geometry": {"type": "LineString", "coordinates": coordinates},
            })

    return {
        "type": "FeatureCollection",
        "name": "Astana OSM city-core snapshot",
        "metadata": {
            "source": "© OpenStreetMap contributors",
            "license": "ODbL 1.0",
            "source_url": "https://www.openstreetmap.org/copyright",
            "snapshot_bbox_wgs84": [71.42, 51.12, 71.44, 51.14],
            "geometry_note": "OSM-mapped building footprints and road centerlines; missing building heights use explicit fallback metadata.",
        },
        "features": features,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="OSM XML snapshot")
    parser.add_argument("output", type=Path, help="Output GeoJSON path")
    args = parser.parse_args()
    data = convert(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    buildings = sum(feature["properties"]["kind"] == "building" for feature in data["features"])
    roads = sum(feature["properties"]["kind"] == "road" for feature in data["features"])
    print(f"Wrote {args.output}: {buildings} building footprints, {roads} road centerlines, {args.output.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
