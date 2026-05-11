"""Shared utilities for strategy builders.

These are intentionally small and pure — easy to unit-test and reason about.
"""

from __future__ import annotations

from scanner.models import CalendarCandidate, CalendarLeg, OptionQuote


def add_rejection(rejections: dict[str, int], reason: str) -> None:
    rejections[reason] = rejections.get(reason, 0) + 1


def atm_round(price: float, increment: float = 5.0) -> float:
    """Round to nearest multiple of `increment`. Used for ATM strike pinning."""
    if increment <= 0:
        return price
    return round(price / increment) * increment


def nearest_by_strike(quotes: list[OptionQuote], target_strike: float) -> OptionQuote | None:
    usable = [q for q in quotes if q.has_required_data()]
    if not usable:
        return None
    return min(usable, key=lambda q: abs(q.strike - target_strike))


def nearest_by_abs_delta(quotes: list[OptionQuote], target_abs_delta: float) -> OptionQuote | None:
    """Useful for puts where delta is negative. Matches |delta| to target."""
    usable = [q for q in quotes if q.has_required_data() and q.delta is not None]
    if not usable:
        return None
    return min(usable, key=lambda q: abs(abs(q.delta) - target_abs_delta))


def expiry_pair_by_target_dte(
    dte_by_expiry: dict[str, int],
    short_target: int,
    long_target: int,
    tolerance: int,
) -> tuple[str, str] | None:
    """Pick the front expiry closest to short_target and the back expiry closest
    to long_target, each within tolerance. Returns None if either is missing."""
    candidates_front = [(exp, dte, abs(dte - short_target)) for exp, dte in dte_by_expiry.items() if abs(dte - short_target) <= tolerance]
    candidates_back = [(exp, dte, abs(dte - long_target)) for exp, dte in dte_by_expiry.items() if abs(dte - long_target) <= tolerance]
    if not candidates_front or not candidates_back:
        return None
    candidates_front.sort(key=lambda r: (r[2], r[1]))
    candidates_back.sort(key=lambda r: (r[2], r[1]))
    for f_exp, f_dte, _ in candidates_front:
        for b_exp, b_dte, _ in candidates_back:
            if b_dte > f_dte and b_exp != f_exp:
                return (f_exp, b_exp)
    return None


def all_expiry_pairs_within_window(
    dte_by_expiry: dict[str, int],
    short_target: int | None = None,
    long_target: int | None = None,
    tolerance: int | None = None,
) -> list[tuple[str, str]]:
    """Return all (front, back) expiry pairs where back DTE > front DTE.

    If targets+tolerance supplied, restrict to pairs near those targets.
    """
    if short_target is not None and tolerance is not None:
        fronts = [exp for exp, dte in dte_by_expiry.items() if abs(dte - short_target) <= tolerance]
    else:
        fronts = list(dte_by_expiry.keys())
    if long_target is not None and tolerance is not None:
        backs = [exp for exp, dte in dte_by_expiry.items() if abs(dte - long_target) <= tolerance]
    else:
        backs = list(dte_by_expiry.keys())
    pairs = []
    for f in fronts:
        for b in backs:
            if dte_by_expiry[b] > dte_by_expiry[f]:
                pairs.append((f, b))
    return pairs


def build_candidate_aggregates(candidate: CalendarCandidate) -> None:
    """Recompute net_debit, total_delta/theta/vega/gamma from legs.

    net_debit convention: positive = pay (debit); negative = receive (credit).
    Short leg short_proceeds = bid; long leg cost = ask (conservative).
    """
    net_debit = 0.0
    td = tt = tv = tg = 0.0
    for leg in candidate.legs:
        q = leg.quote
        # Conservative pricing
        if leg.action == "BUY":
            net_debit += leg.quantity * (q.ask or 0.0)
        else:
            net_debit -= leg.quantity * (q.bid or 0.0)
        td += leg.delta_contribution
        tt += leg.theta_contribution
        tv += leg.vega_contribution
        tg += leg.gamma_contribution
    candidate.net_debit = net_debit
    candidate.total_delta = td
    candidate.total_theta = tt
    candidate.total_vega = tv
    candidate.total_gamma = tg


def expected_move_for_expiry(
    quotes_by_expiry: dict[str, list[OptionQuote]],
    expiry: str,
    spot: float,
    call_quotes_by_expiry: dict[str, list[OptionQuote]] | None = None,
) -> float | None:
    """ATM straddle (put + call) at the given expiry. Returns None if either side missing.

    quotes_by_expiry typically holds puts; call_quotes_by_expiry must be passed
    separately if calls are also fetched. If only puts available, fall back to
    2 * ATM put mid as a rough EM proxy (Triple Cal entry-time rule of thumb).
    """
    puts = [q for q in quotes_by_expiry.get(expiry, []) if q.right.upper() == "P"]
    atm_put = nearest_by_strike(puts, spot)
    if atm_put is None or atm_put.mid is None:
        return None
    if call_quotes_by_expiry:
        calls = call_quotes_by_expiry.get(expiry, [])
        atm_call = nearest_by_strike(calls, spot)
        if atm_call is not None and atm_call.mid is not None:
            return float(atm_put.mid) + float(atm_call.mid)
    # Fallback: 2 * ATM put mid (ATM straddle ≈ 2x ATM single)
    return 2.0 * float(atm_put.mid)
