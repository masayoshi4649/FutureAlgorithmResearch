package execution

import "time"

// RegisterSessionReport はAPIで確定した立会終了時刻をレポート台帳へ保存します。
//
// 引数: session(string)は場ID、end(time.Time)は返済開始時刻ではなく立会終了時刻です。
// 返り値: errorは登録失敗です。商品とモードはこの注文台帳の値を使用します。
func (m *Manager) RegisterSessionReport(session string, end time.Time) error {
	return m.store.RegisterReportSession(session, m.state.DryRun, m.state.Symbol, end)
}

// FinalizeReports は照合済みの終了場を共通ログ領域へ出力します。
//
// 引数: logRoot(string)は全商品共通のログ領域、now(time.Time)は現在時刻です。
// 返り値: errorは保存失敗です。未確定注文や戦略へ未通知の約定があれば延期します。
func (m *Manager) FinalizeReports(logRoot string, now time.Time) error {
	if m.HasPending() || len(m.OutstandingFills()) != 0 {
		return nil
	}
	return m.store.FinalizeReports(logRoot, now)
}
