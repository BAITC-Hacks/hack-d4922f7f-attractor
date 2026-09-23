"""Адаптер исходного условия задачи (data/source-dataset.ru.txt) → payload city-v1.

Файл — таблицы, выгруженные «по ячейке на строку». Парсер опирается на заголовки
секций и шаблоны строк, а не на номера строк, и падает с понятной ошибкой, если
структура поменялась. Он ничего не досчитывает: «Итог D» и базовый Score уходят в
observations для сверки, а не в модель.
"""

from __future__ import annotations

import re
from math import isfinite
from typing import Any

from data_gate.application.ports import ParsedSource
from data_gate.domain.errors import SourceParseError
from data_gate.domain.quality import CITY_V1

RULES_VERSION = "1.0.0"
SNAPSHOT_ID = "official-v1"

DIRECTIONS = {
    "Транспорт": "transport",
    "Экология": "environment",
    "Соцсфера": "social",
    "Безопасность": "safety",
    "Сервисы": "services",
}
SCOPES = {"Район": "district", "Город": "city"}
_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюяәғқңөұүһі",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p", "r",
     "s", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya",
     "a", "g", "k", "n", "o", "u", "u", "h", "i"],
))
# Устоявшиеся латинские id районов Астаны; для остальных — транслитерация.
KNOWN_DISTRICT_IDS = {"Есиль": "esil", "Байконур": "baikonur"}

_INDICATOR = re.compile(r"^[A-Z]\d$")
_MEASURE = re.compile(r"^M\d+$")
_NUMBER = re.compile(r"^[+−-]?\d+(?:[.,]\d+)?$")
_EFFECT = re.compile(r"([A-Z]\d)\s*([+−-])\s*(\d+(?:[.,]\d+)?)")


class SourceTextV1Parser:
    format_id = "source-text-v1"

    def parse(self, content: bytes) -> ParsedSource:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise SourceParseError("Источник должен быть в UTF-8") from error
        lines = [line.strip() for line in text.splitlines()]
        full = "\n".join(lines)

        indicator_catalog = _indicator_catalog(lines)
        weights = _weights(lines)
        districts, declared = _districts(lines, [item["code"] for item in indicator_catalog])
        profiles = _profiles(lines, {d["name"] for d in districts})
        for district in districts:
            if district["name"] in profiles:
                district["profile"] = profiles[district["name"]]

        payload: dict[str, Any] = {
            "id": SNAPSHOT_ID,
            "rulesVersion": RULES_VERSION,
            "horizonQuarters": _int(full, r"H\s*=\s*(\d+)\s*квартал", "горизонт H"),
            "budget": _int(full, r"Бюджет:\s*(\d+)", "бюджет"),
            "requiredSelectionCount": _int(full, r"Решений ровно\s*(\d+)", "число решений"),
            "maxMeasuresPerDirection": _int(full, r"Не более\s*(\d+)\s*мер из одного направления", "лимит на направление"),
            "criticalThreshold": _int(full, r"строго меньше\s*(\d+)", "порог критичности"),
            "criticalPenalty": _int(full, r"Штраф\s*(\d+)\s*балл", "штраф"),
            "weights": weights,
            "indicatorCatalog": indicator_catalog,
            "districts": districts,
            "measures": _measures(lines),
            "synergies": _synergies(lines),
            **_conflicts(lines),
        }
        observations: dict[str, Any] = {"declaredDistrictScores": declared}
        baseline = re.search(r"Базовый Score без действий:\s*([\d.,]+)", full)
        if baseline:
            observations["declaredBaselineScore"] = float(baseline.group(1).replace(",", "."))
        return ParsedSource(
            schema=CITY_V1,
            payload=payload,
            mapped_fields=(
                "indicators", "weights", "districts", "profiles", "measures",
                "synergies", "conflicts", "rules", "horizon",
            ),
            # Текст ради людей: формула, пример набора и роль ИИ в модель не входят.
            unmapped_fields=("scoreFormulaText", "examplePortfolio", "aiRoleText"),
            observations=observations,
        )


def district_id(name: str) -> str:
    if name in KNOWN_DISTRICT_IDS:
        return KNOWN_DISTRICT_IDS[name]
    slug = "".join(_TRANSLIT.get(ch, ch) for ch in name.lower())
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    if not slug:
        raise SourceParseError(f"Не удалось построить id района «{name}»")
    return slug


def _index(lines: list[str], marker: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if lines[i] == marker or lines[i].startswith(marker):
            return i
    raise SourceParseError(f"В источнике нет секции «{marker}»")


def _block(lines: list[str], start: int) -> list[str]:
    """Строки после заголовка таблицы до первой пустой строки."""
    out: list[str] = []
    for line in lines[start:]:
        if not line:
            break
        out.append(line)
    return out


def _chunks(values: list[str], size: int, what: str) -> list[list[str]]:
    if len(values) % size:
        raise SourceParseError(f"{what}: {len(values)} ячеек не делится на {size} колонок")
    return [values[i:i + size] for i in range(0, len(values), size)]


def _num(value: str, what: str) -> float:
    cleaned = value.replace("−", "-").replace(",", ".")
    if not _NUMBER.match(value):
        raise SourceParseError(f"{what}: «{value}» не число")
    number = float(cleaned)
    if not isfinite(number):
        raise SourceParseError(f"{what}: число вне допустимого диапазона")
    return int(number) if number.is_integer() else number


def _int(text: str, pattern: str, what: str) -> int:
    match = re.search(pattern, text)
    if not match:
        raise SourceParseError(f"В источнике не найдено: {what}")
    return int(match.group(1))


def _indicator_catalog(lines: list[str]) -> list[dict[str, str]]:
    rows = _chunks(_block(lines, _index(lines, "Что означает 100 / 0") + 1), 4, "Показатели")
    catalog = []
    for code, direction, name, meaning in rows:
        if not _INDICATOR.match(code) or direction not in DIRECTIONS:
            raise SourceParseError(f"Показатели: некорректная строка {code} / {direction}")
        catalog.append({"code": code, "direction": DIRECTIONS[direction], "name": name, "scale": meaning})
    return catalog


def _weights(lines: list[str]) -> dict[str, float]:
    at = _index(lines, "w_k")
    codes = lines[at - 10:at]
    values = lines[at + 1:at + 11]
    if not all(_INDICATOR.match(c) for c in codes):
        raise SourceParseError("Веса: перед w_k ожидаются 10 кодов показателей")
    return {code: float(_num(v, f"вес {code}")) for code, v in zip(codes, values)}


def _districts(lines: list[str], codes: list[str]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    width = 2 + len(codes) + 1  # район, доля, показатели, итог D
    rows = _chunks(_block(lines, _index(lines, "Итог D") + 1), width, "Районы")
    districts, declared, seen = [], {}, set()
    for row in rows:
        name = row[0]
        did = district_id(name)
        if did in seen:
            raise SourceParseError(f"Районы: повтор {name}")
        seen.add(did)
        districts.append({
            "id": did,
            "name": name,
            "populationShare": float(_num(row[1], f"{name}: доля")),
            "indicators": {code: _num(v, f"{name}.{code}") for code, v in zip(codes, row[2:-1])},
        })
        declared[did] = float(_num(row[-1], f"{name}: Итог D"))
    return districts, declared


def _profiles(lines: list[str], names: set[str]) -> dict[str, str]:
    start = _index(lines, "Профили районов")
    profiles = {}
    for line in _block(lines, start + 1):
        name, _, text = line.partition(":")
        if name in names and text.strip():
            profiles[name] = text.strip()
    return profiles


def _measures(lines: list[str]) -> list[dict[str, Any]]:
    start = _index(lines, "Эффекты (полные")
    end = _index(lines, "Синергии", start)
    cells = [line for line in lines[start + 1:end] if line]
    measures = []
    for mid, direction, name, scope, cost, lag, effects in _chunks(cells, 7, "Мероприятия"):
        if not _MEASURE.match(mid) or direction not in DIRECTIONS or scope not in SCOPES:
            raise SourceParseError(f"Мероприятия: некорректная строка {mid}")
        parsed = {code: _num(sign.replace("−", "-") + value, f"{mid}.{code}")
                  for code, sign, value in _EFFECT.findall(effects)}
        if not parsed:
            raise SourceParseError(f"{mid}: не удалось разобрать эффекты «{effects}»")
        measures.append({
            "id": mid,
            "name": name,
            "direction": DIRECTIONS[direction],
            "scope": SCOPES[scope],
            "cost": _num(cost, f"{mid}: стоимость"),
            "lagQuarters": _integer(lag, f"{mid}: лаг"),
            "effects": parsed,
        })
    return measures


def _integer(value: str, what: str) -> int:
    number = _num(value, what)
    if not float(number).is_integer():
        raise SourceParseError(f"{what}: ожидается целое число")
    return int(number)


def _synergies(lines: list[str]) -> list[dict[str, Any]]:
    rows = _chunks(_block(lines, _index(lines, "Бонус") + 1), 2, "Синергии")
    synergies = []
    for pair, bonus in rows:
        ids = re.findall(r"M\d+", pair)
        match = re.match(r"([A-Z]\d)\s*\+\s*(\d+(?:[.,]\d+)?)\s*в районе\s*(M\d+)", bonus)
        if len(ids) != 2 or not match:
            raise SourceParseError(f"Синергии: не разобрана строка «{pair} / {bonus}»")
        synergies.append({
            "measureIds": ids,
            "targetMeasureId": match.group(3),
            "indicator": match.group(1),
            "bonus": _num(match.group(2), "бонус синергии"),
        })
    return synergies


def _conflicts(lines: list[str]) -> dict[str, list[list[str]]]:
    global_, district = [], []
    for line in _block(lines, _index(lines, "Несовместимости") + 1):
        match = re.match(r"^(M\d+)\s+и\s+(M\d+):\s*(.*)$", line)
        if not match:
            raise SourceParseError(f"Несовместимости: не разобрана строка «{line}»")
        pair = [match.group(1), match.group(2)]
        (district if "в одном районе" in match.group(3) else global_).append(pair)
    return {"globalConflicts": global_, "districtConflicts": district}
