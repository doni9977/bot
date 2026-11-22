"""Battlefield intelligence with explicit uncertainty.

Protocol source of truth: `mechfight/1` §6-§10.  The server reports the real,
current position of a previously seen mech for `vision.memory_s`; after that,
any position is an *estimate*, not a fact.  Sounds are bearing-with-Gaussian-
error plus a coarse distance interval; they never identify a shooter.  Beams
and combat events do carry an id when documented.  Enemy energy, ammunition,
cooldowns, reload state, upgrades and upgraded stats are not exposed and are
represented as unknown rather than inferred.
"""
from __future__ import annotations

import math

TAU = math.tau


def wrap(a):
    return (a + math.pi) % TAU - math.pi


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _mech_id(v):
    """Return a documented 0-15 mech id, else None (NPC/crate/zone)."""
    try:
        i = int(v)
    except (TypeError, ValueError):
        return None
    return i if 0 <= i < 16 else None


class Belief:
    """One opponent's belief record.  None means unknown, never a guess."""

    __slots__ = (
        "id", "pos", "vel", "t", "source", "confidence", "direct_confidence",
        "hp", "hp_conf", "max_hp", "weapons", "weapons_conf", "cubes",
        "cubes_conf", "aim", "aim_conf", "charging", "charging_conf",
        "last_fire_t", "last_fire_pos", "last_attack_t", "last_hit_t",
        "damage_dealt", "rear_hits", "dead", "expired", "pos_estimate",
        "possible_state", "threat_score", "vulnerability", "evidence",
        "unknown",
    )

    def __init__(self, mid):
        self.id = int(mid)
        self.pos = None
        self.vel = [0.0, 0.0, 0.0]
        self.t = -1e9
        self.source = "unknown"
        self.confidence = 0.0
        self.direct_confidence = 0.0
        self.hp = None
        self.hp_conf = 0.0
        self.max_hp = None
        self.weapons = None
        self.weapons_conf = 0.0
        self.cubes = None
        self.cubes_conf = 0.0
        self.aim = None
        self.aim_conf = 0.0
        self.charging = None
        self.charging_conf = 0.0
        self.last_fire_t = None
        self.last_fire_pos = None
        self.last_attack_t = None
        self.last_hit_t = None
        self.damage_dealt = 0.0
        self.rear_hits = 0
        self.dead = False
        self.expired = False
        self.pos_estimate = None
        self.possible_state = "unknown"
        self.threat_score = 0.0
        self.vulnerability = 0.0
        self.evidence = []
        # Explicit non-observables.  Do not invent these from our own state.
        self.unknown = ("energy", "ammo", "cooldown", "reload", "upgrades", "stats")

    def mark(self, tag, t, detail=""):
        self.evidence.append((tag, t, detail))
        if len(self.evidence) > 16:
            del self.evidence[:-16]

    def as_dict(self):
        """Compatibility view for the existing combat/navigation code."""
        return {
            "id": self.id,
            "pos": list(self.pos) if self.pos is not None else None,
            "vel": list(self.vel),
            "hp": self.hp,
            "hp_conf": self.hp_conf,
            "max_hp": self.max_hp,
            "weapons": list(self.weapons) if self.weapons is not None else [],
            "weapons_conf": self.weapons_conf,
            "cubes": self.cubes,
            "cubes_conf": self.cubes_conf,
            # Placeholders are always paired with confidence 0; consumers must
            # not treat them as observed facts.
            "aim": list(self.aim) if self.aim is not None else [0.0, 0.0],
            "aim_conf": self.aim_conf,
            "charging": bool(self.charging) if self.charging is not None else False,
            "charging_conf": self.charging_conf,
            "last_fire_t": self.last_fire_t,
            "last_attack_t": self.last_attack_t,
            "source": self.source,
            "confidence": self.confidence,
            "expired": self.expired,
            "possible_state": self.possible_state,
            "threat_score": self.threat_score,
            "vulnerability": self.vulnerability,
        }


class Sector:
    """An uncertain bearing/range sector, never an exact enemy position.

    `source` is one of `sound`, `event` or `beam`.  Sounds have no shooter id;
    events/beams use the documented `by` id.  `sigma` is the bearing standard
    deviation from live config for sounds and a small explicit policy margin
    for exact-bearing events/beams.
    """

    __slots__ = (
        "source", "kind", "bearing", "sigma", "rmin", "rmax", "age", "age0",
        "recv_t", "confidence", "weight", "by", "rear", "pos", "vel",
    )

    def __init__(self, source, kind, bearing, sigma, rmin, rmax, age,
                 confidence, weight, by=None, rear=False, pos=None, vel=None):
        self.source = source
        self.kind = kind
        self.bearing = float(bearing)
        self.sigma = max(0.0, float(sigma))
        self.rmin = max(0.0, float(rmin or 0.0))
        self.rmax = None if rmax is None else max(self.rmin, float(rmax))
        self.age = max(0.0, float(age or 0.0))
        self.age0 = self.age
        self.recv_t = None
        self.confidence = clamp(float(confidence), 0.0, 1.0)
        self.weight = max(0.0, float(weight))
        self.by = by
        self.rear = bool(rear)
        self.pos = list(pos) if pos is not None else None
        self.vel = list(vel) if vel is not None else None

    def effective_age(self, t):
        """Protocol age at hearing plus wall time since we cached the sector."""
        extra = 0.0 if self.recv_t is None else max(0.0, t - self.recv_t)
        return self.age0 + extra

    def penalty(self, x, y, origin, t):
        """How much a candidate goal at (x,y) lies inside this uncertain sector."""
        dx, dy = x - origin[0], y - origin[1]
        d = math.hypot(dx, dy)
        if d < 0.01:
            return 0.0
        half = self.sigma * 2.0 + 0.05
        ad = abs(wrap(math.atan2(dy, dx) - self.bearing))
        if ad > half:
            return 0.0
        radial = 1.0
        if d < self.rmin:
            radial *= max(0.0, 1.0 - (self.rmin - d) / max(20.0, self.rmin))
        if self.rmax is not None and d > self.rmax:
            radial *= max(0.0, 1.0 - (d - self.rmax) / 80.0)
        if radial <= 0.0:
            return 0.0
        fresh = 1.0 / (1.0 + self.effective_age(t))
        return self.confidence * self.weight * fresh * (1.0 - ad / half) * radial


# Relative evidence weights, not protocol facts.  Sounds are weaker evidence
# than a beam or a damage event carrying an attacker id.
_SOUND_WEIGHT = {
    "gun": 1.0, "mortar": 1.0, "explosion": 0.9, "laser": 1.0,
    "laser_charge": 0.8, "lightning": 0.9, "npc_gun": 0.5,
    "step": 0.35, "boost": 0.5, "jet": 0.5, "reload": 0.4,
    "crate": 0.2, "drop": 0.15, "death": 0.25,
}


class Intel:
    """Thin per-decision belief state.  No Monte-Carlo or omniscient model."""

    def __init__(self, hello, world, params=None):
        self.cfg = hello.get("config", {}) or {}
        self.world = world
        self.p = params or {}
        vis = self.cfg.get("vision", {}) or {}
        snd = self.cfg.get("sound", {}) or {}
        mech = self.cfg.get("mech", {}) or {}
        cubes = self.cfg.get("cubes", {}) or {}
        match = self.cfg.get("match", {}) or {}
        self.vision = vis
        self.sound_cfg = snd
        self.mech = mech
        self.memory_s = _num(vis.get("memory_s"), 5.0)
        self.vision_range = _num(vis.get("range"), 200.0)
        self.near_range = _num(vis.get("near_range"), 45.0)
        self.fov = math.radians(_num(vis.get("fov_deg"), 120.0))
        self.show_enemy_hp = bool(vis.get("show_enemy_hp", False))
        self.sound_near = _num(snd.get("near"), 60.0)
        self.sound_mid = _num(snd.get("mid"), 160.0)
        self.sound_ranges = dict(snd.get("range", {}) or {})
        self.max_sound_range = max(self.sound_ranges.values(), default=600.0)
        self.base_sigma = math.radians(_num(snd.get("bearing_noise_deg"), 7.0))
        self.step_speed = _num(snd.get("step_speed"), 5.0)
        self.front_arc = math.radians(_num(mech.get("front_arc_deg"), 180.0))
        self.base_hp = _num(mech.get("hp"), 1400.0)
        self.mech_height = _num(mech.get("height"), 9.0)
        self.mech_radius = _num(mech.get("radius"), 2.5)
        self.size_per_cube = _num(cubes.get("size_per_cube"), 0.05)
        self.dt = (_num(match.get("decide_every"), 2.0)
                   / max(1.0, _num(match.get("tick_hz"), 20.0)))
        self.estimate_ttl = 8.0         # policy: how long an expired estimate lingers
        self.sector_ttl = 6.0           # policy: how long bearing evidence lingers
        self.beliefs = {}
        self.sectors = []
        self.beams = []
        self.projectiles = []
        self.events = []
        self.alive = None
        self.in_zone = None
        self.drops = []
        self.offer = None
        self.t = -1e9
        self.me = None
        self.rear_hits = 0
        self.last_kill_t = None

    # ------------------------------------------------------------------ helpers
    def _size(self, cubes):
        return 1.0 + self.size_per_cube * float(cubes or 0)

    def _center(self, actor):
        p = actor["pos"]
        s = self._size(actor.get("cubes", 0))
        return (p[0], p[1], p[2] + 0.5 * self.mech_height * s)

    def _eye(self, me):
        st = me.get("stats", {}) or {}
        h = _num(st.get("eye_height"), self.mech.get("eye_height", 8.0))
        return (me["pos"][0], me["pos"][1], me["pos"][2] + h)

    def _hearing(self, me):
        st = me.get("stats", {}) or {}
        return _num(st.get("hearing"), self.mech.get("hearing", 1.0))

    def _classify(self, me, m, t):
        """C: likely direct view vs A: server-tracked memory.

        Every `obs.mechs` position is protocol-guaranteed current.  The
        observed/memory distinction is inferred from our own vision geometry,
        so `observed_likely` is explicitly class C, not a protocol fact.
        """
        d = math.hypot(m["pos"][0] - me["pos"][0], m["pos"][1] - me["pos"][1])
        st = me.get("stats", {}) or {}
        near = self.near_range + _num(st.get("near_range_bonus"), 0.0)
        vrange = self.vision_range + _num(st.get("vision_bonus"), 0.0)
        if d <= near:
            return "observed_likely", 0.85
        if d <= vrange:
            bearing = math.atan2(m["pos"][1] - me["pos"][1],
                                 m["pos"][0] - me["pos"][0])
            if abs(wrap(bearing - me["aim"][0])) <= self.fov * 0.5:
                # Cheap LOS check; canopy/trunk nuance is D9, not needed here.
                if self.world.shot_clear(self._eye(me), self._center(m), step=8.0):
                    return "observed_likely", 0.75
        return "server_memory", 0.25

    def _belief(self, mid):
        b = self.beliefs.get(mid)
        if b is None:
            b = Belief(mid)
            self.beliefs[mid] = b
        return b

    def _add_weapon(self, b, kind):
        if not kind or kind in ("npc", "zone", "x"):
            return
        if b.weapons is None:
            b.weapons = []
        if kind not in b.weapons:
            b.weapons.append(kind)
        b.weapons_conf = max(b.weapons_conf, 0.8)

    # ------------------------------------------------------------------ update
    def update(self, obs):
        t = float(obs.get("t", self.t + self.dt))
        me = obs["self"]
        self.t, self.me = t, me
        self.alive = obs.get("alive")
        self.in_zone = me.get("in_zone")
        self.drops = list(obs.get("drops", []) or [])
        self.offer = obs.get("offer")
        self.events = list(obs.get("events", []) or [])
        self.beams = []
        self.projectiles = []
        new_sectors = []

        # --- mechs: server-tracked current positions, no dead reckoning ----
        seen = set()
        self_id = int(me.get("id", -1))
        for m in obs.get("mechs", []) or []:
            if m.get("kind") != "mech":
                continue
            mid = int(m["id"])
            if mid == self_id:
                continue
            seen.add(mid)
            b = self._belief(mid)
            src, direct_conf = self._classify(me, m, t)
            b.pos = [float(q) for q in m["pos"]]
            b.vel = [float(q) for q in m.get("vel", [0.0, 0.0, 0.0])]
            b.t = t
            b.source = src
            b.confidence = 1.0
            b.direct_confidence = direct_conf
            b.expired = False
            b.dead = False
            b.pos_estimate = None
            if self.show_enemy_hp and m.get("hp") is not None:
                b.hp = _num(m["hp"])
                b.hp_conf = 1.0
            if m.get("max_hp") is not None:
                b.max_hp = _num(m["max_hp"])
            if m.get("weapons") is not None:
                b.weapons = list(m["weapons"])
                b.weapons_conf = 1.0
            if m.get("cubes") is not None:
                b.cubes = _num(m["cubes"])
                b.cubes_conf = 1.0
            if m.get("aim") is not None:
                b.aim = [float(q) for q in m["aim"]]
                b.aim_conf = 1.0
            if m.get("charging") is not None:
                b.charging = bool(m["charging"])
                b.charging_conf = 1.0
            b.mark("mechs", t, src)
            b.possible_state = "tracking"

        # --- expire beliefs that no longer receive server tracking ---------
        for mid, b in list(self.beliefs.items()):
            if mid in seen:
                continue
            age = t - b.t
            if age <= self.memory_s:
                # The record remains recent but is not in this observation;
                # keep its last server-reported position with decaying certainty.
                b.confidence = max(0.0, 1.0 - age / max(0.1, self.memory_s))
                b.source = "server_memory"
                b.expired = False
                continue
            dt = age - self.memory_s
            b.expired = True
            b.source = "estimate"
            b.confidence = max(0.0, 1.0 - dt / self.estimate_ttl)
            if b.pos is not None:
                b.pos_estimate = [b.pos[0] + b.vel[0] * dt,
                                  b.pos[1] + b.vel[1] * dt,
                                  b.pos[2] + b.vel[2] * dt]
            b.possible_state = "uncertain_estimate"
            if dt > self.estimate_ttl or b.dead:
                del self.beliefs[mid]

        # --- sounds: bearing with sigma + distance interval, no shooter id --
        sigma = self.base_sigma * self._hearing(me)
        for s in obs.get("sounds", []) or []:
            kind = str(s.get("kind", ""))
            bearing = s.get("bearing")
            if bearing is None:
                continue
            cat = s.get("dist")
            carry = _num(self.sound_ranges.get(kind), self.max_sound_range)
            if cat == "near":
                rmin, rmax = 0.0, min(self.sound_near, carry)
            elif cat == "mid":
                rmin, rmax = self.sound_near, min(self.sound_mid, carry)
            else:
                rmin, rmax = self.sound_mid, carry
            age = max(0.0, _num(s.get("age"), 0.0))
            conf = 0.55 + 0.45 * math.exp(-sigma / 0.35)
            new_sectors.append(Sector(
                "sound", kind, bearing, sigma, rmin, rmax, age, conf,
                _SOUND_WEIGHT.get(kind, 0.3), by=None, rear=False))

        # --- beams: documented shooter id and muzzle-path origin ----------
        for bm in obs.get("beams", []) or []:
            by = bm.get("by")
            kind = str(bm.get("kind", ""))
            path = bm.get("path") or []
            age = max(0.0, _num(bm.get("age"), 0.0))
            rec = {"by": by, "kind": kind, "path": path, "age": age}
            self.beams.append(rec)
            mid = _mech_id(by)
            if mid is None:
                continue
            b = self._belief(mid)
            b.last_fire_t = t - age
            b.last_fire_pos = list(path[0]) if path else None
            self._add_weapon(b, kind)
            b.mark("beam", t, kind)
            b.possible_state = "firing"
            if path:
                q = path[0]
                d = math.hypot(q[0] - me["pos"][0], q[1] - me["pos"][1])
                new_sectors.append(Sector(
                    "beam", kind, math.atan2(q[1] - me["pos"][1], q[0] - me["pos"][0]),
                    math.radians(3.0), 0.0, d, age, 1.0, 1.2,
                    by=int(by), rear=False, pos=q))

        # --- projectiles: no shooter id is available or invented -----------
        for pr in obs.get("projectiles", []) or []:
            self.projectiles.append({
                "id": pr.get("id"), "kind": pr.get("kind"),
                "pos": list(pr["pos"]), "vel": list(pr.get("vel", [0, 0, 0])),
                "shooter_id": None, "source": "projectile",
            })

        # --- events: only our own combat log; `by`/`target` ids are facts ---
        for e in self.events:
            typ = e.get("type")
            if typ == "damaged":
                by = _mech_id(e.get("by"))
                bearing = e.get("bearing")
                rear = bool(e.get("rear", False))
                if rear:
                    self.rear_hits += 1
                if bearing is not None:
                    new_sectors.append(Sector(
                        "event", "damaged", bearing, math.radians(7.0), 0.0, None,
                        0.0, 1.0, 1.5 + _num(e.get("amount"), 0.0) / 300.0,
                        by=by, rear=rear))
                if by is not None:
                    b = self._belief(by)
                    b.last_attack_t = t
                    if rear:
                        b.rear_hits += 1
                    self._add_weapon(b, e.get("weapon"))
                    b.mark("damaged_by", t, str(e.get("weapon", "")))
                    b.possible_state = "hostile"
            elif typ == "hit":
                target = _mech_id(e.get("target"))
                if target is not None:
                    b = self._belief(target)
                    b.last_hit_t = t
                    b.damage_dealt += _num(e.get("amount"), 0.0)
                    b.mark("hit_by_us", t, str(e.get("weapon", "")))
            elif typ == "effect":
                by = _mech_id(e.get("by"))
                if by is not None:
                    b = self._belief(by)
                    b.last_attack_t = t
                    b.mark("effect_by", t, str(e.get("effect", "")))
                    b.possible_state = "hostile"
            elif typ == "kill":
                target = _mech_id(e.get("target"))
                if target is not None:
                    b = self._belief(target)
                    b.dead = True
                    b.mark("killed_by_us", t)
                self.last_kill_t = t
            # `took`, `take_failed`, `pickup`, `drop`, `upgrade` concern us
            # only; they are deliberately not attributed to an opponent.

        # Keep only fresh bearing evidence.  `age` is the protocol's age at
        # hearing; `recv_t` adds the wall time since we cached the sector.
        self.sectors = [s for s in self.sectors
                        if s.recv_t is not None
                        and s.effective_age(t) <= self.sector_ttl]
        for s in new_sectors:
            s.recv_t = t
        self.sectors.extend(new_sectors)

        # --- derived threat/vulnerability scores (class C) ------------------
        px, py = me["pos"][0], me["pos"][1]
        for b in self.beliefs.values():
            if b.pos is None or b.dead:
                b.threat_score = 0.0
                b.vulnerability = 0.0
                continue
            d = math.hypot(b.pos[0] - px, b.pos[1] - py)
            score = b.confidence / (1.0 + d / 100.0)
            if b.last_fire_t is not None and t - b.last_fire_t < 2.0:
                score *= 1.6
            if b.last_attack_t is not None and t - b.last_attack_t < 3.0:
                score *= 1.7
            b.threat_score = score
            vuln = 0.0
            if b.hp is not None and b.hp_conf > 0.0:
                mx = b.max_hp or self.base_hp
                vuln += b.hp_conf * (1.0 - clamp(b.hp / max(1.0, mx), 0.0, 1.0))
            if b.aim is not None and b.aim_conf > 0.0:
                our_bearing = math.atan2(py - b.pos[1], px - b.pos[0])
                if abs(wrap(our_bearing - b.aim[0])) > self.front_arc * 0.5:
                    vuln += 0.5 * b.aim_conf   # their rear is toward us
            b.vulnerability = vuln
            if b.expired:
                b.possible_state = "uncertain_estimate"
            elif b.last_fire_t is not None and t - b.last_fire_t < 2.0:
                b.possible_state = "firing"
            elif b.last_attack_t is not None and t - b.last_attack_t < 3.0:
                b.possible_state = "hostile"
            else:
                b.possible_state = "tracking"

    # ------------------------------------------------------------------ queries
    def threat_points(self, min_conf=0.65):
        """Only protocol-current positions.  No sound/damage pseudo-points."""
        out = []
        for b in self.beliefs.values():
            if b.dead or b.expired or b.pos is None:
                continue
            if b.confidence < min_conf:
                continue
            out.append((b.pos[0], b.pos[1]))
        return out

    def uncertain_points(self, min_conf=0.2):
        """Expired estimates, explicitly separate from current positions."""
        out = []
        for b in self.beliefs.values():
            if b.dead or not b.expired or b.pos_estimate is None:
                continue
            if b.confidence < min_conf:
                continue
            out.append((b.pos_estimate[0], b.pos_estimate[1], b.confidence))
        return out

    def visible_dicts(self, max_age=0.25):
        out = []
        for b in self.beliefs.values():
            if b.dead or b.expired or b.pos is None:
                continue
            if self.t - b.t > max_age:
                continue
            d = b.as_dict()
            out.append(d)
        return out

    def sector_contacts(self, min_conf=0.08):
        """Recent uncertain sectors for goal scoring and scan direction."""
        return [s for s in self.sectors
                if s.confidence >= min_conf
                and s.effective_age(self.t) <= self.sector_ttl]

    def sound_pressure(self):
        total = 0.0
        for s in self.sector_contacts():
            total += s.confidence * s.weight / (1.0 + s.effective_age(self.t))
        return total

    def sound_bearing(self):
        vx = vy = 0.0
        for s in self.sector_contacts():
            w = s.confidence * s.weight / (1.0 + s.effective_age(self.t))
            vx += math.cos(s.bearing) * w
            vy += math.sin(s.bearing) * w
        if math.hypot(vx, vy) < 1e-6:
            return None
        return math.atan2(vy, vx)
