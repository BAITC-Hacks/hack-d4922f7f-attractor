from data_gate.infrastructure.parsers.city_json import CityJsonParser
from data_gate.infrastructure.parsers.geojson import TerritoryGeoJsonParser
from data_gate.infrastructure.parsers.source_text_v1 import SourceTextV1Parser

ALL_PARSERS = (SourceTextV1Parser(), CityJsonParser(), TerritoryGeoJsonParser())

__all__ = ["ALL_PARSERS", "CityJsonParser", "SourceTextV1Parser", "TerritoryGeoJsonParser"]
