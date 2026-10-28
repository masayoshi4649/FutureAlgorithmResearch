package webui

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"futurealgorithm/sessiontrader/internal/config"
	"futurealgorithm/sessiontrader/internal/runner"
)

// TestHTTPControlsRequireSameOriginToken は不正なブラウザ要求が新規許可を変えないことを検査します。
//
// 引数: t(*testing.T)。返り値: なし。HTTPも売買処理も試験内だけで完結します。
func TestHTTPControlsRequireSameOriginToken(t *testing.T) {
	m, err := NewManager(testConfig(t), func(ctx context.Context, _ config.Config, _ *runner.Control, _ func(runner.Snapshot)) error {
		<-ctx.Done()
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	defer m.Close()
	handler, err := NewHandler(m)
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(handler)
	defer server.Close()
	response, err := http.Get(server.URL + "/api/state")
	if err != nil {
		t.Fatal(err)
	}
	var state State
	if err = json.NewDecoder(response.Body).Decode(&state); err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if len(state.Products) != 5 || state.CSRFToken == "" {
		t.Fatal("状態取得が不正です")
	}
	for _, test := range []struct {
		name, token, origin, host, body string
		status                          int
	}{
		{"トークンなし", "", "", "", `{"enabled":true}`, 403},
		{"別サイト", state.CSRFToken, "http://external.invalid", "", `{"enabled":true}`, 403},
		{"DNS差替え", state.CSRFToken, "", "external.invalid", `{"enabled":true}`, 403},
		{"項目不足", state.CSRFToken, "", "", `{}`, 400},
		{"追加項目", state.CSRFToken, "", "", `{"enabled":true,"price":1}`, 400},
		{"二重本文", state.CSRFToken, "", "", `{"enabled":true}{}`, 400},
		{"正常ON", state.CSRFToken, server.URL, "", `{"enabled":true}`, 200},
		{"正常OFF", state.CSRFToken, server.URL, "", `{"enabled":false}`, 200},
	} {
		t.Run(test.name, func(t *testing.T) {
			req, _ := http.NewRequest(http.MethodPost, server.URL+"/api/products/NK225mini/enabled", strings.NewReader(test.body))
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("X-CSRF-Token", test.token)
			if test.origin != "" {
				req.Header.Set("Origin", test.origin)
			}
			if test.host != "" {
				req.Host = test.host
			}
			res, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			defer res.Body.Close()
			if res.StatusCode != test.status {
				raw, _ := io.ReadAll(res.Body)
				t.Fatalf("状態%d: %s", res.StatusCode, raw)
			}
			if test.status != 200 && m.State().Products[1].Enabled {
				t.Fatal("拒否要求で新規を許可しました")
			}
		})
	}
	res, err := http.Get(server.URL + "/")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	text, _ := io.ReadAll(res.Body)
	if !strings.Contains(string(text), "日経225") || res.Header.Get("Content-Security-Policy") == "" {
		t.Fatal("埋込画面または制限ヘッダーがありません")
	}
}
