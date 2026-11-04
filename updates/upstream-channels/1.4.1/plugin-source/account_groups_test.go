package main

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"testing"
)

var scopeA = strings.Repeat("a", 64)
var scopeB = strings.Repeat("b", 64)

func groupedLimiter() *limiter {
	l := newLimiter()
	l.groups = parseGroupPolicy(true, map[string]accountGroupConfig{
		"Alice": {AuthIDs: []string{"A1", "A2"}, KeyScopes: []string{scopeA}},
		"Bob":   {AuthIDs: []string{"B1"}, KeyScopes: []string{scopeB}},
	})
	return l
}
func groupReq(id, key string, ids ...string) pickRequest {
	r := pickReq(id, key)
	r.Candidates = nil
	r.Options.Headers.Set("X-Claude-Code-Session-Id", "shared-session")
	for _, a := range ids {
		r.Candidates = append(r.Candidates, candidate{ID: a, Provider: "claude"})
	}
	return r
}
func TestGroupsExclusiveSelectionAndRetry(t *testing.T) {
	l := groupedLimiter()
	l.before(beforeReq("r", scopeA))
	for _, ids := range [][]string{{"B1", "A1"}, {"B1", "A2"}} {
		a := result(l.pick(groupReq("r", scopeA, ids...)))["AuthID"]
		if a != ids[1] {
			t.Fatalf("wrong account %v", a)
		}
	}
	if l.pick(groupReq("r", scopeA, "B1"))["ok"] != false {
		t.Fatal("cross-group retry allowed")
	}
	l.complete("r")
	if len(l.owners) != 0 {
		t.Fatal("leak")
	}
}
func TestGroupsUnknownKeyRejectedBeforeLease(t *testing.T) {
	l := groupedLimiter()
	if result(l.before(beforeReq("r", "unknown")))["StatusCode"] != 403 || len(l.leases) != 0 {
		t.Fatal("unknown key admitted")
	}
}
func TestGroupsPinnedSelectionDenied(t *testing.T) {
	l := groupedLimiter()
	l.before(beforeReq("r", scopeA))
	r := beforeReq("r", scopeA)
	r.Metadata["selected_auth_id"] = "B1"
	if result(l.after(r))["StatusCode"] != 403 || len(l.owners) != 0 {
		t.Fatal("pinned bypass")
	}
}
func TestGroupsSessionScopeAndSpoofing(t *testing.T) {
	l := groupedLimiter()
	for i, k := range []string{scopeA, scopeB} {
		id := fmt.Sprint(i)
		l.before(beforeReq(id, k))
		r := groupReq(id, k, "A1", "A2", "B1")
		r.Options.Headers.Set("caller_scope", scopeA)
		a := result(l.pick(r))["AuthID"].(string)
		if (i == 0 && a == "B1") || (i == 1 && a != "B1") {
			t.Fatal("scope escaped")
		}
		l.complete(id)
	}
	if len(l.sessions) != 2 {
		t.Fatal("sessions shared")
	}
}
func TestGroupsAssignedNonClaudeCandidate(t *testing.T) {
	l := groupedLimiter()
	l.before(beforeReq("r", scopeA))
	r := groupReq("r", scopeA, "A1")
	r.Candidates[0].Provider = "openai"
	if result(l.pick(r))["AuthID"] != "A1" {
		t.Fatal("assigned upstream was not selected")
	}
}
func TestGroupsInvalidPoliciesFailClosed(t *testing.T) {
	cases := []map[string]accountGroupConfig{
		{}, {"x": {AuthIDs: []string{"A"}, KeyScopes: []string{"bad"}}},
		{"x": {AuthIDs: []string{"A"}, KeyScopes: []string{scopeA}}, "y": {AuthIDs: []string{"A"}, KeyScopes: []string{scopeB}}},
		{"x": {AuthIDs: []string{"A"}, KeyScopes: []string{scopeA}}, "y": {AuthIDs: []string{"B"}, KeyScopes: []string{scopeA}}},
		{"x": {AuthIDs: []string{}, KeyScopes: []string{scopeA}}},
	}
	for i, c := range cases {
		t.Run(fmt.Sprint(i), func(t *testing.T) {
			l := newLimiter()
			l.groups = parseGroupPolicy(true, c)
			if result(l.before(beforeReq("r", scopeA)))["StatusCode"] != 503 {
				t.Fatal("invalid policy admitted")
			}
		})
	}
}
func TestGroupsHotReconfigureRevokesPendingRequest(t *testing.T) {
	l := groupedLimiter()
	l.before(beforeReq("r", scopeA))
	l.groups = parseGroupPolicy(true, map[string]accountGroupConfig{"new": {AuthIDs: []string{"B1"}, KeyScopes: []string{scopeA}}})
	r := beforeReq("r", scopeA)
	r.Metadata["selected_auth_id"] = "A1"
	if result(l.after(r))["StatusCode"] != 403 {
		t.Fatal("revocation ignored")
	}
}
func TestGroupsSaturationNeverBorrows(t *testing.T) {
	l := groupedLimiter()
	for i := 0; i < 5; i++ {
		id := fmt.Sprint(i)
		l.before(beforeReq(id, scopeB))
		out := l.pick(groupReq(id, scopeB, "B1", "A1", "A2"))
		if i < 2 && result(out)["AuthID"] != "B1" {
			t.Fatal("early rejection")
		}
		if i >= 2 && out["ok"] != false {
			t.Fatal("borrowed or exceeded account limit")
		}
	}
	if result(l.before(beforeReq("six", scopeB)))["StatusCode"] != 429 {
		t.Fatal("key limit broken")
	}
}
func TestGroupsReconfigureAndParallelRequests(t *testing.T) {
	l := groupedLimiter()
	var wg sync.WaitGroup
	raw, _ := json.Marshal(obj{"config_yaml": []byte("max_per_key: 5\nenforce_account_groups: true\naccount_groups:\n  owner:\n    auth_ids: [A1]\n    key_scopes: [" + scopeA + "]\n")})
	for n := 0; n < 8; n++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			for i := 0; i < 20; i++ {
				id := fmt.Sprintf("%d-%d", n, i)
				l.configure(raw)
				l.before(beforeReq(id, scopeA))
				l.pick(groupReq(id, scopeA, "A1", "B1"))
				r := beforeReq(id, scopeA)
				r.Metadata["selected_auth_id"] = "B1"
				if result(l.after(r))["Terminate"] != true {
					t.Error("parallel escape")
				}
				l.complete(id)
			}
		}(n)
	}
	wg.Wait()
	if len(l.leases) != 0 || len(l.owners) != 0 {
		t.Fatal("slots leaked")
	}
}

func TestGroupsMalformedConfigDoesNotDisableIsolation(t *testing.T) {
	l := groupedLimiter()
	for _, yaml := range []string{"account_groups: [", "enforce_account_groups: false\naccount_groups:\n  x:\n    auth_ids: [A1]\n    key_scopes: [" + scopeA + "]\n"} {
		raw, _ := json.Marshal(obj{"config_yaml": []byte(yaml)})
		l.configure(raw)
		if result(l.before(beforeReq("r", scopeA)))["StatusCode"] != 503 {
			t.Fatal("bad config opened access")
		}
	}
}

func TestGroupsPolicyChangeDuringHostCallback(t *testing.T) {
	l := groupedLimiter()
	l.before(beforeReq("first", scopeA))
	l.pick(groupReq("first", scopeA, "A1"))
	l.complete("first")
	l.lookupAccount = func(string) accountState {
		l.mu.Lock()
		l.groups = parseGroupPolicy(true, map[string]accountGroupConfig{"owner": {AuthIDs: []string{"B1"}, KeyScopes: []string{scopeA}}})
		l.mu.Unlock()
		return accountPresent
	}
	l.before(beforeReq("next", scopeA))
	if l.pick(groupReq("next", scopeA, "A2", "B1"))["ok"] != false {
		t.Fatal("used stale pre-callback authorization")
	}
	l.complete("next")
}
