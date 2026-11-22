"""Survival-first decision core.

Priority order: stay in the zone > avoid being found > keep HP > take free
economy > fight only when cornered. Torso facing is independent of leg
movement, so we can retreat while keeping our front arc toward the threat.
"""
from __future__ import annotations

import math
import os
import random

from combat import Combat, clamp, wrap, size_scale, target_center
from cover import find_cover, find_quick_cover, find_isolate_spot
from econ import choose_take, held_kinds, loot_goal, pick_upgrade, seek_goal
from intel import Intel
from nav import Planner, safe_heading
from params import load
from roof import RoofModel
from world import NullWorld, World
from zone import ZoneModel, current_circle, outside_amount

TAU = math.tau


class Brain:
    def __init__(self, hello, params=None):
        # load() also honours BOT_PARAMS, which is how local A/B variants are
        # injected into a protocol-speaking child process.
        self.p = load(params)
        self.intel_enabled = bool(self.p.get("intel_enabled", True))
        self.seed = int(hello.get("seed", 0))
        self.rng = random.Random(self.seed)
        self.slot = int(hello.get("slot", 0))
        cfg = hello.get("config", {})
        self.cfg = cfg
        md = hello.get("map", {}).get("dir") or ""
        if not os.path.isdir(os.path.join(md, "v2")):
            md = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arena")
        if not os.path.isdir(os.path.join(md, "v2")):
            md = "/arena"
        try:
            self.world = World(md, cfg=cfg)
        except Exception as exc:  # never let a missing map turn us into a sitting target
            import sys
            print("map unavailable (%s): running without arena geometry" % exc,
                  file=sys.stderr, flush=True)
            self.world = NullWorld(cfg)
        self.nav = Planner(self.world)
        self.zone = ZoneModel(cfg, self.seed)
        self.roof = RoofModel(self.world, cfg)
        self.intel = Intel(hello, self.world, self.p)
        self.combat = Combat(self.world, self.p, cfg)
        self.memory_s = float(cfg.get("vision", {}).get("memory_s", 5.0))
        self.vision_range = float(cfg.get("vision", {}).get("range", 200.0))
        self.near_range = float(cfg.get("vision", {}).get("near_range", 45.0))
        self.walk_speed = float(cfg.get("mech", {}).get("walk_speed", 11.7))
        self.step_speed = float(cfg.get("sound", {}).get("step_speed", 5.0))
        self.max_pitch = float(cfg.get("mech", {}).get("max_pitch", 1.3))
        self.min_pitch = float(cfg.get("mech", {}).get("min_pitch", -0.7))

        self.enemies = {}          # id -> {pos, vel, t, hp, weapons, charging, aim}
        self.last_t = -1.0
        self.last_pos = None
        self.path = []
        self.path_goal = None
        self.path_t = -1e9
        self.stuck_t = 0.0
        self.recent_damage = 0.0
        self.damage_bearings = []
        self.sound_points = []
        self.sound_pressure = 0.0
        self.sound_bearing = None
        self.sectors = []
        self.last_hp = 1400.0
        self.spotted = False
        self.last_fire_t = -1e9
        self.fire_count = 0
        self.escape_dir = None
        self.escape_until = -1.0
        self.last_reach = 13.0
        self.flee_dir = None
        self.flee_until = -1.0
        self.pos_hist = []
        self.cover_cache = None
        self.cover_cache_t = -1e9
        self.last_damage_t = -1e9
        self.last_hit_t = -1e9
        self.dealt_recent = 0.0
        self.taken_recent = 0.0
        self.press = False
        self.disengage = False
        self.kill_loot = None
        self.kite_dir = None
        self.kite_until = -1.0
        self._break_dir = None
        self._break_t = -1e9
        self.strafe_sign = 1.0
        self.strafe_flip_t = 0.0
        wcfg = cfg.get("weapons", {}) or {}
        self.cfg_light_range = float((wcfg.get("lightning") or {}).get("range", 45.0))
        self.cfg_gun_mag = int((wcfg.get("gun") or {}).get("mag", 12))
        self.roof_spot = None
        self.roof_climbing = False
        self.roof_climb_t = 0.0
        self.roof_healing = False
        self.roof_hide_cache = None
        self.roof_hide_t = -1e9
        self.roof_peek_cache = None
        self.roof_peek_t = -1e9
        self.known_pickups = {}   # pid -> (kind, [x, y, z], t)
        self.kill_loots = []      # [(x, y, z, t), ...]
        self.tc_healing = False
        self.tc_cov_cache = None
        self.tc_cov_t = -1e9
        self.econ_bl = {}         # obj_key -> expire_t (prevents unreachable-cube freeze!)
        self.econ_track_key = None
        self.econ_track_t = 0.0
        self.iso_cache = None
        self.iso_t = -1e9

    # ------------------------------------------------------------------ state
    def _break_heading(self, x, y, z, visible, t, all_threats=None, cc=None, cr=0.0):
        """Pick the escape heading that hides us from the nearest shooters.

        Distance alone does not stop a squad with shared vision; terrain does.
        Headings are scored by how many of the closest threats lose line of
        sight to the point we would occupy, plus a small bonus for opening
        range.  Cached for kite_cover_cache_s because it costs raycasts.
        """
        if (self._break_dir is not None
                and t - self._break_t < self.p["kite_cover_cache_s"]):
            return self._break_dir
        sb3 = bool(self.p.get("snowball_v3", False))
        eyes = sorted(((e["pos"][0], e["pos"][1],
                        e["pos"][2] + self.world.eye_height
                        * size_scale(e.get("cubes", 0), self.world.size_per_cube))
                       for e in visible),
                      key=lambda q: math.hypot(q[0] - x, q[1] - y))[:2]
        probe = self.p["kite_cover_probe"]
        body = 0.5 * self.world.height
        best, best_score = None, -1e18
        w = self.world
        for k in range(12):
            a = k * TAU / 12.0
            cx, cy = math.cos(a), math.sin(a)
            if self.nav.reach(x, y, z, cx, cy) < 6.0:
                continue
            px, py = x + cx * probe, y + cy * probe
            if sb3:
                if (px < w.minx + 25 or px > w.maxx - 25
                        or py < w.miny + 25 or py > w.maxy - 25):
                    continue
                if cc is not None and cr > 0.0 and math.hypot(px - cc[0], py - cc[1]) > cr * 0.86:
                    continue
            pz = w.ground(px, py)
            hidden = 0
            for ex, ey, ez in eyes:
                if not w.shot_clear((ex, ey, ez), (px, py, pz + body)):
                    hidden += 1
            gain = min((math.hypot(px - ex, py - ey) for ex, ey, _ in eyes),
                       default=0.0)
            score = hidden * 60.0 + gain * 0.35
            if sb3 and all_threats:
                # Don't kite straight into a 3rd/4th idle house bot and wake it up!
                near_any = min((math.hypot(px - q[0], py - q[1]) for q in all_threats), default=120.0)
                if near_any < 48.0:
                    score -= (48.0 - near_any) * 1.8
            if score > best_score:
                best_score, best = score, (cx, cy)
        self._break_dir, self._break_t = best, t
        return best

    def _update(self, obs):
        me = obs["self"]
        t = float(obs["t"])
        dt = 0.1 if self.last_t < 0 else max(0.05, min(0.5, t - self.last_t))
        self.last_t = t
        self.recent_damage = max(0.0, self.recent_damage - dt * 0.55)
        # Rolling HP exchange, used to decide whether we are winning the fight
        # we are in.  Decays toward neutral so old trades stop mattering.
        self.dealt_recent = max(0.0, self.dealt_recent - dt * 55.0)
        self.taken_recent = max(0.0, self.taken_recent - dt * 55.0)

        my_id = me.get("id")
        kill_ids = []
        for e in obs.get("events", []):
            ty = e.get("type")
            if ty == "damaged":
                self.recent_damage += 1.0
                self.last_damage_t = t
                self.taken_recent += float(e.get("amount", 0) or 0.0)
                b = e.get("bearing")
                if b is not None:
                    self.damage_bearings.append((b, t, float(e.get("amount", 0)), e.get("by")))
            elif ty == "kill":
                tid = e.get("target")
                if tid is not None and tid != my_id:
                    kill_ids.append(tid)
                    if self.p.get("kill_snowball_v1", False):
                        # Purge damage bearings from the mech we just killed!
                        self.damage_bearings = [d for d in self.damage_bearings if d[3] != tid]
                        # If no other live mech damaged us recently, stop fleeing the corpse so we scoop its 3 cubes!
                        if not any(t - d[1] < 3.0 for d in self.damage_bearings):
                            self.kite_until = -1.0
            elif ty == "hit":
                # confirmation that one of our shots landed
                tgt = e.get("target")
                if tgt is None or tgt != my_id:
                    self.dealt_recent += float(e.get("amount", 0) or 0.0)
                    self.last_hit_t = t
            elif ty == "took":
                self.known_pickups.pop(e.get("id"), None)
            elif ty == "take_failed" and e.get("reason") == "gone":
                self.known_pickups.pop(e.get("id"), None)
        self.damage_bearings = [d for d in self.damage_bearings if t - d[1] < 6.0]
        # resolve fresh kill positions after the belief layer has seen the obs
        if getattr(self, "_kill_ids", None) and self.intel_enabled:
            for tid in self._kill_ids:
                b = self.intel.beliefs.get(tid)
                if b is not None and b.pos is not None:
                    self.kill_loot = (b.pos[0], b.pos[1], t)
                    self.kill_loots.append((b.pos[0], b.pos[1], b.pos[2], t))
        # keep persistent memory of seen weapon pickups (they never despawn unless taken)
        seen_pids = set()
        mx0, my0, mz0 = me["pos"]
        for pk in obs.get("pickups", []):
            pid = pk.get("id")
            if pid is not None:
                seen_pids.add(pid)
                self.known_pickups[pid] = (pk["kind"], list(pk["pos"]), t)
        for pid, (_, ppos, pt) in list(self.known_pickups.items()):
            if pid in seen_pids:
                continue
            if t - pt > 90.0:
                del self.known_pickups[pid]
            elif math.hypot(ppos[0] - mx0, ppos[1] - my0) < 22.0 and abs(ppos[2] - mz0) < 5.0:
                if self.world.shot_clear((mx0, my0, mz0 + self.world.eye_height),
                                         (ppos[0], ppos[1], ppos[2] + 0.5), step=4.0):
                    del self.known_pickups[pid]
        self.kill_loots = [
            kl for kl in self.kill_loots
            if t - kl[3] < 12.0 and math.hypot(kl[0] - mx0, kl[1] - my0) > 3.5
        ]

        self._kill_ids = kill_ids
        if self.intel_enabled:
            # D1: `obs.mechs` positions are already the server's real current
            # positions for `vision.memory_s`; do not dead-reckon them.
            # D2: sounds/beams/events become uncertain bearing sectors, not
            # exact pseudo-positions.
            self.intel.update(obs)
            self.sectors = self.intel.sector_contacts()
            self.sound_pressure = self.intel.sound_pressure()
            self.sound_bearing = self.intel.sound_bearing()
        else:
            # Legacy path, retained unchanged for paired ablations.
            for m in obs.get("mechs", []):
                if m.get("kind") != "mech":
                    continue
                self.enemies[int(m["id"])] = {
                    "pos": list(m["pos"]), "vel": list(m.get("vel", [0, 0, 0])),
                    "t": t, "hp": m.get("hp", 1400), "cubes": m.get("cubes", 0),
                    "weapons": m.get("weapons", []), "charging": m.get("charging", False),
                    "aim": list(m.get("aim", [0, 0])),
                }
            for k in list(self.enemies):
                if t - self.enemies[k]["t"] > self.memory_s:
                    del self.enemies[k]

            pts = []
            for s in obs.get("sounds", []):
                kind = s.get("kind", "")
                if kind in ("step", "boost", "jet", "reload", "npc_gun", "crate", "drop"):
                    continue
                b = s.get("bearing")
                if b is None:
                    continue
                cat = s.get("dist")
                dist = 55.0 if cat == "near" else (135.0 if cat == "mid" else 210.0)
                pts.append((me["pos"][0] + math.cos(b) * dist,
                            me["pos"][1] + math.sin(b) * dist, t, kind))
            self.sound_points = [p for p in self.sound_points if t - p[2] < 4.0] + pts
            self.sectors = []
            self.sound_pressure = 0.0
            self.sound_bearing = None

        if self.last_pos is not None:
            moved = math.hypot(me["pos"][0] - self.last_pos[0], me["pos"][1] - self.last_pos[1])
            if moved < 0.35:
                self.stuck_t += dt
            else:
                self.stuck_t = max(0.0, self.stuck_t - dt * 1.5)
        self.last_pos = list(me["pos"])
        self.last_hp = me["hp"]
        self.pos_hist.append((t, me["pos"][0], me["pos"][1]))
        if len(self.pos_hist) > 40:
            self.pos_hist = self.pos_hist[-40:]
        return me, t, dt

    def _threats(self, obs, me, t):
        """Protocol-current enemy positions only, or legacy pseudo-points."""
        if self.intel_enabled:
            return self.intel.threat_points()
        out = []
        x, y = me["pos"][0], me["pos"][1]
        for k, e in self.enemies.items():
            age = t - e["t"]
            px, py = e["pos"][0], e["pos"][1]
            # legacy dead reckoning while out of sight
            px += e["vel"][0] * min(age, 2.0)
            py += e["vel"][1] * min(age, 2.0)
            out.append((px, py))
        for sp in self.sound_points:
            if t - sp[2] < 3.0:
                out.append((sp[0], sp[1]))
        for d in self.damage_bearings:
            b, bt = d[0], d[1]
            if t - bt < 3.0:
                out.append((x + math.cos(b) * 60.0, y + math.sin(b) * 60.0))
        return out

    def _visible_enemies(self, obs, me, t):
        if self.intel_enabled:
            return self.intel.visible_dicts()
        out = []
        for k, e in self.enemies.items():
            if t - e["t"] <= 0.25:
                d = dict(e)
                d["id"] = k
                out.append(d)
        return out

    # ------------------------------------------------------------------ decide
    def act(self, obs):
        p = self.p
        me, t, dt = self._update(obs)
        x, y, z = me["pos"]
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        threats = self._threats(obs, me, t)
        visible = self._visible_enemies(obs, me, t)
        close = min((math.hypot(q[0] - x, q[1] - y) for q in threats), default=1e6)
        mclose = min((math.hypot(e["pos"][0] - x, e["pos"][1] - y) for e in visible), default=1e6)
        npcs = [m for m in obs.get("mechs", []) if m.get("kind") == "npc"]
        npc_close = min((math.hypot(m["pos"][0] - x, m["pos"][1] - y) for m in npcs),
                        default=1e6)
        npc_near = min(npcs, key=lambda m: math.hypot(m["pos"][0] - x, m["pos"][1] - y)) \
            if npcs else None
        # net displacement over the last 2.5 s: catches orbiting a hide spot,
        # which a per-decision "stuck" check cannot see.
        net = 0.0
        for q in self.pos_hist:
            if t - q[0] >= 2.0:
                net = math.hypot(x - q[1], y - q[2])
                break

        # adaptive pressure: more hunters -> more conservative
        adapt = 1.0
        if p["adapt"]:
            adapt += min(1.2, self.recent_damage * 0.18)
            if self.intel_enabled:
                adapt += min(0.8, self.sound_pressure * p["sound_pressure_gain"])
            if t > p["late_survival_t"]:
                adapt += 0.5

        # ---- situational controller -------------------------------------
        if p["trade_adapt"]:
            ratio = self.dealt_recent / max(1.0, self.taken_recent)
            self.press = (ratio > p["trade_press_ratio"]
                          and hp_frac > p["trade_press_hp"])
            self.disengage = (ratio < p["trade_flee_ratio"]
                              or hp_frac < p["trade_flee_hp"])
        else:
            self.press = self.disengage = False

        # ---- goal -------------------------------------------------------
        (ccx, ccy), cr = current_circle(obs["zone"], t)
        goal_threats = threats + [(m["pos"][0], m["pos"][1]) for m in npcs]
        goal, emergency = self.zone.choose_goal(
            obs, me, self.world, goal_threats, p, t,
            sectors=self.sectors if self.intel_enabled else None)
        out_by = outside_amount(x, y, (ccx, ccy), cr)
        if out_by > -0.12 * cr:
            emergency = True
            goal = (ccx, ccy)

        # ---- drone aggro break (or NPC drone farming in snowball_v1) -----
        sb = bool(p.get("snowball_v1", False))
        wv2 = bool(p.get("weapons_v2", False)) or sb or bool(p.get("combat_v2", False))
        w1 = me["weapons"][1] if len(me.get("weapons") or []) > 1 else None
        w1_kind = w1.get("kind") if w1 else None
        my_light_r = float((w1 or {}).get("stats", {}).get("range", self.cfg_light_range)) if w1_kind == "lightning" else 0.0
        my_muzzle_z = z + me.get("stats", {}).get("muzzle_height", self.world.muzzle_height)
        sb_los_mechs = 0
        if sb and visible:
            for e in visible:
                if math.hypot(e["pos"][0] - x, e["pos"][1] - y) < 120.0:
                    if self.world.shot_clear((x, y, my_muzzle_z), target_center(e, self.world.size_per_cube, self.world.height, p["aim_height_frac"])):
                        sb_los_mechs += 1
        sb_farm_npc = None
        if (sb and p.get("snowball_npc_farm", True) and not emergency
                and npc_near is not None and npc_close < 58.0
                and sb_los_mechs == 0 and mclose > 72.0
                and hp_frac > 0.38 and me.get("cubes", 0) < 15
                and abs(npc_near["pos"][2] - z) < 5.0
                and self.world.shot_clear((x, y, my_muzzle_z),
                                          (npc_near["pos"][0], npc_near["pos"][1], npc_near["pos"][2] + 1.75))):
            sb_farm_npc = npc_near

        # Drones aggro at 45 m, deal 25/s and never lose interest while we
        # orbit a nearby hide spot.  Sprinting out of their 60 m chase leash
        # is quieter (90 m boost sound) than shooting them (320 m gun sound).
        if (sb_farm_npc is None and npc_near is not None and npc_close < p["npc_break_range"]
                and (self.recent_damage > 0.05 or npc_close < 26.0)):
            fx, fy = x - npc_near["pos"][0], y - npc_near["pos"][1]
            fd = math.hypot(fx, fy) or 1.0
            self.flee_dir = (fx / fd, fy / fd)
            self.flee_until = t + p["npc_break_hold_s"]
        if sb_farm_npc is not None:
            self.flee_until = -1.0
        if t < self.flee_until and self.flee_dir is not None and not emergency:
            fx, fy = self.flee_dir
            gx, gy = x + fx * 120.0, y + fy * 120.0
            dd = math.hypot(gx - ccx, gy - ccy)
            lim = cr * 0.82
            if dd > lim and dd > 0.01:
                gx = ccx + (gx - ccx) / dd * lim
                gy = ccy + (gy - ccy) / dd * lim
            goal = (gx, gy)

        # ---- early roam / economy ----------------------------------------
        roaming = (t < p["roam_until"] and not emergency
                   and not (t < self.flee_until))
        goal_kind = "zone"
        sb_econ_lock = False
        sb_boost = False
        sb_farm_crate = None
        sb3 = bool(p.get("snowball_v3", False))
        sb_econ_key = None
        if sb and not emergency and not (t < self.flee_until):
            # 1) Aggressive cube grab (instant +56 HP heal + 4% dmg + upgrade!)
            best_cube = None
            best_cd = 1e9
            best_cid = None
            cube_lim = p.get("snowball_cube_r", 50.0) if sb_los_mechs == 0 else 22.0
            for c in obs.get("cubes", []):
                ckey = ("cube", c.get("id"))
                if sb3 and self.econ_bl.get(ckey, -1e9) > t:
                    continue
                cx, cy, cz = c["pos"]
                if abs(cz - z) > 4.5:
                    continue
                cd = math.hypot(cx - x, cy - y)
                if cd > cube_lim or cd >= best_cd:
                    continue
                if math.hypot(cx - ccx, cy - ccy) > cr * 0.90:
                    continue
                near_e = min((math.hypot(cx - e["pos"][0], cy - e["pos"][1]) for e in visible), default=999.0)
                if near_e < 16.0 or (hp_frac < 0.35 and near_e < 32.0):
                    continue
                if self.world.blocked(cx, cy, self.world.ground(cx, cy)):
                    continue
                best_cd = cd
                best_cube = (cx, cy)
                best_cid = ckey
            if best_cube is not None:
                goal, goal_kind = best_cube, "cube"
                sb_econ_key = best_cid
                sb_econ_lock = (best_cd < 26.0 or sb_los_mechs == 0)
                if best_cd > 10.0 and me.get("energy", 0) > 40.0:
                    sb_boost = True

            # 2) Kill-loot corpse (3 cubes + weapon!)
            sb2 = bool(p.get("snowball_v2", False))
            ks1 = bool(p.get("kill_snowball_v1", False))
            if not sb_econ_lock and self.kill_loots and hp_frac > 0.35 and (sb_los_mechs == 0 or (sb2 and mclose > 30.0)):
                kl_lim = 55.0 if (sb2 and sb_los_mechs > 0) else (105.0 if ks1 else 75.0)
                for kx, ky, kz, kt in reversed(self.kill_loots):
                    if abs(kz - z) > 4.5:
                        continue
                    kd = math.hypot(kx - x, ky - y)
                    if kd > kl_lim or math.hypot(kx - ccx, ky - ccy) > cr * 0.88:
                        continue
                    near_e = min((math.hypot(kx - e["pos"][0], ky - e["pos"][1]) for e in visible), default=999.0)
                    if near_e < (22.0 if ks1 else (24.0 if sb2 else 26.0)):
                        continue
                    if not self.world.blocked(kx, ky, self.world.ground(kx, ky)):
                        goal, goal_kind = (kx, ky), "loot"
                        sb_econ_lock = True
                        if kd > 10.0 and me.get("energy", 0) > 40.0:
                            sb_boost = True
                        break

            # 3) Remembered weapon pickup (secondary empty or strict upgrade!)
            if not sb_econ_lock and p["take_pickups"]:
                pref = p["weapon_pref"]
                cur_rank = pref.index(w1_kind) if (w1_kind and w1_kind in pref) else 99
                held = held_kinds(me)
                best_pk = None
                best_psc = -1e18
                pk_lim = p.get("snowball_pickup_r", 135.0) if sb_los_mechs == 0 else 28.0
                for pid, (pkind, ppos, pt) in self.known_pickups.items():
                    if sb3 and self.econ_bl.get(("pk", pid), -1e9) > t:
                        continue
                    if pkind in held or pkind not in pref:
                        continue
                    prank = pref.index(pkind)
                    if prank >= cur_rank:
                        continue
                    if abs(ppos[2] - z) > 4.5:
                        continue
                    pd = math.hypot(ppos[0] - x, ppos[1] - y)
                    if pd > pk_lim or math.hypot(ppos[0] - ccx, ppos[1] - ccy) > cr * 0.88:
                        continue
                    near_e = min((math.hypot(ppos[0] - e["pos"][0], ppos[1] - e["pos"][1]) for e in visible), default=999.0)
                    if near_e < 28.0:
                        continue
                    if self.world.blocked(ppos[0], ppos[1], self.world.ground(ppos[0], ppos[1])):
                        continue
                    sc = (120.0 - prank * 25.0) - pd * 0.8
                    if sc > best_psc:
                        best_psc = sc
                        best_pk = (ppos[0], ppos[1], pd, ("pk", pid))
                if best_pk is not None and (sb_los_mechs == 0 or (best_pk[2] < 28.0 and hp_frac > 0.45)):
                    goal, goal_kind = (best_pk[0], best_pk[1]), "weapon"
                    sb_econ_key = best_pk[3]
                    sb_econ_lock = (best_pk[2] < 32.0 or w1 is None)
                    if best_pk[2] > 10.0 and me.get("energy", 0) > 45.0:
                        sb_boost = True

            # 4) Safe crate farming when no enemies around
            if (sb_farm_npc is None and p.get("snowball_crate_farm", True)
                    and sb_los_mechs == 0 and mclose > 88.0 and hp_frac > 0.45
                    and (me.get("cubes", 0) < 10 or w1 is None)):
                best_cr = None
                best_crd = 55.0 if sb2 else 48.0
                for cr_it in obs.get("crates", []):
                    cx, cy, cz = cr_it["pos"]
                    if abs(cz - z) > 4.5:
                        continue
                    cd = math.hypot(cx - x, cy - y)
                    if cd < best_crd and self.world.shot_clear((x, y, my_muzzle_z), (cx, cy, cz + 1.2)):
                        best_crd = cd
                        best_cr = cr_it
                sb_farm_crate = best_cr

            # 5) snowball_v2: supply drops, approach visible NPC/crate, active patrol!
            if sb2 and not sb_econ_lock:
                # 5a) Supply drops (FULL HP + FULL ENERGY + 3 CUBES!)
                if p.get("sb2_drop_contest", True):
                    best_dr = None
                    best_drd = 135.0
                    for dr in obs.get("drops", []):
                        if dr.get("lands_in", 99.0) > 16.0:
                            continue
                        dx_d, dy_d, dz_d = dr["pos"]
                        if abs(dz_d - z) > 5.0 or math.hypot(dx_d - ccx, dy_d - ccy) > cr * 0.88:
                            continue
                        dd_d = math.hypot(dx_d - x, dy_d - y)
                        if dd_d >= best_drd:
                            continue
                        near_e = min((math.hypot(dx_d - e["pos"][0], dy_d - e["pos"][1]) for e in visible), default=999.0)
                        if near_e < 26.0 and hp_frac < 0.70:
                            continue
                        if not self.world.blocked(dx_d, dy_d, self.world.ground(dx_d, dy_d)):
                            best_drd = dd_d
                            best_dr = (dx_d, dy_d, dr.get("lands_in", 0.0))
                    if best_dr is not None:
                        goal, goal_kind = (best_dr[0], best_dr[1]), "loot"
                        sb_econ_lock = True
                        if best_drd > 10.0 and best_dr[2] < 8.0 and me.get("energy", 0) > 40.0:
                            sb_boost = True

                # 5b) Approach visible NPC drone (<95m) or crate (<80m) when safe to farm cubes!
                npc_safe_m = 66.0 if ks1 else 82.0
                cube_cap_farm = 15 if ks1 else 12
                if (not sb_econ_lock and sb_los_mechs == 0 and mclose > npc_safe_m
                        and hp_frac > 0.45 and me.get("cubes", 0) < cube_cap_farm):
                    if p.get("snowball_npc_farm", True) and npc_near is not None:
                        nx_d, ny_d, nz_d = npc_near["pos"]
                        if (npc_close < 95.0 and abs(nz_d - z) < 5.0
                                and math.hypot(nx_d - ccx, ny_d - ccy) < cr * 0.88):
                            near_e = min((math.hypot(nx_d - e["pos"][0], ny_d - e["pos"][1]) for e in visible), default=999.0)
                            if near_e > (45.0 if ks1 else 55.0) and npc_close > 26.0:
                                goal, goal_kind = (nx_d, ny_d), "npc"
                                sb_econ_lock = True
                    if not sb_econ_lock and p.get("snowball_crate_farm", True) and (me.get("cubes", 0) < 10 or w1 is None):
                        best_cr2 = None
                        best_cd2 = 80.0
                        for cr_it in obs.get("crates", []):
                            cx, cy, cz = cr_it["pos"]
                            if abs(cz - z) > 5.0 or math.hypot(cx - ccx, cy - ccy) > cr * 0.88:
                                continue
                            cd = math.hypot(cx - x, cy - y)
                            if cd < best_cd2 and cd > 22.0:
                                near_e = min((math.hypot(cx - e["pos"][0], cy - e["pos"][1]) for e in visible), default=999.0)
                                if near_e > (50.0 if ks1 else 60.0):
                                    best_cd2 = cd
                                    best_cr2 = (cx, cy)
                        if best_cr2 is not None:
                            goal, goal_kind = best_cr2, "crate"
                            sb_econ_lock = True

                # 5c) Active full-speed patrol while hungry for secondary weapon or cubes!
                if (not sb_econ_lock and not visible and t < p.get("sb2_patrol_until", 150.0)
                        and (w1 is None or me.get("cubes", 0) < 8)):
                    nc = obs["zone"]["next_center"]
                    nr = obs["zone"]["next_radius"]
                    a = ((self.seed % 360) * math.pi / 180.0) + t * 0.22
                    pr = min(cr * 0.62, max(60.0, nr * 0.72))
                    px_p = nc[0] + math.cos(a) * pr
                    py_p = nc[1] + math.sin(a) * pr
                    if math.hypot(px_p - ccx, py_p - ccy) < cr * 0.80:
                        goal, goal_kind = (px_p, py_p), "patrol"
        elif roaming:
            goal, goal_kind = seek_goal(obs, me, p, self.world, goal_threats, t,
                                        (ccx, ccy), cr, self.seed)
        else:
            # small detours only when safe and early
            if not emergency and close > 55.0 and t < p["late_survival_t"]:
                lg = loot_goal(obs, me, p, self.world, goal_threats, t)
                if lg is not None:
                    goal, goal_kind = lg, "loot"

        # Timeout blacklist for unreachable cubes/pickups (fixes seed 16001 152s freeze!)
        if sb3:
            if sb_econ_key is not None:
                if sb_econ_key == self.econ_track_key:
                    self.econ_track_t += dt
                    if self.econ_track_t > 5.5 or (self.stuck_t > 0.9 and self.econ_track_t > 1.5):
                        self.econ_bl[sb_econ_key] = t + 35.0
                        self.econ_track_key = None
                        self.econ_track_t = 0.0
                        sb_econ_lock = False
                else:
                    self.econ_track_key = sb_econ_key
                    self.econ_track_t = 0.0
            else:
                self.econ_track_key = None
                self.econ_track_t = 0.0

        # ---- hunting ------------------------------------------------------
        # Close on the nearest known enemy and finish it.  This is the opposite
        # of the survival-first default, kept behind a switch because the
        # simulator's squad punishes it while the real squad may not.
        v2 = bool(p.get("combat_v2", False))
        hunting = False
        duel_tgt = None
        duel_want = p["hunt_standoff"]
        duel_los = False
        tgt_has_light = False
        los_threats = 0
        if v2 and visible:
            my_muzzle = (x, y, my_muzzle_z)
            for e in visible:
                ed0 = math.hypot(e["pos"][0] - x, e["pos"][1] - y)
                if ed0 < 165.0 and self.world.shot_clear(my_muzzle, target_center(e, self.world.size_per_cube, self.world.height, p["aim_height_frac"])):
                    los_threats += 1

        sb4 = bool(p.get("snowball_v4", False))
        # In sb4, defer bare-gun hunt in the opening until we equip a secondary
        # (unless an enemy is already wounded < 480 HP); still fire 100% if in LOS!
        gear_defer = (
            sb4 and w1 is None and t < p.get("sb4_gear_until", 38.0)
            and not any((q.get("hp") or 1400.0) <= 480.0 for q in visible)
        )
        if gear_defer and goal_kind == "zone":
            nc = obs["zone"]["next_center"]
            nr = obs["zone"]["next_radius"]
            a = ((self.seed % 360) * math.pi / 180.0) + t * 0.25
            pr = min(cr * 0.62, max(60.0, nr * 0.72))
            px_p = nc[0] + math.cos(a) * pr
            py_p = nc[1] + math.sin(a) * pr
            if math.hypot(px_p - ccx, py_p - ccy) < cr * 0.80:
                goal, goal_kind = (px_p, py_p), "patrol"

        pr1 = bool(p.get("precision_v1", False))
        has_finish = pr1 and any((q.get("hp") or 1400.0) <= 450.0 for q in visible)
        hunt_hp = (0.20 if (v2 or has_finish) else p["hunt_hp"]) * (0.6 if self.press else 1.0)
        if (p["hunt_enabled"] and not emergency and not self.disengage
                and not sb_econ_lock and not gear_defer
                and hp_frac > hunt_hp
                and t < p["hunt_until"] and not (t < self.flee_until)):
            cand = [e for e in visible
                    if math.hypot(e["pos"][0] - x, e["pos"][1] - y) < p["hunt_range"]]
            if cand:
                if v2:
                    def rank(q):
                        hp = q.get("hp")
                        frac = (hp / max(1.0, q.get("max_hp") or 1400.0)
                                if hp is not None else 1.0)
                        atk = 0 if (q.get("last_attack_t") is not None and t - q["last_attack_t"] < 8.0) else 1
                        fin = 0 if (hp is not None and hp <= p["v2_finish_hp"]) else 1
                        return (fin, atk, frac, math.hypot(q["pos"][0] - x, q["pos"][1] - y))
                elif p["hunt_target"] == "weak":
                    # finish the wounded instead of opening a new front
                    def rank(q):
                        hp = q.get("hp")
                        frac = (hp / max(1.0, q.get("max_hp") or 1400.0)
                                if hp is not None else 1.0)
                        return (frac, math.hypot(q["pos"][0] - x, q["pos"][1] - y))
                else:
                    def rank(q):
                        return (0.0, math.hypot(q["pos"][0] - x, q["pos"][1] - y))
                e = min(cand, key=rank)
                duel_tgt = e
                ed = math.hypot(e["pos"][0] - x, e["pos"][1] - y)
                ew = e.get("weapons") or []
                tgt_has_light = "lightning" in ew
                ehp = e.get("hp") or 1400.0
                if v2:
                    if w1_kind == "lightning" and me.get("energy", 0) > 15 and (not tgt_has_light or me["hp"] >= ehp * 0.8):
                        duel_want = min(30.0, my_light_r * 0.68)
                    elif tgt_has_light:
                        duel_want = max(58.0, self.cfg_light_range + 15.0)
                    elif w1_kind == "laser":
                        duel_want = 82.0
                    else:
                        duel_want = 52.0
                    my_muzzle = (x, y, my_muzzle_z)
                    duel_los = self.world.shot_clear(my_muzzle, target_center(e, self.world.size_per_cube, self.world.height, p["aim_height_frac"]))
                    if ed > duel_want or not duel_los:
                        goal, goal_kind = (e["pos"][0], e["pos"][1]), "hunt"
                        hunting = True
                elif sb:
                    # Weapon-aware standoff while preserving HEAD's proven kiting!
                    if w1_kind == "lightning" and me.get("energy", 0) > 18 and (not tgt_has_light or me["hp"] >= ehp * 0.85):
                        duel_want = min(28.0, my_light_r * 0.65)
                    elif tgt_has_light:
                        duel_want = max(58.0, self.cfg_light_range + 14.0)
                    elif sb4 and w1_kind == "laser":
                        duel_want = float(p.get("sb4_laser_standoff", 82.0))
                    else:
                        duel_want = p["hunt_standoff"]
                    if sb4 and w1_kind == "laser":
                        duel_los = self.world.shot_clear((x, y, my_muzzle_z), target_center(e, self.world.size_per_cube, self.world.height, p["aim_height_frac"]))
                        if ed > duel_want or not duel_los:
                            goal, goal_kind = (e["pos"][0], e["pos"][1]), "hunt"
                            hunting = True
                    elif ed > duel_want:
                        goal, goal_kind = (e["pos"][0], e["pos"][1]), "hunt"
                        hunting = True
                elif ed > p["hunt_standoff"]:
                    goal, goal_kind = (e["pos"][0], e["pos"][1]), "hunt"
                    hunting = True

        # ---- collect our own kill ------------------------------------------
        if (p["loot_kill_enabled"] and self.kill_loot is not None
                and not emergency and not hunting and not (t < self.flee_until)
                and t - self.kill_loot[2] < p["loot_kill_window_s"]
                and hp_frac > 0.35 and mclose > p["loot_kill_clear_r"]):
            goal, goal_kind = (self.kill_loot[0], self.kill_loot[1]), "loot"

        # ---- LOS-breaking cover -------------------------------------------
        # Squad vision is shared; distance-hiding fails, occlusion works.
        covered = False
        if (p["cover_enabled"] and not emergency and not (t < self.flee_until)
                and (hp_frac < p["cover_hp"] or self.recent_damage > p["cover_after_hit"])
                and mclose > p["cover_min_enemy"] and t - self.last_damage_t < 20.0):
            if t - self.cover_cache_t > p["cover_cache_s"]:
                eyes = sorted(
                    ((e["pos"][0], e["pos"][1],
                      e["pos"][2] + self.world.eye_height
                      * size_scale(e.get("cubes", 0), self.world.size_per_cube))
                     for e in visible),
                    key=lambda q: math.hypot(q[0] - x, q[1] - y))
                for d in self.damage_bearings[-2:]:
                    b = d[0]
                    tx, ty = x + math.cos(b) * 70.0, y + math.sin(b) * 70.0
                    eyes.append((tx, ty, self.world.ground(tx, ty) + self.world.eye_height))
                if not eyes:
                    eyes = [(q[0], q[1], self.world.ground(q[0], q[1]) + self.world.eye_height)
                            for q in threats[:2]]
                self.cover_cache = find_cover(self.world, x, y, z, eyes,
                                              p["cover_max_r"],
                                              zone_center=(ccx, ccy), zone_radius=cr)
                self.cover_cache_t = t
            if self.cover_cache is not None:
                goal = self.cover_cache
                covered = True

        # ---- kiting ------------------------------------------------------
        # The squad converges on our last known position and needs LOS to
        # shoot.  Boost straight away from the incoming-fire bearings, then
        # go quiet again; they arrive at a position we have already left.
        kiting = False
        recent_hits = [d for d in self.damage_bearings if t - d[1] < 3.0]
        if v2:
            finishing = (duel_tgt is not None
                         and (duel_tgt.get("hp") or 1400.0) <= p["v2_finish_hp"]
                         and hp_frac > 0.22 and duel_los)
            light_danger = (tgt_has_light and w1_kind != "lightning"
                            and mclose < self.cfg_light_range + 6.0)
            want_kite = (
                p["kite_enabled"] and not emergency and not (t < self.flee_until)
                and not finishing
                and (
                    light_danger
                    or (recent_hits and hp_frac < p["v2_kite_hp"])
                    or (recent_hits and los_threats >= 2 and hp_frac < p["v2_multi_kite_hp"])
                    or self.disengage
                )
            )
            if want_kite:
                if recent_hits:
                    vx = -sum(math.cos(d[0]) * (1.0 + min(d[2], 200.0) / 200.0) for d in recent_hits)
                    vy = -sum(math.sin(d[0]) * (1.0 + min(d[2], 200.0) / 200.0) for d in recent_hits)
                elif duel_tgt is not None:
                    vx, vy = x - duel_tgt["pos"][0], y - duel_tgt["pos"][1]
                else:
                    vx, vy = 1.0, 0.0
                vd = math.hypot(vx, vy) or 1.0
                self.kite_dir = (vx / vd, vy / vd)
                self.kite_until = t + (1.4 if light_danger and hp_frac >= p["v2_kite_hp"] else p["v2_kite_hold_s"])
            elif finishing:
                self.kite_until = -1.0
        sb2 = bool(p.get("snowball_v2", False))
        sb2_light_rush = (
            sb2 and p.get("sb2_light_rush", True)
            and w1_kind == "lightning" and me.get("energy", 0) > 22
            and hp_frac > 0.48 and sb_los_mechs <= 1
            and duel_tgt is not None
            and math.hypot(duel_tgt["pos"][0] - x, duel_tgt["pos"][1] - y) < 82.0
            and (not tgt_has_light or me["hp"] >= (duel_tgt.get("hp") or 1400.0) * 0.90)
        )
        sb2_enemy_light_close = (
            sb2 and w1_kind != "lightning"
            and any("lightning" in (e.get("weapons") or [])
                    and math.hypot(e["pos"][0] - x, e["pos"][1] - y) < self.cfg_light_range + 7.0
                    for e in visible)
        )
        if not v2:
            if sb2_light_rush:
                self.kite_until = -1.0
                ed_lr = math.hypot(duel_tgt["pos"][0] - x, duel_tgt["pos"][1] - y)
                if ed_lr > my_light_r - 3.0 and me.get("energy", 0) > 35:
                    sb_boost = True
            elif sb2_enemy_light_close and not emergency and not (t < self.flee_until):
                le = min((e for e in visible if "lightning" in (e.get("weapons") or [])),
                         key=lambda q: math.hypot(q["pos"][0] - x, q["pos"][1] - y))
                vx, vy = x - le["pos"][0], y - le["pos"][1]
                vd = math.hypot(vx, vy) or 1.0
                self.kite_dir = (vx / vd, vy / vd)
                self.kite_until = max(self.kite_until, t + 1.5)
            elif (p["kite_enabled"] and not emergency and not (t < self.flee_until)
                    and recent_hits
                    and not (sb and duel_tgt is not None and (duel_tgt.get("hp") or 1400.0) <= 340.0 and hp_frac > 0.25)
                    and (mclose < p["kite_range"] or self.disengage)
                    and (hp_frac < p["kite_hp"] or len(recent_hits) >= 2
                         or self.disengage)):
                vx = -sum(math.cos(d[0]) * (1.0 + min(d[2], 200.0) / 200.0) for d in recent_hits)
                vy = -sum(math.sin(d[0]) * (1.0 + min(d[2], 200.0) / 200.0) for d in recent_hits)
                vd = math.hypot(vx, vy) or 1.0
                self.kite_dir = (vx / vd, vy / vd)
                kh = p["kite_hold_s"]
                if sb4 and hp_frac > 0.72 and sb_los_mechs <= 1:
                    kh = 3.2
                self.kite_until = t + kh
        if t < self.kite_until and self.kite_dir is not None:
            # In kill_snowball_v1, don't kite away from a <16 m safe cube right at our feet!
            ks1_cube_near = (p.get("kill_snowball_v1", False) and goal_kind == "cube"
                             and math.hypot(goal[0] - x, goal[1] - y) < 16.0 and hp_frac > 0.25)
            if not ks1_cube_near:
                kx, ky = self.kite_dir
                if p["kite_cover"] and visible:
                    bh = self._break_heading(x, y, z, visible, t, all_threats=threats, cc=(ccx, ccy), cr=cr)
                    if bh is not None:
                        kx, ky = bh
                gx, gy = x + kx * 130.0, y + ky * 130.0
                dd = math.hypot(gx - ccx, gy - ccy)
                lim = cr * 0.82
                if dd > lim and dd > 0.01:
                    gx = ccx + (gx - ccx) / dd * lim
                    gy = ccy + (gy - ccy) / dd * lim
                goal, goal_kind = (gx, gy), "kite"
                covered, roaming, kiting = False, False, True

        # ---- rooftop warfare (E42) ---------------------------------------
        roof_active = False
        roof_hold_fire = False
        roof_jump = False
        roof_jet = False
        roof_move = None
        roof_boost = False
        if p.get("roof_enabled", False) and self.roof.spots and not emergency:
            nc = obs["zone"]["next_center"]
            nr = obs["zone"]["next_radius"]
            on_roof_now = self.roof.on_roof(x, y, z) and (me.get("grounded", True) or not self.roof_climbing)
            if on_roof_now:
                self.roof_climbing = False
                self.roof_climb_t = 0.0
                # Classify intruders on/near our elevation vs ground targets
                intruders = [
                    e for e in visible
                    if (math.hypot(e["pos"][0] - x, e["pos"][1] - y) < 42.0 and abs(e["pos"][2] - z) < 7.0)
                    or (math.hypot(e["pos"][0] - x, e["pos"][1] - y) < 22.0 and e["pos"][2] > z - 6.0)
                ]
                out_roof_zone = math.hypot(x - ccx, y - ccy) > cr * 0.85
                abandon = (
                    out_roof_zone
                    or len(intruders) >= 2
                    or (len(intruders) == 1 and hp_frac < 0.42
                        and (intruders[0].get("hp") or 1400.0) > 450.0)
                )
                if abandon:
                    for sp in self.roof.spots:
                        if math.hypot(sp["x"] - x, sp["y"] - y) < 35.0:
                            self.roof.blacklist_spot(sp["id"], t + 18.0)
                    self.roof_spot = None
                    self.roof_healing = False
                    # Drop off toward next_center / away from intruders
                    dx_drop = nc[0] - x
                    dy_drop = nc[1] - y
                    if intruders:
                        dx_drop = sum(x - e["pos"][0] for e in intruders)
                        dy_drop = sum(y - e["pos"][1] for e in intruders)
                    dd = math.hypot(dx_drop, dy_drop) or 1.0
                    goal, goal_kind = (x + dx_drop / dd * 60.0, y + dy_drop / dd * 60.0), "roof_drop"
                    kiting = False
                    self.kite_until = -1.0
                else:
                    roof_active = True
                    kiting = False
                    self.kite_until = -1.0
                    # Heal state with hysteresis
                    lethal_vis = any((e.get("hp") or 1400.0) <= 350.0 for e in visible)
                    if (hp_frac < p["roof_heal_hp"] and not intruders
                            and not lethal_vis and me.get("in_zone", True)):
                        self.roof_healing = True
                    elif hp_frac >= p["roof_heal_exit"] or intruders:
                        self.roof_healing = False

                    w0_cur = me["weapons"][0] if me.get("weapons") else None
                    reloading = bool(w0_cur and w0_cur.get("reload", 0) > 0.35)
                    laser_charging_us = False
                    if p.get("roof_laser_duck", True):
                        for e in visible:
                            if e.get("charging"):
                                b_to_us = math.atan2(y - e["pos"][1], x - e["pos"][0])
                                if abs(wrap((e.get("aim") or [0.0, 0.0])[0] - b_to_us)) < 0.40:
                                    laser_charging_us = True
                                    break
                    reload_duck = (p.get("roof_reload_duck", True) and reloading
                                   and not intruders
                                   and not (w1_kind == "lightning" and mclose < self.cfg_light_range)
                                   and not (w1_kind == "laser" and (w1 or {}).get("charge", 0) > 0.4))
                    want_hide = self.roof_healing or reload_duck or laser_charging_us

                    if want_hide:
                        if self.roof_healing:
                            roof_hold_fire = True
                        eyes = [
                            (e["pos"][0], e["pos"][1],
                             e["pos"][2] + self.world.eye_height
                             * size_scale(e.get("cubes", 0), self.world.size_per_cube))
                            for e in sorted(visible, key=lambda q: math.hypot(q["pos"][0] - x, q["pos"][1] - y))[:3]
                        ]
                        for d in self.damage_bearings[-2:]:
                            b = d[0]
                            tx, ty = x + math.cos(b) * 65.0, y + math.sin(b) * 65.0
                            eyes.append((tx, ty, self.world.ground(tx, ty) + self.world.eye_height))
                        if t - self.roof_hide_t > 0.4 or self.roof_hide_cache is None:
                            self.roof_hide_cache = self.roof.find_roof_hide(x, y, z, eyes, (ccx, ccy), cr)
                            self.roof_hide_t = t
                        if self.roof_hide_cache is not None:
                            hx, hy = self.roof_hide_cache
                            hd = math.hypot(hx - x, hy - y)
                            if hd > 1.5:
                                roof_move = self.roof.stay_on_roof_dir(x, y, z, hx - x, hy - y)
                                if (laser_charging_us or self.recent_damage > 0.2) and me.get("energy", 0) > 20:
                                    roof_boost = True
                            else:
                                roof_move = (0.0, 0.0)
                        else:
                            # Step away from nearest threat while staying on roof
                            if eyes:
                                roof_move = self.roof.stay_on_roof_dir(x, y, z, x - eyes[0][0], y - eyes[0][1])
                            else:
                                roof_move = (0.0, 0.0)
                        goal_kind = "roof_heal" if self.roof_healing else "roof_duck"
                    elif intruders:
                        # Defend roof 1v1 against single climber
                        e = intruders[0]
                        ex, ey = e["pos"][0] - x, e["pos"][1] - y
                        ed = max(0.01, math.hypot(ex, ey))
                        if t >= self.strafe_flip_t:
                            self.strafe_sign = -self.strafe_sign
                            self.strafe_flip_t = t + 0.75
                        sx, sy = -ey / ed * self.strafe_sign, ex / ed * self.strafe_sign
                        want_d = 24.0 if w1_kind == "lightning" else 32.0
                        rad = clamp((ed - want_d) / 14.0, -1.0, 1.0)
                        roof_move = self.roof.stay_on_roof_dir(x, y, z, ex / ed * rad + sx * 0.9, ey / ed * rad + sy * 0.9)
                        goal_kind = "roof_def"
                    else:
                        # Check for loot right on our roof first
                        roof_loot = None
                        for c in obs.get("cubes", []):
                            if abs(c["pos"][2] - z) < 3.0 and math.hypot(c["pos"][0] - x, c["pos"][1] - y) < 35.0:
                                roof_loot = (c["pos"][0], c["pos"][1])
                                break
                        if roof_loot is None and w1 is None and p["take_pickups"]:
                            for pk in obs.get("pickups", []):
                                if abs(pk["pos"][2] - z) < 3.0 and math.hypot(pk["pos"][0] - x, pk["pos"][1] - y) < 40.0:
                                    roof_loot = (pk["pos"][0], pk["pos"][1])
                                    break
                        if roof_loot is not None:
                            roof_move = self.roof.stay_on_roof_dir(x, y, z, roof_loot[0] - x, roof_loot[1] - y)
                            goal_kind = "roof_loot"
                        elif visible:
                            # Peek-and-shoot ground enemies from roof edge!
                            tgt = min(
                                visible,
                                key=lambda q: (
                                    (q.get("hp") or 1400.0) / max(1.0, q.get("max_hp") or 1400.0),
                                    math.hypot(q["pos"][0] - x, q["pos"][1] - y),
                                ),
                            )
                            tc_r = target_center(tgt, self.world.size_per_cube, self.world.height, p["aim_height_frac"])
                            my_mz = (x, y, z + me.get("stats", {}).get("muzzle_height", self.world.muzzle_height))
                            if self.world.shot_clear(my_mz, tc_r):
                                # Already have clear high-ground LOS: flip-strafe along roof!
                                ex, ey = tgt["pos"][0] - x, tgt["pos"][1] - y
                                ed = max(0.01, math.hypot(ex, ey))
                                if t >= self.strafe_flip_t:
                                    self.strafe_sign = -self.strafe_sign
                                    self.strafe_flip_t = t + 0.75
                                sx, sy = -ey / ed * self.strafe_sign, ex / ed * self.strafe_sign
                                if not self.roof.same_roof(x + sx * 4.0, y + sy * 4.0, z):
                                    self.strafe_sign = -self.strafe_sign
                                    sx, sy = -sx, -sy
                                roof_move = self.roof.stay_on_roof_dir(x, y, z, sx, sy)
                                goal_kind = "roof_fire"
                            else:
                                if t - self.roof_peek_t > 0.45 or self.roof_peek_cache is None:
                                    self.roof_peek_cache = self.roof.find_roof_peek(x, y, z, tc_r, (ccx, ccy), cr)
                                    self.roof_peek_t = t
                                if self.roof_peek_cache is not None:
                                    px_r, py_r = self.roof_peek_cache
                                    if math.hypot(px_r - x, py_r - y) > 1.5:
                                        roof_move = self.roof.stay_on_roof_dir(x, y, z, px_r - x, py_r - y)
                                    else:
                                        roof_move = (0.0, 0.0)
                                else:
                                    roof_move = self.roof.stay_on_roof_dir(x, y, z, tgt["pos"][0] - x, tgt["pos"][1] - y)
                                goal_kind = "roof_peek"
                        else:
                            # No visible enemy: slowly drift toward edge facing next_center / sound
                            ang_scan = self.sound_bearing if self.sound_bearing is not None else math.atan2(nc[1] - y, nc[0] - x)
                            roof_move = self.roof.stay_on_roof_dir(x, y, z, math.cos(ang_scan), math.sin(ang_scan))
                            goal_kind = "roof_hold"
            else:
                # Grounded: pick a climbable roof and approach/jet onto it!
                self.roof_healing = False
                if (self.roof_spot is None
                        or self.roof.blacklist.get(self.roof_spot["id"], -1e9) > t
                        or math.hypot(self.roof_spot["x"] - ccx, self.roof_spot["y"] - ccy) > cr * 0.84):
                    self.roof_spot = self.roof.pick_roof(
                        x, y, z, (ccx, ccy), cr, nc, nr, threats, t,
                        max_dist=p["roof_max_seek"],
                    )
                    self.roof_climbing = False
                    self.roof_climb_t = 0.0
                if self.roof_spot is not None:
                    sp = self.roof_spot
                    dl = math.hypot(sp["lx"] - x, sp["ly"] - y)
                    din = math.hypot(sp["in_x"] - x, sp["in_y"] - y)
                    need_e = min(75.0, max(32.0, sp["dh"] * 1.9))
                    if not self.roof_climbing and (dl < 9.0 or din < 13.0) and me.get("energy", 0) >= need_e:
                        self.roof_climbing = True
                        self.roof_climb_t = 0.0
                    if self.roof_climbing:
                        self.roof_climb_t += dt
                        if (self.roof_climb_t > 4.5
                                or (self.roof_climb_t > 0.6 and me.get("grounded") and me.get("energy", 0) < 12.0)):
                            self.roof.blacklist_spot(sp["id"], t + 25.0)
                            self.roof_spot = None
                            self.roof_climbing = False
                        else:
                            roof_active = True
                            kiting = False
                            self.kite_until = -1.0
                            dx_c, dy_c = sp["in_x"] - x, sp["in_y"] - y
                            dc = math.hypot(dx_c, dy_c) or 1.0
                            roof_move = (dx_c / dc, dy_c / dc)
                            if me.get("grounded"):
                                roof_jump = True
                            if not me.get("grounded") and z < sp["z"] + 1.2 and me.get("energy", 0) > 2.0:
                                roof_jet = True
                            goal_kind = "roof_climb"
                    else:
                        # Walk to launch point (override early kite above 55% HP so we actually reach the roof!)
                        if (not kiting or hp_frac > 0.55) and not (t < self.flee_until):
                            goal, goal_kind = (sp["lx"], sp["ly"]), "roof"
                            hunting = False
                            kiting = False
                            self.kite_until = -1.0
                            if dl > 10.0 and me.get("energy", 0) > 45.0:
                                roof_boost = True

        # ---- tactical ground cover: laser-duck, reload-duck, regen hold-fire (E44)
        tc_hold_fire = False
        tc_boost = False
        if p.get("tactical_cover_v1", False) and not emergency and not roof_active:
            my_body = (x, y, z + 0.5 * self.world.height)
            # 1) Enemy laser telegraph cover-duck (42% of holdout deaths!)
            laser_eyes = []
            if p.get("tc_laser_duck", True) and visible:
                for e in visible:
                    if not e.get("charging"):
                        continue
                    ed_l = math.hypot(e["pos"][0] - x, e["pos"][1] - y)
                    if ed_l > 260.0:
                        continue
                    # If we hold lightning and are inside range, zap to short them instead!
                    if w1_kind == "lightning" and ed_l < my_light_r - 1.0 and me.get("energy", 0) > 10:
                        continue
                    b_to_us = math.atan2(y - e["pos"][1], x - e["pos"][0])
                    if abs(wrap((e.get("aim") or [0.0, 0.0])[0] - b_to_us)) < 0.38:
                        ez_l = e["pos"][2] + self.world.eye_height * size_scale(e.get("cubes", 0), self.world.size_per_cube)
                        if self.world.shot_clear((e["pos"][0], e["pos"][1], ez_l), my_body, step=3.0):
                            laser_eyes.append((e["pos"][0], e["pos"][1], ez_l))
            if laser_eyes:
                cov = find_quick_cover(self.world, x, y, z, laser_eyes, max_r=13.0, step=3.0,
                                       zone_center=(ccx, ccy), zone_radius=cr)
                if cov is not None:
                    goal, goal_kind = cov, "tc_laser"
                    covered = True
                    tc_boost = True
                else:
                    # No wall within 13m: boost perpendicular to break track
                    tc_boost = True
            else:
                # 2) Low-HP regen protection (hard-hold-fire ONLY when safe from close LOS!)
                lethal_los = any(
                    (e.get("hp") or 1400.0) <= 400.0
                    and math.hypot(e["pos"][0] - x, e["pos"][1] - y) < 150.0
                    and self.world.shot_clear((x, y, my_muzzle_z), target_center(e, self.world.size_per_cube, self.world.height, p["aim_height_frac"]))
                    for e in visible
                )
                if p.get("tc_heal_hold", True):
                    if hp_frac < p["tc_heal_hp"] and me.get("in_zone", True) and not lethal_los:
                        self.tc_healing = True
                    elif hp_frac >= p["tc_heal_exit"] or not me.get("in_zone", True):
                        self.tc_healing = False
                    if self.tc_healing and not lethal_los:
                        close_los = any(
                            math.hypot(e["pos"][0] - x, e["pos"][1] - y) < p["tc_heal_close_r"]
                            and self.world.shot_clear((x, y, my_muzzle_z), target_center(e, self.world.size_per_cube, self.world.height, p["aim_height_frac"]))
                            for e in visible
                        )
                        if not close_los:
                            tc_hold_fire = True
                            # If someone at medium/long range still has LOS, duck behind a nearby wall!
                            if sb_los_mechs > 0 and not kiting:
                                eyes = [
                                    (e["pos"][0], e["pos"][1],
                                     e["pos"][2] + self.world.eye_height * size_scale(e.get("cubes", 0), self.world.size_per_cube))
                                    for e in sorted(visible, key=lambda q: math.hypot(q["pos"][0] - x, q["pos"][1] - y))[:2]
                                ]
                                if t - self.tc_cov_t > 0.45 or self.tc_cov_cache is None:
                                    self.tc_cov_cache = find_quick_cover(
                                        self.world, x, y, z, eyes, max_r=14.0, step=3.0,
                                        zone_center=(ccx, ccy), zone_radius=cr)
                                    self.tc_cov_t = t
                                if self.tc_cov_cache is not None:
                                    goal, goal_kind = self.tc_cov_cache, "tc_heal"
                                    covered = True

                # 3) Gun-reload cover duck (step behind nearby wall during 2.4s reload!)
                w0_cur = me["weapons"][0] if me.get("weapons") else None
                reloading = bool(w0_cur and w0_cur.get("reload", 0) > 0.45)
                if (p.get("tc_reload_duck", True) and reloading and not covered
                        and not kiting and not sb_econ_lock and sb_los_mechs > 0
                        and not (w1_kind == "lightning" and mclose < my_light_r)
                        and not (w1_kind == "laser" and (w1 or {}).get("charge", 0) > 0.45)):
                    eyes = [
                        (e["pos"][0], e["pos"][1],
                         e["pos"][2] + self.world.eye_height * size_scale(e.get("cubes", 0), self.world.size_per_cube))
                        for e in sorted(visible, key=lambda q: math.hypot(q["pos"][0] - x, q["pos"][1] - y))[:2]
                    ]
                    if t - self.tc_cov_t > 0.45 or self.tc_cov_cache is None:
                        self.tc_cov_cache = find_quick_cover(
                            self.world, x, y, z, eyes, max_r=11.0, step=3.0,
                            zone_center=(ccx, ccy), zone_radius=cr)
                        self.tc_cov_t = t
                    if self.tc_cov_cache is not None:
                        goal, goal_kind = self.tc_cov_cache, "tc_reload"
                        covered = True

        # ---- snowball_v3 pure laser-duck + 1v1 angle isolation (E46) -----
        if sb3 and not emergency and not roof_active and not p.get("tactical_cover_v1", False):
            my_body = (x, y, z + 0.5 * self.world.height)
            # 1) Pure laser-telegraph cover duck (0.5s boost behind wall, ZERO fire suppression!)
            laser_eyes = []
            if p.get("sb3_laser_duck", True) and visible:
                for e in visible:
                    if not e.get("charging"):
                        continue
                    ed_l = math.hypot(e["pos"][0] - x, e["pos"][1] - y)
                    if ed_l > 260.0:
                        continue
                    if w1_kind == "lightning" and ed_l < my_light_r - 1.0 and me.get("energy", 0) > 10:
                        continue
                    b_to_us = math.atan2(y - e["pos"][1], x - e["pos"][0])
                    if abs(wrap((e.get("aim") or [0.0, 0.0])[0] - b_to_us)) < 0.38:
                        ez_l = e["pos"][2] + self.world.eye_height * size_scale(e.get("cubes", 0), self.world.size_per_cube)
                        if self.world.shot_clear((e["pos"][0], e["pos"][1], ez_l), my_body, step=3.0):
                            laser_eyes.append((e["pos"][0], e["pos"][1], ez_l))
            if laser_eyes:
                cov = find_quick_cover(self.world, x, y, z, laser_eyes, max_r=13.0, step=3.0,
                                       zone_center=(ccx, ccy), zone_radius=cr)
                if cov is not None:
                    goal, goal_kind = cov, "tc_laser"
                    covered = True
                tc_boost = True
            # 2) 1v1 corner angle isolation (slice the pie in 1v2+ fights while shooting!)
            elif (p.get("sb3_isolate", True) and sb_los_mechs >= 2
                  and not kiting and not sb_econ_lock and duel_tgt is not None):
                others = [
                    (e["pos"][0], e["pos"][1],
                     e["pos"][2] + self.world.eye_height * size_scale(e.get("cubes", 0), self.world.size_per_cube))
                    for e in visible if e.get("id") != duel_tgt.get("id")
                    and math.hypot(e["pos"][0] - x, e["pos"][1] - y) < 150.0
                ]
                if others:
                    if t - self.iso_t > 0.45 or self.iso_cache is None:
                        p_pos = target_center(duel_tgt, self.world.size_per_cube, self.world.height, p["aim_height_frac"])
                        self.iso_cache = find_isolate_spot(
                            self.world, x, y, z, p_pos, others,
                            zone_center=(ccx, ccy), zone_radius=cr, step=3.0)
                        self.iso_t = t
                    if self.iso_cache is not None:
                        goal, goal_kind = self.iso_cache, "tc_iso"

        # a hide spot we are already standing on is not a goal: stop orbiting
        if covered:
            deadzone = 1.8
        elif goal_kind in ("weapon", "cube", "loot"):
            deadzone = 2.5        # get inside the 4 m pickup radius
        elif goal_kind in ("crate", "npc"):
            deadzone = 22.0       # stop at safe shooting distance
        elif goal_kind == "hunt":
            deadzone = max(8.0, duel_want if (v2 or sb) else p["hunt_standoff"])
        else:
            deadzone = 12.0
        at_goal = math.hypot(goal[0] - x, goal[1] - y) < deadzone

        # ---- movement ---------------------------------------------------
        if self.path_goal is None or math.hypot(goal[0] - self.path_goal[0], goal[1] - self.path_goal[1]) > 18.0 \
                or t - self.path_t > 3.5 or self.stuck_t > 0.8:
            self.path = self.nav.path(x, y, goal[0], goal[1], budget=2600)
            self.path_goal = goal
            self.path_t = t
            if self.stuck_t > 0.8:
                self.stuck_t = 0.0
        mvx, mvy = self.nav.steer(x, y, goal[0], goal[1], z, self.path)
        if (at_goal and not emergency and not (t < self.flee_until)
                and mclose > p["at_goal_stop_r"]):
            mvx, mvy = 0.0, 0.0

        # dodge incoming fire and telegraphed lasers
        from combat import dodge_vector, laser_dodge
        dvx, dvy = dodge_vector(me, obs.get("projectiles", []), p, self.cfg)
        lvx, lvy = laser_dodge(me, visible, p)
        mx = mvx + dvx * 1.4 + lvx * 1.2
        my = mvy + dvy * 1.4 + lvy * 1.2

        # keep away from NPC drones (they shoot, and killing them is loud)
        for npc in npcs:
            nx, ny = npc["pos"][0] - x, npc["pos"][1] - y
            nd = math.hypot(nx, ny)
            if 0.1 < nd < p["npc_avoid"]:
                w = (1.0 - nd / p["npc_avoid"]) * 0.9
                mx -= nx / nd * w
                my -= ny / nd * w

        # strafe instead of walking straight at a shooter
        duel_boost = False
        sr = p["strafe_range"]
        if v2 and duel_tgt is not None and duel_los and not emergency and not kiting and not (t < self.flee_until):
            ex, ey = duel_tgt["pos"][0] - x, duel_tgt["pos"][1] - y
            ed = max(0.01, math.hypot(ex, ey))
            ux, uy = ex / ed, ey / ed
            if t >= self.strafe_flip_t:
                self.strafe_sign = -self.strafe_sign
                self.strafe_flip_t = t + self.rng.uniform(p["v2_flip_min_s"], p["v2_flip_max_s"])
            sx, sy = -uy * self.strafe_sign, ux * self.strafe_sign
            if not self.world.walk_clear(x, y, x + sx * 6.0, y + sy * 6.0, z):
                self.strafe_sign = -self.strafe_sign
                sx, sy = -sx, -sy
                self.strafe_flip_t = t + 0.7
            radial = clamp((ed - duel_want) / 16.0, -1.0, 1.0)
            mx = ux * radial + sx * 0.92 + dvx * 1.1 + lvx * 1.2
            my = uy * radial + sy * 0.92 + dvy * 1.1 + lvy * 1.2
            # Boost in to close with lightning, or boost back out of enemy lightning
            if w1_kind == "lightning" and ed > my_light_r - 2.0 and ed < 85.0 and me.get("energy", 0) > 40:
                duel_boost = True
            elif tgt_has_light and w1_kind != "lightning" and ed < self.cfg_light_range + 10.0 and me.get("energy", 0) > 20:
                duel_boost = True
        elif mclose < sr and visible and not emergency:
            e = min(visible, key=lambda q: math.hypot(q["pos"][0] - x, q["pos"][1] - y))
            ex, ey = e["pos"][0] - x, e["pos"][1] - y
            ed = max(0.01, math.hypot(ex, ey))
            if sb4:
                if t >= self.strafe_flip_t:
                    self.strafe_sign = -self.strafe_sign
                    self.strafe_flip_t = t + self.rng.uniform(0.60, 0.95)
                sx, sy = -ey / ed * self.strafe_sign, ex / ed * self.strafe_sign
                if not self.world.walk_clear(x, y, x + sx * 5.0, y + sy * 5.0, z):
                    self.strafe_sign = -self.strafe_sign
                    sx, sy = -sx, -sy
                    self.strafe_flip_t = t + 0.65
            else:
                sx, sy = -ey / ed, ex / ed
            gain = p["strafe_gain"] * (1.0 - mclose / sr)
            mx += sx * gain
            my += sy * gain

        md = math.hypot(mx, my)
        if md > 1e-5:
            mx, my = mx / md, my / md
        else:
            mx, my = 0.0, 0.0

        # ---- stuck escape ------------------------------------------------
        # A wedged mech dies to a single NPC drone in ~56 s.  When we stop
        # making progress, commit to one high-clearance heading for a while
        # instead of re-deciding every 100 ms (which just oscillates).
        # Priority: break drone contact > escape a geometric trap > normal steer.
        override = None
        if t < self.flee_until and self.flee_dir is not None:
            override = self.flee_dir
        elif t < self.escape_until and self.escape_dir is not None:
            override = self.escape_dir
        elif (self.stuck_t > 0.7
              or (net < 8.0 and math.hypot(goal[0] - x, goal[1] - y) > 30.0
                  and self.recent_damage > 0.1)):
            best, best_score = None, -1e18
            ox = sum(q[1] for q in self.pos_hist) / max(1, len(self.pos_hist))
            oy = sum(q[2] for q in self.pos_hist) / max(1, len(self.pos_hist))
            for k in range(16):
                a = k * TAU / 16.0
                cx, cy = math.cos(a), math.sin(a)
                reach = self.nav.reach(x, y, z, cx, cy)
                qx, qy = x + cx * 14.0, y + cy * 14.0
                away = min((math.hypot(qx - q[0], qy - q[1]) for q in goal_threats),
                           default=120.0)
                # move away from the pocket we have been orbiting
                outward = math.hypot(qx - ox, qy - oy)
                score = reach + min(away, 120.0) * 0.025 + outward * 0.06
                if score > best_score:
                    best_score, best = score, (cx, cy)
            self.escape_dir = best or (mx, my)
            self.escape_until = t + p["escape_hold_s"]
            self.stuck_t = 0.3
            override = self.escape_dir
        escaping = override is not None
        if escaping:
            mx, my = override

        # Always re-validate the *composed* vector: dodges and NPC repulsion
        # can rotate a clear steering heading into a wall.
        if roof_active and roof_move is not None:
            mx, my = roof_move
            reach = 8.0
        else:
            (mx, my), reach = safe_heading(self.world, x, y, z, mx, my)
        self.last_reach = reach
        if reach < 2.0 and self.escape_dir is not None:
            self.escape_until = -1.0

        # quiet movement: <= step_speed makes no footstep sound
        speed_scale = 1.0
        quiet = (p["quiet_when_safe"] and not emergency and close > 70.0
                 and npc_close > 55.0 and t < p["late_survival_t"] and not escaping
                 and not roaming and not kiting and not hunting and not roof_active
                 and goal_kind not in ("roof", "cube", "weapon", "loot", "patrol", "npc", "crate"))
        if quiet:
            speed_scale = min(1.0, p["quiet_speed"] / max(1.0, self.walk_speed))
        boost = bool(p["emergency_boost"] and (emergency or (hp_frac < 0.25 and mclose < 30.0)))
        # NPC drones move at 5 m/s; a quiet 4.85 m/s walk cannot break aggro.
        # Sprint out of their leash instead of eating 25 damage every second.
        npc_aggro = sb_farm_npc is None and npc_close < 38.0 and (self.recent_damage > 0.05 or escaping)
        if (escaping or npc_aggro or kiting or duel_boost or roof_boost or sb_boost or tc_boost) and me.get("energy", 0) > 25:
            boost = True
        if roof_jet:
            boost = True
        if boost:
            speed_scale = 1.0
        if covered and p["cover_quiet"] and not escaping and not tc_boost and goal_kind not in ("tc_laser", "tc_reload"):
            # footsteps are silent below step_speed, and boost is audible at 90 m
            speed_scale = min(speed_scale, p["quiet_speed"] / max(1.0, self.walk_speed))
            boost = False

        # ---- firing gate -------------------------------------------------
        if roof_hold_fire or tc_hold_fire:
            allow_fire = False
        elif wv2:
            allow_fire = bool(p["fire_enabled"] and (not covered or goal_kind in ("tc_laser", "tc_reload")))
        else:
            cornered = mclose < 32.0 and hp_frac > p["hp_floor"]
            engage_dist = p["engage_range"] * p["aggression"] / adapt
            if t > p["late_survival_t"]:
                engage_dist = min(engage_dist, 38.0)
            allow_fire = (p["fire_enabled"] and not emergency and hp_frac > p["hp_floor"]
                          and (not covered or cornered)
                          and (mclose < engage_dist or cornered)
                          and (self.recent_damage > 0.2 or mclose < 40.0 or p["aggression"] > 0.6))
            if (p["recip_fire"] and not allow_fire and not emergency
                    and not covered and hp_frac > p["recip_fire_hp"]
                    and self.recent_damage > 0.05
                    and t - self.last_damage_t < p["recip_fire_window_s"]):
                rng = max(40.0, p["engage_range"])
                ey = z + me.get("stats", {}).get("muzzle_height", self.world.muzzle_height)
                for e in visible:
                    if (math.hypot(e["pos"][0] - x, e["pos"][1] - y) <= rng
                            and self.world.shot_clear((x, y, ey), e["pos"])):
                        allow_fire = True
                        break
        # crate / NPC farming
        combat_targets = list(visible)
        farm = False
        if sb and not emergency and not roof_hold_fire and not tc_hold_fire and sb_los_mechs == 0:
            if sb_farm_npc is not None:
                combat_targets.append({
                    "id": sb_farm_npc["id"], "kind": "mech",
                    "pos": [sb_farm_npc["pos"][0], sb_farm_npc["pos"][1], sb_farm_npc["pos"][2] - 2.75],
                    "vel": list(sb_farm_npc.get("vel", [0, 0, 0])),
                    "hp": sb_farm_npc.get("hp", 350), "max_hp": 350, "cubes": 0,
                    "weapons": [], "aim": [0, 0], "charging": False,
                })
                farm = True
            elif sb_farm_crate is not None:
                combat_targets.append({
                    "id": sb_farm_crate["id"], "kind": "mech",
                    "pos": [sb_farm_crate["pos"][0], sb_farm_crate["pos"][1], sb_farm_crate["pos"][2] - 3.3],
                    "vel": [0, 0, 0], "hp": sb_farm_crate.get("hp", 300), "max_hp": 300,
                    "cubes": 0, "weapons": [], "aim": [0, 0], "charging": False,
                })
                farm = True
        elif not allow_fire and t < p["early_farm_until"] and mclose > 110.0 and not emergency:
            if p["crate_farm"]:
                for cr in obs.get("crates", []):
                    d = math.hypot(cr["pos"][0] - x, cr["pos"][1] - y)
                    if d < 90.0 and self.world.shot_clear(
                            (x, y, z + me.get("stats", {}).get("muzzle_height",
                                                               self.world.muzzle_height)),
                            cr["pos"]):
                        combat_targets.append({"id": cr["id"], "kind": "mech",
                                               "pos": [cr["pos"][0], cr["pos"][1], cr["pos"][2] - 3.3],
                                               "vel": [0, 0, 0], "hp": cr.get("hp", 300),
                                               "cubes": 0, "weapons": [], "aim": [0, 0],
                                               "charging": False})
                        farm = True
                        break
            if p["npc_farm"] and not farm:
                for npc in obs.get("mechs", []):
                    if npc.get("kind") != "npc":
                        continue
                    d = math.hypot(npc["pos"][0] - x, npc["pos"][1] - y)
                    if d < 60.0:
                        combat_targets.append({"id": npc["id"], "kind": "mech",
                                               "pos": [npc["pos"][0], npc["pos"][1], npc["pos"][2] - 2.75],
                                               "vel": list(npc.get("vel", [0, 0, 0])),
                                               "hp": npc.get("hp", 350), "cubes": 0,
                                               "weapons": [], "aim": [0, 0], "charging": False})
                        farm = True
                        break
        if farm:
            allow_fire = True

        allow_charge = (p["fire_enabled"] and not emergency
                        and hp_frac > p["hp_floor"] and not roof_hold_fire and not tc_hold_fire
                        and not (pr1 and (tc_boost or (kiting and hp_frac < 0.45))))
        aim_cmd, fire, fired = self.combat.act(obs, me, combat_targets, p,
                                               allow_fire=allow_fire,
                                               allow_charge=allow_charge)
        if roof_hold_fire or tc_hold_fire:
            fire = [False, False]
            fired = False
        if fired:
            self.last_fire_t = t
            self.fire_count += 1

        # ---- torso: face the threat (front arc), otherwise scan ----------
        aim_yaw, aim_pitch = me["aim"][0], me["aim"][1]
        recent_dmg_b = ([d for d in self.damage_bearings if t - d[1] < 2.0]
                        if (pr1 or p.get("kill_snowball_v1", False)) else [])
        if aim_cmd is not None:
            aim_yaw, aim_pitch = aim_cmd[0], clamp(aim_cmd[1], self.min_pitch, self.max_pitch)
        elif recent_dmg_b:
            # Snap immediately toward unseen attacker to stop 1.5x rear hits & gain vision!
            aim_yaw = recent_dmg_b[-1][0]
            aim_pitch = 0.0
        elif p["face_threat"] and threats:
            tx, ty = min(threats, key=lambda q: math.hypot(q[0] - x, q[1] - y))
            aim_yaw = math.atan2(ty - y, tx - x)
            aim_pitch = 0.0
        elif p["scan_enabled"]:
            base = math.atan2(my, mx) if md > 1e-5 else (self.seed % 628) / 100.0
            if self.intel_enabled and p["sound_scan"] and self.sound_bearing is not None:
                base = self.sound_bearing
            aim_yaw = base + 0.55 * math.sin(t / max(1.0, p["scan_period_s"]) * TAU)
            aim_pitch = 0.0
        else:
            aim_yaw = math.atan2(my, mx) if md > 1e-5 else me["aim"][0]

        act = {
            "move": [round(mx * speed_scale, 4), round(my * speed_scale, 4)],
            "boost": boost,
            "aim": [round(aim_yaw, 4), round(clamp(aim_pitch, self.min_pitch, self.max_pitch), 4)],
            "fire": [bool(fire[0]), bool(fire[1])],
        }
        # unstick / climb: jump if climbing a roof or wedged for a while
        if roof_jump or (self.stuck_t > 1.4 and me.get("grounded")):
            act["jump"] = True
        # reload early when the magazine is dry, or proactively between fights in v2
        w0 = me["weapons"][0] if me["weapons"] else None
        if w0 and w0.get("kind") == "gun" and w0.get("reload", 0) == 0:
            mag = int(w0.get("stats", {}).get("mag", self.cfg_gun_mag))
            ammo = int(w0.get("ammo", mag))
            if ammo == 0 or (wv2 and not self.combat.last_had_target and ammo <= max(6, mag - 4)):
                act["reload"] = True
        # upgrade offer
        pick = pick_upgrade(obs.get("offer"), p, me, self.cfg)
        if pick is not None:
            act["pick"] = pick
        # weapon pickup
        take, drop = choose_take(obs, me, p)
        if take is not None:
            act["take"] = take
            if drop is not None:
                act["drop"] = drop
        if os.environ.get("BOT_DEBUG") and int(obs.get("tick", 0)) % 20 == 0:
            import sys
            print("DBG t=%.1f pos=(%.0f,%.0f) goal=(%.0f,%.0f) kind=%s mv=(%.2f,%.2f) "
                  "reach=%.0f stuck=%.2f esc=%s npc=%.0f threats=%d vis=%d mclose=%.0f "
                  "hp=%.0f fire=%s kit=%s cov=%s roam=%s adapt=%.2f tgt=%s gate=%s rng=%d los=%d ok=%d g=%d l=%d w1=%s"
                  % (t, x, y, goal[0], goal[1], goal_kind, mx, my, reach, self.stuck_t,
                     escaping, npc_close, len(threats), len(visible), mclose,
                     me["hp"], str(fire), kiting, covered, roaming, adapt,
                     self.combat.last_had_target, self.combat.last_gate,
                     self.combat.dbg_range_skip, self.combat.dbg_los_skip,
                     self.combat.dbg_ok,
                     self.combat.gun_shots, self.combat.laser_shots,
                     ((me.get("weapons") or [None, None])[1] or {}).get("kind", "-")),
                  file=sys.stderr, flush=True)
        return act
