package main

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"futurealgorithm/sessiontrader/internal/strategy"
)

// auditScene149 は保存市場を使わず、人工確定足だけの研究場を作ります。
//
// 引数: t(*testing.T)、pastChange(bool)は米国開始前の全足の改変指定です。
// 返り値: Sceneは一時領域だけを参照する人工場です。
func auditScene149(t *testing.T, pastChange bool) Scene {
	t.Helper()
	start := float64(time.Date(2026, 1, 5, 17, 0, 0, 0, time.FixedZone("JST", 9*3600)).Unix())
	scene := Scene{Session: "人工_Night", Start: start, USOpen: start + 3600, ForceClose: start + 7100, End: start + 7200, Partial: true, Candles: map[string]map[string]string{}}
	dir := t.TempDir()
	for _, ref := range []string{"NK225", "TOPIX"} {
		scene.Candles[ref] = map[string]string{}
		base := 60000.
		if ref == "TOPIX" {
			base = 4000
		}
		for _, interval := range []int{60, 300} {
			rows := []map[string]any{}
			for elapsed := 0; elapsed < 7200; elapsed += interval {
				price := base + 10*math.Sin(float64(elapsed)/240)
				if pastChange && elapsed < 3600 {
					price += 777
				}
				rows = append(rows, map[string]any{"time": time.Unix(int64(start)+int64(elapsed), 0).UTC().Format(time.RFC3339), "open": price, "high": price + 12, "low": price - 12, "close": price + 1, "closed": true})
			}
			raw, err := json.Marshal(map[string]any{"data": rows})
			if err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(dir, fmt.Sprintf("%s_%d.json", ref, interval))
			if err = os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
			scene.Candles[ref][fmt.Sprint(interval)] = path
		}
	}
	return scene
}

// auditBoard149 は価格を滑らかに変えた人工板を返します。
//
// 引数: ref(string)、at/start(float64)は市場と原時計です。
// 返り値: strategy.Boardは正の数量と正常気配を持つ一行です。
func auditBoard149(ref string, at, start float64) strategy.Board {
	base, tick := 60000., 10.
	if ref == "TOPIX" {
		base, tick = 4000, .5
	}
	price := base + tick*math.Floor(3*math.Sin((at-start)/150))
	b := strategy.Board{Reference: ref, Time: at, Received: at, Last: price, Bid: price - tick, Ask: price + tick, BidQuantity: 20, AskQuantity: 25}
	for i := 0; i < 10; i++ {
		b.BidLevels[i] = strategy.ResearchLevel{Price: b.Bid - float64(i)*tick, Quantity: float64(20 + i)}
		b.AskLevels[i] = strategy.ResearchLevel{Price: b.Ask + float64(i)*tick, Quantity: float64(25 + i)}
	}
	return b
}

// TestAudit149CandlePrefix は未来足の存在が過去の観測を変えないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。保存市場・金融再生は使いません。
func TestAudit149CandlePrefix(t *testing.T) {
	scene := auditScene149(t, false)
	short := scene
	short.Cutoff = scene.Start + 45*60
	full, err := newFeatures(scene, scene.Start)
	if err != nil {
		t.Fatal(err)
	}
	prefix, err := newFeatures(short, scene.Start)
	if err != nil {
		t.Fatal(err)
	}
	for elapsed := 0.; elapsed < 45*60; elapsed += 10 {
		for _, ref := range []string{"TOPIX", "NK225"} {
			board := auditBoard149(ref, scene.Start+elapsed, scene.Start)
			a, e := full.OnBoard(board)
			if e != nil {
				t.Fatal(e)
			}
			b, e := prefix.OnBoard(board)
			if e != nil {
				t.Fatal(e)
			}
			if !reflect.DeepEqual(a, b) {
				t.Fatalf("未来足が過去観測へ混入: %s %.0f秒", ref, elapsed)
			}
		}
	}
}

// TestAudit149ResetExcludesPreUS はUS前の足を全変更しても後半特徴が不変か検査します。
//
// 引数: t(*testing.T)。返り値: なし。US後の始値・ATR・40分帯も比較します。
func TestAudit149ResetExcludesPreUS(t *testing.T) {
	scene, changed := auditScene149(t, false), auditScene149(t, true)
	a, err := newFeatures(scene, scene.USOpen)
	if err != nil {
		t.Fatal(err)
	}
	b, err := newFeatures(changed, changed.USOpen)
	if err != nil {
		t.Fatal(err)
	}
	for elapsed := 0.; elapsed < 55*60; elapsed += 10 {
		for _, ref := range []string{"TOPIX", "NK225"} {
			board := auditBoard149(ref, scene.USOpen+elapsed, scene.USOpen)
			x, e := a.OnBoard(board)
			if e != nil {
				t.Fatal(e)
			}
			y, e := b.OnBoard(board)
			if e != nil {
				t.Fatal(e)
			}
			if !reflect.DeepEqual(x, y) {
				t.Fatalf("US前足が後半観測へ混入: %s %.0f秒", ref, elapsed)
			}
		}
	}
	if a.OpeningLast["NK225"] != 60000 || a.OpeningLast["TOPIX"] != 4000 {
		t.Fatal("始値がUS開始時に作り直されていない")
	}
}

// TestAudit149PeerSameClock は相手同時計の先処理が研究入力へ混ざらないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。最終相手板だけ異なる人工の二順序を比較します。
func TestAudit149PeerSameClock(t *testing.T) {
	scene := auditScene149(t, false)
	a, err := newFeatures(scene, scene.Start)
	if err != nil {
		t.Fatal(err)
	}
	b, err := newFeatures(scene, scene.Start)
	if err != nil {
		t.Fatal(err)
	}
	for elapsed := 0.; elapsed < 50*60; elapsed += 10 {
		for _, ref := range []string{"TOPIX", "NK225"} {
			board := auditBoard149(ref, scene.Start+elapsed, scene.Start)
			if _, err = a.OnBoard(board); err != nil {
				t.Fatal(err)
			}
			if _, err = b.OnBoard(board); err != nil {
				t.Fatal(err)
			}
		}
	}
	at := scene.Start + 50*60
	peer := auditBoard149("TOPIX", at, scene.Start)
	peer.Last, peer.Bid, peer.Ask = 9000, 8999, 9001
	if _, err = a.OnBoard(peer); err != nil {
		t.Fatal(err)
	}
	x, err := a.OnBoard(auditBoard149("NK225", at, scene.Start))
	if err != nil {
		t.Fatal(err)
	}
	y, err := b.OnBoard(auditBoard149("NK225", at, scene.Start))
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(x.Research, y.Research) || !reflect.DeepEqual(x.MidMarket, y.MidMarket) || !reflect.DeepEqual(x.LastMarket, y.LastMarket) {
		t.Fatal("同時計相手の先処理が研究特徴へ混入")
	}
}

// TestAudit149PendingEntryCrossesReset は境界前に送信済みの成行を消さず返済することを検査します。
//
// 引数: t(*testing.T)。返り値: なし。人工の入口準備状態から実際の発注予約を生成します。
func TestAudit149PendingEntryCrossesReset(t *testing.T) {
	scene, expressions := testSetup(t)
	cfg := StudyConfig{Reset: true, CoreHour: 17, ExtraHour: 17, CloseBeforeMinutes: 15, RestartWaitMinutes: 15, Owners: []string{"core"}}
	p, from, end, err := newPortfolio(scene, cfg, false, expressions)
	if err != nil {
		t.Fatal(err)
	}
	arm := &p.Research.Sleeves[0].Source.Legacy.Core.Arm
	arm.Side, arm.Stage = 1, 2
	arm.Level, arm.Risk, arm.At, arm.ReturnExtreme = 65000, 100, end-120, 65000
	arm.ReturnIndex = 0
	c := &Case{Config: cfg, P: p, Phase: "前半", EntryFrom: from, End: end, Positions: map[string]Lot{}, Parents: map[string]float64{}, Diagnostics: map[string]map[string]int{}, FirstFeatureKnown: map[string]float64{}}
	o := strategy.Observation{Reference: "NK225", Time: end - 1, Received: end - 1, Index: 1, Bid: 65030, Ask: 65040, Last: 65030, QuoteOK: true, ATR: 100}
	o.MidMarket = strategy.Market{Known: true, Own30Known: true, Peer30Known: true, Own120Known: true, Peer120Known: true, Own30: .5, Peer30: .5, Own120: .5, Peer120: .5, OwnATR: 100, PeerATR: 1}
	o.MidHistory.Known = true
	o.MidHistory.Values[10], o.MidHistory.Values[11] = 100, 100
	if err = process(c, o); err != nil {
		t.Fatal(err)
	}
	if len(c.Events) != 0 || len(c.Pending) != 1 || c.Pending[0].Action != "new" || flat(c.P) {
		t.Fatal("境界前の人工新規が予約されない", c.Pending)
	}
	// ----------------------------------------
	// 境界の異常板では約定せず、米国開始まで未解消状態を維持する。
	o.Time, o.Received, o.Index, o.QuoteOK = end, end, 2, false
	if err = process(c, o); err != nil {
		t.Fatal(err)
	}
	if len(c.Events) != 0 || len(c.Pending) != 1 || flat(c.P) {
		t.Fatal("異常板を理由に送信済み新規を取消した")
	}
	// ----------------------------------------
	// 米国開始後の最初の正常板で新規を約定し、その行で返済を判断する。
	o.Time, o.Received, o.Index, o.QuoteOK = scene.USOpen+1, scene.USOpen+1, 3, true
	o.Bid, o.Ask, o.Last = 65050, 65060, 65050
	if err = process(c, o); err != nil {
		t.Fatal(err)
	}
	if len(c.Events) != 1 || c.Events[0].Signal.Action != "new" || c.Events[0].Fill.Price != 65060 || len(c.Pending) != 1 || c.Pending[0].Action != "close" || flat(c.P) {
		t.Fatal("境界越え新規の約定と次行返済予約が不一致", c.Events, c.Pending)
	}
	o.Time, o.Received, o.Index = scene.USOpen+2, scene.USOpen+2, 4
	o.Bid, o.Ask, o.Last = 65030, 65040, 65030
	if err = process(c, o); err != nil {
		t.Fatal(err)
	}
	if len(c.Events) != 2 || c.Events[1].Fill.Price != 65030 || c.Gross != -15000 || !flat(c.P) {
		t.Fatal("次正常板での全返済又は損失計上が不一致", c.Events, c.Gross)
	}
}
