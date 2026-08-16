"""Tests for the Inkycal tennis module (mocked API, no network)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import inkycal_tennis
from inkycal_tennis import Tennis, is_break_point


# --------------------------------------------------------------------- #
# sample payloads, shaped per docs.livetennisapi.com/openapi.yaml
# --------------------------------------------------------------------- #

def make_score(sets=(1, 0), games=((6, 4), (4, 4)), points=("30", "40"),
               server=1, is_tiebreak=False):
    return {
        "sets": list(sets),
        "games": [list(games[0]), list(games[1])],
        "points": list(points),
        "server": server,
        "is_tiebreak": is_tiebreak,
        "win_probability_p1": None,
        "danger": None,
        "timestamp": "2026-08-16T14:05:00Z",
    }


LIVE_MATCH = {
    "id": 101,
    "tournament": "Cincinnati Masters",
    "tour": "atp",
    "round": "SF",
    "round_code": "SF",
    "status": "live",
    "is_doubles": False,
    "players": {
        "p1": {"id": 1, "name": "C. Alcaraz"},
        "p2": {"id": 2, "name": "J. Sinner"},
    },
    "score": make_score(),
}

FIXTURE = {
    "id": 201,
    "event_date": "2026-08-17",
    "start_time": "2026-08-17T15:30:00Z",
    "player1_name": "I. Swiatek",
    "player2_name": "A. Sabalenka",
    "tournament": "Cincinnati Masters",
    "round": "F",
    "tour": "wta",
    "status": "upcoming",
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def fake_api(live_matches, fixtures, calls=None):
    def fake_get(url, headers=None, params=None, timeout=None):
        assert timeout is not None, "API calls must be bounded with a timeout"
        assert headers.get("X-API-Key") == "test-key"
        if calls is not None:
            calls.append(url)
        if url.endswith("/matches"):
            assert params.get("status") == "live"
            return FakeResponse({"data": live_matches, "meta": {}})
        if url.endswith("/fixtures"):
            return FakeResponse({"data": fixtures, "meta": {}})
        raise AssertionError(f"unexpected URL {url}")
    return fake_get


def make_module(tour="all"):
    return Tennis({
        "position": 1,
        "name": "Tennis",
        "config": {
            "size": [400, 300],
            "api_key": "test-key",
            "tour": tour,
            "padding_x": 10,
            "padding_y": 10,
            "fontsize": 12,
            "language": "en",
        },
    })


# --------------------------------------------------------------------- #
# break-point derivation
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("points,server,is_tiebreak,expected", [
    (("30", "AD"), 1, False, True),    # receiver AD
    (("AD", "30"), 2, False, True),    # receiver AD, other orientation
    (("30", "40"), 1, False, True),    # receiver 40, server 30
    (("0", "40"), 1, False, True),     # receiver 40, server 0
    (("40", "15"), 2, False, True),    # receiver 40, server 15 (p2 serving)
    (("40", "40"), 1, False, False),   # deuce
    (("AD", "40"), 1, False, False),   # advantage server
    (("40", "30"), 1, False, False),   # server ahead
    (("5", "6"), 1, True, False),      # tiebreak: never a break point
])
def test_is_break_point(points, server, is_tiebreak, expected):
    score = make_score(points=points, server=server, is_tiebreak=is_tiebreak)
    assert is_break_point(score) is expected


def test_is_break_point_defensive():
    assert is_break_point(None) is False
    assert is_break_point({}) is False
    assert is_break_point(make_score(server=None)) is False
    # the spec allows null point entries on live payloads
    assert is_break_point(make_score(points=(None, None))) is False


# --------------------------------------------------------------------- #
# config validation
# --------------------------------------------------------------------- #

def test_missing_api_key_rejected():
    with pytest.raises((ValueError, KeyError)):
        Tennis({"config": {"size": [400, 300], "api_key": "",
                           "padding_x": 10, "padding_y": 10,
                           "fontsize": 12, "language": "en"}})


def test_bad_tour_rejected():
    with pytest.raises(ValueError):
        make_module(tour="nfl")


# --------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------- #

def test_generate_image_live(monkeypatch):
    calls = []
    monkeypatch.setattr(inkycal_tennis.requests, "get",
                        fake_api([LIVE_MATCH], [], calls))
    module = make_module()
    im_black, im_colour = module.generate_image()
    assert im_black.size == (380, 280)
    assert im_colour.size == (380, 280)
    # live view served from one API call, no fixtures fallback
    assert len(calls) == 1
    # the receiver (p2, "40" vs server "30") holds a break point:
    # the colour layer must carry the BP marker (i.e. not be blank)
    assert im_colour.convert("L").getextrema()[0] < 255


def test_generate_image_fixtures_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(inkycal_tennis.requests, "get",
                        fake_api([], [FIXTURE], calls))
    module = make_module()
    im_black, im_colour = module.generate_image()
    assert im_black.size == (380, 280)
    assert calls[0].endswith("/matches") and calls[1].endswith("/fixtures")
    # something was drawn on the black layer
    assert im_black.convert("L").getextrema()[0] < 255

    # second refresh reuses the cached fixtures: only the live call goes out
    module.generate_image()
    assert len(calls) == 3


def test_invalid_key_raises_clear_error(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return FakeResponse({"error": "unauthorized"}, status_code=401)
    monkeypatch.setattr(inkycal_tennis.requests, "get", fake_get)
    with pytest.raises(ValueError, match="rejected this api_key"):
        make_module().generate_image()
