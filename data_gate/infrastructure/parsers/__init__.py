from data_gate.infrastructure.parsers.city_json import CityJsonParser
from data_gate.infrastructure.parsers.geojson import TerritoryGeoJsonParser
from data_gate.infrastructure.parsers.source_text_v1 import SourceTextV1Parser
from data_gate.infrastructure.parsers.v2 import CsvParser, ObservationsJsonParser, V2CityJsonParser, XlsxParser

ALL_PARSERS = (
    SourceTextV1Parser(), CityJsonParser(), TerritoryGeoJsonParser(),
    V2CityJsonParser(), ObservationsJsonParser(), CsvParser(), XlsxParser(),
)

__all__ = ["ALL_PARSERS", "CityJsonParser", "SourceTextV1Parser", "TerritoryGeoJsonParser",
           "V2CityJsonParser", "ObservationsJsonParser", "CsvParser", "XlsxParser"]
