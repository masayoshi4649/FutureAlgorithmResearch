"""会計の不整合を隠さず、現在の作業段階を資料へ表示する。"""

from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'アルゴリズム調査/00033_復元方式の自動選択と改善8条件の反証'


def main() -> None:
    """機能: 調査案内へ限定改訂の経緯と比較規則を追記する。

    引数: なし。返り値: なし (None)。売買資料を変更しない。
    """
    path=OUT/'README.md';text=path.read_text(encoding='utf-8')
    notice='''

## 会計検査の限定改訂

初回再生は、遅延条件を旧会計が「場末判断の次観測で全返済」と誤判定して中断しました。実例は15:35:00判断・1秒遅延・15:35:01返済で、終場15:45より前でした。

売買・入力・損益計算・採否を変更せず、会計の場末境界2検査だけを固定済みの契約へ合わせます。旧158条件の全資料を保存し、全974条件を再計算して旧158の台帳・全経済値が一致することも要求します。

- [失敗の限定再現](../../work/wave_v38/adaptive_cash_revision_failure_v1.json)
- [独立した境界確認](../../work/wave_v38/adaptive_close_boundary_review.md)
- [改訂前の全資料と再比較規則](../../work/wave_v38/adaptive_cash_revision_plan.json)
'''
    if '## 会計検査の限定改訂' not in text:text+=notice
    path.write_text(text,encoding='utf-8')
    print('初回中断の経緯と、旧結果同値確認の規則を明記。')


if __name__=='__main__':main()
