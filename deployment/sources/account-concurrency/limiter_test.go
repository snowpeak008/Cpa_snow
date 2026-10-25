package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"testing"
	"time"
)

func beforeReq(id, key string) request {
	return request{RequestID: id, Metadata: obj{"caller_scope": key}}
}
func pickReq(id, key string) pickRequest {
	r := pickRequest{}
	r.Options.Headers = http.Header{leaseHeader: {id}}
	r.Options.Metadata = obj{"caller_scope": key}
	for i := 0; i < 5; i++ {
		r.Candidates = append(r.Candidates, candidate{ID: fmt.Sprint(i)})
	}
	return r
}
func result(o obj) obj { r, _ := o["result"].(map[string]any); return r }
func TestFiveDifferentAccountsAndSixthRejected(t *testing.T) {
	l := newLimiter()
	seen := map[string]bool{}
	for i := 0; i < 5; i++ {
		id := fmt.Sprint(i)
		if result(l.before(beforeReq(id, "key")))["Terminate"] == true {
			t.Fatal("admission rejected")
		}
		r := result(l.pick(pickReq(id, "key")))
		a, _ := r["AuthID"].(string)
		if a == "" || seen[a] {
			t.Fatal("account overlap", a)
		}
		seen[a] = true
	}
	if result(l.before(beforeReq("sixth", "key")))["StatusCode"] != 429 {
		t.Fatal("sixth allowed")
	}
	l.complete("0")
	l.complete("0")
	if result(l.before(beforeReq("new", "key")))["Terminate"] == true {
		t.Fatal("slot not released")
	}
	if result(l.pick(pickReq("new", "key")))["AuthID"] == nil {
		t.Fatal("account not released")
	}
}
func TestCrossKeyAccountLimitAndPinnedGate(t *testing.T) {
	l := newLimiter()
	l.before(beforeReq("a", "key-a"))
	a := result(l.pick(pickReq("a", "key-a")))["AuthID"].(string)
	l.before(beforeReq("b", "key-b"))
	r := beforeReq("b", "key-b")
	r.Metadata["selected_auth_id"] = a
	if result(l.after(r))["Terminate"] == true {
		t.Fatal("second denied")
	}
	l.after(r)
	l.before(beforeReq("c", "key-c"))
	r = beforeReq("c", "key-c")
	r.Metadata["selected_auth_id"] = a
	if result(l.after(r))["StatusCode"] != 429 {
		t.Fatal("pinned bypass")
	}
	l.complete("b")
	if !l.owners[a]["a"] || len(l.owners[a]) != 1 {
		t.Fatal("rejected request released another owner")
	}
}
func TestRetryRetainsReservationsUntilComplete(t *testing.T) {
	l := newLimiter()
	l.before(beforeReq("a", "k"))
	p := pickReq("a", "k")
	first := result(l.pick(p))["AuthID"].(string)
	p.Candidates = p.Candidates[1:]
	second := result(l.pick(p))["AuthID"].(string)
	if first == second || len(l.owners) != 2 {
		t.Fatal("retry reservation missing")
	}
	l.complete("a")
	if len(l.owners) != 0 || len(l.keys) != 0 {
		t.Fatal("retry leaked")
	}
}
func TestConcurrentAdmissions(t *testing.T) {
	l := newLimiter()
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			id := fmt.Sprint(i)
			l.before(beforeReq(id, "k"))
			l.pick(pickReq(id, "k"))
		}(i)
	}
	wg.Wait()
	if len(l.leases) != 5 || len(l.owners) != 5 {
		t.Fatal("oversubscription", len(l.leases), len(l.owners))
	}
	for id := range l.leases {
		l.complete(id)
	}
}
func TestHotConfigPreservesLeasesAndLowerLimit(t *testing.T) {
	l := newLimiter()
	l.before(beforeReq("a", "k"))
	l.pick(pickReq("a", "k"))
	raw, _ := json.Marshal(obj{"config_yaml": []byte("max_per_key: 1\n")})
	l.configure(raw)
	if result(l.before(beforeReq("b", "k")))["StatusCode"] != 429 || len(l.owners) != 1 {
		t.Fatal("hot reload lost state")
	}
	l.complete("a")
	if result(l.before(beforeReq("c", "k")))["Terminate"] == true {
		t.Fatal("not recovered")
	}
}
func TestMissingContextFailsClosed(t *testing.T) {
	l := newLimiter()
	if result(l.before(request{}))["StatusCode"] != 503 {
		t.Fatal("missing context allowed")
	}
	if l.pick(pickReq("unknown", "k"))["ok"] != false {
		t.Fatal("unknown lease accepted")
	}
}

func TestThreeAccountsFiveRequests(t *testing.T) {
	l := newLimiter()
	for i := 0; i < 5; i++ {
		id := fmt.Sprint(i)
		l.before(beforeReq(id, "k"))
		p := pickReq(id, "k")
		p.Candidates = p.Candidates[:3]
		if result(l.pick(p))["AuthID"] == nil {
			t.Fatal("denied")
		}
	}
	counts := map[int]int{}
	for _, owners := range l.owners {
		counts[len(owners)]++
	}
	if counts[2] != 2 || counts[1] != 1 {
		t.Fatal(counts)
	}
	if result(l.before(beforeReq("sixth", "k")))["StatusCode"] != 429 {
		t.Fatal("key cap")
	}
}
func TestConcurrentSingleAccountTwoSlots(t *testing.T) {
	l := newLimiter()
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			id := fmt.Sprint(i)
			l.before(beforeReq(id, id))
			p := pickReq(id, id)
			p.Candidates = p.Candidates[:1]
			l.pick(p)
		}(i)
	}
	wg.Wait()
	if len(l.owners["0"]) != 2 {
		t.Fatal("cap")
	}
	for id := range l.leases {
		l.complete(id)
	}
	if len(l.owners) != 0 {
		t.Fatal("leaked")
	}
}

func sessionPickReq(id, key, session string) pickRequest {
	r := pickReq(id, key)
	if session != "" {
		r.Options.Metadata["canonical_session_id"] = session
	}
	return r
}

func mustSessionPick(t *testing.T, l *limiter, id, key, session string) string {
	t.Helper()
	if result(l.before(beforeReq(id, key)))["Terminate"] == true {
		t.Fatal("unexpected admission rejection", id)
	}
	auth, _ := result(l.pick(sessionPickReq(id, key, session)))["AuthID"].(string)
	if auth == "" {
		t.Fatal("unexpected selection rejection", id)
	}
	return auth
}

// 1: Separate completed model executions in one conversation retain the account.
func TestSession01SequentialSameAccount(t *testing.T) {
	l := newLimiter()
	a := mustSessionPick(t, l, "first", "k", "claude:s1")
	l.complete("first")
	l.sessions["claude:s1"].Expire = time.Now().Add(time.Minute)
	oldExpiry := l.sessions["claude:s1"].Expire
	b := mustSessionPick(t, l, "second", "k", "claude:s1")
	if a != b || !l.sessions["claude:s1"].Expire.After(oldExpiry) {
		t.Fatal("binding not retained/refreshed", a, b)
	}
	if len(l.owners[a]) != 1 || !l.leases["second"].Accounts[a] {
		t.Fatal("sticky selection did not reserve a slot")
	}
	l.complete("second")
	if len(l.owners) != 0 || len(l.keys) != 0 {
		t.Fatal("sticky execution leaked slots")
	}
}

func fullSessionAccount(t *testing.T) (*limiter, string) {
	t.Helper()
	l := newLimiter()
	a := mustSessionPick(t, l, "first", "k", "claude:s1")
	if b := mustSessionPick(t, l, "second", "k", "claude:s1"); b != a || len(l.owners[a]) != 2 {
		t.Fatal("failed to fill two sticky slots", a, b)
	}
	return l, a
}

// 2: Busy-account failover must not overwrite or refresh its original binding.
func TestSession02FullAccountFallsBackWithoutRebinding(t *testing.T) {
	l, a := fullSessionAccount(t)
	expiry := l.sessions["claude:s1"].Expire
	b := mustSessionPick(t, l, "third", "k", "claude:s1")
	if b == a || l.sessions["claude:s1"].AuthID != a || !l.sessions["claude:s1"].Expire.Equal(expiry) {
		t.Fatal("full-account fallback altered binding", a, b)
	}
	if len(l.owners[a]) != 2 || len(l.owners[b]) != 1 {
		t.Fatal("capacity changed")
	}
}

// 3: Once a slot on A is released, the conversation returns to A.
func TestSession03ReturnsAfterCapacityReleased(t *testing.T) {
	l, a := fullSessionAccount(t)
	b := mustSessionPick(t, l, "fallback", "k", "claude:s1")
	if b == a {
		t.Fatal("did not fail over")
	}
	l.complete("first")
	c := mustSessionPick(t, l, "return", "k", "claude:s1")
	if c != a || len(l.owners[a]) != 2 || l.sessions["claude:s1"].AuthID != a {
		t.Fatal("did not return to original binding", a, c)
	}
}

// 4: A temporary cooldown must not erase the preferred account.
func TestSession04UnavailableAccountPreservesAndReturns(t *testing.T) {
	l := newLimiter()
	l.lookupAccount = func(string) accountState { return accountPresent }
	a := mustSessionPick(t, l, "first", "k", "claude:s1")
	l.complete("first")
	expiry := l.sessions["claude:s1"].Expire
	l.before(beforeReq("next", "k"))
	p := sessionPickReq("next", "k", "claude:s1")
	p.Candidates = []candidate{{ID: "B"}}
	b, _ := result(l.pick(p))["AuthID"].(string)
	if b != "B" || b == a || l.sessions["claude:s1"].AuthID != a || !l.sessions["claude:s1"].Expire.Equal(expiry) {
		t.Fatal("temporary unavailability changed binding", a, b)
	}
	l.complete("next")
	if got := mustSessionPick(t, l, "recovered", "k", "claude:s1"); got != a {
		t.Fatal("did not return after cooldown", got, a)
	}
}

// 5: Expired entries are removed before selection, with no sleeps in the test.
func TestSession05TTLExpires(t *testing.T) {
	l := newLimiter()
	a := mustSessionPick(t, l, "first", "k", "claude:s1")
	l.complete("first")
	l.sessions["claude:s1"].Expire = time.Now().Add(-time.Second)
	started := time.Now()
	b := mustSessionPick(t, l, "next", "k", "claude:s1")
	if b == a || l.sessions["claude:s1"].AuthID != b || l.sessions["claude:s1"].Expire.Before(started.Add(sessionTTL)) {
		t.Fatal("expired session stayed bound", a, b)
	}
}

// 6: Independent sessions retain independent accounts.
func TestSession06DifferentSessionsStayIndependent(t *testing.T) {
	l := newLimiter()
	a := mustSessionPick(t, l, "s1-first", "k", "claude:s1")
	l.complete("s1-first")
	b := mustSessionPick(t, l, "s2-first", "k", "claude:s2")
	l.complete("s2-first")
	if a == b || mustSessionPick(t, l, "s1-next", "k", "claude:s1") != a || mustSessionPick(t, l, "s2-next", "k", "claude:s2") != b {
		t.Fatal("sessions interfered", a, b)
	}
}

// 7: No session => the original account-ID rotation, and no binding entries.
func TestSession07NoIdentityPreservesRotation(t *testing.T) {
	l := newLimiter()
	for i := 0; i < 10; i++ {
		id := fmt.Sprint(i)
		a := mustSessionPick(t, l, id, "k", "")
		if a != fmt.Sprint(i%5) {
			t.Fatal("legacy rotation changed", i, a)
		}
		l.complete(id)
	}
	if len(l.sessions) != 0 {
		t.Fatal("request IDs incorrectly used as sessions")
	}
}

// 8: Stickiness must preserve both limits, including cross-key saturation.
func TestSession08FiveTwoLimits(t *testing.T) {
	l := newLimiter()
	for i := 0; i < 5; i++ {
		mustSessionPick(t, l, fmt.Sprint(i), "k", "claude:s1")
	}
	if result(l.before(beforeReq("sixth", "k")))["StatusCode"] != 429 {
		t.Fatal("key limit bypassed")
	}
	if len(l.owners["0"]) != 2 || len(l.owners) < 2 {
		t.Fatal("third sticky request did not fail over")
	}
	for account, owners := range l.owners {
		if len(owners) > 2 {
			t.Fatal("account limit bypassed", account, len(owners))
		}
	}
	// With A as the only candidate, two different keys fill it; third is rejected.
	l = newLimiter()
	for i := 0; i < 3; i++ {
		id := fmt.Sprint(i)
		l.before(beforeReq(id, id))
		p := sessionPickReq(id, id, "claude:s1")
		p.Candidates = []candidate{{ID: "A"}}
		r := l.pick(p)
		if i < 2 && result(r)["AuthID"] != "A" {
			t.Fatal("available sticky slot rejected")
		}
		if i == 2 && (r["ok"] != false || r["error"].(map[string]any)["http_status"] != 429) {
			t.Fatal("third request must be rejected", r)
		}
	}
	if len(l.owners["A"]) != 2 {
		t.Fatal("cross-key account cap broken")
	}
}

func TestSessionIdentitySources(t *testing.T) {
	cases := []struct {
		name, header, value, canonical, derived, want string
	}{
		{"canonical", "", "", "claude:body-session", "", "claude:body-session"},
		{"claude-header", "X-Claude-Code-Session-Id", "s", "", "", "claude:s"},
		{"generic-header", "X-Session-ID", "s", "", "", "header:s"},
		{"canonical-wins", "X-Session-ID", "generic", "claude:body-session", "", "claude:body-session"},
		{"request-header-is-not-session", "X-Client-Request-Id", "one-request", "", "", ""},
		{"canonical-request-is-not-session", "", "", "clientreq:one-request", "", ""},
		{"derived-is-not-explicit-session", "", "", "inferred", "inferred", ""},
		{"empty", "X-Session-ID", "  ", " ", "", ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			p := pickReq("execution-id", "k")
			if c.header != "" {
				p.Options.Headers.Set(c.header, c.value)
			}
			p.Options.Metadata["canonical_session_id"] = c.canonical
			p.Options.Metadata["derived_session_id"] = c.derived
			if got := sessionID(p); got != c.want {
				t.Fatalf("got %q, want %q", got, c.want)
			}
		})
	}
}

func TestSessionPrunesExpiredAndEvictsEarliest(t *testing.T) {
	l := newLimiter()
	now := time.Now()
	l.sessions["expired"] = &sessionBinding{AuthID: "A", Expire: now.Add(-time.Second)}
	for i := 0; i < maxSessions; i++ {
		l.sessions[fmt.Sprintf("old-%04d", i)] = &sessionBinding{AuthID: "A", Expire: now.Add(time.Duration(i+1) * time.Millisecond)}
	}
	l.bindSession("new", "B", now)
	if len(l.sessions) != maxSessions || l.sessions["expired"] != nil || l.sessions["old-0000"] != nil || l.sessions["new"] == nil {
		t.Fatal("session table is not bounded or evicts wrong entry", len(l.sessions))
	}
	if l.sessions["old-0001"] == nil {
		t.Fatal("removed extra entry")
	}
}

func TestSessionFailedCompletionPreservesAndReleases(t *testing.T) {
	for _, status := range []int{401, 403, 429, 500, 502, 503, 599} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			l := newLimiter()
			a := mustSessionPick(t, l, "req", "k", "claude:s1")
			after := beforeReq("req", "k")
			after.Metadata["selected_auth_id"] = a
			l.after(after)
			l.sessions["other-on-A"] = &sessionBinding{AuthID: a, Expire: time.Now().Add(sessionTTL)}
			l.sessions["other-on-B"] = &sessionBinding{AuthID: "B", Expire: time.Now().Add(sessionTTL)}
			// Completion metadata may omit selected_auth_id after CPA metadata copies.
			l.completeResult(request{RequestID: "req", Outcome: "failed", StatusCode: status})
			if l.sessions["claude:s1"] == nil || l.sessions["other-on-A"] == nil || l.sessions["other-on-B"] == nil {
				t.Fatal("status-only failure erased session preferences")
			}
			if len(l.owners) != 0 || len(l.keys) != 0 || len(l.leases) != 0 {
				t.Fatal("failed completion leaked slots")
			}
			l.completeResult(request{RequestID: "req", Outcome: "failed", StatusCode: status})
			if l.completed != 1 {
				t.Fatal("duplicate completion not idempotent")
			}
			if got := mustSessionPick(t, l, "next", "k", "claude:s1"); got != a {
				t.Fatal("failure caused permanent account rotation", got, a)
			}
		})
	}
}

func TestSessionConfirmedDisabledOrRemovedRebinds(t *testing.T) {
	l := newLimiter()
	l.lookupAccount = func(string) accountState { return accountDisabledOrRemoved }
	a := mustSessionPick(t, l, "first", "k", "claude:s1")
	l.complete("first")
	l.sessions["other-on-A"] = &sessionBinding{AuthID: a, Expire: time.Now().Add(sessionTTL)}
	l.sessions["other-on-B"] = &sessionBinding{AuthID: "B", Expire: time.Now().Add(sessionTTL)}
	l.before(beforeReq("next", "k"))
	p := sessionPickReq("next", "k", "claude:s1")
	p.Candidates = []candidate{{ID: "B"}}
	if result(l.pick(p))["AuthID"] != "B" || l.sessions["claude:s1"].AuthID != "B" {
		t.Fatal("confirmed permanent removal did not rebind")
	}
	if l.sessions["other-on-A"] != nil || l.sessions["other-on-B"] == nil {
		t.Fatal("confirmed removal affected the wrong account")
	}
}

func TestSessionUnknownHostStatePreservesPreference(t *testing.T) {
	l := newLimiter()
	l.lookupAccount = func(string) accountState { return accountUnknown }
	a := mustSessionPick(t, l, "first", "k", "claude:s1")
	l.complete("first")
	l.before(beforeReq("next", "k"))
	p := sessionPickReq("next", "k", "claude:s1")
	p.Candidates = []candidate{{ID: "B"}}
	if result(l.pick(p))["AuthID"] != "B" || l.sessions["claude:s1"].AuthID != a {
		t.Fatal("callback failure erased preference or blocked fallback")
	}
}

func TestSessionHostLookupRevalidatesCompletedLease(t *testing.T) {
	l := newLimiter()
	mustSessionPick(t, l, "first", "k", "claude:s1")
	l.complete("first")
	l.before(beforeReq("next", "k"))
	l.lookupAccount = func(string) accountState {
		l.complete("next") // Must be able to complete while the host callback runs.
		return accountPresent
	}
	p := sessionPickReq("next", "k", "claude:s1")
	p.Candidates = []candidate{{ID: "B"}}
	if l.pick(p)["ok"] != false || len(l.owners) != 0 || len(l.leases) != 0 {
		t.Fatal("stale lookup recreated a completed lease")
	}
}

func TestSessionHostLookupDoesNotEraseReplacementBinding(t *testing.T) {
	l := newLimiter()
	mustSessionPick(t, l, "first", "k", "claude:s1")
	l.complete("first")
	l.before(beforeReq("next", "k"))
	l.lookupAccount = func(string) accountState {
		l.mu.Lock()
		l.sessions["claude:s1"] = &sessionBinding{AuthID: "C", Expire: time.Now().Add(sessionTTL)}
		l.mu.Unlock()
		return accountDisabledOrRemoved
	}
	p := sessionPickReq("next", "k", "claude:s1")
	p.Candidates = []candidate{{ID: "B"}, {ID: "C"}}
	if result(l.pick(p))["AuthID"] != "C" || l.sessions["claude:s1"].AuthID != "C" {
		t.Fatal("stale host result erased a newer binding")
	}
}

func TestSessionAccountStateRequiresAuthoritativeList(t *testing.T) {
	for _, c := range []struct {
		name, body string
		want       accountState
	}{
		{"enabled", `{"ok":true,"result":{"files":[{"id":"A","status":"active"}]}}`, accountPresent},
		{"cooling", `{"ok":true,"result":{"files":[{"id":"A","status":"error","unavailable":true}]}}`, accountPresent},
		{"disabled-flag", `{"ok":true,"result":{"files":[{"id":"A","disabled":true}]}}`, accountDisabledOrRemoved},
		{"disabled-status", `{"ok":true,"result":{"files":[{"id":"A","status":"disabled"}]}}`, accountDisabledOrRemoved},
		{"removed", `{"ok":true,"result":{"files":[{"id":"B"}]}}`, accountDisabledOrRemoved},
		{"no-accounts", `{"ok":true,"result":{"files":[]}}`, accountDisabledOrRemoved},
		{"host-error", `{"ok":false,"error":{"code":"failed"}}`, accountUnknown},
		{"missing-list", `{"ok":true,"result":{}}`, accountUnknown},
		{"null-list", `{"ok":true,"result":{"files":null}}`, accountUnknown},
		{"missing-id", `{"ok":true,"result":{"files":[{"name":"A"}]}}`, accountUnknown},
		{"invalid-json", `{`, accountUnknown},
	} {
		t.Run(c.name, func(t *testing.T) {
			if got := accountStateFromList([]byte(c.body), "A"); got != c.want {
				t.Fatal("wrong account state", got, c.want)
			}
		})
	}
}

func TestSessionNonAccountFailuresDoNotInvalidate(t *testing.T) {
	for _, c := range []struct {
		outcome string
		status  int
	}{{"succeeded", 200}, {"rejected", 429}, {"canceled", 0}, {"failed", 400}} {
		l := newLimiter()
		a := mustSessionPick(t, l, "req", "k", "claude:s1")
		l.completeResult(request{RequestID: "req", Outcome: c.outcome, StatusCode: c.status, Metadata: obj{"selected_auth_id": a}})
		if l.sessions["claude:s1"] == nil || len(l.owners) != 0 {
			t.Fatal("incorrect invalidation/release", c)
		}
	}
}

func TestSessionConcurrentPicksRespectLimits(t *testing.T) {
	l := newLimiter()
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			id := fmt.Sprint(i)
			key := fmt.Sprint(i % 4)
			l.before(beforeReq(id, key))
			l.pick(sessionPickReq(id, key, "claude:shared"))
		}(i)
	}
	wg.Wait()
	for key, n := range l.keys {
		if n > 5 {
			t.Fatal("key cap", key, n)
		}
	}
	for auth, owners := range l.owners {
		if len(owners) > 2 {
			t.Fatal("account cap", auth, len(owners))
		}
	}
	for id := range l.leases {
		l.complete(id)
	}
	if len(l.owners) != 0 || len(l.keys) != 0 {
		t.Fatal("slots leaked")
	}
}

func TestSessionCannotBypassLeaseValidation(t *testing.T) {
	l := newLimiter()
	mustSessionPick(t, l, "valid", "k", "claude:s1")
	for _, p := range []pickRequest{sessionPickReq("unknown", "k", "claude:s1"), sessionPickReq("valid", "wrong-key", "claude:s1")} {
		if l.pick(p)["ok"] != false {
			t.Fatal("sticky selection bypassed lease validation")
		}
	}
	if len(l.owners["0"]) != 1 {
		t.Fatal("invalid request reserved slot")
	}
}
