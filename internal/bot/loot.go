package bot

import (
	"math"
	"sort"
)

type loot struct {
	kind  string
	id    int
	pos   [3]float64
	score float64
	shoot bool
}

func (b *Bot) weaponValue(kind string) float64 {
	switch kind {
	case "laser": // from ahmad-ovh/Buildathon@56e0f76b (MIT)
		return b.P.LaserValue
	case "lightning":
		return b.P.LightningValue
	case "mortar":
		return 1.2
	case "gun":
		return 2.0
	}
	return 0
}

func (b *Bot) wantPickup(kind string) (bool, int) {
	if b.has(kind) >= 0 {
		return false, -1
	}
	if kind == "mortar" && b.P.NoMortar && b.realModel() { // from ahmad-ovh/Buildathon@56e0f76b (MIT)
		return false, -1
	}
	for i := 0; i < 2; i++ {
		if !b.slots[i].ok {
			return true, -1
		}
	}
	worst, wv := -1, 1e9
	for i := 0; i < 2; i++ {
		if b.slots[i].kind == "gun" {
			continue
		}
		if v := b.weaponValue(b.slots[i].kind); v < wv {
			worst, wv = i, v
		}
	}
	if worst >= 0 && b.weaponValue(kind) > wv+0.3 && b.slots[worst].charge <= 0 {
		return true, worst
	}
	return false, -1
}

func (b *Bot) enemyNear(pos [3]float64, r float64) bool {
	for _, tr := range b.tracks {
		if tr.NPC || b.t-tr.LastSeen > 6 {
			continue
		}
		if dist2(tr.Pos, pos) < r {
			return true
		}
	}
	return false
}

func (b *Bot) chooseLoot(danger bool, st stance) *loot {
	var best *loot
	var watchEyes [][3]float64
	if st.avoid {
		for _, tr := range b.tracks {
			if tr.NPC || b.t-tr.LastSeen > 4.0 {
				continue
			}
			sc := tr.scale(b.sizePerCube)
			watchEyes = append(watchEyes, [3]float64{tr.Pos[0], tr.Pos[1], tr.Pos[2] + 8*sc})
			if len(watchEyes) >= 6 {
				break
			}
		}
	}
	consider := func(l loot, value, handling float64) {
		d := dist2(b.pos, l.pos)
		if d > st.lootRadius {
			return
		}
		if until, banned := b.banUntil[l.id]; banned && b.t < until {
			return
		}
		if !b.reachable(l.pos[0], l.pos[1]) {
			return
		}
		if st.stealth {
			if e := b.Nav.Exposure().At(b.Nav.Index(l.pos[0], l.pos[1])); e <= 1 {
				value *= 1 - 0.6*float64(e)
			}
		}
		tt := d*1.25/b.walk + handling
		if !b.inFutureZone(l.pos[0], l.pos[1], tt+2+10, 6) {
			return
		}
		if b.enemyNear(l.pos, 45) && l.kind != "cube" {
			value *= 0.35
		}
		if st.avoid && len(watchEyes) > 0 {
			for _, e := range watchEyes {
				if hyp(e[0]-l.pos[0], e[1]-l.pos[1]) < 230 && b.W.Visible(e[0], e[1], e[2], l.pos[0], l.pos[1], l.pos[2]+4.5) {
					value *= 1 - 0.5
					break
				}
			}
		}
		l.score = value / (tt + 1.5)
		if l.id == b.lootID {
			l.score *= 1.25
		}
		if best == nil || l.score > best.score {
			c := l
			best = &c
		}
	}
	wantCubes := b.o.Self.Cubes < st.wantCubes
	for _, it := range b.pickups {
		if !it.Ground {
			continue
		}
		if ok, rep := b.wantPickup(it.Kind); ok {
			v := b.weaponValue(it.Kind) * 4
			if rep >= 0 {
				v = (b.weaponValue(it.Kind) - b.weaponValue(b.slots[rep].kind)) * 4
			}
			consider(loot{kind: "pickup", id: it.ID, pos: it.Pos}, v, 0.5)
		}
	}
	if wantCubes {
		for _, it := range b.cubes {
			if it.Ground {
				consider(loot{kind: "cube", id: it.ID, pos: it.Pos}, 11.0, 0)
			}
		}
		for _, it := range b.crates {
			if it.Ground {
				consider(loot{kind: "crate", id: it.ID, pos: it.Pos, shoot: true}, 7*1.0, 2.5)
			}
		}
		if !danger {
			for _, tr := range b.tracks {
				if tr.NPC && b.t-tr.LastSeen < 20 {
					k := b.Nav.Index(tr.Pos[0], tr.Pos[1])
					if !b.Nav.Solid[k] && math.Abs(float64(b.Nav.Z[k])-tr.Pos[2]) < 4 {
						consider(loot{kind: "npc", id: tr.ID, pos: tr.Pos, shoot: true}, 11*1.0, 5)
					}
				}
			}
		}
	}
	for i := range b.o.Drops {
		dr := &b.o.Drops[i]
		d := dist2(b.pos, dr.Pos)
		if d > 300 {
			continue
		}
		if dr.LandsIn > d/b.walk*1.3+6 && !(dr.ID == b.lootID) {
			continue
		}
		if st.avoid && b.o.Self.Cubes >= st.wantCubes && b.hp > b.maxHP*0.7 {
			continue
		}
		if dr.Holder != nil && *dr.Holder != b.o.Self.ID && st.stealth {
			continue
		}
		if st.stealth && b.enemyNear(dr.Pos, 110) {
			continue
		}
		v := 30.0 * 0.5 * 2
		if b.hp < b.maxHP*0.6 {
			v *= 1.5
		}
		saved := st.lootRadius
		st.lootRadius = 300
		consider(loot{kind: "drop", id: dr.ID, pos: dr.Pos}, v, 4+dr.LandsIn*0.3)
		st.lootRadius = saved
	}
	return best
}

func (b *Bot) manageWeapons(act *Action) {
	if b.t < b.takeT {
		return
	}
	reach := b.C.Loot.PickupRadius
	if reach <= 0 {
		reach = 4
	}
	bestID, bestV, bestRep := -1, 0.0, -1
	for _, it := range b.pickups {
		if b.t-it.LastSeen > 0.5 {
			continue
		}
		if dist2(b.pos, it.Pos) > reach-0.3 || math.Abs(it.Pos[2]-b.pos[2]) > 3.7 {
			continue
		}
		if ok, rep := b.wantPickup(it.Kind); ok {
			if v := b.weaponValue(it.Kind); v > bestV {
				bestID, bestV, bestRep = it.ID, v, rep
			}
		}
	}
	if bestID >= 0 {
		act.Take = bestID
		if bestRep >= 0 {
			act.Drop = bestRep
		}
		b.takeT = b.t + 0.25
	}
}

var upgradeRank = map[string]float64{
	// from ahmad-ovh/Buildathon@56e0f76b (MIT)
	"plating": 1.00, "armor": 0.96, "gun_rate": 0.90, "gun_damage": 0.88, "gun_velocity": 0.80,
	"laser_damage": 0.91, "laser_charge": 0.86, "lightning_efficiency": 0.92, "lightning_range": 0.87,
	"nanites": 0.72, "servos": 0.76, "reactor": 0.50, "capacitor": 0.45, "gun_mag": 0.60,
	"sensors": 0.35, "gyros": 0.30, "jets": 0.30, "mortar_reload": 0.42, "mortar_splash": 0.45,
	"mortar_velocity": 0.40, "lightning_chain": 0.40, "laser_pierce": 0.20,
}

func (b *Bot) pickUpgrade(act *Action) {
	of := b.o.Offer
	if of == nil || len(of.Choices) == 0 {
		return
	}
	best, bv := 0, -1.0
	for i, c := range of.Choices {
		v, ok := upgradeRank[c.ID]
		if !ok {
			v = 0.25
		}
		if b.has("lightning") >= 0 && (c.ID == "reactor" || c.ID == "capacitor") {
			v += 0.3
		}
		if v > bv {
			best, bv = i, v
		}
	}
	act.Pick = best
}

type hideCand struct {
	cell  int
	score float64
}

func (b *Bot) chooseHide(zi zoneInfo) int {
	z := &b.o.Zone
	exp := b.Nav.Exposure()
	comp := b.Nav.Components()
	myComp := int32(0)
	if c := b.Nav.Nearest(b.pos[0], b.pos[1], 2.9, 9, 6); c >= 0 {
		myComp = comp[c]
	}
	margin := math.Min(14, z.NextRadius*0.25)
	var cands []hideCand
	for j := 0; j < exp.NY; j++ {
		for i := 0; i < exp.NX; i++ {
			e := exp.V[j*exp.NX+i]
			if e > 1.5 {
				continue
			}
			k := exp.Cell(i, j)
			if myComp != 0 && comp[k] != myComp {
				continue
			}
			x, y := b.Nav.Pos(k)
			dn := hyp(x-z.NextCenter[0], y-z.NextCenter[1])
			if dn > z.NextRadius-margin {
				continue
			}
			if !b.Nav.Walkable(k, b.radius+0.4, b.height) {
				continue
			}
			d := hyp(x-b.pos[0], y-b.pos[1])
			if d > 320 {
				continue
			}
			s := float64(e)*100 + d*b.hideDistW()
			if z.NextRadius > 60 && dn < z.NextRadius*0.35 { // from ahmad-ovh/Buildathon@56e0f76b (MIT)
				s += 10
			}
			if !b.ffa && b.P.PracticeRim > 0 && z.NextRadius >= 180 {
				wantR := z.NextRadius * 0.88
				s += math.Abs(dn-wantR) * b.P.PracticeRim
			}
			s += float64(b.Nav.Clear[k]) * 0.8
			if k == b.holdCell {
				s -= 9
			}
			cands = append(cands, hideCand{k, s})
		}
	}
	if len(cands) == 0 {
		return -1
	}
	sort.Slice(cands, func(a, c int) bool { return cands[a].score < cands[c].score })
	if len(cands) > 60 { // from ahmad-ovh/Buildathon@56e0f76b (MIT): refine the shortlist with enemies and drops
		cands = cands[:60]
	}
	best, bs := -1, 1e18
	for _, c := range cands {
		x, y := b.Nav.Pos(c.cell)
		gz := float64(b.Nav.Z[c.cell])
		s := c.score
		for _, tr := range b.tracks {
			if tr.NPC || b.t-tr.LastSeen > 25 {
				continue
			}
			d := hyp(tr.Pos[0]-x, tr.Pos[1]-y)
			if d < 90 {
				s += (90 - d) * 0.35
			}
			if d < 260 && b.t-tr.LastSeen < 8 {
				sc := tr.scale(b.sizePerCube)
				if b.W.Visible(tr.Pos[0], tr.Pos[1], tr.Pos[2]+8*sc, x, y, gz+b.height*0.6) {
					s += 30
				}
			}
		}
		for i := range b.o.Drops {
			if hyp(b.o.Drops[i].Pos[0]-x, b.o.Drops[i].Pos[1]-y) < 70 {
				s += 15
			}
		}
		if s < bs {
			best, bs = c.cell, s
		}
	}
	return best
}

func (b *Bot) hideDistW() float64 {
	if b.st.stealth {
		return 0.16
	}
	return 0.07
}
