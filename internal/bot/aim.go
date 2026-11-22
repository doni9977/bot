package bot

import "math"

type shot struct {
	ok         bool
	yaw, pitch float64
	tf         float64
	point      [3]float64
	dist       float64
	clear      bool
}

const fireLatency = 0.075

type aimTarget struct {
	pos, vel        [3]float64
	radius, centerZ float64
	mech            bool
	lead            float64
	leadSet         bool
	gunLead         float64
	gunLeadSet      bool
	rear, hasMortar bool
}

func (b *Bot) isRear(tr *Track) bool {
	if tr == nil || tr.NPC {
		return false
	}
	halfFront := b.mech("front_arc_deg", 180) * 0.5 * math.Pi / 180
	bear := math.Atan2(b.pos[1]-tr.Pos[1], b.pos[0]-tr.Pos[0])
	return math.Abs(angDiff(tr.Aim[0], bear)) > halfFront
}

func (b *Bot) gunLead(tr *Track) float64 {
	if tr.NPC {
		return 1
	}
	// from ahmad-ovh/Buildathon@56e0f76b (MIT): per-opponent learned lead
	if b.P.LeadCum && tr.leadN >= b.P.LeadCumMin {
		margin := 0.2 * tr.leadN
		if tr.missNone < tr.missLead-margin {
			return 0
		}
		if tr.missLead < tr.missNone-margin {
			return 1
		}
	}
	return b.leadPersistAt(tr, b.t)
}

func (b *Bot) targetOf(tr *Track) aimTarget {
	if tr.NPC {
		return aimTarget{pos: tr.Pos, vel: tr.Vel, radius: stat(b.C.Npc, "radius", 1.8), centerZ: stat(b.C.Npc, "height", 3.5) * 0.5}
	}
	sc := tr.scale(b.sizePerCube)
	at := aimTarget{pos: tr.Pos, vel: tr.Vel, radius: b.mech("radius", 2.5) * sc, centerZ: 4.5 * sc, mech: true, rear: b.isRear(tr), hasMortar: tr.Mortar}
	at.gunLead, at.gunLeadSet = b.gunLead(tr), true
	return at
}

func (b *Bot) leadDamp(tf float64) float64 {
	if tf <= 0.3 {
		return 1
	}
	d := 1 - (tf-0.3)/0.5*(1-b.P.LeadDamp)
	if d < b.P.LeadDamp {
		d = b.P.LeadDamp
	}
	return d
}

func (b *Bot) solveDirectLat(tg aimTarget, speed, originH, lat float64) shot {
	ox := b.pos[0] + b.vel[0]*lat
	oy := b.pos[1] + b.vel[1]*lat
	oz := b.pos[2] + originH
	if !b.o.Self.Grounded {
		oz += b.vel[2] * lat
	}
	tf := 0.0
	var px, py, pz float64
	k := 1.0
	if tg.leadSet {
		k = tg.lead
	}
	// from ahmad-ovh/Buildathon@56e0f76b (MIT): 4-pass ballistic solve with vertical lead
	for it := 0; it < 4; it++ {
		damp := b.leadDamp(tf)
		px = tg.pos[0] + tg.vel[0]*(lat+tf*damp)*k
		py = tg.pos[1] + tg.vel[1]*(lat+tf*damp)*k
		vz := clamp(tg.vel[2], -15, 12)
		pz = tg.pos[2] + tg.centerZ + vz*(lat+tf)*0.6
		if speed <= 0 {
			break
		}
		d := math.Sqrt((px-ox)*(px-ox) + (py-oy)*(py-oy) + (pz-oz)*(pz-oz))
		tf = math.Max(0, d-3) / speed
	}
	hd := hyp(px-ox, py-oy)
	s := shot{ok: true, tf: tf, point: [3]float64{px, py, pz}}
	s.yaw = math.Atan2(py-oy, px-ox)
	s.pitch = math.Atan2(pz-oz, hd)
	s.dist = math.Sqrt(hd*hd + (pz-oz)*(pz-oz))
	if s.dist > 1e-3 {
		dx, dy, dz := (px-ox)/s.dist, (py-oy)/s.dist, (pz-oz)/s.dist
		reach := s.dist - tg.radius*0.9
		if reach < 0.5 {
			s.clear = true
		} else {
			s.clear = b.W.Raycast(ox, oy, oz, dx, dy, dz, reach) >= reach-1e-6
		}
	} else {
		s.clear = true
	}
	return s
}

func (b *Bot) solveMortar(tg aimTarget, st map[string]float64) shot {
	v := stat(st, "speed", 72)
	g := stat(st, "gravity", 22)
	lat := fireLatency
	ox := b.pos[0] + b.vel[0]*lat
	oy := b.pos[1] + b.vel[1]*lat
	oz := b.pos[2] + b.height + 0.5*b.scale
	minP := b.mech("min_pitch", -0.7)
	maxP := b.mech("max_pitch", 1.3)
	for arc := 0; arc < 2; arc++ {
		tf := 0.6
		var th, px, py, pz float64
		ok := true
		for it := 0; it < 5; it++ {
			damp := b.leadDamp(tf)
			px = tg.pos[0] + tg.vel[0]*(lat+tf*damp)
			py = tg.pos[1] + tg.vel[1]*(lat+tf*damp)
			pz, _ = b.W.Floor(px, py, tg.pos[2]+3)
			pz += 0.3
			d := hyp(px-ox, py-oy)
			if d < 1 {
				ok = false
				break
			}
			h := pz - oz
			disc := v*v*v*v - g*(g*d*d+2*h*v*v)
			if disc < 0 {
				ok = false
				break
			}
			sq := math.Sqrt(disc)
			if arc == 0 {
				th = math.Atan2(v*v-sq, g*d)
			} else {
				th = math.Atan2(v*v+sq, g*d)
			}
			c := math.Cos(th)
			if c < 0.05 {
				ok = false
				break
			}
			tf = d / (v * c)
		}
		if !ok || th < minP || th > maxP {
			continue
		}
		if tf > stat(st, "ttl", 7)-0.3 {
			continue
		}
		s := shot{ok: true, tf: tf, point: [3]float64{px, py, pz}, pitch: th}
		s.yaw = math.Atan2(py-oy, px-ox)
		s.dist = hyp(px-ox, py-oy)
		s.clear = true
		cy, sy := math.Cos(s.yaw), math.Sin(s.yaw)
		vh, vz := v*math.Cos(th), v*math.Sin(th)
		lx, ly, lz := ox+cy*3*math.Cos(th), oy+sy*3*math.Cos(th), oz+3*math.Sin(th)
		n := int(tf/0.12) + 2
		for i := 1; i <= n; i++ {
			tt := tf * float64(i) / float64(n)
			if i == n {
				tt = tf - 0.04
			}
			nx, ny, nz := ox+cy*vh*tt, oy+sy*vh*tt, oz+vz*tt-0.5*g*tt*tt
			if !b.W.Visible(lx, ly, lz, nx, ny, nz) {
				if hyp(nx-px, ny-py) > 3.5 {
					s.clear = false
				}
				break
			}
			lx, ly, lz = nx, ny, nz
		}
		if s.clear {
			return s
		}
	}
	return shot{}
}

func (b *Bot) aimErr(s shot) (float64, float64) {
	ey := math.Abs(angDiff(s.yaw, b.aim[0])) - b.turn*b.dt*0.9
	ep := math.Abs(s.pitch-b.aim[1]) - b.pitchR*b.dt*0.9
	if ey < 0 {
		ey = 0
	}
	if ep < 0 {
		ep = 0
	}
	return ey, ep
}

func (b *Bot) laserDamageAt(st map[string]float64, charge float64) float64 {
	full := stat(st, "charge", 0.75)
	mf := stat(st, "min_frac", 0.35)
	f := 1.0
	if full > 0 {
		f = clamp(charge/full, 0, 1)
	}
	return stat(st, "damage", 315) * (mf + (1-mf)*f) * b.cubeDamageMul(b.o.Self.Cubes)
}

func (b *Bot) engage(act *Action, tg aimTarget, hasLOS, losRecent bool, hpLeft float64, allowFire bool) {
	gunI, lasI, ligI, morI := b.has("gun"), b.has("laser"), b.has("lightning"), b.has("mortar")
	var gunS, lasS, morS shot
	// from ahmad-ovh/Buildathon@56e0f76b (MIT): head-aim fallback and cooldown-aware latency
	headTg := tg
	headOK := false
	if tg.mech {
		headTg.centerZ = tg.centerZ * 1.82
		headTg.radius = tg.radius * 0.8
		headOK = true
	}
	pitchTol := tg.centerZ * 0.8
	if gunI >= 0 {
		gunTg, gunHead := tg, headTg
		if tg.gunLeadSet {
			gunTg.lead, gunTg.leadSet = tg.gunLead, true
			gunHead.lead, gunHead.leadSet = tg.gunLead, true
		}
		gunLat := fireLatency
		if b.P.SmartFireV2 {
			if b.slots[gunI].cooldown <= b.dt+1e-6 {
				gunLat = b.dt
			} else {
				gunLat = b.decide
			}
		}
		gunS = b.solveDirectLat(gunTg, stat(b.slots[gunI].stats, "speed", 252), b.muzzleH, gunLat)
		if !gunS.clear && headOK {
			if alt := b.solveDirectLat(gunHead, stat(b.slots[gunI].stats, "speed", 252), b.muzzleH, gunLat); alt.clear {
				gunS = alt
				pitchTol = 0.7
			}
		}
	}
	if lasI >= 0 || ligI >= 0 {
		lasLat := fireLatency
		if b.P.SmartFireV2 {
			lasLat = b.dt
		}
		lasS = b.solveDirectLat(tg, 0, b.muzzleH, lasLat)
		if !lasS.clear && headOK {
			if alt := b.solveDirectLat(headTg, 0, b.muzzleH, lasLat); alt.clear {
				lasS = alt
				pitchTol = 0.7
			}
		}
	}
	if morI >= 0 {
		morS = b.solveMortar(tg, b.slots[morI].stats)
	}
	d := dist3([3]float64{b.pos[0], b.pos[1], b.pos[2] + b.muzzleH}, [3]float64{tg.pos[0], tg.pos[1], tg.pos[2] + tg.centerZ})

	primary := lasS
	usingMortarAim := false
	gunPrimary := false
	if gunI >= 0 {
		primary = gunS
		gunPrimary = true
	}
	laserReady := false
	if lasI >= 0 {
		sl := &b.slots[lasI]
		full := stat(sl.stats, "charge", 0.75)
		if sl.charge > 0 && (sl.charge >= full-0.16 || b.laserDamageAt(sl.stats, sl.charge+0.1) >= hpLeft) {
			laserReady = true
			primary = lasS
			gunPrimary = false
		}
		if gunI < 0 {
			primary = lasS
		}
	}
	if morI >= 0 && morS.ok && morS.clear && b.slots[morI].cooldown <= 0.15 && !laserReady {
		gunIdle := gunI < 0 || b.slots[gunI].reload > 0 || b.slots[gunI].ammo == 0 || !gunS.clear || d > b.P.GunMaxRange
		if allowFire && (b.mortarWorth(tg, morS, d) || (gunIdle && morS.dist > 25)) {
			primary = morS
			usingMortarAim = true
			gunPrimary = false
		}
	}
	if !primary.ok {
		return
	}
	act.Aim = [2]float64{primary.yaw, clamp(primary.pitch, b.mech("min_pitch", -0.7), b.mech("max_pitch", 1.3))}
	act.HasAim = true
	if !allowFire && !(lasI >= 0 && b.slots[lasI].charge > 0) {
		return
	}

	if gunI >= 0 && allowFire {
		sl := &b.slots[gunI]
		if sl.ammo <= 0 && sl.reload <= 0 {
			act.Reload = true
		}
		rng := stat(sl.stats, "range", 230)
		maxR := math.Min(rng-5, b.P.GunMaxRange)
		if !tg.mech {
			maxR = math.Min(rng-5, 120)
		}
		if hasLOS && gunS.clear && sl.ammo > 0 && sl.reload <= 0 && gunS.dist < maxR {
			ey, ep := b.aimErr(gunS)
			if !gunPrimary {
				ey = math.Abs(angDiff(gunS.yaw, b.aim[0]))
				ep = math.Abs(gunS.pitch - b.aim[1])
			}
			tolY := math.Atan2(tg.radius*0.8, math.Max(gunS.dist, 1))
			tolP := math.Atan2(pitchTol, math.Max(gunS.dist, 1))
			if ey < tolY && ep < tolP {
				act.Fire[gunI] = true
			}
		}
	}
	if lasI >= 0 {
		sl := &b.slots[lasI]
		rng := stat(sl.stats, "range", 280) - 4
		full := stat(sl.stats, "charge", 0.75)
		inRange := lasS.dist < rng
		if sl.charge > 0 {
			hold := true
			// from ahmad-ovh/Buildathon@56e0f76b (MIT): rear/cookoff lethality, early release
			lasMult := 1.0
			if b.P.SmartFireV2 && tg.rear {
				lasMult *= b.mech("rear_mult", 1.5)
			}
			if (b.P.SmartFireV2 || b.P.CookoffAware) && tg.hasMortar {
				lasMult *= 1 + stat(b.C.Weapons["laser"], "cookoff", 0)
			}
			lethal := b.laserDamageAt(sl.stats, sl.charge)*lasMult >= hpLeft && sl.charge >= stat(sl.stats, "min_charge", 0.15)
			relThr := full - 1e-3
			if b.P.LaserEarlyRel {
				relThr = full - b.dt - 1e-3
			}
			if (sl.charge >= relThr || lethal) && hasLOS && lasS.clear && inRange {
				ey, ep := b.aimErr(lasS)
				tolY := math.Atan2(tg.radius*0.75, math.Max(lasS.dist, 1))
				tolP := math.Atan2(pitchTol*0.9, math.Max(lasS.dist, 1))
				if ey < tolY && ep < tolP {
					hold = false
				}
			}
			act.Fire[lasI] = hold
			b.laserHold = hold
		} else if allowFire && sl.cooldown <= 0.12 && inRange && (hasLOS || losRecent) {
			act.Fire[lasI] = true
			b.laserHold = true
		}
	}
	if !allowFire {
		return
	}
	if ligI >= 0 {
		sl := &b.slots[ligI]
		rng := stat(sl.stats, "range", 45)
		cone := stat(sl.stats, "cone_deg", 30) * math.Pi / 180
		cost := stat(sl.stats, "energy", 3)
		if hasLOS && lasS.clear && d < rng-1.0-0.5*hyp(tg.vel[0]-b.vel[0], tg.vel[1]-b.vel[1])*0.1 && b.energy >= cost {
			ey := math.Abs(angDiff(lasS.yaw, b.aim[0])) - b.turn*b.dt*0.9
			if ey < cone*0.4 {
				act.Fire[ligI] = true
			}
		}
	}
	if morI >= 0 && morS.ok && morS.clear {
		sl := &b.slots[morI]
		if sl.cooldown <= 0.05 && usingMortarAim {
			ey, ep := b.aimErr(morS)
			if ey < 0.03 && ep < 0.02 {
				act.Fire[morI] = true
			}
		}
	}
}

func (b *Bot) mortarWorth(tg aimTarget, s shot, d float64) bool {
	splash := 7.0
	if i := b.has("mortar"); i >= 0 {
		splash = stat(b.slots[i].stats, "splash_radius", 7)
	}
	if s.dist < splash+b.radius+3 {
		return false
	}
	sp := hyp(tg.vel[0], tg.vel[1])
	miss := sp * s.tf * 0.5
	if !tg.mech {
		miss = sp * s.tf * 0.2
	}
	return miss < splash*0.75
}

func (b *Bot) idleAim(act *Action, heading float64, haveHeading bool) {
	yaw := b.aim[0]
	switch {
	case b.t < 1.75:
		yaw = b.aim[0] + 0.39
	case b.t-b.lastWeaponDT < 2.5 || b.t-b.lastNpcDT < 2.5:
		yaw = b.lastDmgBear
	case b.t-b.lastSoundT < 1.5:
		yaw = b.lastSoundB
	default:
		b.scanPhase += b.decide
		if haveHeading {
			yaw = heading + 1.9*math.Sin(b.scanPhase*1.3)
		} else {
			yaw = b.aim[0] + 0.35
		}
	}
	act.Aim = [2]float64{yaw, 0}
	act.HasAim = true
}

// ---- hit and DPS models

func gunHitProb(d float64) float64 {
	switch {
	case d < 60:
		return 0.95
	case d < 120:
		return 0.95 - (d-60)/60*0.12
	case d < 180:
		return 0.83 - (d-120)/60*0.10
	case d < 230:
		return 0.73 - (d-180)/50*0.15
	}
	return 0.05
}

func theirGunHitProb(d float64) float64 {
	switch {
	case d < 40:
		return 0.97
	case d < 80:
		return 0.97 - (d-40)/40*0.12
	case d < 120:
		return 0.85 - (d-80)/40*0.40
	case d < 180:
		return 0.45 - (d-120)/60*0.20
	}
	return 0.12
}

func hitTable(d float64, knots [][2]float64) float64 {
	if d <= knots[0][0] {
		return knots[0][1]
	}
	for i := 1; i < len(knots); i++ {
		if d <= knots[i][0] {
			f := (d - knots[i-1][0]) / (knots[i][0] - knots[i-1][0])
			return knots[i-1][1] + (knots[i][1]-knots[i-1][1])*f
		}
	}
	return knots[len(knots)-1][1]
}

var realMyGun = [][2]float64{{30, 0.95}, {60, 0.86}, {100, 0.55}, {150, 0.28}, {200, 0.18}, {230, 0.12}}
var realTheirGun = [][2]float64{{30, 0.92}, {60, 0.78}, {100, 0.57}, {150, 0.32}, {200, 0.15}, {230, 0.10}}

func (b *Bot) myGunHit(d float64) float64 {
	if b.realModel() {
		return hitTable(d, realMyGun)
	}
	return gunHitProb(d)
}

func (b *Bot) theirGunHit(d float64) float64 {
	if b.realModel() {
		return hitTable(d, realTheirGun)
	}
	return theirGunHitProb(d)
}

func (b *Bot) dpsOf(gun, laser, light, mortar bool, cubes int, d float64, energyOK bool, gunHit func(float64) float64) float64 {
	mul := b.cubeDamageMul(cubes)
	w := b.C.Weapons
	total := 0.0
	if gun {
		g := w["gun"]
		cd := stat(g, "cooldown", 0.24)
		mag := stat(g, "mag", 12)
		rl := stat(g, "reload", 2.4)
		if d < stat(g, "range", 230) {
			total += stat(g, "damage", 45) * mag / (mag*cd + rl) * gunHit(d)
		}
	}
	if laser {
		l := w["laser"]
		if d < stat(l, "range", 280) {
			lh := 0.85
			if b.realModel() {
				lh = 0.75
			}
			total += stat(l, "damage", 315) / (stat(l, "charge", 0.75) + stat(l, "cooldown", 1.65)) * lh
		}
	}
	if light && energyOK {
		l := w["lightning"]
		lr := stat(l, "range", 45) + 6
		if d < lr {
			total += stat(l, "damage", 60) / stat(l, "cooldown", 0.25)
		}
	}
	if mortar {
		m := w["mortar"]
		if d > 12 && d < 200 {
			total += stat(m, "damage", 200) / stat(m, "cooldown", 2.6) * 0.25
		}
	}
	return total * mul
}

func (b *Bot) myDPS(d float64) float64 {
	gun := b.has("gun") >= 0 && d < b.P.GunMaxRange
	return b.dpsOf(gun, b.has("laser") >= 0, b.has("lightning") >= 0, b.has("mortar") >= 0, b.o.Self.Cubes, d, b.energy > 15, b.myGunHit)
}

func (b *Bot) theirDPS(tr *Track, d float64) float64 {
	if tr.NPC {
		if d > 95 {
			return 0
		}
		return stat(b.C.Npc, "damage", 25) / stat(b.C.Npc, "cooldown", 1) * 0.5
	}
	gun := tr.Gun || (!tr.Laser && !tr.Mortar && !tr.Light)
	laser := tr.Laser
	if laser {
		if li := b.has("lightning"); li >= 0 && b.energy > 20 && d < stat(b.slots[li].stats, "range", 45)-3 {
			laser = false
		}
		// from ahmad-ovh/Buildathon@56e0f76b (MIT): LaserCDTrack, punish window after an enemy laser shot
		if laser && b.P.LaserCDTrack && !b.ffa && !tr.Charging && tr.LaserFiredT > 0 {
			cdWin := stat(b.C.Weapons["laser"], "cooldown", 1.65) + stat(b.C.Weapons["laser"], "charge", 0.75) - 0.40
			if b.t-tr.LaserFiredT < cdWin {
				laser = false
			}
		}
	}
	return b.dpsOf(gun, laser, tr.Light, tr.Mortar, tr.Cubes, d, true, b.theirGunHit)
}
