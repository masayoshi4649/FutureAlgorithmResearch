package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"time"
)

// saveJSON は取得記録を UTF-8 の JSON として保存します。
//
// 引数: path string は保存先、value any は取得記録です。
// 返り値: error は書込み失敗です。再取得は行いません。
func saveJSON(path string, value any) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil { return err }
	return os.WriteFile(path, data, 0600)
}

// fetch は指定URLへ一回だけGETし、本文完了後のHTTPトレーラーも保存します。
//
// 引数: client *http.Client、address string、path string、book bool は板応答かどうかです。
// 返り値: map[string]any は応答情報です。失敗しても再試行しません。
func fetch(client *http.Client, address, path string, book bool) map[string]any {
	record := map[string]any{"url": address, "file": filepath.Base(path), "成功": false}
	request, err := http.NewRequest(http.MethodGet, address, nil)
	if err != nil { record["error"] = err.Error(); return record }
	request.Header.Set("Accept", "application/json, application/x-ndjson")
	request.Header.Set("TE", "trailers")
	response, err := client.Do(request)
	if err != nil { record["error"] = err.Error(); return record }
	defer response.Body.Close()
	record["status"] = response.StatusCode
	record["headers"] = response.Header.Clone()
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil { record["error"] = err.Error(); return record }
	count, copyErr := io.Copy(file, response.Body)
	closeErr := file.Close()
	record["bytes"] = count
	record["trailers"] = response.Trailer.Clone()
	if copyErr != nil { record["error"] = copyErr.Error(); return record }
	if closeErr != nil { record["error"] = closeErr.Error(); return record }
	if response.StatusCode != http.StatusOK { record["error"] = response.Status; return record }
	if book && response.Trailer.Get("X-History-Complete") != "true" {
		record["error"] = "本文完了トレーラーを確認できません"
		return record
	}
	record["成功"] = true
	return record
}

// main は親のGO後にだけ、状態1回と二銘柄の原本各1回を取得します。
//
// 引数: コマンド引数の authorized、directory、base を使用します。
// 返り値: なし。取得開始記録が存在する場合は二度目を拒否します。
func main() {
	authorized := flag.Bool("authorized", false, "親が候補固定と取得GOを通知済みの場合だけ指定")
	directory := flag.String("directory", ".", "保存先")
	base := flag.String("base", "http://10.10.100.1:8080", "既定の履歴API")
	flag.Parse()
	if !*authorized { fmt.Fprintln(os.Stderr, "取得GOがありません。ネットワーク未使用です"); os.Exit(2) }
	if err := os.MkdirAll(*directory, 0700); err != nil { panic(err) }
	marker, err := os.OpenFile(filepath.Join(*directory, "取得開始.json"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil { fmt.Fprintln(os.Stderr, "取得済み又は保存不可のため再試行しません:", err); os.Exit(2) }
	cutoff := time.Now().UTC().Format(time.RFC3339Nano)
	start, _ := json.Marshal(map[string]any{"共通to": cutoff, "最大HTTP要求数": 3, "再試行": false})
	_, _ = marker.Write(start)
	_ = marker.Close()
	client := &http.Client{
		Timeout: 180 * time.Second,
		Transport: &http.Transport{Proxy: nil, DisableKeepAlives: true, ForceAttemptHTTP2: false},
		CheckRedirect: func(request *http.Request, via []*http.Request) error { return http.ErrUseLastResponse },
	}
	records := []map[string]any{}
	manifest := map[string]any{"共通to": cutoff, "再試行": false, "実注文": 0}
	// ----------------------------------------
	// 異なる三URLを一回ずつ取得し、どの応答が失敗してもそのURLは繰り返しません。
	records = append(records, fetch(client, *base+"/api/v1/history/status", filepath.Join(*directory, "status.json"), false))
	manifest["requests"] = records
	if err = saveJSON(filepath.Join(*directory, "取得記録.json"), manifest); err != nil { panic(err) }
	for _, code := range []string{"NK225", "TOPIX"} {
		query := url.Values{}
		query.Set("to", cutoff)
		address := *base + "/api/v1/history/" + code + "/book?" + query.Encode()
		records = append(records, fetch(client, address, filepath.Join(*directory, code+".jsonl"), true))
		manifest["requests"] = records
		if err = saveJSON(filepath.Join(*directory, "取得記録.json"), manifest); err != nil { panic(err) }
	}
	allOK := true
	for _, record := range records { if record["成功"] != true { allOK = false } }
	manifest["全応答成功"] = allOK
	manifest["終了時計"] = time.Now().UTC().Format(time.RFC3339Nano)
	if err = saveJSON(filepath.Join(*directory, "取得記録.json"), manifest); err != nil { panic(err) }
	if !allOK { fmt.Fprintln(os.Stderr, "一回取得のいずれかが失敗しました。再取得しません"); os.Exit(1) }
	fmt.Println("状態1回・二銘柄各1回の取得とトレーラー確認が完了しました")
}
