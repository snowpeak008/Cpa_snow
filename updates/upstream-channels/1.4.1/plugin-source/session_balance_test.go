package main

import (
 "fmt"
 "testing"
 "time"
)

func TestBalancedSequentialNewSessionsKeepCountsWithinOne(t *testing.T) {
 l:=newLimiter()
 for i:=0;i<40;i++ {
  id:=fmt.Sprint(i);mustSessionPick(t,l,id,"k","conversation-"+id);l.complete(id)
  counts:=l.sessionLoads();lo,hi:=40,0
  for j:=0;j<5;j++ {n:=counts[fmt.Sprint(j)];if n<lo {lo=n};if n>hi {hi=n}}
  if hi-lo>1 {t.Fatalf("imbalanced at step %d: %v",i,counts)}
 }
 if len(l.sessions)!=40 || len(l.owners)!=0 {t.Fatal("sessions confused with requests")}
}
func TestBalancedBindingCountOutranksInstantRequestLoad(t *testing.T) {
 l:=newLimiter();now:=time.Now();l.sessions["oldA1"]=&sessionBinding{AuthID:"A",Expire:now.Add(sessionTTL)};l.sessions["oldA2"]=&sessionBinding{AuthID:"A",Expire:now.Add(sessionTTL)};l.sessions["oldB"]=&sessionBinding{AuthID:"B",Expire:now.Add(sessionTTL)}
 l.before(beforeReq("held","k"));p:=pickReq("held","k");p.Candidates=[]candidate{{ID:"B"}};l.pick(p)
 l.before(beforeReq("new","k"));p=sessionPickReq("new","k","newsession");p.Candidates=[]candidate{{ID:"A"},{ID:"B"}}
 if result(l.pick(p))["AuthID"]!="B" {t.Fatal("instantaneous load overrode fewer active conversations")}
}
func TestBalancedBoundConversationStaysDespiteOtherIdleAccounts(t *testing.T) {
 l:=newLimiter();a:=mustSessionPick(t,l,"first","k","s1");l.complete("first")
 for i:=0;i<3;i++ {l.sessions[fmt.Sprint("extra",i)]=&sessionBinding{AuthID:a,Expire:time.Now().Add(sessionTTL)}}
 if b:=mustSessionPick(t,l,"again","k","s1");a!=b {t.Fatal("existing conversation was load-balanced away")}
}
func TestBalancedOnlyCPACandidatesParticipate(t *testing.T) {
 l:=newLimiter();l.sessions["onA"]=&sessionBinding{AuthID:"A",Expire:time.Now().Add(sessionTTL)}
 l.before(beforeReq("x","k"));p:=sessionPickReq("x","k","new");p.Candidates=[]candidate{{ID:"B"},{ID:"C"}}
 if a:=result(l.pick(p))["AuthID"];a!="B" && a!="C" {t.Fatal("selected excluded credential",a)}
}
func TestBalancedExpiryFreesSessionCapacity(t *testing.T) {
 l:=newLimiter();now:=time.Now();l.sessions["expiredA"]=&sessionBinding{AuthID:"A",Expire:now.Add(-time.Second)};l.sessions["onB"]=&sessionBinding{AuthID:"B",Expire:now.Add(sessionTTL)};l.last="A"
 l.before(beforeReq("x","k"));p:=sessionPickReq("x","k","new");p.Candidates=[]candidate{{ID:"A"},{ID:"B"}}
 if result(l.pick(p))["AuthID"]!="A" || l.sessions["expiredA"]!=nil {t.Fatal("expired session still counted")}
}
func TestBalancedInFlightSessionDoesNotExpire(t *testing.T) {
 l:=newLimiter();a:=mustSessionPick(t,l,"x","k","s");l.sessions["s"].Expire=time.Now().Add(-time.Second)
 l.pruneSessions(time.Now());if l.sessions["s"]==nil {t.Fatal("in-flight session expired")}
 l.complete("x");if l.sessions["s"]==nil || l.sessions["s"].AuthID!=a || !l.sessions["s"].Expire.After(time.Now()) {t.Fatal("completion did not start idle TTL")}
}
func TestBalancedSnapshotReportsSessionsSeparately(t *testing.T) {
 l:=newLimiter();mustSessionPick(t,l,"a","k","s1");l.complete("a");mustSessionPick(t,l,"b","k","s2")
 s:=l.snapshot();if s["active_sessions"]!=2 || s["active_requests"]!=1 || s["routing_policy"]!="least-active-sessions-sticky" {t.Fatal("incorrect counters",s)}
}
func TestBalancedRetryReusesOwnFullReservation(t *testing.T) {
 l,_:=fullSessionAccount(t);r:=l.pick(sessionPickReq("first","k","claude:s1"))
 if result(r)["AuthID"]==nil {t.Fatal("retry rejected its own reserved slot",r)}
}
func TestBalancedFailedReplacementKeepsOriginalBinding(t *testing.T) {
 l:=newLimiter();l.lookupAccount=func(string)accountState{return accountUnknown};a:=mustSessionPick(t,l,"first","k","s");l.complete("first")
 l.before(beforeReq("next","k"));p:=sessionPickReq("next","k","s");p.Candidates=nil
 if l.pick(p)["ok"]!=false || l.sessions["s"].AuthID!=a {t.Fatal("unavailable replacement destroyed original binding")}
}

func TestBalancedIdenticalConfigReloadPreservesBindings(t *testing.T) {
 l:=newLimiter();cfg:="max_per_key: 5\naccount_limits:\n  A: 5\n";configureLimits(t,l,cfg)
 l.before(beforeReq("first","k"));r:=sessionPickReq("first","k","s");r.Candidates=[]candidate{{ID:"A"}};l.pick(r);l.complete("first")
 original:=l.sessions["s"];configureLimits(t,l,cfg)
 if original==nil || l.sessions["s"]!=original {t.Fatal("identical config reload erased binding")}
 l.before(beforeReq("next","k"));r=sessionPickReq("next","k","s");r.Candidates=[]candidate{{ID:"A"},{ID:"B"}}
 if result(l.pick(r))["AuthID"]!="A" {t.Fatal("reload migrated existing conversation")}
 // Changed tenant membership must still invalidate old scoped authorization bindings.
 configureLimits(t,l,"enforce_account_groups: true\naccount_groups:\n  changed:\n    auth_ids: [B]\n    key_scopes: ["+fmt.Sprintf("%064x",1)+"]\n")
 if len(l.sessions)!=0 {t.Fatal("changed authorization policy retained old bindings")}
}
