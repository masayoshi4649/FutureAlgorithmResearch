//go:build windows

package runner

import (
	"fmt"
	"golang.org/x/sys/windows"
	"os"
	"path/filepath"
)

type processLock struct {
	file    *os.File
	overlap windows.Overlapped
}

// lockDirectory はOSロックで同一保存先の二重起動を拒否します。
//
// 引数: directory string。保存先。
// 返り値: *processLock と error。プロセス終了時にはOSが解放します。
func lockDirectory(directory string) (*processLock, error) {
	if err := os.MkdirAll(directory, 0755); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(directory, ".e01.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	l := &processLock{file: f}
	if err = windows.LockFileEx(windows.Handle(f.Fd()), windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &l.overlap); err != nil {
		f.Close()
		return nil, fmt.Errorf("同じ保存先で既にE01が動作中です: %w", err)
	}
	return l, nil
}

// Close はロックを解放します。
//
// 引数: なし。返り値: error。ファイル終了エラー。
func (l *processLock) Close() error { return l.file.Close() }
