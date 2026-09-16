"""
Route-table invariants.

FastAPI matches routes in definition order, so a concrete path declared after
a catch-all that can match it is unreachable. `GET /leads/cooling` was exactly
that: registered ~1,300 lines below `GET /leads/{lead_id}` in a 3.5k-line
main.py, it answered "Lead not found" in production while the Dashboard quietly
showed nothing. Nothing failed, because every endpoint existed and every test
called them directly.

These tests guard the shape of the route table itself.
"""

import re

from fastapi.routing import APIRoute

from app.main import app


def _api_routes():
    return [r for r in app.routes if isinstance(r, APIRoute)]


def _matches(parameterised: str, concrete: str) -> bool:
    pattern = "^" + re.sub(r"\{[^}]+\}", "[^/]+", parameterised) + "$"
    return re.match(pattern, concrete) is not None


class TestNoShadowedRoutes:
    def test_no_concrete_route_is_shadowed_by_an_earlier_catch_all(self):
        routes = _api_routes()
        shadowed = []

        for index, route in enumerate(routes):
            if "{" in route.path:
                continue
            for earlier in routes[:index]:
                if "{" not in earlier.path:
                    continue
                if not set(earlier.methods) & set(route.methods):
                    continue
                if _matches(earlier.path, route.path):
                    shadowed.append(
                        f"{sorted(route.methods)[0]} {route.path} "
                        f"is unreachable — {earlier.path} is registered first"
                    )
                    break

        assert not shadowed, "Unreachable routes:\n  " + "\n  ".join(shadowed)

    def test_cooling_leads_is_reachable(self):
        # The specific regression: a literal segment that a catch-all would eat.
        paths = {r.path for r in _api_routes()}
        assert "/leads/cooling" in paths

        routes = _api_routes()
        cooling = next(i for i, r in enumerate(routes) if r.path == "/leads/cooling")
        wildcard = next(i for i, r in enumerate(routes) if r.path == "/leads/{lead_id}")
        assert cooling < wildcard, "/leads/cooling must be registered before /leads/{lead_id}"


class TestRoutersAreMounted:
    def test_extracted_routers_still_serve_their_paths(self):
        # main.py was split into routers; every extracted prefix must still be
        # mounted, or the split silently dropped a feature.
        paths = {r.path for r in _api_routes()}
        for expected in (
            "/track/open/{email_id}",
            "/config/enrichment-provider",
            "/icp",
            "/ab-tests/results",
            "/analytics/funnel",
        ):
            assert expected in paths, f"{expected} is not mounted"
