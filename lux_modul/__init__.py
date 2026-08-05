"""LUX - Modul Trading Multi-Strategi Binance Futures.

Lapis: data (L0) -> fitur (L1) -> strategi (L2) -> pembobotan/arbiter (L3) -> eksekusi (L4).
"""
from .arbiter import Arbiter, Keputusan
from .data import DataPlane, KonteksEvaluasi, muat_csv
from .kontrak import (
    ARAH_LONG,
    ARAH_SHORT,
    HORIZON_INTRADAY,
    HORIZON_SCALPING,
    HORIZON_SWING,
    Bars,
    StrategyVerdict,
    TFPlan,
)
from .pipeline import HasilBar, Pipeline, StatistikJalan
from .strategi import Registry, registry_bawaan

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Bars",
    "TFPlan",
    "StrategyVerdict",
    "ARAH_LONG",
    "ARAH_SHORT",
    "HORIZON_SCALPING",
    "HORIZON_INTRADAY",
    "HORIZON_SWING",
    "DataPlane",
    "KonteksEvaluasi",
    "muat_csv",
    "Registry",
    "registry_bawaan",
    "Arbiter",
    "Keputusan",
    "Pipeline",
    "HasilBar",
    "StatistikJalan",
]
