package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strings"
)

// Account groups are authorization boundaries, independent of session affinity.
// Scopes come from CPA authentication, never from a client-selected header.
type accountGroupConfig struct {
	AuthIDs   []string `yaml:"auth_ids"`
	KeyScopes []string `yaml:"key_scopes"`
}

type accountGroup struct {
	name  string
	auths map[string]bool
}

type groupPolicy struct {
	enabled bool
	invalid bool
	byScope map[string]*accountGroup
	groups  int
}

func parseGroupPolicy(enabled bool, configs map[string]accountGroupConfig) groupPolicy {
	p := groupPolicy{enabled: enabled, byScope: map[string]*accountGroup{}}
	if !enabled {
		// Do not silently ignore a configured authorization policy.
		p.invalid = len(configs) != 0
		return p
	}
	if len(configs) == 0 {
		p.invalid = true
		return p
	}
	authOwners := map[string]string{}
	for name, cfg := range configs {
		if strings.TrimSpace(name) == "" || len(cfg.AuthIDs) == 0 || len(cfg.KeyScopes) == 0 {
			p.invalid = true
			return p
		}
		g := &accountGroup{name: name, auths: map[string]bool{}}
		for _, auth := range cfg.AuthIDs {
			if auth == "" || strings.TrimSpace(auth) != auth || g.auths[auth] || authOwners[auth] != "" {
				p.invalid = true
				return p
			}
			g.auths[auth] = true
			authOwners[auth] = name
		}
		for _, scope := range cfg.KeyScopes {
			decoded, err := hex.DecodeString(scope)
			if err != nil || len(decoded) != sha256.Size || strings.ToLower(scope) != scope || p.byScope[scope] != nil {
				p.invalid = true
				return p
			}
			p.byScope[scope] = g
		}
		p.groups++
	}
	return p
}

// Called with the limiter lock held. An absent or invalid group fails closed.
func (l *limiter) groupFor(scope string) (*accountGroup, string, int) {
	if l.groups.invalid {
		return nil, "account_group_config_invalid", 503
	}
	if !l.groups.enabled {
		return nil, "", 0
	}
	g := l.groups.byScope[scope]
	if g == nil {
		return nil, "api_key_group_unassigned", 403
	}
	return g, "", 0
}

func groupTerminate(code string, status int) obj {
	typ := "permission_error"
	if status >= 500 {
		typ = "api_error"
	}
	b, _ := json.Marshal(obj{"error": obj{"type": typ, "code": code, "message": code}})
	return ok(obj{"Terminate": true, "StatusCode": status, "ClearHeaders": []string{leaseHeader},
		"ResponseHeaders": http.Header{"Content-Type": {"application/json"}}, "ResponseBody": b})
}

func (l *limiter) groupCandidates(r pickRequest) (pickRequest, string, int) {
	g, code, status := l.groupFor(str(r.Options.Metadata, "caller_scope"))
	if code != "" || g == nil {
		return r, code, status
	}
	filtered := make([]candidate, 0, len(r.Candidates))
	for _, c := range r.Candidates {
		if g.auths[c.ID] && c.Provider == "claude" {
			filtered = append(filtered, c)
		}
	}
	r.Candidates = filtered
	if len(filtered) == 0 {
		return r, "account_group_unavailable", 503
	}
	return r, "", 0
}

func (l *limiter) scopedSessionID(r pickRequest) string {
	sid := sessionID(r)
	if sid == "" || !l.groups.enabled {
		return sid
	}
	// Two tenants choosing identical client session IDs cannot share bindings.
	data, _ := json.Marshal([]string{str(r.Options.Metadata, "caller_scope"), sid})
	h := sha256.Sum256(data)
	return "group-session:" + hex.EncodeToString(h[:])
}
