"""Render screenshots/preview.png from mocked API data (no network, no key).

Run from the repo root, with Inkycal installed:

    python tests/render_preview.py
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import inkycal_tennis
from inkycal_tennis import Tennis
from inkycal.utils.inky_image import Inkyimage


def score(games, points, server, is_tiebreak=False):
    return {"sets": [0, 0], "games": games, "points": points,
            "server": server, "is_tiebreak": is_tiebreak,
            "win_probability_p1": None, "danger": None,
            "timestamp": "2026-08-16T14:05:00Z"}


MATCHES = [
    {"id": 1, "tournament": "Cincinnati Masters", "round": "SF",
     "players": {"p1": {"name": "C. Alcaraz"}, "p2": {"name": "J. Sinner"}},
     "score": score([[6, 4], [4, 4]], ["30", "40"], server=1)},
    {"id": 2, "tournament": "Cincinnati Masters", "round": "SF",
     "players": {"p1": {"name": "I. Swiatek"}, "p2": {"name": "A. Sabalenka"}},
     "score": score([[6, 6], [7, 6]], ["6", "5"], server=2, is_tiebreak=True)},
    {"id": 3, "tournament": "Grodzisk Challenger", "round": "QF",
     "players": {"p1": {"name": "M. Kecmanovic"}, "p2": {"name": "Z. Bergs"}},
     "score": score([[3], [5]], ["15", "AD"], server=1)},
]


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def fake_get(url, headers=None, params=None, timeout=None):
    if url.endswith("/matches"):
        return FakeResponse({"data": MATCHES, "meta": {}})
    return FakeResponse({"data": [], "meta": {}})


def main():
    module = Tennis({
        "position": 1,
        "name": "Tennis",
        "config": {"size": [400, 300], "api_key": "preview-key", "tour": "all",
                   "padding_x": 10, "padding_y": 10, "fontsize": 14,
                   "language": "en"},
    })
    with mock.patch.object(inkycal_tennis.requests, "get", fake_get):
        im_black, im_colour = module.generate_image()

    out_dir = os.path.join(os.path.dirname(__file__), "..", "screenshots")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.abspath(os.path.join(out_dir, "preview.png"))
    Inkyimage.merge(im_black, im_colour).save(out, "PNG")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
