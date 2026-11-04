package main

import (
	"encoding/json"
	"fmt"
	"testing"
)

func configureLimits(t *testing.T, l *limiter, y string) {
	t.Helper()
	b, _ := json.Marshal(map[string][]byte{"config_yaml": []byte(y)})
	l.configure(b)
}
func pickOnly(l *limiter, id, key, auth, sid string) obj {
	r := pickReq(id, key)
	r.Candidates = []candidate{{ID: auth}}
	if sid != "" {
		r.Options.Metadata["canonical_session_id"] = sid
	}
	return l.pick(r)
}
func TestSingleAccountOverrideFiveAndOtherTwo(t *testing.T) {
	l := newLimiter()
	configureLimits(t, l, "max_per_key: 5\naccount_limits:\n  A: 5\n")
	for i := 0; i < 5; i++ {
		id := fmt.Sprint(i)
		l.before(beforeReq(id, "keyA"))
		if result(pickOnly(l, id, "keyA", "A", "same"))["AuthID"] != "A" {
			t.Fatal("rejected before five", i)
		}
	}
	if result(l.before(beforeReq("six", "keyA")))["StatusCode"] != 429 {
		t.Fatal("Key exceeded five")
	}
	l.before(beforeReq("otherKey", "keyB"))
	if pickOnly(l, "otherKey", "keyB", "A", "")["ok"] != false {
		t.Fatal("Account exceeded five via other Key")
	}
	for i := 0; i < 3; i++ {
		id := fmt.Sprint("b", i)
		l.before(beforeReq(id, "keyB"))
		got := pickOnly(l, id, "keyB", "B", "")
		if i < 2 && result(got)["AuthID"] != "B" {
			t.Fatal("default rejected")
		}
		if i == 2 && got["ok"] != false {
			t.Fatal("other exceeded two")
		}
	}
	l.complete("0")
	l.before(beforeReq("new", "keyA"))
	if result(pickOnly(l, "new", "keyA", "A", "same"))["AuthID"] != "A" {
		t.Fatal("slot not released")
	}
}
func TestPinnedAfterHonorsOverride(t *testing.T) {
	l := newLimiter()
	configureLimits(t, l, "account_limits:\n  A: 5\n")
	for i := 0; i < 6; i++ {
		id := fmt.Sprint(i)
		key := "keyA"
		if i == 5 {
			key = "keyB"
		}
		l.before(beforeReq(id, key))
		r := beforeReq(id, key)
		r.Metadata["selected_auth_id"] = "A"
		got := result(l.after(r))
		if i < 5 && got["Terminate"] == true {
			t.Fatal("early rejection")
		}
		if i == 5 && got["StatusCode"] != 429 {
			t.Fatal("pinned exceeded five")
		}
	}
}
func TestInvalidAccountOverridesFailClosed(t *testing.T) {
	for _, y := range []string{"account_limits:\n  A: 6\n", "account_limits:\n  A: 0\n", "enforce_account_groups: true\naccount_limits:\n  unknown: 5\n"} {
		l := newLimiter()
		configureLimits(t, l, y)
		if result(l.before(beforeReq("x", "key")))["Terminate"] != true {
			t.Fatal("invalid admitted")
		}
	}
}
func TestOverrideSnapshotCopyAndRemoval(t *testing.T) {
	l := newLimiter()
	configureLimits(t, l, "account_limits:\n  A: 5\n")
	s := l.snapshot()
	s["account_limits"].(map[string]int)["A"] = 1
	if l.accountLimit("A") != 5 {
		t.Fatal("snapshot mutable")
	}
	configureLimits(t, l, "max_per_key: 5\n")
	if l.accountLimit("A") != 2 {
		t.Fatal("not removed")
	}
}
