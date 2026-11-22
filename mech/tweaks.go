package mech

import (
	"math"
)

var (
	tweakFinalHold  = true
	tweakNoAirBoost = true
	tweakCubeLevel  = true
	tweakLeadK      = 0.0
	tweakLaserSlew  = true
	tweakLethalK    = 0.0
)

func (b *Brain) finalHold(o *Obs) (float64, float64) {
	z := &o.Zone
	me := &o.Self
	if z.NextRadius > 0.5 || b.now < z.ShrinkStart-2 || b.now > z.ShrinkEnd || z.ShrinkEnd <= z.ShrinkStart {
		return 0, math.Inf(1)
	}
	cx, cy := z.NextCenter[0], z.NextCenter[1]
	if b.W.Obst[b.W.vidx(cx, cy)] || b.W.OffMain(cx, cy) {
		return 0, math.Inf(1)
	}
	c := b.curZone(z)
	tol := clamp((c.R-hyp(c.X-cx, c.Y-cy))/3, 0.9, 6)
	mine := b.Cfg.Mech.Radius * b.scaleOf(me.Cubes)
	for _, t := range b.tracks {
		if b.now-t.Seen > 0.5 {
			continue
		}
		if need := mine + b.Cfg.Mech.Radius*b.scaleOf(t.Cubes) - hyp(t.Pos[0]-cx, t.Pos[1]-cy) + 0.7; need > tol {
			tol = need
		}
	}
	return hyp(cx-me.Pos[0], cy-me.Pos[1]), tol
}

func (b *Brain) leadK(muzzle, tp, tv Vec3, speed float64, grounded bool, t0, k float64) (float64, float64) {
	if speed <= 0 {
		speed = 252
	}
	t := 0.0
	var px, py, pz float64
	for it := 0; it < 4; it++ {
		tt := k * (t0 + t)
		px, py, pz = tp[0]+tv[0]*tt, tp[1]+tv[1]*tt, tp[2]
		if !grounded {
			pz += tv[2] * tt * 0.5
		}
		d := math.Sqrt((px-muzzle[0])*(px-muzzle[0]) + (py-muzzle[1])*(py-muzzle[1]) + (pz-muzzle[2])*(pz-muzzle[2]))
		t = math.Max(0, d-3) / speed
	}
	return math.Atan2(py-muzzle[1], px-muzzle[0]), math.Atan2(pz-muzzle[2], hyp(px-muzzle[0], py-muzzle[1]))
}
