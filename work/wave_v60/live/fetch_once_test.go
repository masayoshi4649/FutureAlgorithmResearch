package main

import (
	"io"
	"net/http"
	"path/filepath"
	"strings"
	"testing"
)

type mockTransport struct { calls int; complete string }
type trailerBody struct { reader io.Reader; trailer http.Header; complete string }

// Read は全本文を読み終えた時だけ模擬トレーラーを公開します。
//
// 引数: data []byte は読取先です。返り値: int は読取数、error は終端です。
func (body *trailerBody) Read(data []byte) (int, error) {
	n, err := body.reader.Read(data)
	if err == io.EOF && body.complete != "" { body.trailer.Set("X-History-Complete", body.complete) }
	return n, err
}

// Close は模擬本文を閉じます。
//
// 引数: なし。返り値: error は常にnilです。ソケットは作りません。
func (body *trailerBody) Close() error { return nil }

// RoundTrip はソケットを使わず、本文完了時にトレーラーが届く応答を返します。
//
// 引数: request *http.Request は模擬取得要求です。
// 返り値: *http.Response と error。呼出回数を数えて再試行の有無を確認します。
func (transport *mockTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	transport.calls++
	trailer := make(http.Header)
	return &http.Response{StatusCode: 200, Header: make(http.Header), Trailer: trailer,
		Body: &trailerBody{reader: strings.NewReader("{\"合成\":true}\n"), trailer: trailer, complete: transport.complete}, Request: request}, nil
}

// TestTrailer は完了・未完了・欠測トレーラーをネットワーク無しで確認します。
//
// 引数: t *testing.T は検査器です。返り値: なし。
func TestTrailer(t *testing.T) {
	for _, complete := range []string{"true", "false", ""} {
		transport := &mockTransport{complete: complete}
		client := &http.Client{Transport: transport}
		result := fetch(client, "http://network-is-not-used.invalid/book", filepath.Join(t.TempDir(), "book.jsonl"), true)
		if result["成功"] != (complete == "true") { t.Fatalf("完了判定不一致: %v", result) }
		if transport.calls != 1 { t.Fatalf("一回取得ではありません: %d", transport.calls) }
	}
}
