"""Local line-of-sight breaking.

The practice squad shares vision across 15 mechs, so "hiding" by distance does
not work: one of them always sees us.  What does work is breaking every known
line of sight to our body.  The squad forgets us after vision.memory_s (5 s),
stops shooting, and mech regen (45 HP/s after a 5 s calm window) kicks in.

Find the nearest reachable spot whose torso/head are occluded from the closest
threats, preferring to move away from them.  Results are cached by the caller.
"""
from __future__ import annotations

import math

TAU = math.tau


def find_cover(world, x, y, z, threat_eyes, max_r=18.0, step=2.0,
               zone_center=None, zone_radius=0.0):
    """Return (px, py) or None.

    `threat_eyes` is a short list of (x, y, z) eye positions, nearest first.
    `step` keeps LOS sampling cheap enough for the 50 ms decision budget.
    """
    if not threat_eyes:
        return None
    eyes = threat_eyes[:3]
    best = None
    for r in (4.0, 8.0, 13.0, 18.0):
        if r > max_r:
            break
        best_at_r = None
        best_score = -1e18
        for k in range(12):
            a = k * TAU / 12.0
            cx, cy = math.cos(a), math.sin(a)
            px, py = x + cx * r, y + cy * r
            pz = world.ground(px, py)
            if pz > z + world.step_up or pz < z - 6.0:
                continue
            if zone_center is not None and zone_radius > 0:
                if math.hypot(px - zone_center[0], py - zone_center[1]) > zone_radius * 0.92:
                    continue
            if not world.walk_clear(x, y, px, py, z):
                continue
            hidden = True
            body_z = pz + 0.5 * world.height
            eye_z = pz + world.eye_height
            for ex, ey, ez in eyes:
                if (world.shot_clear((ex, ey, ez), (px, py, body_z), step=step)
                        or world.shot_clear((ex, ey, ez), (px, py, eye_z), step=step)):
                    hidden = False
                    break
            if not hidden:
                continue
            # stay far from the shooters, close to where we already are
            away = min(math.hypot(px - ex, py - ey) for ex, ey, _ in eyes)
            score = away * 0.05 - r * 0.02
            if score > best_score:
                best_score, best_at_r = score, (px, py)
        if best_at_r is not None:
            return best_at_r          # nearest radius that offers cover
    return best


def find_quick_cover(world, x, y, z, threat_eyes, max_r=13.0, step=3.0,
                     zone_center=None, zone_radius=0.0):
    """Fast (<0.5 ms) nearby solid-cover search for laser-duck and reload-cover."""
    if not threat_eyes:
        return None
    eyes = threat_eyes[:2]
    body_h = 0.5 * world.height
    for r in (4.5, 8.5, 13.0):
        if r > max_r:
            break
        best_at_r = None
        best_sc = -1e18
        for k in range(10):
            a = k * TAU / 10.0
            px, py = x + math.cos(a) * r, y + math.sin(a) * r
            pz = world.ground(px, py)
            if pz > z + world.step_up or pz < z - 5.0:
                continue
            if zone_center is not None and zone_radius > 0.0:
                if math.hypot(px - zone_center[0], py - zone_center[1]) > zone_radius * 0.90:
                    continue
            if not world.walk_clear(x, y, px, py, z):
                continue
            bz = pz + body_h
            hidden = True
            for ex, ey, ez in eyes:
                if world.shot_clear((ex, ey, ez), (px, py, bz), step=step):
                    hidden = False
                    break
            if not hidden:
                continue
            away = min(math.hypot(px - ex, py - ey) for ex, ey, _ in eyes)
            sc = away * 0.05 - r * 0.03
            if sc > best_sc:
                best_sc, best_at_r = sc, (px, py)
        if best_at_r is not None:
            return best_at_r
    return None


def find_isolate_spot(world, x, y, z, primary_pos, other_eyes,
                      zone_center=None, zone_radius=0.0, step=3.0):
    """Find a nearby spot (<=11 m) with clear LOS to primary_pos that blocks >=1 other enemy.

    Slices the pie in 1v2+ fights without interrupting offensive DPS.
    """
    if not other_eyes:
        return None
    eyes = other_eyes[:2]
    body_h = 0.5 * world.height
    muzzle_h = world.muzzle_height
    best = None
    best_sc = 0.0
    for r in (5.5, 10.5):
        for k in range(10):
            a = k * TAU / 10.0
            px, py = x + math.cos(a) * r, y + math.sin(a) * r
            pz = world.ground(px, py)
            if pz > z + world.step_up or pz < z - 5.0:
                continue
            if zone_center is not None and zone_radius > 0.0:
                if math.hypot(px - zone_center[0], py - zone_center[1]) > zone_radius * 0.90:
                    continue
            if not world.walk_clear(x, y, px, py, z):
                continue
            # Must keep clear shot on our primary target!
            if not world.shot_clear((px, py, pz + muzzle_h), primary_pos, step=step):
                continue
            bz = pz + body_h
            blocked = 0
            for ex, ey, ez in eyes:
                if not world.shot_clear((ex, ey, ez), (px, py, bz), step=step):
                    blocked += 1
            if blocked == 0:
                continue
            sc = blocked * 40.0 - r * 0.8
            if sc > best_sc:
                best_sc = sc
                best = (px, py)
        if best is not None:
            return best
    return None
