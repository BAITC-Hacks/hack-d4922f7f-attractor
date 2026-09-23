"""Explicit synthetic demo inputs, not measurements of Astana."""


def build_demo_dataset(district_count: int = 6) -> dict:
    """Return independent five- or six-district fixtures with the same contract."""
    names = [
        ("almaty", "Алматы"), ("baikonur", "Байконыр"), ("esil", "Есиль"),
        ("nura", "Нура"), ("saryarka", "Сарыарка"), ("sarayshyk", "Сарайшық"),
    ]
    if district_count not in (5, 6):
        raise ValueError("The demo fixture supports five or six districts")
    districts = []
    for index, (district_id, name) in enumerate(names[:district_count]):
        population = 1200 + index * 150
        districts.append({
            "id": district_id, "name": name, "population": population,
            "roadCapacity": 110 if district_id == "nura" else 190,
            "travelMinutes": 18 + index * 2, "schoolCapacity": 250 + index * 15,
            "housingUnits": population // 3 + 60, "housingPrice": 25000000 + index * 1000000,
            "crews": 1 if district_id == "nura" else 2,
        })
    return {
        "schemaVersion": "v2-city/1.0", "mode": "dynamic-v2", "status": "synthetic",
        "currency": "KZT", "basePeriod": "2026-01", "startSimTime": "2026-01-01T00:00:00Z",
        "districts": districts,
        "weather": {"snowStartMinute": 60, "snowEndMinute": 360, "intensity": 0.8},
        "finance": {"cash": 100000000, "requiredReserve": 1000000},
        "parameters": {},
        "units": {
            "population": "person", "roadCapacity": "person-trip/15min", "travelMinutes": "minute",
            "schoolCapacity": "place", "housingUnits": "dwelling", "housingPrice": "KZT/dwelling",
            "crews": "crew", "cash": "KZT", "requiredReserve": "KZT", "intensity": "fraction",
        },
        "assumptions": [
            "All populations, capacities, prices and causal coefficients are synthetic assumptions.",
            "District names label a synthetic city; this is not a forecast or a real municipal budget.",
            "Strategic periods use fixed 30-day model months, not calendar months.",
        ],
    }
