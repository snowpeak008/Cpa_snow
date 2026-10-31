package main

import (
 "fmt"
 "strings"
 "testing"
)

func TestKeyOverrideHundredWithFivePerAccount(t *testing.T) {
 l:=newLimiter(); owner:=strings.Repeat("a",64); other:=strings.Repeat("b",64)
 config:="max_per_key: 5\nkey_limits:\n  "+owner+": 100\naccount_limits:\n"
 candidates:=[]candidate{}
 for i:=0;i<20;i++ { a:=fmt.Sprintf("A%02d",i);config+="  "+a+": 5\n";candidates=append(candidates,candidate{ID:a}) }
 configureLimits(t,l,config)
 for i:=0;i<100;i++ { id:=fmt.Sprint(i);if result(l.before(beforeReq(id,owner)))["Terminate"]==true {t.Fatalf("request %d rejected early",i)};r:=pickReq(id,owner);r.Candidates=append([]candidate{},candidates...);if result(l.pick(r))["AuthID"]==nil {t.Fatalf("pick %d rejected early",i)} }
 if result(l.before(beforeReq("101",owner)))["StatusCode"]!=429 {t.Fatal("101st request was admitted")}
 for _,a:=range candidates {if len(l.owners[a.ID])!=5 {t.Fatalf("account %s has %d reservations",a.ID,len(l.owners[a.ID]))}}
 for i:=0;i<5;i++ {if result(l.before(beforeReq(fmt.Sprint("other",i),other)))["Terminate"]==true {t.Fatal("other Key rejected early")}}
 if result(l.before(beforeReq("other6",other)))["StatusCode"]!=429 {t.Fatal("other Key default exceeded five")}
 if pickOnly(l,"other0",other,candidates[0].ID,"")["ok"]!=false {t.Fatal("account exceeded five across Keys")}
 l.complete("0")
 if result(l.before(beforeReq("replacement",owner)))["Terminate"]==true {t.Fatal("released Key slot not usable")}
 r:=pickReq("replacement",owner);r.Candidates=append([]candidate{},candidates...)
 if result(l.pick(r))["AuthID"]==nil {t.Fatal("released account slot not usable")}
}

func TestKeyOverrideHundredFollowsFifteenAccountCapacity(t *testing.T) {
 l:=newLimiter();owner:=strings.Repeat("a",64)
 config:="key_limits:\n  "+owner+": 100\naccount_limits:\n";candidates:=[]candidate{}
 for i:=0;i<15;i++ {a:=fmt.Sprintf("A%02d",i);config+="  "+a+": 5\n";candidates=append(candidates,candidate{ID:a})}
 configureLimits(t,l,config)
 for i:=0;i<75;i++ {id:=fmt.Sprint(i);l.before(beforeReq(id,owner));r:=pickReq(id,owner);r.Candidates=append([]candidate{},candidates...);if result(l.pick(r))["AuthID"]==nil {t.Fatal("rejected before total capacity",i)}}
 l.before(beforeReq("76",owner));r:=pickReq("76",owner);r.Candidates=append([]candidate{},candidates...)
 if l.pick(r)["ok"]!=false {t.Fatal("15 accounts exceeded 75 total slots")}
 l.complete("76")
}
