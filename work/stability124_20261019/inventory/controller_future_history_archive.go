package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

// enqueueArchive は、終了済みセッションを複製せず保存待ちへ移します。
//
// 引数: state *futureHistorySession: これ以降書き込まないセッション。
// 返り値: なし。生データがないセッションのファイルは作りません。
func (manager *futureHistoryManager) enqueueArchive(state *futureHistorySession) {
	var records uint64
	for _, product := range state.products {
		records += product.head.Load().sequence
	}
	if records == 0 {
		return
	}
	manager.queueMu.Lock()
	manager.pending = append(manager.pending, state)
	manager.queueMu.Unlock()
	select {
	case manager.wake <- struct{}{}:
	default:
	}
}

// archiveLoop は、書き手から独立して終了済みセッションを順番に保存します。
//
// 引数: なし。
// 返り値: なし。保存失敗時はメモリを保持し30秒後に再試行します。
func (manager *futureHistoryManager) archiveLoop() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-manager.stop:
			return
		case <-manager.wake:
		case <-ticker.C:
		}
		for manager.archiveNext() {
			select {
			case <-manager.stop:
				return
			default:
			}
		}
	}
}

// archiveNext は、保存成功した先頭領域への参照を確実に取り除きます。
//
// 引数: なし。
// 返り値: bool: １セッションの保存が完了した場合true。
func (manager *futureHistoryManager) archiveNext() bool {
	manager.queueMu.Lock()
	if len(manager.pending) == 0 {
		manager.queueMu.Unlock()
		return false
	}
	state := manager.pending[0]
	manager.queueMu.Unlock()
	err := manager.archive(state)
	manager.queueMu.Lock()
	defer manager.queueMu.Unlock()
	if err != nil {
		manager.lastArchiveError = err.Error()
		return false
	}
	manager.lastArchiveError = ""
	manager.pending[0] = nil
	manager.pending = manager.pending[1:]
	if len(manager.pending) == 0 {
		manager.pending = nil
	}
	return true
}

// archiveSession は、生JSONと１分・５分足を銘柄別の指定パスへ保存します。
//
// 引数: state *futureHistorySession: 変更が完了した保存対象。
// 返り値: error: 保存先作成・書き込み・既存ファイルとの衝突時のエラー。
func (manager *futureHistoryManager) archiveSession(state *futureHistorySession) error {
	for _, code := range state.productCodes() {
		product := state.products[code]
		head := product.head.Load()
		if head.sequence == 0 {
			continue
		}
		path := filepath.Join(manager.root, "book", code, state.id+".jsonl")
		if err := writeFutureHistoryFile(path, func(writer io.Writer) error {
			buffer := bufio.NewWriterSize(writer, 64*1024)
			for minute := head.firstMinute; minute <= head.lastMinute; minute++ {
				chunks := make([]*futureHistoryChunk, 0, 16)
				for chunk := product.raw[minute].Load(); chunk != nil; chunk = chunk.previous {
					chunks = append(chunks, chunk)
				}
				for index := len(chunks) - 1; index >= 0; index-- {
					for _, record := range chunks[index].records {
						if _, err := buffer.Write(record.payload); err != nil {
							return err
						}
						if err := buffer.WriteByte('\n'); err != nil {
							return err
						}
					}
				}
			}
			return buffer.Flush()
		}); err != nil {
			return err
		}
		for _, interval := range []int{1, 5} {
			path = filepath.Join(manager.root, fmt.Sprintf("candle_%dmin", interval), code, state.id+".csv")
			if err := writeFutureHistoryFile(path, func(writer io.Writer) error {
				return writeFutureHistoryCandles(writer, product, interval)
			}); err != nil {
				return err
			}
		}
	}
	return nil
}

// writeFutureHistoryCandles は、確定済みの足をCSVへ順番に書き出します。
//
// 引数:
//   - output io.Writer: CSV出力先。
//   - product *futureHistoryProduct: 保存専用になった銘柄領域。
//   - interval int: １または５。
//
// 返り値: error: 出力エラー。
func writeFutureHistoryCandles(output io.Writer, product *futureHistoryProduct, interval int) error {
	writer := csv.NewWriter(output)
	if err := writer.Write([]string{"time", "open", "high", "low", "close", "volume", "volume_complete", "closed"}); err != nil {
		return err
	}
	count, slots := product.head.Load().count1, &product.one
	if interval == 5 {
		count, slots = product.head.Load().count5, &product.five
	}
	for index := 0; index < count; index++ {
		candle := slots[index].Load()
		row := []string{candle.Time.Format(time.RFC3339),
			strconv.FormatFloat(candle.Open, 'f', -1, 64), strconv.FormatFloat(candle.High, 'f', -1, 64),
			strconv.FormatFloat(candle.Low, 'f', -1, 64), strconv.FormatFloat(candle.Close, 'f', -1, 64),
			strconv.FormatFloat(candle.Volume, 'f', -1, 64), strconv.FormatBool(candle.VolumeComplete), strconv.FormatBool(candle.Closed)}
		if err := writer.Write(row); err != nil {
			return err
		}
	}
	writer.Flush()
	return writer.Error()
}

// writeFutureHistoryFile は、一時ファイルを完成させてから公開します。
// 再試行で既に同一内容がある場合は成功し、異なる既存内容は上書きしません。
//
// 引数:
//   - path string: 公開するファイルパス。
//   - write func(io.Writer) error: 内容を書き込む関数。
//
// 返り値: error: 出力または既存内容との衝突エラー。
func writeFutureHistoryFile(path string, write func(io.Writer) error) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	file, err := os.CreateTemp(filepath.Dir(path), ".history-*.tmp")
	if err != nil {
		return err
	}
	temporary := file.Name()
	defer os.Remove(temporary)
	if err = write(file); err != nil {
		file.Close()
		return err
	}
	if err = file.Sync(); err != nil {
		file.Close()
		return err
	}
	if err = file.Close(); err != nil {
		return err
	}
	if _, err = os.Stat(path); err == nil {
		oldHash, oldErr := futureHistoryFileHash(path)
		newHash, newErr := futureHistoryFileHash(temporary)
		if oldErr != nil {
			return oldErr
		}
		if newErr != nil {
			return newErr
		}
		if oldHash == newHash {
			return nil
		}
		return fmt.Errorf("既存の履歴と内容が異なるため上書きしません: %s", path)
	} else if !os.IsNotExist(err) {
		return err
	}
	// 完成したファイルへのハードリンクを排他的に作り、部分ファイルを公開しません。
	if err = os.Link(temporary, path); err != nil {
		return fmt.Errorf("履歴ファイルを公開できません: %w", err)
	}
	return nil
}

// futureHistoryFileHash は、全内容をメモリへ読み込まずSHA256を計算します。
//
// 引数: path string: 比較するファイル。
// 返り値:
//   - [32]byte: ファイル内容のSHA256。
//   - error: 読み取りエラー。
func futureHistoryFileHash(path string) ([32]byte, error) {
	var result [32]byte
	file, err := os.Open(path)
	if err != nil {
		return result, err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err = io.Copy(hash, file); err != nil {
		return result, err
	}
	copy(result[:], hash.Sum(nil))
	return result, nil
}
