package main

import "testing"

func TestUpstreamChannelsIsolatedByAuthID(t *testing.T) {
	for _, provider := range []string{"claude", "snow-gpt-team", "snow-grok-team"} {
		t.Run(provider, func(t *testing.T) {
			l := groupedLimiter()
			l.before(beforeReq("r", scopeA))
			r := groupReq("r", scopeA, "B1", "unassigned", "A1")
			for i := range r.Candidates {
				r.Candidates[i].Provider = provider
			}
			if result(l.pick(r))["AuthID"] != "A1" {
				t.Fatal("wrong tenant selected")
			}
			if l.pick(groupReq("r", scopeA, "B1", "unassigned"))["ok"] != false {
				t.Fatal("fallback crossed tenant")
			}
			l.complete("r")
			if len(l.owners) != 0 || len(l.leases) != 0 {
				t.Fatal("upstream lease leak")
			}
		})
	}
}

func TestUpstreamCapabilityAdvertised(t *testing.T) {
	if newLimiter().snapshot()["upstream_channels_supported"] != true {
		t.Fatal("missing capability")
	}
}
