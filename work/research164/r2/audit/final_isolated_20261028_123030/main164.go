package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"sync"
	"time"
)

type Fingerprint164 struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
}
type Stage164 struct {
	Stage       string            `json:"stage"`
	ManifestSHA string            `json:"manifest_sha256"`
	SpecSHA     string            `json:"spec_sha256"`
	ConfigsSHA  string            `json:"configs_sha256"`
	FreezeSHA   string            `json:"freeze_sha256,omitempty"`
	Selected    map[string]string `json:"selected,omitempty"`
}
type ResultFile164 struct {
	Session, Path, SHA256 string
	Cases                 int
}
type Proof164 struct {
	Completed         bool             `json:"completed"`
	Returncode        int              `json:"returncode"`
	Stage             Stage164         `json:"stage"`
	Sessions          int              `json:"sessions"`
	Cases             int              `json:"cases"`
	SourcesUnchanged  bool             `json:"sources_unchanged"`
	Sources           []Fingerprint164 `json:"sources"`
	RawFilesChecked   int              `json:"raw_files_checked"`
	Results           []map[string]any `json:"results"`
	Started, Finished string
}

// hashFile164 はファイル全体の内容指紋を計算します。
//
// 引数: path(string)。返り値: stringとerror。原資料は読み取りだけです。
func hashFile164(path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	if _, e = io.Copy(h, f); e != nil {
		return "", e
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// allConfigs164 は各IDの対象区分を保って第二巡12手法を同一一覧へ連結します。
//
// 引数: なし。返り値: []any。
func allConfigs164() []any {
	out := []any{}
	for _, v := range configsDay164R2() {
		out = append(out, v)
	}
	for _, v := range configsNight164R2() {
		out = append(out, v)
	}
	return out
}

// validateAllConfigs164 は登録候補と実装に固定した条件の完全一致を検査します。
//
// 引数: path(string)。返り値: error。IDだけ一致した条件変更を許しません。
func validateAllConfigs164(path string) error {
	var got any
	if e := readJSON(path, &got); e != nil {
		return e
	}
	raw, e := json.Marshal(allConfigs164())
	if e != nil {
		return e
	}
	var want any
	if e = json.Unmarshal(raw, &want); e != nil {
		return e
	}
	if !reflect.DeepEqual(got, want) {
		return errors.New("固定12条件との差分があります")
	}
	return nil
}

// rootPath164 は登録器のプロジェクト相対パスを実行位置から解決します。
//
// 引数: path(string)。返り値: string。
func rootPath164(path string) string {
	if filepath.IsAbs(path) {
		return path
	}
	return filepath.Join("../../../..", filepath.FromSlash(path))
}

// verifySources164 は記載された全実装指紋を照合します。
//
// 引数: sources([]Fingerprint164)。返り値: error。
func verifySources164(sources []Fingerprint164) error {
	if len(sources) == 0 {
		return errors.New("実装指紋が空です")
	}
	for _, v := range sources {
		s, e := hashFile164(rootPath164(v.Path))
		if e != nil {
			return e
		}
		if s != v.SHA256 {
			return fmt.Errorf("登録源の改変 %s", v.Path)
		}
	}
	return nil
}

// gate164 は段階許可・正本指紋・選択凍結を検証します。
//
// 引数: stage/permission/manifest/spec/configs/freeze(string)。返り値: Stage164、[]Fingerprint164、error。
func gate164(stage, permission, manifest, spec, configs, freeze string) (Stage164, []Fingerprint164, error) {
	out := Stage164{Stage: stage}
	var allow struct {
		Registered   bool
		Returncode   *int
		Allowed      []string `json:"allowed_stages"`
		ManifestSHA  string   `json:"manifest_sha256"`
		SpecSHA      string   `json:"spec_sha256"`
		ConfigsSHA   string   `json:"configs_sha256"`
		FreezeSHA    string   `json:"freeze_sha256"`
		Registration Fingerprint164
	}
	if e := readJSON(permission, &allow); e != nil {
		return out, nil, e
	}
	if !allow.Registered || allow.Returncode == nil || *allow.Returncode != 0 {
		return out, nil, errors.New("段階許可の登録成功がありません")
	}
	found := false
	for _, s := range allow.Allowed {
		if s == stage {
			found = true
		}
	}
	if !found {
		return out, nil, errors.New("未許可の段階です")
	}
	for _, v := range []struct {
		path, want string
		dest       *string
	}{{manifest, allow.ManifestSHA, &out.ManifestSHA}, {spec, allow.SpecSHA, &out.SpecSHA}, {configs, allow.ConfigsSHA, &out.ConfigsSHA}} {
		s, e := hashFile164(v.path)
		if e != nil {
			return out, nil, e
		}
		if s != v.want {
			return out, nil, fmt.Errorf("正本指紋不一致 %s", v.path)
		}
		*v.dest = s
	}
	receiptPath := rootPath164(allow.Registration.Path)
	sha, e := hashFile164(receiptPath)
	if e != nil {
		return out, nil, e
	}
	if sha != allow.Registration.SHA256 {
		return out, nil, errors.New("登録受領指紋不一致")
	}
	var receipt struct {
		Registered bool
		Returncode *int
		Sources    []Fingerprint164
	}
	if e = readJSON(receiptPath, &receipt); e != nil {
		return out, nil, e
	}
	if !receipt.Registered || receipt.Returncode == nil || *receipt.Returncode != 0 {
		return out, nil, errors.New("登録受領が成功していません")
	}
	if e = verifySources164(receipt.Sources); e != nil {
		return out, nil, e
	}
	if stage == "confirmation" {
		var fr struct {
			Selected          map[string]string
			TestOpened        bool   `json:"test_opened"`
			SelectionSessions int    `json:"selection_sessions"`
			ManifestSHA       string `json:"manifest_sha256"`
			SpecSHA           string `json:"spec_sha256"`
			ConfigsSHA        string `json:"configs_sha256"`
		}
		if freeze == "" {
			return out, nil, errors.New("確認段階は選択凍結が必須です")
		}
		if e = readJSON(freeze, &fr); e != nil {
			return out, nil, e
		}
		sha, e = hashFile164(freeze)
		if e != nil {
			return out, nil, e
		}
		if sha != allow.FreezeSHA || fr.TestOpened || fr.SelectionSessions != 40 || fr.ManifestSHA != out.ManifestSHA || fr.SpecSHA != out.SpecSHA || fr.ConfigsSHA != out.ConfigsSHA {
			return out, nil, errors.New("選択凍結と許可の不一致")
		}
		if len(fr.Selected) != 3 {
			return out, nil, errors.New("選択は3区分です")
		}
		for _, s := range []struct{ key, prefix string }{{"Day", "NK225_D164_"}, {"PreUS", "NK225_P164_"}, {"PostUS", "NK225_U164_"}} {
			if !strings.HasPrefix(fr.Selected[s.key], s.prefix) {
				return out, nil, errors.New("選択区分とIDの不一致")
			}
		}
		valid := map[string]string{}
		for _, c := range configsDay164() {
			valid[c.ID] = c.Scope
		}
		for _, c := range configsNight164() {
			valid[c.ID] = c.Scope
		}
		for _, c := range configsDay164R2() {
			valid[c.ID] = c.Scope
		}
		for _, c := range configsNight164R2() {
			valid[c.ID] = c.Scope
		}
		for scope, id := range fr.Selected {
			if valid[id] != scope {
				return out, nil, errors.New("凍結選択が固定候補にありません")
			}
		}
		out.Selected = fr.Selected
		out.FreezeSHA = sha
	} else if stage != "train_validation" {
		return out, nil, errors.New("段階名が不正です")
	}
	return out, receipt.Sources, nil
}

// verifyRaw164 は当場6資料を読取前後とも全SHAで検査します。
//
// 引数: scene(Scene)。返り値: error。
func verifyRaw164(scene Scene) error {
	if len(scene.Fingerprints) != 6 {
		return fmt.Errorf("原資料指紋は6件必要 %s", scene.Session)
	}
	seen := map[string]bool{}
	for _, v := range scene.Fingerprints {
		path := rootPath164(v.Path)
		sha, e := hashFile164(path)
		if e != nil {
			return e
		}
		if sha != v.SHA256 {
			return fmt.Errorf("原資料改変 %s", path)
		}
		seen[filepath.Clean(path)] = true
	}
	for _, symbol := range []string{"NK225", "TOPIX"} {
		paths := []string{scene.Books[symbol], scene.Candles[symbol]["60"], scene.Candles[symbol]["300"]}
		for _, p := range paths {
			if !seen[filepath.Clean(rootPath164(p))] {
				return fmt.Errorf("読込対象に指紋がありません %s", p)
			}
		}
	}
	return nil
}

// execute164 は場を独立並列で再生し、原資料と源の前後一致を完了証跡へ残します。
//
// 引数: scenes([]Scene)、out(string)、workers(int)、stage(Stage164)、sources([]Fingerprint164)。返り値: Proof164とerror。
func execute164(scenes []Scene, out string, workers int, stage Stage164, sources []Fingerprint164) (Proof164, error) {
	proof := Proof164{Stage: stage, Sources: sources, Started: time.Now().Format(time.RFC3339Nano), Returncode: 1}
	if workers < 1 || workers > 8 {
		return proof, errors.New("並列数は1～8です")
	}
	for _, s := range scenes {
		if _, e := os.Stat(filepath.Join(out, s.Session+".json")); !os.IsNotExist(e) {
			return proof, fmt.Errorf("既存結果又は不正な保存先 %s", s.Session)
		}
	}
	if e := os.MkdirAll(out, 0700); e != nil {
		return proof, e
	}
	dayRules, e := loadDay164Rules()
	if e != nil {
		return proof, e
	}
	nightRules, e := loadNight164Rules()
	if e != nil {
		return proof, e
	}
	jobs := make(chan Scene)
	type completion struct {
		scene     Scene
		cases     int
		path, sha string
		err       error
	}
	done := make(chan completion, len(scenes))
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for s := range jobs {
				began := time.Now()
				item := completion{scene: s, path: filepath.Join(out, s.Session+".json")}
				item.err = verifyRaw164(s)
				var result any
				if item.err == nil {
					if s.Kind == "Day" {
						var v SavedDay164R2
						v, item.err = runDay164R2(s, configsDay164R2(), dayRules)
						result = v
						item.cases = len(v.Cases)
					} else {
						var v SavedNight164R2
						v, item.err = runNight164R2(s, configsNight164R2(), nightRules)
						result = v
						item.cases = len(v.Cases)
					}
				}
				if item.err == nil {
					item.err = verifyRaw164(s)
				}
				if item.err == nil {
					item.err = saveResult(item.path, result)
				}
				if item.err == nil {
					item.sha, item.err = hashFile164(item.path)
				}
				if item.err == nil {
					fmt.Printf("完了 %s 条件%d 所要%s\n", s.Session, item.cases, time.Since(began).Round(time.Millisecond))
				}
				done <- item
			}
		}()
	}
	for _, s := range scenes {
		jobs <- s
	}
	close(jobs)
	wg.Wait()
	close(done)
	var failures []string
	for c := range done {
		if c.err != nil {
			failures = append(failures, c.scene.Session+":"+c.err.Error())
			continue
		}
		proof.Sessions++
		proof.Cases += c.cases
		proof.RawFilesChecked += 6
		path, _ := filepath.Abs(c.path)
		proof.Results = append(proof.Results, map[string]any{"session": c.scene.Session, "path": path, "sha256": c.sha, "cases": c.cases})
	}
	sort.Slice(proof.Results, func(i, j int) bool {
		return proof.Results[i]["session"].(string) < proof.Results[j]["session"].(string)
	})
	if len(failures) > 0 {
		return proof, errors.New(strings.Join(failures, "\n"))
	}
	if e = verifySources164(sources); e != nil {
		return proof, e
	}
	proof.SourcesUnchanged = true
	proof.Completed = true
	proof.Returncode = 0
	proof.Finished = time.Now().Format(time.RFC3339Nano)
	return proof, nil
}

// main は人工以外の実行を登録・段階許可・固定候補の検査後に限定します。
//
// 引数: コマンドラインflag。返り値: なし。不整合は非0終了します。
func main() {
	manifest := flag.String("manifest", "../inputs164r2.json", "入力目録")
	spec := flag.String("spec", "../計画164r2.md", "固定計画")
	configs := flag.String("configs", "configs164r2.json", "固定条件")
	permission := flag.String("registration", "", "段階許可")
	stage := flag.String("stage", "train_validation", "段階")
	freeze := flag.String("freeze", "", "選択凍結")
	out := flag.String("out", "../results/train_validation", "結果保存先")
	workers := flag.Int("workers", 8, "場並列数")
	export := flag.String("export-configs", "", "固定条件だけ新規保存")
	flag.Parse()
	fail := func(e error) { fmt.Fprintln(os.Stderr, e); os.Exit(2) }
	if *export != "" {
		if e := saveResult(*export, allConfigs164()); e != nil {
			fail(e)
		}
		return
	}
	if e := validateAllConfigs164(*configs); e != nil {
		fail(e)
	}
	st, sources, e := gate164(*stage, *permission, *manifest, *spec, *configs, *freeze)
	if e != nil {
		fail(e)
	}
	var input struct{ Sessions []Scene }
	if e = readJSON(*manifest, &input); e != nil {
		fail(e)
	}
	if len(input.Sessions) != 54 {
		fail(errors.New("54場目録が必要です"))
	}
	selected := []Scene{}
	day, night := 0, 0
	for _, s := range input.Sessions {
		use := s.Split == "train" || s.Split == "validation"
		if *stage == "confirmation" {
			use = s.Split == "test" || s.Split == "extra"
		}
		if use {
			selected = append(selected, s)
			if s.Kind == "Day" {
				day++
			} else if s.Kind == "Night" {
				night++
			} else {
				fail(errors.New("昼夜区分不正"))
			}
		}
	}
	want := 20
	if *stage == "confirmation" {
		want = 7
	}
	if day != want || night != want {
		fail(errors.New("段階の昼夜件数が不一致"))
	}
	proof, e := execute164(selected, *out, *workers, st, sources)
	if e != nil {
		fail(e)
	}
	if proof.Cases != want*12 {
		fail(errors.New("出力条件数不一致"))
	}
	proofPath := filepath.Join(*out, "再生完了164r2_"+*stage+".json")
	if e = saveResult(proofPath, proof); e != nil {
		fail(e)
	}
}
