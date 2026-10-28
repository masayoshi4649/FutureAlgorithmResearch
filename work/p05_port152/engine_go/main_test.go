package main

import (
	"os"
	"path/filepath"
	"testing"
)

// TestRegistrationRequiresBoth は登録受領の片方成功だけでは金融再生を許可しません。
//
// 引数: t(*testing.T)。返り値: なし。原資料や約定を再生しません。
func TestRegistrationRequiresBoth(t *testing.T) {
	for _, test := range []struct {
		text string
		okay bool
	}{{`{"registered":true,"returncode":0}`, true}, {`{"registered":false,"returncode":0}`, false}, {`{"registered":true,"returncode":1}`, false}, {`{"registered":true}`, false}} {
		path := filepath.Join(t.TempDir(), "受領.json")
		if err := os.WriteFile(path, []byte(test.text), 0600); err != nil {
			t.Fatal(err)
		}
		if got := registrationOK(path) == nil; got != test.okay {
			t.Fatal("登録検査が不正", test.text, got)
		}
	}
}
