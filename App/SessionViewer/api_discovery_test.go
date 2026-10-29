package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// TestOpenAPIDiscovery はAIが使用する経路とパラメータ参照が実在するか検査します。
//
// 引数: t(*testing.T)。返り値: なし。ネットワーク・画像生成・原資料を必要としません。
func TestOpenAPIDiscovery(t *testing.T) {
	s := &Server{}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/openapi.json", nil))
	var spec struct {
		Version string `json:"openapi"`
		Paths   map[string]map[string]struct {
			Parameters []struct {
				Ref string `json:"$ref"`
			} `json:"parameters"`
		} `json:"paths"`
		Components struct {
			Parameters map[string]map[string]any `json:"parameters"`
		} `json:"components"`
	}
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &spec) != nil || spec.Version != "3.0.3" {
		t.Fatalf("機械用仕様を取得できません: %d %s", w.Code, w.Body.String())
	}
	for _, path := range []string{"/api/resources", "/api/chart", "/api/chart.png", "/api/chart.svg", "/api/data", "/api/catalogs/load"} {
		if len(spec.Paths[path]) == 0 {
			t.Fatal("API経路が仕様にありません:", path)
		}
	}
	for path, methods := range spec.Paths {
		for _, operation := range methods {
			for _, parameter := range operation.Parameters {
				key := strings.TrimPrefix(parameter.Ref, "#/components/parameters/")
				if spec.Components.Parameters[key] == nil {
					t.Fatalf("参照切れ: %s %s", path, parameter.Ref)
				}
			}
		}
	}
	if spec.Components.Parameters["image_width"]["name"] != "width" || spec.Components.Parameters["data_width"]["name"] != "width" {
		t.Fatal("内部区分名を実クエリ名へ混入しました")
	}
}
