"""
ApexSurvivor v3 - Shadow Walker & Ballistic Tactician
Features:
- Fast 2D Spatial-Hash Raycasting for Building Collisions & Cover
- Whisker-based Obstacle Avoidance (never get stuck on walls)
- Anti-Stuck Detection with Evasive Jet/Jump
- Line-of-Sight Breaking (lose the 15-bot swarm behind buildings)
- Low-HP Target Finishing (+Cubes, +Heal)
- Tactical Pre-Reloading
- Ballistic Lead Aiming & Rear-Armor Protection
"""
import os
import json
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
    return (target - current + math.pi) % (2 * math.pi) - math.pi


def seg_intersect(p1, p2, p3, p4):
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1)
    if abs(denom) < 1e-9:
        return False
    ua = ((x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)) / denom
    ub = ((x2 - x1) * (y1 - y3) - (y2 - y1) * (x1 - x3)) / denom
    return 0 <= ua <= 1 and 0 <= ub <= 1


class SpatialGrid:
    def __init__(self, edges, cell_size=35.0):
        self.cell_size = cell_size
        self.grid = {}
        for e in edges:
            min_gx = int(min(e[0], e[2]) // cell_size)
            max_gx = int(max(e[0], e[2]) // cell_size)
            min_gy = int(min(e[1], e[3]) // cell_size)
            max_gy = int(max(e[1], e[3]) // cell_size)
            for gx in range(min_gx, max_gx + 1):
                for gy in range(min_gy, max_gy + 1):
                    self.grid.setdefault((gx, gy), []).append(e)

    def ray_hits(self, start, end):
        cs = self.cell_size
        min_gx = int(min(start[0], end[0]) // cs)
        max_gx = int(max(start[0], end[0]) // cs)
        min_gy = int(min(start[1], end[1]) // cs)
        max_gy = int(max(start[1], end[1]) // cs)
        tested = set()
        p1 = (start[0], start[1])
        p2 = (end[0], end[1])
        for gx in range(min_gx, max_gx + 1):
            for gy in range(min_gy, max_gy + 1):
                for e in self.grid.get((gx, gy), []):
                    eid = id(e)
                    if eid not in tested:
                        tested.add(eid)
                        if seg_intersect(p1, p2, (e[0], e[1]), (e[2], e[3])):
                            return True
        return False


class Bot:
    name = "ApexSurvivor-v3"

    def __init__(self, hello: mf.Hello):
        cfg = hello.get("config", {})
        self.pickup_radius = cfg.get("loot", {}).get("pickup_radius", 3.5)
        self.muzzle_height = cfg.get("mech", {}).get("muzzle_height", 7.0)
        self.bullet_speed = cfg.get("weapons", {}).get("gun", {}).get("speed", 252.0)

        # Build Map Obstacle Grid
        map_dir = hello.get("map", {}).get("dir", "/arena")
        world_path = os.path.join(map_dir, "v2/world.json")
        if not os.path.exists(world_path):
            world_path = os.path.join(os.path.dirname(__file__), "../mechfight-kit/arena/v2/world.json")

        edges = []
        if os.path.exists(world_path):
            try:
                with open(world_path, "r") as f:
                    w = json.load(f)
                for p in w.get("prisms", []):
                    if p.get("top", 0) - p.get("base", 0) > 2.0:
                        ring = p.get("ring", [])
                        n = len(ring) // 2
                        for i in range(n):
                            j = (i + 1) % n
                            edges.append((ring[2 * i], ring[2 * i + 1], ring[2 * j], ring[2 * j + 1]))
            except Exception:
                pass
        self.grid = SpatialGrid(edges, cell_size=35.0)

        # State tracking
        self.stuck_ticks = 0
        self.last_pos = [0.0, 0.0]
        self.unstuck_dir = None
        self.unstuck_ticks_left = 0

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
        # 3. THREAT IDENTIFICATION & TARGETING
        # -------------------------------------------------------------
        enemies = [m for m in obs.get("mechs", []) if m["kind"] == "mech"]

        # Prioritize low-HP mechs (finisher bonus for cubes/healing), then by distance
        def enemy_priority(m):
            d = math.dist(m["pos"][:2], (x, y))
            e_hp = m.get("hp", 1000)
            if e_hp < 220 and d < 65.0:
                return -1000 + d  # Finish off weak bot!
            return d

        enemies.sort(key=enemy_priority)
        primary_target = enemies[0] if enemies else None
        d_target = math.dist(primary_target["pos"][:2], (x, y)) if primary_target else 999.0

        # -------------------------------------------------------------
        # 4. AIMING & BALLISTIC LEAD PREDICTION
        # -------------------------------------------------------------
        desired_yaw = actual_aim_yaw
        desired_pitch = 0.0
        fire_slot0 = False
        fire_slot1 = False
        target_point = None

        if primary_target:
            ep = primary_target["pos"]
            ev = primary_target["vel"]
            tx, ty, tz = ep[0], ep[1], ep[2] + 4.5
            dist_to_target = math.dist((x, y, z + self.muzzle_height), (tx, ty, tz))

            t_flight = dist_to_target / self.bullet_speed
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

            yaw_err = abs(angle_diff(desired_yaw, actual_aim_yaw))
            pitch_err = abs(desired_pitch - actual_aim_pitch)

            # Slot 0: Main Gun
            w0 = me["weapons"][0]
            if w0 and w0["reload"] == 0 and yaw_err < 0.20 and pitch_err < 0.25:
                fire_slot0 = True

            # Slot 1: Special Weapon
            if current_w1:
                kind = current_w1["kind"]
                if kind == "laser":
                    # Only charge if not in extreme close danger
                    if d_target > 28.0 and yaw_err < 0.30:
                        charge = current_w1.get("charge", 0.0)
                        if charge >= 0.70:
                            fire_slot1 = False
                        else:
                            fire_slot1 = True
                    else:
                        fire_slot1 = False
                elif kind == "lightning":
                    if d_target <= 45.0 and yaw_err < 0.45:
                        fire_slot1 = True
                elif kind == "mortar":
                    if 40.0 < d_target < 200.0 and yaw_err < 0.3:
                        fire_slot1 = True

        elif obs.get("crates"):
            # Shoot nearby crate for power cubes
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

        # Tactical Pre-Reload
        w0 = me["weapons"][0]
        if w0 and w0["reload"] == 0 and w0["ammo"] <= 3 and d_target > 40.0:
            act["reload"] = True

        act["aim"] = [desired_yaw, desired_pitch]
        act["fire"] = [fire_slot0, fire_slot1]

        # -------------------------------------------------------------
        # 5. MOVEMENT: RING PATROL & LINE-OF-SIGHT COVER
        # -------------------------------------------------------------
        zone = obs["zone"]
        zc = zone["center"]
        zr = zone["radius"]
        next_c = zone["next_center"]
        next_r = zone["next_radius"]

        dist_cur_center = math.dist((x, y), zc)
        dist_next_center = math.dist((x, y), next_c)

        to_safe_x = (next_c[0] - x) / max(0.1, dist_next_center)
        to_safe_y = (next_c[1] - y) / max(0.1, dist_next_center)

        move_x = 0.0
        move_y = 0.0
        should_boost = False

        outside_cur = dist_cur_center >= (zr - 15.0)
        outside_next = dist_next_center >= (next_r - 12.0)

        if outside_cur or (outside_next and zone.get("shrink_start", 0) <= obs["t"]):
            # Urgent return to zone
            move_x = to_safe_x
            move_y = to_safe_y
            should_boost = not me["in_zone"] or (outside_cur and energy > 20)
        else:
            # Circle zone at 65% radius
            target_r = max(15.0, next_r * 0.65)
            r_diff = target_r - dist_next_center

            tan_x = -to_safe_y
            tan_y = to_safe_x
            radial_x = -to_safe_x * (r_diff / max(1.0, target_r))
            radial_y = -to_safe_y * (r_diff / max(1.0, target_r))

            move_x = tan_x * 0.7 + radial_x * 0.7
            move_y = tan_y * 0.7 + radial_y * 0.7

            # Cube collecting
            if obs.get("cubes") and d_target > 40.0:
                cubes = sorted(obs["cubes"], key=lambda cb: math.dist(cb["pos"][:2], (x, y)))
                cb_pos = cubes[0]["pos"]
                d_cb = math.dist(cb_pos[:2], (x, y))
                if d_cb < 25.0:
                    cb_dir_x = (cb_pos[0] - x) / max(0.1, d_cb)
                    cb_dir_y = (cb_pos[1] - y) / max(0.1, d_cb)
                    move_x = move_x * 0.35 + cb_dir_x * 0.65
                    move_y = move_y * 0.35 + cb_dir_y * 0.65

            # Weapon pickup
            if best_pickup and d_target > 35.0 and best_p_dist < 30.0:
                p_dir_x = (best_pickup["pos"][0] - x) / max(0.1, best_p_dist)
                p_dir_y = (best_pickup["pos"][1] - y) / max(0.1, best_p_dist)
                move_x = move_x * 0.25 + p_dir_x * 0.75
                move_y = move_y * 0.25 + p_dir_y * 0.75

        # -------------------------------------------------------------
        # 6. COMBAT KITING & COVER SEEKING
        # -------------------------------------------------------------
        if primary_target and d_target < 52.0:
            flee_x = (x - primary_target["pos"][0]) / max(0.1, d_target)
            flee_y = (y - primary_target["pos"][1]) / max(0.1, d_target)

            if dist_next_center < (next_r - 20.0):
                move_x = flee_x * 0.85 + to_safe_x * 0.15
                move_y = flee_y * 0.85 + to_safe_y * 0.15
            else:
                strafe_x = -flee_y
                strafe_y = flee_x
                move_x = strafe_x * 0.6 + to_safe_x * 0.4
                move_y = strafe_y * 0.6 + to_safe_y * 0.4

            if d_target < 24.0 and energy > 30:
                should_boost = True

        # -------------------------------------------------------------
        # 7. PROJECTILE DODGING
        # -------------------------------------------------------------
        for proj in obs.get("projectiles", []):
            pr_pos = proj["pos"]
            pr_vel = proj["vel"]
            p_dist = math.dist(pr_pos[:2], (x, y))
            if p_dist < 32.0:
                rel_x = x - pr_pos[0]
                rel_y = y - pr_pos[1]
                dot = rel_x * pr_vel[0] + rel_y * pr_vel[1]
                if dot > 0:
                    v_mag = math.hypot(pr_vel[0], pr_vel[1])
                    if v_mag > 1.0:
                        perp_x = -pr_vel[1] / v_mag
                        perp_y = pr_vel[0] / v_mag
                        move_x += perp_x * 1.4
                        move_y += perp_y * 1.4
                        if p_dist < 16.0 and energy > 20:
                            should_boost = True

        # -------------------------------------------------------------
        # 8. WHISKER-BASED BUILDING AVOIDANCE & UNSTUCK LOGIC
        # -------------------------------------------------------------
        # Normalize baseline desired move
        m_len = math.hypot(move_x, move_y)
        if m_len > 0.05:
            base_dir_x = move_x / m_len
            base_dir_y = move_y / m_len
        else:
            base_dir_x, base_dir_y = to_safe_x, to_safe_y

        # Stuck detection
        moved_dist = math.hypot(x - self.last_pos[0], y - self.last_pos[1])
        if m_len > 0.2 and moved_dist < 0.2 and me["grounded"]:
            self.stuck_ticks += 1
        else:
            self.stuck_ticks = 0

        self.last_pos = [x, y]

        if self.stuck_ticks > 3 or self.unstuck_ticks_left > 0:
            if self.unstuck_ticks_left <= 0:
                # Trigger unstuck: perpendicular jump-boost
                self.unstuck_dir = [-base_dir_y, base_dir_x]
                self.unstuck_ticks_left = 6
            self.unstuck_ticks_left -= 1
            move_x, move_y = self.unstuck_dir[0], self.unstuck_dir[1]
            act["jump"] = me["grounded"]
            should_boost = energy > 20
        else:
            # Check 7 whisker rays ahead (angles: 0, +30, -30, +60, -60, +90, -90 deg)
            base_angle = math.atan2(base_dir_y, base_dir_x)
            angles_to_try = [0, 0.52, -0.52, 1.05, -1.05, 1.57, -1.57]
            chosen_dir = None
            ray_dist = 6.5

            for da in angles_to_try:
                test_a = base_angle + da
                test_dx = math.cos(test_a)
                test_dy = math.sin(test_a)
                p_end = (x + test_dx * ray_dist, y + test_dy * ray_dist)
                if not self.grid.ray_hits((x, y), p_end):
                    chosen_dir = [test_dx, test_dy]
                    break

            if chosen_dir:
                move_x, move_y = chosen_dir[0], chosen_dir[1]
            else:
                # All front rays blocked, turn 180 and jump
                move_x, move_y = -base_dir_x, -base_dir_y
                act["jump"] = me["grounded"]

        # Final move vector clamp
        final_len = math.hypot(move_x, move_y)
        if final_len > 1.0:
            move_x /= final_len
            move_y /= final_len

        act["move"] = [move_x, move_y]
        act["boost"] = should_boost
        if "jump" not in act:
            act["jump"] = (tick % 70 == 0) and me["grounded"] and not should_boost

        # Visual debug lines
        if target_point:
            mf.draw.line([x, y, z + self.muzzle_height], target_point, "#ff3333")
        mf.draw.point([next_c[0], next_c[1], z], "#00e5ff", 6)
        mf.draw.label(f"HP:{hp:.0f} | v3-Shadow | En:{energy:.0f}")

        return act


mf.run(Bot)
