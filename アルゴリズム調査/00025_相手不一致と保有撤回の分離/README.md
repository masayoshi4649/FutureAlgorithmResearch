# 作業00025：相手不一致と保有撤回

最初に見るファイルは [相手不一致と保有撤回](相手不一致と保有撤回.html) です。

読む順序：
1. 主報告の短い結論と全入口の対応比較。
2. 手法を選び、TOPIXミニ／NKマイクロの全玉・週別・13セッション損益。
3. ５分足図（生成後）で新規・返済と入口／保有方向の違い。
4. [結果前の設計](../../work/wave_v30/管理設計の固定.json)、[反証規則](../../work/wave_v30/反証規則の固定.json)、work/wave_v30内の構造・比較・会計監査。

詳しい根拠：[構造と先読み検査](../../work/wave_v30/context_structure_audit.md)、[全件の対応比較](../../work/wave_v30/context_comparison.md)、[最初の返済分岐](../../work/wave_v30/context_cause_summary.md)、[全84の独立会計](../../work/wave_v30/all_accounting_audit.md)、[選抜の整合性](../../work/wave_v30/選抜整合の監査.json)、[改良なしと解なしの区別](../../work/wave_v30/次段階の敵対整理.md)。

初回TOPIX5枚／NK10枚、片方向同時上限10／20枚。費用0、指定価格約定。大きい契約の原本を小型契約倍率へ換算している。損失玉を含め全玉を場内返済する。

全84は既知13セッションの限定診断。現在APIと保存済み9月29日ナイト21時のデータは使わない。候補採用と診断の完了を区別する。

再現：プロジェクトルートで `python -X utf8 work/wave_v30/verify_replay.py --run --workers 12`。固定元と既存結果の指紋・集計を照合してから再実行する。反証・指定波・独立監査を完了してから `python -X utf8 work/wave_v30/select_verified.py`、`python -X utf8 work/wave_v30/report_round6.py`。凍結コードに差があれば停止する。
