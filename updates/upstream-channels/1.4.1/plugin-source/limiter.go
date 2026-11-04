package main

import (
	"encoding/hex"
	"encoding/json"
	"net/http"
	"sort"
	"strings"
	"sync"
	"time"

	"gopkg.in/yaml.v3"
)

const leaseHeader = "X-Cpa-Concurrency-Lease"

const (
	sessionTTL  = time.Hour
	maxSessions = 4096
)

type sessionBinding struct {
	AuthID string
	Expire time.Time
}

type accountState uint8

const (
	accountUnknown accountState = iota
	accountPresent
	accountDisabledOrRemoved
)

// Only an explicitly disabled host record may invalidate all account bindings.
// A partial list, a failed callback or a cooldown is not global deletion proof.
func accountStateFromList(raw []byte, authID string) accountState {
	var reply struct {
		OK     bool `json:"ok"`
		Result struct {
			Files *[]struct {
				ID       string `json:"id"`
				Disabled bool   `json:"disabled"`
				Status   string `json:"status"`
			} `json:"files"`
		} `json:"result"`
	}
	if authID == "" || json.Unmarshal(raw, &reply) != nil || !reply.OK || reply.Result.Files == nil {
		return accountUnknown
	}
	for _, a := range *reply.Result.Files {
		if a.ID == authID {
			if a.Disabled || a.Status == "disabled" {
				return accountDisabledOrRemoved
			}
			return accountPresent
		}
		if a.ID == "" {
			// Do not infer deletion from an incomplete/unsupported host schema.
			return accountUnknown
		}
	}
	// Host lists can omit config-backed runtime credentials. Absence alone is not deletion proof.
	return accountUnknown
}

type obj = map[string]any
type lease struct {
	Key            string
	Accounts       map[string]bool
	Started        time.Time
	SelectedAuthID string
	SessionID      string
}
type limiter struct {
	mu                            sync.Mutex
	groups                        groupPolicy
	limit                         int
	accountLimits                 map[string]int
	keyLimits                     map[string]int
	leases                        map[string]*lease
	owners                        map[string]map[string]bool
	keys                          map[string]int
	last                          string
	sessions                      map[string]*sessionBinding
	sessionPolicy                 string
	lookupAccount                 func(string) accountState
	accepted, rejected, completed uint64
}

func newLimiter() *limiter {
	return &limiter{limit: 5, leases: map[string]*lease{}, owners: map[string]map[string]bool{}, keys: map[string]int{}, sessions: map[string]*sessionBinding{}, lookupAccount: readHostAccountState}
}

var state = newLimiter()

func ok(v any) obj { return obj{"ok": true, "result": v} }
func failure(code string, status int) obj {
	return obj{"ok": false, "error": obj{"code": code, "message": code, "http_status": status, "retryable": false}}
}
func terminate(code string, status int) obj {
	b, _ := json.Marshal(obj{"error": obj{"type": "rate_limit_error", "code": code, "message": code}})
	return ok(obj{"Terminate": true, "StatusCode": status, "ClearHeaders": []string{leaseHeader}, "ResponseHeaders": http.Header{"Content-Type": {"application/json"}, "Retry-After": {"1"}}, "ResponseBody": b})
}

type request struct {
	RequestID  string
	Headers    http.Header
	Metadata   obj
	Outcome    string
	StatusCode int
}
type candidate struct{ ID, Provider string }
type pickRequest struct {
	Options struct {
		Headers  http.Header
		Metadata obj
	}
	Candidates []candidate
}

func str(m obj, k string) string { s, _ := m[k].(string); return s }

// CPA enriches explicit Claude headers/body sessions into canonical_session_id
// before scheduler.pick. Request IDs and inferred content fingerprints are not
// conversation identities for this plugin.
func sessionID(r pickRequest) string {
	if id := strings.TrimSpace(str(r.Options.Metadata, "canonical_session_id")); id != "" &&
		!strings.HasPrefix(id, "clientreq:") &&
		strings.TrimSpace(str(r.Options.Metadata, "derived_session_id")) == "" &&
		strings.TrimSpace(str(r.Options.Metadata, "lcp_affinity_session_id")) == "" {
		return id
	}
	if id := strings.TrimSpace(r.Options.Headers.Get("X-Claude-Code-Session-Id")); id != "" {
		return "claude:" + id
	}
	if id := strings.TrimSpace(r.Options.Headers.Get("X-Session-ID")); id != "" {
		return "header:" + id
	}
	return ""
}

// Called only while l.mu is held. Expiry is sliding on a successful sticky pick;
// a capacity fallback must not refresh or replace the original binding.
func (l *limiter) pruneSessions(now time.Time) {
	for id, binding := range l.sessions {
		if binding == nil || (!binding.Expire.After(now) && !l.sessionInFlight(id)) {
			delete(l.sessions, id)
		}
	}
	for len(l.sessions) > maxSessions {
		oldestID := ""
		var oldest *sessionBinding
		for id, binding := range l.sessions {
			if oldest == nil || binding.Expire.Before(oldest.Expire) ||
				(binding.Expire.Equal(oldest.Expire) && id < oldestID) {
				oldestID, oldest = id, binding
			}
		}
		delete(l.sessions, oldestID)
	}
}

// Caller holds l.mu. Counts represent explicit live conversation bindings, not requests.
func (l *limiter) sessionInFlight(id string) bool {
	for _, lease := range l.leases {
		if lease.SessionID == id {
			return true
		}
	}
	return false
}
func (l *limiter) sessionLoads() map[string]int {
	counts := map[string]int{}
	for _, b := range l.sessions {
		if b != nil {
			counts[b.AuthID]++
		}
	}
	return counts
}

func (l *limiter) bindSession(id, authID string, now time.Time) {
	if id != "" && l.sessions[id] == nil {
		l.sessions[id] = &sessionBinding{AuthID: authID, Expire: now.Add(sessionTTL)}
		l.pruneSessions(now)
	}
}

func (l *limiter) forgetAccountSessions(authID string) {
	for id, binding := range l.sessions {
		if binding != nil && binding.AuthID == authID {
			delete(l.sessions, id)
		}
	}
}

// accountLimit must be called with l.mu held. Unlisted accounts retain 2.
func (l *limiter) accountLimit(auth string) int {
	if n := l.accountLimits[auth]; n >= 1 && n <= 5 {
		return n
	}
	return 2
}

// keyLimit must be called with l.mu held. Defaults remain unchanged.
func (l *limiter) keyLimit(scope string) int {
	if n := l.keyLimits[scope]; n >= 1 && n <= 100 {
		return n
	}
	return l.limit
}
func (l *limiter) before(r request) obj {
	l.mu.Lock()
	defer l.mu.Unlock()
	key := str(r.Metadata, "caller_scope")
	if r.RequestID == "" || key == "" {
		return terminate("concurrency_context_missing", 503)
	}
	if _, code, status := l.groupFor(key); code != "" {
		return groupTerminate(code, status)
	}
	if existing := l.leases[r.RequestID]; existing != nil {
		if existing.Key != key {
			return terminate("concurrency_context_mismatch", 503)
		}
	} else {
		if l.keys[key] >= l.keyLimit(key) {
			l.rejected++
			return terminate("key_concurrency_exceeded", 429)
		}
		l.leases[r.RequestID] = &lease{Key: key, Accounts: map[string]bool{}, Started: time.Now()}
		l.keys[key]++
		l.accepted++
	}
	// Overwrite any untrusted client-supplied lease header with the host UUID.
	return ok(obj{"Headers": http.Header{leaseHeader: {r.RequestID}}})
}
func (l *limiter) pick(r pickRequest) obj {
	l.mu.Lock()
	defer l.mu.Unlock()
	id := r.Options.Headers.Get(leaseHeader)
	lease := l.leases[id]
	if lease == nil || lease.Key != str(r.Options.Metadata, "caller_scope") {
		return failure("concurrency_context_missing", 503)
	}
	var code string
	var status int
	r, code, status = l.groupCandidates(r)
	if code != "" {
		return failure(code, status)
	}
	now := time.Now()
	l.pruneSessions(now)
	sid := l.scopedSessionID(r)
	lease.SessionID = sid
	if binding := l.sessions[sid]; sid != "" && binding != nil && !hasCandidate(r, binding.AuthID) && l.lookupAccount != nil {
		authID := binding.AuthID
		lookup := l.lookupAccount
		// Host callbacks may acquire host locks. Never hold our limiter lock while
		// calling back; a completion can release its slots during this lookup.
		l.mu.Unlock()
		availability := lookup(authID)
		l.mu.Lock()
		lease = l.leases[id]
		if lease == nil || lease.Key != str(r.Options.Metadata, "caller_scope") {
			return failure("concurrency_context_missing", 503)
		}
		r, code, status = l.groupCandidates(r)
		if code != "" {
			return failure(code, status)
		}
		sid = l.scopedSessionID(r)
		lease.SessionID = sid
		now = time.Now()
		l.pruneSessions(now)
		if current := l.sessions[sid]; current != nil && current.AuthID == authID && availability == accountDisabledOrRemoved {
			l.forgetAccountSessions(authID)
		}
	}
	if binding := l.sessions[sid]; sid != "" && binding != nil {
		if hasCandidate(r, binding.AuthID) && (len(l.owners[binding.AuthID]) < l.accountLimit(binding.AuthID) || l.owners[binding.AuthID][id]) {
			authID := binding.AuthID
			if l.owners[authID] == nil {
				l.owners[authID] = map[string]bool{}
			}
			l.owners[authID][id] = true
			lease.Accounts[authID] = true
			l.last = authID
			binding.Expire = now.Add(sessionTTL)
			return ok(obj{"Handled": true, "AuthID": authID})
		}
		if hasCandidate(r, binding.AuthID) {
			// Capacity alone never migrates an existing conversation.
			binding.Expire = now.Add(sessionTTL)
			l.rejected++
			return failure("session_account_concurrency_exceeded", 429)
		}
		// CPA removed this credential from the current model's available set.
		// Rebind this conversation only after selecting a replacement. Do not
		// infer quota exhaustion or clear other conversations from this signal.
	}
	sort.Slice(r.Candidates, func(i, j int) bool { return r.Candidates[i].ID < r.Candidates[j].ID })
	counts := l.sessionLoads()
	// Explicit conversations balance by live bindings. Missing session identities
	// retain request-load selection and never invent a conversation identity.
	best := -1
	better := func(i, j int) bool {
		a, b := r.Candidates[i].ID, r.Candidates[j].ID
		if sid != "" && counts[a] != counts[b] {
			return counts[a] < counts[b]
		}
		if len(l.owners[a]) != len(l.owners[b]) {
			return len(l.owners[a]) < len(l.owners[b])
		}
		an, bn := a > l.last, b > l.last
		if an != bn {
			return an
		}
		return a < b
	}
	for i, c := range r.Candidates {
		if c.ID == "" || len(l.owners[c.ID]) >= l.accountLimit(c.ID) || l.owners[c.ID][id] {
			continue
		}
		if best < 0 || better(i, best) {
			best = i
		}
	}
	if best >= 0 {
		authID := r.Candidates[best].ID
		if l.owners[authID] == nil {
			l.owners[authID] = map[string]bool{}
		}
		l.owners[authID][id] = true
		lease.Accounts[authID] = true
		l.last = authID
		if sid != "" {
			l.sessions[sid] = &sessionBinding{AuthID: authID, Expire: now.Add(sessionTTL)}
			l.pruneSessions(now)
		}
		return ok(obj{"Handled": true, "AuthID": authID})
	}
	// A retry can reuse a reservation owned by this same execution, never another execution.
	for _, c := range r.Candidates {
		if l.owners[c.ID][id] && c.ID != "" {
			if sid != "" {
				l.sessions[sid] = &sessionBinding{AuthID: c.ID, Expire: now.Add(sessionTTL)}
				l.pruneSessions(now)
			}
			return ok(obj{"Handled": true, "AuthID": c.ID})
		}
	}
	l.rejected++
	return failure("account_concurrency_exceeded", 429)
}

func hasCandidate(r pickRequest, authID string) bool {
	for _, c := range r.Candidates {
		if authID != "" && c.ID == authID {
			return true
		}
	}
	return false
}
func (l *limiter) after(r request) obj {
	l.mu.Lock()
	defer l.mu.Unlock()
	lease := l.leases[r.RequestID]
	auth := str(r.Metadata, "selected_auth_id")
	if lease == nil || auth == "" || lease.Key != str(r.Metadata, "caller_scope") {
		return terminate("concurrency_context_missing", 503)
	}
	g, code, status := l.groupFor(lease.Key)
	if code != "" {
		return groupTerminate(code, status)
	}
	if g != nil && !g.auths[auth] {
		return groupTerminate("account_group_access_denied", 403)
	}
	// Also gate pinned selections that bypass the scheduler.
	if !l.owners[auth][r.RequestID] && len(l.owners[auth]) >= l.accountLimit(auth) {
		l.rejected++
		return terminate("account_concurrency_exceeded", 429)
	}
	if l.owners[auth] == nil {
		l.owners[auth] = map[string]bool{}
	}
	l.owners[auth][r.RequestID] = true
	lease.Accounts[auth] = true
	lease.SelectedAuthID = auth
	return ok(obj{"ClearHeaders": []string{leaseHeader}})
}
func (l *limiter) complete(id string) obj {
	return l.completeResult(request{RequestID: id})
}

func (l *limiter) completeResult(r request) obj {
	id := r.RequestID
	l.mu.Lock()
	defer l.mu.Unlock()
	if lease := l.leases[id]; lease != nil {
		if b := l.sessions[lease.SessionID]; b != nil {
			b.Expire = time.Now().Add(sessionTTL)
		}
		// Completion status alone cannot establish permanent account failure.
		// Preserve preferences on EOF/5xx/429 (and failed refresh attempts); the
		// host filters unusable candidates and pick checks confirmed disablement.
		for auth := range lease.Accounts {
			delete(l.owners[auth], id)
			if len(l.owners[auth]) == 0 {
				delete(l.owners, auth)
			}
		}
		l.keys[lease.Key]--
		if l.keys[lease.Key] == 0 {
			delete(l.keys, lease.Key)
		}
		delete(l.leases, id)
		l.completed++
	}
	return ok(obj{})
}
func (l *limiter) configure(raw []byte) obj {
	var r struct {
		ConfigYAML []byte `json:"config_yaml"`
	}
	if json.Unmarshal(raw, &r) != nil {
		l.mu.Lock()
		l.groups.invalid = true
		l.mu.Unlock()
		return failure("invalid_config", 400)
	}
	cfg := struct {
		Max           int                           `yaml:"max_per_key"`
		KeyLimits     map[string]int                `yaml:"key_limits"`
		AccountLimits map[string]int                `yaml:"account_limits"`
		EnforceGroups bool                          `yaml:"enforce_account_groups"`
		Groups        map[string]accountGroupConfig `yaml:"account_groups"`
	}{Max: 5}
	err := yaml.Unmarshal(r.ConfigYAML, &cfg)
	l.mu.Lock()
	defer l.mu.Unlock()
	l.groups = parseGroupPolicy(cfg.EnforceGroups, cfg.Groups)
	l.keyLimits = map[string]int{}
	for scope, n := range cfg.KeyLimits {
		decoded, decodeErr := hex.DecodeString(scope)
		if decodeErr != nil || len(decoded) != 32 || strings.ToLower(scope) != scope || n < 1 || n > 100 || (cfg.EnforceGroups && l.groups.byScope[scope] == nil) {
			l.groups.invalid = true
			continue
		}
		l.keyLimits[scope] = n
	}
	l.accountLimits = map[string]int{}
	for auth, n := range cfg.AccountLimits {
		if strings.TrimSpace(auth) == "" || strings.TrimSpace(auth) != auth || n < 1 || n > 5 {
			l.groups.invalid = true
			continue
		}
		found := !cfg.EnforceGroups
		for _, g := range cfg.Groups {
			for _, id := range g.AuthIDs {
				if id == auth {
					found = true
				}
			}
		}
		if !found {
			l.groups.invalid = true
			continue
		}
		l.accountLimits[auth] = n
	}
	if err != nil {
		l.groups.invalid = true
	}
	policyJSON, _ := json.Marshal(obj{"enabled": cfg.EnforceGroups, "groups": cfg.Groups})
	policy := string(policyJSON)
	if l.groups.invalid || l.sessionPolicy != policy {
		l.sessions = map[string]*sessionBinding{}
	}
	l.sessionPolicy = policy
	l.pruneSessions(time.Now())
	// Invalid configuration fails conservatively, never silently disables admission control.
	if err != nil || cfg.Max < 1 || cfg.Max > 5 {
		l.limit = 1
	} else {
		l.limit = cfg.Max
	}
	return registration()
}
func registration() obj {
	return ok(obj{"schema_version": 2, "metadata": obj{"Name": "account-concurrency", "Version": "1.4.1-upstream-channels", "Author": "Local deployment", "GitHubRepository": "local:/opt/cpa-concurrency-build", "ConfigFields": []obj{{"Name": "max_per_key", "Type": "integer", "Default": 5, "Description": "未覆盖Key默认并发上限（1–5）；key_limits可单Key覆盖至100；未覆盖账号默认 2 并发；account_limits 可单独设置 1–5。修改后保存生效。"}}}, "capabilities": obj{"scheduler": true, "scheduler_across_priorities": true, "request_interceptor": true, "request_lifecycle_plugin": true, "management_api": true}})
}
func cloneAccountLimits(m map[string]int) map[string]int {
	out := map[string]int{}
	for k, v := range m {
		out[k] = v
	}
	return out
}
func (l *limiter) snapshot() obj {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.pruneSessions(time.Now())
	counts := l.sessionLoads()
	sessionAccounts := []obj{}
	for account, count := range counts {
		sessionAccounts = append(sessionAccounts, obj{"account": account, "active_sessions": count})
	}
	sort.Slice(sessionAccounts, func(i, j int) bool {
		return sessionAccounts[i]["account"].(string) < sessionAccounts[j]["account"].(string)
	})
	active := []obj{}
	for auth, owners := range l.owners {
		seconds := 0
		for id := range owners {
			age := int(time.Since(l.leases[id].Started).Seconds())
			if age > seconds {
				seconds = age
			}
		}
		active = append(active, obj{"account": auth, "active": len(owners), "seconds": seconds})
	}
	return obj{"upstream_channels_supported": true, "routing_policy": "least-active-sessions-sticky", "session_idle_ttl_seconds": int(sessionTTL.Seconds()), "active_sessions": len(l.sessions), "session_accounts": sessionAccounts, "account_groups_enabled": l.groups.enabled, "account_groups_valid": !l.groups.invalid, "account_group_count": l.groups.groups, "assigned_key_count": len(l.groups.byScope), "max_per_key": l.limit, "max_per_account": 2, "account_limits": cloneAccountLimits(l.accountLimits), "key_limits": cloneAccountLimits(l.keyLimits), "active_requests": len(l.leases), "busy_accounts": active, "accepted": l.accepted, "rejected": l.rejected, "completed": l.completed}
}
func manage(raw []byte) obj {
	var r struct{ Method, Path string }
	if json.Unmarshal(raw, &r) != nil {
		return failure("invalid_request", 400)
	}
	if r.Path == "/groups" || r.Path == "/v0/resource/plugins/account-concurrency/groups" {
		return ok(obj{"StatusCode": 200, "Headers": http.Header{"Content-Type": {"text/html; charset=utf-8"}, "Cache-Control": {"no-store"}}, "Body": []byte(groupMenu)})
	}
	if r.Path == "/menu" || r.Path == "/v0/resource/plugins/account-concurrency/menu" {
		return ok(obj{"StatusCode": 200, "Headers": http.Header{"Content-Type": {"text/html; charset=utf-8"}, "Cache-Control": {"no-store"}}, "Body": []byte(menu)})
	}
	if r.Method != "GET" {
		return ok(obj{"StatusCode": 405})
	}
	b, _ := json.Marshal(state.snapshot())
	return ok(obj{"StatusCode": 200, "Headers": http.Header{"Content-Type": {"application/json"}, "Cache-Control": {"no-store"}}, "Body": b})
}
func handle(method string, raw []byte) obj {
	switch method {
	case "plugin.register", "plugin.reconfigure":
		return state.configure(raw)
	case "plugin.quiesce", "plugin.shutdown":
		return ok(obj{})
	case "request.intercept_before", "request.intercept_after", "request.complete":
		var r request
		if json.Unmarshal(raw, &r) != nil {
			return terminate("invalid_context", 503)
		}
		if method == "request.intercept_before" {
			return state.before(r)
		}
		if method == "request.intercept_after" {
			return state.after(r)
		}
		return state.completeResult(r)
	case "scheduler.pick":
		var r pickRequest
		if json.Unmarshal(raw, &r) != nil {
			return failure("invalid_context", 503)
		}
		return state.pick(r)
	case "management.register":
		return ok(obj{"resources": []obj{{"Path": "/groups", "Menu": "账号组与专属 Key", "Description": "选择 Claude 账号及专属 Key"}, {"Path": "/menu", "Menu": "账号并发限制", "Description": "Key 并发上限与账号忙碌状态"}}, "routes": []obj{{"Method": "GET", "Path": "/plugins/account-concurrency/status"}}})
	case "management.handle":
		return manage(raw)
	}
	return failure("unknown_method", 400)
}

const menu = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>账号并发限制</title><style>body{font:16px system-ui;max-width:760px;margin:40px auto;background:#171717;color:#eee}input,button{padding:10px;margin:8px}pre{white-space:pre-wrap}label{display:block}</style><h1>账号并发限制</h1><p>账号默认同时最多 2 个请求；指定账号可覆盖至 5。没有空闲账号时返回 429，不排队。Key 上限可设置为 1–5。</p><label>CPA 管理密钥（不是客户端 API Key）<input id="key" type="password" autocomplete="off"></label><label>每个 Key 最大并发<input id="limit" type="number" min="1" max="5" value="5"></label><button id="load">查看状态</button><button id="save">保存上限</button><pre id="out">也可以在「插件管理 → account-concurrency → 配置」修改 max_per_key。</pre><script>
const $=id=>document.getElementById(id);async function api(path,method='GET',body){let r=await fetch('/v0/management/plugins/account-concurrency/'+path,{method,headers:{'Authorization':'Bearer '+$('key').value,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});let t=await r.text();if(!r.ok)throw Error(r.status+' '+t);return JSON.parse(t)}
$('load').onclick=async()=>{try{let s=await api('status');$('limit').value=s.max_per_key;$('out').textContent=JSON.stringify(s,null,2)}catch(e){$('out').textContent=e.message}};
$('save').onclick=async()=>{let n=Number($('limit').value);if(!Number.isInteger(n)||n<1||n>5){$('out').textContent='请输入 1–5 的整数';return}try{await api('config','PATCH',{max_per_key:n});$('out').textContent='已保存。请点击查看状态核对生效值。'}catch(e){$('out').textContent=e.message}};
</script></html>`
