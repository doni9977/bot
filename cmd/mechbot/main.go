// Command mechbot is the apex-go mechfight/1 bot: JSON lines on stdin, one action per observation on stdout.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"runtime/debug"
	"strconv"

	"apexbot/internal/bot"
	"apexbot/internal/proto"
	"apexbot/internal/world"
)

type agent interface {
	Act(o *proto.Obs) proto.Action
}

// newAgent builds the real bot for a hello; returns nil when the arena cannot be loaded.
// It may panic: the caller recovers and falls back to blind.
func newAgent(h *proto.Hello) (agent, string) {
	w := loadWorld(h.Map.Dir, "/arena", "arena")
	if w == nil {
		return nil, "doni"
	}
	nav := world.NewNav(w, proto.Stat(h.Config.Mech, "step_up", 1.2), proto.Stat(h.Config.Mech, "height", 9))
	p := bot.DefaultParams()
	b := bot.New(h, w, nav, p)
	return b, b.P.Name
}

// loadWorld: first directory that loads; "" is skipped.
func loadWorld(dirs ...string) *world.World {
	for _, d := range dirs {
		if d == "" {
			continue
		}
		w, err := world.Load(d)
		if err == nil {
			return w
		}
	}
	return nil
}

func main() {
	debug.SetGCPercent(800)
	debug.SetMemoryLimit(380 << 20)
	lines := make(chan []byte, 256)
	go func() {
		rd := bufio.NewReaderSize(os.Stdin, 1<<20)
		for {
			line, err := rd.ReadBytes('\n')
			if len(bytes.TrimSpace(line)) > 0 {
				lines <- line
			}
			if err != nil {
				close(lines)
				return
			}
		}
	}()
	out := bufio.NewWriterSize(os.Stdout, 1<<16)
	var ag agent
	var last proto.Action
	buf := make([]byte, 0, 512)
	badObs := 0

	handle := func(line []byte) (obsLine []byte, done bool) {
		if bytes.Contains(line[:min(len(line), 40)], []byte(`"obs"`)) {
			return line, false
		}
		var head struct {
			Type string `json:"type"`
		}
		if err := json.Unmarshal(line, &head); err != nil {
			return nil, false
		}
		switch head.Type {
		case "obs":
			return line, false
		case "end":
			return nil, true
		case "hello":
			var h proto.Hello
			if err := json.Unmarshal(line, &h); err != nil {
				h = proto.Hello{}
				json.Unmarshal(stripZeroFractions(line), &h)
			}
			name := "doni"
			func() {
				defer func() {
					if r := recover(); r != nil {
						fmt.Fprintf(os.Stderr, "init panic: %v\n", r)
						ag = blind{}
					}
				}()
				a, n := newAgent(&h)
				if a == nil {
					ag = blind{}
					return
				}
				name = n
				ag = a
			}()
			buf = buf[:0]
			buf = append(buf, `{"type":"ready","name":`...)
			buf = strconv.AppendQuote(buf, name)
			buf = append(buf, "}\n"...)
			out.Write(buf)
			out.Flush()
		}
		return nil, false
	}

	for line := range lines {
		latest, done := handle(line)
		if done {
			return
		}
	drain:
		for {
			select {
			case more, ok := <-lines:
				if !ok {
					break drain
				}
				l2, d2 := handle(more)
				if d2 {
					return
				}
				if l2 != nil {
					latest = l2
				}
			default:
				break drain
			}
		}
		if latest == nil {
			continue
		}
		var o proto.Obs
		if err := json.Unmarshal(latest, &o); err != nil {
			o = proto.Obs{}
			if err2 := json.Unmarshal(stripZeroFractions(latest), &o); err2 != nil {
				badObs++
				if badObs <= 5 || badObs%200 == 0 {
					fmt.Fprintf(os.Stderr, "bad obs (%d): %v\n", badObs, err2)
				}
				if tick, ok := sniffTick(latest); ok {
					act := proto.NewAction(tick)
					act.Move, act.Boost, act.Aim, act.HasAim = last.Move, last.Boost, last.Aim, last.HasAim
					buf = act.AppendJSON(buf[:0])
					buf = append(buf, '\n')
					out.Write(buf)
					out.Flush()
				}
				continue
			}
		}
		if ag == nil {
			ag = blind{}
		}
		act := safeAct(ag, &o, &last)
		if act.Tick != o.Tick {
			act.Tick = o.Tick
		}
		last = act
		buf = act.AppendJSON(buf[:0])
		buf = append(buf, '\n')
		out.Write(buf)
		out.Flush()
	}
}

// safeAct: on a panic in Act, emit the previous move/boost/aim without fire nor label.
func safeAct(ag agent, o *proto.Obs, last *proto.Action) (act proto.Action) {
	defer func() {
		if r := recover(); r != nil {
			fmt.Fprintf(os.Stderr, "act panic: %v\n", r)
			act = proto.NewAction(o.Tick)
			act.Move = last.Move
			act.Boost = last.Boost
			act.Aim = last.Aim
			act.HasAim = last.HasAim
		}
	}()
	return ag.Act(o)
}

// stripZeroFractions removes zero fractions outside strings: "3.0" -> "3", "12.000," -> "12,".
func stripZeroFractions(in []byte) []byte {
	out := make([]byte, 0, len(in))
	inStr, esc := false, false
	for i := 0; i < len(in); i++ {
		c := in[i]
		if inStr {
			out = append(out, c)
			if esc {
				esc = false
			} else if c == '\\' {
				esc = true
			} else if c == '"' {
				inStr = false
			}
			continue
		}
		if c == '"' {
			inStr = true
			out = append(out, c)
			continue
		}
		if c == '.' && i > 0 && in[i-1] >= '0' && in[i-1] <= '9' {
			j := i + 1
			for j < len(in) && in[j] == '0' {
				j++
			}
			if j > i+1 && j < len(in) && (in[j] == ',' || in[j] == ']' || in[j] == '}' || in[j] == ' ' || in[j] == '\n') {
				i = j - 1
				continue
			}
		}
		out = append(out, c)
	}
	return out
}

// sniffTick reads the integer after the first `"tick":` (leading spaces skipped).
func sniffTick(line []byte) (int, bool) {
	k := bytes.Index(line, []byte(`"tick":`))
	if k < 0 {
		return 0, false
	}
	n, seen := 0, false
	for i := k + 7; i < len(line); i++ {
		c := line[i]
		if c == ' ' && !seen {
			continue
		}
		if c < '0' || c > '9' {
			break
		}
		n = n*10 + int(c-'0')
		seen = true
	}
	return n, seen
}

// blind is the fallback agent (no arena, or a panic during init).
type blind struct{}

func (blind) Act(o *proto.Obs) proto.Action {
	a := proto.NewAction(o.Tick)
	me := o.Self
	gx, gy := o.Zone.NextCenter[0], o.Zone.NextCenter[1]
	yaw := math.Atan2(gy-me.Pos[1], gx-me.Pos[0])
	if math.Hypot(gx-me.Pos[0], gy-me.Pos[1]) > 10 {
		a.Move = [2]float64{math.Cos(yaw), math.Sin(yaw)}
	}
	a.Aim = [2]float64{yaw, 0}
	a.HasAim = true
	a.Boost = !me.InZone
	best := -1.0
	for i := range o.Mechs {
		m := &o.Mechs[i]
		if m.Kind != "mech" {
			continue
		}
		d := math.Hypot(m.Pos[0]-me.Pos[0], m.Pos[1]-me.Pos[1])
		if best < 0 || d < best {
			best = d
			tf := d / 252
			a.Aim = [2]float64{
				math.Atan2(m.Pos[1]+m.Vel[1]*tf-me.Pos[1], m.Pos[0]+m.Vel[0]*tf-me.Pos[0]),
				math.Atan2(m.Pos[2]+4.5-me.Pos[2]-7, math.Max(d, 1)),
			}
			a.Fire = [2]bool{true, true}
		}
	}
	if o.Offer != nil {
		a.Pick = 0
	}
	return a
}
