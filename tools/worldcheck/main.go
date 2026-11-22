// worldcheck prints the §10.3 checkpoints of the arena-derived structures.
package main

import (
	"encoding/binary"
	"fmt"
	"hash/fnv"
	"math"
	"os"

	"apexbot/internal/world"
)

func hf32(v []float32) uint64 {
	h := fnv.New64a()
	var b [4]byte
	for _, x := range v {
		binary.LittleEndian.PutUint32(b[:], math.Float32bits(x))
		h.Write(b[:])
	}
	return h.Sum64()
}

func hi32(v []int32) uint64 {
	h := fnv.New64a()
	var b [4]byte
	for _, x := range v {
		binary.LittleEndian.PutUint32(b[:], uint32(x))
		h.Write(b[:])
	}
	return h.Sum64()
}

func hi16(v []int16) uint64 {
	h := fnv.New64a()
	var b [2]byte
	for _, x := range v {
		binary.LittleEndian.PutUint16(b[:], uint16(x))
		h.Write(b[:])
	}
	return h.Sum64()
}

func hbool(v []bool) uint64 {
	h := fnv.New64a()
	for _, x := range v {
		if x {
			h.Write([]byte{1})
		} else {
			h.Write([]byte{0})
		}
	}
	return h.Sum64()
}

func main() {
	dir := "/arena"
	if len(os.Args) > 1 {
		dir = os.Args[1]
	}
	w, err := world.Load(dir)
	if err != nil {
		fmt.Println("load:", err)
		os.Exit(1)
	}
	fmt.Printf("World : prismes=%d arêtes=%d arbres=%d TerrainMax=%f hash(H)=%016x\n", len(w.Prisms), len(w.Edges), len(w.Trees), w.TerrainMax, hf32(w.H))
	n := world.NewNav(w, 1.2, 9)
	ns := 0
	for _, s := range n.Solid {
		if s {
			ns++
		}
	}
	fmt.Printf("Nav   : NX=%d NY=%d MinX=%.2f MinY=%.2f cellules Solid=%d\n", n.NX, n.NY, n.MinX, n.MinY, ns)
	fmt.Printf("hash  : Z=%016x Clear=%016x Head=%016x Solid=%016x Roof=%016x\n", hf32(n.Z), hf32(n.Clear), hf32(n.Head), hbool(n.Solid), hf32(n.Roof))
	n.Exposure()
	comp := n.Components()
	cnt := map[int32]int{}
	maxc := int32(0)
	for _, c := range comp {
		if c > 0 {
			cnt[c]++
		}
		if c > maxc {
			maxc = c
		}
	}
	big, bigN := int32(0), 0
	for id := int32(1); id <= maxc; id++ {
		if cnt[id] > bigN {
			big, bigN = id, cnt[id]
		}
	}
	fmt.Printf("Components : %d composantes ; la plus grande = id %d (%d cellules) ; hash(comp)=%016x\n", maxc, big, bigN, hi32(comp))
	roofs, roofOf := n.Roofs()
	fmt.Printf("Roofs : %d toits retenus ; hash(roofOf)=%016x ; hash(roofDist)=%016x\n", len(roofs), hi32(roofOf), hi16(n.RoofDist()))
	e := n.Exposure()
	fmt.Printf("Exposure : NX=%d NY=%d hash(V)=%016x\n", e.NX, e.NY, hf32(e.V))
	fmt.Printf("Tops : hash=%016x\n", hf32(n.Tops()))
	fmt.Printf("TerrainZ(0,0)=%.9f   TerrainZ(100.5,-50.25)=%.9f\n", w.TerrainZ(0, 0), w.TerrainZ(100.5, -50.25))
	fmt.Printf("Raycast(0,0,20, dir +x, maxT 400)=%.9f   Visible((0,0,10),(150,40,10))=%v\n", w.Raycast(0, 0, 20, 1, 0, 0, 400), w.Visible(0, 0, 10, 150, 40, 10))
	p := n.Path(-200, 0, 200, 50, 2.5, 9, 6000, nil)
	fmt.Printf("Path(-200,0 → 200,50, r=2.5, h=9, maxExpand=6000, extra=nil) : longueur %d, hash=%016x\n", len(p), hi32(p))
	fmt.Printf("Nearest(0,0, r=2.9, h=9, maxR=4)=%d\n", n.Nearest(0, 0, 2.9, 9, 4))
	fmt.Println()
	for _, id := range []int{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 18, 19, 43, 69, 92} {
		if id >= len(roofs) {
			continue
		}
		r := roofs[id]
		fmt.Printf("%d Z=%.4f cells=%d area=%.0f height=%.4f inner=%d innerD=%.1f access=%d C=(%.4f,%.4f)\n", r.ID, r.Z, len(r.Cells), r.Area, r.Height, r.Inner, r.InnerD, len(r.Access), r.CX, r.CY)
	}
}
