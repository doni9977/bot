package bot

import (
	"math"

	"apexbot/internal/world"
)

const (
	roofNone     = 0
	roofApproach = 1
	roofClimb    = 2
	roofOn       = 3
)

type roofPlan struct {
	state      int
	id         int
	acc        world.RoofAccess
	t0         float64
	ban        map[int]float64
	chosen     float64
	tries      int
	stepT      float64
	waitT0     float64
	want, spot int
}

func (b *Bot) onRoof() int {
	roofs, roofOf := b.Nav.Roofs()
	k := b.Nav.Index(b.pos[0], b.pos[1])
	id := int(roofOf[k])
	if id < 0 || id >= len(roofs) {
		return -1
	}
	if math.Abs(b.pos[2]-roofs[id].Z) < 1.6 {
		return id
	}
	return -1
}

func (b *Bot) maxClimb() float64 {
	drain := stat(b.o.Self.Stats, "jet_drain", b.mech("jet_drain", 15))
	if drain <= 0 {
		drain = 15
	}
	return (b.o.Self.MaxEnergy - 28) / drain * 8.9
}

func (b *Bot) roofSpotOK(r *world.Roof) bool {
	z := &b.o.Zone
	x, y := b.Nav.Pos(r.Inner)
	return hyp(x-z.NextCenter[0], y-z.NextCenter[1]) < z.NextRadius-8
}

func (b *Bot) chooseRoof() (int, world.RoofAccess, bool) {
	roofs, _ := b.Nav.Roofs()
	comp := b.Nav.Components()
	myComp := int32(0)
	if c := b.Nav.Nearest(b.pos[0], b.pos[1], 2.9, 9, 6); c >= 0 {
		myComp = comp[c]
	}
	limit := math.Min(b.maxClimb(), 40)
	bestID, bestS := -1, 1e18
	var bestAcc world.RoofAccess
	for i := range roofs {
		r := &roofs[i]
		if until, ok := b.roof.ban[i]; ok && b.t < until {
			continue
		}
		if r.Height < b.P.RoofMinHeight || r.InnerD < 6+b.radius || !b.roofSpotOK(r) { // from ahmad-ovh/Buildathon@56e0f76b (MIT)
			continue
		}
		if hyp(r.CX-b.pos[0], r.CY-b.pos[1]) > 260+math.Sqrt(r.Area) {
			continue
		}
		var acc world.RoofAccess
		ad := 1e18
		for _, a := range r.Access {
			if a.Climb > limit || a.Climb < 6 {
				continue
			}
			if myComp != 0 && comp[a.Ground] != myComp {
				continue
			}
			if !b.Nav.Walkable(a.Ground, b.radius+0.2, b.height) {
				continue
			}
			gx, gy := b.Nav.Pos(a.Ground)
			if d := hyp(gx-b.pos[0], gy-b.pos[1]); d < ad {
				acc, ad = a, d
			}
		}
		if ad > 1e17 {
			continue
		}
		s := ad*1.2 - math.Min(r.InnerD, 25)*2.5 - math.Min(r.Height, 30)*1.5
		ix, iy := b.Nav.Pos(r.Inner)
		for _, tr := range b.tracks {
			if tr.NPC || b.t-tr.LastSeen > 20 {
				continue
			}
			if d := hyp(tr.Pos[0]-ix, tr.Pos[1]-iy); d < 120 {
				s += (120 - d) * 0.6
			}
		}
		if i == b.roof.id && b.roof.state != roofNone {
			s -= 40
		}
		if s < bestS {
			bestID, bestS, bestAcc = i, s, acc
		}
	}
	return bestID, bestAcc, bestID >= 0
}

func (b *Bot) roofSpot(id int) (float64, float64) {
	roofs, roofOf := b.Nav.Roofs()
	dist := b.Nav.RoofDist()
	r := &roofs[id]
	k := b.Nav.Index(b.pos[0], b.pos[1])
	if int(roofOf[k]) != id {
		return b.Nav.Pos(r.Inner)
	}
	ix, iy := b.Nav.Pos(r.Inner)
	d := hyp(ix-b.pos[0], iy-b.pos[1])
	steps := int(d/2) + 1
	clear := true
	for s := 1; s <= steps; s++ {
		t := float64(s) / float64(steps)
		c := b.Nav.Index(b.pos[0]+(ix-b.pos[0])*t, b.pos[1]+(iy-b.pos[1])*t)
		if int(roofOf[c]) != id || dist[c] < 2 {
			clear = false
			break
		}
	}
	if clear {
		return ix, iy
	}
	ci, cj := k%b.Nav.NX, k/b.Nav.NX
	best, bd := k, dist[k]
	for dj := -3; dj <= 3; dj++ {
		for di := -3; di <= 3; di++ {
			i, j := ci+di, cj+dj
			if i < 0 || j < 0 || i >= b.Nav.NX || j >= b.Nav.NY {
				continue
			}
			c := j*b.Nav.NX + i
			if int(roofOf[c]) == id && dist[c] > bd {
				best, bd = c, dist[c]
			}
		}
	}
	return b.Nav.Pos(best)
}

func (b *Bot) roofCover(id int, ths []threat) int {
	roofs, roofOf := b.Nav.Roofs()
	dist := b.Nav.RoofDist()
	r := &roofs[id]
	var eyes []eyePt
	for i := range ths {
		tr := ths[i].tr
		if ths[i].d > 280 || (b.t-tr.LastSeen > 8 && !ths[i].phantom) {
			continue
		}
		eyes = append(eyes, eyePt{tr.Pos[0], tr.Pos[1], tr.Pos[2] + 8*tr.scale(b.sizePerCube)})
	}
	if len(eyes) == 0 {
		return -1
	}
	best, bs := -1, 1e18
	for _, c := range r.Cells {
		k := int(c)
		ci, cj := k%b.Nav.NX, k/b.Nav.NX
		if (ci+cj)%2 != 0 || dist[k] < 3 || int(roofOf[k]) != id {
			continue
		}
		x, y := b.Nav.Pos(k)
		d := hyp(x-b.pos[0], y-b.pos[1])
		if d > 50 || d >= bs {
			continue
		}
		hidden := true
		for _, e := range eyes {
			if b.W.Visible(e.x, e.y, e.z, x, y, r.Z+b.height*0.5) || b.W.Visible(e.x, e.y, e.z, x, y, r.Z+b.height*0.97) {
				hidden = false
				break
			}
		}
		if hidden {
			best, bs = k, d
		}
	}
	return best
}

func (b *Bot) enemyOnRoof(ths []threat) bool {
	for i := range ths {
		tr := ths[i].tr
		if tr.Listed && ths[i].d < 70 && math.Abs(tr.Pos[2]-b.pos[2]) < 5 {
			return true
		}
	}
	return false
}

func (b *Bot) roofClimbStep(act *Action) {
	roofs, roofOf := b.Nav.Roofs()
	r := &roofs[b.roof.id]
	ex, ey := b.Nav.Pos(b.roof.acc.Edge)
	dx, dy := norm2(ex-b.pos[0], ey-b.pos[1])
	act.Move = [2]float64{dx, dy}
	feet := b.pos[2]
	cell := b.Nav.Index(b.pos[0], b.pos[1])
	over := int(roofOf[cell]) == b.roof.id
	grounded := b.o.Self.Grounded
	switch {
	case grounded && over && math.Abs(feet-r.Z) < 1.6:
		b.roof.state = roofOn
		b.roof.t0 = b.t
		b.roof.tries = 0
		return
	case grounded && feet < r.Z-1.0:
		act.Jump = true
	case feet < r.Z+0.7:
		act.Boost = true
	case !over:
		act.Boost = b.vel[2] < 0.5
	}
	budget := b.roof.acc.Climb/8.0 + 5
	if b.t-b.roof.t0 > budget || (b.energy < 2 && !grounded && feet < r.Z-0.5) {
		b.roof.tries++
		if b.roof.ban == nil {
			b.roof.ban = map[int]float64{}
		}
		b.roof.ban[b.roof.id] = b.t + 90
		b.roof.state = roofNone
	}
}

func (b *Bot) overland(act *Action, gx, gy float64) {
	tops := b.Nav.Tops()
	feet := b.pos[2]
	grounded := b.o.Self.Grounded
	here := b.Nav.Index(b.pos[0], b.pos[1])
	if b.surfBan == nil {
		b.surfBan = map[int]float64{}
	}
	if b.t-b.surfWatchT >= 1.5 {
		if b.surfPushing && dist3(b.pos, b.surfWatchPos) < 1.2 && len(b.surf) >= 2 {
			for j := b.surfIdx + 1; j < len(b.surf) && j <= b.surfIdx+3; j++ {
				b.surfBan[int(b.surf[j])] = b.t + 25
			}
			b.surf = nil
			b.surfT = -100
		}
		b.surfWatchT, b.surfWatchPos, b.surfPushing = b.t, b.pos, false
	}
	replan := len(b.surf) < 2 || hyp(gx-b.surfGoal[0], gy-b.surfGoal[1]) > 6 || b.t-b.surfT > 1.2
	if !replan {
		px, py := b.Nav.Pos(int(b.surf[b.surfIdx]))
		if hyp(px-b.pos[0], py-b.pos[1]) > 7 {
			replan = true
		}
	}
	if replan && b.t-b.surfT >= 0.3 {
		blocked := func(k int) bool {
			until, ok := b.surfBan[k]
			return ok && b.t < until
		}
		b.surf = b.Nav.SurfacePath(b.pos[0], b.pos[1], feet, gx, gy, b.maxClimb(), b.radius, 14000, blocked)
		b.surfGoal = [2]float64{gx, gy}
		b.surfT = b.t
		b.surfIdx = 0
	}
	dx, dy := norm2(gx-b.pos[0], gy-b.pos[1])
	need := feet
	if len(b.surf) >= 2 {
		best, bd := b.surfIdx, 1e18
		for j := b.surfIdx; j < len(b.surf) && j < b.surfIdx+8; j++ {
			px, py := b.Nav.Pos(int(b.surf[j]))
			if d := hyp(px-b.pos[0], py-b.pos[1]); d < bd {
				best, bd = j, d
			}
		}
		b.surfIdx = best
		n1 := best + 1
		if n1 > len(b.surf)-1 {
			n1 = len(b.surf) - 1
		}
		tgt := n1
		for tgt < len(b.surf)-1 && tgt < best+3 && math.Abs(float64(tops[b.surf[tgt+1]])-float64(tops[b.surf[n1]])) < 0.6 && float64(tops[b.surf[n1]]) <= feet+1.0 {
			tgt++
		}
		tx, ty := b.Nav.Pos(int(b.surf[tgt]))
		if int(b.surf[tgt]) != here {
			dx, dy = norm2(tx-b.pos[0], ty-b.pos[1])
		}
		need = float64(tops[b.surf[n1]])
		if h := float64(tops[b.surf[tgt]]); h > need {
			need = h
		}
	} else {
		for _, s := range [...]float64{b.radius + 1, b.radius + 3.5} {
			if h, _ := b.W.Floor(b.pos[0]+dx*s, b.pos[1]+dy*s, 1e9); h > need {
				need = h
			}
		}
	}
	act.Move = [2]float64{dx, dy}
	rise := need - feet
	drain := stat(b.o.Self.Stats, "jet_drain", b.mech("jet_drain", 15))
	switch {
	case rise < 1.0:
		act.Boost = grounded && !b.o.Self.InZone && b.energy > 70
		b.surfPushing = true
	case grounded:
		if b.energy >= math.Min(rise/8.9*drain+16, b.o.Self.MaxEnergy-3) {
			act.Jump = true
			b.surfPushing = true
		} else {
			act.Move = [2]float64{0, 0}
		}
	default:
		act.Boost = feet < need+0.8 && b.energy > 1
	}
}

func (b *Bot) roofWanted(st stance, zi zoneInfo) bool {
	if zi.final || b.o.Zone.NextRadius < 60 {
		return false
	}
	if st.name == "duel" {
		return false
	}
	if !st.stealth {
		if !(st.avoid && st.name == "ffa") {
			return false
		}
		if b.has("laser") < 0 && b.o.Self.Cubes < 6 && b.t < 60 {
			return false
		}
	}
	return true
}

func (b *Bot) roofPlanStep(wanted bool, act *Action) (gx, gy float64, settled, ok bool) {
	if !wanted {
		b.roof.state = roofNone
		return 0, 0, false, false
	}
	return b.roofHold(act)
}

func (b *Bot) roofHold(act *Action) (gx, gy float64, settled, ok bool) {
	roofs, _ := b.Nav.Roofs()
	if b.t-b.roof.stepT > 1.5 {
		b.roof.t0 = b.t
	}
	b.roof.stepT = b.t
	if id := b.onRoof(); id >= 0 && b.o.Self.Grounded {
		r := &roofs[id]
		stay := b.roofSpotOK(r) && r.Height >= 12-3
		if stay {
			z := &b.o.Zone
			sx, sy := b.roofSpot(id)
			if hyp(sx-z.NextCenter[0], sy-z.NextCenter[1]) > z.NextRadius-4 {
				stay = false
				if b.roof.ban == nil {
					b.roof.ban = map[int]float64{}
				}
				b.roof.ban[id] = b.t + 60
			}
		}
		if !stay && b.holdRoofMove {
			stay = true
		}
		if stay {
			b.roof.state, b.roof.id = roofOn, id
			x, y := b.roofSpot(id)
			return x, y, hyp(x-b.pos[0], y-b.pos[1]) < 2.0, true
		}
		b.roof.state = roofNone
	}
	if b.roof.state == roofOn {
		b.roof.state = roofNone
	}
	if b.roof.state == roofNone || b.t-b.roof.chosen > 3 {
		id, acc, found := b.chooseRoof()
		b.roof.chosen = b.t
		if !found {
			b.roof.state = roofNone
			return 0, 0, false, false
		}
		if b.roof.state == roofNone || id != b.roof.id {
			b.roof.state, b.roof.id, b.roof.acc, b.roof.t0 = roofApproach, id, acc, b.t
		}
	}
	gx, gy = b.Nav.Pos(b.roof.acc.Ground)
	d := hyp(gx-b.pos[0], gy-b.pos[1])
	if d < 1.6 && b.onGroundLevel() {
		need := b.roof.acc.Climb/8.9*stat(b.o.Self.Stats, "jet_drain", 15) + 24
		if b.holdClimb {
			if b.roof.waitT0 <= 0 {
				b.roof.waitT0 = b.t
			}
			if b.t-b.roof.waitT0 > 4 {
				if b.roof.ban == nil {
					b.roof.ban = map[int]float64{}
				}
				b.roof.ban[b.roof.id] = b.t + 20
				b.roof.state = roofNone
				b.roof.waitT0 = 0
				return 0, 0, false, false
			}
			return gx, gy, true, true
		}
		b.roof.waitT0 = 0
		if b.energy >= need {
			b.roof.state = roofClimb
			b.roof.t0 = b.t
		}
		return gx, gy, true, true
	}
	if b.t-b.roof.t0 > 60 {
		if b.roof.ban == nil {
			b.roof.ban = map[int]float64{}
		}
		b.roof.ban[b.roof.id] = b.t + 60
		b.roof.state = roofNone
		return 0, 0, false, false
	}
	return gx, gy, false, true
}
