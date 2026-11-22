"""Arena model: 1 m column grid built from v2/world.json + v2/terrain.i16.

The match engine represents the world as a heightmap of 1 m columns plus
"overhang" intervals for bridges.  A column is blocked for a mech standing at
z when its solid top is above z + step_up, or when an overhang intersects the
mech's body.  Using the same representation (instead of a coarse 2 m bilinear
approximation) is what keeps us from walking into a slope the engine refuses
to climb and oscillating there forever.

Everything expensive is built once in hello (20 s budget).  Per-decision
queries are a handful of indexed array lookups.
"""
from __future__ import annotations

import heapq
import json
import math
import os
import sys
import time
from array import array
from collections import deque

TAU = math.tau
NAN = float("nan")


def _spans(ring, y):
    """Horizontal inside-spans of a flat polygon ring at height y (scanline fill)."""
    n = len(ring) // 2
    xs = []
    for k in range(n):
        k2 = (k + 1) % n
        x1, y1 = ring[2 * k], ring[2 * k + 1]
        x2, y2 = ring[2 * k2], ring[2 * k2 + 1]
        if (y1 <= y < y2) or (y2 <= y < y1):
            d = y2 - y1
            xs.append(x1 + (y - y1) * (x2 - x1) / d)
    xs.sort()
    return [(xs[m], xs[m + 1]) for m in range(0, len(xs) - 1, 2)]


class World:
    def __init__(self, map_dir, cell=1.0, nav_cell=8.0, load_trees=True, cfg=None):
        self.map_dir = map_dir
        with open(os.path.join(map_dir, "v2", "world.json"), "r", encoding="utf-8") as f:
            w = json.load(f)
        self.w = w
        cfg = cfg or {}
        mech = cfg.get("mech", {}) or {}
        cubes = cfg.get("cubes", {}) or {}
        rules = w.get("rules", {}) or {}
        self.radius = float(mech.get("radius", 2.5))
        self.height = float(mech.get("height", 9.0))
        self.step_up = float(mech.get("step_up", 1.2))
        self.eye_height = float(mech.get("eye_height", 8.0))
        self.muzzle_height = float(mech.get("muzzle_height", 7.0))
        self.front_arc_deg = float(mech.get("front_arc_deg", 180.0))
        self.rear_mult = float(mech.get("rear_mult", 1.5))
        self.size_per_cube = float(cubes.get("size_per_cube", 0.05))
        self.canopy_density = float(rules.get("canopyDensity", 0.35))
        self.canopy_block_t = float(rules.get("canopyBlockT", 0.25))
        slope_deg = float(mech.get("max_slope_deg", rules.get("maxSlopeDeg", 50.0)))
        self.max_slope = math.tan(math.radians(slope_deg))
        t = w["terrain"]
        self.minx, self.miny = float(t["minX"]), float(t["minY"])
        self.tstep, self.tscale = float(t.get("step", 1.0)), float(t.get("scale", 0.01))
        self.nx, self.ny = int(t["nx"]), int(t["ny"])
        self.maxx = self.minx + self.nx - 1
        self.maxy = self.miny + self.ny - 1
        with open(os.path.join(map_dir, "v2", "terrain.i16"), "rb") as f:
            raw = f.read()
        terr = array("h")
        terr.frombytes(raw[: self.nx * self.ny * 2])
        if sys.byteorder != "little":
            terr.byteswap()
        n = self.nx * self.ny
        self.g = array("f", [0.0]) * n          # terrain height
        self.top = array("f", [0.0]) * n        # highest solid top standing on the ground
        self.walk = array("f", [0.0]) * n       # walkable surface height (includes low bridges)
        self.obst = bytearray(n)                # 1m obstacle mask
        self.ohb = array("f", [NAN]) * n        # overhang base (NaN = none)
        self.oht = array("f", [NAN]) * n        # overhang top
        sc = self.tscale
        g_arr, top_arr, walk_arr = self.g, self.top, self.walk
        for k in range(n):
            gv = terr[k] * sc
            g_arr[k] = gv
            top_arr[k] = gv
            walk_arr[k] = gv

        self._build_prisms(w.get("prisms") or [])
        self._finalize_columns()
        self._build_block_max()
        self._build_trees(w.get("trees") if load_trees else None)

        self.cell = float(cell)
        # ---- coarse navigation grid (8m legacy) -----------------------------
        self.nav_cell = float(nav_cell)
        self.nnx = int((self.maxx - self.minx) / self.nav_cell) + 2
        self.nny = int((self.maxy - self.miny) / self.nav_cell) + 2
        self.nav_blocked = bytearray(self.nnx * self.nny)
        self.nav_z = [0.0] * (self.nnx * self.nny)
        self._build_nav()
        # ---- high-resolution 3m tactical nav grid + components --------------
        self._build_nav2()
        self.ready = True

    # ------------------------------------------------------------------ build
    def _build_prisms(self, prisms):
        nx, ny, minx, miny = self.nx, self.ny, self.minx, self.miny
        g, top, ohb, oht = self.g, self.top, self.ohb, self.oht
        for p in prisms:
            ring = p.get("ring") or []
            if len(ring) < 6:
                continue
            holes = p.get("holes") or []
            if holes and isinstance(holes[0], (int, float)):
                holes = [holes]
            base, high = float(p["base"]), float(p["top"])
            if high <= base:
                continue
            is_bridge = p.get("kind") == "bridge"
            xs, ys = ring[0::2], ring[1::2]
            j0 = max(0, int(math.floor(min(ys) - miny)) - 1)
            j1 = min(ny - 1, int(math.ceil(max(ys) - miny)) + 1)
            i0 = max(0, int(math.floor(min(xs) - minx)) - 1)
            i1 = min(nx - 1, int(math.ceil(max(xs) - minx)) + 1)
            for j in range(j0, j1 + 1):
                y = miny + j
                spans = _spans(ring, y)
                if not spans:
                    continue
                hspans = []
                for h in holes:
                    if len(h) >= 6:
                        hspans.extend(_spans(h, y))
                row = j * nx
                for s, e in spans:
                    ia = max(i0, int(math.ceil(s - minx)))
                    ib = min(i1, int(math.floor(e - minx)))
                    for i in range(ia, ib + 1):
                        x = minx + i
                        if hspans and any(hs <= x <= he for hs, he in hspans):
                            continue
                        k = row + i
                        if base <= g[k] + 1.5:
                            if high > top[k]:
                                top[k] = high
                        else:
                            b = ohb[k]
                            if math.isnan(b) or base < b:
                                ohb[k] = base
                            tt = oht[k]
                            if math.isnan(tt) or high > tt:
                                oht[k] = high
                            if is_bridge and high - g[k] < 6.5 and high > self.walk[k]:
                                self.walk[k] = high

    def _finalize_columns(self):
        n = self.nx * self.ny
        g, top, walk, obst, ohb = self.g, self.top, self.walk, self.obst, self.ohb
        su = self.step_up
        mh_pad = self.height + 1.5
        isnan = math.isnan
        for k in range(n):
            tk = top[k]
            gk = g[k]
            if tk > walk[k]:
                walk[k] = tk
            low = False
            b = ohb[k]
            if not isnan(b) and b - tk < mh_pad and walk[k] <= tk:
                low = True
            if tk - gk > su or low:
                obst[k] = 1

    def _build_block_max(self):
        nx, ny = self.nx, self.ny
        bnx = (nx + 7) // 8
        bny = (ny + 7) // 8
        self.bnx, self.bny = bnx, bny
        bm = array("f", [-1e9]) * (bnx * bny)
        top, oht = self.top, self.oht
        isnan = math.isnan
        for j in range(ny):
            bj_row = (j >> 3) * bnx
            row = j * nx
            for i in range(nx):
                k = row + i
                h = top[k]
                ot = oht[k]
                if not isnan(ot) and ot > h:
                    h = ot
                bi = bj_row + (i >> 3)
                if h > bm[bi]:
                    bm[bi] = h
        self.bmax = bm

    def _build_nav2(self):
        ns = 3.0
        self.n2s = ns
        n2x = int((self.maxx - self.minx) / ns) + 1
        n2y = int((self.maxy - self.miny) / ns) + 1
        self.n2x, self.n2y = n2x, n2y
        n2 = n2x * n2y
        blk = bytearray(n2)
        surf = array("f", [0.0]) * n2
        obst = self.obst
        walk = self.walk
        nx, ny = self.nx, self.ny
        minx, miny = self.minx, self.miny
        pad = int(math.ceil(self.radius + 0.2))
        # Fast sample offsets inside mech radius
        offs = []
        r2 = (self.radius + 0.1) ** 2
        for dy in range(-pad, pad + 1):
            for dx in range(-pad, pad + 1):
                if dx * dx + dy * dy <= r2:
                    offs.append((dx, dy))
        for j in range(n2y):
            cy = int(round((j + 0.5) * ns))
            row2 = j * n2x
            for i in range(n2x):
                cx = int(round((i + 0.5) * ns))
                c = row2 + i
                if cx < pad or cy < pad or cx >= nx - pad or cy >= ny - pad:
                    blk[c] = 1
                    continue
                base_k = cy * nx + cx
                surf[c] = walk[base_k]
                if obst[base_k]:
                    blk[c] = 1
                    continue
                hit = 0
                for dx, dy in offs:
                    if obst[(cy + dy) * nx + (cx + dx)]:
                        hit = 1
                        break
                blk[c] = hit
        self.n2_blk = blk
        self.n2_surf = surf

        # Wall clearance BFS (0..8 cells)
        clr = bytearray([255]) * n2
        q = deque()
        for c in range(n2):
            if blk[c]:
                clr[c] = 0
                q.append(c)
        while q:
            c = q.popleft()
            d = clr[c]
            if d >= 8:
                continue
            nd = d + 1
            ci = c % n2x
            cj = c // n2x
            if ci > 0 and clr[c - 1] == 255:
                clr[c - 1] = nd; q.append(c - 1)
            if ci + 1 < n2x and clr[c + 1] == 255:
                clr[c + 1] = nd; q.append(c + 1)
            if cj > 0 and clr[c - n2x] == 255:
                clr[c - n2x] = nd; q.append(c - n2x)
            if cj + 1 < n2y and clr[c + n2x] == 255:
                clr[c + n2x] = nd; q.append(c + n2x)
        self.n2_clr = clr

        # Connected components (8-connected, matching symmetric step-up / slope walkability)
        comp = array("i", [-1]) * n2
        climb_card = max(self.step_up, ns * self.max_slope * 0.92) + 0.35
        climb_diag = max(self.step_up, ns * 1.4142 * self.max_slope * 0.92) + 0.35
        self._n2_climb_c = climb_card
        self._n2_climb_d = climb_diag
        best_comp = 0
        best_sz = 0
        cid = 0
        nbr8 = (
            (1, 0, False), (-1, 0, False), (0, 1, False), (0, -1, False),
            (1, 1, True), (1, -1, True), (-1, 1, True), (-1, -1, True),
        )
        for s in range(n2):
            if blk[s] or comp[s] >= 0:
                continue
            comp[s] = cid
            q = deque([s])
            sz = 0
            while q:
                c = q.popleft()
                sz += 1
                ci = c % n2x
                cj = c // n2x
                sc = surf[c]
                row_c = cj * n2x
                for di, dj, diag in nbr8:
                    ni, nj = ci + di, cj + dj
                    if ni < 0 or nj < 0 or ni >= n2x or nj >= n2y:
                        continue
                    nb = nj * n2x + ni
                    if blk[nb] or comp[nb] >= 0:
                        continue
                    if diag and (blk[row_c + ni] or blk[nj * n2x + ci]):
                        continue
                    lim = climb_diag if diag else climb_card
                    if abs(surf[nb] - sc) <= lim:
                        comp[nb] = cid
                        q.append(nb)
            if sz > best_sz:
                best_sz = sz
                best_comp = cid
            cid += 1
        self.n2_comp = comp
        self.main_comp = best_comp

        # Precompute nearest main-component cell (up to 14 cells = 42m) for courtyard escape
        near = array("i", [-1]) * n2
        depth = bytearray(n2)
        q = deque()
        for c in range(n2):
            if not blk[c] and comp[c] == best_comp:
                near[c] = c
                q.append(c)
        while q:
            c = q.popleft()
            d = depth[c]
            if d >= 14:
                continue
            nd = d + 1
            ci = c % n2x
            cj = c // n2x
            src = near[c]
            if ci > 0 and near[c - 1] < 0:
                near[c - 1] = src; depth[c - 1] = nd; q.append(c - 1)
            if ci + 1 < n2x and near[c + 1] < 0:
                near[c + 1] = src; depth[c + 1] = nd; q.append(c + 1)
            if cj > 0 and near[c - n2x] < 0:
                near[c - n2x] = src; depth[c - n2x] = nd; q.append(c - n2x)
            if cj + 1 < n2y and near[c + n2x] < 0:
                near[c + n2x] = src; depth[c + n2x] = nd; q.append(c + n2x)
        self.main_near = near

        # Reusable A* / BFS scratch arrays (zero per-tick allocation)
        self._n2_stamp = array("I", [0]) * n2
        self._n2_closed = array("I", [0]) * n2
        self._n2_g = array("f", [0.0]) * n2
        self._n2_came = array("i", [-1]) * n2
        self._n2_gen = 0

    def _build_trees(self, trees):
        self.trees = []
        self.tree_hash = {}
        self.tree_bucket = 24.0
        if not trees:
            return
        fields = trees["fields"]
        data = trees["data"]
        nf = len(fields)
        fi = {name: k for k, name in enumerate(fields)}
        bucket = self.tree_bucket
        for k in range(0, len(data) - nf + 1, nf):
            row = data[k:k + nf]
            x = float(row[fi["x"]])
            y = float(row[fi["y"]])
            z = float(row[fi.get("z", 0)])
            h = float(row[fi["height"]])
            cr = float(row[fi["crownR"]])
            cb = float(row[fi["crownBase"]])
            tr = float(row[fi["trunkR"]])
            cx = float(row[fi["crownX"]]) if "crownX" in fi else x
            cy = float(row[fi["crownY"]]) if "crownY" in fi else y
            top = z + h
            rec = (cx, cy, max(z, cb), top, cr, tr, x, y)
            self.trees.append(rec)
            self.tree_hash.setdefault((int(x // bucket), int(y // bucket)), []).append(rec)

    def _build_nav(self):
        c = self.nav_cell
        for j in range(self.nny):
            y = self.miny + j * c
            row = j * self.nnx
            for i in range(self.nnx):
                x = self.minx + i * c
                z = self.ground(x, y)
                self.nav_z[row + i] = z
                blk = self.blocked(x, y, z)
                if not blk:
                    d = self.ground(x + c, y) - z
                    d2 = self.ground(x, y + c) - z
                    if max(abs(d), abs(d2)) / c > self.max_slope:
                        blk = True
                if x < self.minx + 4 or x > self.maxx - 4 or y < self.miny + 4 or y > self.maxy - 4:
                    blk = True
                self.nav_blocked[row + i] = 1 if blk else 0

    # ------------------------------------------------------------------ queries
    def idx(self, x, y):
        i = int(round(x - self.minx))
        j = int(round(y - self.miny))
        if i < 0:
            i = 0
        elif i >= self.nx:
            i = self.nx - 1
        if j < 0:
            j = 0
        elif j >= self.ny:
            j = self.ny - 1
        return j * self.nx + i

    def in_bounds(self, x, y):
        i = int(round(x - self.minx))
        j = int(round(y - self.miny))
        return 1 <= i < self.nx - 1 and 1 <= j < self.ny - 1

    def ground(self, x, y):
        """Terrain height of the 1 m column under (x, y)."""
        return self.g[self.idx(x, y)]

    def surface(self, x, y, z, step_up=None):
        """Highest walkable surface at (x,y) at or below z + step_up."""
        step_up = self.step_up if step_up is None else step_up
        k = self.idx(x, y)
        s = self.g[k]
        if self.top[k] <= z + step_up and self.top[k] > s:
            s = self.top[k]
        return s

    def intervals(self, x, y):
        """Compatibility helper: solid intervals at the column under (x,y)."""
        k = self.idx(x, y)
        out = []
        if self.top[k] > self.g[k]:
            out.append((self.g[k], self.top[k]))
        if not math.isnan(self.ohb[k]):
            out.append((self.ohb[k], self.oht[k]))
        return out or None

    def _solid_cell(self, x, y, z, h, step_up):
        if not self.in_bounds(x, y):
            return True
        k = self.idx(x, y)
        if self.top[k] > z + step_up:
            return True
        b = self.ohb[k]
        if b < z + h and self.oht[k] > z + step_up:
            return True
        return False

    def _ring(self, x, y, z, h, radius, step_up):
        """Engine-style collision: centre + eight points on the mech's radius."""
        r = radius * 0.9
        if self._solid_cell(x, y, z, h, step_up):
            return False
        for a in range(8):
            ang = a * TAU / 8.0
            if self._solid_cell(x + math.cos(ang) * r, y + math.sin(ang) * r,
                                z, h, step_up):
                return False
        return True

    def blocked(self, x, y, z, h=None, step_up=None, radius=None):
        """True when a mech with feet at z cannot stand at (x,y)."""
        h = self.height if h is None else h
        step_up = self.step_up if step_up is None else step_up
        radius = self.radius if radius is None else radius
        return not self._ring(x, y, z, h, radius, step_up)

    def walk_clear(self, x0, y0, x1, y1, z, h=None, radius=None, step_up=None):
        """True when the straight segment is body-clear at the current height."""
        h = self.height if h is None else h
        step_up = self.step_up if step_up is None else step_up
        radius = self.radius if radius is None else radius
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d < 0.01:
            return self._ring(x1, y1, z, h, radius, step_up)
        n = max(1, min(20, int(d / 1.25) + 1))
        for k in range(1, n + 1):
            f = k / n
            if not self._ring(x0 + dx * f, y0 + dy * f, z, h, radius, step_up):
                return False
        return True

    def solid(self, x, y, z):
        """Point-in-solid test used for projectile / laser lines."""
        k = self.idx(x, y)
        if z < self.top[k]:
            return True
        b = self.ohb[k]
        return (b <= z <= self.oht[k]) if not math.isnan(b) else False

    def shot_clear(self, a, b, step=None):
        """Line of sight for projectiles/lasers: terrain + prisms, trees ignored."""
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        dist = math.hypot(dx, dy)
        if dist < 0.01:
            return True
        st = step or 1.0
        n = max(2, min(240, int(dist / st) + 1))
        for k in range(1, n):
            f = k / n
            if self.solid(a[0] + dx * f, a[1] + dy * f, a[2] + dz * f):
                return False
        return True

    def vision_clear(self, a, b):
        """Approximate visual LOS including tree canopy and trunks."""
        if not self.shot_clear(a, b):
            return False
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        dist = math.hypot(dx, dy)
        n = max(2, min(80, int(dist / 4.0) + 1))
        density = 0.0
        seen = set()
        bk = self.tree_bucket
        for k in range(1, n):
            f = k / n
            x, y, z = a[0] + dx * f, a[1] + dy * f, a[2] + dz * f
            key = (int(x // bk), int(y // bk))
            for gi in (key, (key[0] + 1, key[1]), (key[0] - 1, key[1]),
                       (key[0], key[1] + 1), (key[0], key[1] - 1)):
                for rec in self.tree_hash.get(gi, ()):
                    rid = id(rec)
                    if rid in seen:
                        continue
                    seen.add(rid)
                    cx, cy, cb, top, cr, tr, tx, ty = rec
                    if cb <= z <= top:
                        d = math.hypot(x - cx, y - cy)
                        if d < cr:
                            density += self.canopy_density * (1.0 - d / cr)
                    if z < cb and math.hypot(x - tx, y - ty) < tr:
                        return False
            if density > self.canopy_block_t:
                return False
        return True

    def cover_score(self, x, y, z):
        """0..1: how much solid geometry is nearby (good for hiding)."""
        score = 0.0
        for ang in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
            px, py = x + math.cos(ang) * 6.0, y + math.sin(ang) * 6.0
            if self.blocked(px, py, z):
                score += 0.25
        return score

    # ------------------------------------------------------------------ fast tactical queries (v2)
    def walk_at(self, x, y):
        return self.walk[self.idx(x, y)]

    def top_at(self, x, y):
        return self.top[self.idx(x, y)]

    def cell2(self, x, y):
        i = int((x - self.minx) / self.n2s)
        j = int((y - self.miny) / self.n2s)
        if i < 0:
            i = 0
        elif i >= self.n2x:
            i = self.n2x - 1
        if j < 0:
            j = 0
        elif j >= self.n2y:
            j = self.n2y - 1
        return j * self.n2x + i

    def cell2_pos(self, c):
        return (
            self.minx + (c % self.n2x + 0.5) * self.n2s,
            self.miny + (c // self.n2x + 0.5) * self.n2s,
        )

    def nearest_free2(self, c):
        blk = self.n2_blk
        if not blk[c]:
            return c
        n2x, n2y = self.n2x, self.n2y
        ci, cj = c % n2x, c // n2x
        for r in range(1, 14):
            i0 = max(0, ci - r)
            i1 = min(n2x - 1, ci + r)
            j0 = max(0, cj - r)
            j1 = min(n2y - 1, cj + r)
            for j in range(j0, j1 + 1):
                row = j * n2x
                if j == j0 or j == j1:
                    for i in range(i0, i1 + 1):
                        if not blk[row + i]:
                            return row + i
                else:
                    if not blk[row + i0]:
                        return row + i0
                    if not blk[row + i1]:
                        return row + i1
        return -1

    def free2(self, x, y):
        if not self.in_bounds(x, y):
            return False
        return not self.n2_blk[self.cell2(x, y)]

    def reachable2(self, x, y):
        if not self.in_bounds(x, y):
            return False
        c = self.cell2(x, y)
        return (not self.n2_blk[c]) and (self.n2_comp[c] == self.main_comp)

    def off_main(self, x, y):
        c = self.nearest_free2(self.cell2(x, y))
        return c >= 0 and self.n2_comp[c] != self.main_comp

    def line_walkable2(self, x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d < 0.2:
            return self.free2(x1, y1)
        n = int(d * 0.65) + 1
        inv_n = 1.0 / n
        minx, miny, inv_s = self.minx, self.miny, 1.0 / self.n2s
        n2x, n2y = self.n2x, self.n2y
        blk = self.n2_blk
        surf = self.n2_surf
        pi = int((x0 - minx) * inv_s)
        pj = int((y0 - miny) * inv_s)
        if pi < 0: pi = 0
        elif pi >= n2x: pi = n2x - 1
        if pj < 0: pj = 0
        elif pj >= n2y: pj = n2y - 1
        prev = pj * n2x + pi
        prev_s = surf[prev]
        for k in range(1, n + 1):
            t = k * inv_n
            i = int((x0 + dx * t - minx) * inv_s)
            j = int((y0 + dy * t - miny) * inv_s)
            if i < 0 or j < 0 or i >= n2x or j >= n2y:
                return False
            c = j * n2x + i
            if c == prev:
                continue
            if blk[c]:
                return False
            cs = surf[c]
            if cs - prev_s > 3.2:
                return False
            prev = c
            prev_s = cs
        return True

    def clear(self, ax, ay, az, bx, by, bz, fine=False):
        """Fast 8x8 block-skipping 3D LOS check against terrain + prisms + overhangs."""
        dx = bx - ax
        dy = by - ay
        dz = bz - az
        hl = math.hypot(dx, dy)
        if hl < 0.5:
            return True
        minx, miny = self.minx, self.miny
        nx, ny = self.nx, self.ny
        bnx, bny = self.bnx, self.bny
        bmax = self.bmax
        top = self.top
        ohb = self.ohb
        oht = self.oht
        isnan = math.isnan
        step_m = 1.0 if fine else 1.5
        dt = step_m / hl
        t = dt
        inv_dx = (1.0 / dx) if abs(dx) > 1e-9 else 0.0
        inv_dy = (1.0 / dy) if abs(dy) > 1e-9 else 0.0
        while t < 0.995:
            px = ax + dx * t
            py = ay + dy * t
            pz = az + dz * t
            ix = int(px - minx + 0.5)
            iy = int(py - miny + 0.5)
            if ix < 0 or iy < 0 or ix >= nx or iy >= ny:
                t += dt
                continue
            bi = ix >> 3
            bj = iy >> 3
            # Fast 8m block skip when ray stays above the entire 8x8 block max
            if bi < bnx and bj < bny:
                bm = bmax[bj * bnx + bi]
                if pz > bm:
                    # Compute exit t from this 8x8 block
                    t_exit = 1.0
                    if inv_dx > 0.0:
                        ex = minx + (bi + 1) * 8.0
                        tx = (ex - ax) * inv_dx
                        if tx < t_exit:
                            t_exit = tx
                    elif inv_dx < 0.0:
                        ex = minx + bi * 8.0
                        tx = (ex - ax) * inv_dx
                        if tx < t_exit:
                            t_exit = tx
                    if inv_dy > 0.0:
                        ey = miny + (bj + 1) * 8.0
                        ty = (ey - ay) * inv_dy
                        if ty < t_exit:
                            t_exit = ty
                    elif inv_dy < 0.0:
                        ey = miny + bj * 8.0
                        ty = (ey - ay) * inv_dy
                        if ty < t_exit:
                            t_exit = ty
                    if t_exit > t and (az + dz * t_exit) > bm:
                        t = t_exit + 1e-4
                        continue
            k = iy * nx + ix
            if pz < top[k]:
                return False
            ob = ohb[k]
            if not isnan(ob) and ob <= pz <= oht[k]:
                return False
            t += dt
        return True

    def path2(self, sx, sy, gx, gy, max_expand=4500, budget_s=0.010):
        """Fast generation-stamped A* on the 3m nav grid with wall-clock ceiling."""
        s = self.nearest_free2(self.cell2(sx, sy))
        g = self.nearest_free2(self.cell2(gx, gy))
        if s < 0 or g < 0:
            return [], False
        if s == g:
            return [s], True
        self._n2_gen += 1
        gen = self._n2_gen
        stamp = self._n2_stamp
        closed = self._n2_closed
        gscore = self._n2_g
        came = self._n2_came
        blk = self.n2_blk
        surf = self.n2_surf
        clr = self.n2_clr
        n2x, n2y = self.n2x, self.n2y
        ns = self.n2s
        climb_c = self._n2_climb_c
        climb_d = self._n2_climb_d
        gi, gj = g % n2x, g // n2x
        h_scale = ns * 1.15

        def h_fn(ci, cj):
            adx = abs(ci - gi)
            ady = abs(cj - gj)
            return (max(adx, ady) + 0.4142 * min(adx, ady)) * h_scale

        si, sj = s % n2x, s // n2x
        hs = h_fn(si, sj)
        gscore[s] = 0.0
        came[s] = -1
        stamp[s] = gen
        heap = [(hs, s)]
        best = s
        best_h = hs
        found = False
        t0 = time.perf_counter()
        heappop = heapq.heappop
        heappush = heapq.heappush
        nbrs = (
            (1, 0, ns, False), (-1, 0, ns, False),
            (0, 1, ns, False), (0, -1, ns, False),
            (1, 1, ns * 1.4142, True), (1, -1, ns * 1.4142, True),
            (-1, 1, ns * 1.4142, True), (-1, -1, ns * 1.4142, True),
        )
        for n in range(max_expand):
            if not heap:
                break
            if (n & 127) == 127 and (time.perf_counter() - t0) > budget_s:
                break
            _, c = heappop(heap)
            if closed[c] == gen:
                continue
            closed[c] = gen
            if c == g:
                best = c
                found = True
                break
            ci, cj = c % n2x, c // n2x
            hc = h_fn(ci, cj)
            if hc < best_h:
                best_h = hc
                best = c
            gc = gscore[c]
            sc = surf[c]
            row_c = cj * n2x
            for di, dj, step_cost, diag in nbrs:
                ni, nj = ci + di, cj + dj
                if ni < 0 or nj < 0 or ni >= n2x or nj >= n2y:
                    continue
                nb = nj * n2x + ni
                if closed[nb] == gen or blk[nb]:
                    continue
                if diag and (blk[row_c + ni] or blk[nj * n2x + ci]):
                    continue
                rise = surf[nb] - sc
                if rise > (climb_d if diag else climb_c):
                    continue
                cl = clr[nb]
                cost = step_cost * (1.0 + (3 - cl) * 0.16) if cl < 3 else step_cost
                ng = gc + cost
                if stamp[nb] != gen or ng < gscore[nb]:
                    gscore[nb] = ng
                    came[nb] = c
                    stamp[nb] = gen
                    heappush(heap, (ng + h_fn(ni, nj), nb))
        path = []
        c = best
        while c >= 0:
            path.append(c)
            if c == s:
                break
            c = came[c]
        path.reverse()
        return path, found

    def escape_plan(self, x, y):
        """Find nearest launch cell in current isolated courtyard to jump onto main_comp."""
        s = self.nearest_free2(self.cell2(x, y))
        if s < 0:
            return None, None, False
        self._n2_gen += 1
        gen = self._n2_gen
        stamp = self._n2_stamp
        gscore = self._n2_g
        blk = self.n2_blk
        surf = self.n2_surf
        near = self.main_near
        n2x, n2y = self.n2x, self.n2y
        ns = self.n2s
        climb_c = self._n2_climb_c
        stamp[s] = gen
        gscore[s] = 0.0
        q = deque([s])
        best = -1
        best_sc = 1e18
        pops = 0
        while q and pops < 6000:
            c = q.popleft()
            pops += 1
            m = near[c]
            if m >= 0:
                cx, cy = self.cell2_pos(c)
                mx, my = self.cell2_pos(m)
                sc = gscore[c] * ns + 4.0 * math.hypot(mx - cx, my - cy)
                if sc < best_sc:
                    best_sc = sc
                    best = c
            ci, cj = c % n2x, c // n2x
            sc_z = surf[c]
            ng = gscore[c] + 1.0
            for nb in (
                c - 1 if ci > 0 else -1,
                c + 1 if ci + 1 < n2x else -1,
                c - n2x if cj > 0 else -1,
                c + n2x if cj + 1 < n2y else -1,
            ):
                if nb >= 0 and stamp[nb] != gen and not blk[nb] and surf[nb] - sc_z <= climb_c:
                    stamp[nb] = gen
                    gscore[nb] = ng
                    q.append(nb)
        if best < 0:
            return None, None, False
        lx, ly = self.cell2_pos(best)
        mx, my = self.cell2_pos(near[best])
        d = math.hypot(mx - lx, my - ly)
        if d > 0.1:
            ex, ey = mx + (mx - lx) / d * 5.0, my + (my - ly) / d * 5.0
            if self.reachable2(ex, ey):
                mx, my = ex, ey
        return (lx, ly), (mx, my), True

    def exposure(self, x, y):
        """0..1: open-sky sightline exposure at (x, y) using 12 fast rays."""
        z = self.walk_at(x, y) + self.muzzle_height
        minx, miny, nx, ny = self.minx, self.miny, self.nx, self.ny
        top = self.top
        ohb = self.ohb
        oht = self.oht
        isnan = math.isnan
        total = 0.0
        for k in range(12):
            a = k * (TAU / 12.0)
            ca, sa = math.cos(a), math.sin(a)
            d = 4.0
            while d < 180.0:
                ix = int(x + ca * d - minx + 0.5)
                iy = int(y + sa * d - miny + 0.5)
                if ix < 0 or iy < 0 or ix >= nx or iy >= ny:
                    break
                idx = iy * nx + ix
                if z < top[idx]:
                    break
                ob = ohb[idx]
                if not isnan(ob) and ob <= z <= oht[idx]:
                    break
                d += 4.5
            total += d
        return total / (12.0 * 180.0)


class NullWorld:
    """Permissive stand-in when the arena files cannot be read.

    A crashed mech is scored as a sitting target, so the bot must always keep
    playing even if /arena is missing.  Without a map it loses LOS/navigation
    but keeps zone logic, facing, firing and economy working.
    """

    def __init__(self, cfg=None):
        cfg = cfg or {}
        mech = cfg.get("mech", {}) or {}
        cubes = cfg.get("cubes", {}) or {}
        self.ready = False
        self.minx, self.miny = -600.0, -600.0
        self.maxx, self.maxy = 600.0, 600.0
        self.nav_cell = 8.0
        self.radius = float(mech.get("radius", 2.5))
        self.height = float(mech.get("height", 9.0))
        self.step_up = float(mech.get("step_up", 1.2))
        self.eye_height = float(mech.get("eye_height", 8.0))
        self.muzzle_height = float(mech.get("muzzle_height", 7.0))
        self.front_arc_deg = float(mech.get("front_arc_deg", 180.0))
        self.rear_mult = float(mech.get("rear_mult", 1.5))
        self.size_per_cube = float(cubes.get("size_per_cube", 0.05))
        self.canopy_density = 0.35
        self.canopy_block_t = 0.25
        self.max_slope = 1.19
        self.nx = self.ny = self.nnx = self.nny = 0
        self.nav_blocked = bytearray(0)
        self.nav_z = []
        self.trees = []
        self.tree_hash = {}
        self.tree_bucket = 24.0

    def ground(self, x, y):
        return 0.0

    def surface(self, x, y, z, step_up=None):
        return 0.0

    def idx(self, x, y):
        return 0

    def in_bounds(self, x, y):
        return True

    def intervals(self, x, y):
        return None

    def blocked(self, x, y, z, h=None, step_up=None, radius=None):
        return False

    def _ring(self, x, y, z, h, radius, step_up):
        return True

    def shot_clear(self, a, b, step=None):
        return True

    def solid(self, x, y, z):
        return False

    def vision_clear(self, a, b):
        return True

    def cover_score(self, x, y, z):
        return 0.0

    def walk_clear(self, x0, y0, x1, y1, z, h=None, radius=None, step_up=None):
        return True

    def walk_at(self, x, y):
        return 0.0

    def top_at(self, x, y):
        return 0.0

    def cell2(self, x, y):
        return 0

    def cell2_pos(self, c):
        return (0.0, 0.0)

    def nearest_free2(self, c):
        return 0

    def free2(self, x, y):
        return True

    def reachable2(self, x, y):
        return True

    def off_main(self, x, y):
        return False

    def line_walkable2(self, x0, y0, x1, y1):
        return True

    def clear(self, ax, ay, az, bx, by, bz, fine=False):
        return True

    def path2(self, sx, sy, gx, gy, max_expand=4500, budget_s=0.010):
        return [], False

    def escape_plan(self, x, y):
        return None, None, False

    def exposure(self, x, y):
        return 0.5
