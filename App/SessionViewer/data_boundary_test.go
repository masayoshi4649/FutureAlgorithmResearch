package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestViewerRightBoundaryUsesOnlyKnownPast は同時計不明・欠測板・観測終了後を右端へ補間しません。
//
// 引数: t(*testing.T)。返り値: なし。将来の高値を入れても過去の含みは未知のままです。
func TestViewerRightBoundaryUsesOnlyKnownPast(t *testing.T) {
	cfg, cat := apiFixture(t)
	c, err := validateCatalog(cfg, cat)
	if err != nil {
		t.Fatal(err)
	}
	r := c.Resources[0]
	raw := `{"CurrentPriceTime":"2026-10-27T08:45:00+09:00","CurrentPrice":100,"Buy1":{"Price":100},"Sell1":{"Price":110}}
{"CurrentPriceTime":"2026-10-27T08:45:00+09:00","CurrentPrice":200,"Buy1":{"Price":200},"Sell1":{"Price":210}}
{"CurrentPriceTime":"2026-10-27T08:45:02+09:00","CurrentPrice":null,"Buy1":{"Price":null},"Sell1":{"Price":210}}
{"CurrentPriceTime":"2026-10-27T08:45:04+09:00","CurrentPrice":300,"Buy1":{"Price":300},"Sell1":{"Price":310}}
`
	trades := `{"id":"n","timestamp":"2026-10-27T08:45:00+09:00","type":"LongN","position_id":"p","qty":2,"price":110}` + "\n"
	if err = os.WriteFile(r.MarketPath, []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(cfg.Paths.ResourceRoot, "trades.jsonl"), []byte(trades), 0600); err != nil {
		t.Fatal(err)
	}
	start, _, _ := sessionBounds(r.Session)
	for _, seconds := range []float64{1, 3, 5} {
		to := millis(start) + seconds*1000
		out, e := loadData(cfg, r, "", millis(start), to, 100)
		if e != nil {
			t.Fatal(e)
		}
		if out.Summary.LongQty == nil || *out.Summary.LongQty != 2 || out.Summary.Realized == nil || *out.Summary.Realized != 0 || out.Summary.Unrealized != nil {
			t.Fatalf("%v秒の未知含みを補った: %+v", seconds, out.Summary)
		}
		last := out.States[len(out.States)-1]
		if last[0] != to || last[3] != 2 || last[5] != float64(0) || last[6] != nil {
			t.Fatalf("右端補助: %v", last)
		}
	}
	// ----------------------------------------
	// 正常な観測時刻そのものは既知の評価を残します。
	out, err := loadData(cfg, r, "", millis(start), millis(start.Add(4*time.Second)), 100)
	if err != nil {
		t.Fatal(err)
	}
	if out.Summary.Unrealized == nil || *out.Summary.Unrealized != 3800 {
		t.Fatalf("観測時の評価を失った: %+v", out.Summary)
	}
}
