package bot

import "math"

// Per-opponent gun lead, from ahmad-ovh/Buildathon@56e0f76b internal/bot/lead.go (MIT).
// Each decision scores one "virtual shot" fired one flight time ago, with and without lead, against
// where the mech really is now; gunLead then aims the way that has been missing by less.

func (b *Bot) leadRecord(tr *Track, facing bool) {
	if tr.hn > 0 {
		last := &tr.hist[(tr.hi+trkHist-1)%trkHist]
		if b.t-last.t > 0.25 || b.t <= last.t {
			if b.t <= last.t {
				return
			}
			tr.hn, tr.hi = 0, 0
		}
	}
	tr.hist[tr.hi] = trkSample{t: b.t, x: tr.Pos[0], y: tr.Pos[1], vx: tr.Vel[0], vy: tr.Vel[1], facing: facing}
	tr.hi = (tr.hi + 1) % trkHist
	if tr.hn < trkHist {
		tr.hn++
	}
	d := hyp(tr.Pos[0]-b.pos[0], tr.Pos[1]-b.pos[1])
	if d < 55 || d > 240 {
		return
	}
	gunSpd := stat(b.C.Weapons["gun"], "speed", 252)
	if b.P.SmartFireV2 {
		if gi := b.has("gun"); gi >= 0 {
			gunSpd = stat(b.slots[gi].stats, "speed", gunSpd)
		}
	}
	tf := math.Max(0, d-3) / math.Max(gunSpd, 1)
	s := b.leadSample(tr, b.t-(fireLatency+tf))
	if s == nil || !s.facing {
		return
	}
	side := func(px, py float64) float64 {
		ax, ay := norm2(px-b.pos[0], py-b.pos[1])
		return math.Abs(-(tr.Pos[0]-b.pos[0])*ay + (tr.Pos[1]-b.pos[1])*ax)
	}
	k := b.leadPersistAt(tr, s.t)
	lead := (fireLatency + tf*b.leadDamp(tf)) * k
	mNone := math.Min(side(s.x, s.y), 6)
	mLead := math.Min(side(s.x+s.vx*lead, s.y+s.vy*lead), 6)
	const keep = 0.997
	tr.leadN = tr.leadN*keep + 1
	tr.missNone = tr.missNone*keep + mNone
	tr.missLead = tr.missLead*keep + mLead
}

func (b *Bot) leadSample(tr *Track, t float64) *trkSample {
	var best *trkSample
	bd := 0.07
	for i := 0; i < tr.hn; i++ {
		s := &tr.hist[(tr.hi+trkHist-1-i)%trkHist]
		if dt := math.Abs(s.t - t); dt < bd {
			best, bd = s, dt
		}
		if s.t < t-0.1 {
			break
		}
	}
	return best
}

// leadPersistAt: how straight the mech moved over the 1.2 s before t (1 = steady walk, 0 = jitter).
func (b *Bot) leadPersistAt(tr *Track, t float64) float64 {
	if !b.P.LeadPersist {
		return 1
	}
	var first, last *trkSample
	n := 0
	sp := 0.0
	for i := 0; i < tr.hn; i++ {
		s := &tr.hist[(tr.hi+trkHist-1-i)%trkHist]
		if s.t > t+0.01 {
			continue
		}
		if s.t < t-1.25 {
			break
		}
		if last == nil {
			last = s
		}
		first = s
		sp += hyp(s.vx, s.vy)
		n++
	}
	if n < 8 || last == nil || last.t-first.t < 0.7 {
		return 1
	}
	mean := hyp(last.x-first.x, last.y-first.y) / (last.t - first.t)
	pers := mean / math.Max(sp/float64(n), 0.5)
	return clamp((pers-0.2)/0.5, 0, 1)
}
