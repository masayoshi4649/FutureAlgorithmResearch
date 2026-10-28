package main

import (
	"errors"
	"fmt"
	"path/filepath"
)

// rootPath165 は研究165の起点から登録器の相対根拠を解決します。
//
// 引数: path(string)。返り値: string。
func rootPath165(path string) string {
	if filepath.IsAbs(path) {
		return path
	}
	return filepath.Join("../../..", filepath.FromSlash(path))
}

// verifySources165 は登録した全源の現在SHAを検査します。
//
// 引数: sources([]Fingerprint164)。返り値: error。
func verifySources165(sources []Fingerprint164) error {
	if len(sources) == 0 {
		return errors.New("源指紋が空です")
	}
	for _, s := range sources {
		h, e := hashFile164(rootPath165(s.Path))
		if e != nil {
			return e
		}
		if h != s.SHA256 {
			return fmt.Errorf("源指紋不一致:%s", s.Path)
		}
	}
	return nil
}

// gate165 は登録受領と段階、定義、入力、選択凍結をすべて検査します。
//
// 引数: stage/permission/manifest/spec/configs/freeze(string)。返り値: Stage164、[]Fingerprint164、error。
func gate165(stage, permission, manifest, spec, configs, freeze string) (Stage164, []Fingerprint164, error) {
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
	receiptPath := rootPath165(allow.Registration.Path)
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
	if e = verifySources165(receipt.Sources); e != nil {
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
		if sha != allow.FreezeSHA || fr.TestOpened || fr.SelectionSessions != 20 || fr.ManifestSHA != out.ManifestSHA || fr.SpecSHA != out.SpecSHA || fr.ConfigsSHA != out.ConfigsSHA {
			return out, nil, errors.New("選択凍結と許可の不一致")
		}
		if len(fr.Selected) != 1 {
			return out, nil, errors.New("選択は米国後1区分です")
		}
		valid := map[string]string{"NK225_U164_00": "PostUS"}
		for _, c := range configs165() {
			valid[c.ID] = c.Scope
		}
		for scope, id := range fr.Selected {
			if scope != "PostUS" || valid[id] != scope {
				return out, nil, errors.New("凍結選択が米国後固定候補にありません")
			}
		}
		out.Selected = fr.Selected
		out.FreezeSHA = sha
	} else if stage != "train_validation" {
		return out, nil, errors.New("段階名が不正です")
	}
	return out, receipt.Sources, nil
}
