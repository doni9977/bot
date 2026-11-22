"""Loot, cubes, supply drops and upgrade valuation."""
from __future__ import annotations

import math


def _legacy_upgrade_value(choice, params):
    uid = choice.get("id", "")
    if uid.startswith("plating"):
        return params["upgrade_plating"]
    if uid.startswith("armor"):
        return params["upgrade_armor"]
    if uid.startswith("nanites"):
        return params["upgrade_nanites"]
    if uid.startswith("capacitor"):
        return params["upgrade_capacitor"]
    if uid.startswith("jets"):
        return params["upgrade_jets"]
    if uid.startswith("servos"):
        return params["upgrade_servos"]
    if uid.startswith("gyros"):
        return params["upgrade_gyros"]
    if uid.startswith("sensors"):
        return params["upgrade_sensors"]
    if uid.startswith("gun_"):
        return params["upgrade_gun"]
    return params["upgrade_weapon"]


def _current_value(cfg, me, path):
    """Current value of an effect path, from live stats or config."""
    if path.startswith("mech."):
        key = path[5:]
        st = me.get("stats", {}) or {}
        if key in st:
            return float(st[key])
        return float((cfg.get("mech", {}) or {}).get(key, 0.0))
    if path.startswith("weapons."):
        parts = path.split(".")
        if len(parts) == 3:
            _, kind, stat = parts
            for w in me.get("weapons", []) or []:
                if w and w.get("kind") == kind:
                    return float((w.get("stats", {}) or {}).get(stat, 0.0))
            return None
    return None


def _effect_value(path, old, new, held):
    """Marginal value of one exact config effect, normalized to a common scale."""
    d = new - old
    if path == "mech.hp":
        return 70.0 * d / max(1.0, old)
    if path == "mech.armor":
        return 60.0 * d / max(0.05, 1.0 - old)
    if path in ("mech.walk_speed", "mech.boost_speed"):
        return 9.0 * (new / max(1e-6, old) - 1.0) / 0.08
    if path == "mech.energy":
        return 8.0 * d / 30.0
    if path == "mech.energy_regen":
        return 5.0 * (new / max(1e-6, old) - 1.0) / 0.30
    if path in ("mech.boost_drain", "mech.jet_drain"):
        return 4.0 * (old / max(1e-6, new) - 1.0) / 0.25
    if path == "mech.regen_per_s":
        return 20.0 * (new / max(1e-6, old) - 1.0) / 0.60
    if path == "mech.regen_delay":
        return 12.0 * (old - new) / 1.5
    if path in ("mech.turn_rate", "mech.pitch_rate"):
        return 9.0 * (new / max(1e-6, old) - 1.0) / 0.30
    if path == "mech.near_range_bonus":
        return 4.0 * d / 15.0
    if path == "mech.vision_bonus":
        return 4.0 * d / 25.0
    if path == "mech.hearing":
        return 5.0 * (old / max(1e-6, new) - 1.0) / 1.0
    if not path.startswith("weapons."):
        return 0.0
    if not held:
        return 0.0
    if path.endswith(".damage"):
        return 22.0 * (new / max(1e-6, old) - 1.0) / 0.15
    if path.endswith(".cooldown"):
        return 18.0 * (old / max(1e-6, new) - 1.0) / 0.15
    if path.endswith(".speed"):
        return 8.0 * (new / max(1e-6, old) - 1.0) / 0.25
    if path.endswith(".range"):
        return 7.0 * (new / max(1e-6, old) - 1.0) / 0.15
    if path.endswith(".mag"):
        return 12.0 * d / 8.0
    if path.endswith(".reload"):
        return 10.0 * (old / max(1e-6, new) - 1.0) / 0.25
    if path.endswith(".splash_radius"):
        return 15.0 * (new / max(1e-6, old) - 1.0) / 0.30
    if path.endswith(".charge"):
        return 16.0 * (old / max(1e-6, new) - 1.0) / 0.33
    if path.endswith(".pierce"):
        return 15.0 * d
    if path.endswith(".chain"):
        return 12.0 * d
    if path.endswith(".cone_deg"):
        return 7.0 * (new / max(1e-6, old) - 1.0) / 0.20
    if path.endswith(".energy"):
        return 12.0 * (old / max(1e-6, new) - 1.0) / 0.54
    return 0.5 * abs(d)


def _effect_value_v2(path, old, new, held, hp_frac=1.0):
    """Fixed marginal value from hello.config.upgrades (E43).

    Fixes the v1 bug where armor scored 4.80 (dead last) and plating scored
    10.50 (below servos=18, gyros=18, sensors=13) due to multi-effect summing.
    """
    d = new - old
    if path == "mech.hp":
        # +15% max HP AND instantly heals the difference!
        base = 26.0 * (new / max(1.0, old) - 1.0) / 0.15
        heal_bonus = 8.0 * (1.0 - max(0.0, min(1.0, hp_frac)))
        return base + heal_bonus
    if path == "mech.armor":
        # Exact EHP multiplier: (1 - old) / (1 - new) - 1 (~8.7% per 0.08 stack, increasing!)
        ehp_gain = (1.0 - old) / max(0.05, 1.0 - new) - 1.0
        return 25.0 * ehp_gain / 0.087
    if path in ("mech.walk_speed", "mech.boost_speed"):
        return 5.5 * (new / max(1e-6, old) - 1.0) / 0.08
    if path == "mech.energy":
        return 7.0 * d / 30.0
    if path == "mech.energy_regen":
        return 7.5 * (new / max(1e-6, old) - 1.0) / 0.30
    if path in ("mech.boost_drain", "mech.jet_drain"):
        return 4.0 * (old / max(1e-6, new) - 1.0) / 0.25
    if path == "mech.regen_per_s":
        return 11.0 * (new / max(1e-6, old) - 1.0) / 0.60
    if path == "mech.regen_delay":
        return 9.0 * (old - new) / 1.5
    if path in ("mech.turn_rate", "mech.pitch_rate"):
        return 4.0 * (new / max(1e-6, old) - 1.0) / 0.30
    if path == "mech.near_range_bonus":
        return 2.5 * d / 15.0
    if path == "mech.vision_bonus":
        return 2.5 * d / 25.0
    if path == "mech.hearing":
        return 2.0 * (old / max(1e-6, new) - 1.0) / 1.0
    if not path.startswith("weapons.") or not held:
        return 0.0
    if path.endswith(".damage"):
        return 23.0 * (new / max(1e-6, old) - 1.0) / 0.15
    if path.endswith(".cooldown"):
        return 24.0 * (old / max(1e-6, new) - 1.0) / 0.15
    if path.endswith(".speed"):
        return 9.0 * (new / max(1e-6, old) - 1.0) / 0.25
    if path.endswith(".range"):
        return 14.0 * (new / max(1e-6, old) - 1.0) / 0.20
    if path.endswith(".mag"):
        return 12.0 * d / 8.0
    if path.endswith(".reload"):
        return 10.0 * (old / max(1e-6, new) - 1.0) / 0.25
    if path.endswith(".splash_radius"):
        return 14.0 * (new / max(1e-6, old) - 1.0) / 0.30
    if path.endswith(".charge"):
        return 21.0 * (old / max(1e-6, new) - 1.0) / 0.33
    if path.endswith(".pierce"):
        return 10.0 * d
    if path.endswith(".chain"):
        return 14.0 * d
    if path.endswith(".cone_deg"):
        return 8.0 * (new / max(1e-6, old) - 1.0) / 0.20
    if path.endswith(".energy"):
        return 14.0 * (old / max(1e-6, new) - 1.0) / 0.54
    return 0.5 * abs(d)


def upgrade_value(choice, params, me=None, cfg=None, exact=True):
    """Exact marginal value from hello.config.upgrades, or legacy fallback."""
    uid = choice.get("id", "")
    if not exact or not cfg or not me:
        return _legacy_upgrade_value(choice, params)
    table = {u.get("id"): u for u in (cfg.get("upgrades", []) or []) if u.get("id")}
    u = table.get(uid)
    if not u:
        return _legacy_upgrade_value(choice, params)
    owned = me.get("upgrades", []) or []
    if u.get("max") is not None and owned.count(uid) >= int(u["max"]):
        return -1e6
    held = {w["kind"] for w in me.get("weapons", []) or [] if w}
    if u.get("requires") and u["requires"] not in held:
        return 0.0
    use_v2 = bool(params.get("upgrade_v2", False) or params.get("snowball_v1", False))
    hp_frac = float(me.get("hp", 1400.0)) / max(1.0, float(me.get("max_hp", 1400.0)))
    total = 0.0
    for eff in u.get("effects", []) or []:
        path = eff.get("path", "")
        old = _current_value(cfg, me, path)
        if old is None:
            continue
        new = old
        if "mul" in eff:
            new *= float(eff["mul"])
        if "add" in eff:
            new += float(eff["add"])
        is_held = bool(u.get("requires") in held if u.get("requires") else True)
        if use_v2:
            total += _effect_value_v2(path, old, new, is_held, hp_frac)
        else:
            total += _effect_value(path, old, new, is_held)
    return total


def pick_upgrade(offer, params, me, cfg=None):
    if not offer or not offer.get("choices"):
        return None
    hp_frac = me["hp"] / max(1.0, me["max_hp"])
    exact = bool(params.get("upgrade_exact", True))
    best_i, best_v = 0, -1e30
    for i, ch in enumerate(offer["choices"]):
        v = upgrade_value(ch, params, me, cfg, exact)
        # when badly hurt, healing matters more than raw max HP
        if ch.get("id", "").startswith("nanites") and hp_frac < 0.5:
            v += 2.0
        if v > best_v:
            best_v, best_i = v, i
    return best_i


def held_kinds(me):
    return [w["kind"] for w in me["weapons"] if w]


def choose_take(obs, me, params):
    """Return (pickup_id, drop_slot) or (None, None)."""
    if not params["take_pickups"]:
        return None, None
    x, y, z = me["pos"]
    reach = 4.0
    held = held_kinds(me)
    empty = 1 if len(me["weapons"]) > 1 and me["weapons"][1] is None else None
    pref = params["weapon_pref"]
    best = None
    best_key = None
    for p in obs.get("pickups", []):
        kind = p["kind"]
        if kind in held:
            continue
        px, py, pz = p["pos"]
        if math.hypot(px - x, py - y) > reach or abs(pz - z) > 4.0:
            continue
        try:
            rank = pref.index(kind)
        except ValueError:
            rank = 99
        key = (rank, math.hypot(px - x, py - y))
        if best_key is None or key < best_key:
            best_key, best = key, p
    if best is None:
        return None, None
    if empty is not None:
        return best["id"], None
    # both slots full: replace slot 1 unless the new weapon is better than slot 1
    slot1 = me["weapons"][1]
    cur_rank = pref.index(slot1["kind"]) if slot1["kind"] in pref else 99
    new_rank = pref.index(best["kind"]) if best["kind"] in pref else 99
    if new_rank >= cur_rank:
        return None, None
    return best["id"], 1


def seek_goal(obs, me, params, world, threats, t, center, radius, seed):
    """Early-game roaming objective.

    The floor starts with 40 weapon pickups and 36 crates, and each cube
    crosses an upgrade threshold (+4% HP and damage, up to +40%).  A bot that
    camps on a hide spot collects none of it.  Returns (goal, kind).
    """
    x, y, z = me["pos"]
    p = params
    held = held_kinds(me)
    pref = p["weapon_pref"]
    best, best_score, kind = None, -1e30, "roam"
    empty_slot = len(me["weapons"]) > 1 and me["weapons"][1] is None

    def consider(cx, cy, cz, score, tag, max_d):
        nonlocal best, best_score, kind
        d = math.hypot(cx - x, cy - y)
        if d > max_d or abs(cz - z) > 8.0:
            return
        # avoid walking through known enemies to get loot
        near = min((math.hypot(cx - q[0], cy - q[1]) for q in threats), default=999.0)
        if near < 35.0:
            return
        s = score - d * 0.35
        if s > best_score:
            best_score, best, kind = s, (cx, cy), tag

    if empty_slot and p["take_pickups"]:
        for pk in obs.get("pickups", []):
            if pk["kind"] in held:
                continue
            try:
                rank = pref.index(pk["kind"])
            except ValueError:
                rank = 9
            consider(pk["pos"][0], pk["pos"][1], pk["pos"][2],
                     120.0 - rank * 12.0, "weapon", p["weapon_seek_range"])

    for c in obs.get("cubes", []):
        consider(c["pos"][0], c["pos"][1], c["pos"][2], 60.0, "cube", p["roam_loot_range"])
    if p["crate_farm"] and t < p["early_farm_until"]:
        for cr in obs.get("crates", []):
            consider(cr["pos"][0], cr["pos"][1], cr["pos"][2], 45.0, "crate",
                     p["roam_loot_range"])
    if p["npc_farm"] and t < p["early_farm_until"]:
        for e in obs.get("mechs", []):
            if e.get("kind") != "npc":
                continue
            consider(e["pos"][0], e["pos"][1], e["pos"][2], 25.0, "npc",
                     p["roam_loot_range"])

    if best is not None and world.blocked(best[0], best[1], world.ground(best[0], best[1])):
        best = None
    if best is not None:
        return best, kind

    # slow deterministic sweep of the safe circle: covers fresh ground and
    # reveals pickups that only become visible when we get close
    a = ((seed % 360) * math.pi / 180.0) + t * p["roam_omega"]
    r = radius * p["roam_goal_frac"]
    return (center[0] + math.cos(a) * r, center[1] + math.sin(a) * r), "roam"


def loot_goal(obs, me, params, world, threats, t):
    """Pick a nearby economic objective worth a small detour. Returns (x,y) or None."""
    x, y, z = me["pos"]
    p = params
    cands = []

    for c in obs.get("cubes", []):
        cx, cy = c["pos"][0], c["pos"][1]
        d = math.hypot(cx - x, cy - y)
        if d < p["cube_detour"] and abs(c["pos"][2] - z) < 6.0:
            cands.append((-d * 0.35 + 14.0, cx, cy, "cube"))

    for pk in obs.get("pickups", []):
        cx, cy = pk["pos"][0], pk["pos"][1]
        d = math.hypot(cx - x, cy - y)
        if d < p["pickup_detour_r"] and pk["kind"] not in held_kinds(me) and me["weapons"][1] is None:
            cands.append((-d * 0.4 + 18.0, cx, cy, "pickup"))

    if p["crate_farm"] and t < p["early_farm_until"]:
        for cr in obs.get("crates", []):
            cx, cy = cr["pos"][0], cr["pos"][1]
            d = math.hypot(cx - x, cy - y)
            if d < 90.0:
                cands.append((-d * 0.5 + 10.0, cx, cy, "crate"))

    if p["npc_farm"] and t < p["early_farm_until"]:
        for e in obs.get("mechs", []):
            if e["kind"] != "npc":
                continue
            cx, cy = e["pos"][0], e["pos"][1]
            d = math.hypot(cx - x, cy - y)
            if d < 70.0:
                cands.append((-d * 0.5 + 8.0, cx, cy, "npc"))

    if p["drop_aggression"] > 0.0:
        for dr in obs.get("drops", []):
            if dr.get("lands_in", 99) > 12.0:
                continue
            holder = dr.get("holder")
            if holder is not None and holder != me["id"]:
                continue
            cx, cy = dr["pos"][0], dr["pos"][1]
            d = math.hypot(cx - x, cy - y)
            near_enemy = min((math.hypot(t[0] - cx, t[1] - cy) for t in threats), default=999.0)
            if d < 120.0 and near_enemy > 45.0 / max(0.1, p["drop_aggression"]):
                cands.append((-d * 0.6 + 26.0 * p["drop_aggression"], cx, cy, "drop"))

    if not cands:
        return None
    cands.sort(reverse=True)
    score, cx, cy, kind = cands[0]
    if score < 0:
        return None
    # do not walk into a wall for loot
    if world.blocked(cx, cy, world.ground(cx, cy)):
        return None
    return (cx, cy)
