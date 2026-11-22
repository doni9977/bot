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
