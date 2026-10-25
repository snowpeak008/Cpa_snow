package main

import (
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

// Only an authoritative host list may invalidate a preferred account. A failed
// callback, a cooldown, or a missing per-request candidate is not such evidence.
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
	return accountDisabledOrRemoved
}

type obj = map[string]any
type lease struct {
	Key            string
	Accounts       map[string]bool
	Started        time.Time
	SelectedAuthID string
}
type limiter struct {
	mu                            sync.Mutex
	limit                         int
	leases                        map[string]*lease
	owners                        map[string]map[string]bool
	keys                          map[string]int
	last                          string
	sessions                      map[string]*sessionBinding
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
type candidate struct{ ID string }
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
		if binding == nil || !binding.Expire.After(now) {
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

func (l *limiter) before(r request) obj {
	l.mu.Lock()
	defer l.mu.Unlock()
	key := str(r.Metadata, "caller_scope")
	if r.RequestID == "" || key == "" {
		return terminate("concurrency_context_missing", 503)
	}
	if existing := l.leases[r.RequestID]; existing != nil {
		if existing.Key != key {
			return terminate("concurrency_context_mismatch", 503)
		}
	} else {
		if l.keys[key] >= l.limit {
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
	now := time.Now()
	l.pruneSessions(now)
	sid := sessionID(r)
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
		now = time.Now()
		l.pruneSessions(now)
		if current := l.sessions[sid]; current != nil && current.AuthID == authID && availability == accountDisabledOrRemoved {
			l.forgetAccountSessions(authID)
		}
	}
	if binding := l.sessions[sid]; sid != "" && binding != nil {
		if hasCandidate(r, binding.AuthID) && len(l.owners[binding.AuthID]) < 2 {
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
		// Full or temporarily absent: borrow another eligible account without
		// replacing/extending the preferred binding. Host cooldowns still apply.
	}
	sort.Slice(r.Candidates, func(i, j int) bool { return r.Candidates[i].ID < r.Candidates[j].ID })
	// Prefer the next idle account, retaining old reservations across retries until completion.
	for load := 0; load < 2; load++ {
		for pass := 0; pass < 2; pass++ {
			for _, c := range r.Candidates {
				if c.ID == "" || (pass == 0 && c.ID <= l.last) || (pass == 1 && c.ID > l.last) {
					continue
				}
				if len(l.owners[c.ID]) != load || l.owners[c.ID][id] {
					continue
				}
				if l.owners[c.ID] == nil {
					l.owners[c.ID] = map[string]bool{}
				}
				l.owners[c.ID][id] = true
				lease.Accounts[c.ID] = true
				l.last = c.ID
				l.bindSession(sid, c.ID, now)
				return ok(obj{"Handled": true, "AuthID": c.ID})
			}
		}
	}
	// A retry can reuse a reservation owned by this same execution, never another execution.
	for _, c := range r.Candidates {
		if l.owners[c.ID][id] && c.ID != "" {
			l.bindSession(sid, c.ID, now)
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
	// Also gate pinned selections that bypass the scheduler.
	if !l.owners[auth][r.RequestID] && len(l.owners[auth]) >= 2 {
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
		return failure("invalid_config", 400)
	}
	cfg := struct {
		Max int `yaml:"max_per_key"`
	}{Max: 5}
	err := yaml.Unmarshal(r.ConfigYAML, &cfg)
	l.mu.Lock()
	defer l.mu.Unlock()
	// Invalid configuration fails conservatively, never silently disables admission control.
	if err != nil || cfg.Max < 1 || cfg.Max > 5 {
		l.limit = 1
	} else {
		l.limit = cfg.Max
	}
	return registration()
}
func registration() obj {
	return ok(obj{"schema_version": 2, "metadata": obj{"Name": "account-concurrency", "Version": "1.2.1-session-recovery", "Author": "Local deployment", "GitHubRepository": "local:/opt/cpa-concurrency-build", "ConfigFields": []obj{{"Name": "max_per_key", "Type": "integer", "Default": 5, "Description": "每个客户端 Key 的并发上限（1–5）；每个账号固定 2 并发。修改后保存生效。"}}}, "capabilities": obj{"scheduler": true, "scheduler_across_priorities": true, "request_interceptor": true, "request_lifecycle_plugin": true, "management_api": true}})
}
func (l *limiter) snapshot() obj {
	l.mu.Lock()
	defer l.mu.Unlock()
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
	return obj{"max_per_key": l.limit, "max_per_account": 2, "active_requests": len(l.leases), "busy_accounts": active, "accepted": l.accepted, "rejected": l.rejected, "completed": l.completed}
}
func manage(raw []byte) obj {
	var r struct{ Method, Path string }
	if json.Unmarshal(raw, &r) != nil {
		return failure("invalid_request", 400)
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
		return ok(obj{"resources": []obj{{"Path": "/menu", "Menu": "账号并发限制", "Description": "Key 并发上限与账号忙碌状态"}}, "routes": []obj{{"Method": "GET", "Path": "/plugins/account-concurrency/status"}}})
	case "management.handle":
		return manage(raw)
	}
	return failure("unknown_method", 400)
}

const menu = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>账号并发限制</title><style>body{font:16px system-ui;max-width:760px;margin:40px auto;background:#171717;color:#eee}input,button{padding:10px;margin:8px}pre{white-space:pre-wrap}label{display:block}</style><h1>账号并发限制</h1><p>每个账号同时最多 2 个请求。没有空闲账号时返回 429，不排队。Key 上限可设置为 1–5。</p><label>CPA 管理密钥（不是客户端 API Key）<input id="key" type="password" autocomplete="off"></label><label>每个 Key 最大并发<input id="limit" type="number" min="1" max="5" value="5"></label><button id="load">查看状态</button><button id="save">保存上限</button><pre id="out">也可以在「插件管理 → account-concurrency → 配置」修改 max_per_key。</pre><script>
const $=id=>document.getElementById(id);async function api(path,method='GET',body){let r=await fetch('/v0/management/plugins/account-concurrency/'+path,{method,headers:{'Authorization':'Bearer '+$('key').value,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});let t=await r.text();if(!r.ok)throw Error(r.status+' '+t);return JSON.parse(t)}
$('load').onclick=async()=>{try{let s=await api('status');$('limit').value=s.max_per_key;$('out').textContent=JSON.stringify(s,null,2)}catch(e){$('out').textContent=e.message}};
$('save').onclick=async()=>{let n=Number($('limit').value);if(!Number.isInteger(n)||n<1||n>5){$('out').textContent='请输入 1–5 的整数';return}try{await api('config','PATCH',{max_per_key:n});$('out').textContent='已保存。请点击查看状态核对生效值。'}catch(e){$('out').textContent=e.message}};
</script></html>`
