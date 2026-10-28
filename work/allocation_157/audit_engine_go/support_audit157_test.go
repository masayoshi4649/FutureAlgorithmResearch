package main

import (
	"math"
	"reflect"
	"testing"

	"futurealgorithm/sessiontrader/internal/strategy"
)

// auditBoard157 は支持の人工検査用に正常な板を作成します。
//
// 引数: reference(string)、at/bid(float64)。返り値: strategy.Board。
func auditBoard157(reference string, at, bid float64) strategy.Board {
	return strategy.Board{Reference: reference, Time: at, Received: at, Bid: bid, Ask: bid + 10, Last: bid + 5, BidQuantity: 10, AskQuantity: 10}
}

// auditSupport157 は400秒までの人工二市場系列を作成します。
//
// 引数: なし。返り値: *SupportBuilder157。実データは読みません。
func auditSupport157() *SupportBuilder157 {
	f := &SupportBuilder157{}
	for at := 0.0; at <= 400; at++ {
		f.add(auditBoard157("TOPIX", at, 4000+at/10))
		f.add(auditBoard157("NK225", at, 60000+at*10))
	}
	return f
}

// TestAuditSupportFuturePeer157 は同秒・未来相手板が支持へ混入しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSupportFuturePeer157(t *testing.T) {
	f := auditSupport157()
	before := f.get(400, 1)
	if !before.Known || before.PeerAt != 399 {
		t.Fatalf("人工正常支持が未知又は同秒相手使用: %+v", before)
	}
	f.add(auditBoard157("TOPIX", 400, 9000))
	f.add(auditBoard157("TOPIX", 401, 10000))
	after := f.get(400, 1)
	if !reflect.DeepEqual(before, after) {
		t.Fatalf("同秒又は未来相手で過去支持が変化: %+v / %+v", before, after)
	}
}

// TestAuditSupportQuantityFinite157 は非有限数量で既知NaN支持を作らないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSupportQuantityFinite157(t *testing.T) {
	for _, bad := range []float64{math.Inf(1), math.NaN()} {
		f := auditSupport157()
		b := auditBoard157("NK225", 401, 64010)
		b.BidQuantity = bad
		f.add(b)
		if got := f.get(401, 1); got.Known {
			t.Fatalf("非有限数量を既知扱い: %+v", got)
		}
		f.add(auditBoard157("TOPIX", 401, 4040.1))
		f.add(auditBoard157("NK225", 402, 64020))
		got := f.get(402, 1)
		if got.Known && (math.IsNaN(got.OFI30) || math.IsNaN(got.M) || math.IsNaN(got.T)) {
			t.Fatalf("過去の非有限数量で支持が汚染: %+v", got)
		}
	}
}

// TestAuditSupportTolerance157 は窓端の許容幅を超える古い値を使用しないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSupportTolerance157(t *testing.T) {
	for _, tc := range []struct {
		old   float64
		known bool
	}{{3.01, true}, {3, true}, {2.99, false}} {
		rows := []supportRow157{{Time: tc.old, Mid: 100, Valid: true}, {Time: 10, Mid: 110, Valid: true}}
		v, ok := return157(rows, 1, 5, 2)
		if ok != tc.known || (ok && math.Abs(v-1000) > 1e-9) {
			t.Fatalf("端点許容差 old=%v v=%v known=%v", tc.old, v, ok)
		}
	}
}

// TestAuditSupportBadInterval157 は現在が正常でも窓内の異常を忘れないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSupportBadInterval157(t *testing.T) {
	f := auditSupport157()
	b := auditBoard157("NK225", 401, 64010)
	b.Ask = b.Bid
	f.add(b)
	f.add(auditBoard157("NK225", 402, 64020))
	if got := f.get(402, 1); got.Known {
		t.Fatalf("窓内の異常板を無視: %+v", got)
	}
	rows := []supportRow157{{Time: 0, Mid: 100, Valid: true, Bad: 0}, {Time: 6, Mid: 106, Valid: true, Bad: 1}}
	if _, ok := return157(rows, 1, 5, 2); ok {
		t.Fatal("観測空白又は異常の累積差を無視")
	}
}

// TestAuditSupportDirectionalSymmetry157 は同じ数式の売買符号が片方へ偏らないことを確認します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSupportDirectionalSymmetry157(t *testing.T) {
	f := auditSupport157()
	buy, sell := f.get(400, 1), f.get(400, -1)
	if !buy.Known || !sell.Known || buy.M <= 0 || buy.T <= 0 || sell.M != 0 || sell.T != 0 || buy.T != sell.Opp || buy.Opp != sell.T {
		t.Fatalf("同方向スコアの符号対称性: %+v / %+v", buy, sell)
	}
}

// TestAuditSupportOverflowCurrentOFI157 は過去の有効OFIで当行の計算不能を隠しません。
//
// 引数: t(*testing.T)。返り値: なし。
func TestAuditSupportOverflowCurrentOFI157(t *testing.T) {
	f := auditSupport157()
	b := auditBoard157("NK225", 401, 64010)
	b.BidQuantity = 1e308
	b.AskQuantity = 1e308
	f.add(b)
	if got := f.get(401, 1); got.Known {
		t.Fatalf("有限数量の合計overflowを既知扱い: %+v", got)
	}
}
