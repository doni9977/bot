package bot

import "math"

type incoming struct {
	mortar      bool
	pos, vel    [3]float64
	maxT        float64
	impact      [3]float64
	dmg, splash float64
}

func (b *Bot) gatherIncoming() []incoming {
	var out []incoming
	g := stat(b.C.Weapons["mortar"], "gravity", 22)
	for i := range b.o.Projectiles {
		p := &b.o.Projectiles[i]
		sp := math.Sqrt(p.Vel[0]*p.Vel[0] + p.Vel[1]*p.Vel[1] + p.Vel[2]*p.Vel[2])
		if sp < 1 {
			continue
		}
		if p.Kind == "mortar" {
			x, y, z := p.Pos[0], p.Pos[1], p.Pos[2]
			vx, vy, vz := p.Vel[0], p.Vel[1], p.Vel[2]
			tt := 0.0
			const h = 0.05 // from ahmad-ovh/Buildathon@56e0f76b (MIT)
			hit := false
			for tt < 7 {
				nx, ny, nz := x+vx*h, y+vy*h, z+vz*h-0.5*g*h*h
				if !b.W.Visible(x, y, z, nx, ny, nz) {
					hit = true
					break
				}
				x, y, z = nx, ny, nz
				vz -= g * h
				tt += h
			}
			if !hit {
				continue
			}
			splash := stat(b.C.Weapons["mortar"], "splash_radius", 7) * 1.3
			if dist3([3]float64{x, y, z}, b.pos) > splash+b.radius+45 {
				continue
			}
			out = append(out, incoming{mortar: true, pos: p.Pos, vel: p.Vel, maxT: tt + h, impact: [3]float64{x, y, z},
				dmg: stat(b.C.Weapons["mortar"], "splash", 160), splash: splash})
			continue
		}
		rx, ry := b.pos[0]-p.Pos[0], b.pos[1]-p.Pos[1]
		along := (rx*p.Vel[0] + ry*p.Vel[1]) / sp
		if along < -3 {
			continue
		}
		d := hyp(rx, ry)
		if d > 330 {
			continue
		}
		lat := math.Abs(rx*p.Vel[1]-ry*p.Vel[0]) / math.Max(hyp(p.Vel[0], p.Vel[1]), 1)
		if lat > 14+b.radius {
			continue
		}
		reach := b.W.Raycast(p.Pos[0], p.Pos[1], p.Pos[2], p.Vel[0]/sp, p.Vel[1]/sp, p.Vel[2]/sp, d+20)
		if reach < d-b.radius-3 {
			continue
		}
		dmg := stat(b.C.Weapons["gun"], "damage", 45)
		if p.Kind == "npc" {
			dmg = stat(b.C.Npc, "damage", 25)
		}
		out = append(out, incoming{pos: p.Pos, vel: p.Vel, maxT: reach / sp, dmg: dmg})
	}
	return out
}

type steerReq struct {
	wantX, wantY float64
	wantW        float64
	boost        bool
	slow         bool
	posCost      func(x, y float64) float64
	hold         bool
	threats      []incoming
	lookTicks    int
	dodgeBoost   bool
	fenceRoof    bool
	zoneFree     bool
}

var dirs16 [16][2]float64

func init() {
	for i := 0; i < 16; i++ {
		dirs16[i] = [2]float64{math.Cos(float64(i) * math.Pi / 8), math.Sin(float64(i) * math.Pi / 8)}
	}
}

type cand struct {
	dx, dy float64
	boost  bool
	score  float64
}

func (b *Bot) steer(act *Action, rq steerReq) {
	grounded := b.o.Self.Grounded
	accel := b.mech("ground_accel", 58.5)
	if !grounded {
		accel = b.mech("air_accel", 12)
	}
	walk := b.walk
	if rq.slow {
		walk *= b.mech("charge_move_mult", 0.5)
	}
	boostV := b.boostV
	if rq.slow {
		boostV *= b.mech("charge_move_mult", 0.5)
	}
	canBoost := b.energy > 12 && grounded
	horizon := 8
	for i := range rq.threats {
		k := int(rq.threats[i].maxT/b.dt) + 2
		if k > horizon {
			horizon = k
		}
	}
	if horizon > 44 { // from ahmad-ovh/Buildathon@56e0f76b (MIT)
		horizon = 44
	}
	progTick := 6
	if rq.lookTicks > progTick {
		progTick = rq.lookTicks
		if horizon < progTick {
			horizon = progTick
		}
	}

	cands := make([]cand, 0, 40)
	cands = append(cands, cand{0, 0, false, 0})
	for i := 0; i < 16; i++ {
		cands = append(cands, cand{dirs16[i][0], dirs16[i][1], false, 0})
	}
	if rq.wantX != 0 || rq.wantY != 0 {
		cands = append(cands, cand{rq.wantX, rq.wantY, false, 0})
	}
	if canBoost && (rq.boost || rq.dodgeBoost || len(rq.threats) > 0) {
		n := len(cands)
		for i := 1; i < n; i++ {
			cands = append(cands, cand{cands[i].dx, cands[i].dy, true, 0})
		}
	}

	zc, zr := b.o.Zone.Center, b.o.Zone.Radius
	fence := -1
	var roofOf []int32
	var roofDist []int16
	startCell := b.Nav.Index(b.pos[0], b.pos[1])
	startClear := b.Nav.Clear[startCell]
	groundLevel := b.onGroundLevel()
	startRD := int16(0)
	if rq.fenceRoof {
		fence = b.onRoof()
		_, roofOf = b.Nav.Roofs()
		roofDist = b.Nav.RoofDist()
		startRD = roofDist[startCell]
	}
	minClear := float32(b.radius * 0.8)
	best := -1
	for ci := range cands {
		c := &cands[ci]
		sp := walk
		if c.boost {
			sp = boostV
		}
		tvx, tvy := c.dx*sp, c.dy*sp
		x, y := b.pos[0], b.pos[1]
		vx, vy := b.vel[0], b.vel[1]
		score := 0.0
		blocked := false
		var px, py float64
		for k := 1; k <= horizon; k++ {
			vx, vy = approach2(vx, vy, tvx, tvy, accel*b.dt)
			nx, ny := x+vx*b.dt, y+vy*b.dt
			cell := b.Nav.Index(nx, ny)
			if cell != startCell {
				if fence >= 0 {
					if int(roofOf[cell]) != fence || (roofDist[cell] < 2 && roofDist[cell] < startRD) {
						blocked = true
						vx, vy = 0, 0
						nx, ny = x, y
					}
				} else if groundLevel && (b.Nav.Solid[cell] || !b.W.InBounds(nx, ny) || (b.Nav.Clear[cell] < minClear && b.Nav.Clear[cell] < startClear)) {
					blocked = true
					vx, vy = 0, 0
					nx, ny = x, y
				}
			}
			x, y = nx, ny
			if k == progTick {
				px, py = x, y
			}
			t0 := float64(k-1) * b.dt
			t1 := float64(k) * b.dt
			for ti := range rq.threats {
				th := &rq.threats[ti]
				if th.mortar {
					if th.maxT > t0 && th.maxT <= t1+1e-9 || (k == horizon && th.maxT > t1) {
						d := math.Sqrt((x-th.impact[0])*(x-th.impact[0]) + (y-th.impact[1])*(y-th.impact[1]) + (b.pos[2]+b.height*0.5-th.impact[2])*(b.pos[2]+b.height*0.5-th.impact[2]))
						reach := th.splash + b.radius
						if d < reach {
							score -= th.dmg*(1-0.7*d/reach) + 40
						}
					}
					continue
				}
				if t0 >= th.maxT {
					continue
				}
				te := math.Min(t1, th.maxT)
				ax, ay := th.pos[0]+th.vel[0]*t0, th.pos[1]+th.vel[1]*t0
				bx, by := th.pos[0]+th.vel[0]*te, th.pos[1]+th.vel[1]*te
				d, s := segPointDist2D(x, y, ax, ay, bx, by)
				if d < b.radius+0.3+0.55 {
					tz := th.pos[2] + th.vel[2]*(t0+(te-t0)*s)
					if tz > b.pos[2]-0.6 && tz < b.pos[2]+b.height+0.6 {
						score -= th.dmg
					}
				}
			}
		}
		if horizon < progTick {
			px, py = x, y
		}
		score += ((px-b.pos[0])*rq.wantX + (py-b.pos[1])*rq.wantY) * rq.wantW
		if blocked {
			score -= 3
		}
		if zr > 0 && !rq.zoneFree {
			dOut := hyp(px-zc[0], py-zc[1]) - zr
			dNow := hyp(b.pos[0]-zc[0], b.pos[1]-zc[1]) - zr
			if dNow < -0.5 && dOut > -4 && dOut > dNow {
				score -= (dOut - dNow) * 8
			}
		}
		if rq.posCost != nil {
			score -= rq.posCost(px, py)
		}
		if c.boost && !rq.boost {
			score -= 1.5
		}
		if c.dx == 0 && c.dy == 0 {
			if rq.hold {
				score += 0.6
			}
		} else {
			score += 0.25 * (c.dx*b.lastMove[0] + c.dy*b.lastMove[1])
		}
		c.score = score
		if best < 0 || score > cands[best].score {
			best = ci
		}
	}
	if best >= 0 {
		act.Move = [2]float64{cands[best].dx, cands[best].dy}
		act.Boost = cands[best].boost
	}
}

func (b *Bot) onGroundLevel() bool {
	k := b.Nav.Index(b.pos[0], b.pos[1])
	if b.Nav.Solid[k] {
		return false
	}
	return b.pos[2]-float64(b.Nav.Z[k]) < 3.5
}

func (b *Bot) navDir(gx, gy float64) (float64, float64, float64, bool) {
	d := hyp(gx-b.pos[0], gy-b.pos[1])
	if d < 1.0 {
		return 0, 0, d, true
	}
	if !b.onGroundLevel() {
		dx, dy := norm2(gx-b.pos[0], gy-b.pos[1])
		return dx, dy, d, true
	}
	r, h := b.radius+0.15, b.height
	if d < 14 && b.Nav.WalkLine(b.pos[0], b.pos[1], gx, gy, r, h) {
		dx, dy := norm2(gx-b.pos[0], gy-b.pos[1])
		return dx, dy, d, true
	}
	other := !b.pathSet || hyp(gx-b.pathGoal[0], gy-b.pathGoal[1]) > 5
	replan := len(b.path) == 0 || other || b.t-b.pathT > 1.6
	if !replan && b.pathIdx < len(b.path) {
		px, py := b.Nav.Pos(int(b.path[b.pathIdx]))
		if hyp(px-b.pos[0], py-b.pos[1]) > 12 {
			replan = true
		}
	}
	gap := 0.35
	if b.pathBad {
		gap = 1.0
	}
	if other {
		gap = 0.15
	}
	if replan && b.pathSet && b.t-b.pathT < gap {
		replan = false
	}
	if other && !replan {
		dx, dy := norm2(gx-b.pos[0], gy-b.pos[1])
		return dx, dy, d, true
	}
	if replan {
		b.pathSet = true
		b.path = b.Nav.Path(b.pos[0], b.pos[1], gx, gy, r, h, 9000, b.navCost())
		b.pathGoal = [2]float64{gx, gy}
		b.pathT = b.t
		b.pathIdx = 0
		b.pathBad = len(b.path) == 0
		if !b.pathBad {
			lx, ly := b.Nav.Pos(int(b.path[len(b.path)-1]))
			b.pathBad = hyp(lx-gx, ly-gy) > 7
		}
	}
	if len(b.path) == 0 {
		dx, dy := norm2(gx-b.pos[0], gy-b.pos[1])
		return dx, dy, d, false
	}
	if b.pathBad {
		lx, ly := b.Nav.Pos(int(b.path[len(b.path)-1]))
		if hyp(lx-b.pos[0], ly-b.pos[1]) < 4 {
			dx, dy := norm2(gx-b.pos[0], gy-b.pos[1])
			return dx, dy, d, false
		}
	}
	for b.pathIdx < len(b.path)-1 {
		px, py := b.Nav.Pos(int(b.path[b.pathIdx]))
		if hyp(px-b.pos[0], py-b.pos[1]) < 3.2 {
			b.pathIdx++
		} else {
			break
		}
	}
	tgt := b.pathIdx
	hi := b.pathIdx + 14
	if hi > len(b.path)-1 {
		hi = len(b.path) - 1
	}
	for j := hi; j > b.pathIdx; j -= 2 {
		px, py := b.Nav.Pos(int(b.path[j]))
		if b.Nav.WalkLine(b.pos[0], b.pos[1], px, py, r, h) {
			tgt = j
			break
		}
	}
	if tgt > b.pathIdx+1 {
		b.pathIdx = tgt - 1
	}
	px, py := b.Nav.Pos(int(b.path[tgt]))
	if tgt == len(b.path)-1 && hyp(gx-px, gy-py) < 4 {
		px, py = gx, gy
	}
	dx, dy := norm2(px-b.pos[0], py-b.pos[1])
	return dx, dy, d, true
}

func (b *Bot) unstick(act *Action, navigating bool) {
	if !navigating {
		b.stuckFor = 0
		b.stuckT = b.t
		b.stuckPos = b.pos
		b.unstickT = 0
		return
	}
	moving := hyp(act.Move[0], act.Move[1]) > 0.3
	if b.t-b.stuckT >= 0.5 {
		moved := dist2(b.pos, b.stuckPos)
		if moving && moved < 1.2 {
			b.stuckFor += b.t - b.stuckT
		} else {
			b.stuckFor = 0
		}
		b.stuckT = b.t
		b.stuckPos = b.pos
	}
	if b.stuckFor >= 1.0 && b.t > b.unstickT {
		a := b.rng.Float64() * 2 * math.Pi
		b.unstickDir = [2]float64{math.Cos(a), math.Sin(a)}
		b.unstickT = b.t + 0.7
		b.stuckFor = 0
		b.path = nil
	}
	if b.t < b.unstickT {
		act.Move = [2]float64{act.Move[0]*0.4 + b.unstickDir[0], act.Move[1]*0.4 + b.unstickDir[1]}
		l := hyp(act.Move[0], act.Move[1])
		if l > 1 {
			act.Move[0] /= l
			act.Move[1] /= l
		}
		if b.o.Self.Grounded {
			act.Jump = true
		} else if b.energy > 30 {
			act.Boost = true
		}
	}
}
