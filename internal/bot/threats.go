package bot

import "math"

type threat struct {
	tr         *Track
	d          float64
	adv        float64
	rmin, rmax float64
	engaged    bool
	dps        float64
	phantom    bool
}

// assess: the returned slice follows the (random) iteration order of the tracks map.
func (b *Bot) assess() []threat {
	var out []threat
	for _, tr := range b.tracks {
		if tr.NPC {
			continue
		}
		phantom := !tr.Listed && b.t-tr.PhantomT < 4 && b.t-tr.LastSeen > 1
		if b.t-tr.LastSeen > 8 && !phantom {
			continue
		}
		d := dist3(b.pos, tr.Pos)
		th := threat{tr: tr, d: d, phantom: phantom}
		th.adv, th.rmin, th.rmax = b.fightPlan(tr, d)
		th.dps = b.theirDPS(tr, d)
		aimR := 200.0
		if tr.Laser && b.realModel() {
			aimR = 285
		}
		th.engaged = b.t-tr.HurtMeT < 4 || (tr.LOS && b.t-tr.AimAtMeT < 0.6 && d < aimR) || (tr.LOS && d < 40)
		if !th.engaged && tr.LOS && d < 90 {
			bear := math.Atan2(b.pos[1]-tr.Pos[1], b.pos[0]-tr.Pos[0])
			closing := (tr.Vel[0]*(b.pos[0]-tr.Pos[0]) + tr.Vel[1]*(b.pos[1]-tr.Pos[1])) / math.Max(d, 1)
			if math.Abs(angDiff(tr.Aim[0], bear)) < 0.5 && closing > 4 {
				th.engaged = true
			}
		}
		if phantom {
			th.engaged = true
			th.dps = math.Max(th.dps, tr.HurtMe/3)
			th.adv = math.Min(th.adv, 0.5)
		}
		if th.engaged {
			tr.EngT = b.t
		} else if b.t-tr.EngT < 0.8 && tr.Listed {
			th.engaged = true
		}
		out = append(out, th)
	}
	return out
}

type stance struct {
	name                    string
	engageRatio, disengage  float64
	hunt, stealth, avoid    bool
	lootRadius              float64
	wantCubes               int
}

func (b *Bot) brawlStance(name string) stance {
	return stance{name: name, engageRatio: 1.3, disengage: 0.75, hunt: true, avoid: true, lootRadius: 220, wantCubes: 10}
}

func (b *Bot) realModel() bool { return b.ffa || b.openPhase() }

func (b *Bot) openPhase() bool {
	return b.t < b.P.OpenSecs || (b.P.CreditOpenS > 0 && b.t-b.creditAbsorbT < b.P.CreditOpenS) // from ahmad-ovh/Buildathon@56e0f76b (MIT)
}

func (b *Bot) belief() stance {
	total := int(stat(b.C.Match, "mechs", 16))
	dead := total - b.o.Alive
	if dead > b.deadSeen {
		n := dead - b.deadSeen
		b.deadSeen = dead
		if b.kills > b.killsSeen {
			n -= b.kills - b.killsSeen
			b.killsSeen = b.kills
		} else if b.t-b.creditT < 6 {
			mine := true
			if tr := b.tracks[b.creditID]; tr != nil && tr.Listed && tr.HP > 0 {
				mine = false
			}
			if mine {
				n--
				b.creditAbsorbT = b.t
			}
		}
		if n > 0 {
			b.unexplained += n
		}
		if (b.unexplained >= 1 && b.t < 35) || (b.unexplained >= 2 && b.t < 110) || b.unexplained >= 3 {
			b.ffa = true
		}
	}
	alive := b.o.Alive
	switch {
	case alive <= 2:
		return stance{name: "duel", engageRatio: 0.0, disengage: 0.45, hunt: true, lootRadius: 150, wantCubes: 40}
	case b.ffa:
		return b.brawlStance("ffa")
	case b.openPhase():
		return b.brawlStance("open")
	case b.P.CautiousT > 0 && b.P.PracticeAware && (b.t >= b.P.CautiousT || (b.o.Zone.NextRadius > 0 && b.o.Zone.NextRadius <= 72 && b.t >= 180)):
		return b.brawlStance("late") // from ahmad-ovh/Buildathon@56e0f76b (MIT)
	}
	return stance{name: "squad", engageRatio: b.P.EngageRatio, disengage: b.P.DisengageRat, hunt: b.P.Hunt, lootRadius: b.P.LootRadius, wantCubes: b.P.WantCubes}
}

// ---- §9.5 cover, visibility, fight plan

func (b *Bot) sameComp(cell int) bool {
	if b.myComp == 0 || cell < 0 {
		return true
	}
	return b.Nav.Components()[cell] == b.myComp
}

func (b *Bot) reachable(x, y float64) bool {
	if b.myComp == 0 {
		return true
	}
	c := b.Nav.Nearest(x, y, 2.9, 9, 3)
	return c >= 0 && b.Nav.Components()[c] == b.myComp
}

func (b *Bot) hiddenHere(ths []threat) bool {
	for i := range ths {
		tr := ths[i].tr
		if (b.t-tr.LastSeen > 6 && !ths[i].phantom) || ths[i].d > 260 {
			continue
		}
		sc := tr.scale(b.sizePerCube)
		ex, ey, ez := tr.Pos[0], tr.Pos[1], tr.Pos[2]+8*sc
		if b.W.Visible(ex, ey, ez, b.pos[0], b.pos[1], b.pos[2]+b.height*0.5) || b.W.Visible(ex, ey, ez, b.pos[0], b.pos[1], b.pos[2]+b.height*0.95) {
			return false
		}
	}
	return true
}

type eyePt struct{ x, y, z float64 }

// recentEyes: eye points of the threats not excluded by ((t-LastSeen > 6 && !phantom) || d > 260), ths order.
func (b *Bot) recentEyes(ths []threat) []eyePt {
	var eyes []eyePt
	for i := range ths {
		tr := ths[i].tr
		if (b.t-tr.LastSeen > 6 && !ths[i].phantom) || ths[i].d > 260 {
			continue
		}
		eyes = append(eyes, eyePt{tr.Pos[0], tr.Pos[1], tr.Pos[2] + 8*tr.scale(b.sizePerCube)})
	}
	return eyes
}

func (b *Bot) findCover(ths []threat, maxCost float64) int {
	eyes := b.recentEyes(ths)
	if len(eyes) == 0 {
		return -1
	}
	z := &b.o.Zone
	found := -1
	checked := 0
	b.Nav.Flood(b.pos[0], b.pos[1], b.radius+0.15, b.height, maxCost, nil, func(k int, cost float32) bool {
		if (k%b.Nav.NX+k/b.Nav.NX)%2 != 0 {
			return true
		}
		if float64(b.Nav.Clear[k]) < b.radius+0.6 {
			return true
		}
		x, y := b.Nav.Pos(k)
		if hyp(x-z.Center[0], y-z.Center[1]) > z.Radius-6 {
			return true
		}
		if z.ShrinkEnd-b.t < 25 && hyp(x-z.NextCenter[0], y-z.NextCenter[1]) > z.NextRadius-4 {
			return true
		}
		checked++
		if checked > 700 {
			return false
		}
		gz := float64(b.Nav.Z[k])
		for _, e := range eyes {
			if b.W.Visible(e.x, e.y, e.z, x, y, gz+b.height*0.5) || b.W.Visible(e.x, e.y, e.z, x, y, gz+b.height*0.95) {
				return true
			}
		}
		found = k
		return false
	})
	return found
}

func (b *Bot) cellHidden(k int, ths []threat) bool {
	x, y := b.Nav.Pos(k)
	gz := float64(b.Nav.Z[k])
	for i := range ths {
		tr := ths[i].tr
		if (b.t-tr.LastSeen > 6 && !ths[i].phantom) || ths[i].d > 260 {
			continue
		}
		sc := tr.scale(b.sizePerCube)
		ex, ey, ez := tr.Pos[0], tr.Pos[1], tr.Pos[2]+8*sc
		if b.W.Visible(ex, ey, ez, x, y, gz+b.height*0.5) || b.W.Visible(ex, ey, ez, x, y, gz+b.height*0.95) {
			return false
		}
	}
	return true
}

func (b *Bot) nearestEye(ths []threat) float64 {
	d0 := 1e9
	for i := range ths {
		tr := ths[i].tr
		if (b.t-tr.LastSeen > 6 && !ths[i].phantom) || ths[i].d > 260 {
			continue
		}
		if d := hyp(tr.Pos[0]-b.pos[0], tr.Pos[1]-b.pos[1]); d < d0 {
			d0 = d
		}
	}
	return d0
}

func (b *Bot) seenBy(ths []threat, maxD float64) []*threat {
	var out []*threat
	for i := range ths {
		if ths[i].tr.LOS && ths[i].tr.Listed && ths[i].d < maxD {
			out = append(out, &ths[i])
		}
	}
	return out
}

func (b *Bot) deeperCover(ths []threat, maxCost float64, farther bool) int {
	var eyes []eyePt
	d0 := 1e9
	for i := range ths {
		tr := ths[i].tr
		if (b.t-tr.LastSeen > 6 && !ths[i].phantom) || ths[i].d > 260 {
			continue
		}
		eyes = append(eyes, eyePt{tr.Pos[0], tr.Pos[1], tr.Pos[2] + 8*tr.scale(b.sizePerCube)})
		if d := hyp(tr.Pos[0]-b.pos[0], tr.Pos[1]-b.pos[1]); d < d0 {
			d0 = d
		}
	}
	if len(eyes) == 0 {
		return -1
	}
	needFar := farther && d0 <= 80
	hidden := func(x, y, gz float64) bool {
		for _, e := range eyes {
			if b.W.Visible(e.x, e.y, e.z, x, y, gz+b.height*0.5) || b.W.Visible(e.x, e.y, e.z, x, y, gz+b.height*0.95) {
				return false
			}
		}
		return true
	}
	// from ahmad-ovh/Buildathon@56e0f76b (MIT): hidden with room to spare (threat stepping CoverMargin sideways)
	margin := b.P.CoverMargin
	seen := func(ex, ey, ez, x, y, gz float64) bool {
		return b.W.Visible(ex, ey, ez, x, y, gz+b.height*0.5) || b.W.Visible(ex, ey, ez, x, y, gz+b.height*0.95)
	}
	robust := func(x, y, gz float64) bool {
		for _, e := range eyes {
			if seen(e.x, e.y, e.z, x, y, gz) {
				return false
			}
			if margin <= 0 {
				continue
			}
			dx, dy := x-e.x, y-e.y
			l := hyp(dx, dy)
			if l < 1 {
				return false
			}
			px, py := -dy/l*margin, dx/l*margin
			if seen(e.x+px, e.y+py, e.z, x, y, gz) || seen(e.x-px, e.y-py, e.z, x, y, gz) {
				return false
			}
		}
		return true
	}
	if !needFar && robust(b.pos[0], b.pos[1], b.pos[2]) {
		return -1
	}
	z := &b.o.Zone
	found := -1
	checked := 0
	b.Nav.Flood(b.pos[0], b.pos[1], b.radius+0.15, b.height, maxCost, nil, func(k int, cost float32) bool {
		if (k%b.Nav.NX+k/b.Nav.NX)%2 != 0 {
			return true
		}
		if float64(b.Nav.Clear[k]) < b.radius+0.6 {
			return true
		}
		x, y := b.Nav.Pos(k)
		if hyp(x-z.Center[0], y-z.Center[1]) > z.Radius-6 {
			return true
		}
		if z.ShrinkEnd-b.t < 25 && hyp(x-z.NextCenter[0], y-z.NextCenter[1]) > z.NextRadius-4 {
			return true
		}
		if needFar {
			de := 1e9
			for _, e := range eyes {
				if d := hyp(x-e.x, y-e.y); d < de {
					de = d
				}
			}
			if de < d0+18 {
				return true
			}
		}
		checked++
		if checked > 300 {
			return false
		}
		if !robust(x, y, float64(b.Nav.Z[k])) {
			return true
		}
		for _, f := range [3]float64{0.25, 0.5, 0.75} {
			mx, my := b.pos[0]+(x-b.pos[0])*f, b.pos[1]+(y-b.pos[1])*f
			mk := b.Nav.Index(mx, my)
			if b.Nav.Solid[mk] {
				continue
			}
			if !hidden(mx, my, float64(b.Nav.Z[mk])) {
				return true
			}
		}
		found = k
		return false
	})
	return found
}

func (b *Bot) fightPlan(tr *Track, d float64) (adv, rmin, rmax float64) {
	hp := tr.HP
	if hp <= 0 {
		hp = math.Max(tr.MaxHP, 1)
	}
	// from ahmad-ovh/Buildathon@56e0f76b (MIT): wider range ladder and a band around the best range
	cands := [...]float64{22, 45, 75, 115, 160, 200}
	bestAdv, bestR := -1.0, d
	eval := func(r float64, here bool) {
		mine := b.myDPS(r)
		theirs := b.theirDPS(tr, r) * (1 - b.armor) * b.dodgeFactor(r, tr)
		if mine < 1 {
			return
		}
		move := math.Abs(d - r)
		cost, gain := 0.0, 0.0
		if !here && move > 8 {
			mid := (d + r) / 2
			cost = b.theirDPS(tr, mid) * (1 - b.armor) * b.dodgeFactor(mid, tr) * (move / 9.0) * 0.8
			if b.P.PlanV2 && b.realModel() {
				gain = b.myDPS(mid) * (move / 9.0) * 0.8
			}
			if r > d && !tr.NPC {
				cost += 60
			}
		}
		left := b.hp - cost
		if left <= 0 {
			return
		}
		hpT := hp - gain
		if hpT < 20 {
			hpT = 20
		}
		a := 10.0
		if theirs >= 1 {
			a = (left / theirs) / (hpT / mine)
		}
		if here {
			a *= 1.05
		}
		if a > bestAdv {
			bestAdv, bestR = a, r
		}
	}
	eval(d, true)
	for _, r := range cands {
		eval(r, false)
	}
	if bestAdv < 0 {
		return 0, 30, 55
	}
	w := 10 + bestR*0.15
	return bestAdv, math.Max(8, bestR-w), bestR + w
}

func (b *Bot) dodgeFactor(r float64, tr *Track) float64 {
	if tr.NPC {
		return 0.6
	}
	return 1
}

// ---- §9.6 exploration

const seenCell = 32.0

func (b *Bot) markSeen() {
	if b.seenT == nil {
		b.seenNX = int(math.Ceil((b.W.MaxX-b.W.MinX)/seenCell)) + 1
		b.seenNY = int(math.Ceil((b.W.MaxY-b.W.MinY)/seenCell)) + 1
		b.seenT = make([]float32, b.seenNX*b.seenNY)
		for i := range b.seenT {
			b.seenT[i] = -1e6
		}
	}
	const R = 150.0
	half := b.C.Vision.FovDeg * math.Pi / 360
	if half <= 0 {
		half = math.Pi / 3
	}
	ex, ey, ez := b.pos[0], b.pos[1], b.pos[2]+b.eyeH
	i0 := int((ex - R - b.W.MinX) / seenCell)
	i1 := int((ex + R - b.W.MinX) / seenCell)
	j0 := int((ey - R - b.W.MinY) / seenCell)
	j1 := int((ey + R - b.W.MinY) / seenCell)
	for j := j0; j <= j1; j++ {
		if j < 0 || j >= b.seenNY {
			continue
		}
		for i := i0; i <= i1; i++ {
			if i < 0 || i >= b.seenNX {
				continue
			}
			k := j*b.seenNX + i
			if float64(b.seenT[k]) > b.t-2.0 {
				continue
			}
			cx := b.W.MinX + (float64(i)+0.5)*seenCell
			cy := b.W.MinY + (float64(j)+0.5)*seenCell
			d := hyp(cx-ex, cy-ey)
			if d > R {
				continue
			}
			if d > 40 && math.Abs(angDiff(math.Atan2(cy-ey, cx-ex), b.aim[0])) > half {
				continue
			}
			gz := b.W.TerrainZ(cx, cy) + 2
			if d < 20 || b.W.Visible(ex, ey, ez, cx, cy, gz) {
				b.seenT[k] = float32(b.t)
			}
		}
	}
}

func (b *Bot) roamGoal() (float64, float64, bool) {
	if b.seenT == nil {
		return 0, 0, false
	}
	if b.roamCell >= 0 && b.t-b.roamT < 12 && float64(b.seenT[b.roamCell]) < b.t-20 {
		i, j := b.roamCell%b.seenNX, b.roamCell/b.seenNX
		x, y := b.W.MinX+(float64(i)+0.5)*seenCell, b.W.MinY+(float64(j)+0.5)*seenCell
		if c := b.Nav.Nearest(x, y, b.radius+0.3, b.height, 8); c >= 0 {
			px, py := b.Nav.Pos(c)
			return px, py, true
		}
	}
	z := &b.o.Zone
	best, bs := -1, 1e18
	for j := 0; j < b.seenNY; j++ {
		for i := 0; i < b.seenNX; i++ {
			k := j*b.seenNX + i
			age := b.t - float64(b.seenT[k])
			if age < 45 {
				continue
			}
			x := b.W.MinX + (float64(i)+0.5)*seenCell
			y := b.W.MinY + (float64(j)+0.5)*seenCell
			if !b.W.InBounds(x, y) {
				continue
			}
			if hyp(x-z.NextCenter[0], y-z.NextCenter[1]) > z.NextRadius-15 {
				continue
			}
			nk := b.Nav.Index(x, y)
			if b.Nav.Solid[nk] {
				continue
			}
			if until, banned := b.banUntil[-(k + 1)]; banned && b.t < until {
				continue
			}
			if !b.reachable(x, y) {
				b.seenT[k] = float32(b.t)
				continue
			}
			d := hyp(x-b.pos[0], y-b.pos[1])
			s := d - math.Min(age, 300)*0.15
			if !b.ffa && b.P.PracticeRim > 0 && z.NextRadius >= 180 { // from ahmad-ovh/Buildathon@56e0f76b (MIT)
				dn := hyp(x-z.NextCenter[0], y-z.NextCenter[1])
				s += math.Abs(dn-z.NextRadius*0.88) * b.P.PracticeRim
			}
			if s < bs {
				best, bs = k, s
			}
		}
	}
	if best < 0 {
		return 0, 0, false
	}
	b.roamCell, b.roamT = best, b.t
	i, j := best%b.seenNX, best/b.seenNX
	x, y := b.W.MinX+(float64(i)+0.5)*seenCell, b.W.MinY+(float64(j)+0.5)*seenCell
	if c := b.Nav.Nearest(x, y, b.radius+0.3, b.height, 8); c >= 0 {
		px, py := b.Nav.Pos(c)
		return px, py, true
	}
	b.seenT[best] = float32(b.t)
	return 0, 0, false
}
