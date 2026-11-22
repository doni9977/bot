// Package bot holds the apex-go policy: memory (observe) and decisions (think).
package bot

import (
	"math"
	"math/rand"

	"apexbot/internal/proto"
	"apexbot/internal/world"
)

type (
	Obs    = proto.Obs
	Action = proto.Action
	Hello  = proto.Hello
	Config = proto.Config
	World  = world.World
	Nav    = world.Nav
)

var stat = proto.Stat

// Params are the effective production parameters (§5.1). They are variables, not constants.
type Params struct {
	Name            string
	EngageRatio     float64
	DisengageRat    float64
	RetreatHP       float64
	ReturnHP        float64
	LeadDamp        float64
	GunMaxRange     float64
	StrafeMin       float64
	StrafeMax       float64
	LootRadius      float64
	WantCubes       int
	DropGreed       float64
	Hunt            bool
	PracticeAware   bool
	FFAReturnFire   float64
	Salt            int
	DuelDisengage   float64
	UseRoofs        bool
	RoofInSquad     bool
	RoofMaxClimb    float64
	RoofMinHeight   float64
	RoofMinZone     float64
	DropRadius      float64
	LeaveTTD        float64
	UseHideMap      bool
	QuietHoldS      float64
	ArmSwapMin      float64
	HitModel        int
	PlanV2          bool
	KiteNeedsLaser  bool
	ExchangeW       float64
	BrawlEngage     float64
	BrawlDisengage  float64
	BrawlHunt       bool
	BrawlLootRadius float64
	BrawlWantCubes  int
	AvoidAdv        float64
	AvoidRange      float64
	AvoidCover      float64
	CoverFirst      bool
	EdgeHold        float64
	RunOnRange      float64
	RunOnGain       float64
	CoverMargin     float64
	RetreatRunMax   float64
	LootHiddenBias  float64
	CoverEdgeAdv    float64
	HuntLaserEdge   bool
	Peek            bool
	OverlandEarly   float64
	RoofCoverHold   float64
	RoofStandCheck  bool
	DropStick       bool
	ClimbClearRange float64
	RoofLeaveQuiet  float64
	ZoneSlack       float64
	BrawlRoofs      bool
	BrawlRoofCubes  int
	BrawlRoofAfter  float64
	Jink            float64
	LeadPersist     bool
	LeadCum         bool
	LaserPreempt    bool
	AvoidCoverLaser float64
	HoldHideMap     bool
	LaserAimRange   float64
	PathFix         bool
	CreditFix       bool
	LootBoost       float64
	PlinkMaxDPS     float64
	HuntRange       float64
	HuntRangeLaser  float64
	KiteMin         float64
	KiteMax         float64
	CookoffAware    bool
	AntiLightningW  float64
	LaserDodgeV2    bool
	SmartFireV2     bool
	BeamFFA         bool
	UpV2            bool
	LaserMechOnly   bool
	LaserCDTrack    bool
	DropRun         float64
	// restored from ahmad-ovh/Buildathon@56e0f76b (MIT)
	LeadCumMin    float64
	LaserEarlyRel bool
	RearBonus     float64
	CookoffBonus  float64
	KillFocus     float64
	AntiLightningPad float64
	RearAvoidW       float64
	OpenSecs         float64
	CreditOpenS      float64
	CoverMinRange    float64
	NoMortar         bool
	LaserValue       float64
	LightningValue   float64
	CautiousT        float64
	RetreatPest      bool
	FinalHold        bool
	CoverReload      bool
	PracticeRim      float64
}

func DefaultParams() Params {
	return Params{
		Name: "doni", EngageRatio: 1.25, DisengageRat: 0.75, RetreatHP: 0.45, ReturnHP: 0.85, LeadDamp: 0.65,
		GunMaxRange: 224, StrafeMin: 0.35, StrafeMax: 1.1, LootRadius: 220, WantCubes: 15, DropGreed: 0.5,
		Hunt: true, PracticeAware: true, FFAReturnFire: 230, Salt: 8, DuelDisengage: 0.5, UseRoofs: true,
		RoofInSquad: false, RoofMaxClimb: 40, RoofMinHeight: 12, RoofMinZone: 60, DropRadius: 300, LeaveTTD: 10,
		UseHideMap: false, QuietHoldS: 3, ArmSwapMin: 1, HitModel: 1, PlanV2: true, KiteNeedsLaser: true,
		ExchangeW: 0, BrawlEngage: 1.3, BrawlDisengage: 0.75, BrawlHunt: true, BrawlLootRadius: 220,
		BrawlWantCubes: 10, AvoidAdv: 1.25, AvoidRange: 85, AvoidCover: 55, CoverFirst: true, EdgeHold: 2.5,
		RunOnRange: 80, RunOnGain: 18, CoverMargin: 8, RetreatRunMax: 0, LootHiddenBias: 0.5, CoverEdgeAdv: 3,
		HuntLaserEdge: true, Peek: false, OverlandEarly: 0, RoofCoverHold: 6, RoofStandCheck: true, DropStick: true,
		ClimbClearRange: 150, RoofLeaveQuiet: 25, ZoneSlack: 10, BrawlRoofs: true, BrawlRoofCubes: 6,
		BrawlRoofAfter: 60, Jink: 0, LeadPersist: true, LeadCum: true, LaserPreempt: true, AvoidCoverLaser: 90,
		HoldHideMap: false, LaserAimRange: 285, PathFix: true, CreditFix: true, LootBoost: 30, PlinkMaxDPS: 60,
		HuntRange: 130, HuntRangeLaser: 130, KiteMin: 130, KiteMax: 190, CookoffAware: false, AntiLightningW: 180,
		LaserDodgeV2: false, SmartFireV2: true, BeamFFA: true, UpV2: false, LaserMechOnly: false,
		LaserCDTrack: true, DropRun: 0,
		LeadCumMin: 8, LaserEarlyRel: true, RearBonus: 0.25, CookoffBonus: 0.30,
		AntiLightningPad: 12, RearAvoidW: 35,
		OpenSecs: 24, CreditOpenS: 25, CoverMinRange: 40, NoMortar: true, LaserValue: 6.0, LightningValue: 2.6,
		CautiousT: 265, RetreatPest: true, FinalHold: true, CoverReload: true, PracticeRim: 0.6,
	}
}

// Track is what the bot remembers about another mech or an NPC drone.
type Track struct {
	ID                                int
	NPC                               bool
	Pos, Vel                          [3]float64
	Aim                               [2]float64
	HP, MaxHP                         float64
	Cubes                             int
	Laser, Mortar, Light, Gun, Charging bool
	LastSeen                          float64
	Listed                            bool
	LOS                               bool
	LOST                              float64
	HurtMeT                           float64
	HurtMe                            float64
	IHurtT                            float64
	IHurt                             float64
	AimAtMeT                          float64
	SeenT0                            float64
	PhantomT                          float64
	WasListed                         bool
	ViewT                             float64
	EngT                              float64
	LaserFiredT                       float64

	hist                      [trkHist]trkSample
	hn, hi                    int
	leadN, missNone, missLead float64
}

const trkHist = 40

type trkSample struct {
	t, x, y, vx, vy float64
	facing          bool
}

func (t *Track) scale(sizePerCube float64) float64 { return 1 + sizePerCube*float64(t.Cubes) }

type Item struct {
	ID       int
	Pos      [3]float64
	HP       float64
	Kind     string
	LastSeen float64
	Ground   bool
	Cell     int
}

type slot struct {
	ok                               bool
	kind                             string
	cooldown, ammo, reload, charge   float64
	stats                            map[string]float64
}

type Bot struct {
	P   Params
	H   *Hello
	C   *Config
	W   *World
	Nav *Nav
	rng *rand.Rand

	dt, decide, sizePerCube float64

	o                                                  *Obs
	t                                                  float64
	pos, vel                                           [3]float64
	aim                                                [2]float64
	hp, maxHP, energy                                  float64
	scale, radius, height, eyeH, muzzleH               float64
	walk, boostV, turn, pitchR, armor                  float64
	slots                                              [2]slot

	tracks                 map[int]*Track
	crates, cubes, pickups map[int]*Item

	lastDamageT, lastWeaponDT, lastEnemyLOST, lastDealtT float64
	recentDmg, lastDmgBear                               float64
	lastDmgBy                                            int
	lastSoundT, lastSoundB                               float64

	path               []int32
	pathBad, pathSet   bool
	pathGoal           [2]float64
	pathT              float64
	pathIdx            int
	strafeSign         float64
	strafeT            float64
	stuckT             float64
	stuckPos           [3]float64
	stuckFor, unstickT float64
	unstickDir         [2]float64
	lastMove           [2]float64

	mode                        string
	targetID                    int
	retreating                  bool
	coverCell                   int
	coverT                      float64
	deepCell                    int
	deepT, deepTryT, standT     float64
	creditAbsorbT               float64
	lootID                      int
	holdCell                    int
	lastAimCmd                  [2]float64
	scanPhase                   float64
	laserHold                   bool
	takeT                       float64
	ffaSeenT                    float64
	ffaBeams                    int
	kills, killsSeen, deadSeen  int
	unexplained                 int
	ffa                         bool
	st                          stance
	hideT                       float64
	modeLabel                   string
	lastNpcDT                   float64
	seenT                       []float32
	seenNX, seenNY              int
	roamCell                    int
	roamT, retreatT, corneredT  float64
	zgKey                       [3]float64
	zgT                         float64
	zgComp                      int32
	zgGoal                      [2]float64
	zgWalk                      bool
	myComp                      int32
	surf                        []int32
	surfGoal                    [2]float64
	surfT                       float64
	surfIdx                     int
	surfBan                     map[int]float64
	surfWatchT                  float64
	surfWatchPos                [3]float64
	surfPushing                 bool
	banUntil                    map[int]float64
	roof                        roofPlan
	roofCoverC                  int
	roofCoverT                  float64
	unquietT                    float64
	roofCoverHoldT              float64
	holdClimb, holdRoofMove     bool
	edgeOnT                     float64
	slipCell                    int
	slipT, slipOnT              float64
	creditT                     float64
	creditID                    int
}

func New(h *Hello, w *World, nav *Nav, p Params) *Bot {
	b := &Bot{P: p, H: h, C: &h.Config, W: w, Nav: nav}
	b.rng = rand.New(rand.NewSource(h.Seed*7919 + int64(h.Slot) + 1 + int64(p.Salt)*104729))
	hz := stat(h.Config.Match, "tick_hz", 20)
	if hz <= 0 {
		hz = 20
	}
	b.dt = 1 / hz
	b.decide = stat(h.Config.Match, "decide_every", 2) * b.dt
	b.sizePerCube = h.Config.Cubes.SizePerCube

	b.tracks = map[int]*Track{}
	b.crates = map[int]*Item{}
	b.cubes = map[int]*Item{}
	b.pickups = map[int]*Item{}
	b.lastDamageT, b.lastWeaponDT, b.lastEnemyLOST, b.lastDealtT = -100, -100, -100, -100
	b.lastDmgBy = -1
	b.lastSoundT = -100
	b.strafeSign = 1
	b.mode = "init"
	b.targetID = -1
	b.coverCell = -1
	b.coverT = -100
	b.deepCell = -1
	b.deepT, b.deepTryT, b.standT = -100, -100, -100
	b.creditAbsorbT = -100
	b.lootID = -1
	b.holdCell = -1
	b.ffaSeenT = -100
	b.lastNpcDT = -100
	b.roamCell = -1
	b.corneredT = -100
	b.surfT = -100
	b.banUntil = map[int]float64{}
	b.roof = roofPlan{id: -1, want: -1, spot: -1}
	b.roofCoverC = -1
	b.roofCoverT = -100
	b.unquietT = -100
	b.roofCoverHoldT = -100
	b.edgeOnT = -100
	b.slipCell = -1
	b.slipT, b.slipOnT = -100, -100
	b.creditT = -100

	nav.Exposure()
	nav.Components()
	nav.Roofs()
	nav.Tops()
	return b
}

func (b *Bot) Act(o *Obs) Action {
	act := proto.NewAction(o.Tick)
	b.observe(o)
	b.think(&act)
	if math.IsNaN(act.Move[0]) || math.IsNaN(act.Move[1]) {
		act.Move = [2]float64{0, 0}
	}
	if math.IsNaN(act.Aim[0]) || math.IsNaN(act.Aim[1]) {
		act.HasAim = false
	}
	b.lastMove = act.Move
	if act.HasAim {
		b.lastAimCmd = act.Aim
	}
	return act
}

func (b *Bot) mech(key string, def float64) float64 { return stat(b.C.Mech, key, def) }

func (b *Bot) observe(o *Obs) {
	b.o = o
	b.t = o.T
	s := &o.Self
	b.pos, b.vel, b.aim = s.Pos, s.Vel, s.Aim
	b.hp, b.maxHP, b.energy = s.HP, s.MaxHP, s.Energy
	if b.maxHP <= 0 {
		b.maxHP = 1
	}
	st := s.Stats
	baseMuzzle := b.mech("muzzle_height", 7)
	b.scale = 1 + b.sizePerCube*float64(s.Cubes)
	b.muzzleH = stat(st, "muzzle_height", baseMuzzle*b.scale)
	b.eyeH = stat(st, "eye_height", b.mech("eye_height", 8)*b.scale)
	if b.muzzleH < baseMuzzle*b.scale-1e-6 {
		b.muzzleH = baseMuzzle * b.scale
	}
	if e := b.mech("eye_height", 8) * b.scale; b.eyeH < e-1e-6 {
		b.eyeH = e
	}
	b.radius = math.Max(stat(st, "radius", 0), b.mech("radius", 2.5)*b.scale)
	b.height = math.Max(stat(st, "height", 0), b.mech("height", 9)*b.scale)
	b.walk = stat(st, "walk_speed", b.mech("walk_speed", 11.7))
	b.boostV = stat(st, "boost_speed", b.mech("boost_speed", 19.5))
	b.turn = stat(st, "turn_rate", b.mech("turn_rate", 4))
	b.pitchR = stat(st, "pitch_rate", b.mech("pitch_rate", 3))
	b.armor = stat(st, "armor", 0)
	for i := 0; i < 2; i++ {
		b.slots[i] = slot{}
		if i < len(s.Weapons) && s.Weapons[i] != nil {
			w := s.Weapons[i]
			b.slots[i] = slot{ok: true, kind: w.Kind, cooldown: w.Cooldown, ammo: w.Ammo, reload: w.Reload, charge: w.Charge, stats: w.Stats}
			if b.slots[i].stats == nil {
				b.slots[i].stats = b.C.Weapons[w.Kind]
			}
		}
	}
	b.recentDmg *= math.Exp(-b.decide / 3.0)
	for _, tr := range b.tracks {
		tr.WasListed = tr.Listed
		tr.Listed = false
		tr.LOS = false
		tr.HurtMe *= math.Exp(-b.decide / 4.0)
		tr.IHurt *= math.Exp(-b.decide / 4.0)
	}
	if c := b.Nav.Nearest(b.pos[0], b.pos[1], 2.9, 9, 4); c >= 0 && b.onGroundLevel() {
		b.myComp = b.Nav.Components()[c]
	}

	eye := [3]float64{b.pos[0], b.pos[1], b.pos[2] + b.eyeH}
	fovHalf := b.C.Vision.FovDeg * math.Pi / 360
	if fovHalf <= 0 {
		fovHalf = math.Pi / 3
	}
	visRange := b.C.Vision.Range + stat(s.Stats, "vision_bonus", 0)
	nearRange := b.C.Vision.NearRange + stat(s.Stats, "near_range_bonus", 0)
	for i := range o.Mechs {
		m := &o.Mechs[i]
		tr := b.tracks[m.ID]
		if tr == nil {
			tr = &Track{ID: m.ID, NPC: m.Kind == "npc", HurtMeT: -100, IHurtT: -100, AimAtMeT: -100, LOST: -100, SeenT0: b.t, PhantomT: -100, ViewT: -100, EngT: -100}
			b.tracks[m.ID] = tr
		}
		if b.t-tr.LastSeen > 6 {
			tr.SeenT0 = b.t
		}
		tr.Pos, tr.Vel, tr.Aim = m.Pos, m.Vel, m.Aim
		if m.MaxHP > 0 {
			tr.HP, tr.MaxHP = m.HP, m.MaxHP
		} else if tr.MaxHP == 0 {
			tr.HP, tr.MaxHP = 1400, 1400
		}
		tr.Cubes = m.Cubes
		tr.Charging = m.Charging
		tr.LastSeen = b.t
		tr.Listed = true
		if !tr.NPC {
			tr.Gun, tr.Laser, tr.Mortar, tr.Light = false, false, false, false
			for _, w := range m.Weapons {
				switch w {
				case "gun":
					tr.Gun = true
				case "laser":
					tr.Laser = true
				case "mortar":
					tr.Mortar = true
				case "lightning":
					tr.Light = true
				}
			}
		}
		sc := 1.0
		if !tr.NPC {
			sc = tr.scale(b.sizePerCube)
		}
		ch := 4.5 * sc
		if tr.NPC {
			ch = stat(b.C.Npc, "height", 3.5) * 0.5
		}
		tr.LOS = b.W.Visible(eye[0], eye[1], eye[2], m.Pos[0], m.Pos[1], m.Pos[2]+ch) ||
			b.W.Visible(eye[0], eye[1], eye[2], m.Pos[0], m.Pos[1], m.Pos[2]+ch*1.9)
		if tr.LOS {
			tr.LOST = b.t
			if !tr.NPC {
				b.lastEnemyLOST = b.t
			}
			d3 := dist3(eye, [3]float64{m.Pos[0], m.Pos[1], m.Pos[2] + ch})
			if d3 < nearRange-1 || (d3 < visRange-2 && math.Abs(angDiff(math.Atan2(m.Pos[1]-b.pos[1], m.Pos[0]-b.pos[0]), b.aim[0])) < fovHalf-0.05) {
				tr.ViewT = b.t
			}
		}
		if !tr.NPC && tr.LOS {
			bear := math.Atan2(b.pos[1]-m.Pos[1], b.pos[0]-m.Pos[0])
			d := dist2(b.pos, m.Pos)
			tol := 0.12 + math.Atan2(b.radius*1.5, math.Max(d, 1))
			off := math.Abs(angDiff(m.Aim[0], bear))
			if off < tol {
				tr.AimAtMeT = b.t
			}
			if b.P.LeadPersist || b.P.LeadCum {
				b.leadRecord(tr, off < 0.35)
			}
		}
	}
	mem := b.C.Vision.MemoryS
	if mem <= 0 {
		mem = 5
	}
	for id, tr := range b.tracks {
		if b.t-tr.LastSeen > 45 && b.t-tr.HurtMeT > 45 {
			delete(b.tracks, id)
			continue
		}
		if tr.WasListed && !tr.Listed && b.t-tr.ViewT < mem-1.5 {
			delete(b.tracks, id)
			if b.targetID == id {
				b.targetID = -1
			}
		}
	}
	for i := range o.Events {
		e := &o.Events[i]
		switch e.Type {
		case "damaged":
			b.lastDamageT = b.t
			if e.Weapon == "npc" {
				b.lastNpcDT = b.t
				if e.Bearing != nil {
					b.lastDmgBear = *e.Bearing
				}
				if e.By != nil {
					if tr := b.tracks[*e.By]; tr != nil {
						tr.HurtMeT = b.t
					}
				}
			} else if e.Weapon != "zone" {
				b.lastWeaponDT = b.t
				b.recentDmg += e.Amount
				if e.Bearing != nil {
					b.lastDmgBear = *e.Bearing
				}
				if e.By != nil && *e.By != s.ID {
					b.lastDmgBy = *e.By
					tr := b.tracks[*e.By]
					if tr == nil {
						tr = &Track{ID: *e.By, NPC: *e.By >= 100, HurtMeT: -100, IHurtT: -100, AimAtMeT: -100, LOST: -100, SeenT0: b.t, LastSeen: -100, HP: 1400, MaxHP: 1400, PhantomT: -100, ViewT: -100, EngT: -100}
						b.tracks[*e.By] = tr
					}
					if !tr.Listed && b.t-tr.LastSeen > 2 && e.Bearing != nil {
						guess := 115.0
						switch e.Weapon {
						case "laser":
							guess = 150
						case "lightning":
							guess = 35
						}
						tr.Pos = [3]float64{b.pos[0] + math.Cos(*e.Bearing)*guess, b.pos[1] + math.Sin(*e.Bearing)*guess, b.pos[2]}
						tr.Vel = [3]float64{}
						tr.PhantomT = b.t
					}
					tr.HurtMeT = b.t
					tr.HurtMe += e.Amount
					switch e.Weapon {
					case "laser":
						tr.Laser = true
					case "mortar":
						tr.Mortar = true
					case "lightning":
						tr.Light = true
					}
				}
			}
		case "hit":
			b.lastDealtT = b.t
			if e.Target < 100 {
				b.creditT = b.t
				b.creditID = e.Target
			}
			if tr := b.tracks[e.Target]; tr != nil {
				tr.IHurtT = b.t
				tr.IHurt += e.Amount
			}
		case "kill":
			b.kills++
			delete(b.tracks, e.Target)
			if b.targetID == e.Target {
				b.targetID = -1
			}
		case "took":
			delete(b.pickups, e.ID.Num)
		case "take_failed":
			if e.Reason == "gone" || e.Reason == "have" {
				delete(b.pickups, e.ID.Num)
			}
		}
	}
	b.foldItems(o.Crates, b.crates, "crate")
	b.foldItems(o.Cubes, b.cubes, "cube")
	seen := map[int]bool{}
	for i := range o.Pickups {
		p := &o.Pickups[i]
		seen[p.ID] = true
		it := b.pickups[p.ID]
		if it == nil {
			it = &Item{ID: p.ID}
			b.pickups[p.ID] = it
		}
		it.Pos, it.Kind, it.LastSeen = p.Pos, p.Kind, b.t
		b.groundCheck(it)
	}
	b.expireUnseen(b.pickups, seen, eye)
	for i := range o.Sounds {
		sd := &o.Sounds[i]
		switch sd.Kind {
		case "gun", "laser", "lightning", "mortar", "laser_charge", "boost", "step", "jet", "reload":
			if sd.Dist != "far" {
				b.lastSoundT = b.t - sd.Age
				b.lastSoundB = sd.Bearing
			}
		}
	}
	sawFFABeam := false
	for i := range o.Beams {
		bm := &o.Beams[i]
		if bm.By == s.ID {
			continue
		}
		if bm.Kind == "laser" {
			if tr := b.tracks[bm.By]; tr != nil {
				tr.LaserFiredT = b.t - bm.Age
			}
		}
		if len(bm.Path) >= 2 {
			p0 := bm.Path[0]
			end := bm.Path[len(bm.Path)-1]
			segD, _ := segPointDist2D(b.pos[0], b.pos[1], p0[0], p0[1], end[0], end[1])
			if dist2(end, b.pos) > 25 && segD > 22 {
				b.ffaSeenT = b.t
				sawFFABeam = true
			}
		}
	}
	if sawFFABeam {
		b.ffaBeams++
	}
}

func (b *Bot) foldItems(list []proto.ItemObs, m map[int]*Item, kind string) {
	eye := [3]float64{b.pos[0], b.pos[1], b.pos[2] + b.eyeH}
	seen := map[int]bool{}
	for i := range list {
		p := &list[i]
		seen[p.ID] = true
		it := m[p.ID]
		if it == nil {
			it = &Item{ID: p.ID, Kind: kind}
			m[p.ID] = it
		}
		it.Pos, it.HP, it.LastSeen = p.Pos, p.HP, b.t
		b.groundCheck(it)
	}
	b.expireUnseen(m, seen, eye)
}

func (b *Bot) expireUnseen(m map[int]*Item, seen map[int]bool, eye [3]float64) {
	near := b.C.Vision.NearRange * 0.85
	for id, it := range m {
		if seen[id] {
			continue
		}
		if b.t-it.LastSeen > 240 {
			delete(m, id)
			continue
		}
		d := dist3(it.Pos, eye)
		if d < near && b.W.Visible(eye[0], eye[1], eye[2], it.Pos[0], it.Pos[1], it.Pos[2]+0.8) {
			delete(m, id)
		}
	}
}

func (b *Bot) groundCheck(it *Item) {
	k := b.Nav.Index(it.Pos[0], it.Pos[1])
	it.Cell = k
	it.Ground = false
	if !b.Nav.Solid[k] && math.Abs(float64(b.Nav.Z[k])-it.Pos[2]) < 3.0 {
		it.Ground = true
		return
	}
	if c := b.Nav.Nearest(it.Pos[0], it.Pos[1], b.radius, b.height, 2); c >= 0 && math.Abs(float64(b.Nav.Z[c])-it.Pos[2]) < 3.0 {
		it.Cell = c
		it.Ground = true
	}
}

func (b *Bot) has(kind string) int {
	for i := 0; i < 2; i++ {
		if b.slots[i].ok && b.slots[i].kind == kind {
			return i
		}
	}
	return -1
}

func (b *Bot) cubeDamageMul(cubes int) float64 {
	capc := b.C.Cubes.StatCap
	c := float64(cubes)
	if c > capc {
		c = capc
	}
	return 1 + b.C.Cubes.DamagePerCube*c
}

// ---- numeric helpers (§9.0)

func clamp(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func hyp(x, y float64) float64 { return math.Sqrt(x*x + y*y) }

func dist2(a, b [3]float64) float64 { return hyp(a[0]-b[0], a[1]-b[1]) }

func dist3(a, b [3]float64) float64 {
	dx, dy, dz := a[0]-b[0], a[1]-b[1], a[2]-b[2]
	return math.Sqrt(dx*dx + dy*dy + dz*dz)
}

func angDiff(a, b float64) float64 {
	d := math.Mod(a-b, 2*math.Pi)
	if d > math.Pi {
		d -= 2 * math.Pi
	} else if d <= -math.Pi {
		d += 2 * math.Pi
	}
	return d
}

func norm2(x, y float64) (float64, float64) {
	l := hyp(x, y)
	if l < 1e-9 {
		return 0, 0
	}
	return x / l, y / l
}

func approach2(cx, cy, tx, ty, maxDelta float64) (float64, float64) {
	dx, dy := tx-cx, ty-cy
	d := hyp(dx, dy)
	if d <= maxDelta || d < 1e-12 {
		return tx, ty
	}
	return cx + dx/d*maxDelta, cy + dy/d*maxDelta
}

func segPointDist2D(px, py, ax, ay, bx, by float64) (float64, float64) {
	ex, ey := bx-ax, by-ay
	l2 := ex*ex + ey*ey
	t := 0.0
	if l2 > 1e-12 {
		t = clamp(((px-ax)*ex+(py-ay)*ey)/l2, 0, 1)
	}
	cx, cy := ax+ex*t, ay+ey*t
	return hyp(px-cx, py-cy), t
}
