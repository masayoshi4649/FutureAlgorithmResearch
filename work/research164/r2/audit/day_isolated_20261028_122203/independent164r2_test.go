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
						if closed > 0 { s=append(s,closeSignalDay164("partial","initial",closed,o)) }
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
		auditStepDayR2(t,r,o,[]strategy.Signal{closeSignalDay164("end","a",5,o)},side,100,true)
		auditStepDayR2(t,r,sample157(2,106,1029,1031),nil,side,100,true)
		if len(r.Actual.Events)!=0 || len(r.Actual.Pending)!=0 || r.Parents["core/1"].SourceQty!=0 { t.Fatal("死亡SourceIDの復元") }
	}
}
