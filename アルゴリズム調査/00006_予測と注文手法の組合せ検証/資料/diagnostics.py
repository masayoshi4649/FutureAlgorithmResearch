"""探索の上位だけで判断せず、乱数・同時刻方向・対応する注文条件を調べる。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import catalog
import research
import single

OUT = Path(__file__).resolve().parent


def seed_diagnostics(prepared: dict, mapping: dict, selected: dict) -> pd.DataFrame:
    """機能: 定刻コインと段階利確を64個の事前連番seedで再評価する。

    引数: prepared/mapping/selected (dict)。返り値: seed別セッション集計 (DataFrame)。
    最良seedの選択・主条件への差し替えは行わない。
    """
    targets = []
    for family in ('O01','O08'):
        choice = selected['群別代表'].get(f'注文主導|{family}', {})
        if choice.get('採用'):
            targets.append(choice['採用']['方式'])
    rows = []
    for key in targets:
        for seed in range(64):
            cfg = dict(mapping[key], seed=seed)
            for (session,symbol), ready in prepared.items():
                if session not in research.COMPLETE:
                    continue
                row, _, _ = research.run_one(ready,cfg)
                rows.append(dict(row, 乱数種=seed, 元方式=key))
    return pd.DataFrame(rows)


def same_time_coin(prepared: dict, mapping: dict, selected: dict) -> pd.DataFrame:
    """機能: 主候補の信号時刻を維持して方向だけ無作為にした比較を行う。

    引数: prepared/mapping/selected (dict)。返り値: seed別セッション集計 (DataFrame)。
    取引時刻は注文の経路依存で変化し得る。これは事後診断であり未見検定ではない。
    """
    targets = [r['採用']['方式'] for p,r in selected['主選択'].items() if p != '注文主導' and r.get('採用')]
    targets += [r['採用']['方式'] for by in selected.get('銘柄別主選択',{}).values()
                for p,r in by.items() if p != '注文主導' and r.get('採用')]
    targets = list(dict.fromkeys(targets))
    rows = []
    for key in targets:
        cfg = mapping[key]
        family_key = cfg.get('signal_family') or cfg['family']
        for seed in range(64):
            rng = np.random.default_rng(seed)
            for (session,symbol), ready in prepared.items():
                if session not in research.COMPLETE or family_key not in ready['families']:
                    continue
                original = ready['families'][family_key]
                shuffled = dict(original, sides=rng.choice(np.array([-1,1], dtype=np.int64), len(original['sides'])))
                fake = dict(ready, families=dict(ready['families'], **{family_key:shuffled}))
                row, _, _ = research.run_one(fake,cfg)
                rows.append(dict(row, 乱数種=seed, 元方式=key))
    return pd.DataFrame(rows)


def paired_effects(frame: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """機能: 他条件を固定した入口・出口・夜間休止の差を全候補で比較する。

    引数: frame (DataFrame)、mapping (dict)。返り値: 対応比較の要約 (DataFrame)。
    """
    f = frame[frame.セッション.isin(research.COMPLETE)].set_index(['方式','セッション','銘柄'])
    pairs = [dict(比較='成行→追跡0.25ATR', old='_E0_', new='_E1_'),
             dict(比較='追跡0.25→0.5ATR', old='_E1_', new='_E2_'),
             dict(比較='追跡0.25→固定逆指値0.25ATR', old='_E1_', new='_E3_'),
             dict(比較='出口一式:1ATR追跡→初期1.5ATR・順行時0.5ATR', old='_X1_', new='_X3_'),
             dict(比較='出口一式:1ATR追跡→追跡2ATR・半分保護', old='_X1_', new='_X4_'),
             dict(比較='出口一式:1ATR追跡→初期1.5ATR・板反対時0.5ATR', old='_X1_', new='_X5_'),
             dict(比較='米国開始前後の新規休止', old='_Z0', new='_Z1')]
    output = []
    for definition in pairs:
        diffs, counts = [], []
        for key in mapping:
            if not key.startswith('H_') or definition['old'] not in key:
                continue
            other = key.replace(definition['old'],definition['new'])
            if other not in mapping:
                continue
            a, b = f.loc[key], f.loc[other]
            joined = a[['収支円','取引数']].join(b[['収支円','取引数']],lsuffix='_前',rsuffix='_後')
            if definition['old']=='_Z0':
                joined = joined[[s.endswith('Night') for s in joined.index.get_level_values(0)]]
            active = (joined.取引数_前+joined.取引数_後)>0
            d = joined.loc[active,'収支円_後']-joined.loc[active,'収支円_前']
            diffs.extend(d.tolist())
            counts.extend((joined.loc[active,'取引数_後']-joined.loc[active,'取引数_前']).tolist())
        x = np.array(diffs)
        output.append(dict(比較=definition['比較'], 有取引対応セル数=len(x), 改善数=int((x>0).sum()),
                           悪化数=int((x<0).sum()), 同値数=int((x==0).sum()),
                           改善比率=float((x>0).mean()) if len(x) else None,
                           差の中央値円=float(np.median(x)) if len(x) else None,
                           差の平均円=float(x.mean()) if len(x) else None,
                           平均取引数差=float(np.mean(counts)) if counts else None,
                           注意='重複する条件セルの記述統計。勝率や有意確率ではない。出口一式の比較は複数パラメータが変わり、短縮だけの効果とは解釈しない。'))
    return pd.DataFrame(output)


def cost_diagnostics(frame: pd.DataFrame) -> pd.DataFrame:
    """機能: 同じ注文経路に対して追加費用だけを0・1・2・4呼値に再採点する。

    引数: frame (DataFrame)。返り値: 費用別収支表 (DataFrame)。
    気配差はどの水準でも含む。損失上限などの注文判断は基本２呼値のまま固定する。
    """
    rows = []
    for row in frame.to_dict('records'):
        value = single.TICKS[row['銘柄']]*single.MULTIPLIERS[row['銘柄']]
        for cost in [0,1,2,4]:
            rows.append(dict(方式=row['方式'], 思想=row['思想'], セッション=row['セッション'], 銘柄=row['銘柄'],
                             往復追加呼値=cost, 取引数=row['取引数'], 未返済数=row['未返済数'],
                             収支円=row['収支円']+(2-cost)*value*row['取引数'],
                             評価損益円=row['評価損益円']+(2-cost)*value*row['未返済数'],
                             条件判断='基本２呼値のまま固定', 気配差を含む=True))
    return pd.DataFrame(rows)


def parameter_neighbors(prepared: dict, mapping: dict, selected: dict) -> pd.DataFrame:
    """機能: 主候補と旧比較の距離・保有時間を一項目ずつ±25%変更する。

    引数: prepared/mapping/selected (dict)。返り値: 近傍条件の保存データ集計 (DataFrame)。
    結果を使った主条件の再選択は行わない。
    """
    targets = [r['採用']['方式'] for r in selected['主選択'].values() if r.get('採用')]
    targets += [r['採用']['方式'] for by in selected.get('銘柄別主選択',{}).values()
                for r in by.values() if r.get('採用')]
    targets += selected.get('固定比較ID',[])
    rows = []
    for key in dict.fromkeys(targets):
        original = mapping[key]
        for field in ['entry_offset','initial_stop_atr','trail_atr','holding_min','gap_atr','basket_stop_atr']:
            value = original.get(field)
            if value is None or not np.isfinite(value) or value <= 0:
                continue
            for ratio in [.75,1.25]:
                cfg = dict(original, **{field:value*ratio})
                for (session,symbol), ready in prepared.items():
                    if session not in research.COMPLETE:
                        continue
                    row, _, _ = research.run_one(ready,cfg)
                    rows.append(dict(row, 元方式=key, 変更項目=field, 倍率=ratio, 元値=value, 変更値=value*ratio))
    return pd.DataFrame(rows)


def main() -> None:
    """機能: 保存済み再生入力だけを使って追加診断を作る。

    引数: なし。返り値: なし (None)。追加ネットワーク取得・条件再選択なし。
    """
    with (OUT/'再生入力.pkl').open('rb') as stream:
        prepared = pickle.load(stream)
    mapping = {c['id']:c for c in catalog.configs()}
    selected = json.loads((OUT/'最終選択.json').read_text(encoding='utf-8'))
    frame = pd.read_csv(OUT/'全条件_セッション集計.csv')
    seed_diagnostics(prepared,mapping,selected).to_csv(OUT/'定刻コイン_64種.csv',index=False,encoding='utf-8-sig')
    same_time_coin(prepared,mapping,selected).to_csv(OUT/'信号時刻固定_方向64種.csv',index=False,encoding='utf-8-sig')
    paired_effects(frame,mapping).to_csv(OUT/'入口と出口の対応比較.csv',index=False,encoding='utf-8-sig')
    cost_diagnostics(frame).to_csv(OUT/'追加費用0_1_2_4呼値.csv',index=False,encoding='utf-8-sig')
    parameter_neighbors(prepared,mapping,selected).to_csv(OUT/'主候補の一変数近傍.csv',index=False,encoding='utf-8-sig')
    print('乱数と対応比較の診断を保存しました。主条件の変更はありません。',flush=True)


if __name__ == '__main__':
    main()
