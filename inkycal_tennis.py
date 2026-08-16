"""
Tennis module for the Inkycal project — live scores from the Live Tennis API.

Shows matches currently in progress (per-set games, current points, who is
serving, and a break-point marker on the colour layer). When nothing is live,
it falls back to the upcoming fixtures schedule.

Data source: https://livetennisapi.com (spec: https://docs.livetennisapi.com/openapi.yaml)

Version 0.1.0: Initial release, targets Inkycal 2.x

by https://github.com/livetennisapi
"""
import logging
import time

import requests

from inkycal.modules.template import InkycalModule
from inkycal.utils.canvas import Canvas

logger = logging.getLogger(__name__)

API_BASE = "https://api.livetennisapi.com/api/public/v1"
REQUEST_TIMEOUT = 10  # seconds — keep network calls bounded
FIXTURES_CACHE_SECONDS = 6 * 3600  # fixtures move slowly; cache to save quota

TOURS = ["all", "atp", "wta", "challenger", "itf", "juniors"]


def is_break_point(score) -> bool:
    """Derive whether the receiver holds a break point from a Score object.

    Uses only fields of the API's ``Score`` schema (``points``, ``server``,
    ``is_tiebreak``). A break point exists when, outside a tiebreak, the
    receiver's in-game points read "AD", or the receiver is on "40" while the
    server is below 40 ("0", "15" or "30"). There is no break point in a
    tiebreak — every point there is scored the same way — and none when the
    server is unknown or the points are null (the spec allows null entries).
    """
    if not score or score.get("is_tiebreak"):
        return False
    server = score.get("server")
    if server not in (1, 2):
        return False
    points = score.get("points") or []
    if len(points) != 2:
        return False
    server_points = points[server - 1]
    receiver_points = points[2 - server]
    if receiver_points == "AD":
        return True
    return receiver_points == "40" and server_points in ("0", "15", "30")


class Tennis(InkycalModule):
    name = "Tennis - Live scores from the Live Tennis API"

    requires = {
        "api_key": {
            "label": "Your Live Tennis API key. A free key (no card) is "
                     "available at https://livetennisapi.com/subscribe/free"
        }
    }

    optional = {
        "tour": {
            "label": "Show only one tour (atp, wta, challenger, itf, juniors) "
                     "or all of them",
            "options": TOURS,
            "default": "all",
        }
    }

    def __init__(self, config):
        super().__init__(config)

        config = config['config']

        self.api_key = config['api_key']
        if not self.api_key:
            raise ValueError("api_key is required — get a free key at "
                             "https://livetennisapi.com/subscribe/free")

        tour = config.get('tour') or "all"
        if tour not in TOURS:
            raise ValueError(f"tour must be one of {TOURS}, got '{tour}'")
        self.tour = tour

        # fixtures fallback cache: (fetched_at_monotonic, data)
        self._fixtures_cache = None

        logger.debug(f'{__name__} loaded')

    def _validate(self):
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ValueError("api_key must be a non-empty string")

    def _get(self, path, params):
        """One bounded API call. Raises with a clear message on auth errors."""
        response = requests.get(
            f"{API_BASE}{path}",
            headers={"X-API-Key": self.api_key},
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 401:
            raise ValueError(
                "The Live Tennis API rejected this api_key (401). Check the "
                "key in your settings.json.")
        if response.status_code == 429:
            raise RuntimeError(
                "Live Tennis API rate limit hit (429). Increase the Inkycal "
                "update interval — see the README's quota guidance.")
        response.raise_for_status()
        return response.json()

    def _fetch_live_matches(self, limit):
        params = {"status": "live", "limit": limit}
        if self.tour != "all":
            params["tour"] = self.tour
        return self._get("/matches", params).get("data", [])

    def _fetch_fixtures(self, limit):
        now = time.monotonic()
        if self._fixtures_cache is not None:
            fetched_at, data = self._fixtures_cache
            if now - fetched_at < FIXTURES_CACHE_SECONDS:
                logger.debug("using cached fixtures")
                return data
        params = {"limit": limit}
        if self.tour != "all":
            params["tour"] = self.tour
        data = self._get("/fixtures", params).get("data", [])
        self._fixtures_cache = (now, data)
        return data

    # ------------------------------------------------------------------ #
    # formatting
    # ------------------------------------------------------------------ #

    @staticmethod
    def _truncate(text, max_chars):
        text = text or ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 1].rstrip() + "…"

    @staticmethod
    def _player_line(match, index, score):
        """One display line for player 1 (index=1) or player 2 (index=2)."""
        players = match.get("players") or {}
        player = players.get(f"p{index}") or {}
        name = player.get("name") or f"Player {index}"

        marker = "• " if score and score.get("server") == index else "  "

        parts = []
        if score:
            games = score.get("games") or []
            if len(games) == 2 and games[index - 1]:
                parts.append(" ".join(str(g) for g in games[index - 1]))
            points = score.get("points") or []
            if len(points) == 2 and points[index - 1] is not None:
                point = str(points[index - 1])
                if score.get("is_tiebreak"):
                    point = f"TB {point}"
                parts.append(point)

        scoreline = "  ".join(parts)
        name = Tennis._truncate(name, 16)
        return f"{marker}{name}  {scoreline}".rstrip()

    def _live_lines(self, matches, max_lines):
        """(black_lines, colour_lines) for the live view.

        colour_lines entries are either "" or "BP", drawn right-aligned on
        the colour layer of the same row.
        """
        black, colour = [], []
        for match in matches:
            if len(black) + 3 > max_lines:
                break
            score = match.get("score")
            header = self._truncate(match.get("tournament") or "", 24)
            round_name = match.get("round")
            if round_name:
                header = f"{header} · {round_name}"

            breakpoint_now = is_break_point(score)
            server = score.get("server") if score else None
            receiver = (3 - server) if server in (1, 2) else None

            black.append(header)
            colour.append("")
            for index in (1, 2):
                black.append(self._player_line(match, index, score))
                colour.append(
                    "BP" if (breakpoint_now and index == receiver) else "")
            if len(black) < max_lines:
                black.append("")
                colour.append("")
        return black, colour

    def _fixture_lines(self, fixtures, max_lines):
        black = ["No live matches — next up:"]
        colour = [""]
        for fixture in fixtures:
            if len(black) + 2 > max_lines:
                break
            start = fixture.get("start_time") or fixture.get("event_date")
            when = ""
            if start:
                # "2026-08-16T14:30:00Z" -> "16.08 14:30", "2026-08-16" -> "16.08"
                date_part = start[:10]
                day_month = f"{date_part[8:10]}.{date_part[5:7]}"
                when = f"{day_month} {start[11:16]}".rstrip()
            p1 = self._truncate(fixture.get("player1_name") or "?", 14)
            p2 = self._truncate(fixture.get("player2_name") or "?", 14)
            black.append(f"{when}  {p1} v {p2}".strip())
            colour.append("")
            tournament = self._truncate(fixture.get("tournament") or "", 28)
            if tournament and len(black) < max_lines:
                black.append(f"    {tournament}")
                colour.append("")
        return black, colour

    # ------------------------------------------------------------------ #
    # image generation
    # ------------------------------------------------------------------ #

    def generate_image(self):
        """Generate image for this module"""

        im_width = int(self.width - (2 * self.padding_left))
        im_height = int(self.height - (2 * self.padding_top))
        im_size = im_width, im_height
        logger.debug(f'image size: {im_width} x {im_height} px')

        canvas = Canvas(im_size=im_size, font=self.font, font_size=self.fontsize)

        line_spacing = 1
        line_height = canvas.get_line_height()
        max_lines = im_height // (line_height + line_spacing)
        spacing_top = int(im_height % line_height / 2)
        line_positions = [
            (0, spacing_top + _ * line_height) for _ in range(max_lines)]

        # 4 lines per live match (header + 2 players + blank)
        match_capacity = max(max_lines // 4, 1)
        matches = self._fetch_live_matches(limit=min(match_capacity, 20))

        if matches:
            black_lines, colour_lines = self._live_lines(matches, max_lines)
        else:
            fixtures = self._fetch_fixtures(limit=20)
            black_lines, colour_lines = self._fixture_lines(fixtures, max_lines)

        for index, text in enumerate(black_lines[:max_lines]):
            if not text:
                continue
            canvas.write(
                xy=line_positions[index],
                box_size=(im_width, line_height),
                text=text,
                alignment='left',
            )

        # break-point markers, right-aligned on the colour layer
        for index, text in enumerate(colour_lines[:max_lines]):
            if not text:
                continue
            canvas.write(
                xy=line_positions[index],
                box_size=(im_width, line_height),
                text=text,
                alignment='right',
                colour='colour',
            )

        return canvas.image_black, canvas.image_colour
