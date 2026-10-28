package main

import (
 "futurealgorithm/sessiontrader/internal/strategy"
 "reflect"
 "testing"
)

// auditOpen1573 は人工Source初回を判断して次原行で約定させます。
//
// 引数: t(*testing.T)、id(string)、side(int)、strong(bool)。返り値: *PolicyResult157。
func auditOpen1573(t *testing.T,id string,side int,strong bool)*PolicyResult157 {
 t.Helper()
 r:=newPolicy157(policyBy157(id),Scene{Start:100,ForceClose:1e5})
 o:=sample157(0,100,60000,60002)
 var s map[int]Support157
 if strong{s=supportPair157(1,1,side)}
 if e:=step157(r,o,[]strategy.Signal{newSignal157("初回","core",0,side,5,o)},s);e!=nil{t.Fatal(e)}
 if e:=step157(r,sample157(1,101,60000,60002),nil,s);e!=nil{t.Fatal(e)}
 return r
}

// auditQuote1573 は指定した保有方向の清算価格を持つ人工気配を作ります。
//
// 引数: index(int64)、at/mark(float64)、side(int)。返り値: strategy.Observation。
func auditQuote1573(index int64,at,mark float64,side int)strategy.Observation {
 if side>0{return sample157(index,at,mark,mark+2)}
 return sample157(index,at,mark-2,mark)
}

// auditHedge1573 は元玉と逆玉を実約定させ、逆玉の利確試験を準備します。
//
// 引数: t(*testing.T)、id(string)、side(int)。返り値: 政策、逆玉ID、逆玉建値。
func auditHedge1573(t *testing.T,id string,side int)(*PolicyResult157,string,float64) {
 t.Helper();r:=auditOpen1573(t,id,side,false);p:=r.Parents["core/0"]
 o:=sample157(2,102,60000,60002)
 r.Canonical.open(p,o,"cover","人工逆玉",-side,10,Support157{})
 r.project157(o)
 if e:=step157(r,sample157(3,103,60000,60002),nil,nil);e!=nil{t.Fatal(e)}
 for id,l:=range r.Canonical.Lots{if l.Kind=="cover"&&l.Remaining>0{return r,id,l.Entry}}
 t.Fatal("逆玉なし");return nil,"",0
}

// TestAuditOldBaseHasNoNewExit1573 は全12案の元玉へ新固定出口が混入しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditOldBaseHasNoNewExit1573(t *testing.T) {
 for _,c:=range configs157(){for _,side:=range []int{-1,1}{
  r:=auditOpen1573(t,c.ID,side,true);p:=r.Parents["core/0"]
  base:=r.Canonical.Lots[r.Canonical.Active[0]].Entry
  // ----------------------------------------
  // 100枚で100pt逆行し親8万円も超えるが、旧Sourceは終了していません。
  if e:=step157(r,auditQuote1573(2,112,base-float64(side)*100,side),nil,nil);e!=nil{t.Fatal(e)}
  if len(r.Canonical.Pending)!=0||p.Blocked!=""{t.Fatalf("%s 旧出口へ固定防御が漏れた: %v",c.ID,r.Canonical.Pending)}
  // 100pt利益から50ptへ戻しても元玉の40pt追尾を作らない。
  if e:=step157(r,auditQuote1573(3,113,base+float64(side)*100,side),nil,nil);e!=nil{t.Fatal(e)}
  if e:=step157(r,auditQuote1573(4,114,base+float64(side)*50,side),nil,nil);e!=nil{t.Fatal(e)}
  if len(r.Canonical.Pending)!=0{t.Fatalf("%s 元玉へ利益追尾が漏れた",c.ID)}
 }}
}

// TestAuditCoverOnlyTrailAndNextQuoteLoss1573 は逆玉だけの追尾と判断後の価格飛び損失を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditCoverOnlyTrailAndNextQuoteLoss1573(t *testing.T) {
 for _,side:=range []int{-1,1}{
  r,id,entry:=auditHedge1573(t,"O08",side);p:=r.Parents["core/0"];base:=p.LastBasePrice
  if e:=step157(r,auditQuote1573(4,110,entry-float64(side)*100,-side),nil,nil);e!=nil{t.Fatal(e)}
  if len(r.Canonical.Pending)!=0{t.Fatal("順行中の即時返済")}
  if e:=step157(r,auditQuote1573(5,111,entry-float64(side)*55,-side),nil,nil);e!=nil{t.Fatal(e)}
  if len(r.Canonical.Pending)!=1||r.Canonical.Pending[0].Reason!="cover_trail"||r.Canonical.Pending[0].Targets[0].ID!=id{t.Fatal(r.Canonical.Pending)}
  if e:=step157(r,auditQuote1573(6,112,entry+float64(side)*60,-side),nil,nil);e!=nil{t.Fatal(e)}
  event:=r.Canonical.Events[len(r.Canonical.Events)-1]
  if event.Gross!=-6000{t.Fatal("次板の逆玉損失を消した",event.Gross)}
  if p.LastBasePrice!=base||p.RecoveryAllowed||p.Blocked!=""{t.Fatal("逆玉返済が元玉状態を変更",p)}
  l,s:=r.Canonical.position(p.Key,"base");if l+s!=10{t.Fatal("元玉まで閉じた")}
 }
}

// TestAuditSourceEndWinsOverCoverTrail1573 は元全終了と利確が重なっても源の返済を優先します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSourceEndWinsOverCoverTrail1573(t *testing.T) {
 r,_,entry:=auditHedge1573(t,"O08",1)
 if e:=step157(r,auditQuote1573(4,110,entry-100,-1),nil,nil);e!=nil{t.Fatal(e)}
 o:=auditQuote1573(5,111,entry-55,-1)
 source:=strategy.Signal{ID:"終了",Owner:"core",Campaign:0,Action:"close",Side:-1,Quantity:5,Time:o.Time,SourceIndex:o.Index}
 if e:=step157(r,o,[]strategy.Signal{source},nil);e!=nil{t.Fatal(e)}
 if len(r.Canonical.Pending)!=2{t.Fatal(r.Canonical.Pending)}
 for _,order:=range r.Canonical.Pending{if order.Reason!="source_end"{t.Fatal("源より追尾を優先",order)}}
 if e:=step157(r,auditQuote1573(6,112,entry,-1),nil,nil);e!=nil{t.Fatal(e)}
 l,s:=r.Canonical.position("core/0","");if l+s!=0||len(r.Canonical.Pending)!=0{t.Fatal("源終了後に逆玉を残した")}
}

// TestAuditCollapseUnknownResetAndSameParentBlock1573 は崩壊継続の不明リセットと同親停止を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditCollapseUnknownResetAndSameParentBlock1573(t *testing.T) {
 for _,side:=range []int{-1,1}{
  r:=auditOpen1573(t,"O10",side,false)
  bad:=map[int]Support157{side:{Known:true,M:0,Opp:.8,Own5:-float64(side),Own15:-float64(side)}}
  for i,at:=range []float64{110,120,130,140,154}{s:=bad;if at==130{s=nil};if e:=step157(r,sample157(int64(i+2),at,60000,60002),nil,s);e!=nil{t.Fatal(e)};if len(r.Canonical.Pending)!=0{t.Fatal("崩壊を15秒未満で確定",at)}}
  o:=sample157(7,155,60000,60002)
  if e:=step157(r,o,nil,bad);e!=nil{t.Fatal(e)}
  if len(r.Canonical.Pending)!=1||r.Canonical.Pending[0].Reason!="長短支持崩壊"{t.Fatal(r.Canonical.Pending)}
  o=sample157(8,156,60000,60002)
  if e:=step157(r,o,[]strategy.Signal{newSignal157("同親再追加","core",0,side,1,o)},supportPair157(1,1,side));e!=nil{t.Fatal(e)}
  if len(r.Canonical.Pending)!=0{t.Fatal("崩壊した同親へ再追加")}
 }
}

// TestAuditCollapseGapAndRestriction1573 は15秒超空白を継続へ足さず、対象外のO03へ崩壊を漏らしません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditCollapseGapAndRestriction1573(t *testing.T) {
 for _,id:=range []string{"O03","O10"}{
  r:=auditOpen1573(t,id,1,false);bad:=map[int]Support157{1:{Known:true,M:0,Opp:.8,Own5:-1,Own15:-1}}
  for i,at:=range []float64{110,126,140}{if e:=step157(r,sample157(int64(i+2),at,60000,60002),nil,bad);e!=nil{t.Fatal(e)};if len(r.Canonical.Pending)!=0{t.Fatal(id,at)}}
  if e:=step157(r,sample157(5,141,60000,60002),nil,bad);e!=nil{t.Fatal(e)}
  if (len(r.Canonical.Pending)>0)!=(id=="O10"){t.Fatal(id,r.Canonical.Pending)}
 }
}

// TestAuditDStopsBeforeSameRowSourceAdd1573 はDの損失停止を同原行の源追加より優先します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditDStopsBeforeSameRowSourceAdd1573(t *testing.T) {
 r:=auditOpen1573(t,"O09",1,true);o:=sample157(2,112,59800,59802)
 if e:=step157(r,o,[]strategy.Signal{newSignal157("追加","core",0,1,1,o)},supportPair157(1,1,1));e!=nil{t.Fatal(e)}
 if !r.Stopped||len(r.Canonical.Pending)!=1||len(r.Canonical.Pending[0].Targets)==0||r.Canonical.Pending[0].Quantity!=100{t.Fatal(r.Stopped,r.Canonical.Pending)}
}

// TestAuditHAndDPureConfiguration1573 はH/Dの対照から余分な条件差を排除します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditHAndDPureConfiguration1573(t *testing.T) {
 base:=policyBy157("O05");base.ID="";base.Control="";base.Description=""
 for _,id:=range []string{"O08","O09"}{p:=policyBy157(id);p.ID="";p.Control="";p.Description="";p.Hedge=false;p.SessionSave=false;if !reflect.DeepEqual(base,p){t.Fatal(id,base,p)}}
}
