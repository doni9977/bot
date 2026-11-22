package bot

import (
	"fmt"
	"math"
)

// navCost: extra A* cost per cell (stay inside the zone).
func (b *Bot) navCost() func(k int) float32 {
	z := &b.o.Zone
	cx, cy, r := z.Center[0], z.Center[1], z.Radius
	return func(k int) float32 {
		x, y := b.Nav.Pos(k)
		c := float32(0)
		if hyp(x-cx, y-cy) > r-3 {
			c += 6
		}
		return c
	}
}

func (b *Bot) think(act *Action) {
	b.pickUpgrade(act)
	b.manageWeapons(act)
	st := b.belief()
	b.st = st
	if b.o.Tick%6 == 0 {
		b.markSeen()
	}
	zi := b.zoneInfo()
	ths := b.assess()
	inc := b.gatherIncoming()
	hpFrac := b.hp / b.maxHP

	// §8.3 target
	var tgt *threat
	bestS := -1.0
	engagedDPS := 0.0
	nEngaged := 0
	for i := range ths {
		th := &ths[i]
		if th.engaged {
			engagedDPS += th.dps
			nEngaged++
		}
		if !th.tr.Listed {
			continue
		}
		// from ahmad-ovh/Buildathon@56e0f76b (MIT): focus the weakest engaged target
		s := 1 / (1 + th.d/60)
		if th.tr.LOS {
			s *= 3
		}
		if th.engaged {
			s *= 1.6
		}
		if th.tr.MaxHP > 0 {
			kf := 1.0
			if b.P.KillFocus > 0 {
				kf = b.P.KillFocus
			}
			s *= 1 + kf*(1-th.tr.HP/th.tr.MaxHP)
		}
		if th.tr.ID == b.targetID {
			s *= 1.2
		}
		if b.P.RearBonus > 0 && b.isRear(th.tr) {
			s *= 1 + b.P.RearBonus
		}
		if b.P.CookoffBonus > 0 && b.has("laser") >= 0 && th.tr.Mortar && stat(b.C.Weapons["laser"], "cookoff", 0) > 0 {
			s *= 1 + b.P.CookoffBonus
		}
		if s > bestS {
			bestS, tgt = s, th
		}
	}
	if tgt != nil {
		b.targetID = tgt.tr.ID
	} else {
		b.targetID = -1
	}
	watchers := b.seenBy(ths, 230)

	// §8.4 fight or flee
	underFire := b.t-b.lastWeaponDT < 3.0
	danger := nEngaged > 0 || underFire
	overall := 10.0
	if engagedDPS > 1 {
		mine := 1.0
		if tgt != nil {
			mine = b.myDPS(tgt.d)
		}
		need := 0.0
		for i := range ths {
			if ths[i].engaged {
				need += math.Max(ths[i].tr.HP, 20) / math.Max(mine, 1)
			}
		}
		overall = (b.hp / (engagedDPS * (1 - b.armor))) / math.Max(need, 0.1)
		if nEngaged == 1 && tgt != nil && tgt.engaged {
			overall = tgt.adv
		}
	}
	visibleFoe := tgt != nil && tgt.engaged && tgt.tr.LOS && tgt.tr.Listed
	knownFoe := tgt != nil && tgt.engaged && tgt.tr.Listed
	if b.retreating {
		healed := hpFrac >= b.P.ReturnHP
		winnable := overall > math.Max(st.disengage*1.25, 0.95)
		switch {
		case healed && (!danger || winnable):
			b.retreating = false
		case !danger && hpFrac >= b.P.ReturnHP-0.1:
			b.retreating = false
		case winnable && hpFrac > 0.3 && nEngaged <= 1 && knownFoe:
			b.retreating = false
		case visibleFoe && tgt.d < 45 && b.t-b.retreatT > 2.0 && nEngaged <= 1 && overall > 0.35:
			b.retreating = false
			b.corneredT = b.t
		}
	} else if danger && b.t-b.corneredT > 4 {
		leave := false
		phantoms := 0
		for i := range ths {
			if ths[i].phantom {
				phantoms++
			}
		}
		dmgRate := b.recentDmg / 3.0
		ttd := b.hp / math.Max(dmgRate, 1)
		switch {
		case nEngaged <= 1 && knownFoe:
			leave = overall < b.P.DuelDisengage && tgt.d > 30 && ttd < 25
		case nEngaged >= 2:
			leave = (ttd < b.P.LeaveTTD && hpFrac < 0.8) || (hpFrac < b.P.RetreatHP && ttd < 2*b.P.LeaveTTD)
		default:
			leave = underFire && phantoms > 0 && (ttd < 1.5*b.P.LeaveTTD || hpFrac < 0.6)
		}
		if leave {
			b.retreating = true
			b.retreatT = b.t
			b.coverCell = -1
		}
	}
	if tgt != nil && tgt.tr.LOS && tgt.tr.Listed && tgt.tr.HP > 0 && tgt.tr.HP < b.myDPS(tgt.d)*1.2+40 && hpFrac > 0.12 {
		b.retreating = false
	}

	// §8.5 intent
	wantFight, slip, plink, unprovoked, roofDuck := false, false, false, false, false
	fightWhy := ""
	onRoof := b.onRoof() >= 0 && b.o.Self.Grounded
	roofWanted := b.roofWanted(st, zi)
	huntR := b.P.HuntRange
	if tgt != nil && !b.retreating {
		switch {
		case tgt.engaged:
			if st.avoid {
				provoked := b.t-tgt.tr.HurtMeT < 4 || tgt.d < b.P.AvoidRange ||
					(tgt.tr.Laser && tgt.tr.Charging && b.t-tgt.tr.AimAtMeT < 0.4) ||
					(tgt.tr.Laser && tgt.tr.LOS && b.t-tgt.tr.AimAtMeT < 0.6)
				far := tgt.d >= b.P.AvoidRange && tgt.adv < b.P.AvoidAdv
				heavy := tgt.tr.Laser || b.recentDmg/3.0 > b.P.PlinkMaxDPS || hpFrac < 0.5 || nEngaged >= 2
				edgeThr, edgeBig := b.P.AvoidAdv, b.P.CoverEdgeAdv
				switch {
				case b.t-b.edgeOnT < b.P.EdgeHold:
					edgeThr, edgeBig = edgeThr*0.75, edgeBig*0.75
				case b.t-b.slipOnT < b.P.EdgeHold:
					edgeThr, edgeBig = edgeThr*1.3, edgeBig*1.3
				}
				edge := (b.laserEdge(tgt.tr) && tgt.adv >= edgeThr) || tgt.adv >= edgeBig
				if edge && provoked {
					b.edgeOnT = b.t
				}
				coverFirst := b.P.CoverFirst && provoked && !edge && tgt.d >= b.P.CoverMinRange // from ahmad-ovh/Buildathon@56e0f76b (MIT)
				switch {
				case !provoked:
					unprovoked = true
				case coverFirst && !(onRoof && roofWanted) && b.slipFromX(tgt, ths, true):
					slip = true
				case onRoof && roofWanted && !b.enemyOnRoof(ths):
					roofDuck = true
				case far && heavy && b.slipFrom(tgt, ths):
					slip = true
				case far && !heavy && b.P.PlinkMaxDPS > 0:
					plink = true
				case far && b.slipFrom(tgt, ths):
					slip = true
				default:
					wantFight = true
					switch {
					case tgt.adv >= b.P.AvoidAdv:
						fightWhy = ".edge"
					case tgt.d < b.P.AvoidRange && !(b.P.CoverFirst && tgt.d >= b.P.CoverMinRange):
						fightWhy = ".close"
					default:
						fightWhy = ".nocover"
					}
					if b.t-b.standT < 1.0 {
						fightWhy = ".stand"
					}
				}
			} else {
				wantFight = true
			}
		case st.hunt && tgt.adv >= st.engageRatio && tgt.d < huntR && tgt.tr.LOS && hpFrac > 0.6 &&
			(!st.avoid || b.laserEdge(tgt.tr) || tgt.adv >= b.P.CoverEdgeAdv):
			wantFight = true
			fightWhy = ".hunt"
		case st.name == "duel" && hpFrac > 0.5:
			wantFight = true
		}
	}
	if plink && b.chooseLoot(true, st) == nil {
		plink = false
		if b.slipFrom(tgt, ths) {
			slip = true
		} else {
			wantFight = true
		}
	}
	quiet := len(watchers) == 0 && !danger
	if quiet {
		for i := range ths {
			if b.t-ths[i].tr.LastSeen < 6 && ths[i].d < 180 {
				quiet = false
				break
			}
		}
	}
	if !quiet {
		b.unquietT = b.t
	} else if b.t-b.unquietT < b.P.QuietHoldS {
		quiet = false
	}

	// §8.6 movement preparation
	rq := steerReq{threats: inc}
	if li := b.has("laser"); li >= 0 && b.slots[li].charge > 0 {
		rq.slow = true
	}
	for i := range ths {
		tr := ths[i].tr
		if !tr.Laser || !tr.Charging || !tr.LOS {
			continue
		}
		if b.t-tr.AimAtMeT < 0.25 {
			sc := tr.scale(b.sizePerCube)
			ex, ey, ez := tr.Pos[0], tr.Pos[1], tr.Pos[2]+7*sc
			dmg := stat(b.C.Weapons["laser"], "damage", 315) * b.cubeDamageMul(tr.Cubes) * 0.85
			if b.has("mortar") >= 0 {
				dmg *= 1 + stat(b.C.Weapons["laser"], "cookoff", 0)
			}
			prev := rq.posCost
			rq.posCost = func(x, y float64) float64 {
				c := 0.0
				if prev != nil {
					c = prev(x, y)
				}
				if b.W.Visible(ex, ey, ez, x, y, b.pos[2]+b.height*0.5) || b.W.Visible(ex, ey, ez, x, y, b.pos[2]+b.height*0.9) {
					c += dmg
				}
				return c
			}
			rq.lookTicks = 12
			rq.dodgeBoost = true
		}
	}
	// from ahmad-ovh/Buildathon@56e0f76b (MIT): anti-lightning forcefield
	if b.P.AntiLightningW > 0 {
		haveLight := b.has("lightning") >= 0 && b.energy > 18
		if !haveLight || hpFrac < 0.55 {
			lightBase := stat(b.C.Weapons["lightning"], "range", 45)
			pad := b.P.AntiLightningPad
			if pad <= 0 {
				pad = 10
			}
			for i := range ths {
				tr := ths[i].tr
				if !tr.Light || (!tr.Listed && b.t-tr.LastSeen > 2.5) {
					continue
				}
				safeR := lightBase + pad
				if tr.Cubes >= 6 {
					safeR += 6
				}
				if ths[i].d > safeR+22 {
					continue
				}
				lx, ly := tr.Pos[0], tr.Pos[1]
				w := b.P.AntiLightningW
				prev := rq.posCost
				rq.posCost = func(x, y float64) float64 {
					c := 0.0
					if prev != nil {
						c = prev(x, y)
					}
					d := hyp(x-lx, y-ly)
					if d < safeR {
						f := (safeR - d) / safeR
						c += w * f * (1 + (safeR-d)/20)
					}
					return c
				}
				if ths[i].d < safeR+4 && tr.LOS {
					rq.dodgeBoost = true
					if rq.lookTicks < 10 {
						rq.lookTicks = 10
					}
				}
			}
		}
	}
	// from ahmad-ovh/Buildathon@56e0f76b (MIT): RearAvoidW, keep extra attackers out of our rear arc
	if b.P.RearAvoidW > 0 && tgt != nil && tgt.tr.LOS && nEngaged >= 2 {
		halfFront := b.mech("front_arc_deg", 180) * 0.5 * math.Pi / 180
		tx, ty := tgt.tr.Pos[0], tgt.tr.Pos[1]
		var extras [][2]float64
		for i := range ths {
			th := &ths[i]
			if th.engaged && th.tr.ID != tgt.tr.ID && th.tr.LOS && th.d < 210 {
				extras = append(extras, [2]float64{th.tr.Pos[0], th.tr.Pos[1]})
			}
		}
		if len(extras) > 0 {
			w := b.P.RearAvoidW
			prev := rq.posCost
			rq.posCost = func(x, y float64) float64 {
				c := 0.0
				if prev != nil {
					c = prev(x, y)
				}
				face := math.Atan2(ty-y, tx-x)
				for _, e := range extras {
					bear := math.Atan2(e[1]-y, e[0]-x)
					if math.Abs(angDiff(bear, face)) > halfFront {
						c += w
					}
				}
				return c
			}
		}
	}
	heading, haveHeading := 0.0, false
	var shootItem *aimTarget
	shootHP := 0.0
	goalOK := true
	navigating := false
	var lastGoal [2]float64
	setGoal := func(gx, gy, w float64, boost bool) float64 {
		dx, dy, d, ok := b.navDir(gx, gy)
		goalOK = ok
		navigating = true
		lastGoal = [2]float64{gx, gy}
		rq.wantX, rq.wantY, rq.wantW, rq.boost = dx, dy, w, boost
		if dx != 0 || dy != 0 {
			heading, haveHeading = math.Atan2(dy, dx), true
		}
		return d
	}
	holdFire := false
	direct := false
	b.holdClimb = st.avoid && (len(watchers) > 0 || underFire)
	if st.avoid && !b.holdClimb {
		for i := range ths {
			if ths[i].tr.Listed && ths[i].tr.LOS && ths[i].d < b.P.ClimbClearRange {
				b.holdClimb = true
				break
			}
		}
	}
	b.holdRoofMove = st.avoid && onRoof && (len(watchers) > 0 || underFire) && zi.tPass > b.P.RoofLeaveQuiet && !zi.urgent
	roofCoverCell := -1
	wantRoofCover := false
	if st.avoid && (roofDuck || b.retreating || len(watchers) > 0 || underFire) {
		wantRoofCover = true
		b.roofCoverHoldT = b.t
	} else if st.avoid && b.t-b.roofCoverHoldT < b.P.RoofCoverHold {
		wantRoofCover = true
	}
	if onRoof && roofWanted && wantRoofCover && !b.enemyOnRoof(ths) {
		if b.t-b.roofCoverT > 0.4 {
			b.roofCoverC = b.roofCover(b.onRoof(), ths)
			b.roofCoverT = b.t
		}
		roofCoverCell = b.roofCoverC
	} else {
		b.roofCoverC = -1
		b.roofCoverT = -100
	}
	if roofDuck && roofCoverCell < 0 && !b.retreating {
		wantFight = true
	}
	if b.roof.state == roofApproach && b.t-b.roof.stepT > 2.5 {
		b.roof.state = roofNone
	}

	// §8.7 movement mode
	switch {
	case zi.critical || (zi.urgent && (!wantFight || tgt == nil || tgt.d > 60)) || (zi.urgent && zi.tPass < 5):
		b.mode = "zone"
		b.roof.state = roofNone
		if b.lootID >= 0 {
			b.banUntil[b.lootID] = b.t + 20
			b.lootID = -1
		}
		setGoal(zi.goal[0], zi.goal[1], 3.0, zi.critical && b.energy > 15)
		rq.zoneFree = true
		if !zi.walkable {
			b.mode = "zone-over"
			b.overland(act, zi.goal[0], zi.goal[1])
			direct = true
		}

	case b.roof.state == roofClimb:
		b.mode = "climb"
		b.roofClimbStep(act)
		direct = true

	case roofCoverCell >= 0:
		b.mode = "roof-cover"
		x, y := b.Nav.Pos(roofCoverCell)
		if d := setGoal(x, y, 2.4, false); d < 1.8 {
			rq.wantW = 0
			rq.hold = true
		}
		rq.fenceRoof = true
		holdFire = tgt == nil || !tgt.engaged || tgt.d > b.P.FFAReturnFire

	case slip:
		b.mode = "slip"
		deepSlip := b.deepCell >= 0 && b.t-b.deepT < 8 && b.t-b.lastWeaponDT > 0.45 && b.cellHidden(b.deepCell, ths)
		if !deepSlip {
			b.deepCell = -1
		}
		if deepSlip {
			cx, cy := b.Nav.Pos(b.deepCell)
			if d := setGoal(cx, cy, 2.5, false); d < 1.5 || !goalOK {
				rq.wantW = 0
				rq.hold = true
				b.mode = "ambush"
			}
		} else {
			cx, cy := b.Nav.Pos(b.slipCell)
			if d := setGoal(cx, cy, 2.5, b.energy > 25 && underFire); d < 0.9 || (d < 3.0 && b.hiddenHere(ths)) {
				if b.t-b.deepTryT > 0.6 {
					b.deepTryT = b.t
					if c := b.deeperCover(ths, 45, false); c >= 0 {
						b.deepCell, b.deepT = c, b.t
					}
				}
				if b.deepCell >= 0 {
					cx, cy = b.Nav.Pos(b.deepCell)
					setGoal(cx, cy, 2.5, false)
				} else {
					rq.wantW = 0
					rq.hold = true
					b.mode = "ambush"
				}
			}
		}

	case b.retreating:
		b.mode = "retreat"
		if b.P.RetreatPest && nEngaged == 0 { // from ahmad-ovh/Buildathon@56e0f76b (MIT)
			if tr := b.pest(); tr != nil && tr.LOS && dist2(b.pos, tr.Pos) < 120 {
				at := b.targetOf(tr)
				shootItem = &at
				shootHP = tr.HP
			}
		}
		deeper := st.avoid
		deep := deeper && b.deepCell >= 0 && b.t-b.deepT < 8
		if deep && (b.t-b.lastWeaponDT < 0.45 || !b.cellHidden(b.deepCell, ths)) {
			deep = false
		}
		if !deep {
			b.deepCell = -1
			if b.t-b.coverT > 0.5 {
				b.coverCell = b.findCover(ths, 90)
				b.coverT = b.t
			}
		}
		if deep {
			b.mode = "retreat-on"
			cx, cy := b.Nav.Pos(b.deepCell)
			if d := setGoal(cx, cy, 2.5, b.energy > 35 && b.nearestEye(ths) < 60); d < 1.5 || !goalOK {
				b.deepCell = -1
				b.coverT = -100
			}
		} else if b.coverCell >= 0 {
			cx, cy := b.Nav.Pos(b.coverCell)
			d := setGoal(cx, cy, 2.5, b.energy > 20 && underFire)
			if d < 0.9 || (d < 3.0 && b.hiddenHere(ths)) {
				if deeper && b.t-b.deepTryT > 0.6 {
					b.deepTryT = b.t
					if c := b.deeperCover(ths, 75, true); c >= 0 {
						b.deepCell, b.deepT = c, b.t
					}
				}
				if b.deepCell >= 0 {
					b.mode = "retreat-on"
					cx, cy = b.Nav.Pos(b.deepCell)
					setGoal(cx, cy, 2.5, b.energy > 35 && b.nearestEye(ths) < 60)
				} else {
					rq.wantW = 0
					rq.hold = true
					b.mode = "heal"
				}
			}
		} else if from := b.fleeFrom(tgt, ths); from != nil {
			dx, dy := norm2(b.pos[0]-from.tr.Pos[0], b.pos[1]-from.tr.Pos[1])
			gx, gy := b.pos[0]+dx*30, b.pos[1]+dy*30
			setGoal(gx, gy, 2.0, b.energy > 30)
		} else if st.avoid && zi.outNext < -5 && b.t-b.lastNpcDT > 4 && b.t-b.lastWeaponDT < 30 {
			rq.wantW = 0
			rq.hold = true
			b.mode = "heal"
		} else {
			setGoal(zi.goal[0], zi.goal[1], 1.5, false)
		}

	case wantFight:
		b.mode = "fight" + fightWhy
		if w := b.weaponRun(32); w != nil && !onRoof {
			b.mode = "fight+arm"
			dx, dy, _, _ := b.navDir(w.Pos[0], w.Pos[1])
			rq.wantX, rq.wantY, rq.wantW = dx, dy, 2.4
		} else if c := b.cubeRun(tgt, st, hpFrac); c != nil {
			b.mode = "fight+cube"
			dx, dy, _, _ := b.navDir(c.Pos[0], c.Pos[1])
			rq.wantX, rq.wantY, rq.wantW = dx, dy, 2.2
		} else if near := b.kiteFrom(ths, nEngaged); near != nil {
			b.mode = "kite"
			b.strafe(&rq, near.tr.Pos, b.P.KiteMin, b.P.KiteMax, 2.0)
			if near.d < 70 && b.energy > 45 {
				rq.boost = true
			}
		} else {
			b.fightMove(&rq, tgt)
		}
		rq.fenceRoof = onRoof && roofWanted

	case b.pest() != nil:
		tr := b.pest()
		b.mode = "pest"
		at := b.targetOf(tr)
		d := dist2(b.pos, tr.Pos)
		if tr.LOS && d < 120 {
			shootItem = &at
			shootHP = tr.HP
			b.strafe(&rq, tr.Pos, 35, 60, 1.0)
		} else {
			setGoal(tr.Pos[0], tr.Pos[1], 1.5, false)
		}

	default:
		l := b.chooseLoot(danger, st)
		if l != nil && onRoof && roofWanted && l.kind != "drop" && !(l.kind == "pickup" && b.has("laser") < 0 && dist2(b.pos, l.pos) < 90) {
			l = nil
		}
		if l != nil {
			b.mode = "loot:" + l.kind
			b.lootID = l.id
			d := dist2(b.pos, l.pos)
			switch l.kind {
			case "crate":
				it := b.crates[l.id]
				at := aimTarget{pos: l.pos, radius: stat(b.C.Crates, "radius", 1.4), centerZ: stat(b.C.Crates, "height", 2.4) * 0.5}
				vis := d < 70 && b.W.Visible(b.pos[0], b.pos[1], b.pos[2]+b.muzzleH, at.pos[0], at.pos[1], at.pos[2]+at.centerZ)
				if vis {
					shootItem = &at
					if it != nil {
						shootHP = it.HP
					}
				}
				if d > 9 || !vis {
					setGoal(l.pos[0], l.pos[1], 1.5, false)
				} else {
					rq.hold = true
				}
			case "npc":
				tr := b.tracks[l.id]
				if tr != nil {
					at := b.targetOf(tr)
					if tr.LOS && d < 110 {
						shootItem = &at
						shootHP = tr.HP
					}
					if d > 60 || !tr.LOS {
						setGoal(l.pos[0], l.pos[1], 1.5, false)
					} else {
						b.strafe(&rq, tr.Pos, 50, 70, 1.0)
					}
				}
			case "drop":
				if d > 3 {
					setGoal(l.pos[0], l.pos[1], 2.0, false)
				} else {
					rq.hold = true
				}
			default:
				sprint := false
				if l.kind == "pickup" && b.energy > b.P.LootBoost && d > 25 {
					if it := b.pickups[l.id]; it != nil && it.Kind == "laser" && b.has("laser") < 0 {
						sprint = true
					}
				}
				setGoal(l.pos[0], l.pos[1], 2.0, sprint)
			}
			if navigating && !goalOK {
				b.banUntil[l.id] = b.t + 40
			}
		} else {
			b.lootID = -1
			b.mode = "hold"
			if zi.final {
				tol := 2.0
				boostFinal := false
				if b.P.FinalHold { // from ahmad-ovh/Buildathon@56e0f76b (MIT)
					tol = clamp(b.o.Zone.Radius*0.06, 0.35, 2.0)
					boostFinal = b.o.Zone.Radius < 18 && b.energy > 15
				}
				if d := setGoal(b.o.Zone.NextCenter[0], b.o.Zone.NextCenter[1], 1.8, boostFinal); d < tol {
					rq.wantW = 0
					rq.hold = true
				}
			} else if rx, ry, ok := b.roamTarget(st, hpFrac); ok && (!roofWanted || (!b.armed() && quiet)) {
				b.mode = "roam"
				setGoal(rx, ry, 1.5, false)
				if !goalOK && b.roamCell >= 0 {
					b.banUntil[-(b.roamCell + 1)] = b.t + 120
					b.roamCell = -1
				}
			} else if gx, gy, settled, ok2 := b.roofPlanStep(roofWanted, act); ok2 {
				b.mode = "roof"
				if settled {
					rq.hold = true
				} else {
					setGoal(gx, gy, 1.6, false)
				}
				rq.fenceRoof = onRoof && b.roof.state == roofOn
			} else {
				if b.holdCell < 0 || b.t-b.hideT > 2.0 {
					b.holdCell = b.chooseHide(zi)
					b.hideT = b.t
				}
				gx, gy := zi.goal[0], zi.goal[1]
				if b.holdCell >= 0 {
					gx, gy = b.Nav.Pos(b.holdCell)
				}
				if d := setGoal(gx, gy, 1.4, false); d < 2.5 {
					rq.wantW = 0
					rq.hold = true
				}
			}
		}
	}

	// §8.8 off the walk grid, final steering
	if !direct && navigating && !rq.hold && !rq.fenceRoof && (!b.onGroundLevel() || !goalOK) {
		gd := hyp(lastGoal[0]-b.pos[0], lastGoal[1]-b.pos[1])
		if gd > 3 {
			b.overland(act, lastGoal[0], lastGoal[1])
			direct = true
		}
	}
	if !direct {
		b.steer(act, rq)
		b.unstick(act, navigating && !rq.hold && !rq.fenceRoof)
	}

	// §8.9 aim and triggers
	unseen := false
	for i := range ths {
		if ths[i].phantom && b.t-ths[i].tr.HurtMeT < 1.5 {
			unseen = true
		}
	}
	switch {
	case unseen && (tgt == nil || !tgt.engaged || !tgt.tr.LOS):
		act.Aim = [2]float64{b.lastDmgBear, 0}
		act.HasAim = true
		if li := b.has("laser"); li >= 0 && b.slots[li].charge > 0 {
			act.Fire[li] = true
		}
	case plink && shootItem != nil:
		b.engage(act, *shootItem, true, true, shootHP, true)
	case tgt != nil && !holdFire && !unprovoked && (wantFight || tgt.engaged || b.retreating):
		at := b.targetOf(tgt.tr)
		b.engage(act, at, tgt.tr.LOS, b.t-tgt.tr.LOST < 0.8, tgt.tr.HP, true)
	case shootItem != nil:
		b.engage(act, *shootItem, true, true, shootHP, true)
	case tgt != nil && (tgt.tr.LOS || b.t-tgt.tr.LastSeen < 3):
		at := b.targetOf(tgt.tr)
		b.engage(act, at, tgt.tr.LOS, false, tgt.tr.HP, false)
	default:
		b.idleAim(act, heading, haveHeading)
		if gi := b.has("gun"); gi >= 0 {
			sl := &b.slots[gi]
			if sl.reload <= 0 && sl.ammo < stat(sl.stats, "mag", 12)*0.67 {
				act.Reload = true
			}
		}
		if li := b.has("laser"); li >= 0 && b.slots[li].charge > 0 {
			for _, tr := range b.tracks {
				if !tr.NPC && b.t-tr.LastSeen < 1.5 {
					act.Fire[li] = true
					break
				}
			}
		}
	}

	if b.P.CoverReload && !act.Reload && shootItem == nil { // from ahmad-ovh/Buildathon@56e0f76b (MIT)
		if gi := b.has("gun"); gi >= 0 && !act.Fire[gi] {
			sl := &b.slots[gi]
			mag := stat(sl.stats, "mag", 12)
			frac := 0.60
			if b.ffa {
				frac = 0.25
			}
			if sl.reload <= 0 && sl.ammo <= mag*frac && sl.ammo < mag && b.t-b.lastEnemyLOST >= 1.1 {
				act.Reload = true
			}
		}
	}

	// §8.10 debug label
	b.modeLabel = st.name + ":" + b.mode
	wl := ""
	for i := 0; i < 2; i++ {
		if b.slots[i].ok {
			wl += b.slots[i].kind[:2]
		}
	}
	td := -1.0
	if tgt != nil {
		td = tgt.d
	}
	act.Label = fmt.Sprintf("%s h%.0f a%d e%d k%d c%d %s d%.0f", b.modeLabel, b.hp, b.o.Alive, nEngaged, b.kills, b.o.Self.Cubes, wl, td)
}

// ---- §8.11 policy helpers

func (b *Bot) weaponRun(maxD float64) *Item {
	var best *Item
	bv := 0.0
	for _, it := range b.pickups {
		if !it.Ground || !b.sameComp(it.Cell) {
			continue
		}
		if until, banned := b.banUntil[it.ID]; banned && b.t < until {
			continue
		}
		ok, rep := b.wantPickup(it.Kind)
		if !ok {
			continue
		}
		v := b.weaponValue(it.Kind)
		if rep >= 0 {
			v -= b.weaponValue(b.slots[rep].kind)
			if v < b.P.ArmSwapMin {
				continue
			}
		}
		d := dist2(b.pos, it.Pos)
		if d > maxD {
			continue
		}
		if !b.inFutureZone(it.Pos[0], it.Pos[1], d/b.walk+2, 5) {
			continue
		}
		contested := false
		for _, tr := range b.tracks {
			if tr.NPC || b.t-tr.LastSeen > 5 {
				continue
			}
			if de := dist2(tr.Pos, it.Pos); de < 30 || de < d*0.8 {
				contested = true
				break
			}
		}
		if contested {
			continue
		}
		if s := v / (d + 15); s > bv {
			best, bv = it, s
		}
	}
	return best
}

func (b *Bot) slipFrom(tgt *threat, ths []threat) bool { return b.slipFromX(tgt, ths, false) }

func (b *Bot) laserEdge(tr *Track) bool { return b.has("laser") >= 0 && !tr.Laser }

func (b *Bot) slipFromX(tgt *threat, ths []threat, anyEdge bool) bool {
	minR, maxAdv := b.P.AvoidRange, b.P.AvoidAdv
	if b.P.CoverFirst && b.P.CoverMinRange < minR {
		minR = b.P.CoverMinRange
	}
	if b.t-b.slipOnT < 1.0 {
		minR, maxAdv = minR*0.85, maxAdv*1.15
	}
	if anyEdge {
		maxAdv = 1e9
	}
	if b.P.AvoidAdv <= 0 || tgt.d < minR || tgt.adv >= maxAdv {
		return false
	}
	if tgt.tr.LOS && tgt.tr.HP > 0 && tgt.tr.HP < b.myDPS(tgt.d)*1.5+60 {
		return false
	}
	if b.t-b.slipT > 0.5 {
		reach := b.P.AvoidCover
		if tgt.tr.Laser && b.P.AvoidCoverLaser > reach {
			reach = b.P.AvoidCoverLaser
		}
		c := b.findCover(ths, reach)
		if c >= 0 || b.t-b.slipOnT > 1.5 {
			b.slipCell = c
		}
		b.slipT = b.t
	}
	if b.slipCell < 0 {
		return false
	}
	b.slipOnT = b.t
	return true
}

func (b *Bot) kiteFrom(ths []threat, nEngaged int) *threat {
	if nEngaged < 2 {
		return nil
	}
	if b.realModel() && b.has("laser") < 0 {
		return nil
	}
	if b.has("lightning") >= 0 && b.energy > 40 && b.has("laser") < 0 {
		return nil
	}
	var near *threat
	for i := range ths {
		if ths[i].engaged && !ths[i].phantom && ths[i].tr.Listed && (near == nil || ths[i].d < near.d) {
			near = &ths[i]
		}
	}
	if near == nil || near.d > b.P.KiteMax+20 {
		return nil
	}
	return near
}

func (b *Bot) armed() bool {
	n := 0
	for i := 0; i < 2; i++ {
		if b.slots[i].ok {
			n++
		}
	}
	return n >= 2
}

func (b *Bot) fleeFrom(tgt *threat, ths []threat) *threat {
	if tgt != nil {
		return tgt
	}
	var best *threat
	for i := range ths {
		if ths[i].engaged && (best == nil || ths[i].tr.HurtMeT > best.tr.HurtMeT) {
			best = &ths[i]
		}
	}
	return best
}

func (b *Bot) cubeRun(tgt *threat, st stance, hpFrac float64) *Item {
	if b.o.Self.Cubes >= st.wantCubes+6 {
		return nil
	}
	var best *Item
	bv := 0.0
	for _, c := range b.cubes {
		if !c.Ground || b.t-c.LastSeen > 20 || !b.sameComp(c.Cell) {
			continue
		}
		d := dist2(b.pos, c.Pos)
		n := 0
		for _, o := range b.cubes {
			if dist2(o.Pos, c.Pos) < 7 {
				n++
			}
		}
		maxD := 40.0
		if n >= 2 {
			maxD = 110
		}
		if st.stealth {
			maxD *= 0.5
		}
		if d > maxD || (d > 30 && hpFrac < 0.3) {
			continue
		}
		if b.has("lightning") < 0 {
			lightR := stat(b.C.Weapons["lightning"], "range", 45) + 8
			dangerLight := false
			for _, tr := range b.tracks {
				if !tr.NPC && tr.Light && b.t-tr.LastSeen < 4 && dist2(c.Pos, tr.Pos) < lightR {
					dangerLight = true
					break
				}
			}
			if dangerLight {
				continue
			}
		}
		if !b.inFutureZone(c.Pos[0], c.Pos[1], d/b.walk+1, 3) {
			continue
		}
		v := float64(n) / (d + 12)
		if v > bv {
			best, bv = c, v
		}
	}
	return best
}

func (b *Bot) roamTarget(st stance, hpFrac float64) (float64, float64, bool) {
	if hpFrac < 0.7 {
		return 0, 0, false
	}
	if b.o.Self.Cubes >= st.wantCubes {
		return 0, 0, false
	}
	return b.roamGoal()
}

func (b *Bot) pest() *Track {
	if b.t-b.lastNpcDT > 4 {
		return nil
	}
	var best *Track
	bd := 1e18
	for _, tr := range b.tracks {
		if !tr.NPC || b.t-tr.HurtMeT > 4 || b.t-tr.LastSeen > 3 {
			continue
		}
		if d := dist2(b.pos, tr.Pos); d < bd {
			best, bd = tr, d
		}
	}
	return best
}

func (b *Bot) strafe(rq *steerReq, at [3]float64, rmin, rmax, w float64) {
	if b.t >= b.strafeT {
		b.strafeSign = -b.strafeSign
		if b.rng.Float64() < 0.25 {
			b.strafeSign = -b.strafeSign
		}
		b.strafeT = b.t + b.P.StrafeMin + b.rng.Float64()*(b.P.StrafeMax-b.P.StrafeMin)
	}
	rx, ry := norm2(at[0]-b.pos[0], at[1]-b.pos[1])
	d := dist2(b.pos, at)
	radial := 0.0
	if d > rmax {
		radial = clamp((d-rmax)/15, 0, 1)
	} else if d < rmin {
		radial = -clamp((rmin-d)/15, 0, 1)
	}
	tx, ty := -ry*b.strafeSign, rx*b.strafeSign
	wx := tx*(1-0.6*math.Abs(radial)) + rx*radial
	wy := ty*(1-0.6*math.Abs(radial)) + ry*radial
	rq.wantX, rq.wantY = norm2(wx, wy)
	rq.wantW = w
}

func (b *Bot) fightMove(rq *steerReq, th *threat) {
	tr := th.tr
	haveLight := b.has("lightning") >= 0 && b.energy > 18
	rmin, rmax := th.rmin, th.rmax
	if rmax <= 0 {
		rmin, rmax = 30, 55
	}
	if !tr.LOS {
		dx, dy, _, _ := b.navDir(tr.Pos[0], tr.Pos[1])
		rq.wantX, rq.wantY, rq.wantW = dx, dy, 1.2
		return
	}
	b.strafe(rq, tr.Pos, rmin, rmax, 1.6)
	if haveLight && th.d > rmax+10 && b.energy > 55 {
		rq.boost = true
	}
}
