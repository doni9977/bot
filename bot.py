"""
ApexSurvivor v4 - Ghost Protocol
Core philosophy: SURVIVAL ABOVE ALL. Against a 15-bot squad that shares vision
and hunts you, the winning move is to run, hide, and only fight when cornered.

Key changes from v3:
- Removed whisker obstacle avoidance (caused erratic movement, hurt score)
- Removed low-HP chasing (lured bot into squad ambushes)
- Much more aggressive fleeing from multiple enemies
- Better energy conservation (boost only when truly needed)
- Smarter engagement: only fire while fleeing, never chase
- Zigzag evasion pattern when under fire
- Supply drop awareness
"""
import math
import mechfight as mf

UPGRADE_PRIORITY = {
    "nanites": 100,    # Regen = survival
    "armor": 95,       # Less damage = survival
    "servos": 90,      # Speed = survival
    "plating": 85,     # More HP = survival
    "jets": 80,        # Better boost = escape
    "reactor": 75,     # More energy = more boosts
    "capacitor": 70,   # Energy pool
    "sensors": 65,     # See enemies sooner = react sooner
    "gyros": 60,       # Faster aim = faster snap shots while running
    "gun_rate": 55,
    "gun_damage": 50,
    "gun_velocity": 48,
    "gun_mag": 45,
    "laser_damage": 40,
    "laser_charge": 38,
    "lightning_efficiency": 35,
    "lightning_range": 33,
    "mortar_splash": 20,
    "mortar_reload": 18,
    "mortar_velocity": 15,
    "laser_pierce": 12,
    "lightning_chain": 10,
}

WEAPON_RANK = {"laser": 4, "lightning": 3, "mortar": 2, "gun": 1}


def angle_diff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


class Bot:
    name = "Ghost-v4"

    def __init__(self, hello: mf.Hello):
        cfg = hello.get("config", {})
        self.pickup_radius = cfg.get("loot", {}).get("pickup_radius", 3.5)
        self.muzzle_height = cfg.get("mech", {}).get("muzzle_height", 7.0)
        self.bullet_speed = cfg.get("weapons", {}).get("gun", {}).get("speed", 252.0)
        self.last_x = 0.0
        self.last_y = 0.0
        self.stuck_count = 0
        self.zigzag_phase = 1  # alternates +1 / -1

    def act(self, obs: mf.Observation) -> mf.Action:
        me = obs["self"]
        x, y, z = me["pos"]
        vx, vy, vz = me["vel"]
        hp = me["hp"]
        max_hp = me["max_hp"]
        energy = me["energy"]
        aim_yaw, aim_pitch = me["aim"]
        tick = obs["tick"]
        t = obs["t"]
        grounded = me["grounded"]
        in_zone = me["in_zone"]

        act: mf.Action = {"tick": tick}

        # === 1. UPGRADE SELECTION ===
        if obs.get("offer"):
            choices = obs["offer"]["choices"]
            best_i = max(range(len(choices)),
                         key=lambda i: UPGRADE_PRIORITY.get(choices[i]["id"], 5))
            act["pick"] = best_i

        # === 2. WEAPON PICKUP ===
        w1 = me["weapons"][1]
        w1_kind = w1["kind"] if w1 else None
        w1_rank = WEAPON_RANK.get(w1_kind, 0)

        best_pickup = None
        best_p_dist = 999.0
        for p in obs.get("pickups", []):
            rank = WEAPON_RANK.get(p["kind"], 0)
            if rank > w1_rank:
                d = math.dist(p["pos"][:2], (x, y))
                if d < best_p_dist:
                    best_p_dist = d
                    best_pickup = p

        if best_pickup and best_p_dist < self.pickup_radius:
            act["take"] = best_pickup["id"]
            if w1:
                act["drop"] = 1

        # === 3. ENEMIES ===
        enemies = [m for m in obs.get("mechs", []) if m["kind"] == "mech"]
        enemies.sort(key=lambda m: math.dist(m["pos"][:2], (x, y)))
        n_visible = len(enemies)
        nearest = enemies[0] if enemies else None
        d_nearest = math.dist(nearest["pos"][:2], (x, y)) if nearest else 999.0

        # Threat level: how many enemies are close
        close_enemies = sum(1 for e in enemies if math.dist(e["pos"][:2], (x, y)) < 80.0)
        danger = close_enemies >= 2 or d_nearest < 30.0

        # === 4. ZONE ===
        zone = obs["zone"]
        zc = zone["center"]
        zr = zone["radius"]
        nc = zone["next_center"]
        nr = zone["next_radius"]
        shrink_start = zone.get("shrink_start", 999)
        dps = zone.get("dps", 20)

        d_center = math.dist((x, y), zc)
        d_next = math.dist((x, y), nc)

        to_nc_x = (nc[0] - x) / max(0.01, d_next)
        to_nc_y = (nc[1] - y) / max(0.01, d_next)

        # === 5. MOVEMENT STRATEGY ===
        mx, my = 0.0, 0.0
        boost = False

        # Priority 1: Stay in zone
        outside_zone = d_center > (zr - 12.0)
        zone_shrinking = t >= shrink_start
        need_zone = outside_zone or (zone_shrinking and d_next > (nr - 15.0))

        if not in_zone or need_zone:
            # URGENT: get to safety
            mx, my = to_nc_x, to_nc_y
            boost = energy > 15
        elif danger:
            # Priority 2: RUN from enemies
            # Flee direction: away from centroid of close enemies
            flee_x, flee_y = 0.0, 0.0
            for e in enemies:
                ed = math.dist(e["pos"][:2], (x, y))
                if ed < 80.0:
                    w = 1.0 / max(1.0, ed)
                    flee_x += (x - e["pos"][0]) * w
                    flee_y += (y - e["pos"][1]) * w

            fl = math.hypot(flee_x, flee_y)
            if fl > 0.01:
                flee_x /= fl
                flee_y /= fl

            # Zigzag while fleeing (harder to hit)
            if tick % 15 == 0:
                self.zigzag_phase *= -1
            perp_x = -flee_y * self.zigzag_phase * 0.4
            perp_y = flee_x * self.zigzag_phase * 0.4

            # Blend: flee + zigzag + pull toward zone center
            zone_pull = 0.15 if d_next < (nr - 25.0) else 0.4
            mx = flee_x * 0.75 + perp_x + to_nc_x * zone_pull
            my = flee_y * 0.75 + perp_y + to_nc_y * zone_pull

            boost = d_nearest < 35.0 and energy > 25
        else:
            # Priority 3: Patrol ring & loot
            target_r = max(12.0, nr * 0.6)
            r_err = target_r - d_next

            # Tangent for circling
            tan_x = -to_nc_y
            tan_y = to_nc_x
            # Radial correction
            rad_x = -to_nc_x * (r_err / max(1.0, target_r))
            rad_y = -to_nc_y * (r_err / max(1.0, target_r))

            mx = tan_x * 0.7 + rad_x * 0.5
            my = tan_y * 0.7 + rad_y * 0.5

            # Steer toward cubes when safe
            if obs.get("cubes") and d_nearest > 50.0:
                cubes_sorted = sorted(obs["cubes"],
                                      key=lambda c: math.dist(c["pos"][:2], (x, y)))
                cp = cubes_sorted[0]["pos"]
                dc = math.dist(cp[:2], (x, y))
                if dc < 22.0:
                    mx = mx * 0.3 + (cp[0] - x) / max(0.01, dc) * 0.7
                    my = my * 0.3 + (cp[1] - y) / max(0.01, dc) * 0.7

            # Steer toward weapon pickups
            if best_pickup and d_nearest > 45.0 and best_p_dist < 28.0:
                px = (best_pickup["pos"][0] - x) / max(0.01, best_p_dist)
                py = (best_pickup["pos"][1] - y) / max(0.01, best_p_dist)
                mx = mx * 0.25 + px * 0.75
                my = my * 0.25 + py * 0.75

        # === 6. PROJECTILE EVASION ===
        for proj in obs.get("projectiles", []):
            pp = proj["pos"]
            pv = proj["vel"]
            pd = math.dist(pp[:2], (x, y))
            if pd < 30.0:
                rx, ry = x - pp[0], y - pp[1]
                if rx * pv[0] + ry * pv[1] > 0:  # heading toward us
                    vm = math.hypot(pv[0], pv[1])
                    if vm > 1.0:
                        mx += (-pv[1] / vm) * 1.5
                        my += (pv[0] / vm) * 1.5
                        if pd < 15.0:
                            boost = energy > 15

        # === 7. STUCK DETECTION ===
        moved = math.hypot(x - self.last_x, y - self.last_y)
        speed = math.hypot(vx, vy)
        if speed < 1.5 and math.hypot(mx, my) > 0.3 and grounded:
            self.stuck_count += 1
        else:
            self.stuck_count = 0
        self.last_x, self.last_y = x, y

        jump = False
        if self.stuck_count > 4:
            # Perpendicular escape
            ml = math.hypot(mx, my)
            if ml > 0.01:
                mx, my = -my / ml, mx / ml
            jump = grounded
            boost = energy > 15
            self.stuck_count = 0

        # Normalize
        ml = math.hypot(mx, my)
        if ml > 1.0:
            mx /= ml
            my /= ml

        act["move"] = [mx, my]
        act["boost"] = boost
        act["jump"] = jump or (tick % 80 == 0 and grounded and not boost and not danger)

        # === 8. AIMING & FIRING ===
        desired_yaw = aim_yaw
        desired_pitch = 0.0
        fire0 = False
        fire1 = False

        if nearest:
            ep = nearest["pos"]
            ev = nearest["vel"]
            tx, ty, tz = ep[0], ep[1], ep[2] + 4.5

            # Lead aiming
            d3 = math.dist((x, y, z + self.muzzle_height), (tx, ty, tz))
            tf = d3 / self.bullet_speed
            px = tx + ev[0] * tf
            py = ty + ev[1] * tf
            pz = tz + ev[2] * tf

            d3r = math.dist((x, y, z + self.muzzle_height), (px, py, pz))
            tf2 = d3r / self.bullet_speed
            fx = tx + ev[0] * tf2
            fy = ty + ev[1] * tf2
            fz = tz + ev[2] * tf2

            ddx = fx - x
            ddy = fy - y
            ddz = fz - (z + self.muzzle_height)
            hd = math.hypot(ddx, ddy)

            desired_yaw = math.atan2(ddy, ddx)
            desired_pitch = math.atan2(ddz, max(1.0, hd))

            ye = abs(angle_diff(desired_yaw, aim_yaw))
            pe = abs(desired_pitch - aim_pitch)

            # Fire gun while running (snap shots)
            w0 = me["weapons"][0]
            if w0 and w0["reload"] == 0 and ye < 0.18 and pe < 0.22 and d_nearest < 180.0:
                fire0 = True

            # Slot 1
            if w1:
                k = w1["kind"]
                if k == "lightning" and d_nearest < 42.0 and ye < 0.45:
                    fire1 = True
                elif k == "laser" and d_nearest > 30.0 and ye < 0.28:
                    ch = w1.get("charge", 0.0)
                    fire1 = ch < 0.65  # hold to charge, release at 0.65+
                elif k == "mortar" and 45.0 < d_nearest < 190.0 and ye < 0.25:
                    fire1 = True
        elif obs.get("crates"):
            # Shoot crate if safe
            crs = sorted(obs["crates"], key=lambda c: math.dist(c["pos"][:2], (x, y)))
            cr = crs[0]
            cxyz = cr["pos"]
            cdx = cxyz[0] - x
            cdy = cxyz[1] - y
            cdz = cxyz[2] + 1.0 - (z + self.muzzle_height)
            ch = math.hypot(cdx, cdy)
            desired_yaw = math.atan2(cdy, cdx)
            desired_pitch = math.atan2(cdz, max(1.0, ch))
            if abs(angle_diff(desired_yaw, aim_yaw)) < 0.18 and ch < 60.0:
                fire0 = True

        # Pre-reload when safe
        w0 = me["weapons"][0]
        if w0 and w0["reload"] == 0 and w0["ammo"] <= 3 and d_nearest > 50.0:
            act["reload"] = True

        act["aim"] = [desired_yaw, desired_pitch]
        act["fire"] = [fire0, fire1]

        mf.draw.label(f"Ghost-v4 HP:{hp:.0f} E:{energy:.0f} vis:{n_visible}")

        return act


mf.run(Bot)
