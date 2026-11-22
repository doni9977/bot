"""Bounded A* on a coarse grid, plus local steering and wall sliding."""
from __future__ import annotations

import heapq
import math
import time

SQ2 = math.sqrt(2.0)
DIRS = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
        (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2))


class Planner:
    def __init__(self, world):
        self.w = world
        self.ok = bool(getattr(world, "ready", False))
        self.nx, self.ny = world.nnx, world.nny
        self.c = world.nav_cell
        self.minx, self.miny = world.minx, world.miny
        self.blocked = world.nav_blocked
        self.radius = float(getattr(world, "radius", 2.5))
        self.height = float(getattr(world, "height", 9.0))
        self.step_up = float(getattr(world, "step_up", 1.2))

    def cell(self, x, y):
        i = int((x - self.minx) / self.c)
        j = int((y - self.miny) / self.c)
        return max(0, min(self.nx - 1, i)), max(0, min(self.ny - 1, j))

    def world(self, i, j):
        return (self.minx + (i + 0.5) * self.c, self.miny + (j + 0.5) * self.c)

    def nearest_free(self, i, j):
        if not self.blocked[j * self.nx + i]:
            return i, j
        for r in range(1, 9):
            for di in range(-r, r + 1):
                for dj in (-r, r):
                    a, b = i + di, j + dj
                    if 0 <= a < self.nx and 0 <= b < self.ny and not self.blocked[b * self.nx + a]:
                        return a, b
                for dj in range(-r + 1, r):
                    a, b = i - r, j + dj
                    if 0 <= a < self.nx and 0 <= b < self.ny and not self.blocked[b * self.nx + a]:
                        return a, b
                    a, b = i + r, j + dj
                    if 0 <= a < self.nx and 0 <= b < self.ny and not self.blocked[b * self.nx + a]:
                        return a, b
        return i, j

    def path(self, sx, sy, gx, gy, budget=3500, time_budget=0.006):
        """Return a list of world waypoints, or [] if unreachable within budget.

        A hard wall-clock guard keeps this inside one decision's 50 ms budget even
        on a slow 1-CPU match container.
        """
        if not self.ok:
            return []
        deadline = time.perf_counter() + time_budget
        si, sj = self.nearest_free(*self.cell(sx, sy))
        gi, gj = self.nearest_free(*self.cell(gx, gy))
        start = sj * self.nx + si
        goal = gj * self.nx + gi
        if start == goal:
            return [(gx, gy)]
        nx, blk = self.nx, self.blocked
        h = lambda idx: math.hypot(idx % nx - gi, idx // nx - gj) * self.c
        openq = [(h(start), 0.0, start)]
        came = {}
        gscore = {start: 0.0}
        closed = set()
        expanded = 0
        while openq and expanded < budget:
            if expanded % 64 == 0 and time.perf_counter() > deadline:
                break
            f, g, cur = heapq.heappop(openq)
            if cur in closed:
                continue
            closed.add(cur)
            expanded += 1
            if cur == goal:
                out = []
                while cur in came:
                    out.append(self.world(cur % nx, cur // nx))
                    cur = came[cur]
                out.reverse()
                out.append((gx, gy))
                return out
            ci, cj = cur % nx, cur // nx
            for di, dj, cost in DIRS:
                ni, nj = ci + di, cj + dj
                if ni < 0 or ni >= nx or nj < 0 or nj >= self.ny:
                    continue
                nxt = nj * nx + ni
                if blk[nxt] or nxt in closed:
                    continue
                if di and dj:
                    if blk[cj * nx + ni] or blk[nj * nx + ci]:
                        continue
                # small penalty for cells adjacent to walls -> keep clear of corners
                pen = 0.0
                if ni > 0 and blk[nj * nx + ni - 1]:
                    pen += 0.35
                if ni < nx - 1 and blk[nj * nx + ni + 1]:
                    pen += 0.35
                if nj > 0 and blk[(nj - 1) * nx + ni]:
                    pen += 0.35
                if nj < self.ny - 1 and blk[(nj + 1) * nx + ni]:
                    pen += 0.35
                ng = g + cost * self.c + pen
                if ng < gscore.get(nxt, 1e30):
                    gscore[nxt] = ng
                    came[nxt] = cur
                    heapq.heappush(openq, (ng + h(nxt), ng, nxt))
        return []

    def reach(self, x, y, z, ux, uy, radius=None):
        """How far (m) a body can travel from (x,y) along a unit heading."""
        radius = self.radius if radius is None else radius
        out = 0.0
        px, py = x, y
        for d in (2.0, 4.0, 6.0, 9.0, 13.0):
            qx, qy = x + ux * d, y + uy * d
            if not self.w.walk_clear(px, py, qx, qy, z, radius=radius):
                break
            out, px, py = d, qx, qy
        return out

    def steer(self, x, y, gx, gy, z, path=None, radius=None):
        """Return a unit (dx,dy) direction toward the goal that avoids walls."""
        radius = self.radius if radius is None else radius
        dx, dy = gx - x, gy - y
        d = math.hypot(dx, dy)
        if d < 0.5:
            return (0.0, 0.0)
        ux, uy = dx / d, dy / d
        look = min(18.0, max(6.0, d))
        if self.w.walk_clear(x, y, x + ux * look, y + uy * look, z, radius=radius):
            return (ux, uy)
        # follow an A* waypoint if we have one (advance from closest point along
        # path so we never bounce backwards to an already-passed path[0]!)
        if path:
            ci = min(range(len(path)), key=lambda i: math.hypot(path[i][0] - x, path[i][1] - y))
            # Pick the furthest visible waypoint slightly ahead, else next waypoint
            chosen = None
            hi = min(len(path) - 1, ci + 4)
            for idx in range(hi, ci, -1):
                wx, wy = path[idx]
                vx, vy = wx - x, wy - y
                vd = math.hypot(vx, vy)
                if vd > 2.5 and self.w.walk_clear(x, y, x + vx / vd * min(look, vd),
                                                  y + vy / vd * min(look, vd), z, radius=radius):
                    chosen = (vx / vd, vy / vd)
                    break
            if chosen is not None:
                return chosen
            nxt = min(len(path) - 1, ci + 1)
            wx, wy = path[nxt]
            vx, vy = wx - x, wy - y
            vd = math.hypot(vx, vy)
            if vd > 0.5:
                ux, uy = vx / vd, vy / vd
        # heading fan: prefer the closest heading that is genuinely walkable
        best = None
        best_score = -1e18
        base = math.atan2(uy, ux)
        for da in (0.0, 0.3, -0.3, 0.6, -0.6, 0.9, -0.9, 1.2, -1.2,
                   1.6, -1.6, 2.0, -2.0, 2.5, -2.5, math.pi):
            a = base + da
            cx, cy = math.cos(a), math.sin(a)
            clear = self.reach(x, y, z, cx, cy, radius=radius)
            if clear < 2.0:
                continue
            score = math.cos(da) * 3.0 - 0.05 * abs(da) + 0.12 * clear
            if score > best_score:
                best_score = score
                best = (cx, cy)
            if da == 0.0 and clear >= 9.0:
                return (ux, uy)
        return best or (ux, uy)


def safe_heading(world, x, y, z, mx, my, radius=None, min_reach=8.0):
    """Rotate a composed movement vector to the nearest body-clear heading.

    Dodge / NPC-repulsion / strafe contributions can point a perfectly good
    steering direction straight into a wall.  Always re-validate the *final*
    vector.  Returns ((dx,dy), reach).
    """
    radius = float(getattr(world, "radius", 2.5)) if radius is None else radius
    m = math.hypot(mx, my)
    if m < 1e-6:
        return (0.0, 0.0), 0.0
    ux, uy = mx / m, my / m
    if world.walk_clear(x, y, x + ux * min_reach, y + uy * min_reach, z, radius=radius):
        return (ux, uy), min_reach
    base = math.atan2(uy, ux)
    best, best_reach = (ux, uy), 0.0
    for da in (0.2, -0.2, 0.4, -0.4, 0.65, -0.65, 0.9, -0.9, 1.2, -1.2,
               1.5, -1.5, 1.85, -1.85, 2.2, -2.2, 2.6, -2.6, math.pi):
        a = base + da
        cx, cy = math.cos(a), math.sin(a)
        clear = 0.0
        px, py = x, y
        for d in (2.0, 4.0, 6.0, 9.0, 13.0):
            qx, qy = x + cx * d, y + cy * d
            if not world.walk_clear(px, py, qx, qy, z, radius=radius):
                break
            clear, px, py = d, qx, qy
        if clear >= min_reach:
            return (cx, cy), clear
        if clear > best_reach:
            best_reach, best = clear, (cx, cy)
    return best, best_reach
