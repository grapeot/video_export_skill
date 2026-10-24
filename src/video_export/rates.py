"""Exact source-rate families and explicit delivery policy."""

from fractions import Fraction

from .common import ExportError


def rate(value):
    """Accept decimal, rational, and Compressor R-prefixed frame rates."""
    try:
        parsed = Fraction(str(value).removeprefix("R"))
        if parsed <= 0:
            raise ValueError()
    except (ValueError, ZeroDivisionError) as exc:
        raise ExportError("frame_rate_invalid", "Expected a positive frame rate", value=value) from exc
    # Conventional rounded labels refer to NTSC rational rates.
    return {Fraction("23.976"): Fraction(24000, 1001),
            Fraction("29.97"): Fraction(30000, 1001),
            Fraction("59.94"): Fraction(60000, 1001),
            Fraction("119.88"): Fraction(120000, 1001)}.get(parsed, parsed)


def delivery_rate(source, maximum):
    """Preserve low rates; halve high rates until they fit the requested cap."""
    result, cap = rate(source), rate(maximum)
    while result > cap:
        result /= 2
    return result
