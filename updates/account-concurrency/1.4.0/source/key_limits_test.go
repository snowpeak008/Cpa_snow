package main

import (
	"fmt"
	"strings"
	"testing"
)

func TestKeyOverrideTwentyWithFivePerAccount(t *testing.T) {
	l := newLimiter()
	owner := strings.Repeat("a", 64)
	other := strings.Repeat("b", 64)
	configureLimits(t, l, "max_per_key: 5\nkey_limits:\n  "+owner+": 20\naccount_limits:\n  A: 5\n  B: 5\n  C: 5\n  D: 5\n")
	for i := 0; i < 20; i++ {
		id := fmt.Sprint(i)
		if result(l.before(beforeReq(id, owner)))["Terminate"] == true {
			t.Fatal("owner rejected before twenty", i)
		}
		r := pickReq(id, owner)
		r.Candidates = []candidate{{ID: "A"}, {ID: "B"}, {ID: "C"}, {ID: "D"}}
		if result(l.pick(r))["AuthID"] == nil {
			t.Fatal("account selection rejected", i)
		}
	}
	if result(l.before(beforeReq("twenty-one", owner)))["StatusCode"] != 429 {
		t.Fatal("owner exceeded twenty")
	}
	for _, a := range []string{"A", "B", "C", "D"} {
		if len(l.owners[a]) != 5 {
			t.Fatal("account exceeded/missed five", a, len(l.owners[a]))
		}
	}
	for i := 0; i < 5; i++ {
		if result(l.before(beforeReq(fmt.Sprint("other", i), other)))["Terminate"] == true {
			t.Fatal("other rejected early")
		}
	}
	if result(l.before(beforeReq("other-six", other)))["StatusCode"] != 429 {
		t.Fatal("other key exceeded five")
	}
	// Another Key cannot exceed an account's shared limit.
	if pickOnly(l, "other0", other, "A", "")["ok"] != false {
		t.Fatal("shared account exceeded five")
	}
	l.complete("0")
	if result(l.before(beforeReq("replacement", owner)))["Terminate"] == true {
		t.Fatal("key slot not released")
	}
	if result(pickOnly(l, "replacement", owner, "A", ""))["AuthID"] != "A" {
		t.Fatal("account slot not released")
	}
}
func TestKeyOverrideValidation(t *testing.T) {
	for _, v := range []string{strings.Repeat("a", 64) + ": 101", strings.Repeat("a", 64) + ": 0", "short: 20", strings.Repeat("A", 64) + ": 20"} {
		l := newLimiter()
		configureLimits(t, l, "key_limits:\n  "+v+"\n")
		if result(l.before(beforeReq("x", "key")))["Terminate"] != true {
			t.Fatal("invalid config admitted", v)
		}
	}
	l := newLimiter()
	configureLimits(t, l, "enforce_account_groups: true\nkey_limits:\n  "+strings.Repeat("a", 64)+": 20\n")
	if !l.groups.invalid {
		t.Fatal("unknown grouped scope accepted")
	}
}
func TestKeyOverrideSnapshotAndRemoval(t *testing.T) {
	l := newLimiter()
	scope := strings.Repeat("a", 64)
	configureLimits(t, l, "key_limits:\n  "+scope+": 20\n")
	l.snapshot()["key_limits"].(map[string]int)[scope] = 1
	if l.keyLimit(scope) != 20 {
		t.Fatal("snapshot mutated live policy")
	}
	configureLimits(t, l, "max_per_key: 5\n")
	if l.keyLimit(scope) != 5 {
		t.Fatal("override removal did not restore default")
	}
}
