"""
Apex Survivor v2 - Strategic Kiter & Ballistics Bot for Mech Royale
Features:
- Ballistic lead aiming (252 m/s bullet prediction)
- Rear armor protection (face attackers while kiting)
- Safe zone ring-hugging (patrol outer 65% of circle, avoid center meatgrinder)
- Projectile evasion / dodging
- Priority looting (power cubes, laser/lightning pickups)
- Optimal upgrade selection
"""
import math
import mechfight as mf

UPGRADE_WEIGHTS = {
    "nanites": 100,
    "armor": 90,
    "plating": 85,
    "servos": 80,
    "jets": 75,
    "reactor": 70,
    "capacitor": 65,
    "laser_damage": 60,
    "laser_charge": 58,
    "lightning_efficiency": 55,
    "lightning_range": 54,
    "gun_damage": 50,
    "gun_rate": 48,
    "gun_velocity": 46,
    "sensors": 45,
    "gyros": 40,
    "gun_mag": 35,
    "mortar_splash": 30,
    "mortar_reload": 28,
    "mortar_velocity": 25,
}

WEAPON_RANK = {
    "laser": 4,
    "lightning": 3,
    "mortar": 2,
    "gun": 1,
}


def angle_diff(target, current):
    """Smallest signed angular difference from current to target."""
    diff = (target - current + math.pi) % (2 * math.pi) - math.pi
    return diff


class Bot:
    name = "ApexSurvivor-v2"

    def __init__(self, hello: mf.Hello):
        cfg = hello.get("config", {})
        self.pickup_radius = cfg.get("loot", {}).get("pickup_radius", 3.5)
        self.muzzle_height = cfg.get("mech", {}).get("muzzle_height", 7.0)
        self.bullet_speed = cfg.get("weapons", {}).get("gun", {}).get("speed", 252.0)
        self.charging_laser = False

    def act(self, obs: mf.Observation) -> mf.Action:
        me = obs["self"]
        x, y, z = me["pos"]
        vx, vy, vz = me["vel"]
        hp = me["hp"]
        max_hp = me["max_hp"]
        energy = me["energy"]
        actual_aim_yaw, actual_aim_pitch = me["aim"]
        tick = obs["tick"]

        act: mf.Action = {"tick": tick}

        # -------------------------------------------------------------
        # 1. UPGRADE SELECTION
        # -------------------------------------------------------------
        if obs.get("offer"):
            offer = obs["offer"]
            best_idx = 0
            best_score = -1
            for idx, ch in enumerate(offer["choices"]):
                score = UPGRADE_WEIGHTS.get(ch["id"], 10)
                if score > best_score:
                    best_score = score
                    best_idx = idx
            act["pick"] = best_idx

        # -------------------------------------------------------------
        # 2. WEAPON & PICKUP MANAGEMENT
        # -------------------------------------------------------------
        current_w1 = me["weapons"][1]
        w1_kind = current_w1["kind"] if current_w1 else None
        w1_rank = WEAPON_RANK.get(w1_kind, 0)

        best_pickup = None
        best_p_dist = 999.0
        for p in obs.get("pickups", []):
            p_kind = p["kind"]
            p_rank = WEAPON_RANK.get(p_kind, 0)
            if p_rank > w1_rank:
                d = math.dist(p["pos"][:2], (x, y))
                if d < best_p_dist:
                    best_p_dist = d
                    best_pickup = p

        if best_pickup and best_p_dist < self.pickup_radius:
            act["take"] = best_pickup["id"]
            if current_w1:
                act["drop"] = 1

        # -------------------------------------------------------------
        # 3. THREAT IDENTIFICATION & ENEMY TRACKING
        # -------------------------------------------------------------
        enemies = [m for m in obs.get("mechs", []) if m["kind"] == "mech"]
        enemies.sort(key=lambda m: math.dist(m["pos"][:2], (x, y)))
        nearest_enemy = enemies[0] if enemies else None
        d_enemy = math.dist(nearest_enemy["pos"][:2], (x, y)) if nearest_enemy else 999.0

        # -------------------------------------------------------------
        # 4. AIMING & BALLISTIC LEAD PREDICTION
        # -------------------------------------------------------------
        desired_yaw = actual_aim_yaw
        desired_pitch = 0.0
        fire_slot0 = False
        fire_slot1 = False

        target_point = None

        if nearest_enemy:
            ep = nearest_enemy["pos"]
            ev = nearest_enemy["vel"]
            # Target center of mass (z + 4.5)
            tx, ty, tz = ep[0], ep[1], ep[2] + 4.5
            dist_to_enemy = math.dist((x, y, z + self.muzzle_height), (tx, ty, tz))

            # Ballistic lead calculation
            t_flight = dist_to_enemy / self.bullet_speed
            # Iterative refinement
            pred_x = tx + ev[0] * t_flight
            pred_y = ty + ev[1] * t_flight
            pred_z = tz + ev[2] * t_flight

            dist_refined = math.dist((x, y, z + self.muzzle_height), (pred_x, pred_y, pred_z))
            t_flight2 = dist_refined / self.bullet_speed
            final_tx = tx + ev[0] * t_flight2
            final_ty = ty + ev[1] * t_flight2
            final_tz = tz + ev[2] * t_flight2

            dx = final_tx - x
            dy = final_ty - y
            dz = final_tz - (z + self.muzzle_height)
            h_dist = math.hypot(dx, dy)

            desired_yaw = math.atan2(dy, dx)
            desired_pitch = math.atan2(dz, max(1.0, h_dist))
            target_point = [final_tx, final_ty, final_tz]

            # Firing decisions
            yaw_err = abs(angle_diff(desired_yaw, actual_aim_yaw))
            pitch_err = abs(desired_pitch - actual_aim_pitch)

            # Slot 0: Main Gun
            w0 = me["weapons"][0]
            if w0 and w0["reload"] == 0 and yaw_err < 0.22 and pitch_err < 0.25:
                fire_slot0 = True

            # Slot 1: Special Weapon
            if current_w1:
                kind = current_w1["kind"]
                if kind == "laser":
                    # Charge laser when aimed roughly at target
                    if yaw_err < 0.35:
                        charge = current_w1.get("charge", 0.0)
                        if charge >= 0.70 or (charge >= 0.20 and d_enemy > 150):
                            # Release to fire
                            fire_slot1 = False
                            self.charging_laser = False
                        else:
                            # Hold charge
                            fire_slot1 = True
                            self.charging_laser = True
                    else:
                        self.charging_laser = False
                elif kind == "lightning":
                    # Instant cone attack within 45m
                    if d_enemy <= 45.0 and yaw_err < 0.45:
                        fire_slot1 = True
                elif kind == "mortar":
                    # Lob at enemy if distance is suitable
                    if 35.0 < d_enemy < 200.0 and yaw_err < 0.3:
                        fire_slot1 = True

        elif obs.get("crates"):
            # Shoot nearby crate if safe
            crates = sorted(obs["crates"], key=lambda c: math.dist(c["pos"][:2], (x, y)))
            c = crates[0]
            cx, cy, cz = c["pos"]
            dx = cx - x
            dy = cy - y
            dz = cz + 1.0 - (z + self.muzzle_height)
            h_dist = math.hypot(dx, dy)
            desired_yaw = math.atan2(dy, dx)
            desired_pitch = math.atan2(dz, max(1.0, h_dist))
            if abs(angle_diff(desired_yaw, actual_aim_yaw)) < 0.2:
                fire_slot0 = True

        act["aim"] = [desired_yaw, desired_pitch]
        act["fire"] = [fire_slot0, fire_slot1]

        # -------------------------------------------------------------
        # 5. MOVEMENT: RING-HUGGING & TACTICAL KITING
        # -------------------------------------------------------------
        zone = obs["zone"]
        zc = zone["center"]
        zr = zone["radius"]
        next_c = zone["next_center"]
        next_r = zone["next_radius"]

        dist_cur_center = math.dist((x, y), zc)
        dist_next_center = math.dist((x, y), next_c)

        # Vector towards safe zone center
        to_safe_x = (next_c[0] - x) / max(0.1, dist_next_center)
        to_safe_y = (next_c[1] - y) / max(0.1, dist_next_center)

        # Default move weights
        move_x = 0.0
        move_y = 0.0
        should_boost = False

        # Check zone urgency
        outside_cur = dist_cur_center >= (zr - 15.0)
        outside_next = dist_next_center >= (next_r - 10.0)

        if outside_cur or (outside_next and zone.get("shrink_start", 0) <= obs["t"]):
            # URGENT: Move into safe zone
            move_x = to_safe_x
            move_y = to_safe_y
            should_boost = not me["in_zone"] or (outside_cur and energy > 20)
        else:
            # Safely inside: Ring-hugger patrol
            # Target radius: 65% of next_radius
            target_r = max(15.0, next_r * 0.65)
            r_diff = target_r - dist_next_center

            # Tangent vector for circling
            tan_x = -to_safe_y
            tan_y = to_safe_x

            # Radial correction
            radial_x = -to_safe_x * (r_diff / max(1.0, target_r))
            radial_y = -to_safe_y * (r_diff / max(1.0, target_r))

            patrol_x = tan_x * 0.7 + radial_x * 0.7
            patrol_y = tan_y * 0.7 + radial_y * 0.7

            move_x = patrol_x
            move_y = patrol_y

            # If cube nearby and safe, steer toward cube
            if obs.get("cubes") and d_enemy > 45.0:
                cubes = sorted(obs["cubes"], key=lambda cb: math.dist(cb["pos"][:2], (x, y)))
                cb_pos = cubes[0]["pos"]
                d_cb = math.dist(cb_pos[:2], (x, y))
                if d_cb < 25.0:
                    cb_dir_x = (cb_pos[0] - x) / max(0.1, d_cb)
                    cb_dir_y = (cb_pos[1] - y) / max(0.1, d_cb)
                    move_x = move_x * 0.4 + cb_dir_x * 0.6
                    move_y = move_y * 0.4 + cb_dir_y * 0.6

            # If high-value pickup nearby, steer toward it
            if best_pickup and d_enemy > 40.0 and best_p_dist < 30.0:
                p_dir_x = (best_pickup["pos"][0] - x) / max(0.1, best_p_dist)
                p_dir_y = (best_pickup["pos"][1] - y) / max(0.1, best_p_dist)
                move_x = move_x * 0.3 + p_dir_x * 0.7
                move_y = move_y * 0.3 + p_dir_y * 0.7

        # -------------------------------------------------------------
        # 6. COMBAT KITING & REAR ARMOR PROTECTION
        # -------------------------------------------------------------
        if nearest_enemy and d_enemy < 50.0:
            # Enemy is too close! Backpedal / kite away
            flee_x = (x - nearest_enemy["pos"][0]) / max(0.1, d_enemy)
            flee_y = (y - nearest_enemy["pos"][1]) / max(0.1, d_enemy)

            # Blend flee with staying in zone
            if dist_next_center < (next_r - 20.0):
                # We have room to flee
                move_x = flee_x * 0.8 + to_safe_x * 0.2
                move_y = flee_y * 0.8 + to_safe_y * 0.2
            else:
                # Strafe around enemy while moving toward safe center
                strafe_x = -flee_y
                strafe_y = flee_x
                move_x = strafe_x * 0.6 + to_safe_x * 0.4
                move_y = strafe_y * 0.6 + to_safe_y * 0.4

            if d_enemy < 25.0 and energy > 35:
                should_boost = True

        # -------------------------------------------------------------
        # 7. PROJECTILE DODGING
        # -------------------------------------------------------------
        for proj in obs.get("projectiles", []):
            pr_pos = proj["pos"]
            pr_vel = proj["vel"]
            p_dist = math.dist(pr_pos[:2], (x, y))
            if p_dist < 35.0:
                # Vector from projectile to me
                rel_x = x - pr_pos[0]
                rel_y = y - pr_pos[1]
                # Is projectile moving towards me?
                dot = rel_x * pr_vel[0] + rel_y * pr_vel[1]
                if dot > 0:
                    # Strafe perpendicular to projectile trajectory
                    v_mag = math.hypot(pr_vel[0], pr_vel[1])
                    if v_mag > 1.0:
                        perp_x = -pr_vel[1] / v_mag
                        perp_y = pr_vel[0] / v_mag
                        move_x += perp_x * 1.2
                        move_y += perp_y * 1.2
                        if p_dist < 18.0 and energy > 25:
                            should_boost = True

        # Normalize move vector
        move_len = math.hypot(move_x, move_y)
        if move_len > 1.0:
            move_x /= move_len
            move_y /= move_len

        act["move"] = [move_x, move_y]
        act["boost"] = should_boost
        act["jump"] = (tick % 60 == 0) and me["grounded"] and not should_boost

        # Debug drawing
        if target_point:
            mf.draw.line([x, y, z + self.muzzle_height], target_point, "#00ff88")
        mf.draw.point([next_c[0], next_c[1], z], "#40c0ff", 5)
        status_text = f"HP:{hp:.0f} En:{energy:.0f} W1:{w1_kind or 'none'}"
        mf.draw.label(status_text)

        return act


mf.run(Bot)
