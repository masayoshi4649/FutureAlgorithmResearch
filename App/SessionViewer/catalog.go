package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type SessionChoice struct {
	Symbol  string `json:"symbol"`
	Session string `json:"session"`
}

// validateCatalog は登録リソースの識別子と読取パスを検査します。
//
// 引数: cfg(Config)、catalog(Catalog)。返り値: 解決済みCatalogとerror。
func validateCatalog(cfg Config, catalog Catalog) (Catalog, error) {
	return validateCatalogAt(cfg, catalog, "")
}

// validateCatalogAt はリンク列挙の実在位置を優先し、移動可能な資料の相対参照を解決します。
//
// 引数: cfg(Config)、catalog(Catalog)、catalogPath(string、アップロードは空)。
// 返り値: 解決済みCatalogとerror。原板の相対基準は常にdata_rootです。
func validateCatalogAt(cfg Config, catalog Catalog, catalogPath string) (Catalog, error) {
	if catalog.SchemaVersion != 1 {
		return catalog, fmt.Errorf("schema_version は1が必要です")
	}
	if len(catalog.Resources) == 0 {
		return catalog, fmt.Errorf("resources が空です")
	}
	catalog.Resources = append([]ResourceMeta(nil), catalog.Resources...)
	resourceRoot := cfg.Paths.ResourceRoot
	if catalog.PathBase != "" && catalog.PathBase != "catalog" {
		return catalog, fmt.Errorf("path_baseは省略又はcatalogです")
	}
	if catalog.PathBase == "catalog" {
		if catalogPath != "" {
			resourceRoot = filepath.Dir(catalogPath)
		} else {
			if catalog.BaseDir == "" || !filepath.IsAbs(catalog.BaseDir) {
				return catalog, fmt.Errorf("path_base=catalogのアップロードには絶対base_dirが必要です。サーバー上の一覧パスを指定して開いてください")
			}
			resourceRoot = filepath.Clean(catalog.BaseDir)
		}
	} else if catalog.BaseDir != "" && !filepath.IsAbs(catalog.BaseDir) {
		return catalog, fmt.Errorf("base_dirは絶対パスが必要です")
	}
	seen := map[string]bool{}
	for i := range catalog.Resources {
		r := &catalog.Resources[i]
		if r.ID == "" || seen[r.ID] {
			return catalog, fmt.Errorf("resource IDが空又は重複です")
		}
		seen[r.ID] = true
		if r.Symbol != "NK225" && r.Symbol != "TOPIX" {
			return catalog, fmt.Errorf("未知の銘柄です: %s", r.Symbol)
		}
		if _, _, err := sessionBounds(r.Session); err != nil {
			return catalog, err
		}
		if r.PNLFormat != "trades" && r.PNLFormat != "snapshots" {
			return catalog, fmt.Errorf("pnl_format が不正です")
		}
		if r.EntryMethodID != "" && (r.PNLFormat != "trades" || strings.TrimSpace(r.EntryMethodID) != r.EntryMethodID || r.EntryMethodID == "*") {
			return catalog, fmt.Errorf("entry_method_idはtradesの実際の新規手法IDを指定してください")
		}
		if r.PNLBasis != "gross" && r.PNLBasis != "net" {
			return catalog, fmt.Errorf("pnl_basis が不正です")
		}
		if r.PNLFormat == "trades" && (!finite(r.PointValue) || r.PointValue <= 0) {
			return catalog, fmt.Errorf("tradesには正のpoint_valueが必須です")
		}
		var err error
		r.PNLPath, err = resolvePath(resourceRoot, r.PNLPath)
		if err != nil {
			return catalog, err
		}
		if r.MarketPath == "" {
			r.MarketPath = filepath.Join(r.Symbol, r.Session, "book.jsonl")
		}
		r.MarketPath, err = resolvePath(cfg.Paths.DataRoot, r.MarketPath)
		if err != nil {
			return catalog, err
		}
		if r.Title == "" {
			r.Title = r.ID
		}
	}
	return catalog, nil
}

// readCatalog は明示された一覧ファイルだけを読取ります。
//
// 引数: cfg(Config)、path(string)。返り値: Catalog、解決パス(string)、error。
func readCatalog(cfg Config, path string) (Catalog, string, error) {
	var c Catalog
	if !strings.HasSuffix(strings.ToLower(path), ".resources.json") {
		return c, "", fmt.Errorf("一覧は .resources.json が必要です")
	}
	p, err := resolvePath(cfg.Paths.ResourceRoot, path)
	if err != nil {
		return c, "", err
	}
	b, err := os.ReadFile(p)
	if err != nil {
		return c, p, err
	}
	if err = json.Unmarshal(b, &c); err != nil {
		return c, p, fmt.Errorf("一覧JSON: %w", err)
	}
	c, err = validateCatalogAt(cfg, c, p)
	return c, p, err
}

// listSessions は原板のあるフォルダだけを列挙します。
//
// 引数: cfg(Config)、symbol(string)。返り値: []SessionChoice と error。原板本文は読みません。
func listSessions(cfg Config, symbol string) ([]SessionChoice, error) {
	if symbol != "NK225" && symbol != "TOPIX" {
		return nil, fmt.Errorf("未知の銘柄です")
	}
	items, err := os.ReadDir(filepath.Join(cfg.Paths.DataRoot, symbol))
	if os.IsNotExist(err) {
		return []SessionChoice{}, nil
	}
	if err != nil {
		return nil, err
	}
	result := []SessionChoice{}
	for _, e := range items {
		if !e.IsDir() {
			continue
		}
		if _, _, err := sessionBounds(e.Name()); err != nil {
			continue
		}
		if st, err := os.Stat(filepath.Join(cfg.Paths.DataRoot, symbol, e.Name(), "book.jsonl")); err == nil && !st.IsDir() {
			result = append(result, SessionChoice{symbol, e.Name()})
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Session < result[j].Session })
	return result, nil
}
