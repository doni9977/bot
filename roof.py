"""Rooftop catalog, jump+jet climbing, ledge-peeking and roof LOS-break cover.

All heights and energy costs are read from `hello.config` and `world`.
Precomputes flat climbable roof spots once during hello (<150 ms) so
per-decision queries are fast enough for the 50 ms budget.
"""
from __future__ import annotations

import math

TAU = math.tau


class RoofModel:
    def __init__(self, world, cfg=None):
        self.w = world
        self.cfg = cfg or {}
        mech = self.cfg.get("mech", {}) or {}
        self.step_up = float(mech.get("step_up", getattr(world, "step_up", 1.2)))
        self.jet_drain = float(mech.get("jet_drain", 15.0))
        self.max_rise = float(mech.get("max_rise_speed", 10.0))
        self.jump_speed = float(mech.get("jump_speed", 11.0))
        self.eye_h = float(mech.get("eye_height", getattr(world, "eye_height", 8.0)))
        self.muzzle_h = float(mech.get("muzzle_height", getattr(world, "muzzle_height", 7.0)))
        self.body_h = 0.5 * float(mech.get("height", getattr(world, "height", 9.0)))
        self.spots = []          # list of dicts: x,y,z,lx,ly,lz,dh,edges
        self.blacklist = {}      # idx -> expire_t
        if getattr(world, "ready", False):
            self._build()

    def _flat_roof(self, x, y, rz):
        w = self.w
        if w.blocked(x, y, rz):
            return False
        for k in range(8):
            a = k * TAU / 8.0
            px, py = x + math.cos(a) * 3.2, y + math.sin(a) * 3.2
            if not w.in_bounds(px, py):
                return False
            if abs(w.top[w.idx(px, py)] - rz) > 1.0:
                return False
        return True

    def _build(self):
        w = self.w
        step = 10
        nx, ny = w.nx, w.ny
        minx, miny = w.minx, w.miny
        g, top = w.g, w.top
        # Keep roof height within comfortable single-tank jet climb
        max_dh = min(26.0, self.max_rise * 2.6)
        min_dh = 7.5
        for j in range(12, ny - 12, step):
            y = miny + j
            row = j * nx
            for i in range(12, nx - 12, step):
                k = row + i
                rz = top[k]
                gz = g[k]
                dh = rz - gz
                if dh < min_dh or dh > max_dh:
                    continue
                x = minx + i
                if not self._flat_roof(x, y, rz):
                    continue
                # Find nearest climbable edge & ground launch point
                best_launch = None
                best_ld = 1e9
                edges = 0
                for d_idx in range(8):
                    a = d_idx * TAU / 8.0
                    ux, uy = math.cos(a), math.sin(a)
                    # Check if there is a drop-off within 14 m (good peek edge)
                    edge_d = None
                    for dist in (5.0, 8.0, 11.0, 14.0, 18.0, 22.0):
                        px, py = x + ux * dist, y + uy * dist
                        if not w.in_bounds(px, py):
                            break
                        tk = w.top[w.idx(px, py)]
                        gk = w.g[w.idx(px, py)]
                        if tk < rz - 5.0:
                            if dist <= 14.0:
                                edges += 1
                            edge_d = dist
                            # Step 5 m further out onto walkable ground for launch
                            for extra in (4.0, 6.0, 8.0):
                                lx, ly = x + ux * (dist + extra), y + uy * (dist + extra)
                                if not w.in_bounds(lx, ly):
                                    continue
                                lk = w.idx(lx, ly)
                                lz = w.top[lk]
                                if lz <= w.g[lk] + 1.5 and not w.blocked(lx, ly, lz):
                                    # Also verify roof landing point 3m inside edge is flat
                                    rx_in = x + ux * max(0.0, dist - 4.0)
                                    ry_in = y + uy * max(0.0, dist - 4.0)
                                    if abs(w.top[w.idx(rx_in, ry_in)] - rz) <= 1.0:
                                        if dist + extra < best_ld and (rz - lz) <= max_dh:
                                            best_ld = dist + extra
                                            best_launch = (lx, ly, lz, rx_in, ry_in)
                                    break
                            break
                if best_launch is not None and edges > 0:
                    lx, ly, lz, rx_in, ry_in = best_launch
                    self.spots.append({
                        "id": len(self.spots),
                        "x": x, "y": y, "z": rz,
                        "in_x": rx_in, "in_y": ry_in,
                        "lx": lx, "ly": ly, "lz": lz,
                        "dh": rz - lz,
                        "edges": edges,
                    })

    def on_roof(self, x, y, z):
        if not getattr(self.w, "ready", False):
            return False
        gz = self.w.ground(x, y)
        return (z - gz) >= 6.0

    def same_roof(self, x, y, z):
        w = self.w
        if not w.in_bounds(x, y):
            return False
        rz = w.top[w.idx(x, y)]
        if abs(rz - z) > 1.3:
            return False
        return not w.blocked(x, y, z)

    def blacklist_spot(self, spot_id, until_t):
        self.blacklist[spot_id] = until_t

    def pick_roof(self, x, y, z, cc, cr, nc, nr, threats, t, max_dist=180.0):
        """Pick best climbable roof inside current zone & near next zone."""
        if not self.spots:
            return None
        ccx, ccy = cc
        ncx, ncy = nc
        lim_cur = cr * 0.82
        lim_next = max(nr * 0.90, 90.0)
        best = None
        best_sc = -1e18
        for sp in self.spots:
            if self.blacklist.get(sp["id"], -1e9) > t:
                continue
            sx, sy = sp["x"], sp["y"]
            if math.hypot(sx - ccx, sy - ccy) > lim_cur:
                continue
            d_me = math.hypot(sx - x, sy - y)
            if d_me > max_dist:
                continue
            d_nc = math.hypot(sx - ncx, sy - ncy)
            in_next = 35.0 if d_nc <= lim_next else -0.35 * (d_nc - lim_next)
            # Prefer moderate height (10-20m) and multiple peek edges
            h_bonus = -abs(sp["dh"] - 14.0) * 0.6
            edge_bonus = min(sp["edges"], 4) * 4.0
            t_pen = 0.0
            if threats:
                near_t = min(math.hypot(sx - q[0], sy - q[1]) for q in threats)
                if near_t < 35.0:
                    t_pen = (35.0 - near_t) * 1.5
            sc = -d_me * 0.9 + in_next + h_bonus + edge_bonus - t_pen
            if sc > best_sc:
                best_sc = sc
                best = sp
        return best

    def find_roof_hide(self, x, y, z, threat_eyes, cc, cr):
        """Find a point on the SAME roof that breaks LOS from all threat_eyes."""
        w = self.w
        if not threat_eyes:
            return None
        eyes = threat_eyes[:3]
        best = None
        best_sc = -1e18
        # Include current position as candidate 0
        cands = [(x, y, 0.0)]
        for r in (4.0, 8.0, 12.0, 16.0):
            for k in range(12):
                a = k * TAU / 12.0
                cands.append((x + math.cos(a) * r, y + math.sin(a) * r, r))
        for px, py, r in cands:
            if math.hypot(px - cc[0], py - cc[1]) > cr * 0.88:
                continue
            if not self.same_roof(px, py, z):
                continue
            if r > 0.1 and not w.walk_clear(x, y, px, py, z):
                continue
            hidden = 0
            bz = z + self.body_h
            ez = z + self.eye_h
            for ex, ey, eez in eyes:
                if (not w.shot_clear((ex, ey, eez), (px, py, bz), step=2.5)
                        and not w.shot_clear((ex, ey, eez), (px, py, ez), step=2.5)):
                    hidden += 1
            sc = hidden * 100.0 - r * 0.8
            if sc > best_sc:
                best_sc = sc
                best = (px, py)
        return best if best_sc >= 90.0 else None

    def find_roof_peek(self, x, y, z, target_pos, cc, cr):
        """Find nearest point on the SAME roof that has clear muzzle LOS to target_pos."""
        w = self.w
        tx, ty, tz = target_pos
        base_a = math.atan2(ty - y, tx - x)
        best = None
        best_sc = -1e18
        for r in (3.5, 7.0, 11.0, 15.0):
            for da in (0.0, 0.35, -0.35, 0.75, -0.75, 1.2, -1.2, 1.7, -1.7):
                a = base_a + da
                px, py = x + math.cos(a) * r, y + math.sin(a) * r
                if math.hypot(px - cc[0], py - cc[1]) > cr * 0.88:
                    continue
                if not self.same_roof(px, py, z):
                    continue
                if not w.walk_clear(x, y, px, py, z):
                    continue
                # Ensure 2.5m margin so we don't wobble off the edge
                if w.shot_clear((px, py, z + self.muzzle_h), (tx, ty, tz), step=2.0):
                    sc = -r * 1.2 - abs(da) * 1.5
                    if sc > best_sc:
                        best_sc = sc
                        best = (px, py)
            if best is not None:
                return best
        return None

    def stay_on_roof_dir(self, x, y, z, mx, my):
        """Clamp a horizontal move vector so we do not accidentally step off the roof."""
        m = math.hypot(mx, my)
        if m < 1e-6:
            return (0.0, 0.0)
        ux, uy = mx / m, my / m
        if self.same_roof(x + ux * 3.5, y + uy * 3.5, z):
            return (ux, uy)
        base = math.atan2(uy, ux)
        for da in (0.4, -0.4, 0.8, -0.8, 1.3, -1.3, 1.8, -1.8, 2.4, -2.4, math.pi):
            a = base + da
            cx, cy = math.cos(a), math.sin(a)
            if self.same_roof(x + cx * 3.5, y + cy * 3.5, z):
                return (cx, cy)
        return (0.0, 0.0)
