package main

import (
	"futurealgorithm/sessiontrader/internal/strategy"
	"math"
	"testing"
)

// auditStepDayR2 は既知の人工支持と原板だけを第二巡状態へ入力します。
//
// 引数: t(*testing.T)、r(*DayResult164R2)、o(Observation)、s([]Signal)、side/desired(int)、recover(bool)。返り値: なし。
func auditStepDayR2(t *testing.T, r *DayResult164R2, o strategy.Observation, s []strategy.Signal, side, desired int, recover bool) {
	t.Helper()
	x, y := .2, 2.
	if recover { x = 3 }
	short := shortCase164(float64(side)*x, float64(side)*y)
	supports := supportPair157(1, float64(desired-10)/90, side)
	if e := stepDay164R2(r, o, s, supports, short); e != nil { t.Fatal(e) }
}

// TestIndependentR2DelayedQuantityBound は買売と待機中の増減を変え当初希望上限を独立算式で照合します。
//
// 引数: t(*testing.T)。返り値: なし。実資料・金融再生は使いません。
func TestIndependentR2DelayedQuantityBound(t *testing.T) {
	for _, side := range []int{1,-1} {
		for _, q0 := range []int{10,25,50,100} {
			for _, now := range []int{10,25,88,100} {
				for _, add := range []int{0,2,5} {
					for _, closed := range []int{0,2,4} {
						r := r2CaseDay164(1)
						o := sample157(0,100,999,1001)
						auditStepDayR2(t,r,o,[]strategy.Signal{newSignal157("initial","core",1,side,5,o)},side,q0,false)
						cap := r.Caps["core/1"]
						if cap == nil { t.Fatal("初回上限なし") }
						o = sample157(1,105,989,991)
						s := []strategy.Signal{}
						if closed > 0 { c:=closeSignalDay164("partial","initial",closed,o); c.Side=-side; s=append(s,c) }
						if add > 0 { s=append(s,newSignal157("source_add","core",1,side,add,o)) }
						auditStepDayR2(t,r,o,s,side,now,false)
						p := r.Parents["core/1"]
						current := r.Base.desired157(supportPair157(1,float64(now-10)/90,side)[side])
						bound := min(cap.OriginalDesired,current)
						want := bound*min(p.SourceQty,p.SourcePeak)/p.SourcePeak
						auditStepDayR2(t,r,sample157(2,110,999,1001),nil,side,now,true)
						n := 0
						for _, order := range r.Actual.Pending { if len(order.Targets)==0 { n+=order.Quantity } }
						if n != want || n>cap.OriginalDesired || n*cap.NativeInitial>cap.OriginalDesired*p.SourceQty { t.Fatalf("数量式: side=%d q0=%d now=%d add=%d close=%d got=%d want=%d",side,q0,now,add,closed,n,want) }
						if p.Factor > float64(cap.OriginalDesired)/float64(cap.NativeInitial)+1e-12 { t.Fatal("後続係数膨張") }
						if r.Caps[p.Key].CapturedIndex!=0 || math.Abs(r.Caps[p.Key].CapturedAt-100)>1e-9 { t.Fatal("上限を後付で更新") }
					}
				}
			}
		}
	}
}

// TestIndependentR2UnknownDoesNotDelay は未知の短期変化を待機理由にしないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentR2UnknownDoesNotDelay(t *testing.T) {
	for _, side := range []int{1,-1} {
		r := r2CaseDay164(1)
		o := sample157(0,100,999,1001)
		supports := supportPair157(1,15./90.,side)
		if e := stepDay164R2(r,o,[]strategy.Signal{newSignal157("a","core",1,side,5,o)},supports,Short164{}); e!=nil { t.Fatal(e) }
		if len(r.Actual.Pending)!=1 || r.Actual.Pending[0].Quantity!=25 || len(r.Caps)!=0 { t.Fatal("未知を失速・上限記録へ転用") }
	}
}

// TestIndependentR2DeadSourceCannotRelease は元初回の全返済後に同じIDを再加速で復活しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentR2DeadSourceCannotRelease(t *testing.T) {
	for _, side := range []int{1,-1} {
		r:=r2CaseDay164(1)
		o:=sample157(0,100,999,1001)
		auditStepDayR2(t,r,o,[]strategy.Signal{newSignal157("a","core",1,side,5,o)},side,25,false)
		o=sample157(1,105,999,1001)
		c:=closeSignalDay164("end","a",5,o); c.Side=-side
		auditStepDayR2(t,r,o,[]strategy.Signal{c},side,100,true)
		auditStepDayR2(t,r,sample157(2,106,1029,1031),nil,side,100,true)
		if len(r.Actual.Events)!=0 || len(r.Actual.Pending)!=0 || r.Parents["core/1"].SourceQty!=0 { t.Fatal("死亡SourceIDの復元") }
	}
}

// auditNightR2 は実データを使わない夜の状態と元通知を作ります。
//
// 引数: number(int)。返り値: *NightResult164R2。
func auditNightR2(number int) *NightResult164R2 {
	return newNight164R2(configsNight164R2()[number-4],Scene{Start:100,USOpen:10000,ForceClose:20000})
}

// auditNativeCloseR2 はSource ID・方向が正しい人工返済通知を作ります。
//
// 引数: id,target(string)、quantity,side(int)、o(Observation)。返り値: Signal。
func auditNativeCloseR2(id,target string, quantity,side int,o strategy.Observation) strategy.Signal {
	c:=closeSignalDay164(id,target,quantity,o); c.Owner="前半/core"; c.Side=-side; return c
}

// auditDoNightR2 は人工の一原行だけを処理します。
//
// 引数: t(*testing.T)、r(*NightResult164R2)、o(Observation)、signals([]Signal)、short(Short164)。返り値: なし。
func auditDoNightR2(t *testing.T,r *NightResult164R2,o strategy.Observation,signals []strategy.Signal,short Short164) {
	t.Helper(); if e:=r.stepNight164R2(o,signals,short); e!=nil { t.Fatal(e) }
}

// TestIndependentR2PartialEligibilityOrder は部分返済後に約定した新玉へ資格を先渡ししないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。同秒でも約定内順を区別します。
func TestIndependentR2PartialEligibilityOrder(t *testing.T) {
	r:=auditNightR2(5); o:=sample157(0,100,999,1001)
	auditDoNightR2(t,r,o,[]strategy.Signal{newSignal157("a","前半/core",1,1,5,o)},Short164{})
	auditDoNightR2(t,r,sample157(1,101,999,1001),nil,Short164{})
	o=sample157(2,102,1029,1031)
	auditDoNightR2(t,r,o,[]strategy.Signal{auditNativeCloseR2("partial","a",2,1,o),newSignal157("b","前半/core",1,1,2,o)},Short164{})
	auditDoNightR2(t,r,sample157(3,103,1030,1032),nil,Short164{})
	seen:=0
	for _,id:=range r.Actual.Active { l:=r.Actual.Lots[id]; s:=r.Lots[id]; seen++
		if l.SourceID=="a" && !s.ResidualEligible { t.Fatal("その時点の残玉資格なし") }
		if l.SourceID=="b" && s.ResidualEligible { t.Fatal("部分返済より後順の新玉が残玉資格を継承") }
	}
	if seen!=2 { t.Fatal("残玉検査の分母",seen) }
}

// TestIndependentR2FloorGapAndNoResurrection は起動床後の次板赤字と元返済による二重返済防止を検査します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentR2FloorGapAndNoResurrection(t *testing.T) {
	for _,side:=range []int{1,-1} {
		r:=auditNightR2(4)
		prices:=[][2]float64{{999,1001},{999,1001},{1031,1033},{1011,1013},{978,980},{978,980},{978,980}}
		for i,p:=range prices { if side<0 { p=[2]float64{2000-p[1],2000-p[0]} }; o:=sample157(int64(i),100+float64(i),p[0],p[1]); s:=[]strategy.Signal{}
			if i==0 { s=append(s,newSignal157("a","前半/core",1,side,5,o)) }
			if i==5 { s=append(s,auditNativeCloseR2("native_end","a",5,side,o)) }
			auditDoNightR2(t,r,o,s,Short164{})
		}
		if len(r.Actual.Events)!=2 || r.Actual.Realized!=-11500 || len(r.Actual.Active)>0 || len(r.Actual.Pending)>0 { t.Fatal("床を利益保証又は元返済で復活",side,r.Actual.Realized,len(r.Actual.Events)) }
	}
}

// TestIndependentR2CurrentActualRatio は元部分返済を保護後の現実残量へ比例配賦することを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestIndependentR2CurrentActualRatio(t *testing.T) {
	r:=auditNightR2(5); o:=sample157(0,100,999,1001)
	auditDoNightR2(t,r,o,[]strategy.Signal{newSignal157("a","前半/core",1,1,5,o)},Short164{})
	auditDoNightR2(t,r,sample157(1,101,999,1001),nil,Short164{})
	p:=r.Parents["前半/core/1"]; id:=r.Actual.Active[0]
	r.Actual.closeLot(&p.Base,sample157(1,101,999,1001),id,"人工の既実行保護",20,Support157{})
	auditDoNightR2(t,r,sample157(2,102,1029,1031),nil,Short164{})
	o=sample157(3,103,1029,1031)
	auditDoNightR2(t,r,o,[]strategy.Signal{auditNativeCloseR2("partial","a",2,1,o)},Short164{})
	if len(r.Actual.Pending)!=1 || r.Actual.Pending[0].Quantity!=12 { t.Fatal("30実残に元20/50を適用していない") }
	auditDoNightR2(t,r,sample157(4,104,1029,1031),nil,Short164{})
	o=sample157(5,105,1029,1031)
	auditDoNightR2(t,r,o,[]strategy.Signal{auditNativeCloseR2("end","a",3,1,o)},Short164{})
	if len(r.Actual.Pending)!=1 || r.Actual.Pending[0].Quantity!=18 { t.Fatal("元ID終了で実残全数を返さない") }
}
