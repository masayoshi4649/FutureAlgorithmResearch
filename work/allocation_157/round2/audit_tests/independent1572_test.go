package main

import (
 "futurealgorithm/sessiontrader/internal/strategy"
 "math"
 "testing"
)

// auditClose1572 は人工期待値の不一致を報告します。
//
// 引数: t(*testing.T)、got/want(float64)。返り値: なし。
func auditClose1572(t *testing.T, got, want float64) {
 t.Helper()
 if math.IsNaN(got)||math.IsInf(got,0)||math.Abs(got-want)>1e-8 {t.Fatalf("計算値=%v 期待=%v",got,want)}
}

// TestAuditPastNormalEndpoint1572 は異常過去端を飛ばし、未来の近い正常値を使用しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditPastNormalEndpoint1572(t *testing.T) {
 rows:=[]supportRow157{{Time:0,Mid:100,Valid:true},{Time:5,Mid:110,Valid:true},{Time:14,Valid:false,Bad:1},{Time:16,Mid:999,Valid:true,Bad:1},{Time:20,Mid:120,Valid:true,Bad:1}}
 w:=elapsedReturn1572(rows,4,5,true)
 if !w.Known||w.EndpointAt!=5||w.Elapsed!=15||w.Delay!=10||w.IntermediateBad!=1 {t.Fatal(w)}
 auditClose1572(t,w.RawReturn,10000*(120./110-1))
 auditClose1572(t,w.Value,10000*(120./110-1)/3)
 rows[3].Mid=1e9
 auditClose1572(t,elapsedReturn1572(rows,4,5,true).Value,w.Value)
}

// TestAuditEndpointFifteenSecondBoundary1572 は過去端遅れ15秒ちょうどと超過を分けます。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditEndpointFifteenSecondBoundary1572(t *testing.T) {
 rows:=[]supportRow157{{Time:0,Mid:100,Valid:true},{Time:20,Mid:120,Valid:true}}
 w:=elapsedReturn1572(rows,1,5,true)
 if !w.Known||w.Delay!=15 {t.Fatal(w)}
 auditClose1572(t,w.Value,500)
 rows[1].Time=20.001
 if elapsedReturn1572(rows,1,5,true).Known {t.Fatal("15秒を超える端を採用")}
}

// TestAuditLongWindowKeepsPriceRatio1572 は長い窓だけを速度へ正規化しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditLongWindowKeepsPriceRatio1572(t *testing.T) {
 for _,h:=range []float64{120,300} {
  rows:=[]supportRow157{{Time:0,Mid:100,Valid:true},{Time:h+15,Mid:102,Valid:true}}
  w:=elapsedReturn1572(rows,1,h,false)
  if !w.Known||w.Elapsed!=h+15 {t.Fatal(w)}
  auditClose1572(t,w.Value,200)
 }
}

// auditPriceBuilder1572 は補助が欠測しても自己価格が揃う人工系列を作ります。
//
// 引数: side(int)。返り値: *SupportBuilder157。
func auditPriceBuilder1572(side int)*SupportBuilder157 {
 b:=&SupportBuilder157{}
 for i:=0;i<=400;i++ {p:=60000+float64(side*i*10);q:=10.;if i==400 {q=0};b.add(strategy.Board{Reference:"NK225",Time:float64(i),Bid:p,Ask:p+10,BidQuantity:q,AskQuantity:q})}
 return b
}

// TestAuditMissingAuxiliaryIsNotRenormalized1572 は相手・OFI欠測時にも重みを増幅しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditMissingAuxiliaryIsNotRenormalized1572(t *testing.T) {
 for _,side:=range []int{-1,1} {
  b:=auditPriceBuilder1572(side);s:=b.get(400,side)
  if !s.Known||!s.Components.OwnKnown||s.Components.PeerKnown||s.Components.OFIKnown {t.Fatal(s)}
  auditClose1572(t,s.M,.8);auditClose1572(t,s.T,.8);auditClose1572(t,s.Peer120,0);auditClose1572(t,s.OFI30,0)
 }
}

// TestAuditCurrentInvalidStillUnknown1572 は途中の異常許容が現在板の異常許容にならないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditCurrentInvalidStillUnknown1572(t *testing.T) {
 b:=auditPriceBuilder1572(1)
 b.add(strategy.Board{Reference:"NK225",Time:401,Bid:100,Ask:100,BidQuantity:10,AskQuantity:10})
 if b.get(401,1).Known {t.Fatal("交差した現在板を採用")}
}

// TestAuditSameSecondPeerCannotLeak1572 は自己時刻と同秒以後の相手板が支持へ混入しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSameSecondPeerCannotLeak1572(t *testing.T) {
 b:=auditPriceBuilder1572(1)
 for i:=0;i<=400;i++ {p:=4000+float64(i);if i==400 {p=1e9};b.add(strategy.Board{Reference:"TOPIX",Time:float64(i),Bid:p,Ask:p+1,BidQuantity:10,AskQuantity:10})}
 s:=b.get(400,1)
 if !s.Components.PeerKnown||s.PeerAt!=399 {t.Fatal(s)}
 auditClose1572(t,s.Peer120,10000*((4399.5/4279.5)-1))
 b.add(strategy.Board{Reference:"TOPIX",Time:401,Bid:1e12,Ask:1e12+1,BidQuantity:10,AskQuantity:10})
 auditClose1572(t,b.get(400,1).Peer120,s.Peer120)
}

// TestAuditMinimumIsScaledAndUnknownUsesMinimum1572 は最低数量も場内抑制対象であり、未知の残存値を無視することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditMinimumIsScaledAndUnknownUsesMinimum1572(t *testing.T) {
 r:=newPolicy157(policyBy157("J13"),Scene{Start:0,ForceClose:1e5})
 unknown:=Support157{Known:false,M:1,T:1}
 if q:=r.desired157(unknown);q!=10 {t.Fatal(q)}
 r.Canonical.Last.Equity=-120000
 if q:=r.desired157(unknown);q!=5 {t.Fatal(q)}
 r.Canonical.Last.Equity=-159999
 if q:=r.desired157(unknown);q!=0 {t.Fatal(q)}
 r.Canonical.Last.Equity=-160000
 if q:=r.desired157(Support157{Known:true,M:1,T:1});q!=0 {t.Fatal(q)}
}

// TestAuditFixedTenAndLinearInitial1572 は固定数量対照と弱支持可変数量を区別します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditFixedTenAndLinearInitial1572(t *testing.T) {
 fixed:=newPolicy157(policyBy157("K01"),Scene{})
 for _,s:=range []Support157{{Known:false},{Known:true,M:1,T:1},{Known:true,M:.5,T:.5}} {if fixed.desired157(s)!=10 {t.Fatal("固定量が支持に依存")}}
 linear:=newPolicy157(policyBy157("J02"),Scene{})
 if linear.desired157(Support157{Known:true,M:.5,T:.5})!=32 {t.Fatal("最低量を含む線形量")}
 square:=newPolicy157(policyBy157("J15"),Scene{})
 if square.desired157(Support157{Known:true,M:.5,T:.5})!=15 {t.Fatal("二乗量")}
}

// TestAuditUnknownSourceAddKeepsInitialFactor1572 は元通知の追加を現在の未知支持で再選抜しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditUnknownSourceAddKeepsInitialFactor1572(t *testing.T) {
 for _,side:=range []int{-1,1} {
  r:=newPolicy157(policyBy157("J02"),Scene{Start:100,ForceClose:1e5})
  o:=sample157(0,100,1000,1002)
  if e:=step157(r,o,[]strategy.Signal{newSignal157("初回","core",0,side,5,o)},supportPair157(.5,.5,side));e!=nil {t.Fatal(e)}
  if len(r.Canonical.Pending)!=1||r.Canonical.Pending[0].Quantity!=32 {t.Fatal(r.Canonical.Pending)}
  o=sample157(1,101,1000,1002)
  if e:=step157(r,o,[]strategy.Signal{newSignal157("追加","core",0,side,1,o)},map[int]Support157{});e!=nil {t.Fatal(e)}
  if len(r.Canonical.Pending)!=1||r.Canonical.Pending[0].Quantity!=6||r.Canonical.Pending[0].Kind!="source_add" {t.Fatal(r.Canonical.Pending)}
 }
}
