"""Data models for the Calendar Scanner.

Models are intentionally simple dataclasses so they are easy to inspect,
serialise (to_dict for JSON / SQLite / CSV), and explain when debugging scans.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Option quote
# ---------------------------------------------------------------------------

@dataclass
class OptionQuote:
    symbol: str
    expiry: str
    strike: float
    right: str                       # "P" or "C"
    bid: float | None
    ask: float | None
    mid: float | None
    delta: float | None              # stored in 100-delta scale (54.0 not 0.54)
    theta: float | None = None       # per-contract per-day (option-price units)
    vega: float | None = None        # per-contract per-vol-point (option-price units)
    gamma: float | None = None
    implied_vol: float | None = None
    contract: Any | None = None

    def has_required_data(self) -> bool:
        return (
            self.bid is not None
            and self.ask is not None
            and self.mid is not None
            and self.delta is not None
            and self.bid >= 0
            and self.ask > 0
            and self.ask >= self.bid
        )

    def missing_data_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.bid is None or self.ask is None or self.mid is None:
            reasons.append("missing_bid_ask")
        elif self.bid < 0 or self.ask <= 0 or self.ask < self.bid:
            reasons.append("invalid_bid_ask")
        if self.delta is None:
            reasons.append("missing_delta")
        return reasons

    @property
    def spread(self) -> float:
        if self.bid is None or self.ask is None:
            return 0.0
        return max(self.ask - self.bid, 0.0)

    @property
    def spread_pct(self) -> float:
        if self.mid is None or self.mid <= 0:
            return 0.0
        return self.spread / self.mid * 100.0


# ---------------------------------------------------------------------------
# Legs and candidates
# ---------------------------------------------------------------------------

@dataclass
class CalendarLeg:
    """One leg of a multi-leg calendar / diagonal / combo candidate.

    Conventions:
    - quantity is positive (number of contracts)
    - action is "BUY" or "SELL"; signed_quantity composes them
    - conservative entry pricing: short legs at bid, long legs at ask
    """

    name: str
    action: str              # "BUY" or "SELL"
    quantity: int
    quote: OptionQuote
    role: str = ""           # free-form label e.g. "atm_cal_short", "pcs_long"

    @property
    def signed_quantity(self) -> int:
        return self.quantity if self.action == "BUY" else -self.quantity

    @property
    def conservative_price(self) -> float:
        """Bid for shorts (proceeds), ask for longs (cost)."""
        if self.action == "BUY":
            return float(self.quote.ask or 0.0)
        return float(self.quote.bid or 0.0)

    @property
    def mid_price(self) -> float:
        return float(self.quote.mid or 0.0)

    @property
    def delta_contribution(self) -> float:
        return self.signed_quantity * (self.quote.delta or 0.0)

    @property
    def theta_contribution(self) -> float:
        return self.signed_quantity * (self.quote.theta or 0.0)

    @property
    def vega_contribution(self) -> float:
        return self.signed_quantity * (self.quote.vega or 0.0)

    @property
    def gamma_contribution(self) -> float:
        return self.signed_quantity * (self.quote.gamma or 0.0)


@dataclass
class CalendarCandidate:
    """One candidate trade for any of the calendar-family strategies."""

    strategy: str            # "buddy_atm" | "triple_calendar" | "time_edge" | "time_edge_no_touch" | "time_zone"
    symbol: str
    legs: list[CalendarLeg]
    front_expiry: str
    back_expiry: str
    front_dte: int
    back_dte: int

    # Aggregates (filled by builder)
    net_debit: float = 0.0         # positive = pay; negative = receive
    total_delta: float = 0.0
    total_theta: float = 0.0
    total_vega: float = 0.0
    total_gamma: float = 0.0
    average_spread_pct: float = 0.0

    # Strategy-specific extras (free-form so individual strategies can stash data)
    extras: dict[str, Any] = field(default_factory=dict)

    # Entry-quality metrics (filled by scoring)
    theta_debit_ratio: float = 0.0
    range_debit_ratio: float = 0.0
    days_to_target_pct: float = 0.0
    vega_debit_ratio: float = 0.0

    # Scoring components (normalised 0-1)
    theta_score: float = 0.0
    range_score: float = 0.0
    days_score: float = 0.0
    vega_score: float = 0.0
    spread_penalty: float = 0.0
    liquidity_score: float = 0.0
    regime_score: float = 1.0       # multiplier from regime gate (1.0 = neutral)
    custom_score: float = 0.0
    rank: int = 0

    # Regime annotations
    regime_flags: list[str] = field(default_factory=list)
    regime_skip: bool = False

    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def position_theta(self) -> float:
        """Per-day theta in dollars (x100 multiplier)."""
        return self.total_theta * 100.0

    @property
    def position_vega(self) -> float:
        return self.total_vega * 100.0

    @property
    def position_delta(self) -> float:
        return self.total_delta

    @property
    def position_gamma(self) -> float:
        return self.total_gamma * 100.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for leg in data.get("legs", []):
            leg.get("quote", {}).pop("contract", None)
        data["position_theta"] = self.position_theta
        data["position_vega"] = self.position_vega
        data["position_delta"] = self.position_delta
        return data


# ---------------------------------------------------------------------------
# Scan settings
# ---------------------------------------------------------------------------

@dataclass
class ScanSettings:
    # Underlying
    symbol: str = "SPX"
    exchange: str = "CBOE"
    currency: str = "USD"

    # Strike-window for ATM-centred calendar fetches
    lower_strike_multiplier: float = 0.85
    upper_strike_multiplier: float = 1.15
    max_contracts_per_expiry: int = 80
    market_data_batch_size: int = 60
    strike_increment: int = 0        # 0 = any strike; 5 = SPX standard

    # DTE search window (strategies may tighten this)
    min_short_dte: int = 1
    max_long_dte: int = 60

    # Strategy selection
    strategy: str = "buddy_atm"      # which strategy to run

    # Per-strategy DTE / structure overrides (defaults follow rule docs)
    # Triple Calendar
    triple_short_dte: int = 21
    triple_long_dte: int = 28
    triple_dte_tolerance: int = 2
    triple_em_margin: float = 5.0    # extra points beyond EM for upper/lower
    triple_right: str = "P"          # "P" or "C"
    triple_require_full_straddle: bool = False

    # TimeEdge main
    te_short_dte: int = 15
    te_long_dte: int = 22
    te_dte_tolerance: int = 2
    te_right: str = "P"
    te_back_iv_excess_max: float = 1.0  # abort if back IV - front IV > this (pts of vol)

    # TimeEdge no-touch
    te_nt_short_dte: int = 15
    te_nt_long_dte: int = 43
    te_nt_dte_tolerance: int = 3
    te_nt_target_delta: float = 35.0

    # TimeZone
    tz_short_dte: int = 15
    tz_long_dte: int = 43
    tz_dte_tolerance: int = 3
    tz_pcs_short_delta: float = 14.0
    tz_pcs_width: float = 20.0
    tz_pcs_min_credit: float = 1.50
    tz_cal_short_delta: float = 40.0
    tz_quantity: int = 2

    # buddy_atm (the 4th, generic enumerator)
    buddy_min_short_dte: int = 1
    buddy_max_long_dte: int = 20
    buddy_right: str = "P"

    # A14 put BWB
    a14_dte: int = 14
    a14_dte_tolerance: int = 2
    a14_upper_delta: float = 50.0
    a14_short_delta: float = 35.0
    a14_lower_delta: float = 20.0

    # HV7 put BWB
    hv7_min_dte: int = 7
    hv7_max_dte: int = 14
    hv7_upper_delta: float = 50.0
    hv7_short_delta: float = 35.0
    hv7_lower_delta: float = 20.0
    hv7_trigger_confirmed: bool = False

    # FlyDiagonal: call BWB + put diagonal
    fly_short_dte: int = 8
    fly_long_dte: int = 15
    fly_dte_tolerance: int = 3
    fly_call_lower_delta: float = 30.0
    fly_call_short_delta: float = 20.0
    fly_call_upper_delta: float = 10.0
    fly_put_short_delta: float = 30.0
    fly_put_strike_gap: float = 10.0

    # Scoring weights (used by buddy_atm; other strategies may override)
    w_theta_debit: float = 50.0
    w_range_debit: float = 20.0
    w_days_to_target: float = 20.0
    w_vega_debit: float = 0.0
    w_spread_penalty: float = 10.0
    default_target_pct: float = 0.10

    # Filters
    max_spread_pct_hard: float = 50.0
    min_net_theta: float = 0.0      # require net positive theta for calendar
    require_positive_credit_pcs: bool = True  # for TimeZone PCS leg

    # Output
    max_results: int = 20

    # Modelling assumptions for risk chart (overridden via UI/macro_data)
    risk_free_rate: float = 0.045
    dividend_yield: float = 0.013

    # Quote cache
    cache_max_age_minutes: int = 30

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Regime snapshot (from stfs v2.6)
# ---------------------------------------------------------------------------

@dataclass
class RegimeSnapshot:
    """Minimal snapshot of stfs v2.6 outputs.

    User pastes these once per session from the TradingView dashboard.
    Effects on the scanner are deterministic and surfaced as regime_flags
    on each candidate.
    """

    # Free-form context (informational; affects soft weighting)
    ctx_state: str = "NEUTRAL"          # NEUTRAL / CRISIS / RISK_OFF_VOL / MEAN_REV_DN / MEAN_REV_UP / DRIFT_UP_TRENDING / DRIFT_UP_CALM / CHOP_LOW_VOL / CHOP_NORMAL_VOL / TRANSITION
    macro_regime: str = "NEUTRAL"       # RISK OFF / LIQUIDITY / GOLDILOCKS / NEUTRAL
    drift_state: str = "FLAT"
    vol_state: str = "NORMAL"           # EXPANDING / COMPRESSED / NORMAL
    term_state: str = "FLAT"            # BACKWARDATION / CONTANGO / FLAT / UNKNOWN
    skew_state: str = "NORMAL"          # CRASH_FEAR / COMPLACENT / NORMAL / UNKNOWN
    credit_state: str = "NEUTRAL"       # STRESSED / BID / NEUTRAL / UNKNOWN
    iv_rank: int = 50                   # 0-100, SPX IV Rank from TWS
    event_flag: str = "None"            # None / Tier-1 / Tier-2 / OPEX / Multiple

    # Per-strategy scores from stfs (0-100, used as multiplicative weight)
    stfs_score_triple: int = 50         # not in stfs; default neutral. If user wants, map from te or fly score.
    stfs_score_time_edge: int = 50
    stfs_score_time_zone: int = 50
    stfs_score_buddy_atm: int = 50      # neutral by default

    # Conviction / size hint
    conviction: int = 50

    # Optional human note
    note: str = ""

    @property
    def event_is_tier1(self) -> bool:
        return self.event_flag in ("Tier-1", "Multiple")

    @property
    def event_present(self) -> bool:
        return self.event_flag != "None"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Scan result
# ---------------------------------------------------------------------------

@dataclass
class ScanResult:
    settings: ScanSettings
    strategy: str
    candidates: list[CalendarCandidate]
    underlying_price: float | None = None
    quote_counts_by_expiry: dict[str, dict[str, Any]] = field(default_factory=dict)
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    regime: RegimeSnapshot | None = None
    extras: dict[str, Any] = field(default_factory=dict)   # strategy-specific outputs (e.g. heatmap pivot)
    mock: bool = False
