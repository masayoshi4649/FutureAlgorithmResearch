"""選択済み条件の周辺と、費用ゼロ探索の分布を学習区間だけで確認する。"""

from __future__ import annotations

import json

import pandas as pd

import research


def main() -> None:
    """機能: 全体分布、旧比較、主候補の入口・出口近傍を既存結果から抽出する。

    引数: なし。返り値: None。条件の再選択、保留データの開封、通信はしない。
    """
    folder = research.OUT
    frame = pd.read_csv(folder/'全条件_セッション集計.csv')
    configs = json.loads((folder/'条件一覧.json').read_text(encoding='utf-8'))
    mapping = {c['id']: c for c in configs}
    selected = json.loads((folder/'最終選択.json').read_text(encoding='utf-8'))
    columns = ['profit_yen', 'loss_yen', 'closed_net_yen', 'open_yen', 'closed_count', 'win_count',
               'ideal_fill_gap_count', 'ideal_fill_benefit_yen']
    summed = frame.groupby(['方式', '思想', '新旧', '系統', '銘柄'])[columns].sum().reset_index()
    summed['勝率'] = summed['win_count'] / summed['closed_count'].replace(0, float('nan'))
    summed.to_csv(folder/'学習６セッションの全方式合計.csv', index=False, encoding='utf-8-sig')
    distribution = []
    for (symbol, philosophy, origin), part in summed.groupby(['銘柄', '思想', '新旧']):
        active = part[part['closed_count'] > 0]
        distribution.append(dict(銘柄=symbol, 思想=philosophy, 新旧=origin, 条件数=len(part),
                                 有取引条件数=len(active), 黒字条件数=int((active.closed_net_yen > 0).sum()),
                                 最良探索収支円=float(active.closed_net_yen.max()) if len(active) else None,
                                 中央収支円=float(active.closed_net_yen.median()) if len(active) else None))
    research.save(folder/'探索分布.json', distribution)

    # ----------------------------------------
    comparisons = []
    fields = ['entry_mode', 'entry_atr', 'initial_stop_atr', 'target_atr', 'trail_atr', 'trail_start_atr',
              'tighten_trigger_atr', 'tighten_width_atr', 'protect_trigger_atr', 'protect_fraction',
              'weak_width_atr', 'state_trigger_atr', 'us_pause']
    for symbol, choice in selected['主候補'].items():
        key = choice['採用']['方式']
        cfg = mapping[key]
        for other in configs:
            if other['family'] != cfg['family'] or other.get('signal_multiplier', 1) != cfg.get('signal_multiplier', 1):
                continue
            if other['philosophy'] != cfg['philosophy']:
                continue
            differing = [name for name in fields if other.get(name) != cfg.get(name)]
            if len(differing) > 3:
                continue
            rows = summed[summed['方式'].eq(other['id']) & summed['銘柄'].eq(symbol)]
            comparisons.append(dict(主候補=key, 変更項目='・'.join(differing) or '同条件',
                                     条件=other['label'], **rows.iloc[0].to_dict()))
    pd.DataFrame(comparisons).to_csv(folder/'主候補の設定近傍.csv', index=False, encoding='utf-8-sig')
    summed[summed['方式'].isin(selected['固定比較'])].to_csv(folder/'既存固定比較.csv', index=False, encoding='utf-8-sig')
    manifest = json.loads((folder/'実行前記録.json').read_text(encoding='utf-8'))
    import hashlib
    unchanged = {name: hashlib.sha256((folder/name).read_bytes()).hexdigest() == expected
                 for name, expected in manifest['SHA256'].items()}
    assert all(unchanged.values()), unchanged
    research.save(folder/'学習実行ソースの不変確認.json', dict(全一致=True, ファイル=unchanged,
                  保留日中未開封=not (folder/'最終保留開封監査.json').exists()))
    print(json.dumps(dict(全方式銘柄数=len(summed), 主候補近傍数=len(comparisons), 学習ソース一致=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
