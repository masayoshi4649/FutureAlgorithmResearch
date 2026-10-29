package main

import (
	"os"
	"runtime"
	"testing"
	"time"
)

// BenchmarkViewerRawStreaming は明示指定された原板の読取だけを計測します。
//
// 引数: b(*testing.B)。返り値: なし。SESSION_VIEWER_RAWとSESSION_VIEWER_SESSIONが必要です。
// 売買政策は呼ばず、原資料・キャッシュファイル・損益ファイルを生成しません。
func BenchmarkViewerRawStreaming(b *testing.B) {
	path := os.Getenv("SESSION_VIEWER_RAW")
	session := os.Getenv("SESSION_VIEWER_SESSION")
	if path == "" || session == "" {
		b.Skip("明示した原板だけを計測します")
	}
	st, err := os.Stat(path)
	if err != nil {
		b.Fatal(err)
	}
	var cfg Config
	r := ResourceMeta{ID: "価格読取計測", Symbol: "NK225", Session: session, MarketPath: path}
	b.SetBytes(st.Size())
	for i := 0; i < b.N; i++ {
		runtime.GC()
		var before runtime.MemStats
		runtime.ReadMemStats(&before)
		stop := make(chan struct{})
		peakDone := make(chan uint64, 1)
		go func() {
			peak := before.HeapAlloc
			timer := time.NewTicker(10 * time.Millisecond)
			defer timer.Stop()
			for {
				select {
				case <-timer.C:
					var stats runtime.MemStats
					runtime.ReadMemStats(&stats)
					if stats.HeapAlloc > peak {
						peak = stats.HeapAlloc
					}
				case <-stop:
					peakDone <- peak
					return
				}
			}
		}()
		data, err := loadData(cfg, r, "", 0, 0, 1200)
		close(stop)
		peak := <-peakDone
		if err != nil {
			b.Fatal(err)
		}
		b.ReportMetric(float64(peak-before.HeapAlloc)/(1024*1024), "追加ヒープMiB")
		b.ReportMetric(float64(data.Quality.RawRows), "原行数")
		b.ReportMetric(float64(len(data.Prices)), "出力点数")
	}
}
