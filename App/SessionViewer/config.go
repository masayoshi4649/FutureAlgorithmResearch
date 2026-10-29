package main

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
)

var sessionPattern = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}_(Day|Night)$`)
var japan = time.FixedZone("JST", 9*60*60)

// LoadConfig は実行ファイル基準のTOMLを読み、相対設定を絶対パスに解決します。
//
// 引数: path(string)は設定ファイル、baseDir(string)は実行ファイルのフォルダです。
// 返り値: Config と error。原資料やキャッシュファイルを作りません。
func LoadConfig(path, baseDir string) (Config, error) {
	var c Config
	base, err := filepath.Abs(baseDir)
	if err != nil {
		return c, err
	}
	c.BaseDir = base
	c.Server.Listen = "127.0.0.1:8091"
	c.Viewer.CacheMB = 64
	if !filepath.IsAbs(path) {
		path = filepath.Join(base, path)
	}
	if _, err = toml.DecodeFile(path, &c); err != nil {
		return c, err
	}
	c.BaseDir = base
	if c.Paths.DataRoot == "" || c.Paths.ResourceRoot == "" {
		return c, fmt.Errorf("data_root と resource_root は必須です")
	}
	for _, p := range []*string{&c.Paths.DataRoot, &c.Paths.ResourceRoot} {
		if !filepath.IsAbs(*p) {
			*p = filepath.Join(base, *p)
		}
		*p = filepath.Clean(*p)
	}
	if c.Viewer.FontPath != "" {
		if !filepath.IsAbs(c.Viewer.FontPath) {
			c.Viewer.FontPath = filepath.Join(base, c.Viewer.FontPath)
		}
		c.Viewer.FontPath = filepath.Clean(c.Viewer.FontPath)
	}
	if c.Paths.DefaultCatalog != "" {
		c.Paths.DefaultCatalog, err = resolvePath(c.Paths.ResourceRoot, c.Paths.DefaultCatalog)
		if err != nil {
			return c, err
		}
	}
	if c.Server.Listen == "" || c.Viewer.CacheMB < 0 || c.Viewer.CacheMB > 4096 {
		return c, fmt.Errorf("listen 又は cache_mb が不正です")
	}
	return c, nil
}

// resolvePath は明示絶対パス又は指定基準内の相対パスを解決します。
//
// 引数: root/name(string)。返り値: 解決パス(string)とerror。相対の親抜けを拒否します。
func resolvePath(root, name string) (string, error) {
	if name == "" {
		return "", fmt.Errorf("パスが空です")
	}
	if filepath.IsAbs(name) {
		return filepath.Clean(name), nil
	}
	base, err := filepath.Abs(root)
	if err != nil {
		return "", err
	}
	p := filepath.Join(base, name)
	r, err := filepath.Rel(base, p)
	if err != nil || r == ".." || strings.HasPrefix(r, ".."+string(os.PathSeparator)) {
		return "", fmt.Errorf("相対パスが基準フォルダ外です")
	}
	// ----------------------------------------
	// 存在するリンクは実体も基準内であることを確認します。
	if real, e := filepath.EvalSymlinks(p); e == nil {
		realBase, e := filepath.EvalSymlinks(base)
		if e == nil {
			r, e = filepath.Rel(realBase, real)
			if e != nil || r == ".." || strings.HasPrefix(r, ".."+string(os.PathSeparator)) {
				return "", fmt.Errorf("リンク先が基準フォルダ外です")
			}
		}
	}
	return p, nil
}

// sessionBounds はフォルダ日付を開始日とする日本時間の立会範囲を返します。
//
// 引数: session(string)。返り値: 開始/終了(time.Time)、error。Nightは翌朝までです。
func sessionBounds(session string) (time.Time, time.Time, error) {
	if !sessionPattern.MatchString(session) {
		return time.Time{}, time.Time{}, fmt.Errorf("セッション名が不正です")
	}
	d, err := time.ParseInLocation("2006-01-02", session[:10], japan)
	if err != nil {
		return d, d, err
	}
	if strings.HasSuffix(session, "_Day") {
		return d.Add(8*time.Hour + 45*time.Minute), d.Add(15*time.Hour + 45*time.Minute), nil
	}
	return d.Add(17 * time.Hour), d.Add(30 * time.Hour), nil
}

// finite はJSONへ安全に表示できる有限数か確認します。
//
// 引数: x(float64)。返り値: bool。
func finite(x float64) bool { return !math.IsNaN(x) && !math.IsInf(x, 0) }

// millis は絶対時計を小数ミリ秒へ変換します。
//
// 引数: t(time.Time)。返り値: float64。
func millis(t time.Time) float64 { return float64(t.UnixNano()) / 1e6 }
