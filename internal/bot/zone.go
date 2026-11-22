package bot

import "math"

type zoneInfo struct {
	outNext          float64
	outCur           float64
	tPass            float64
	goal             [2]float64
	urgent, critical bool
	final            bool
	walkable         bool
}

func (b *Bot) zoneInfo() zoneInfo {
	z := &b.o.Zone
	var zi zoneInfo
	dn := hyp(b.pos[0]-z.NextCenter[0], b.pos[1]-z.NextCenter[1])
	dc := hyp(b.pos[0]-z.Center[0], b.pos[1]-z.Center[1])
	zi.outNext = dn - z.NextRadius
	zi.outCur = dc - z.Radius
	zi.tPass = math.Inf(1)
	zi.final = z.NextRadius < 12
	t0 := math.Max(b.t, z.ShrinkStart)
	if zi.outCur > 0 {
		zi.tPass = 0
	} else if zi.outNext > 0 && z.ShrinkEnd > t0 {
		for i := 1; i <= 50; i++ {
			f := float64(i) / 50
			cx := z.Center[0] + (z.NextCenter[0]-z.Center[0])*f
			cy := z.Center[1] + (z.NextCenter[1]-z.Center[1])*f
			r := z.Radius + (z.NextRadius-z.Radius)*f
			if hyp(b.pos[0]-cx, b.pos[1]-cy) > r {
				zi.tPass = (t0 - b.t) + f*(z.ShrinkEnd-t0)
				break
			}
		}
	} else if zi.outNext > 0 && z.ShrinkEnd <= t0 {
		zi.tPass = 0
	}
	dx, dy := norm2(b.pos[0]-z.NextCenter[0], b.pos[1]-z.NextCenter[1])
	gr := math.Min(z.NextRadius*0.6, z.NextRadius-10)
	if gr < 0 {
		gr = 0
	}
	zi.goal = [2]float64{z.NextCenter[0] + dx*gr, z.NextCenter[1] + dy*gr}
	zi.walkable = true
	key := [3]float64{z.NextCenter[0], z.NextCenter[1], z.NextRadius}
	if key != b.zgKey || b.t-b.zgT > 1.0 || b.zgComp != b.myComp {
		b.zgKey, b.zgT, b.zgComp = key, b.t, b.myComp
		margin := math.Min(5, z.NextRadius*0.3)
		base := math.Atan2(dy, dx)
		found, foundAny := false, false
		var anyGoal [2]float64
	search:
		for _, fr := range [...]float64{0.6, 0.45, 0.75, 0.3, 0.15, 0.9, 0.0} {
			rr := math.Max(0, math.Min(z.NextRadius*fr, z.NextRadius-10))
			for _, off := range [...]float64{0, 0.4, -0.4, 0.8, -0.8, 1.4, -1.4, 2.2, -2.2, math.Pi} {
				x, y := z.NextCenter[0]+math.Cos(base+off)*rr, z.NextCenter[1]+math.Sin(base+off)*rr
				k := b.Nav.Nearest(x, y, b.radius+0.3, b.height, 4)
				if k < 0 {
					continue
				}
				px, py := b.Nav.Pos(k)
				if z.NextRadius > 12 && hyp(px-z.NextCenter[0], py-z.NextCenter[1]) > z.NextRadius-margin {
					continue
				}
				if !b.sameComp(k) {
					if !foundAny {
						foundAny, anyGoal = true, [2]float64{px, py}
					}
					continue
				}
				b.zgGoal, found = [2]float64{px, py}, true
				break search
			}
		}
		b.zgWalk = found
		if !found {
			if foundAny {
				b.zgGoal = anyGoal
			} else {
				b.zgGoal = [2]float64{z.NextCenter[0], z.NextCenter[1]}
			}
		}
	}
	zi.goal, zi.walkable = b.zgGoal, b.zgWalk
	need := 0.0
	if zi.outNext > 0 {
		need = (zi.outNext+8)/b.walk*1.35 + 4
	}
	zi.critical = zi.outCur > -2 || zi.tPass < 2.5
	zi.urgent = zi.critical || zi.tPass < 9 || (zi.outNext > 0 && z.ShrinkEnd-b.t < need) || (zi.outNext > 0 && zi.tPass-need < 3)
	return zi
}

func (b *Bot) inFutureZone(x, y, secs, margin float64) bool {
	z := &b.o.Zone
	if hyp(x-z.Center[0], y-z.Center[1]) > z.Radius-margin {
		return false
	}
	if b.t+secs > z.ShrinkStart {
		f := 1.0
		if z.ShrinkEnd > z.ShrinkStart {
			f = clamp((b.t+secs-z.ShrinkStart)/(z.ShrinkEnd-z.ShrinkStart), 0, 1)
		}
		cx := z.Center[0] + (z.NextCenter[0]-z.Center[0])*f
		cy := z.Center[1] + (z.NextCenter[1]-z.Center[1])*f
		r := z.Radius + (z.NextRadius-z.Radius)*f
		if hyp(x-cx, y-cy) > r-margin {
			return false
		}
	}
	return true
}
