"""Tests for arxaudio.tts.edge_backend (speed/rate handling).

These tests do not hit the edge-tts network service; they only exercise the
pure speed→rate conversion and the backend's construction of that rate.
"""
from __future__ import annotations

import pytest

from arxaudio.tts.edge_backend import EdgeTTSBackend, speed_to_rate


# ---------------------------------------------------------------------------
# speed_to_rate conversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "speed,expected",
    [
        (1.0, "+0%"),
        (0.8, "-20%"),
        (1.2, "+20%"),
        (1.5, "+50%"),
        (2.0, "+100%"),
        (0.5, "-50%"),
    ],
)
def test_speed_to_rate(speed, expected):
    assert speed_to_rate(speed) == expected


def test_speed_to_rate_always_signed():
    # edge-tts requires an explicit sign even at normal pace.
    assert speed_to_rate(1.0).startswith("+")
    assert speed_to_rate(0.9).startswith("-")


# ---------------------------------------------------------------------------
# Backend stores the converted rate
# ---------------------------------------------------------------------------

def test_backend_default_rate_is_normal():
    backend = EdgeTTSBackend()
    assert backend.rate == "+0%"


def test_backend_applies_speed():
    backend = EdgeTTSBackend(speed=1.5)
    assert backend.rate == "+50%"
