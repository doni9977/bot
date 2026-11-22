"""Apex tactical engine (Python 3.13) — 3-phase stealth/hunt/FFA controller.

Architecture:
  Phase 1 (Opening <= 20s): Stealth Ghost + Peek + LaserFirst; quiet walk when
      idle, hot-target gate avoids waking idle squad bots while securing a laser.
  Phase 2 (Squad Hunt > 20s): High-tempo hunter-killer with hot-target filter,
      heavy focus fire (Stick/LowBonus/HPw), 16-dir local fight_move, BFS
      cover_move, LoseRule rapid disengage, Finish dive, and mid-fight cube scoop.
  Phase 3 (Guard FFA, auto-switched when other_dead >= 5): Ghost + Peek +
      Vulture + Ambush + logistic Odds model for multi-way FFA finals.

Every rule value is read from hello.config. All experimental upgrades are
independently toggleable via BOT_PARAMS for clean paired A/B ablation.
"""
from __future__ import annotations

import math
import os
import random
import time
from collections import deque

from econ import upgrade_value
from params import load as load_params
from world import NullWorld, World

TAU = math.tau
PI = math.pi
AIM_LATENCY = 0.075

UPGRADE_ORDER_GUN = (
    "plating", "armor", "gun_damage", "nanites", "gun_rate",
    "lightning_efficiency", "lightning_range", "laser_damage", "servos",
    "laser_charge", "gun_mag", "gun_velocity", "gyros", "lightning_chain",
    "reactor", "capacitor", "mortar_reload", "mortar_splash",
    "mortar_velocity", "sensors", "jets", "laser_pierce",
)

UPGRADE_ORDER_LASER = (
    "plating", "armor", "laser_damage", "laser_charge", "nanites",
    "gun_damage", "gun_rate", "lightning_efficiency", "lightning_range",
    "servos", "gun_mag", "gun_velocity", "gyros", "lightning_chain",
    "reactor", "capacitor", "mortar_reload", "mortar_splash",
    "mortar_velocity", "sensors", "jets", "laser_pierce",
)

WEAPON_RANK = {"lightning": 3, "laser": 2, "mortar": 1}

APEX_DEFAULTS = {
    # Core 3-phase baseline parameters
    "retreat_hp": 0.38,
    "recover_hp": 0.80,
    "gun_range": 85.0,
    "light_range": 28.0,
    "laser_range": 85.0,
    "engage_dist": 60.0,
    "farm_npc": True,
    "ghost": True,
    "home_expo": 120.0,
    "loot_radius": 90.0,
    "crate_until": 150.0,
    "use_drops": False,
    "dodge": True,
    "no_mortar": True,
    "peek": True,
    "laser_first": True,
    "crowd_hide": True,
    "practice": True,
    "laser_seek": 0.0,
    "lethal": False,
    "lethal_k": 0.80,
    "stick": 0.0,
    "hp_w": 60.0 / 1400.0,
    "low_bonus": 0.0,
    "max_target": 215.0,
    "lose_rule": False,
    "fight_loot": 0.0,
    "farm_hp": 0.70,
    "laser_up": False,
    "finish": 0.0,
    "finish_hp": 0.38,
    "finish_rush": False,
    "pursue": 0.0,
    "backstab": 0.0,
    "cookoff_bonus": 0.0,
    # FFA Guard parameters (active when not_practice)
    "ffa_vulture": 0.55,
    "ffa_ambush": 120.0,
    "ffa_odds": 0.68,
    "ffa_odds_flee": 0.30,
    # Ablatable innovations beyond #2
    "anti_lightning": True,       # VALIDATED E57: +0.24 combined (+0.29 HK1 -> 3.35, +0.19 HK0 -> 3.08), cuts lightning deaths -53%
    "hunt_laser_duck": False,
    "dynamic_upgrades": False,
    "sensor_awareness": False,
    "kill_reset": False,
    "regen_hold": False,
    "smart_fire": False,
    "hunt_backstab": 0.0,
    "hunt_cookoff": 0.0,
    "hunt_pursue": 0.0,
    "hunt_drops": False,
    "hunt_fin_rush": False,
    "opening_laser_seek": 0.0,
    "opening_loot_r": 0.0,
    "corner_slice": False,
    "laser_punish": False,
    "smart_lose": False,
    "gun_juke": False,
    "mortar_v2": False,
    "combat_boost": False,
    "dead_window_duck": False,
    "early_hunt_laser": False,
    "long_laser_range": False,
    "smart_drops": False,
    "roof_laser_grab": False,
    "fight_loot_fix": True,
    "hunt_laser_r": 120.0,
    "hunt_fight_loot": 70.0,
}


def _ang_diff(a: float, b: float) -> float:
    d = (a - b + PI) % TAU - PI
    return d


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def _has_weapon(ws, kind: str):
    for i, w in enumerate(ws):
        if w and w.get("kind") == kind:
            return i, w
    return -1, None


class _Track:
    __slots__ = (
        "id", "kind", "pos", "vel", "aim", "hp", "max_hp", "cubes",
        "weapons", "charging", "seen", "hit_me", "dist", "los",
        "closing", "engage", "laser_fired_at",
    )

    def __init__(self, tid: int):
        self.id = tid
        self.kind = "mech"
        self.pos = (0.0, 0.0, 0.0)
        self.vel = (0.0, 0.0, 0.0)
        self.aim = (0.0, 0.0)
        self.hp = 1400.0
        self.max_hp = 1400.0
        self.cubes = 0
        self.weapons = ()
        self.charging = False
        self.seen = -100.0
        self.hit_me = -100.0
        self.dist = 999.0
        self.los = False
        self.closing = 0.0
        self.engage = False
        self.laser_fired_at = -100.0


class _Known:
    __slots__ = ("id", "kind", "pos", "hp", "seen")

    def __init__(self, kid: int):
        self.id = kid
        self.kind = ""
        self.pos = (0.0, 0.0, 0.0)
        self.hp = 0.0
        self.seen = 0.0


class ApexBrain:
    def __init__(self, hello: dict, params: dict | None = None):
        merged = dict(APEX_DEFAULTS)
        loaded = load_params(params)
        for k, v in loaded.items():
            if k in merged:
                merged[k] = v
        self.p = dict(merged)
        self.base = dict(merged)

        self.cfg = hello.get("config", {}) or {}
        self.slot = int(hello.get("slot", 0))
        seed = int(hello.get("seed", 0))
        if seed == 0:
            seed = self.slot + 1
        self.seed = seed
        self.rng = random.Random(seed)

        md = (hello.get("map") or {}).get("dir") or ""
        if not os.path.isdir(os.path.join(md, "v2")):
            md = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arena")
        if not os.path.isdir(os.path.join(md, "v2")):
            md = "/arena"
        try:
            self.w = World(md, load_trees=False, cfg=self.cfg)
        except Exception:
            self.w = NullWorld(self.cfg)

        # Config-driven rule constants (never hard-coded)
        mech_c = self.cfg.get("mech", {}) or {}
        cubes_c = self.cfg.get("cubes", {}) or {}
        npc_c = self.cfg.get("npc", {}) or {}
        crates_c = self.cfg.get("crates", {}) or {}
        loot_c = self.cfg.get("loot", {}) or {}
        sound_c = self.cfg.get("sound", {}) or {}
        match_c = self.cfg.get("match", {}) or {}
        weapons_c = self.cfg.get("weapons", {}) or {}

        tick_hz = float(match_c.get("tick_hz", 20.0) or 20.0)
        self.tick_s = 1.0 / max(1.0, tick_hz)
        self.mech_r = float(mech_c.get("radius", 2.5))
        self.mech_h = float(mech_c.get("height", 9.0))
        self.eye_h = float(mech_c.get("eye_height", 8.0))
        self.muzzle_h = float(mech_c.get("muzzle_height", 7.0))
        self.walk_speed = float(mech_c.get("walk_speed", 11.7))
        self.min_pitch = float(mech_c.get("min_pitch", -0.7))
        self.max_pitch = float(mech_c.get("max_pitch", 1.3))
        self.front_arc_rad = math.radians(float(mech_c.get("front_arc_deg", 180.0))) * 0.5
        self.rear_mult = max(1.0, float(mech_c.get("rear_mult", 1.5)))
        self.regen_delay = float(mech_c.get("regen_delay", 5.0))
        self.regen_per_s = float(mech_c.get("regen_per_s", 45.0))
        self.size_per_cube = float(cubes_c.get("size_per_cube", 0.05))
        self.dmg_per_cube = float(cubes_c.get("damage_per_cube", 0.04))
        self.cube_cap = int(cubes_c.get("stat_cap", 10))
        self.npc_r = float(npc_c.get("radius", 1.8))
        self.npc_h = float(npc_c.get("height", 3.5))
        self.crate_r = float(crates_c.get("radius", 1.4))
        self.crate_h = float(crates_c.get("height", 2.4))
        self.pickup_r = float(loot_c.get("pickup_radius", 4.0))
        self.step_speed = float(sound_c.get("step_speed", 5.0))
        self.light_range_cfg = float((weapons_c.get("lightning") or {}).get("range", 45.0))
        self.mortar_g = float((weapons_c.get("mortar") or {}).get("gravity", 22.0))
        self.mortar_splash = float((weapons_c.get("mortar") or {}).get("splash_radius", 7.0))
        self.laser_cd_cfg = float((weapons_c.get("laser") or {}).get("cooldown", 1.5))

        # Precompute 16-direction unit vectors
        self._dirs16 = [(math.cos(k * PI / 8.0), math.sin(k * PI / 8.0)) for k in range(16)]
        self._dirs8 = [(math.cos(k * PI / 4.0), math.sin(k * PI / 4.0)) for k in range(8)]

        # Dynamic state
        self.tracks: dict[int, _Track] = {}
        self.npcs: dict[int, _Track] = {}
        self.crates: dict[int, _Known] = {}
        self.cubes: dict[int, _Known] = {}
        self.pickups: dict[int, _Known] = {}
        self.bad: dict[int, float] = {}

        self.now = 0.0
        self.path: list[int] = []
        self.path_goal = (0.0, 0.0)
        self.path_at = -100.0
        self.path_i = 0

        self.strafe = 1.0
        self.strafe_until = 0.0
        self.last_juke = -100.0

        self.retreat = False
        self.cover_at = -100.0
        self.cover_goal = (0.0, 0.0)
        self.cover_ok = False
        self.regen_hold_until = -100.0

        self.last_hurt = -100.0
        self.hurt_bearing = 0.0
        self.npc_hurt = -100.0
        self.npc_bearing = 0.0
        self.sensor_at = -100.0
        self.sensor_bearing = 0.0
        self.sensor_prio = 0

        self.loot_id = -1
        self.loot_since = 0.0

        self.hold = (0.0, 0.0, 9999.0)
        self.hold_start = -1.0

        self.home_xy = (0.0, 0.0)
        self.home_at = -100.0
        self.home_set = False

        self.stuck_since = -1.0
        self.unstuck_until = -100.0
        self.unstuck_dir = (0.0, 0.0)
        self.last_threat_at = -100.0
        self.last_aim = [0.0, 0.0]

        self.esc_launch = (0.0, 0.0)
        self.esc_land = (0.0, 0.0)
        self.esc_at = -100.0
        self.esc_ok = False
        self.esc_flying = False
        self.roof_grab_flying = False
        self.roof_grab_target = None

        self.base_set = False
        self.prac_on = False
        self.not_practice = False
        self.start_alive = 16
        self.kills = 0
        self.other_dead = 0
        self.stick_id = -1
        self.stick_at = -100.0
        self.lose_at = -100.0
        self.odds_flee_until = -100.0

    # ------------------------------------------------------------------ phase
    def _squad_params(self) -> dict:
        p = dict(self.base)
        p["ghost"] = False
        p["peek"] = False
        p["laser_first"] = True
        p["laser_range"] = float(p.get("hunt_laser_r", 120.0) or 120.0)
        p["loot_radius"] = 150.0
        p["crate_until"] = 1e9
        p["stick"] = 200.0
        p["hp_w"] = 0.18
        p["low_bonus"] = 200.0
        p["max_target"] = 200.0
        p["lose_rule"] = True
        p["fight_loot"] = float(p.get("hunt_fight_loot", 70.0) or 70.0)
        p["farm_hp"] = 0.50
        p["laser_seek"] = 240.0
        p["laser_up"] = True
        p["lethal"] = True
        p["lethal_k"] = 0.70
        p["finish"] = 20.0
        if p.get("hunt_drops"):
            p["use_drops"] = True
        if p.get("hunt_pursue", 0.0) > 0:
            p["pursue"] = float(p["hunt_pursue"])
        if p.get("hunt_backstab", 0.0) > 0:
            p["backstab"] = float(p["hunt_backstab"])
        if p.get("hunt_cookoff", 0.0) > 0:
            p["cookoff_bonus"] = float(p["hunt_cookoff"])
        if p.get("hunt_fin_rush"):
            p["finish_rush"] = True
        return p

    def _ffa_params(self) -> dict:
        p = dict(self.base)
        p["ghost"] = True
        p["peek"] = True
        p["laser_first"] = True
        p["laser_seek"] = 180.0
        p["lethal"] = True
        p["lethal_k"] = 0.75
        p["finish"] = 24.0
        p["stick"] = 120.0
        p["low_bonus"] = 120.0
        return p

    # ------------------------------------------------------------------ helpers
    def _scale(self, cubes: int) -> float:
        return 1.0 + self.size_per_cube * cubes

    def _center(self, t: _Track):
        h = self.npc_h if t.kind == "npc" else self.mech_h * self._scale(t.cubes)
        return (t.pos[0], t.pos[1], t.pos[2] + h * 0.5)

    def _eye(self, t: _Track):
        return (t.pos[0], t.pos[1], t.pos[2] + self.eye_h * self._scale(t.cubes))

    def _shows_back(self, t: _Track, x: float, y: float) -> bool:
        return abs(_ang_diff(t.aim[0], math.atan2(y - t.pos[1], x - t.pos[0]))) > self.front_arc_rad + 0.1

    def _zone_at(self, z: dict, t: float):
        ss = float(z.get("shrink_start", 0.0))
        se = float(z.get("shrink_end", 0.0))
        if t <= ss or se <= ss:
            return self.hold
        f = _clamp((t - ss) / (se - ss), 0.0, 1.0)
        nc = z.get("next_center") or [0.0, 0.0]
        nr = float(z.get("next_radius", 0.0))
        hx, hy, hr = self.hold
        return (hx + (nc[0] - hx) * f, hy + (nc[1] - hy) * f, hr + (nr - hr) * f)

    def _cur_zone(self, z: dict):
        c = z.get("center") or [0.0, 0.0]
        live = (float(c[0]), float(c[1]), float(z.get("radius", 9999.0)))
        ss = float(z.get("shrink_start", 0.0))
        if self.now <= ss:
            return live
        if abs(live[2] - self.hold[2]) > 0.01 or abs(live[0] - self.hold[0]) > 0.01:
            return live
        return self._zone_at(z, self.now)

    def _zone_deadline(self, z: dict, x: float, y: float, pad: float) -> float:
        nc = z.get("next_center") or [0.0, 0.0]
        nr = float(z.get("next_radius", 0.0))
        if math.hypot(x - nc[0], y - nc[1]) <= nr - pad:
            return 1e9
        ss = float(z.get("shrink_start", 0.0))
        se = float(z.get("shrink_end", 0.0))
        if se <= ss:
            return se
        span = (se - ss) / 20.0
        for k in range(21):
            t = ss + span * k
            cx, cy, cr = self._zone_at(z, t)
            if math.hypot(x - cx, y - cy) > cr - pad:
                return t
        return se

    def _zone_penalty(self, z: dict, x: float, y: float) -> float:
        cx, cy, cr = self._cur_zone(z)
        p = 0.0
        d = math.hypot(x - cx, y - cy) - cr
        if d > -5.0:
            p += 150.0 + 5.0 * (d + 5.0)
        nc = z.get("next_center") or [0.0, 0.0]
        nr = float(z.get("next_radius", 0.0))
        dn = math.hypot(x - nc[0], y - nc[1]) - nr
        if dn > -5.0:
            ss = float(z.get("shrink_start", 0.0))
            soon = _clamp(1.0 - (ss - self.now) / 25.0, 0.1, 1.0)
            p += soon * (25.0 + 0.8 * (dn + 5.0))
        return p

    def _zone_goal(self, z: dict, x: float, y: float):
        nc = z.get("next_center") or [0.0, 0.0]
        nr = float(z.get("next_radius", 0.0))
        if nr <= 30.0:
            return float(nc[0]), float(nc[1])
        margin = _clamp(0.3 * nr, 3.0, 30.0)
        dx, dy = x - nc[0], y - nc[1]
        d = math.hypot(dx, dy)
        if d < 1.0:
            return x, y
        r = max(0.0, nr - margin - 5.0)
        if d <= r:
            return x, y
        return nc[0] + dx / d * r, nc[1] + dy / d * r

    # ------------------------------------------------------------------ observe
    def _observe(self, obs: dict):
        me = obs["self"]
        now = self.now
        mx, my, mz = float(me["pos"][0]), float(me["pos"][1]), float(me["pos"][2])
        mvx, mvy = float(me["vel"][0]), float(me["vel"][1])
        st = me.get("stats") or {}
        eh = float(st.get("eye_height", self.eye_h))
        mh = float(st.get("muzzle_height", self.muzzle_h))
        ex, ey, ez = mx, my, mz + eh
        zx, zy, zz = mx, my, mz + mh
        w = self.w

        for m in obs.get("mechs") or ():
            mid = int(m["id"])
            kind = m.get("kind", "mech")
            tab = self.npcs if kind == "npc" else self.tracks
            t = tab.get(mid)
            if t is None:
                t = _Track(mid)
                tab[mid] = t
            t.kind = kind
            mp = m["pos"]
            mv = m.get("vel") or (0.0, 0.0, 0.0)
            ma = m.get("aim") or (0.0, 0.0)
            t.pos = (float(mp[0]), float(mp[1]), float(mp[2]))
            t.vel = (float(mv[0]), float(mv[1]), float(mv[2]))
            t.aim = (float(ma[0]), float(ma[1]))
            t.hp = float(m.get("hp", 1400.0))
            t.max_hp = float(m.get("max_hp", 1400.0))
            t.cubes = int(m.get("cubes", 0))
            t.weapons = tuple(m.get("weapons") or ())
            t.charging = bool(m.get("charging", False))
            t.seen = now
            dx = t.pos[0] - mx
            dy = t.pos[1] - my
            t.dist = math.hypot(dx, dy)
            cx, cy, cz = self._center(t)
            t.los = w.clear(zx, zy, zz, cx, cy, cz)
            if not t.los and kind == "mech":
                th = self.mech_h * self._scale(t.cubes)
                t.los = w.clear(zx, zy, zz, t.pos[0], t.pos[1], t.pos[2] + th * 0.85)
            if t.dist > 1.0:
                t.closing = -((t.vel[0] - mvx) * dx + (t.vel[1] - mvy) * dy) / t.dist
            else:
                t.closing = 0.0

        for mid in [k for k, v in self.tracks.items() if now - v.seen > 20.0]:
            del self.tracks[mid]
        for mid in [k for k, v in self.npcs.items() if now - v.seen > 120.0]:
            del self.npcs[mid]

        def _upd(tab: dict, items):
            for it in items or ():
                iid = int(it["id"])
                k = tab.get(iid)
                if k is None:
                    k = _Known(iid)
                    tab[iid] = k
                p = it["pos"]
                k.kind = it.get("kind", "")
                k.pos = (float(p[0]), float(p[1]), float(p[2]))
                k.hp = float(it.get("hp", 0.0))
                k.seen = now
            gone = []
            for iid, k in tab.items():
                if k.seen == now:
                    continue
                if math.hypot(k.pos[0] - mx, k.pos[1] - my) < 40.0 and now - k.seen > 0.35:
                    if w.clear(ex, ey, ez, k.pos[0], k.pos[1], k.pos[2] + 1.5):
                        gone.append(iid)
            for iid in gone:
                del tab[iid]

        _upd(self.crates, obs.get("crates"))
        _upd(self.cubes, obs.get("cubes"))
        _upd(self.pickups, obs.get("pickups"))

        # Beam & sound situational awareness (Innovation 4)
        if self.p.get("sensor_awareness") or self.p.get("laser_punish"):
            for bm in obs.get("beams") or ():
                st_p = bm.get("start")
                if not st_p:
                    continue
                bx, by = float(st_p[0]), float(st_p[1])
                d = math.hypot(bx - mx, by - my)
                if 8.0 < d < 240.0:
                    # Attribute beam to closest known track to mark laser cooldown
                    best_t = None
                    best_d = 18.0
                    for tr in self.tracks.values():
                        if now - tr.seen < 2.0:
                            td = math.hypot(tr.pos[0] - bx, tr.pos[1] - by)
                            if td < best_d:
                                best_d = td
                                best_t = tr
                    if best_t is not None:
                        best_t.laser_fired_at = now
                    if self.p.get("sensor_awareness"):
                        self.sensor_at = now
                        self.sensor_bearing = math.atan2(by - my, bx - mx)
                        self.sensor_prio = 3
            if self.p.get("sensor_awareness"):
                for sn in obs.get("sounds") or ():
                    age = float(sn.get("age", 9.0))
                    if age > 0.8:
                        continue
                    band = sn.get("band", "far")
                    skind = sn.get("kind", "")
                    if band == "far":
                        continue
                    prio = 0
                    if skind in ("laser_charge", "laser"):
                        prio = 4 if band == "near" else 3
                    elif skind == "lightning":
                        prio = 4 if band == "near" else 2
                    elif skind in ("gun", "mortar") and band == "near":
                        prio = 2
                    if prio > 0 and (now - self.sensor_at > 1.2 or prio >= self.sensor_prio):
                        self.sensor_at = now
                        self.sensor_bearing = float(sn.get("bearing", 0.0))
                        self.sensor_prio = prio

        for ev in obs.get("events") or ():
            et = ev.get("type")
            if et == "damaged":
                bearing = ev.get("bearing")
                wep = ev.get("weapon", "")
                if wep == "npc" and bearing is not None:
                    self.npc_hurt = now
                    self.npc_bearing = float(bearing)
                if self.p.get("gun_juke") and wep == "gun" and now - self.last_juke > 0.30:
                    # Break enemy linear velocity lead the exact tick a gun round connects
                    self.strafe = -self.strafe
                    self.strafe_until = now + 0.45
                    self.last_juke = now
                by = ev.get("by")
                if by is not None:
                    self.last_hurt = now
                    if bearing is not None:
                        self.hurt_bearing = float(bearing)
                    by_id = int(by)
                    if by_id in self.tracks:
                        self.tracks[by_id].hit_me = now
                    if by_id in self.npcs:
                        self.npcs[by_id].hit_me = now
            elif et == "kill":
                self.kills += 1
                tid = int(ev.get("target", -1))
                self.tracks.pop(tid, None)
                if self.p.get("kill_reset"):
                    other_hot = False
                    for tr in self.tracks.values():
                        if now - tr.hit_me < 3.0 or (tr.seen == now and tr.dist < 55.0):
                            other_hot = True
                            break
                    if not other_hot:
                        self.lose_at = -100.0
                        self.retreat = False

        # Auto-detect practice (squad) vs FFA (other bots killing each other)
        alive = int(obs.get("alive", 16))
        if not self.base_set:
            self.base_set = True
            self.start_alive = alive
        if self.start_alive - alive - self.kills > 0:
            self.other_dead += 1
        else:
            self.other_dead = 0
        if self.other_dead >= 5 and not self.not_practice:
            self.not_practice = True
            self.prac_on = False
            self.p = self._ffa_params()

        if self.base.get("practice") and not self.not_practice:
            _, has_las = _has_weapon(me.get("weapons") or (), "laser")
            want_prac = now > 20.0 or (bool(self.base.get("early_hunt_laser")) and has_las is not None and now >= 8.0)
            if want_prac != self.prac_on:
                self.prac_on = want_prac
                self.p = self._squad_params() if want_prac else dict(self.base)
            elif not self.prac_on:
                if self.base.get("opening_laser_seek", 0.0) > 0:
                    self.p["laser_seek"] = float(self.base["opening_laser_seek"])
                if self.base.get("opening_loot_r", 0.0) > 0:
                    self.p["loot_radius"] = float(self.base["opening_loot_r"])

        z = obs.get("zone") or {}
        ss = float(z.get("shrink_start", 0.0))
        zc = z.get("center") or [0.0, 0.0]
        zr = float(z.get("radius", 9999.0))
        if self.hold_start != ss or now <= ss:
            self.hold_start = ss
            self.hold = (float(zc[0]), float(zc[1]), zr)

    # ------------------------------------------------------------------ upgrades & pickups
    def _pick_upgrade(self, me: dict, offer: dict) -> int:
        choices = offer.get("choices") or []
        if not choices:
            return 0
        if self.p.get("dynamic_upgrades"):
            best_i = 0
            best_v = -1e18
            held = {w["kind"] for w in (me.get("weapons") or ()) if w}
            for i, c in enumerate(choices):
                # Exact config-driven value via econ.py v2
                v = upgrade_value(c, {"upgrade_v2": True}, me=me, cfg=self.cfg, exact=True)
                uid = c.get("id", "")
                # Small lookahead for laser upgrades if slot 1 is empty in Hunt
                if uid in ("laser_damage", "laser_charge") and "laser" not in held and self.prac_on:
                    ws = me.get("weapons") or ()
                    if len(ws) < 2 or ws[1] is None:
                        v = max(v, 14.0 if uid == "laser_damage" else 12.0)
                if v > best_v:
                    best_v = v
                    best_i = i
            return best_i

        order = UPGRADE_ORDER_LASER if self.p.get("laser_up") else UPGRADE_ORDER_GUN
        best_i = 0
        best_r = len(order) + 1
        for i, c in enumerate(choices):
            cid = c.get("id", "")
            try:
                r = order.index(cid)
            except ValueError:
                r = len(order)
            if r < best_r:
                best_r = r
                best_i = i
        return best_i

    def _want_pickup(self, me: dict, kind: str) -> bool:
        ws = me.get("weapons") or []
        if kind == "gun":
            return len(ws) > 0 and ws[0] is None
        idx, _ = _has_weapon(ws, kind)
        if idx >= 0:
            return False
        if kind == "mortar" and self.p.get("no_mortar"):
            return False
        def _rank(k: str) -> int:
            if self.p.get("laser_first") and k == "laser":
                return 4
            return WEAPON_RANK.get(k, 0)
        cur = _rank(ws[1]["kind"]) if (len(ws) > 1 and ws[1] is not None) else 0
        return _rank(kind) > cur

    # ------------------------------------------------------------------ movement primitives
    def _travel(self, me: dict, gx: float, gy: float):
        x, y, zf = float(me["pos"][0]), float(me["pos"][1]), float(me["pos"][2])
        d = math.hypot(gx - x, gy - y)
        if d < 0.8:
            return 0.0, 0.0

        def _unit(tx: float, ty: float):
            l = math.hypot(tx - x, ty - y)
            return ((tx - x) / l, (ty - y) / l) if l > 1e-6 else (0.0, 0.0)

        w = self.w
        if w.ready and zf - w.ground(x, y) > 3.0 and w.obst[w.idx(x, y)]:
            return _unit(gx, gy)
        if d < 45.0 and w.line_walkable2(x, y, gx, gy):
            return _unit(gx, gy)
        goal_shift = math.hypot(gx - self.path_goal[0], gy - self.path_goal[1])
        need_replan = (
            (not self.path and self.now - self.path_at > 0.35)
            or (goal_shift > 5.0 and self.now - self.path_at > 0.25)
            or self.now - self.path_at > 2.5
        )
        if need_replan:
            self.path, _ = w.path2(x, y, gx, gy, max_expand=4000, budget_s=0.008)
            self.path_goal = (gx, gy)
            self.path_at = self.now
            self.path_i = 0
        if not self.path:
            return _unit(gx, gy)
        bi = self.path_i
        bd = 1e18
        lim = min(len(self.path), self.path_i + 10)
        for i in range(self.path_i, lim):
            px, py = w.cell2_pos(self.path[i])
            dd = math.hypot(px - x, py - y)
            if dd < bd:
                bd = dd
                bi = i
        self.path_i = bi
        if bd > 12.0:
            self.path = []
            return _unit(gx, gy)
        for i in range(min(bi + 12, len(self.path) - 1), bi, -1):
            px, py = w.cell2_pos(self.path[i])
            if w.line_walkable2(x, y, px, py):
                if i == len(self.path) - 1 and math.hypot(px - gx, py - gy) < 4.0 and w.line_walkable2(x, y, gx, gy):
                    return _unit(gx, gy)
                return _unit(px, py)
        if bi + 1 < len(self.path):
            px, py = w.cell2_pos(self.path[bi + 1])
            return _unit(px, py)
        return _unit(gx, gy)

    def _escape(self, me: dict):
        """Jump-jet escape if spawned/trapped inside a walled courtyard."""
        w = self.w
        if not w.ready:
            return False, 0.0, 0.0, False, False
        x, y, zf = float(me["pos"][0]), float(me["pos"][1]), float(me["pos"][2])
        grounded = bool(me.get("grounded", True))
        energy = float(me.get("energy", 0.0))
        max_e = float(me.get("max_energy", 100.0))
        jump = False
        if grounded:
            if zf - w.ground(x, y) > 3.0 and w.obst[w.idx(x, y)]:
                self.esc_ok = self.esc_flying = False
                return False, 0.0, 0.0, False, False
            if not w.off_main(x, y):
                self.esc_ok = self.esc_flying = False
                return False, 0.0, 0.0, False, False
            self.esc_flying = False
            if not self.esc_ok or self.now - self.esc_at > 6.0:
                la, ld, ok = w.escape_plan(x, y)
                self.esc_at = self.now
                if not ok:
                    self.esc_ok = False
                    return False, 0.0, 0.0, False, False
                self.esc_launch, self.esc_land, self.esc_ok = la, ld, True
            if math.hypot(self.esc_launch[0] - x, self.esc_launch[1] - y) > 3.0:
                mx, my = self._travel(me, self.esc_launch[0], self.esc_launch[1])
                return True, mx, my, False, False
            if energy < min(70.0, max_e * 0.7):
                return True, 0.0, 0.0, False, False
            self.esc_flying = True
            jump = True
        elif not self.esc_flying:
            return False, 0.0, 0.0, False, False
        dx, dy = self.esc_land[0] - x, self.esc_land[1] - y
        d = math.hypot(dx, dy)
        if d < 1.5:
            return True, 0.0, 0.0, False, jump
        mx, my = dx / d, dy / d
        need = -1e9
        steps = int(min(d, 30.0))
        for t in range(steps + 1):
            tv = w.top_at(x + mx * t, y + my * t)
            if tv > need:
                need = tv
        return True, mx, my, (zf < need + 2.5 and energy > 1.0), jump

    def _roof_laser_grab(self, me: dict, z: dict):
        """Hit-and-run jump-jet onto a low roof (<14m) solely to grab an otherwise unreachable laser."""
        w = self.w
        if not w.ready:
            return None
        x, y, zf = float(me["pos"][0]), float(me["pos"][1]), float(me["pos"][2])
        energy = float(me.get("energy", 0.0))
        grounded = bool(me.get("grounded", True))
        best_pk = None
        best_d = 95.0
        for pk in self.pickups.values():
            if pk.kind != "laser":
                continue
            dz = pk.pos[2] - w.ground(pk.pos[0], pk.pos[1])
            if dz <= 3.2 or dz > 14.0:
                continue
            if self._zone_penalty(z, pk.pos[0], pk.pos[1]) > 0.0:
                continue
            d = math.hypot(pk.pos[0] - x, pk.pos[1] - y)
            if d < best_d:
                best_d = d
                best_pk = pk
        if best_pk is None:
            self.roof_grab_flying = False
            return None
        px, py, pz = best_pk.pos
        # If already near/above roof elevation, walk straight onto the pickup
        if abs(zf - pz) <= 3.5:
            self.roof_grab_flying = False
            d = math.hypot(px - x, py - y)
            if d < 0.5:
                return 0.0, 0.0, False, False
            return (px - x) / d, (py - y) / d, False, False
        # Find nearest free street cell next to the roof pickup
        nf = w.nearest_free2(w.cell2(px, py))
        if nf < 0 or w.n2_comp[nf] != w.main_comp:
            return None
        lx, ly = w.cell2_pos(nf)
        if math.hypot(lx - px, ly - py) > 16.0:
            return None
        if grounded:
            self.roof_grab_flying = False
            if math.hypot(lx - x, ly - y) > 3.5:
                mx, my = self._travel(me, lx, ly)
                return mx, my, False, False
            if energy < 65.0:
                return 0.0, 0.0, False, False
            self.roof_grab_flying = True
            d = math.hypot(px - x, py - y) + 1e-6
            return (px - x) / d, (py - y) / d, True, True
        if not self.roof_grab_flying:
            return None
        d = math.hypot(px - x, py - y) + 1e-6
        return (px - x) / d, (py - y) / d, (zf < pz + 1.8 and energy > 2.0), False

    def _dodge_shell(self, obs: dict):
        me = obs["self"]
        x, y = float(me["pos"][0]), float(me["pos"][1])
        v2 = bool(self.p.get("mortar_v2"))
        pad = 3.0 if v2 else 2.0
        rad = self.mortar_splash + float((me.get("stats") or {}).get("radius", self.mech_r)) + pad
        t_lim = 3.0 if v2 else 2.5
        rots = (0.0, 0.55, -0.55, 1.1, -1.1, 1.65, -1.65, 2.2, -2.2) if v2 else (0.0, 0.7, -0.7, 1.4, -1.4)
        g = self.mortar_g
        w = self.w
        for pr in obs.get("projectiles") or ():
            if pr.get("kind") != "mortar":
                continue
            px, py, pz = float(pr["pos"][0]), float(pr["pos"][1]), float(pr["pos"][2])
            vx, vy, vz = float(pr["vel"][0]), float(pr["vel"][1]), float(pr["vel"][2])
            t = 0.0
            while t < 4.0:
                px += vx * 0.05
                py += vy * 0.05
                pz += vz * 0.05
                vz -= g * 0.05
                t += 0.05
                if w.solid(px, py, pz):
                    d = math.hypot(px - x, py - y)
                    if d < rad and t < t_lim:
                        dx, dy = x - px, y - py
                        if d < 0.5:
                            dx, dy = -vy, vx
                            d = math.hypot(dx, dy) + 1e-9
                        dx, dy = dx / d, dy / d
                        for rot in rots:
                            c, s = math.cos(rot), math.sin(rot)
                            ex, ey = dx * c - dy * s, dx * s + dy * c
                            if w.line_walkable2(x, y, x + ex * 6.0, y + ey * 6.0):
                                return True, ex, ey
                    break
        return False, 0.0, 0.0

    def _pref_range(self, me: dict, tg: _Track) -> float:
        _, light = _has_weapon(me.get("weapons") or (), "lightning")
        _, laser = _has_weapon(me.get("weapons") or (), "laser")
        if tg.kind == "npc":
            return 58.0
        if light is not None and float(me.get("energy", 0.0)) > 12.0:
            r = float(self.p["light_range"])
        elif laser is not None:
            r = float(self.p["laser_range"])
        else:
            r = float(self.p["gun_range"])
        if light is None:
            if "lightning" in tg.weapons:
                r = max(r, self.light_range_cfg + 19.0)
            if "mortar" in tg.weapons:
                r = max(r, 80.0)
        return r

    def _fight_move(self, obs: dict, tg: _Track, seen: list[_Track], want_los: float, extra_ring: bool = False):
        me = obs["self"]
        x, y, zf = float(me["pos"][0]), float(me["pos"][1]), float(me["pos"][2])
        st = me.get("stats") or {}
        mh = float(st.get("muzzle_height", self.muzzle_h))
        my_h = float(st.get("height", self.mech_h))
        rp = self._pref_range(me, tg)
        bx, by = tg.pos[0] - x, tg.pos[1] - y
        bd = math.hypot(bx, by) + 1e-9
        ux, uy = bx / bd, by / bd
        if self.now >= self.strafe_until:
            if self.rng.random() < 0.6:
                self.strafe = -self.strafe
            self.strafe_until = self.now + 0.3 + self.rng.random() * 0.7
        sx, sy = -uy * self.strafe, ux * self.strafe
        tcx, tcy, tcz = self._center(tg)

        # Nearest reachable ground-level cube within 40m
        cube = None
        cube_d = 40.0
        for c in self.cubes.values():
            if abs(c.pos[2] - zf) < 4.0:
                d = math.hypot(c.pos[0] - x, c.pos[1] - y)
                if d < cube_d:
                    cube_d = d
                    cube = c

        _, my_light = _has_weapon(me.get("weapons") or (), "lightning")
        anti_light = bool(self.p.get("anti_lightning")) and (my_light is None)
        light_r = self.light_range_cfg
        peek = bool(self.p.get("peek"))
        corner_slice = bool(self.p.get("corner_slice"))
        rings = 2 if (peek or extra_ring) else 1
        w = self.w
        z = obs["zone"]
        # Pre-filter nearby other enemies for LOS checks
        others = []
        light_foes = []
        for e in seen:
            ed0 = math.hypot(e.pos[0] - x, e.pos[1] - y)
            if anti_light and "lightning" in e.weapons and ed0 < light_r + 32.0:
                light_foes.append(e)
            if e is not tg and ed0 < 185.0:
                others.append((e, self._eye(e)))

        best = -1e18
        mx, my = 0.0, 0.0
        blocked_side = False
        dirs16 = self._dirs16
        dirs8 = self._dirs8
        t_fm = time.perf_counter()

        for k in range(-1, 16 * rings):
            if k >= 16 and (k & 3) == 0 and (time.perf_counter() - t_fm) > 0.007:
                break
            if k < 0:
                cx, cy, dx, dy, r = x, y, 0.0, 0.0, 0.0
            else:
                dx, dy = dirs16[k & 15]
                r = 6.0 if k < 16 else 12.0
                cx, cy = x + dx * r, y + dy * r
                if not w.free2(cx, cy) or not w.line_walkable2(x, y, cx, cy):
                    if k < 16 and dx * sx + dy * sy > 0.9:
                        blocked_side = True
                    continue
            cz = w.walk_at(cx, cy)
            d = math.hypot(tg.pos[0] - cx, tg.pos[1] - cy)
            s = -1.1 * abs(d - rp) - r * 0.4
            los = w.clear(cx, cy, cz + mh, tcx, tcy, tcz)
            if los:
                s += 45.0 * want_los
            if peek and 0 <= k < 16 and (los == (want_los > 0.0)) and (time.perf_counter() - t_fm) < 0.005:
                for qx_d, qy_d in dirs8:
                    qx, qy = cx + qx_d * 7.0, cy + qy_d * 7.0
                    if w.free2(qx, qy) and w.clear(qx, qy, w.walk_at(qx, qy) + mh, tcx, tcy, tcz) != los:
                        s += 8.0
                        break
            body_z = cz + my_h * 0.6
            vis_others = 0
            for e, (eex, eey, eez) in others:
                if math.hypot(e.pos[0] - cx, e.pos[1] - cy) <= 170.0:
                    if w.clear(eex, eey, eez, cx, cy, body_z):
                        vis_others += 1
                        s -= 35.0 if corner_slice else 30.0
            # Extra bonus for true 1v1 isolation when multiple enemies are present
            if corner_slice and los and want_los > 0.0 and len(others) > 0 and vis_others == 0:
                s += 18.0
            if light_foes:
                for lf in light_foes:
                    ed = math.hypot(lf.pos[0] - cx, lf.pos[1] - cy)
                    if ed < light_r + 16.0:
                        s -= (light_r + 16.0 - ed) * 4.2
            s -= self._zone_penalty(z, cx, cy)
            if cube is not None:
                s += 1.5 * (cube_d - math.hypot(cube.pos[0] - cx, cube.pos[1] - cy))
            if w.ready:
                cl = w.n2_clr[w.cell2(cx, cy)]
                if cl < 3:
                    s -= (3 - cl) * 3.0
            if want_los > 0.0:
                s += 9.0 * (dx * sx + dy * sy)
            if k < 0:
                s -= 8.0
                if want_los < 0.0 and not los:
                    s += 14.0
            if s > best:
                best = s
                mx, my = dx, dy
        if blocked_side:
            self.strafe = -self.strafe
            self.strafe_until = self.now + 0.5
        return mx, my

    def _cover_move(self, obs: dict, seen: list[_Track]):
        me = obs["self"]
        x, y = float(me["pos"][0]), float(me["pos"][1])
        my_h = float((me.get("stats") or {}).get("height", self.mech_h))
        threats = [t for t in seen if math.hypot(t.pos[0] - x, t.pos[1] - y) < 230.0]
        if not threats:
            return False, 0.0, 0.0
        if len(threats) > 4:
            threats.sort(key=lambda t: math.hypot(t.pos[0] - x, t.pos[1] - y))
            threats = threats[:4]
        eyes = [(t, self._eye(t)) for t in threats]
        w = self.w
        z = obs["zone"]

        def _hidden(cx: float, cy: float) -> bool:
            cz = w.walk_at(cx, cy)
            h_hi = cz + my_h
            h_mid = cz + my_h * 0.5
            for _, (ex, ey, ez) in eyes:
                if w.clear(ex, ey, ez, cx, cy, h_hi) or w.clear(ex, ey, ez, cx, cy, h_mid):
                    return False
            return True

        if self.cover_ok and self.now - self.cover_at < 0.4:
            if math.hypot(self.cover_goal[0] - x, self.cover_goal[1] - y) < 1.8:
                return True, 0.0, 0.0
            mx, my = self._travel(me, self.cover_goal[0], self.cover_goal[1])
            return True, mx, my

        self.cover_at = self.now
        if _hidden(x, y) and self._zone_penalty(z, x, y) == 0.0:
            self.cover_ok = True
            self.cover_goal = (x, y)
            return True, 0.0, 0.0

        if not w.ready:
            return False, 0.0, 0.0
        s = w.nearest_free2(w.cell2(x, y))
        if s < 0:
            return False, 0.0, 0.0
        w._n2_gen += 1
        gen = w._n2_gen
        stamp = w._n2_stamp
        gscore = w._n2_g
        blk = w.n2_blk
        surf = w.n2_surf
        n2x, n2y = w.n2x, w.n2y
        ns = w.n2s
        climb_c = w._n2_climb_c

        stamp[s] = gen
        gscore[s] = 0.0
        q = deque([s])
        best_c = -1
        best_s = 1e18
        checked = 0
        t0 = time.perf_counter()

        while q and checked < 160:
            if checked > 0 and (checked & 15) == 0 and (time.perf_counter() - t0) > 0.006:
                break
            c = q.popleft()
            steps = gscore[c]
            if steps > 34.0 or (best_c >= 0 and steps * ns > best_s + 26.0):
                break
            ci, cj = c % n2x, c // n2x
            if ((ci + cj) & 1) == 0 and steps > 0.0:
                cx, cy = w.cell2_pos(c)
                checked += 1
                if _hidden(cx, cy):
                    sc = steps * ns + self._zone_penalty(z, cx, cy)
                    near = min(math.hypot(t.pos[0] - cx, t.pos[1] - cy) for t in threats)
                    sc -= min(near, 80.0) * 0.25
                    if sc < best_s:
                        best_s = sc
                        best_c = c
            sc_z = surf[c]
            ng = steps + 1.0
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

        if best_c < 0:
            self.cover_ok = False
            return False, 0.0, 0.0
        gx, gy = w.cell2_pos(best_c)
        self.cover_ok = True
        self.cover_goal = (gx, gy)
        if math.hypot(gx - x, gy - y) < 1.8:
            return True, 0.0, 0.0
        mx, my = self._travel(me, gx, gy)
        return True, mx, my

    def _hide_from_bearing(self, obs: dict, seen: list[_Track]):
        me = obs["self"]
        ghost = _Track(-999)
        ghost.pos = (
            float(me["pos"][0]) + math.cos(self.hurt_bearing) * 80.0,
            float(me["pos"][1]) + math.sin(self.hurt_bearing) * 80.0,
            float(me["pos"][2]),
        )
        return self._cover_move(obs, [ghost] + seen)

    def _home_cost(self, obs: dict, px: float, py: float) -> float:
        z = obs["zone"]
        now = self.now
        crowd = 0.0
        for t in self.tracks.values():
            if now - t.seen < 20.0:
                crowd += max(0.0, 80.0 - math.hypot(t.pos[0] - px, t.pos[1] - py)) / 80.0
        for dr in obs.get("drops") or ():
            dp = dr["pos"]
            crowd += max(0.0, 60.0 - math.hypot(dp[0] - px, dp[1] - py)) / 60.0
        nc = z.get("next_center") or [0.0, 0.0]
        nr = max(30.0, float(z.get("next_radius", 30.0)))
        edge = math.hypot(px - nc[0], py - nc[1]) / nr
        me = obs["self"]["pos"]
        return (
            float(self.p["home_expo"]) * self.w.exposure(px, py)
            + 0.25 * math.hypot(px - me[0], py - me[1])
            + 40.0 * crowd
            + 10.0 * edge
        )

    def _home(self, obs: dict):
        z = obs["zone"]
        nc = z.get("next_center") or [0.0, 0.0]
        nr = float(z.get("next_radius", 100.0))
        out = (not self.home_set) or math.hypot(self.home_xy[0] - nc[0], self.home_xy[1] - nc[1]) > nr * 0.8
        if out or self.now - self.home_at > 12.0:
            self.home_at = self.now
            best = None
            best_c = 1e18
            t0 = time.perf_counter()
            for k in range(18):
                if k >= 6 and (time.perf_counter() - t0) > 0.005:
                    break
                a = self.rng.random() * TAU
                r = math.sqrt(self.rng.random()) * nr * 0.7
                px, py = nc[0] + math.cos(a) * r, nc[1] + math.sin(a) * r
                if not self.w.reachable2(px, py):
                    continue
                c = self._home_cost(obs, px, py)
                if c < best_c:
                    best_c = c
                    best = (px, py)
            if best is not None and (out or best_c < self._home_cost(obs, self.home_xy[0], self.home_xy[1]) - 15.0):
                self.home_xy = best
                self.home_set = True
        return self.home_xy[0], self.home_xy[1], self.home_set

    def _choose_loot(self, obs: dict, hp_frac: float, danger: bool):
        me = obs["self"]
        x, y = float(me["pos"][0]), float(me["pos"][1])
        z = obs["zone"]
        now = self.now
        cx, cy, cr = self._cur_zone(z)
        walk_spd = float((me.get("stats") or {}).get("walk_speed", self.walk_speed)) or self.walk_speed
        w = self.w
        best = None
        best_u = 0.0

        def _consider(kind: str, iid: int, pos, value: float):
            nonlocal best, best_u
            if self.bad.get(iid, -1.0) > now:
                return
            d = math.hypot(pos[0] - x, pos[1] - y)
            if d > 260.0:
                return
            if math.hypot(pos[0] - cx, pos[1] - cy) > cr - 6.0:
                return
            if now + d * 1.4 / walk_spd + 5.0 > self._zone_deadline(z, pos[0], pos[1], 6.0):
                return
            if pos[2] - w.ground(pos[0], pos[1]) > 3.2:
                return
            if w.ready:
                nf = w.nearest_free2(w.cell2(pos[0], pos[1]))
                if nf < 0 or w.n2_comp[nf] != w.main_comp:
                    return
            u = value / (d + 18.0)
            if iid == self.loot_id:
                u *= 1.35
            if u > best_u:
                best_u = u
                best = (kind, iid, pos, value)

        loot_r = float(self.p["loot_radius"])
        laser_seek = float(self.p["laser_seek"])
        ws = me.get("weapons") or []
        slot1_empty = len(ws) < 2 or ws[1] is None
        for pk in self.pickups.values():
            seek = pk.kind == "laser" and laser_seek > loot_r
            rad = laser_seek if seek else loot_r
            if self._want_pickup(me, pk.kind) and math.hypot(pk.pos[0] - x, pk.pos[1] - y) < rad:
                v = 130.0 if slot1_empty else 60.0
                if seek:
                    v = max(v, 150.0)
                _consider("pickup", pk.id, pk.pos, v)

        my_cubes = int(me.get("cubes", 0))
        cube_v = 25.0 if my_cubes >= self.cube_cap else 75.0
        cube_rad = max(60.0, loot_r * 0.7)
        for cb in self.cubes.values():
            if math.hypot(cb.pos[0] - x, cb.pos[1] - y) < cube_rad:
                _consider("cube", cb.id, cb.pos, cube_v)

        farm_hp = float(self.p.get("farm_hp", 0.70) or 0.70)
        if hp_frac > farm_hp and not danger and now < float(self.p["crate_until"]):
            for cr_it in self.crates.values():
                if math.hypot(cr_it.pos[0] - x, cr_it.pos[1] - y) < loot_r:
                    _consider("crate", cr_it.id, cr_it.pos, cube_v * 0.6)
            if self.p.get("farm_npc") and my_cubes < self.cube_cap:
                for np in self.npcs.values():
                    if now - np.seen < 12.0 and math.hypot(np.pos[0] - x, np.pos[1] - y) < loot_r:
                        _consider("npc", np.id, np.pos, 85.0)

        if (self.p.get("use_drops") or self.p.get("smart_drops")) and not danger:
            smart_d = bool(self.p.get("smart_drops")) and not bool(self.p.get("use_drops"))
            for dr in obs.get("drops") or ():
                holder = dr.get("holder")
                if holder is not None and holder != me.get("id"):
                    continue
                dp = dr["pos"]
                dist = math.hypot(dp[0] - x, dp[1] - y)
                eta = dist * 1.45 / walk_spd
                lands_in = float(dr.get("lands_in", 0.0))
                cap_s = float(dr.get("capture_s", 5.0))
                if smart_d:
                    if dist <= 110.0 and lands_in <= 6.0 and (hp_frac < 0.85 or my_cubes < 6) and eta + lands_in + cap_s <= 18.0:
                        _consider("drop", int(dr["id"]), (float(dp[0]), float(dp[1]), float(dp[2])), 280.0)
                elif eta <= 15.0 and lands_in <= 6.0 and eta + lands_in + cap_s <= 20.0:
                    _consider("drop", int(dr["id"]), (float(dp[0]), float(dp[1]), float(dp[2])), 260.0)

        if best is None:
            self.loot_id = -1
            return None
        if best[1] != self.loot_id:
            self.loot_id = best[1]
            self.loot_since = now
        elif now - self.loot_since > 30.0:
            self.bad[best[1]] = now + 60.0
            self.loot_id = -1
            return None
        return best

    def _dodge(self, obs: dict):
        me = obs["self"]
        st = me.get("stats") or {}
        cx, cy = float(me["pos"][0]), float(me["pos"][1])
        cz = float(me["pos"][2]) + float(st.get("height", self.mech_h)) * 0.56
        reach = float(st.get("radius", self.mech_r)) + 1.1
        dx = dy = 0.0
        laser_threat = False
        for pr in obs.get("projectiles") or ():
            if pr.get("kind") == "mortar":
                continue
            pv = pr["vel"]
            v2 = pv[0] * pv[0] + pv[1] * pv[1] + pv[2] * pv[2]
            if v2 < 1.0:
                continue
            pp = pr["pos"]
            tc = ((cx - pp[0]) * pv[0] + (cy - pp[1]) * pv[1] + (cz - pp[2]) * pv[2]) / v2
            if tc <= 0.0 or tc > 0.7:
                continue
            mxx = pp[0] + pv[0] * tc - cx
            myy = pp[1] + pv[1] * tc - cy
            if math.hypot(mxx, myy) < reach:
                vh = math.hypot(pv[0], pv[1])
                if vh < 1.0:
                    continue
                px, py = -pv[1] / vh, pv[0] / vh
                if px * mxx + py * myy > 0.0:
                    px, py = -px, -py
                dx += px
                dy += py
        for m in obs.get("mechs") or ():
            if m.get("kind") != "mech" or not m.get("charging"):
                continue
            mp = m["pos"]
            to_me = math.atan2(cy - mp[1], cx - mp[0])
            if abs(_ang_diff(float(m["aim"][0]), to_me)) > 0.15:
                continue
            ang = to_me + (PI * 0.5) * self.strafe
            dx += math.cos(ang) * 1.5
            dy += math.sin(ang) * 1.5
            laser_threat = True
        l = math.hypot(dx, dy)
        if l > 0.01:
            return dx / l, dy / l, laser_threat
        return 0.0, 0.0, False

    def _lead(self, muzzle, tp, tv, speed: float, grounded: bool):
        if speed <= 0.0:
            speed = 252.0
        t = 0.0
        mx, my, mz = muzzle
        px = py = pz = 0.0
        for _ in range(4):
            tt = AIM_LATENCY + t
            px = tp[0] + tv[0] * tt
            py = tp[1] + tv[1] * tt
            pz = tp[2] + (0.0 if grounded else tv[2] * tt * 0.5)
            d = math.sqrt((px - mx) ** 2 + (py - my) ** 2 + (pz - mz) ** 2)
            t = max(0.0, d - 3.0) / speed
        return (
            math.atan2(py - my, px - mx),
            math.atan2(pz - mz, math.hypot(px - mx, py - my)),
            (px, py, pz),
        )

    def _odds(self, me: dict, t: _Track, opening: bool) -> float:
        my_w = sum(1 for w in (me.get("weapons") or ()) if w)
        th_w = max(1, len(t.weapons))
        cap_c = lambda c: float(min(c, self.cube_cap))
        busy_me = busy_them = 0.0
        for u in self.tracks.values():
            if u.id == t.id or self.now - u.seen > 2.5:
                continue
            if self.now - u.hit_me < 6.0:
                busy_me = 1.0
            br = math.atan2(u.pos[1] - t.pos[1], u.pos[0] - t.pos[0])
            if abs(_ang_diff(t.aim[0], br)) < 0.2 and math.hypot(u.pos[0] - t.pos[0], u.pos[1] - t.pos[1]) < 160.0:
                busy_them = 1.0
        z = (
            1.5093 * math.log(max(float(me["hp"]), 1.0) / max(t.hp, 1.0))
            + 0.7049 * (cap_c(int(me.get("cubes", 0))) - cap_c(t.cubes)) / 10.0
            + 0.9583 * (my_w - th_w)
            - 0.5592 * (busy_me - busy_them)
        )
        if opening:
            z += 0.0562 + 0.7475 * min(t.dist, 200.0) / 100.0
            to_me = math.atan2(me["pos"][1] - t.pos[1], me["pos"][0] - t.pos[0])
            if abs(_ang_diff(t.aim[0], to_me)) > 1.75:
                z += 0.8235
        return 1.0 / (1.0 + math.exp(-_clamp(z, -20.0, 20.0)))

    # ------------------------------------------------------------------ main decision tick
    def act(self, obs: dict) -> dict:
        self.now = float(obs.get("t", 0.0))
        now = self.now
        self._observe(obs)

        me = obs["self"]
        st = me.get("stats") or {}
        x, y, zf = float(me["pos"][0]), float(me["pos"][1]), float(me["pos"][2])
        vx, vy = float(me["vel"][0]), float(me["vel"][1])
        my_aim = me.get("aim") or [0.0, 0.0]
        hp = float(me.get("hp", 1400.0))
        max_hp = max(1.0, float(me.get("max_hp", 1400.0)))
        hp_frac = hp / max_hp
        energy = float(me.get("energy", 0.0))
        ws = me.get("weapons") or []
        z = obs["zone"]
        alive = int(obs.get("alive", 16))
        p = self.p

        act: dict = {
            "move": [0.0, 0.0],
            "boost": False,
            "jump": False,
            "fire": [False, False],
            "reload": False,
        }

        offer = obs.get("offer")
        if offer and offer.get("choices"):
            act["pick"] = self._pick_upgrade(me, offer)

        _, gun = _has_weapon(ws, "gun")
        _, light = _has_weapon(ws, "lightning")
        _, laser = _has_weapon(ws, "laser")
        late = float(z.get("next_radius", 999.0)) <= 70.0 or alive <= 3

        # ---- target selection & hot-target gating ----------------------------
        seen: list[_Track] = []
        target: _Track | None = None
        hidden: _Track | None = None
        best_score = 1e18
        max_t = float(p.get("max_target", 215.0) or 215.0)
        if p.get("long_laser_range") and laser is not None:
            las_r_cfg = float((laser.get("stats") or {}).get("range", 280.0))
            max_t = max(max_t, min(265.0, las_r_cfg - 12.0))
        hp_w = float(p.get("hp_w", 60.0 / 1400.0) or (60.0 / 1400.0))
        ghost = bool(p.get("ghost"))
        eng_d = float(p["engage_dist"])

        for t in self.tracks.values():
            if now - t.seen > 2.5:
                continue
            t.engage = False
            seen.append(t)
            if t.seen != now:
                t.los = False
                continue
            to_me = math.atan2(y - t.pos[1], x - t.pos[0])
            off = abs(_ang_diff(t.aim[0], to_me))
            aimed = off < 0.22
            if ghost:
                t.engage = (
                    t.dist < eng_d
                    or now - t.hit_me < 4.0
                    or (aimed and t.charging and t.dist < 120.0)
                    or (t.hp < 350.0 and t.dist < 120.0)
                    or alive <= 2
                )
                if self.not_practice and not t.engage:
                    if hp_frac > 0.75 and t.hp < p["ffa_vulture"] * t.max_hp and off > 0.6 and t.dist < 165.0:
                        t.engage = True
                    elif hp_frac > 0.85 and off > 1.75 and t.dist < p["ffa_ambush"]:
                        t.engage = True
                    elif t.los and hp_frac > 0.5 and t.dist < 160.0 and self._odds(me, t, True) >= p["ffa_odds"]:
                        t.engage = True
            else:
                if (
                    t.dist < eng_d
                    or now - t.hit_me < 6.0
                    or late
                    or (t.closing > 3.0 and t.dist < 180.0)
                    or (t.hp < 0.4 * t.max_hp and t.dist < 160.0)
                    or (aimed and t.dist < 190.0)
                ):
                    t.engage = True

            if t.engage and not t.los and t.dist < max_t:
                if hidden is None or t.dist < hidden.dist:
                    hidden = t
            if not t.engage or not t.los or t.dist > max_t:
                continue

            s = t.dist + hp_w * t.hp
            if p["low_bonus"] > 0.0 and t.hp <= 0.3 * t.max_hp:
                s -= p["low_bonus"]
            if p["stick"] > 0.0 and t.id == self.stick_id and now - self.stick_at < 2.0:
                s -= p["stick"]
            if p["backstab"] > 0.0 and self._shows_back(t, x, y):
                s -= p["backstab"]
            if p["cookoff_bonus"] > 0.0 and laser is not None and "mortar" in t.weapons:
                s -= p["cookoff_bonus"]
            if p.get("laser_punish") and (now - t.laser_fired_at) < self.laser_cd_cfg + 0.5:
                s -= 45.0
            if now - t.hit_me < 4.0:
                s -= 40.0
            if t.closing > 3.0:
                s -= 15.0
            if s < best_score:
                best_score = s
                target = t

        if target is not None:
            self.stick_id = target.id
            self.stick_at = now

        foe = target
        if foe is None and p.get("peek"):
            foe = hidden
        if foe is None and p["pursue"] > 0.0 and hidden is not None and hidden.hp < p["pursue"] * hidden.max_hp:
            foe = hidden

        danger = False
        crowd = 0
        for t in seen:
            if t.engage or now - t.hit_me < 4.0:
                danger = True
            if t.seen == now and (t.engage or (t.los and t.dist < 150.0)):
                crowd += 1
        if danger or now - self.last_hurt < 3.0:
            self.last_threat_at = now

        finishing = target is not None and target.dist < 120.0 and (target.hp < 200.0 or target.hp < hp * 0.5)
        outgunned = (
            target is not None
            and "laser" in target.weapons
            and laser is None
            and target.dist > 55.0
            and hp_frac < 0.8
        )
        swamped = bool(p.get("crowd_hide")) and (crowd >= 3 or (crowd == 2 and hp_frac < 0.65) or outgunned)
        if self.not_practice and target is not None and not finishing and self._odds(me, target, False) < p["ffa_odds_flee"]:
            self.odds_flee_until = now + 5.0
        if now < self.odds_flee_until and not finishing:
            swamped = True

        if not self.retreat and ((hp_frac < p["retreat_hp"] and now - self.last_threat_at < 2.0) or swamped):
            self.retreat = True
            self.cover_at = -100.0
        if self.retreat and not swamped and (hp_frac > p["recover_hp"] or (now - self.last_threat_at > 7.0 and hp_frac > 0.55)):
            self.retreat = False

        if p.get("lose_rule"):
            if p.get("smart_lose"):
                near = sum(
                    1 for t in seen
                    if t.seen == now and t.dist < 160.0 and (t.los or now - t.hit_me < 4.0 or t.dist < 75.0)
                )
            else:
                near = sum(1 for t in seen if t.seen == now and t.dist < 160.0)
            losing = (near >= 2 and hp_frac < 0.55) or (near >= 3 and hp_frac < 0.80)
            if target is not None:
                tf = target.hp / max(1.0, target.max_hp)
                if hp_frac < 0.35 and tf > hp_frac + 0.1:
                    losing = True
                if tf < 0.25 and hp_frac > 0.20 and near <= 2:
                    losing = False
            if losing:
                self.lose_at = now
            self.retreat = (now - self.lose_at < 1.5 and self.lose_at > 0.0)
            # Regen-hold innovation: if already safely out of LOS and regen is about to/actively ticking, bank HP
            if p.get("regen_hold") and not self.retreat and hp_frac < 0.78 and not finishing and not late:
                if (now - self.last_hurt) >= (self.regen_delay - 0.8) and (now - self.lose_at) < 4.5:
                    if target is None and self._zone_penalty(z, x, y) == 0.0:
                        self.retreat = True

        # ---- enemy lightning hard-counter (Innovation 1) ---------------------
        close_light: _Track | None = None
        if p.get("anti_lightning") and light is None:
            for t in seen:
                if t.seen == now and "lightning" in t.weapons and t.dist < self.light_range_cfg + 6.0:
                    if close_light is None or t.dist < close_light.dist:
                        close_light = t

        # ---- movement state machine ------------------------------------------
        mx = my = 0.0
        boost = False
        mode = "idle"
        farm: _Track | None = None
        farm_pos = None

        zgx, zgy = self._zone_goal(z, x, y)
        zdist = math.hypot(zgx - x, zgy - y)
        walk_spd = float(st.get("walk_speed", self.walk_speed)) or self.walk_speed
        t_need = zdist * 1.45 / walk_spd + 4.0
        deadline = self._zone_deadline(z, x, y, 8.0)
        zone_must = (not bool(me.get("in_zone", True))) or (now + t_need + 3.0 >= deadline)
        zone_should = now + t_need + 14.0 >= deadline

        esc_ok, emx, emy, eboost, ejump = self._escape(me)
        if esc_ok:
            mx, my, boost = emx, emy, eboost
            if ejump:
                act["jump"] = True
            mode = "escape"
        elif now < self.unstuck_until:
            mx, my = self.unstuck_dir
            mode = "unstuck"
        else:
            ds_ok, dmx, dmy = self._dodge_shell(obs)
            if ds_ok:
                mx, my = dmx, dmy
                boost = energy > 15.0
                mode = "dodge"
            elif zone_must and zdist > 2.0:
                mx, my = self._travel(me, zgx, zgy)
                boost = ((not bool(me.get("in_zone", True))) or now + t_need >= deadline) and energy > 5.0
                mode = "zone"
            elif close_light is not None and not finishing:
                # Smart lightning emergency kite: score 7 escape headings by distance + zone + laser LOS
                dx = x - close_light.pos[0]
                dy = y - close_light.pos[1]
                d = math.hypot(dx, dy)
                if d < 0.1:
                    dx, dy, d = 1.0, 0.0, 1.0
                dx, dy = dx / d, dy / d
                best_k = -1e18
                bx, by = dx, dy
                for rot in (0.0, 0.45, -0.45, 0.9, -0.9, 1.35, -1.35):
                    c, s = math.cos(rot), math.sin(rot)
                    ex, ey = dx * c - dy * s, dx * s + dy * c
                    nx_, ny_ = x + ex * 8.0, y + ey * 8.0
                    if not self.w.line_walkable2(x, y, nx_, ny_):
                        continue
                    sc = 25.0 * math.cos(rot) - self._zone_penalty(z, nx_, ny_)
                    cz = self.w.walk_at(nx_, ny_) + self.mech_h * 0.6
                    for e in seen:
                        if e is not close_light and e.seen == now and e.dist < 170.0:
                            eex, eey, eez = self._eye(e)
                            if self.w.clear(eex, eey, eez, nx_, ny_, cz):
                                sc -= 35.0 if e.charging else 18.0
                    if sc > best_k:
                        best_k = sc
                        bx, by = ex, ey
                mx, my = bx, by
                boost = (close_light.dist < self.light_range_cfg + 1.0) and energy > 15.0
                mode = "light_kite"
            elif self.retreat and not finishing and not late:
                cov_ok, cmx, cmy = self._cover_move(obs, seen)
                if cov_ok:
                    mx, my = cmx, cmy
                    boost = energy > 10.0 and (mx != 0.0 or my != 0.0)
                    mode = "cover"
                elif target is not None:
                    mx, my = self._fight_move(obs, target, seen, 1.0)
                    mode = "cornered"
                else:
                    mx, my = self._travel(me, zgx, zgy)
                    if self.npc_hurt > 0.0 and now - self.npc_hurt < 3.0 and mx == 0.0 and my == 0.0:
                        side = 1.0 if (now % 3.0) > 1.5 else -1.0
                        mx, my = -math.sin(self.npc_bearing) * side, math.cos(self.npc_bearing) * side
                    mode = "flee"
            elif target is None and now - self.last_hurt < 2.5 and not late and ghost:
                hb_ok, hmx, hmy = self._hide_from_bearing(obs, seen)
                if hb_ok:
                    mx, my = hmx, hmy
                    boost = energy > 30.0 and (mx != 0.0 or my != 0.0)
                    mode = "cover"
            elif foe is not None:
                gun_r = float((gun.get("stats") or {}).get("range", 180.0)) if gun else 0.0
                las_r = float((laser.get("stats") or {}).get("range", 200.0)) if laser else 0.0
                las_ch = float((laser.get("stats") or {}).get("charge", 1.4)) if laser else 1.4
                lig_r = float((light.get("stats") or {}).get("range", 45.0)) if light else 0.0
                lig_e = float((light.get("stats") or {}).get("energy", 3.0)) if light else 3.0

                ready = (gun is not None and gun.get("ammo", 0) > 0 and gun.get("reload", 0.0) <= 0.25 and foe.dist <= gun_r - 10.0)
                hot = (laser is not None and laser.get("charge", 0.0) >= las_ch - 0.3 and foe.dist <= las_r - 5.0)
                if hot or (light is not None and foe.dist <= lig_r + 6.0 and energy >= lig_e * 3.0):
                    ready = True
                if not p.get("peek") and (light is not None or laser is not None):
                    if p.get("dead_window_duck") and light is None:
                        gun_dead = (gun is None) or (gun.get("reload", 0.0) > 0.35) or (gun.get("ammo", 0) <= 0)
                        las_dead = (laser is None) or (laser.get("cooldown", 0.0) > 0.25 and laser.get("charge", 0.0) <= 0.0)
                        if not (gun_dead and las_dead):
                            ready = True
                    else:
                        ready = True
                want_los = 1.0 if ready else -1.0

                # Laser-duck (Opening Peek + Innovation 2 Hunt laser duck!)
                duck_ring = False
                if (p.get("peek") or (p.get("hunt_laser_duck") and not finishing)) and not hot:
                    for t in seen:
                        if t.seen == now and t.charging and t.los:
                            if abs(_ang_diff(t.aim[0], math.atan2(y - t.pos[1], x - t.pos[0]))) < 0.28:
                                want_los = -1.6
                                duck_ring = True
                                break

                fin_r = float(p.get("finish", 0.0) or 0.0)
                fin_hp = float(p.get("finish_hp", 0.38) or 0.38)
                if fin_r > 0.0 and foe.hp < fin_hp * foe.max_hp and hp_frac > 0.42 and crowd <= 2:
                    k_gr, k_lr, k_lg = p["gun_range"], p["laser_range"], p["light_range"]
                    p["gun_range"] = p["laser_range"] = p["light_range"] = fin_r
                    mx, my = self._fight_move(obs, foe, seen, want_los, extra_ring=duck_ring)
                    p["gun_range"], p["laser_range"], p["light_range"] = k_gr, k_lr, k_lg
                    if p.get("finish_rush") and foe.dist > 2.0 * fin_r and energy > 35.0 and (laser is None or laser.get("charge", 0.0) <= 0.0):
                        boost = True
                else:
                    mx, my = self._fight_move(obs, foe, seen, want_los, extra_ring=duck_ring)

                if light is not None and foe.dist > 50.0 and energy > 55.0 and want_los > 0.0:
                    boost = True
                if p.get("combat_boost") and light is None and energy > 52.0 and (mx != 0.0 or my != 0.0):
                    boost = True
                mode = "fight"

                # Mid-fight cube scoop (with rooftop dz & reachability bug FIXED!)
                fl = float(p.get("fight_loot", 0.0) or 0.0)
                if fl > 0.0:
                    r = fl * (0.57 if hp_frac <= 0.5 else 1.0)
                    bc = None
                    fix_dz = bool(p.get("fight_loot_fix", True))
                    for c in self.cubes.values():
                        if fix_dz and abs(c.pos[2] - zf) > 3.6:
                            continue
                        d = math.hypot(c.pos[0] - x, c.pos[1] - y)
                        if d < r:
                            # Don't walk straight into a lightning carrier for a cube
                            if p.get("anti_lightning") and light is None:
                                too_hot = any(
                                    e.seen == now and "lightning" in e.weapons
                                    and math.hypot(e.pos[0] - c.pos[0], e.pos[1] - c.pos[1]) < self.light_range_cfg + 4.0
                                    for e in seen
                                )
                                if too_hot:
                                    continue
                            r = d
                            bc = c.pos
                    if bc is not None:
                        mx, my = self._travel(me, bc[0], bc[1])
                        mode = "fight:cube"
            elif zone_should and zdist > 2.0:
                mx, my = self._travel(me, zgx, zgy)
                mode = "zone"
            else:
                lc = self._choose_loot(obs, hp_frac, danger)
                if lc is not None:
                    lkind, lid, lpos, _ = lc
                    mode = "loot:" + lkind
                    if lkind == "npc":
                        nt = self.npcs.get(lid)
                        if nt is not None and now - nt.seen < 1.0 and nt.los and nt.dist < 75.0:
                            farm = nt
                            mx, my = self._fight_move(obs, nt, seen, 1.0)
                        else:
                            mx, my = self._travel(me, lpos[0], lpos[1])
                    elif lkind == "crate":
                        d = math.hypot(lpos[0] - x, lpos[1] - y)
                        cp = (lpos[0], lpos[1], lpos[2] + self.crate_h * 0.5)
                        mh = float(st.get("muzzle_height", self.muzzle_h))
                        if d < 50.0 and self.w.clear(x, y, zf + mh, cp[0], cp[1], cp[2]):
                            farm_pos = cp
                            if d < 12.0:
                                mx, my = (x - lpos[0]) / max(d, 0.1), (y - lpos[1]) / max(d, 0.1)
                        else:
                            mx, my = self._travel(me, lpos[0], lpos[1])
                    else:
                        mx, my = self._travel(me, lpos[0], lpos[1])
                        if lkind == "drop" and math.hypot(lpos[0] - x, lpos[1] - y) < 2.5:
                            mx = my = 0.0
                elif p.get("roof_laser_grab") and laser is None and not danger and not late:
                    rg = self._roof_laser_grab(me, z)
                    if rg is not None:
                        mx, my, boost, rj = rg
                        if rj:
                            act["jump"] = True
                        mode = "roof_grab"
                    elif zdist > 3.0 and (not ghost or float(z.get("next_radius", 999.0)) <= 30.0):
                        mx, my = self._travel(me, zgx, zgy)
                        mode = "zone-walk"
                    elif ghost:
                        hx, hy, hok = self._home(obs)
                        if hok and math.hypot(hx - x, hy - y) > 3.0:
                            mx, my = self._travel(me, hx, hy)
                            if not danger and now - self.last_hurt > 6.0:
                                q = min(1.0, max(0.2, (self.step_speed - 0.4) / walk_spd))
                                mx, my = mx * q, my * q
                            mode = "home"
                elif zdist > 3.0 and (not ghost or float(z.get("next_radius", 999.0)) <= 30.0):
                    mx, my = self._travel(me, zgx, zgy)
                    mode = "zone-walk"
                elif ghost:
                    hx, hy, hok = self._home(obs)
                    if hok and math.hypot(hx - x, hy - y) > 3.0:
                        mx, my = self._travel(me, hx, hy)
                        if not danger and now - self.last_hurt > 6.0:
                            q = min(1.0, max(0.2, (self.step_speed - 0.4) / walk_spd))
                            mx, my = mx * q, my * q
                        mode = "home"

        if p.get("dodge") and mode not in ("unstuck", "escape"):
            ddx, ddy, lz = self._dodge(obs)
            if ddx != 0.0 or ddy != 0.0:
                mx = mx * 0.4 + ddx * 0.9
                my = my * 0.4 + ddy * 0.9
                l = math.hypot(mx, my)
                if l > 1.0:
                    mx, my = mx / l, my / l
                if lz and energy > 25.0:
                    boost = True
                if p.get("combat_boost") and light is None and energy > 28.0:
                    boost = True

        # Stuck detection
        if mode == "escape":
            self.stuck_since = -1.0
        elif (mx != 0.0 or my != 0.0) and math.hypot(vx, vy) < 1.2 and bool(me.get("grounded", True)):
            if self.stuck_since < 0.0:
                self.stuck_since = now
            elif now - self.stuck_since > 0.7:
                a = self.rng.random() * TAU
                self.unstuck_dir = (math.cos(a), math.sin(a))
                self.unstuck_until = now + 0.5
                self.stuck_since = -1.0
                self.path = []
                act["jump"] = True
        else:
            self.stuck_since = -1.0

        # ---- fire control & torso aim ----------------------------------------
        mh = float(st.get("muzzle_height", self.muzzle_h))
        muzzle = (x + vx * AIM_LATENCY, y + vy * AIM_LATENCY, zf + mh)
        aim = [float(my_aim[0]), 0.0]
        have_aim = False
        tp = tv = (0.0, 0.0, 0.0)
        tr = th = 1.0
        shootable = False
        is_mech = False
        defend = False

        if target is None and self.npc_hurt > 0.0 and now - self.npc_hurt < 3.0:
            worst = None
            best_off = 0.7
            for n in self.npcs.values():
                if now - n.seen > 0.5 or not n.los or n.dist > 150.0:
                    continue
                off = 0.0 if (now - n.hit_me < 3.0) else abs(_ang_diff(math.atan2(n.pos[1] - y, n.pos[0] - x), self.npc_bearing))
                if off < best_off:
                    best_off = off
                    worst = n
            if worst is not None:
                farm, farm_pos, defend = worst, None, True

        if target is not None:
            sc = self._scale(target.cubes)
            tr, th = self.mech_r * sc, self.mech_h * sc
            tp = (target.pos[0], target.pos[1], target.pos[2] + th * 0.5)
            tv = target.vel
            if not self.w.clear(muzzle[0], muzzle[1], muzzle[2], tp[0], tp[1], tp[2]):
                tp = (target.pos[0], target.pos[1], target.pos[2] + th * 0.85)
            shootable = True
            is_mech = True
        elif farm is not None:
            tr, th = self.npc_r, self.npc_h
            tp = (farm.pos[0], farm.pos[1], farm.pos[2] + th * 0.5)
            tv = farm.vel
            shootable = True
        elif farm_pos is not None:
            tr, th = self.crate_r, self.crate_h
            tp = farm_pos
            tv = (0.0, 0.0, 0.0)
            shootable = True

        if not is_mech and target is None and (self.retreat or hp_frac < 0.5) and not defend:
            shootable = False

        if shootable:
            dist = math.hypot(tp[0] - x, tp[1] - y)
            grounded = abs(tv[2]) < 0.5
            smart_fire = bool(p.get("smart_fire"))
            gy = gp = 0.0
            gun_ok = False
            lead_clear = True
            if gun is not None:
                gst = gun.get("stats") or {}
                gy, gp, lpt = self._lead(muzzle, tp, tv, float(gst.get("speed", 252.0)), grounded)
                gun_ok = dist <= float(gst.get("range", 180.0)) * 0.96
                if smart_fire and gun_ok and dist > 25.0:
                    # Don't waste rounds shooting into a wall when enemy ducks behind a corner
                    lead_clear = self.w.clear(muzzle[0], muzzle[1], muzzle[2], lpt[0], lpt[1], lpt[2])

            lat_h = AIM_LATENCY + self.tick_s
            dp = (tp[0] + tv[0] * lat_h, tp[1] + tv[1] * lat_h, tp[2])
            hy = math.atan2(dp[1] - muzzle[1], dp[0] - muzzle[0])
            hp_a = math.atan2(dp[2] - muzzle[2], math.hypot(dp[0] - muzzle[0], dp[1] - muzzle[1]))
            aim = [gy, gp] if gun is not None else [hy, hp_a]
            have_aim = True

            tol_y = math.atan2(tr * 0.75, max(dist, 1.0))
            tol_p = math.atan2(th * 0.40, max(dist, 1.0))
            turn_r = float(st.get("turn_rate", 3.2)) * self.tick_s
            pitch_r = float(st.get("pitch_rate", 2.5)) * self.tick_s

            def _slew(wy: float, wp: float) -> bool:
                ey = max(0.0, abs(_ang_diff(wy, float(my_aim[0]))) - turn_r)
                ep = max(0.0, abs(wp - float(my_aim[1])) - pitch_r)
                return ey < tol_y and ep < tol_p

            for i, w_s in enumerate(ws[:2]):
                if not w_s:
                    continue
                wk = w_s.get("kind")
                wst = w_s.get("stats") or {}
                if wk == "gun":
                    if gun_ok and lead_clear and w_s.get("ammo", 0) > 0 and w_s.get("reload", 0.0) <= 0.0 and _slew(gy, gp):
                        act["fire"][i] = True
                elif wk == "lightning":
                    cone = math.radians(float(wst.get("cone_deg", 25.0)))
                    if (
                        dist < float(wst.get("range", 45.0)) - 1.5
                        and abs(_ang_diff(hy, float(my_aim[0]))) < cone * 0.5 - 0.05
                        and energy >= float(wst.get("energy", 3.0))
                    ):
                        act["fire"][i] = True
                elif wk == "laser":
                    if not is_mech or dist > float(wst.get("range", 200.0)) * 0.97:
                        continue
                    full = float(wst.get("charge", 1.4))
                    chg = float(w_s.get("charge", 0.0))
                    min_ch = float(wst.get("min_charge", 0.3))
                    if p.get("lethal") and chg >= min_ch and chg < full - 0.051:
                        min_f = float(wst.get("min_frac", 0.35))
                        dmg = (
                            float(wst.get("damage", 315.0))
                            * (min_f + (1.0 - min_f) * chg / max(0.01, full))
                            * (1.0 + self.dmg_per_cube * min(int(me.get("cubes", 0)), self.cube_cap))
                        )
                        if "mortar" in target.weapons:
                            dmg *= 1.0 + float(wst.get("cookoff", 0.6))
                        if (p["backstab"] > 0.0 or smart_fire) and self._shows_back(target, x, y):
                            dmg *= self.rear_mult
                        lk = float(p.get("lethal_k", 0.80) or 0.80)
                        if (
                            dmg * lk >= target.hp
                            and abs(_ang_diff(hy, float(my_aim[0]))) < tol_y * 0.9
                            and abs(hp_a - float(my_aim[1])) < tol_p
                        ):
                            aim = [hy, hp_a]
                            act["fire"][i] = False
                            continue
                    if chg < full - 0.051:
                        act["fire"][i] = True
                        # Innovation 6: delay hitscan aim takeover until 0.35s before release so gun stays accurate
                        snap_t = (full - 0.35) if smart_fire else (full * 0.45)
                        if chg > snap_t:
                            aim = [hy, hp_a]
                    else:
                        aim = [hy, hp_a]
                        ey = abs(_ang_diff(hy, float(my_aim[0])))
                        ep = abs(hp_a - float(my_aim[1]))
                        act["fire"][i] = not (ey < tol_y * 0.9 and ep < tol_p)

        # Pre-charge laser while peeking / closing on occluded foe
        if target is None and foe is not None:
            for i, w_s in enumerate(ws[:2]):
                if w_s and w_s.get("kind") == "laser":
                    wst = w_s.get("stats") or {}
                    if (
                        w_s.get("cooldown", 0.0) <= 0.05
                        and foe.dist < float(wst.get("range", 200.0))
                        and w_s.get("charge", 0.0) < float(wst.get("charge", 1.4)) + float(wst.get("hold_s", 1.5)) - 0.35
                    ):
                        act["fire"][i] = True

        # Keep front armor pointed at closest threat / unseen sound / beam when not shooting
        if not have_aim:
            watch = None
            for t in seen:
                if t.engage or now - t.hit_me < 6.0:
                    if watch is None or t.dist < watch.dist:
                        watch = t
            if watch is not None:
                aim[0] = math.atan2(watch.pos[1] - y, watch.pos[0] - x)
            elif self.npc_hurt > 0.0 and now - self.npc_hurt < 2.5:
                aim[0] = self.npc_bearing
            elif now - self.last_hurt < 2.5:
                aim[0] = self.hurt_bearing
            elif p.get("sensor_awareness") and now - self.sensor_at < 2.0:
                aim[0] = self.sensor_bearing
            elif mx != 0.0 or my != 0.0:
                aim[0] = math.atan2(my, mx) + 1.15 * math.sin(now * 1.3)
            else:
                aim[0] = float(my_aim[0]) + 0.35
            aim[1] = 0.0

        min_p = float(st.get("min_pitch", self.min_pitch))
        max_p = float(st.get("max_pitch", self.max_pitch))
        aim[1] = _clamp(aim[1], min_p, max_p)
        act["aim"] = aim
        self.last_aim = aim

        if gun is not None and gun.get("reload", 0.0) <= 0.0:
            mag = int((gun.get("stats") or {}).get("mag", 12))
            if gun.get("ammo", 0) < mag:
                if target is None and farm is None and farm_pos is None:
                    if gun.get("ammo", 0) <= mag * 0.6 or now - self.last_threat_at > 3.0:
                        act["reload"] = True

        # Ground weapon pickup / swap
        slot1_kind = ws[1]["kind"] if (len(ws) > 1 and ws[1] is not None) else ""
        for pk in obs.get("pickups") or ():
            pp = pk["pos"]
            if math.hypot(pp[0] - x, pp[1] - y) > self.pickup_r - 0.3 or abs(pp[2] - zf) > 3.6:
                continue
            if not self._want_pickup(me, pk.get("kind", "")):
                continue
            if slot1_kind and len(ws) > 0 and ws[0] is not None:
                if slot1_kind == "laser" and ws[1].get("charge", 0.0) > 0.0:
                    break
                act["drop"] = 1
            act["take"] = int(pk["id"])
            break

        act["move"] = [mx, my]
        act["boost"] = bool(boost and (mx != 0.0 or my != 0.0))
        return act
