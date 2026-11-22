package mech

import "testing"

func TestDefaultParamsPreferWeakTargets(t *testing.T) {
	p := DefaultParams()
	if p.LowBonus <= 0 {
		t.Fatalf("LowBonus is %v, want positive weak-target preference", p.LowBonus)
	}
	if p.RetreatHP >= p.RecoverHP {
		t.Fatalf("invalid HP thresholds: RetreatHP=%v RecoverHP=%v", p.RetreatHP, p.RecoverHP)
	}
}

func TestPickUpgradeAvoidsMortar(t *testing.T) {
	offer := &Offer{Choices: []OfferChoice{
		{ID: "mortar_velocity"},
		{ID: "plating"},
	}}
	if got := pickUpgrade(offer, false, false); got != 1 {
		t.Fatalf("pickUpgrade picked index %d, want plating", got)
	}
}

func TestThreatRateDecays(t *testing.T) {
	b := NewBrain(&Hello{}, FlatWorld())
	b.now = 30
	b.thrDmg[7] = [2]float64{270, 30}
	if got := b.threatRate(7); got < 44 || got > 46 {
		t.Fatalf("threat rate %.2f, want ~45", got)
	}
	b.now = 42
	if got := b.threatRate(7); got < 5 || got > 7 {
		t.Fatalf("decayed threat rate %.2f, want ~6", got)
	}
}

func TestSquadParamsEnableThreatFocus(t *testing.T) {
	p := squadParams(DefaultParams())
	if p.ThreatFocus <= 0 {
		t.Fatalf("missing squad threat focus: %+v", p)
	}
}
