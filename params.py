"""Tunable policy knobs.

A local A/B run injects a variant with the BOT_PARAMS environment JSON (or by
passing a dict to Brain).  Production has no such variable, so it uses DEFAULT.
"""
from __future__ import annotations

import json
import os

DEFAULT = {
    # --- zone rotation -------------------------------------------------
    "zone_margin": 0.78,          # stay inside this fraction of the current radius
    "goal_offset": 0.42,          # camp this fraction of next_radius away from next_center
    "goal_candidates": 12,        # candidate hide spots evaluated per decision
    "cover_bias": 0.55,           # weight on nearby solid cover when scoring a hide spot
    "threat_bias": 1.35,          # weight on distance from known threats
    "travel_bias": 0.30,          # weight on travel distance to a hide spot
    "slope_bias": 0.10,           # mild preference for higher ground
    # The ring of candidates is scored by endpoint distance only, so the bot
    # happily drives *through* a visible squad to reach a spot that is a few
    # metres farther from their centroid.  Score the path instead, and keep a
    # goal for a few seconds so the argmax cannot flip every decision.
    "path_threat_r": 60.0,        # clearance from a visible enemy along the route
    "path_threat_bias": 1.6,      # weight on route clearance
    "goal_replan_s": 6.0,         # hold a goal this long before re-scoring
    "goal_hyst": 14.0,            # score margin required to abandon a held goal
    "emergency_boost": True,      # boost while outside the circle / when the shrink is closing in
    "quiet_speed": 4.85,          # <= step_speed (5 m/s) makes no footstep sound
    "quiet_when_safe": True,      # move silently when no threat is close
    # --- engagement ----------------------------------------------------
    "aggression": 1.0,            # 0 = pure pacifist, 1 = fight anything in range
    "engage_range": 240.0,        # only consider fighting inside this range
    "fire_enabled": True,
    "fire_max_range": 175.0,
    # The gate used to only scale candidate utility while the weapon branches
    # passed a literal fire=True, so a zeroed candidate could still win the argmax
    # and shoot.  That is why every fire-discipline experiment measured flat.
    # Strict mode propagates the permission bit into the fire flag.
    "fire_gate_strict": False,    # A/B: see EXPERIMENTS E35
    "early_farm_until": 150.0,    # farm crates / NPCs / drops before this match time
    "late_survival_t": 250.0,     # after this, never shoot unless cornered
    "hp_floor": 0.28,             # below this HP fraction, disengage completely
    # Silence only helps while nobody is shooting at us.  Once a visible enemy
    # is in gun range and landing damage, not returning fire is strictly worse
    # than trading: the kiting loop alone cannot outrun bullets.
    "recip_fire": True,           # return fire when damaged by a visible enemy in range
    "recip_fire_hp": 0.45,        # ... but not below this HP fraction (disengage instead)
    "recip_fire_window_s": 2.5,   # damage this recent counts as "in a fight"
    "retreat_hp": 0.55,
    "pressure_hide": 2,           # number of recent damage events that triggers hard hiding
    "face_threat": True,          # turn torso toward the attacker (front arc avoids x1.5)
    "scan_enabled": True,         # sweep the torso when idle to widen the vision wedge
    "scan_period_s": 7.0,
    # --- weapons -------------------------------------------------------
    "weapon_pref": ["laser", "lightning", "mortar", "gun"],
    "gun_min_hit": 1.25,          # fire only if predicted miss < this * target radius
    # Damage split across many targets produces damage but no kills, and place
    # only improves when a bot actually dies.
    "aim_height_frac": 0.5,       # aim point on the target body (0.5 = mid-body)
    "focus_fire": True,           # keep shooting the same target until it dies
    "focus_switch_margin": 55.0,  # score advantage required to switch target
    "laser_min_charge": 0.45,
    "laser_precharge": False,     # A/B: -0.16 score, so off
    "mortar_self_safe": 11.0,     # never lob a shell whose impact is closer than this
    "mortar_indirect": False,     # A/B: -0.28 score, so off
    "lightning_energy_floor": 12.0,
    # --- economy -------------------------------------------------------
    "take_pickups": True,
    "upgrade_exact": True,        # exact hello.config.upgrades marginal effects; false = legacy ranks
    "crate_farm": False,          # shooting crates is loud (320 m gun sound)
    "npc_farm": False,            # NPC drones shoot back and make noise
    "npc_avoid": 42.0,            # keep this distance from drones
    "npc_break_range": 50.0,      # sprint out of drone aggro inside this range
    "npc_break_hold_s": 2.8,      # commit to the break for this long
    "drop_aggression": 0.0,       # 0 = ignore supply drops, 1 = always contest
    # --- hunting -------------------------------------------------------
    # Probe strategy: close on the nearest known enemy and kill it, instead of
    # only ever reacting.  Against the simulator's squad this measures neutral
    # to negative; it exists to test whether the real house bots are weaker
    # than the emulation assumes.
    "hunt_enabled": True,         # actively seek and engage (probe build)
    "hunt_range": 170.0,          # only chase enemies known inside this range
    "hunt_standoff": 45.0,        # close to this distance, then hold
    "hunt_hp": 0.45,              # stop hunting below this HP fraction
    "hunt_until": 420.0,          # stop hunting after this match time
    # Chasing the nearest enemy spreads damage across fresh targets; chasing
    # the weakest one converts it into kills, and place only improves on kills.
    "hunt_target": "weak",        # "weak" = lowest HP first, "near" = closest
    # --- situational controller ----------------------------------------
    # Instead of one fixed aggression for every fight, read the rolling HP
    # exchange: press while out-damaging them, break off when losing it.
    "trade_adapt": False,         # A/B switch
    # A kill drops cubes at the corpse (death_drop + death_drop_extra), and
    # cubes are the only multiplicative stat gain in the game.  Collecting our
    # own kills is low-exposure economy: we are already there.
    "loot_kill_enabled": False,   # A/B switch
    "loot_kill_window_s": 7.0,    # how long the corpse is worth visiting
    "loot_kill_clear_r": 55.0,    # only detour if nothing is this close
    "trade_press_ratio": 1.35,    # dealt/taken above this = winning the trade
    "trade_press_hp": 0.45,       # ... and healthy enough to press
    "trade_flee_ratio": 0.65,     # dealt/taken below this = losing it
    "trade_flee_hp": 0.32,        # ... or this hurt, disengage
    # --- early roam / economy -------------------------------------------
    # Shipped in a33d613 (roam_until 45) and measured OFFICIALLY at 2.50, versus
    # 2.52 for the build without it.  Weapon uptime does rise 8% -> 35% (E37) but
    # the score effect is negative, so the default is back to off.  Kept as a knob
    # because the mechanism is real; the exchange rate is not.
    "roam_until": 0.0,            # actively seek weapons + cubes before this t
    # --- kiting the coordinated squad -----------------------------------
    "kite_enabled": True,         # A/B: +0.55 paired, death t 80 -> 105
    "kite_hp": 0.97,              # break contact below this HP fraction
    "kite_hold_s": 6.0,           # commit to the break-away for this long
    # Kiting from 150 m chip damage is pure loss: it cancels every zone
    # rotation, so the mech oscillates in place and dies where it spawned.
    # Only break contact when the shooter is close enough to press the attack.
    "kite_range": 100.0,          # only kite when the nearest enemy is this close
    # Running straight away from incoming fire is the easiest thing to lead.
    # When breaking contact, prefer a heading that actually puts terrain
    # between us and the shooters: occlusion stops damage, distance does not.
    "kite_cover": True,           # steer the break toward terrain occlusion
    "kite_cover_probe": 34.0,     # how far ahead the break heading is sampled
    "kite_cover_cache_s": 1.0,    # recompute the break heading this often
    "weapon_seek_range": 130.0,
    # Measured: we hold a secondary weapon in only 14% of decisions (laser 8%,
    # lightning 6%), so 86% of the match is fought with the 45-damage gun.  The
    # detour radius was hard-coded at 30 m, which is smaller than the gap between
    # floor spawns, so the bot almost never reached one.
    "pickup_detour_r": 30.0,      # A/B: 80 / 140 (EXPERIMENTS E36)
    "roam_loot_range": 95.0,
    "roam_omega": 0.16,           # rad/s of the exploration sweep
    "roam_goal_frac": 0.55,       # sweep radius as a fraction of the circle
    "cube_detour": 26.0,          # max detour (m) to grab a loose cube
    "upgrade_plating": 10.0,
    "upgrade_armor": 8.5,
    "upgrade_nanites": 7.0,
    "upgrade_capacitor": 4.0,
    "upgrade_jets": 4.0,
    "upgrade_servos": 5.0,
    "upgrade_gyros": 4.5,
    "upgrade_sensors": 3.0,
    "upgrade_gun": 2.0,
    "upgrade_weapon": 2.5,
    # --- evasion -------------------------------------------------------
    "dodge_gain": 1.0,
    "dodge_lead_s": 0.65,
    "laser_dodge_gain": 1.0,
    "strafe_gain": 0.85,
    # Standing on a hide spot while a squad converges makes the mech a static
    # target for mortars and lasers.  Keep drifting until they are far away.
    "strafe_range": 120.0,        # strafe while the nearest enemy is inside this
    "at_goal_stop_r": 120.0,      # only come to a full stop beyond this range
    "stuck_speed": 1.2,           # moved < this many m over 2 s => replan
    "escape_hold_s": 1.6,         # commit to one escape heading for this long
    # --- line-of-sight breaking (survival core) ------------------------
    "cover_enabled": False,       # A/B: neutral in the local sim, costs ~10 ms/decision
    "cover_hp": 0.78,             # seek cover below this HP fraction
    "cover_after_hit": 0.35,      # ...or after this much recent damage pressure
    "cover_min_enemy": 42.0,      # do not try to hide with a mech this close
    "cover_max_r": 18.0,          # search radius for a hidden spot
    "cover_cache_s": 0.6,         # recompute the cover spot this often
    "cover_quiet": True,          # walk at <= step_speed while moving to cover
    # --- protocol-first intelligence / controlled experiments ------------
    "intel_enabled": True,        # belief layer; false restores the old dead-reckoning path
    "sound_goal_bias": 1.0,       # soft zone-goal penalty inside uncertain sound sectors
    "sound_pressure_gain": 0.12,  # pressure from sound/beam/damage sectors -> conservative adapt
    "sound_scan": True,           # bias idle torso scan toward the weighted bearing evidence
    "aim_arbiter": True,          # one final torso aim for both weapon slots; false = legacy path
    # --- adaptive / final generalisation --------------------------------
    "adapt": True,                # modulate policy by observed opponent pressure
    "ffa_mode": False,            # simulator-only: opponents are independent, not a squad
    # --- combat engine v2 (E41) -----------------------------------------
    "combat_v2": False,           # duel commitment, dual-wielding, weapon-aware range, flipping strafe
    "v2_kite_hp": 0.42,           # retreat HP threshold when not finishing a kill
    "v2_multi_kite_hp": 0.72,     # retreat HP threshold when 2+ enemies have direct LOS
    "v2_finish_hp": 420.0,        # commit to kill below this target HP
    "v2_kite_hold_s": 3.5,        # shorter disengage commitment
    "v2_poke_max_r": 95.0,        # don't poke idle full-HP bystanders beyond this (gun)
    "v2_laser_poke_r": 150.0,     # ...or this with laser
    "v2_flip_min_s": 0.65,        # strafe direction flip interval min
    "v2_flip_max_s": 1.05,        # strafe direction flip interval max
    # --- rooftop warfare (E42) ------------------------------------------
    "roof_enabled": False,        # climb buildings with jump+jet, ledge-peek, roof heal cycle
    "roof_heal_hp": 0.62,         # step back & hard-hold-fire to regen below this HP
    "roof_heal_exit": 0.90,       # resume ledge-peeking above this HP
    "roof_reload_duck": True,     # step back behind roof edge during gun reload
    "roof_laser_duck": True,      # step back behind roof edge when enemy charges laser
    "roof_max_seek": 220.0,       # max distance to seek a climbable roof
    # --- snowball economy + weapons_v2 (E43) ----------------------------
    "snowball_v1": True,          # A/B E43: +0.55 ± 0.26 across 96 matches (+0.48 train / +0.62 holdout)
    "weapons_v2": False,          # aligned gun, gun+lightning shared-pitch dual-wield, full/lethal laser, proactive reload
    "upgrade_v2": False,          # fixed EHP/DPS marginal weights (fixes armor=4.80 & plating=10.50 bugs)
    "snowball_npc_farm": True,    # kill nearby NPC drones (350 HP -> 2 cubes) when safe
    "snowball_crate_farm": True,  # break nearby crates (300 HP -> 1 cube + 50% weapon) when safe
    "snowball_pickup_r": 135.0,   # seek remembered/visible weapons within this range
    "snowball_cube_r": 50.0,      # collect visible cubes within this range
    # --- tactical cover + laser-duck + reload-duck + regen hold-fire (E44) -
    "tactical_cover_v1": False,   # laser-charge cover duck, reload cover duck, low-HP regen hold-fire
    "tc_laser_duck": True,        # boost behind cover when enemy charges laser aimed at us
    "tc_reload_duck": True,       # duck behind nearby cover during 2.4s gun reload
    "tc_heal_hold": True,         # hard-hold-fire to regen when hurt & out of close LOS
    "tc_heal_hp": 0.52,           # enter low-HP regen protection below this fraction
    "tc_heal_exit": 0.84,         # resume poking above this fraction
    "tc_heal_close_r": 52.0,      # always fight back if an enemy has LOS inside this range
    # --- snowball v2 (E45): mortar fix, active patrol, drone/crate approach, lightning rush, drops
    "snowball_v2": True,          # A/B E45: +0.625 ± 0.23 across 96 matches (+0.75 holdout, +0.69 kills)
    "sb2_patrol_until": 150.0,    # actively patrol at full speed while hungry for weapon/cubes
    "sb2_light_rush": True,       # suppress 2-hit kite during healthy 1v1 lightning rush
    "sb2_drop_contest": True,     # contest reachable supply drops (full HP + 3 cubes)
    # --- snowball v3 (E46): loot-timeout fix, laser-only duck, 1v1 angle isolation, ballistic mortar dodge, threat-aware kite
    "snowball_v3": True,          # A/B E46b (laser>light): +0.84 ± 0.28 across 96 matches (2.81 train / 2.52 holdout, 2.10 kills)
    "sb3_laser_duck": True,       # pure 0.5s cover-duck on enemy laser telegraph (no fire suppression)
    "sb3_isolate": True,          # 1v1 corner angle isolation when 2+ enemies have LOS
    # --- snowball v4 (E47): laser 82m standoff, opening gear-first, flipping strafe, dynamic kite, laser_charge weight
    "snowball_v4": False,         # A/B test on top of snowball_v3
    "sb4_laser_standoff": 82.0,   # ideal standoff when holding laser (hitscan range, zero enemy lightning)
    "sb4_gear_until": 38.0,       # defer bare-gun hunt until w1 equipped (still fire 100% if in LOS!)
    # --- precision v1 (E48): 1-tick laser slew/lead, rear-bearing snap, no self-slow on laser-duck, finish hunt, fallback indirect mortar
    "precision_v1": False,        # A/B test on top of E46b snowball_v3
    # --- kill snowball v1 (E49): kill-reset kite to scoop 3 cubes + rear-bearing snap + aggressive NPC/crate farm
    "kill_snowball_v1": True,     # ADOPTED E49: 3.15 combined (+1.32 vs BASE, 2.52 kills, 3.12 cubes)
    # --- Apex v2 Python engine (E56+): 3-phase stealth/hunt/FFA + anti-lightning/laser-duck/config-econ/sensors
    "engine_v2": True,
}


def load(params=None):
    """Merge an optional override dict (and an optional BOT_PARAMS env JSON) over DEFAULT."""
    out = dict(DEFAULT)
    raw = os.environ.get("BOT_PARAMS")
    if raw:
        try:
            out.update(json.loads(raw))
        except (ValueError, TypeError):
            pass
    if params:
        out.update(params)
    return out


P = load()
