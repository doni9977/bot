"""Zone interpolation and safe-position selection."""
from __future__ import annotations

import math

TAU = math.tau


def current_circle(z, t):
    """The circle that is in force at match time t."""
    ss, se = z.get("shrink_start", 1e9), z.get("shrink_end", 1e9)
    c, r = z["center"], z["radius"]
    nc, nr = z["next_center"], z["next_radius"]
    if t <= ss or se <= ss:
        return (c[0], c[1]), r
    if t >= se:
        return (nc[0], nc[1]), nr
    f = (t - ss) / (se - ss)
    return (c[0] + (nc[0] - c[0]) * f, c[1] + (nc[1] - c[1]) * f), r + (nr - r) * f


def outside_amount(x, y, center, radius):
    return math.hypot(x - center[0], y - center[1]) - radius


class ZoneModel:
    def __init__(self, config, seed=0):
        self.cfg = config
        zc = config.get("zone", {})
        self.start_center = zc.get("start_center", (0.0, 0.0))
        self.start_radius = zc.get("start_radius", 560.0)
        self.phases = zc.get("phases", [])
        self.seed = seed
        self._goal = None
        self._goal_t = -1e9

    def choose_goal(self, obs, me, world, threats, params, t, sectors=None):
        """Pick a quiet, covered spot inside the next circle, away from threats.

        `sectors` are uncertain bearing/range contacts, not enemy positions;
        they only apply a soft penalty to candidate goals lying inside them.
        """
        z = obs["zone"]
        (cx, cy), r = current_circle(z, t)
        x, y, fz = me["pos"][0], me["pos"][1], me["pos"][2]
        nc, nr = z["next_center"], z["next_radius"]
        margin = params["zone_margin"]
        d = math.hypot(x - cx, y - cy)

        # Outside (or nearly outside) the circle: get back in, fast.
        if d > r * margin:
            self._goal, self._goal_t = None, -1e9
            return (cx + (x - cx) * 0.0, cy + (y - cy) * 0.0), True

        off = params["goal_offset"] * max(8.0, nr)
        base = (self.seed % 360) * math.pi / 180.0
        n = max(4, int(params["goal_candidates"]))
        tx = sum(p[0] for p in threats) / len(threats) if threats else nc[0]
        ty = sum(p[1] for p in threats) / len(threats) if threats else nc[1]
        clear_r = float(params.get("path_threat_r", 0.0))
        clear_bias = float(params.get("path_threat_bias", 0.0))
        sound_bias = float(params.get("sound_goal_bias", 0.0))

        def score_at(gx, gy):
            """Score one candidate, including how exposed the route to it is."""
            gz = world.ground(gx, gy)
            cover = world.cover_score(gx, gy, gz)
            tdist = min((math.hypot(gx - p[0], gy - p[1]) for p in threats), default=180.0)
            # prefer the side away from the threat centroid
            away = math.hypot(gx - tx, gy - ty)
            travel = math.hypot(gx - x, gy - y)
            s = (params["cover_bias"] * cover * 40.0
                 + params["threat_bias"] * min(tdist, 220.0) * 0.18
                 + params["threat_bias"] * min(away, 220.0) * 0.10
                 - params["travel_bias"] * travel * 0.35
                 + params["slope_bias"] * gz * 0.4)
            if clear_bias > 0.0 and threats and clear_r > 0.0:
                # minimum clearance to any known enemy sampled along the route,
                # at ~45 m spacing so a cluster cannot sit between samples
                steps = min(8, max(2, int(travel / 45.0) + 1))
                worst = 1e9
                for i in range(1, steps + 1):
                    f = i / steps
                    px = x + (gx - x) * f
                    py = y + (gy - y) * f
                    dd = min(math.hypot(px - p[0], py - p[1]) for p in threats)
                    if dd < worst:
                        worst = dd
                if worst < clear_r:
                    s -= clear_bias * (clear_r - worst) * 2.2
            if sectors and sound_bias > 0.0:
                s -= sound_bias * sum(q.penalty(gx, gy, me["pos"], t) for q in sectors) * 20.0
            return s

        best = None
        best_score = -1e18
        for k in range(n):
            a = base + TAU * k / n
            gx = nc[0] + math.cos(a) * off
            gy = nc[1] + math.sin(a) * off
            # must be inside the current circle with margin
            if math.hypot(gx - cx, gy - cy) > r * margin:
                continue
            if world.blocked(gx, gy, world.ground(gx, gy)):
                continue
            s = score_at(gx, gy)
            if s > best_score:
                best_score = s
                best = (gx, gy)
        if best is None:
            self._goal, self._goal_t = None, -1e9
            return (nc[0], nc[1]), False

        # Hysteresis: re-scoring a ring that moves with the next circle makes
        # the argmax jump hundreds of metres, so the mech paces in place and
        # never arrives anywhere.  Keep a valid held goal unless a candidate
        # is clearly better, and force a fresh pick every goal_replan_s.
        hold = float(params.get("goal_replan_s", 0.0))
        prev = self._goal
        if (prev is not None and hold > 0.0 and t - self._goal_t < hold
                and math.hypot(prev[0] - cx, prev[1] - cy) <= r * margin
                and not world.blocked(prev[0], prev[1], world.ground(prev[0], prev[1]))
                and score_at(prev[0], prev[1]) >= best_score - float(params.get("goal_hyst", 0.0))):
            return prev, False
        self._goal, self._goal_t = best, t
        return best, False
