"""主候補の条件と適用範囲を一つの参照ファイルへまとめる。"""

import json
from pathlib import Path


def main() -> None:
    """機能: 既存の選択結果を変更せず、主候補の実行設定を抽出する。

    引数: なし。返り値: なし (None)。実際の注文送信は行わない。
    """
    root = Path(__file__).resolve().parent
    selection = json.loads((root / '選択結果.json').read_text(encoding='utf-8'))
    rows = json.loads((root / '週比較.json').read_text(encoding='utf-8'))
    selected = next(row for row in rows if row['id'] == selection['primary'])
    spec = next(row for row in json.loads((root / '信号条件一覧.json').read_text(encoding='utf-8')) if row['id'] == selected['signal_id'])
    payload = dict(候補ID=selected['id'], 原手法='M3_逆_A00', 信号条件=spec,
                   元からの変更=selected['changes'], 一枚でのエンジン設定=selected['config'],
                   枚数='一度に固定した整数枚数で新規し、全枚数を返済。増玉・部分返済・両建てなし。',
                   同時保有上限={'TOPIXミニ': 10, 'NK225マイクロ': 20},
                   枚数変更='エンジン設定のinitial_qtyとaudit_capを同じ整数へ変更。全許容枚数で経路と損益比例を監査済み。',
                   ATR='確定５分足TRを係数1/12で平滑化。最低３本。注文設定時のATRを組の終了まで固定。',
                   新規受付='開始20分経過後。日中15:05・夜間翌05:20で受付終了。方向根拠の確定待ちも必要。',
                   場末返済='日中15:35・夜間翌05:50以降の観測で返済を予約し、次の有効な原本行で全返済。',
                   約定='前行までに決めた注文のみ次行以降で有効。費用０・指定価格。設置時に通過済みの出口は次行実価格。',
                   検証範囲='保存済み既知の2026-09-21日中〜09-25夜間。新しい期間での検証ではない。',
                   注意='360分は最長保有時間。損切り・追跡・場末による返済はそれ以前にも行う。実注文接続は含まない。')
    (root / '主候補の条件.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
