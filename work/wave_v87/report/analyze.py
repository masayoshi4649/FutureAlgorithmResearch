"""原因に基づく各改修を、同じ料金後会計と既知全期間で比較する。"""

from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
BASE = 'E01_G_U'


def read(path):
    """
    機能: 完成済みの日本語JSONを読み取る。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 集計元の内容指紋を作る。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(result, symbol, period='全30'):
    """
    機能: 商品を合算せず、利益と損失の比率・収支・活動と下落を取り出す。
    引数: result(dict)、symbol/period(str)。
    返り値: dict。
    """
    source = result['periods'][period][symbol]
    fields = ('net', 'gross', 'fees', 'campaign_profit', 'campaign_loss',
              'campaign_profit_share', 'campaign_pf', 'campaigns', 'campaign_wins',
              'positive_sessions', 'negative_sessions', 'no_trade_sessions',
              'max_drawdown', 'best_session_removed', 'worst_session', 'new_lots')
    value = {key: source[key] for key in fields}
    value['収支下落比'] = source['net'] / source['max_drawdown'] if source['max_drawdown'] else 0.
    value['金額八割'] = source['campaign_profit_share'] is not None and source['campaign_profit_share'] >= .8
    return value


def improved(current, baseline):
    """
    機能: 四指標が両立して基準以上で、少なくとも一つが改善したか確認する。
    引数: current/baseline(dict)。
    返り値: bool。
    """
    if current['campaign_profit_share'] is None:
        return False
    diffs = [current['net'] - baseline['net'],
             current['campaign_profit_share'] - baseline['campaign_profit_share'],
             current['positive_sessions'] - baseline['positive_sessions'],
             baseline['max_drawdown'] - current['max_drawdown']]
    return min(diffs) >= -1e-8 and max(diffs) > 1e-8


def collect():
    """
    機能: 各改修の全固定条件と指定約定結果が揃った段階だけを比較へ加える。
    引数: なし。
    返り値: tuple[dict,dict,list,dict]。結果・所在・段階状態・指紋。
    """
    locations = {BASE: ROOT / 'work/wave_v86', 'T2_S': ROOT / 'work/wave_v86',
                 'T2_P1': ROOT / 'work/wave_v86/phase2'}
    available_models = {identifier: ('observed', 'specified') for identifier in locations}
    stages = []
    for stage in sorted(WORK.glob('round[0-9]*'), key=lambda path: int(path.name[5:])):
        fixed_path = stage / '事前固定.json'
        if not fixed_path.exists():
            stages.append(dict(段階=stage.name, 状態='条件実装・監査中'))
            continue
        fixed = read(fixed_path)
        complete = all((stage / model / 'results' / (c['id']+'.json')).exists()
                       for model in fixed['models'] for c in fixed['catalog'])
        stop_path = stage / '停止理由.json'
        state = '全場計算済み' if complete else '全場計算中'
        if stop_path.exists():
            assert not complete
            state = read(stop_path)['状態']+'（round6で同条件を再評価）'
        stages.append(dict(段階=stage.name, 状態=state,
                           条件数=len(fixed['catalog']), 仕様=fixed['specification'],
                           固定指紋=sha(fixed_path)))
        if complete:
            for name, digest in fixed['code_SHA256'].items():
                assert sha(ROOT / name) == digest, name
            for config in fixed['catalog']:
                assert config['id'] not in locations
                locations[config['id']] = stage
                available_models[config['id']] = tuple(fixed['models'])
    results, hashes = {}, {}
    for model in ('observed', 'specified'):
        results[model] = {}
        for identifier, folder in locations.items():
            if model not in available_models[identifier]:
                continue
            path = folder / model / 'results' / (identifier+'.json')
            value = read(path)
            assert len(value['rows']) == 60
            assert value['config']['id'] == identifier and value['model'] == model
            for row in value['rows']:
                assert abs(row['campaign_profit']-row['campaign_loss']-row['net']) < 1e-7
                assert abs(row['gross']-row['fees']-row['net']) < 1e-7
                assert row['new_lots'] == row['exit_lots']
                assert row['residual_long'] == row['residual_short'] == 0
            for symbol in SYMBOLS:
                rows = [r for r in value['rows'] if r['symbol'] == symbol]
                assert len(rows) == 30
                for field in ('net', 'campaign_profit', 'campaign_loss', 'fees', 'campaigns'):
                    assert abs(sum(r[field] for r in rows)-value['periods']['全30'][symbol][field]) < 1e-7
            results[model][identifier] = value
            hashes[str(path.relative_to(ROOT))] = sha(path)
    return results, locations, stages, hashes


def main():
    """
    機能: 未達を隠さず、対照・主仮説・全条件・前後半を一つの比較へまとめる。
    引数: なし。
    返り値: None。比較結果JSONを更新する。取引条件は変更しない。
    """
    results, locations, stages, hashes = collect()
    regime_source = ROOT / 'work/wave_v85/analysis/方向偏り独立確認.json'
    regime_groups = [r for r in read(regime_source)['regime_results']
                     if r['model'] == 'observed' and r['classification'] == 'regime']
    summary = {}
    for model, values in results.items():
        baseline = {s: metrics(values[BASE], s) for s in SYMBOLS}
        rows = []
        for identifier, result in values.items():
            stat = {s: metrics(result, s) for s in SYMBOLS}
            source_id = result['config'].get('round3_id', result['config'].get('source_id', BASE))
            parent = values.get(source_id, values[BASE])
            row = dict(id=identifier, 名前=result['config']['name'], 段階=locations[identifier].name,
                       商品別=stat, 比較元=source_id,
                       比較元との差={s: {k: stat[s][k]-metrics(parent, s)[k]
                                      for k in ('net', 'fees', 'campaign_profit', 'campaign_loss',
                                                'campaigns', 'positive_sessions', 'max_drawdown')}
                                     for s in SYMBOLS},
                       期間別={p: {s: metrics(result, s, p) for s in SYMBOLS} for p in ('前16', '後14')},
                       両商品四指標改善=all(improved(stat[s], baseline[s]) for s in SYMBOLS),
                       両商品八割=all(stat[s]['金額八割'] and stat[s]['net'] > 0 for s in SYMBOLS))
            stability = {}
            for symbol in SYMBOLS:
                sessions = [r for r in result['rows'] if r['symbol'] == symbol]
                ordered = sorted((r['net'] for r in sessions), reverse=True)
                groups = {}
                for group in regime_groups:
                    if group['symbol'] != symbol:
                        continue
                    subset = [r for r in sessions if r['session'] in group['sessions']]
                    assert len(subset) == group['session_count']
                    groups[group['regime']] = dict(場数=len(subset), 黒字場数=sum(r['net']>0 for r in subset),
                                                  収支=sum(r['net'] for r in subset))
                stability[symbol] = dict(最大利益三場除外収支=sum(ordered[3:]), 相場別=groups,
                    デイ収支=sum(r['net'] for r in sessions if r['session'].endswith('_Day')),
                    ナイト収支=sum(r['net'] for r in sessions if r['session'].endswith('_Night')),
                    活動場数=sum(r['campaigns']>0 for r in sessions),
                    最悪三場=[dict(場=r['session'],収支=r['net']) for r in sorted(sessions,key=lambda r:r['net'])[:3]])
            row['場の安定性'] = stability
            rows.append(row)
        summary[model] = sorted(rows, key=lambda r: min(r['商品別'][s]['収支下落比'] for s in SYMBOLS), reverse=True)
    output = dict(状態='改善を反復中。目標達成と未見データでの有効性は未証明。',
                  評価='金額利益割合＝親組利益÷（親組利益＋親組損失）。商品別。全30場・料金後。観測約定を主とする。',
                  四指標='元E01_G_U以上の収支・金額利益割合・黒字場数、以下の最大下落を両商品で同時比較。',
                  前後半='どちらも既知データ。探索後の未見検証とは呼ばない。',
                  相場区分='保存始終値の変化±0.1%を基にした事後分類。売買条件に使用しない。横ばいはTOPIX1場、日経6場のみ。',
                  相場分類SHA256=sha(regime_source),
                  段階=stages, 結果=summary, 入力SHA256=hashes,
                  所在={k: str(v.relative_to(ROOT)) for k, v in locations.items()},
                  全セッション=sorted({r['session'] for r in results['observed'][BASE]['rows']}))
    (HERE / '比較結果.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    for model, rows in summary.items():
        print(model)
        for row in rows:
            print(row['id'], [(s, v['net'], round(v['campaign_profit_share']*100, 1) if v['campaign_profit_share'] is not None else None,
                              v['positive_sessions'], v['max_drawdown']) for s, v in row['商品別'].items()])


if __name__ == '__main__':
    main()
