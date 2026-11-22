package world

import (
	"math"
	"sort"
	"sync"
)

// Nav is a 2 m walk grid on ground level (terrain, small steppable plinths, under bridges).
type Nav struct {
	W     *World
	Cell  float64
	NX    int
	NY    int
	MinX  float64
	MinY  float64
	Z     []float32
	Clear []float32
	Head  []float32
	Solid []bool
	Roof  []float32

	shared *navShared

	g      []float32
	parent []int32
	stamp  []uint32
	closed []uint32
	gen    uint32
	open   navHeap
}

type navShared struct {
	expOnce  sync.Once
	exp      *Exposure
	compOnce sync.Once
	comp     []int32
	roofOnce sync.Once
	roofs    []Roof
	roofOf   []int32
	roofDist []int16
	topsOnce sync.Once
	tops     []float32
}

const (
	NavClearCap = 8.0
	NavHeadCap  = 40.0
)

const tanMaxSlope = 1.19

var navDI = [8]int{1, -1, 0, 0, 1, 1, -1, -1}
var navDJ = [8]int{0, 0, 1, -1, 1, -1, 1, -1}

// NewNav builds the walk grid (stepUp = config.mech.step_up, bodyHeight = config.mech.height).
func NewNav(w *World, stepUp, bodyHeight float64) *Nav {
	n := &Nav{W: w, Cell: 2.0, shared: &navShared{}}
	n.MinX = math.Floor(w.MinX)
	n.MinY = math.Floor(w.MinY)
	n.NX = int(math.Ceil((w.MaxX - n.MinX) / n.Cell))
	n.NY = int(math.Ceil((w.MaxY - n.MinY) / n.Cell))
	N := n.NX * n.NY
	n.Z = make([]float32, N)
	n.Clear = make([]float32, N)
	n.Head = make([]float32, N)
	n.Solid = make([]bool, N)
	n.Roof = make([]float32, N)
	nan := float32(math.NaN())
	for j := 0; j < n.NY; j++ {
		for i := 0; i < n.NX; i++ {
			k := j*n.NX + i
			x, y := n.Center(i, j)
			n.Roof[k] = nan
			if !w.InBounds(x, y) {
				n.Solid[k] = true
				continue
			}
			g := w.TerrainZ(x, y)
			solid := false
			c := w.cellOf(x, y)
			cand := w.prismIdx[w.prismOff[c]:w.prismOff[c+1]]
			for iter := 0; iter < 4; iter++ {
				changed := false
				for _, pi := range cand {
					p := &w.Prisms[pi]
					if p.Top <= g || p.Base > g+0.3 || !p.Contains(x, y) {
						continue
					}
					if p.Top-g <= stepUp {
						g = p.Top
						changed = true
					} else {
						solid = true
						if math.IsNaN(float64(n.Roof[k])) || float32(p.Top) > n.Roof[k] {
							n.Roof[k] = float32(p.Top)
						}
					}
				}
				if !changed {
					break
				}
			}
			if solid {
				top := float64(n.Roof[k])
				for iter := 0; iter < 4; iter++ {
					changed := false
					for _, pi := range cand {
						p := &w.Prisms[pi]
						if p.Top > top && p.Base <= top+0.3 && p.Contains(x, y) {
							top = p.Top
							changed = true
						}
					}
					if !changed {
						break
					}
				}
				n.Roof[k] = float32(top)
				n.Solid[k] = true
				continue
			}
			n.Z[k] = float32(g)
			head := w.Ceiling(x, y, g+0.3) - g
			if head > NavHeadCap {
				head = NavHeadCap
			}
			n.Head[k] = float32(head)
			n.Clear[k] = float32(w.WallDist(x, y, g+stepUp+0.05, g+bodyHeight, NavClearCap))
		}
	}
	n.g = make([]float32, N)
	n.parent = make([]int32, N)
	n.stamp = make([]uint32, N)
	n.closed = make([]uint32, N)
	return n
}

func (n *Nav) Center(i, j int) (float64, float64) {
	return n.MinX + (float64(i)+0.5)*n.Cell, n.MinY + (float64(j)+0.5)*n.Cell
}

func (n *Nav) CellAt(x, y float64) (int, int) {
	i := clampi(int((x-n.MinX)/n.Cell), 0, n.NX-1)
	j := clampi(int((y-n.MinY)/n.Cell), 0, n.NY-1)
	return i, j
}

func (n *Nav) Index(x, y float64) int {
	i, j := n.CellAt(x, y)
	return j*n.NX + i
}

func (n *Nav) Pos(k int) (float64, float64) { return n.Center(k%n.NX, k/n.NX) }

func (n *Nav) Walkable(k int, r, h float64) bool {
	return !n.Solid[k] && float64(n.Clear[k]) >= r && float64(n.Head[k]) >= h
}

func (n *Nav) canStep(from, to int, dist float64) bool {
	rise := float64(n.Z[to] - n.Z[from])
	lim := tanMaxSlope * dist * 0.85
	if lim < 1.2 {
		lim = 1.2
	}
	return rise <= lim
}

func absi(a int) int {
	if a < 0 {
		return -a
	}
	return a
}

// Nearest: square-ring search of radius 0..maxR; returns as soon as a ring holds a candidate.
func (n *Nav) Nearest(x, y, r, h float64, maxR int) int {
	ci, cj := n.CellAt(x, y)
	best, bestD := -1, 1e18
	for rad := 0; rad <= maxR; rad++ {
		for dj := -rad; dj <= rad; dj++ {
			for di := -rad; di <= rad; di++ {
				if absi(di) != rad && absi(dj) != rad {
					continue
				}
				i, j := ci+di, cj+dj
				if i < 0 || j < 0 || i >= n.NX || j >= n.NY {
					continue
				}
				k := j*n.NX + i
				if !n.Walkable(k, r, h) {
					continue
				}
				px, py := n.Center(i, j)
				d := (px-x)*(px-x) + (py-y)*(py-y)
				if d < bestD {
					best, bestD = k, d
				}
			}
		}
		if best >= 0 {
			return best
		}
	}
	return best
}

type navItem struct {
	k int32
	f float32
}

type navHeap []navItem

func (h *navHeap) push(it navItem) {
	*h = append(*h, it)
	a := *h
	i := len(a) - 1
	for i > 0 {
		p := (i - 1) / 2
		if a[p].f <= a[i].f {
			break
		}
		a[p], a[i] = a[i], a[p]
		i = p
	}
}

func (h *navHeap) pop() navItem {
	a := *h
	top := a[0]
	n := len(a) - 1
	a[0] = a[n]
	a = a[:n]
	i := 0
	for {
		l := 2*i + 1
		if l >= n {
			break
		}
		m := l
		if r := l + 1; r < n && a[r].f < a[l].f {
			m = r
		}
		if a[i].f <= a[m].f {
			break
		}
		a[i], a[m] = a[m], a[i]
		i = m
	}
	*h = a
	return top
}

type CostFn func(k int) float32

func (n *Nav) nextGen() uint32 {
	n.gen++
	if n.gen == 0 {
		for i := range n.stamp {
			n.stamp[i] = 0
			n.closed[i] = 0
		}
		n.gen = 1
	}
	return n.gen
}

func (n *Nav) tracePath(end int) []int32 {
	var path []int32
	for k := end; k >= 0 && len(path) < 100001; k = int(n.parent[k]) {
		path = append(path, int32(k))
	}
	for i, j := 0, len(path)-1; i < j; i, j = i+1, j-1 {
		path[i], path[j] = path[j], path[i]
	}
	return path
}

// Path: A* on the walk grid; partial path to the closest explored cell if the goal is not reached.
func (n *Nav) Path(sx, sy, tx, ty, r, h float64, maxExpand int, extra CostFn) []int32 {
	start := n.Nearest(sx, sy, r, h, 6)
	goal := n.Nearest(tx, ty, r, h, 10)
	if start < 0 || goal < 0 {
		return nil
	}
	if start == goal {
		return []int32{int32(start)}
	}
	gen := n.nextGen()
	gi, gj := goal%n.NX, goal/n.NX
	hfn := func(k int) float32 {
		di := float64(absi(k%n.NX - gi))
		dj := float64(absi(k/n.NX - gj))
		mn, mx := di, dj
		if mn > mx {
			mn, mx = mx, mn
		}
		return float32((mx + 0.4142*mn) * n.Cell * 1.15)
	}
	n.open = n.open[:0]
	n.g[start] = 0
	n.parent[start] = -1
	n.stamp[start] = gen
	n.open.push(navItem{int32(start), hfn(start)})
	expanded := 0
	bestK, bestH := start, hfn(start)
	found := false
	wantClear := float32(r + 2.0)
	for len(n.open) > 0 {
		it := n.open.pop()
		k := int(it.k)
		if n.closed[k] == gen {
			continue
		}
		n.closed[k] = gen
		if k == goal {
			found = true
			break
		}
		expanded++
		if expanded > maxExpand {
			break
		}
		hk := hfn(k)
		if hk < bestH {
			bestH, bestK = hk, k
		}
		ci, cj := k%n.NX, k/n.NX
		for d := 0; d < 8; d++ {
			i, j := ci+navDI[d], cj+navDJ[d]
			if i < 0 || j < 0 || i >= n.NX || j >= n.NY {
				continue
			}
			nk := j*n.NX + i
			if n.closed[nk] == gen || !n.Walkable(nk, r, h) {
				continue
			}
			dist := n.Cell
			if d >= 4 {
				if !n.Walkable(cj*n.NX+i, r, h) || !n.Walkable(j*n.NX+ci, r, h) {
					continue
				}
				dist *= 1.41421356
			}
			if !n.canStep(k, nk, dist) {
				continue
			}
			cost := float32(dist)
			if n.Clear[nk] < wantClear {
				cost += (wantClear - n.Clear[nk]) * 0.6
			}
			if extra != nil {
				cost += extra(nk)
			}
			ng := n.g[k] + cost
			if n.stamp[nk] != gen || ng < n.g[nk] {
				n.g[nk] = ng
				n.parent[nk] = int32(k)
				n.stamp[nk] = gen
				n.open.push(navItem{int32(nk), ng + hfn(nk)})
			}
		}
	}
	end := goal
	if !found {
		end = bestK
		if end == start {
			return nil
		}
	}
	return n.tracePath(end)
}

func (n *Nav) WalkLine(ax, ay, bx, by, r, h float64) bool {
	d := math.Hypot(bx-ax, by-ay)
	steps := int(d/(n.Cell*0.5)) + 1
	prev := n.Index(ax, ay)
	if !n.Walkable(prev, r, h) {
		return false
	}
	for s := 1; s <= steps; s++ {
		t := float64(s) / float64(steps)
		k := n.Index(ax+(bx-ax)*t, ay+(by-ay)*t)
		if k == prev {
			continue
		}
		if !n.Walkable(k, r, h) {
			return false
		}
		if !n.canStep(prev, k, n.Cell) {
			return false
		}
		prev = k
	}
	return true
}

// Flood: bounded Dijkstra; visit returns false to stop.
func (n *Nav) Flood(sx, sy, r, h, maxCost float64, extra CostFn, visit func(k int, cost float32) bool) {
	start := n.Nearest(sx, sy, r, h, 6)
	if start < 0 {
		return
	}
	gen := n.nextGen()
	n.open = n.open[:0]
	n.g[start] = 0
	n.parent[start] = -1
	n.stamp[start] = gen
	n.open.push(navItem{int32(start), 0})
	for len(n.open) > 0 {
		it := n.open.pop()
		k := int(it.k)
		if n.closed[k] == gen {
			continue
		}
		n.closed[k] = gen
		if !visit(k, n.g[k]) {
			return
		}
		ci, cj := k%n.NX, k/n.NX
		for d := 0; d < 8; d++ {
			i, j := ci+navDI[d], cj+navDJ[d]
			if i < 0 || j < 0 || i >= n.NX || j >= n.NY {
				continue
			}
			nk := j*n.NX + i
			if n.closed[nk] == gen || !n.Walkable(nk, r, h) {
				continue
			}
			dist := n.Cell
			if d >= 4 {
				if !n.Walkable(cj*n.NX+i, r, h) || !n.Walkable(j*n.NX+ci, r, h) {
					continue
				}
				dist *= 1.41421356
			}
			if !n.canStep(k, nk, dist) {
				continue
			}
			cost := float32(dist)
			if extra != nil {
				cost += extra(nk)
			}
			ng := n.g[k] + cost
			if float64(ng) > maxCost {
				continue
			}
			if n.stamp[nk] != gen || ng < n.g[nk] {
				n.g[nk] = ng
				n.parent[nk] = int32(k)
				n.stamp[nk] = gen
				n.open.push(navItem{int32(nk), ng})
			}
		}
	}
}

// Components: connected walkable regions (0 = not walkable; ids from 1). Built once.
func (n *Nav) Components() []int32 {
	n.shared.compOnce.Do(func() { n.shared.comp = n.buildComponents() })
	return n.shared.comp
}

func (n *Nav) buildComponents() []int32 {
	const r, h = 2.9, 9.0
	comp := make([]int32, n.NX*n.NY)
	var stack []int32
	next := int32(0)
	for s := range comp {
		if comp[s] != 0 || !n.Walkable(s, r, h) {
			continue
		}
		next++
		comp[s] = next
		stack = append(stack[:0], int32(s))
		for len(stack) > 0 {
			k := int(stack[len(stack)-1])
			stack = stack[:len(stack)-1]
			ci, cj := k%n.NX, k/n.NX
			for d := 0; d < 4; d++ {
				i, j := ci+navDI[d], cj+navDJ[d]
				if i < 0 || j < 0 || i >= n.NX || j >= n.NY {
					continue
				}
				nk := j*n.NX + i
				if comp[nk] != 0 || !n.Walkable(nk, r, h) {
					continue
				}
				if !n.canStep(k, nk, n.Cell) && !n.canStep(nk, k, n.Cell) {
					continue
				}
				comp[nk] = next
				stack = append(stack, int32(nk))
			}
		}
	}
	return comp
}

// Tops: height of the highest surface at each cell centre. Built once.
func (n *Nav) Tops() []float32 {
	n.shared.topsOnce.Do(func() {
		tops := make([]float32, n.NX*n.NY)
		for j := 0; j < n.NY; j++ {
			for i := 0; i < n.NX; i++ {
				x, y := n.Center(i, j)
				h, _ := n.W.Floor(x, y, 1e9)
				tops[j*n.NX+i] = float32(h)
			}
		}
		n.shared.tops = tops
	})
	return n.shared.tops
}

// SurfacePath routes over the top of everything: walking, dropping, jet climbs up to maxClimb.
func (n *Nav) SurfacePath(sx, sy, sz, tx, ty, maxClimb, bodyR float64, maxExpand int, blocked func(k int) bool) []int32 {
	tops := n.Tops()
	si, sj := n.CellAt(sx, sy)
	gi, gj := n.CellAt(tx, ty)
	start, goal := sj*n.NX+si, gj*n.NX+gi
	if start == goal {
		return []int32{int32(start)}
	}
	gen := n.nextGen()
	hfn := func(k int) float32 {
		di := float64(absi(k%n.NX - gi))
		dj := float64(absi(k/n.NX - gj))
		mn, mx := di, dj
		if mn > mx {
			mn, mx = mx, mn
		}
		return float32((mx + 0.4142*mn) * n.Cell * 1.1)
	}
	n.open = n.open[:0]
	n.g[start] = 0
	n.parent[start] = -1
	n.stamp[start] = gen
	n.open.push(navItem{int32(start), hfn(start)})
	expanded := 0
	bestK, bestH := start, hfn(start)
	found := false
	for len(n.open) > 0 {
		it := n.open.pop()
		k := int(it.k)
		if n.closed[k] == gen {
			continue
		}
		n.closed[k] = gen
		if k == goal {
			found = true
			break
		}
		expanded++
		if expanded > maxExpand {
			break
		}
		if hk := hfn(k); hk < bestH {
			bestH, bestK = hk, k
		}
		hcur := float64(tops[k])
		if k == start {
			hcur = sz
		}
		ci, cj := k%n.NX, k/n.NX
		for d := 0; d < 8; d++ {
			i, j := ci+navDI[d], cj+navDJ[d]
			if i < 0 || j < 0 || i >= n.NX || j >= n.NY {
				continue
			}
			nk := j*n.NX + i
			if n.closed[nk] == gen {
				continue
			}
			x, y := n.Center(i, j)
			if !n.W.InBounds(x, y) {
				continue
			}
			dist := n.Cell
			if d >= 4 {
				dist *= 1.41421356
			}
			if blocked != nil && blocked(nk) {
				continue
			}
			dh := float64(tops[nk]) - hcur
			cost := dist
			switch {
			case dh > maxClimb:
				continue
			case dh > 1.2:
				cost += 10 + dh*2.2
			case dh < -1.2:
				cost += 1.5
			}
			if !n.Solid[nk] && float64(n.Clear[nk]) < bodyR-0.3 {
				cost += 14
			}
			ng := n.g[k] + float32(cost)
			if n.stamp[nk] != gen || ng < n.g[nk] {
				n.g[nk] = ng
				n.parent[nk] = int32(k)
				n.stamp[nk] = gen
				n.open.push(navItem{int32(nk), ng + hfn(nk)})
			}
		}
	}
	end := goal
	if !found {
		end = bestK
		if end == start {
			return nil
		}
	}
	return n.tracePath(end)
}

type Roof struct {
	ID     int
	Z      float64
	Cells  []int32
	Area   float64
	Height float64
	Inner  int
	InnerD float64
	Access []RoofAccess
	CX, CY float64
}

type RoofAccess struct {
	Ground int
	Edge   int
	Climb  float64
}

func (n *Nav) buildShared() {
	n.shared.roofOnce.Do(func() { n.shared.roofs, n.shared.roofOf, n.shared.roofDist = buildRoofs(n) })
}

// Roofs returns the kept roofs and the per-cell roof id (-1 = none). Built once.
func (n *Nav) Roofs() ([]Roof, []int32) {
	n.buildShared()
	return n.shared.roofs, n.shared.roofOf
}

// RoofDist returns the per-cell distance to the roof edge (1 = edge cell, 0 = not a kept roof).
func (n *Nav) RoofDist() []int16 {
	n.buildShared()
	return n.shared.roofDist
}

func buildRoofs(n *Nav) ([]Roof, []int32, []int16) {
	N := n.NX * n.NY
	roofOf := make([]int32, N)
	for i := range roofOf {
		roofOf[i] = -1
	}
	var roofs []Roof
	var stack []int32
	for s := 0; s < N; s++ {
		if roofOf[s] >= 0 || !n.Solid[s] || math.IsNaN(float64(n.Roof[s])) {
			continue
		}
		id := int32(len(roofs))
		z0 := float64(n.Roof[s])
		roofOf[s] = id
		stack = append(stack[:0], int32(s))
		var cells []int32
		sumZ := 0.0
		for len(stack) > 0 {
			k := int(stack[len(stack)-1])
			stack = stack[:len(stack)-1]
			cells = append(cells, int32(k))
			sumZ += float64(n.Roof[k])
			ci, cj := k%n.NX, k/n.NX
			for d := 0; d < 4; d++ {
				i, j := ci+navDI[d], cj+navDJ[d]
				if i < 0 || j < 0 || i >= n.NX || j >= n.NY {
					continue
				}
				nk := j*n.NX + i
				if roofOf[nk] >= 0 || !n.Solid[nk] || math.IsNaN(float64(n.Roof[nk])) {
					continue
				}
				if math.Abs(float64(n.Roof[nk])-z0) > 0.8 || math.Abs(float64(n.Roof[nk]-n.Roof[k])) > 0.6 {
					continue
				}
				roofOf[nk] = id
				stack = append(stack, int32(nk))
			}
		}
		roofs = append(roofs, Roof{ID: int(id), Z: sumZ / float64(len(cells)), Cells: cells, Area: float64(len(cells)) * n.Cell * n.Cell})
	}
	dist := make([]int16, N)
	for ri := range roofs {
		r := &roofs[ri]
		var q []int32
		minGround := math.Inf(1)
		sx, sy := 0.0, 0.0
		for _, c := range r.Cells {
			k := int(c)
			x, y := n.Pos(k)
			sx += x
			sy += y
			ci, cj := k%n.NX, k/n.NX
			edge := false
			for d := 0; d < 8; d++ {
				i, j := ci+navDI[d], cj+navDJ[d]
				if i < 0 || j < 0 || i >= n.NX || j >= n.NY {
					edge = true
					continue
				}
				nk := j*n.NX + i
				if roofOf[nk] != int32(ri) {
					edge = true
					if !n.Solid[nk] {
						g := float64(n.Z[nk])
						if g < minGround {
							minGround = g
						}
					}
				}
			}
			if edge {
				dist[k] = 1
				q = append(q, c)
			} else {
				dist[k] = 0
			}
		}
		r.CX, r.CY = sx/float64(len(r.Cells)), sy/float64(len(r.Cells))
		for h := 0; h < len(q); h++ {
			k := int(q[h])
			ci, cj := k%n.NX, k/n.NX
			for d := 0; d < 4; d++ {
				i, j := ci+navDI[d], cj+navDJ[d]
				if i < 0 || j < 0 || i >= n.NX || j >= n.NY {
					continue
				}
				nk := j*n.NX + i
				if roofOf[nk] == int32(ri) && dist[nk] == 0 {
					dist[nk] = dist[k] + 1
					q = append(q, int32(nk))
				}
			}
		}
		best, bd := int(r.Cells[0]), int16(0)
		for _, c := range r.Cells {
			if dist[c] > bd {
				best, bd = int(c), dist[c]
			}
		}
		r.Inner = best
		r.InnerD = (float64(bd) - 0.5) * n.Cell
		if math.IsInf(minGround, 1) {
			r.Height = 0
		} else {
			r.Height = r.Z - minGround
		}
		for _, c := range r.Cells {
			k := int(c)
			if dist[k] != 1 {
				continue
			}
			ci, cj := k%n.NX, k/n.NX
			for d := 0; d < 4; d++ {
				i1, j1 := ci+navDI[d], cj+navDJ[d]
				if i1 < 0 || j1 < 0 || i1 >= n.NX || j1 >= n.NY || n.Solid[j1*n.NX+i1] {
					continue
				}
				for step := 2; step <= 3; step++ {
					i, j := ci+navDI[d]*step, cj+navDJ[d]*step
					if i < 0 || j < 0 || i >= n.NX || j >= n.NY {
						break
					}
					g := j*n.NX + i
					if n.Solid[g] {
						break
					}
					if n.Walkable(g, 2.7, 9) {
						i2, j2 := ci-navDI[d]*2, cj-navDJ[d]*2
						if i2 < 0 || j2 < 0 || i2 >= n.NX || j2 >= n.NY || roofOf[j2*n.NX+i2] != int32(ri) {
							break
						}
						r.Access = append(r.Access, RoofAccess{Ground: g, Edge: j2*n.NX + i2, Climb: r.Z - float64(n.Z[g])})
						break
					}
				}
			}
		}
	}
	var keep []Roof
	remap := make([]int32, len(roofs))
	for i := range remap {
		remap[i] = -1
	}
	sort.SliceStable(roofs, func(a, b int) bool { return roofs[a].ID < roofs[b].ID })
	for i := range roofs {
		r := roofs[i]
		if r.Area < 250 || r.InnerD < 5 || len(r.Access) == 0 {
			continue
		}
		remap[r.ID] = int32(len(keep))
		r.ID = len(keep)
		keep = append(keep, r)
	}
	for i := range roofOf {
		if roofOf[i] >= 0 {
			roofOf[i] = remap[roofOf[i]]
		}
	}
	for i := range dist {
		if roofOf[i] < 0 {
			dist[i] = 0
		}
	}
	return keep, roofOf, dist
}

// Exposure is a coarse map of how open each spot is (V = 2: unusable).
type Exposure struct {
	Step   int
	NX, NY int
	V      []float32
	nav    *Nav
}

// Exposure returns the shared exposure map NewExposure(n, 3, 24, 8, 200). Built once.
func (n *Nav) Exposure() *Exposure {
	n.shared.expOnce.Do(func() { n.shared.exp = NewExposure(n, 3, 24, 8, 200) })
	return n.shared.exp
}

func NewExposure(n *Nav, step, rays int, eyeH, maxR float64) *Exposure {
	e := &Exposure{Step: step, nav: n}
	e.NX = (n.NX + step - 1) / step
	e.NY = (n.NY + step - 1) / step
	e.V = make([]float32, e.NX*e.NY)
	dirs := make([][2]float64, rays)
	for i := 0; i < rays; i++ {
		a := (float64(i) + 0.5) * 2 * math.Pi / float64(rays)
		dirs[i] = [2]float64{math.Cos(a), math.Sin(a)}
	}
	for j := 0; j < e.NY; j++ {
		for i := 0; i < e.NX; i++ {
			ci, cj := i*step+step/2, j*step+step/2
			if ci >= n.NX {
				ci = n.NX - 1
			}
			if cj >= n.NY {
				cj = n.NY - 1
			}
			k := cj*n.NX + ci
			if n.Solid[k] || n.Clear[k] < 2.6 {
				e.V[j*e.NX+i] = 2
				continue
			}
			x, y := n.Center(ci, cj)
			z := float64(n.Z[k]) + eyeH
			sum := 0.0
			for _, d := range dirs {
				free := n.W.Raycast(x, y, z, d[0], d[1], 0, maxR)
				if free > 45 {
					if c := n.W.CanopyReach(x, y, z, d[0], d[1], 0, free); c < free {
						free = math.Max(c, 45)
					}
				}
				sum += free
			}
			e.V[j*e.NX+i] = float32(sum / (float64(rays) * maxR))
		}
	}
	return e
}

func (e *Exposure) At(k int) float32 {
	ci, cj := k%e.nav.NX, k/e.nav.NX
	i, j := ci/e.Step, cj/e.Step
	if i >= e.NX {
		i = e.NX - 1
	}
	if j >= e.NY {
		j = e.NY - 1
	}
	return e.V[j*e.NX+i]
}

func (e *Exposure) Cell(i, j int) int {
	ci, cj := i*e.Step+e.Step/2, j*e.Step+e.Step/2
	if ci >= e.nav.NX {
		ci = e.nav.NX - 1
	}
	if cj >= e.nav.NY {
		cj = e.nav.NY - 1
	}
	return cj*e.nav.NX + ci
}
