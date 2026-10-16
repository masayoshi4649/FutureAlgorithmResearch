"""出口と再参加の効果を分け、全場成績と問題の夜間を同じ会計で比較する。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import pickle

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
BASE = 'E01_G_U'
JST = timezone(timedelta(hours=9))


def read(path):
    """
    機能: 完了した計算資料を読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def summary(result, symbol, period='全30'):
    """
    機能: 同一商品の比較に必要な料金後指標を抽出する。
    引数: result(dict)、symbol/period(str)。
    返り値: dict。
    """
    value = result['periods'][period][symbol]
    fields = ('net', 'gross', 'fees', 'campaign_profit', 'campaign_loss', 'campaign_profit_share',
              'campaigns', 'campaign_wins', 'positive_sessions', 'max_drawdown', 'new_lots',
              'worst_session', 'best_session_removed')
    output = {k: value[k] for k in fields}
    output['収支下落比'] = value['net'] / value['max_drawdown'] if value['max_drawdown'] else 0.
    return output


def dominates(value, baseline):
    """
    機能: 収支・利益割合・黒字場数・最大下落が両立して改善したかを判定する。
    引数: value/baseline(dict)。
    返り値: bool。同値だけの基準自身は改善に含めない。
    """
    diffs = [value['net']-baseline['net'], value['campaign_profit_share']-baseline['campaign_profit_share'],
             value['positive_sessions']-baseline['positive_sessions'], baseline['max_drawdown']-value['max_drawdown']]
    return min(diffs) >= -1e-9 and max(diffs) > 1e-9


def ledger_summary(path, session):
    """
    機能: 買売別成績と指定夜間の各取引を保存台帳から集計する。
    引数: path(Path)、session(str)。
    返り値: dict。
    """
    with path.open('rb') as stream:
        ledgers = pickle.load(stream)
    groups = {s: {1: [], -1: []} for s in SYMBOLS}
    cases = {}
    for (name, symbol), ledger in ledgers.items():
        cycle_groups = defaultdict(list)
        for trade in ledger['net_trades']:
            cycle_groups[trade['組']].append(trade)
        for trades in cycle_groups.values():
            groups[symbol][trades[0]['方向']].append(float(sum(t['収支'] for t in trades)))
        if name == session:
            cases[symbol] = [dict(組=int(identifier), 方向='買い' if trades[0]['方向'] > 0 else '売り',
                新規=datetime.fromtimestamp(trades[0]['新規時刻'], JST).isoformat(),
                新規原本行=int(trades[0]['新規原本行']), 建値=float(trades[0]['建値']), 収支=float(sum(t['収支'] for t in trades)),
                返済=[dict(時刻=datetime.fromtimestamp(t['返済時刻'], JST).isoformat(),
                    枚数=int(t['枚数']), 価格=float(t['返済値']), 理由=int(t['理由']), 収支=float(t['収支']))
                       for t in trades]) for identifier, trades in cycle_groups.items()]
    sides = {s: {('買い' if side > 0 else '売り'): dict(組数=len(values), 黒字組数=sum(v > 0 for v in values),
            利益=sum(max(v, 0) for v in values), 損失=sum(max(-v, 0) for v in values), 収支=sum(values))
                  for side, values in group.items()} for s, group in groups.items()}
    return dict(方向別=sides, 対象夜間=session, 夜間各取引=cases)


def main():
    """
    機能: 全条件の効果を集計し、既知期間内の比較として保存する。
    引数: なし。
    返り値: None。
    """
    fixed = read(WORK / '事前固定.json')
    extra_path = WORK / 'phase2/事前固定.json'
    extra = read(extra_path) if extra_path.exists() else None
    configs = fixed['catalog'] + (extra['catalog'] if extra else [])
    locations = {c['id']: WORK for c in fixed['catalog']}
    if extra:
        locations.update({c['id']: WORK / 'phase2' for c in extra['catalog']})
    results = {m: {c['id']: read(locations[c['id']] / m / 'results' / (c['id']+'.json'))
                   for c in configs} for m in fixed['models']}
    comparison, ranks = {}, {}
    for model, values in results.items():
        stats = {identifier: {s: summary(value, s) for s in SYMBOLS} for identifier, value in values.items()}
        ordered = sorted(values, key=lambda i: min(stats[i][s]['収支下落比'] for s in SYMBOLS), reverse=True)
        ranks[model] = ordered
        comparison[model] = []
        for identifier in ordered:
            stat = stats[identifier]
            improvement = {s: dominates(stat[s], stats[BASE][s]) for s in SYMBOLS}
            comparison[model].append(dict(id=identifier, name=values[identifier]['config']['name'], 商品別=stat,
                基準四指標改善=improvement, 両商品四指標改善=all(improvement.values()),
                期間別={period: {s: summary(values[identifier], s, period) for s in SYMBOLS}
                       for period in ('前16', '後14')},
                問題夜間={r['symbol']: r for r in values[identifier]['rows'] if r['session'] == '2026-09-24_Night'}))
    # ----------------------------------------
    # 出口を固定した時計比較と時計を固定した出口比較を別々に保持する。
    mapping = {(c['exit_id'], c['clock_id']): c['id'] for c in configs}
    pairs = []
    for model, values in results.items():
        for exit_id in ('T0', 'T1', 'T2', 'T3', 'T4'):
            for clock in ('A5', 'A1', 'A0') + (('P1', 'P0') if extra else ()):
                before, after = mapping[exit_id, 'S'], mapping[exit_id, clock]
                for symbol in SYMBOLS:
                    a, b = summary(values[before], symbol), summary(values[after], symbol)
                    pairs.append(dict(model=model, 比較='再参加時計', before=before, after=after, symbol=symbol,
                                      差={k: b[k]-a[k] for k in a}))
        for clock in ('S', 'A5', 'A1', 'A0') + (('P1', 'P0') if extra else ()):
            for exit_id in ('T1', 'T2', 'T3', 'T4'):
                before, after = mapping['T0', clock], mapping[exit_id, clock]
                for symbol in SYMBOLS:
                    a, b = summary(values[before], symbol), summary(values[after], symbol)
                    pairs.append(dict(model=model, 比較='出口', before=before, after=after, symbol=symbol,
                                      差={k: b[k]-a[k] for k in a}))
    best_modified = next(i for i in ranks['observed'] if i != BASE)
    chosen = list(dict.fromkeys([BASE, 'T2_S', 'T3_A1']+(['T2_P1', 'T2_P0', 'T3_P1'] if extra else [])+[best_modified]))
    diagnostic_ids = list(dict.fromkeys(chosen+['T1_S', 'T2_S', 'T3_S', 'T4_S']))
    diagnostics = {i: ledger_summary(locations[i] / 'observed/ledgers' / (i+'.pkl'), '2026-09-24_Night') for i in diagnostic_ids}
    same_entry = {i: [t for t in diagnostics[i]['夜間各取引']['TOPIX'] if t['新規原本行'] == 151579]
                  for i in (BASE, 'T1_S', 'T2_S', 'T3_S', 'T4_S')}
    regime_source = read(ROOT / 'work/wave_v85/analysis/方向偏り独立確認.json')
    regime_groups = [r for r in regime_source['regime_results']
                     if r['model'] == 'observed' and r['classification'] == 'regime']
    regimes = []
    for identifier in diagnostic_ids:
        for group in regime_groups:
            subset = [r for r in results['observed'][identifier]['rows']
                      if r['symbol'] == group['symbol'] and r['session'] in group['sessions']]
            assert len(subset) == group['session_count']
            net = sum(r['net'] for r in subset)
            regimes.append(dict(id=identifier, symbol=group['symbol'], 区分=group['regime'],
                場数=len(subset), 黒字場数=sum(r['net'] > 0 for r in subset), 収支=net,
                最大一場除外=net-max(r['net'] for r in subset)))
    output = dict(条件数=len(configs), 入力='既知30場。各条件を全場で再生。後半は未見検証ではない。',
        主仮説='T3_A1', 追加仮説='T3_P1' if extra else None,
        観測価格参考首位=ranks['observed'][0], 最良改修候補=best_modified, ランキング基準=fixed['specification']['評価'],
        比較=comparison, 順位=ranks, 部品比較=pairs, 詳細表示=chosen, 取引診断=diagnostics,
        九月二十五日三時三十七分の同一入口比較=same_entry,
        相場区分='セッションの保存始終値の変化が±0.1%以内を横ばいとする事後診断。売買判定には使わない。',
        相場別=regimes,
        入力SHA256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for model in fixed['models'] for location in set(locations.values())
                      for p in (location / model / 'results').glob('*.json')})
    (HERE / '比較結果.json').write_text(json.dumps(output, ensure_ascii=False, allow_nan=False, indent=2)+'\n', encoding='utf-8')
    for model in fixed['models']:
        print(model)
        for item in comparison[model]:
            print(item['id'], [(s, round(v['net']), round(v['campaign_profit_share']*100, 1),
                               v['positive_sessions'], round(v['max_drawdown']), v['campaigns'])
                              for s, v in item['商品別'].items()], '両改善', item['両商品四指標改善'])


if __name__ == '__main__':
    main()
