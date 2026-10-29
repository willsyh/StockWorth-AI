"""Configurable scoring thresholds.

These are PROVISIONAL MVP heuristics, not empirically validated investment thresholds.
Each metric band is a linear scale from `worst` (score 0) to `best` (score 100); the
direction is implied by which number is larger, so "lower is better" metrics such as
DER simply have `worst > best`.

Override the defaults by pointing SCORING_CONFIG_PATH at a JSON file with the same
shape (keys you omit keep their default values).
"""

import copy
import json
import os
from functools import lru_cache

DEFAULT_CONFIG: dict = {
    "version": "mvp-2026.1",
    "weights": {
        "profitability": 0.30,
        "growth": 0.20,
        "leverage": 0.20,
        "liquidity": 0.15,
        "cash_flow": 0.15,
    },
    "dimension_labels": {
        "profitability": "Profitabilitas",
        "growth": "Pertumbuhan",
        "leverage": "Leverage (Utang)",
        "liquidity": "Likuiditas",
        "cash_flow": "Arus Kas",
    },
    "dimensions": {
        "profitability": ["npm", "roe", "roa"],
        "growth": ["revenue_growth", "net_income_growth"],
        "leverage": ["der"],
        "liquidity": ["current_ratio"],
        "cash_flow": ["cash_flow_quality", "fcf_margin"],
    },
    # Below this weighted coverage no overall score is issued.
    "min_coverage_for_score": 0.6,
    # At or above this coverage the score is labelled complete instead of provisional.
    "complete_coverage": 0.9,
    "fundamental_labels": [[80, "Kuat"], [60, "Baik"], [40, "Cukup"], [0, "Lemah"]],
    "valuation_labels": [
        [70, "Relatif rendah terhadap acuan"],
        [40, "Dalam rentang acuan"],
        [0, "Relatif tinggi terhadap acuan"],
    ],
    "sector_profiles": {
        "financials_bank": "bank",
        "financials_non_bank": "financial_non_bank",
        "infrastructures": "capital_intensive",
        "transportation": "capital_intensive",
        "properties": "capital_intensive",
    },
    "profiles": {
        "default": {
            "label": "Umum (non-keuangan)",
            "not_applicable_dimensions": [],
            "bands": {
                "npm": {"worst": 0, "best": 15},
                "roe": {"worst": 0, "best": 18},
                "roa": {"worst": 0, "best": 8},
                "revenue_growth": {"worst": -10, "best": 15},
                "net_income_growth": {"worst": -20, "best": 20},
                "der": {"worst": 2.0, "best": 0.5},
                "current_ratio": {"worst": 0.8, "best": 2.0},
                "cash_flow_quality": {"worst": 0.5, "best": 1.2},
                "fcf_margin": {"worst": -5, "best": 10},
            },
            "valuation": {
                "per": {"worst": 25, "best": 8},
                "pbv": {"worst": 4.0, "best": 1.0},
            },
        },
        "capital_intensive": {
            "label": "Padat modal (infrastruktur, transportasi, properti)",
            "bands": {
                "der": {"worst": 3.0, "best": 1.0},
                "current_ratio": {"worst": 0.6, "best": 1.5},
                "fcf_margin": {"worst": -10, "best": 8},
                "roa": {"worst": 0, "best": 6},
            },
        },
        "bank": {
            "label": "Perbankan",
            "not_applicable_dimensions": ["leverage", "liquidity", "cash_flow"],
            "bands": {
                "npm": {"worst": 0, "best": 30},
                "roa": {"worst": 0, "best": 2.5},
                "roe": {"worst": 0, "best": 18},
            },
            "valuation": {
                "per": {"worst": 22, "best": 7},
                "pbv": {"worst": 3.5, "best": 0.9},
            },
        },
        "financial_non_bank": {
            "label": "Keuangan non-bank",
            "not_applicable_dimensions": ["liquidity"],
            "bands": {
                "der": {"worst": 6.0, "best": 2.0},
                "roa": {"worst": 0, "best": 4},
            },
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@lru_cache
def get_scoring_config() -> dict:
    path = os.environ.get("SCORING_CONFIG_PATH")
    if path:
        with open(path, encoding="utf-8") as fh:
            return _deep_merge(DEFAULT_CONFIG, json.load(fh))
    return copy.deepcopy(DEFAULT_CONFIG)


def resolve_profile(config: dict, sector: str | None) -> tuple[str, dict]:
    """Return (profile_name, merged profile) for a sector."""
    name = config["sector_profiles"].get(sector or "", "default")
    default = config["profiles"]["default"]
    if name == "default":
        return name, copy.deepcopy(default)
    return name, _deep_merge(default, config["profiles"][name])
