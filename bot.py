"""
ApexSurvivor v5 - Aggressive Kiter

Key insight from practice rules: House bots "hunt you weakest first" and
"one early, more as you thin them out, all of them late".

This means:
- Early game: only 1-2 bots are hunting you. FIGHT THEM. Win the 1v1.
- Each kill gives ALL their cubes + 2 bonus. Cubes = +4% HP and +4% damage.
- Cubes make you STRONGER so you survive longer in mid/late game.
- NPCs (12 drones, 350 HP, 2 cubes each) are free cube farms!

Strategy: Aggressive early farming → kiting mid-game → tanky late-game

What was wrong with v2-v4:
- v3/v4: Too passive, ran from everything, died anyway
- v2: Good balance but weak aiming and no NPC farming

v5 improvements:
- Farm NPC drones early (easy kills, free cubes)
- Break crates for cubes + weapon drops
- Engage enemies when HP advantage or 1v1
- Better lead aiming with 2-step Newton iteration
- Supply drop awareness (3 cubes + full heal!)
- Regen awareness: disengage for 5s to heal when low
- Face attackers always (rear armor protection)
"""
import math
import mechfight as mf

UPGRADE_PRIORITY = {
    "armor": 100,
    "plating": 95,
    "nanites": 90,
    "servos": 85,
    "gun_damage": 80,
    "gun_rate": 78,
    "gun_velocity": 75,
    "jets": 72,
    "reactor": 68,
    "capacitor": 65,
    "gyros": 62,
    "sensors": 60,
    "gun_mag": 55,
    "laser_damage": 50,
    "laser_charge": 48,
    "lightning_efficiency": 45,
    "lightning_range": 42,
    "mortar_splash": 30,
    "mortar_reload": 28,
    "mortar_velocity": 25,
    "laser_pierce": 20,
    "lightning_chain": 18,
}

WEAPON_RANK = {"laser": 4, "lightning": 3, "mortar": 2, "gun": 1}


def adiff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


class Bot:
    name = "Apex-v5"

    def __init__(self, hello: mf.Hello):
        cfg = hello.get("config", {})
        self.pickup_r = cfg.get("loot", {}).get("pickup_radius", 4.0)
        self.muzzle_h = cfg.get("mech", {}).get("muzzle_height", 7.0)
        self.bullet_spd = cfg.get("weapons", {}).get("gun", {}).get("speed", 252.0)
        self.regen_delay = cfg.get("mech", {}).get("regen_delay", 5.0)
        self.last_combat_t = -99.0
        self.last_x = 0.0
        self.last_y = 0.0
        self.stuck = 0

    def act(self, obs: mf.Observation) -> mf.Action:
        me = obs["self"]
        x, y, z = me["pos"]
        vx, vy, _ = me["vel"]
        hp, max_hp = me["hp"], me["max_hp"]
        energy = me["energy"]
        aim_y, aim_p = me["aim"]
        tick = obs["tick"]
        t = obs["t"]
        grounded = me["grounded"]
        cubes = me.get("cubes", 0)

        act: mf.Action = {"tick": tick}

        # --- Upgrade ---
        if obs.get("offer"):
            ch = obs["offer"]["choices"]
            act["pick"] = max(range(len(ch)),
                              key=lambda i: UPGRADE_PRIORITY.get(ch[i]["id"], 5))

        # --- Weapon Pickup ---
        w1 = me["weapons"][1]
        w1k = w1["kind"] if w1 else None
        w1r = WEAPON_RANK.get(w1k, 0)
        best_pu, best_pd = None, 999.0
        for p in obs.get("pickups", []):
            r = WEAPON_RANK.get(p["kind"], 0)
            if r > w1r:
                d = math.dist(p["pos"][:2], (x, y))
                if d < best_pd:
                    best_pd, best_pu = d, p
        if best_pu and best_pd < self.pickup_r:
            act["take"] = best_pu["id"]
            if w1:
                act["drop"] = 1

        # --- Enemies & NPCs ---
        mechs = [m for m in obs.get("mechs", []) if m["kind"] == "mech"]
        npcs = [m for m in obs.get("mechs", []) if m["kind"] == "npc"]
        mechs.sort(key=lambda m: math.dist(m["pos"][:2], (x, y)))
        npcs.sort(key=lambda m: math.dist(m["pos"][:2], (x, y)))

        nearest_e = mechs[0] if mechs else None
        d_ne = math.dist(nearest_e["pos"][:2], (x, y)) if nearest_e else 999.0
        nearest_npc = npcs[0] if npcs else None
        d_npc = math.dist(nearest_npc["pos"][:2], (x, y)) if nearest_npc else 999.0
        close_mechs = sum(1 for m in mechs if math.dist(m["pos"][:2], (x, y)) < 70)

        # Combat timestamp tracking
        for ev in obs.get("events", []):
            if ev.get("type") in ("damaged", "hit"):
                self.last_combat_t = t

        # --- Zone ---
        zone = obs["zone"]
        zc, zr = zone["center"], zone["radius"]
        nc, nr = zone["next_center"], zone["next_radius"]
        dc = math.dist((x, y), zc)
        dn = math.dist((x, y), nc)
        to_nc = ((nc[0] - x) / max(0.01, dn), (nc[1] - y) / max(0.01, dn))

        # --- Choose Primary Target ---
        # Priority: NPC if close (easy cubes), else nearest mech
        target = None
        d_target = 999.0

        if nearest_npc and d_npc < 55.0 and (d_ne > 50.0 or close_mechs <= 1):
            # Farm NPC when safe
            target = nearest_npc
            d_target = d_npc
        elif nearest_e:
            target = nearest_e
            d_target = d_ne

        # --- Crate targeting when no enemies ---
        crate_target = None
        if obs.get("crates") and d_ne > 55.0:
            crs = sorted(obs["crates"], key=lambda c: math.dist(c["pos"][:2], (x, y)))
            cr = crs[0]
            cd = math.dist(cr["pos"][:2], (x, y))
            if cd < 50.0:
                crate_target = cr

        # --- Aiming & Firing ---
        des_yaw, des_pitch = aim_y, 0.0
        fire0, fire1 = False, False

        if target:
            ep = target["pos"]
            ev = target.get("vel", [0, 0, 0])
            is_npc = target.get("kind") == "npc"
            tz_offset = 1.5 if is_npc else 4.5
            tx, ty, tz = ep[0], ep[1], ep[2] + tz_offset

            # 2-step Newton lead aiming
            d3 = math.dist((x, y, z + self.muzzle_h), (tx, ty, tz))
            tf = d3 / self.bullet_spd
            px, py, pz = tx + ev[0] * tf, ty + ev[1] * tf, tz + ev[2] * tf
            d3r = math.dist((x, y, z + self.muzzle_h), (px, py, pz))
            tf2 = d3r / self.bullet_spd
            fx, fy, fz = tx + ev[0] * tf2, ty + ev[1] * tf2, tz + ev[2] * tf2

            ddx, ddy = fx - x, fy - y
            ddz = fz - (z + self.muzzle_h)
            hd = math.hypot(ddx, ddy)
            des_yaw = math.atan2(ddy, ddx)
            des_pitch = math.atan2(ddz, max(1.0, hd))

            ye = abs(adiff(des_yaw, aim_y))
            pe = abs(des_pitch - aim_p)

            w0 = me["weapons"][0]
            if w0 and w0["reload"] == 0 and ye < 0.20 and pe < 0.25:
                fire0 = True

            if w1:
                k = w1["kind"]
                if k == "lightning" and d_target < 42 and ye < 0.45:
                    fire1 = True
                elif k == "laser" and ye < 0.28:
                    ch = w1.get("charge", 0.0)
                    fire1 = ch < 0.65
                elif k == "mortar" and 40 < d_target < 190 and ye < 0.25:
                    fire1 = True

        elif crate_target:
            cp = crate_target["pos"]
            cdx, cdy = cp[0] - x, cp[1] - y
            cdz = cp[2] + 1.0 - (z + self.muzzle_h)
            ch = math.hypot(cdx, cdy)
            des_yaw = math.atan2(cdy, cdx)
            des_pitch = math.atan2(cdz, max(1.0, ch))
            if abs(adiff(des_yaw, aim_y)) < 0.18:
                fire0 = True

        # Pre-reload
        w0 = me["weapons"][0]
        if w0 and w0["reload"] == 0 and w0["ammo"] <= 3 and d_ne > 45:
            act["reload"] = True

        act["aim"] = [des_yaw, des_pitch]
        act["fire"] = [fire0, fire1]

        # --- Movement ---
        mx, my = 0.0, 0.0
        boost = False
        jump = False

        outside = dc > (zr - 12) or (not me["in_zone"])
        need_zone = outside or (dn > (nr - 15) and t >= zone.get("shrink_start", 999))

        # HP fraction
        hp_frac = hp / max(1, max_hp)

        # Regen check: if low HP and can disengage, run to heal
        can_regen = (t - self.last_combat_t) > self.regen_delay
        want_disengage = hp_frac < 0.35 and d_ne > 30

        if need_zone:
            mx, my = to_nc
            boost = not me["in_zone"] or energy > 20

        elif want_disengage and not can_regen:
            # Run away to heal
            if nearest_e:
                fx = (x - nearest_e["pos"][0]) / max(0.01, d_ne)
                fy = (y - nearest_e["pos"][1]) / max(0.01, d_ne)
                zone_pull = 0.3 if dn < (nr - 20) else 0.5
                mx = fx * (1 - zone_pull) + to_nc[0] * zone_pull
                my = fy * (1 - zone_pull) + to_nc[1] * zone_pull
                boost = d_ne < 35 and energy > 20
            else:
                mx, my = to_nc

        elif close_mechs >= 3 or (close_mechs >= 2 and hp_frac < 0.5):
            # Too many enemies: flee from centroid
            fx, fy = 0.0, 0.0
            for m in mechs:
                md = math.dist(m["pos"][:2], (x, y))
                if md < 70:
                    w = 1.0 / max(1.0, md)
                    fx += (x - m["pos"][0]) * w
                    fy += (y - m["pos"][1]) * w
            fl = math.hypot(fx, fy)
            if fl > 0.01:
                fx, fy = fx / fl, fy / fl
            zone_pull = 0.15 if dn < (nr - 25) else 0.4
            mx = fx * (1 - zone_pull) + to_nc[0] * zone_pull
            my = fy * (1 - zone_pull) + to_nc[1] * zone_pull
            boost = d_ne < 35 and energy > 25

        elif target and d_target < 55:
            # KITING: maintain 30-45m distance from target while fighting
            ideal_dist = 38.0
            tp = target["pos"]
            flee_x = (x - tp[0]) / max(0.01, d_target)
            flee_y = (y - tp[1]) / max(0.01, d_target)

            if d_target < ideal_dist - 5:
                # Too close: back up
                mx = flee_x * 0.85 + to_nc[0] * 0.15
                my = flee_y * 0.85 + to_nc[1] * 0.15
                boost = d_target < 20 and energy > 25
            elif d_target > ideal_dist + 10:
                # Too far: close in (only if 1v1)
                mx = -flee_x * 0.6 + to_nc[0] * 0.4
                my = -flee_y * 0.6 + to_nc[1] * 0.4
            else:
                # Good range: strafe
                strafe_x = -flee_y
                strafe_y = flee_x
                mx = strafe_x * 0.75 + to_nc[0] * 0.25
                my = strafe_y * 0.75 + to_nc[1] * 0.25

        elif crate_target:
            # Move toward crate
            cp = crate_target["pos"]
            cd = math.dist(cp[:2], (x, y))
            mx = (cp[0] - x) / max(0.01, cd)
            my = (cp[1] - y) / max(0.01, cd)

        else:
            # Patrol ring at 60% of zone radius
            tr = max(12, nr * 0.6)
            rerr = tr - dn
            tan_x, tan_y = -to_nc[1], to_nc[0]
            rad_x = -to_nc[0] * (rerr / max(1, tr))
            rad_y = -to_nc[1] * (rerr / max(1, tr))
            mx = tan_x * 0.7 + rad_x * 0.5
            my = tan_y * 0.7 + rad_y * 0.5

        # Cube/pickup attraction when patrolling
        if not need_zone and d_ne > 45:
            if obs.get("cubes"):
                cs = sorted(obs["cubes"], key=lambda c: math.dist(c["pos"][:2], (x, y)))
                cp = cs[0]["pos"]
                cd = math.dist(cp[:2], (x, y))
                if cd < 20:
                    mx = mx * 0.3 + (cp[0] - x) / max(0.01, cd) * 0.7
                    my = my * 0.3 + (cp[1] - y) / max(0.01, cd) * 0.7

            if best_pu and best_pd < 25:
                px = (best_pu["pos"][0] - x) / max(0.01, best_pd)
                py = (best_pu["pos"][1] - y) / max(0.01, best_pd)
                mx = mx * 0.3 + px * 0.7
                my = my * 0.3 + py * 0.7

        # Supply drop attraction
        for drop in obs.get("drops", []):
            dp = drop["pos"]
            dd = math.dist(dp[:2], (x, y))
            lands_in = drop.get("lands_in", 99)
            holder = drop.get("holder")
            if lands_in <= 0 and holder is None and dd < 40 and d_ne > 50:
                mx = (dp[0] - x) / max(0.01, dd)
                my = (dp[1] - y) / max(0.01, dd)
                boost = dd > 15 and energy > 20

        # Projectile evasion
        for proj in obs.get("projectiles", []):
            pp, pv = proj["pos"], proj["vel"]
            pd = math.dist(pp[:2], (x, y))
            if pd < 30:
                rx, ry = x - pp[0], y - pp[1]
                if rx * pv[0] + ry * pv[1] > 0:
                    vm = math.hypot(pv[0], pv[1])
                    if vm > 1:
                        mx += (-pv[1] / vm) * 1.3
                        my += (pv[0] / vm) * 1.3
                        if pd < 15:
                            boost = energy > 15

        # Stuck detection
        spd = math.hypot(vx, vy)
        if spd < 1.5 and math.hypot(mx, my) > 0.3 and grounded:
            self.stuck += 1
        else:
            self.stuck = 0
        self.last_x, self.last_y = x, y

        if self.stuck > 4:
            ml = math.hypot(mx, my)
            if ml > 0.01:
                mx, my = -my / ml, mx / ml
            jump = grounded
            boost = energy > 15
            self.stuck = 0

        # Normalize
        ml = math.hypot(mx, my)
        if ml > 1:
            mx /= ml
            my /= ml

        act["move"] = [mx, my]
        act["boost"] = boost
        act["jump"] = jump or (tick % 90 == 0 and grounded and not boost)

        mf.draw.label(f"v5 HP:{hp:.0f} C:{cubes} E:{energy:.0f} vis:{len(mechs)}")
        return act


mf.run(Bot)
