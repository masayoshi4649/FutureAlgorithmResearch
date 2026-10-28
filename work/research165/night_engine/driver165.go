package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"time"
)

// validateConfigs165 は外部定義とコード内定義の全構造一致を要求します。
//
// 引数: path(string)。返り値: error。
func validateConfigs165(path string) error {
	var got, want any
	if e := readJSON(path, &got); e != nil {
		return e
	}
	b, e := json.Marshal(configs165())
	if e != nil {
		return e
	}
	if e = json.Unmarshal(b, &want); e != nil {
		return e
	}
	if !reflect.DeepEqual(got, want) {
		return fmt.Errorf("固定14定義と外部ファイルが一致しません")
	}
	return nil
}

// saveNew165 は上書きをせず新しい証跡を保存します。
//
// 引数: path(string)、value(any)。返り値: error。
func saveNew165(path string, value any) error {
	b, e := json.MarshalIndent(value, "", "  ")
	if e != nil {
		return e
	}
	f, e := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if e != nil {
		return e
	}
	_, e = f.Write(b)
	closeErr := f.Close()
	if e != nil {
		return e
	}
	return closeErr
}

// baselineActual165 は保存U00との全実台帳一致を検査します。
//
// 引数: actual(*Ledger157)、saved(json.RawMessage)。返り値: error。メタ差だけで成績を変更しません。
func baselineActual165(actual *Ledger157, saved json.RawMessage) error {
	var expected struct {
		Actual *Ledger157 `json:"actual"`
	}
	if e := json.Unmarshal(saved, &expected); e != nil {
		return e
	}
	if !reflect.DeepEqual(actual, expected.Actual) {
		return fmt.Errorf("保存U164_00実台帳と不一致")
	}
	return nil
}

// execute165 は許可済みの20夜又は7夜だけを独立並列で実行します。
//
// 引数: manifest/out(string)、workers(int)、stage(Stage164)、sources([]Fingerprint164)。返り値: Proof164とerror。
func execute165(manifest, out string, workers int, stage Stage164, sources []Fingerprint164) (Proof164, error) {
	proof := Proof164{Stage: stage, Sources: sources, Returncode: 1, Started: time.Now().Format(time.RFC3339)}
	if workers < 1 || workers > 8 {
		return proof, fmt.Errorf("並列数は1〜8")
	}
	if _, e := os.Stat(out); e == nil {
		return proof, fmt.Errorf("結果ディレクトリが既存")
	}
	var input struct {
		Sessions []json.RawMessage `json:"sessions"`
	}
	if e := readJSON(manifest, &input); e != nil {
		return proof, e
	}
	if len(input.Sessions) != 27 {
		return proof, fmt.Errorf("Night27場が必要")
	}
	type job struct {
		scene Scene
		raw   json.RawMessage
	}
	jobsList := []job{}
	for _, raw := range input.Sessions {
		var scene Scene
		if e := json.Unmarshal(raw, &scene); e != nil {
			return proof, e
		}
		if scene.Kind != "Night" || scene.Partial {
			return proof, fmt.Errorf("Night完了場以外")
		}
		early := scene.Split == "train" || scene.Split == "validation"
		if (stage.Stage == "train_validation" && early) || (stage.Stage == "confirmation" && !early) {
			jobsList = append(jobsList, job{scene, raw})
		}
	}
	wanted := 20
	if stage.Stage == "confirmation" {
		wanted = 7
	}
	if len(jobsList) != wanted {
		return proof, fmt.Errorf("段階場数不一致")
	}
	var baseline struct {
		Cases []struct {
			Scene Scene           `json:"scene"`
			Case  json.RawMessage `json:"case"`
		} `json:"cases"`
	}
	if e := readJSON("../baseline165.json", &baseline); e != nil {
		return proof, e
	}
	base := map[string]json.RawMessage{}
	for _, b := range baseline.Cases {
		base[b.Scene.Session] = b.Case
	}
	if len(base) != 27 {
		return proof, fmt.Errorf("保存基準27場が必要")
	}
	sets, e := loadNight164Rules()
	if e != nil {
		return proof, e
	}
	if e = verifySources165(sources); e != nil {
		return proof, e
	}
	if e = os.MkdirAll(out, 0755); e != nil {
		return proof, e
	}
	type done struct {
		session, path, sha string
		err                error
	}
	queue := make(chan job)
	results := make(chan done, len(jobsList))
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := range queue {
				result := done{session: j.scene.Session, path: filepath.Join(out, j.scene.Session+".json")}
				if result.err = verifyRaw164(j.scene); result.err == nil {
					var saved Saved165
					saved, result.err = run165(j.scene, configs165(), sets)
					if result.err == nil {
						result.err = baselineActual165(saved.Control.Actual, base[j.scene.Session])
					}
					if result.err == nil {
						result.err = verifyRaw164(j.scene)
					}
					if result.err == nil {
						var doc map[string]json.RawMessage
						raw, err := json.Marshal(saved)
						if err == nil {
							err = json.Unmarshal(raw, &doc)
						}
						if err == nil {
							doc["scene"] = j.raw
							err = saveNew165(result.path, doc)
						}
						result.err = err
					}
					if result.err == nil {
						result.sha, result.err = hashFile164(result.path)
					}
				}
				results <- result
			}
		}()
	}
	go func() {
		for _, j := range jobsList {
			queue <- j
		}
		close(queue)
		wg.Wait()
		close(results)
	}()
	var first error
	for r := range results {
		if r.err != nil {
			if first == nil {
				first = fmt.Errorf("%s:%w", r.session, r.err)
			}
			continue
		}
		abs, _ := filepath.Abs(r.path)
		root, _ := filepath.Abs("../../..")
		rel, _ := filepath.Rel(root, abs)
		proof.Results = append(proof.Results, map[string]any{"session": r.session, "path": filepath.ToSlash(rel), "sha256": r.sha, "cases": 14})
		proof.Sessions++
		proof.Cases += 14
		proof.RawFilesChecked += 6
		fmt.Printf("完了 %s 14条件・保存基準同値\n", r.session)
	}
	proof.Finished = time.Now().Format(time.RFC3339)
	if e = verifySources165(sources); e != nil && first == nil {
		first = e
	}
	proof.SourcesUnchanged = e == nil
	if first == nil && proof.Sessions == wanted {
		proof.Completed = true
		proof.Returncode = 0
	}
	if e = saveNew165(filepath.Join(out, "再生完了165_"+stage.Stage+".json"), proof); e != nil && first == nil {
		first = e
	}
	return proof, first
}
