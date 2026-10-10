# 独立監査の読み順

最初に [独立監査まとめ.md](独立監査まとめ.md) を参照してください。

1. [管理の合成検査.json](管理の合成検査.json)：次行約定・半減・保護・連敗休止。
2. [特徴の独立検査.json](特徴の独立検査.json)：現在足除外・ATR・山谷・未来改変。
3. [入口と選択の独立検査.json](入口と選択の独立検査.json)：十二入口と自動選択の未来不変性。
4. [売買会計の独立検査.json](売買会計の独立検査.json)：全 2,300 口座の会計と数量。
5. [中値再評価の独立検査.json](中値再評価の独立検査.json)：約定基準だけを変えた感度。
6. [HTML表示の独立検査.json](HTML表示の独立検査.json)：全表示切替と図。

再実行はプロジェクトルートで行います。検査は原本・既存結果を変更せず、このフォルダへ証跡を保存します。

```powershell
python -X utf8 work/wave_v53/review/check_engine.py
python -X utf8 work/wave_v53/review/check_features.py
python -X utf8 work/wave_v53/review/check_signals.py
python -X utf8 work/wave_v53/review/check_accounts.py
python -X utf8 work/wave_v53/review/check_mid_evaluation.py
python -X utf8 work/wave_v53/review/verify_report.py --links
```

表示検査はローカル Chrome をネットワーク遮断プロキシ付きで起動します。既存作業の描画補助関数を読み取り利用しますが、そのファイルは変更しません。
