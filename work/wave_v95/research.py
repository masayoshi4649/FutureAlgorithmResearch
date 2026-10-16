"""追従入口の価格と資格、実損失後の反転確認38条件を損益前に固定して再生する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

import accounting
import catalog
import data
import strategy


def read(path: Path) -> object:
    """
    機能: 凍結仕様又は保存された台帳を読む。
    引数: path(Path)。
    返り値: object。JSON又はpickleの保存内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def clean(value: object) -> object:
    """
    機能: NumPy値を有限JSONの標準型へ変換する。
    引数: value(object)。
    返り値: object。辞書、列、標準数値へ再帰変換した値。
    """
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    return value


def save(path: Path, value: object) -> None:
    """
    機能: 新しい作業領域内へ会計又は証跡を保存する。
    引数: path(Path)、value(object)。
    返り値: None。生データと過去成果を上書きしない。
    """
    assert path.absolute().is_relative_to(HERE.absolute())
    path.parent.mkdir(parents=True, exist_ok=True)
    assert path.resolve().is_relative_to(HERE.resolve())
    if path.suffix == '.pkl':
        with path.open('wb') as stream:
            pickle.dump(value, stream, protocol=5)
    else:
        path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                                   allow_nan=False) + '\n', encoding='utf-8')


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 検証コードの外部接続を禁止する。
    引数: args(tuple)、kwargs(dict)。
    返り値: None。常に例外を出す。
    """
    raise RuntimeError('保存した31セッションの既知入力だけを使用します')


def freeze() -> None:
    """
    機能: 明示的な前検証目録の合格後に38条件と理論主及び全依存を固定する。
    引数: なし。
    返り値: None。未知場の成功と扱わず、検査漏れ又は資料変化なら停止する。
    """
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    plan = read(HERE / '結果前の設計案.json')
    assert plan['予定合計条件数'] == 38 and plan['基本対照数'] == 36
    assert plan['新条件損益閲覧'] == plan['新条件売買実行'] == 0
    assert len(catalog.catalog()) == 38 and catalog.PRIMARY == 'P3_R3_N'
    material = data.load_inputs()
    sessions = material['metadata']['sessions']
    assert len(sessions) == 31 and set(material['trend_prices']) == {'I3'}
    for symbol in catalog.SYMBOLS:
        assert {p.stem for p in (ROOT / 'book' / symbol).glob('*.jsonl')} == set(sessions)
    manifest_path = HERE / '前検証の照合目録.json'
    manifest = read(manifest_path)
    required = {'全62LP窓と源対応', '旧2対照全31完全一致', '38人工と実反転境界',
                '38実接頭部と未来不変', '4入口源の全62独立準備', '38設計の敵対的反証',
                '全38独立人工台帳と会計及び源復元'}
    assert manifest['全合格'] and set(manifest['検査']) == required
    assert manifest['正式新損益未実行'] and manifest['全31既知']
    paths = [manifest_path, HERE / '前検証目録を作る.py']
    for label, binding in {**manifest['検査'], **manifest.get('補足', {})}.items():
        path = ROOT / binding['資料']
        assert data.digest(path) == binding['SHA256'], label
        proof = read(path)
        for field, expected in binding['必須値'].items():
            assert proof[field] == expected, (label, field)
        for relative, expected in proof.get('SHA256', {}).items():
            assert data.digest(ROOT / relative) == expected, (label, relative)
            paths.append(ROOT / relative)
        paths.append(path)
    old_fixed_path = HERE.parent / 'wave_v94/事前固定.json'
    old_fixed = read(old_fixed_path)
    for relative, expected in old_fixed['SHA256'].items():
        assert data.digest(ROOT / relative) == expected, relative
    paths += [HERE / name for name in ('catalog.py', 'data.py', 'strategy.py', 'engine.py',
                                      'accounting.py', 'research.py', 'analysis/assemble.py')]
    paths += material['paths']
    paths += [HERE / '結果前の設計案.json', old_fixed_path,
              HERE / 'prepared/metadata.json', HERE / 'prepare_prices.py',
              HERE / 'セッション安定性の事前評価.json']
    paths += list((HERE / 'engine_preflight').glob('*.py'))
    paths += list((HERE / 'engine_preflight').glob('*.json'))
    paths += list((HERE / 'engine_review').glob('*.py'))
    paths += list((HERE / 'engine_review').glob('*.json'))
    paths += list((HERE / 'review_pre').glob('*.py'))
    paths += list((HERE / 'audit').glob('*.py'))
    paths += list((HERE / 'audit').glob('*.json'))
    paths += list((HERE / 'review_pre').glob('*.json'))
    fingerprints = dict(old_fixed['SHA256'])
    fingerprints.update({str(path.relative_to(ROOT)): data.digest(path) for path in sorted(set(paths))})
    save(HERE / '事前固定.json', dict(
        条件=catalog.catalog(), 主=catalog.PRIMARY, 全31=sessions,
        主の選択=plan['暫定理論主'],
        前16=sessions[:16], 後15=sessions[16:], 旧30=sessions[:-1], 後14=sessions[16:-1],
        追加1=sessions[-1:], 全31既知=True, 新しい未見確認場数=0,
        意味='全31場は既知の再探索。前16選定と後15確認も未知データの成功とは呼ばない。',
        目的='商品ごとに親別総利益/(総利益+総損失)80%以上、費用後黒字、含み損込み最大下落と活動の改善。無取引は勝ちではない。',
        入力軸=plan['入力軸'], 再参加軸=plan['再参加軸'], 純損失軸=plan['純損失軸'],
        源の分離=plan['価格と板の分離'],
        実返済基準=plan['実返済基準'], 欠測後基準=plan['欠測後の新基準'],
        持続条件=plan['持続条件'], 候補消費=plan['候補の消費'],
        演算順=plan['演算順'], 旧出口=plan['旧出口の保持'],
        基本対照='4入口源×9反転条件の36。同じ入口で反転kind/純損失triggerを対照化。J10と主4/8枚を数量対照として加えた38。',
        枚数='TOPIXmini片方向10枚、NK225micro20枚以内。基本38中36は8/16枚、J10は10/20、主小数量対照は4/8枚。',
        約定='既存retained原板で判断後の次有効買ask/売bid。追加rawLP行で返済を前倒しせず、実返済後にだけ失敗記憶を更新。実小商品板・全量約定・真受信時計は未検証。追加5秒劣化なし。',
        料金='TOPIXmini片道41.8円/枚、NK225micro11円/枚を注文別切捨て。倍率1000/10。全原板を清算気配と返済費用で評価し全玉場内返済。',
        選定=read(HERE / 'セッション安定性の事前評価.json'),
        採用判定='両銘柄の費用後黒字及び金額利益80%、十分な活動と全日安定への改善を確認。最大利益日除外・前後・方向別・全玉時価で反証。小取引数と無取引を達成へ代用しない。',
        正式新条件損益前固定=True, 前検証SHA256=data.digest(manifest_path),
        SHA256=fingerprints, API取得=0, 実注文=0))
    print('38条件と主P3_R3_Nを固定。31場すべて既知です。', flush=True)


def validate(fixed: dict) -> None:
    """
    機能: 実行前に条件と凍結したすべての依存を照合する。
    引数: fixed(dict)。
    返り値: None。不一致があれば実行を拒絶する。
    """
    assert fixed['条件'] == catalog.catalog()
    for relative, expected in fixed['SHA256'].items():
        assert data.digest(ROOT / relative) == expected, relative


def changes(trace: np.ndarray) -> np.ndarray:
    """
    機能: 未定義値を含む全行状態から変化行と両端を取り出す。
    引数: trace(ndarray[float])。
    返り値: ndarray。行番号とその行の全状態列。
    """
    equal = (trace[1:] == trace[:-1]) | (np.isnan(trace[1:]) & np.isnan(trace[:-1]))
    rows = np.unique(np.r_[0, np.flatnonzero(~equal.all(axis=1)) + 1, len(trace)-1])
    return np.column_stack((rows, trace[rows]))


def ledger(output: dict, prepared: dict | None = None) -> dict:
    """
    機能: 全注文・会計と独立価格及び執行源・初回入口の潜在状態を保存する。
    引数: output(dict、正式執行の結果)、prepared(dict|None、当該口座の因果入力)。
    返り値: dict。全行を指紋化し、状態は疎形式で独立復元できる。
    """
    names = ('orders', 'trades', 'events', 'stats', 'slots', 'order_columns', 'trade_columns',
             'trace_columns', 'event_columns', 'stat_columns', 'slot_columns', 'reasons', 'event_codes')
    answer = {name: output[name] for name in names}
    answer.update(input_rows=len(output['curve']), trace_changes=changes(output['target_trace']),
                  range_state_changes=changes(output['range_state_trace']),
                  range_state_columns=output['range_state_columns'])
    for name in ('curve', 'source_curve', 'target_trace'):
        answer[name + '_SHA256'] = hashlib.sha256(output[name].tobytes()).hexdigest()
    answer['range_state_SHA256'] = hashlib.sha256(output['range_state_trace'].tobytes()).hexdigest()
    if 'risk_state_trace' in output:
        answer.update(risk_state_changes=changes(output['risk_state_trace']),
                      risk_state_columns=output['risk_state_columns'],
                      risk_state_SHA256=hashlib.sha256(output['risk_state_trace'].tobytes()).hexdigest())
    if 'price_source_trace' in output:
        answer.update(price_source_changes=changes(output['price_source_trace']),
                      price_source_columns=output['price_source_columns'],
                      price_source_SHA256=hashlib.sha256(output['price_source_trace'].tobytes()).hexdigest())
    if 'range_parent_diagnostics' in output:
        answer.update(range_parent_diagnostics=output['range_parent_diagnostics'],
                      range_parent_columns=output['range_parent_columns'])
    answer['source_curve_column_SHA256'] = [hashlib.sha256(output['source_curve'][:, i].tobytes()).hexdigest()
                                            for i in range(2)]
    for name in ('loss_reentry_events', 'loss_event_columns', 'loss_event_codes'):
        if name in output:
            answer[name] = output[name]
    if prepared is not None:
        answer['trend_candidate_state'] = prepared['trend_candidate_state']
        answer['trend_lp_allowed'] = prepared['trend_lp_allowed']
        answer['trend_event_changes'] = changes(prepared['signal']['event'].reshape((-1, 1)))
        answer['trend_event_SHA256'] = hashlib.sha256(prepared['signal']['event'].tobytes()).hexdigest()
        answer['loss_observations_SHA256'] = hashlib.sha256(prepared['signal']['loss_observations'].tobytes()).hexdigest()
        answer['execution_lp_index_SHA256'] = hashlib.sha256(prepared['signal']['execution_lp_index'].tobytes()).hexdigest()
    return answer


def stability(rows: list[dict], config: dict, prepared: dict, sessions: list[str]) -> dict:
    """
    機能: 最大利益よりセッション損失の安定を評価するため、全条件共通単位で下方偏差を求める。
    引数: rows(list[dict])、config/prepared(dict)、sessions(list[str])。
    返り値: dict。商品別の活動黒字率、赤字平均・最大、下方偏差と収支分位。
    0.1%は比較単位であり注文幅の変更ではない。実円額と比較単位を両方保持する。
    """
    result = {}
    for symbol in catalog.SYMBOLS:
        selected = [row for row in rows if row['symbol'] == symbol and row['session'] in sessions]
        active = [row for row in selected if row['campaigns'] > 0]
        red = [row for row in active if row['net'] < -1e-5]
        scale, multiplier = (1, 1000.) if symbol == 'TOPIX' else (2, 10.)
        quantity = (int(config['trend_budget']) + int(config['range_budget'])) * scale
        assert quantity > 0
        comparison_cap = 10 * scale
        units = {}
        for row in selected:
            record = prepared[row['session'], symbol]['record']
            first_price = float(record['price'][0])
            assert first_price > 0 and np.isfinite(first_price)
            units[row['session']] = comparison_cap * multiplier * first_price * .001
        normalized = np.array([row['net'] / units[row['session']] for row in active], float)
        loss = np.minimum(normalized, 0.)
        red_units = [-row['net'] / units[row['session']] for row in red]
        nets = np.array([row['net'] for row in selected], float)
        result[symbol] = dict(
            configured_quantity=quantity, comparison_cap=comparison_cap,
            session_count=len(selected), active_sessions=len(active),
            no_trade_sessions=len(selected) - len(active), losing_sessions=len(red),
            positive_session_rate=sum(row['net'] > 1e-5 for row in active) / len(active) if active else None,
            mean_losing_session_yen=float(np.mean([-row['net'] for row in red])) if red else 0.,
            worst_session_loss_yen=max([-row['net'] for row in red], default=0.),
            downside_rms_units=float(np.sqrt(np.sum(loss * loss) / len(selected))) if selected else None,
            active_downside_rms_units=float(np.sqrt(np.mean(loss * loss))) if active else None,
            mean_losing_session_units=float(np.mean(red_units)) if red else 0.,
            worst_session_loss_units=max(red_units, default=0.),
            active_net_q25_units=float(np.quantile(normalized, .25)) if active else None,
            active_net_median_units=float(np.median(normalized)) if active else None,
            session_net_q25_yen=float(np.quantile(nets, .25)) if selected else None,
            session_net_median_yen=float(np.median(nets)) if selected else None,
            worst_intraday_drawdown_units=max([row['equity_drawdown'] / units[row['session']]
                                               for row in selected], default=0.),
            comparison_units_yen=units,
            definition='全条件共通上限10/20枚×倍率×当該場最初の正常価格0.1%。主RMS分母は共通全評価場数。無取引は活動黒字率の勝ちへ含めない。')
    return result


def run_one(config: dict, sessions: list[str], base: Path, prepared: dict) -> str:
    """
    機能: 固定した一条件の指定期間を再生し、会計と台帳を新規保存する。
    引数: config(dict)、sessions(list[str])、base(Path)、prepared(dict)。
    返り値: str。完了した条件ID。
    """
    target = base / 'results' / (config['id'] + '.json')
    assert not target.exists()
    rows, records = [], {}
    for key in sorted(key for key in prepared if key[0] in sessions):
        output = strategy.play(config, key, prepared)
        rows.append(accounting.account(key, output))
        records[key] = ledger(output, prepared[key])
    name = '前16' if len(sessions) == 16 else '後15'
    periods = {name: {symbol: accounting.aggregate(rows, symbol, sessions) for symbol in catalog.SYMBOLS}}
    path = base / 'ledgers' / (config['id'] + '.pkl')
    save(path, records)
    save(target, dict(config=config, rows=rows, periods=periods,
                      stability=stability(rows, config, prepared, sessions), ledger_SHA256=data.digest(path)))
    return config['id']


def run_config(config: dict, sessions: list[str], base: Path, material: dict) -> str:
    """
    機能: 作業者内で状態を作り、同時に保持する全場配列を並列数以下へ抑える。
    引数: config/material(dict)、sessions(list[str])、base(Path)。
    返り値: str。再生を完了した条件ID。
    """
    return run_one(config, sessions, base, strategy.prepare(material, config))


def score(result: dict) -> tuple:
    """
    機能: 前16の悪い側のセッション下方偏差と活動黒字率を優先する固定順を作る。
    引数: result(dict)。
    返り値: tuple。昇順で使う採点。
    """
    values = [result['periods']['前16'][symbol] for symbol in catalog.SYMBOLS]
    stable = [result['stability'][symbol] for symbol in catalog.SYMBOLS]
    shares = [value['profit_share'] if value['profit_share'] is not None else -1 for value in values]
    rates = [value['positive_session_rate'] if value['positive_session_rate'] is not None else -1 for value in stable]
    rms = [value['downside_rms_units'] if value['downside_rms_units'] is not None else 1e300 for value in stable]
    lower = [value['active_net_q25_units'] if value['active_net_q25_units'] is not None else -1e300 for value in stable]
    return (max(rms), -min(rates), max(value['worst_session_loss_units'] for value in stable),
            -min(lower), -min(shares), result['config']['id'])


def select() -> None:
    """
    機能: 前16の参考を後15の正式損益前に固定する。
    引数: なし。
    返り値: None。後15も既知であり未知性能と主張しない。
    """
    assert not (HERE / '前16参考代表.json').exists()
    assert not list((HERE / 'back/results').glob('*.json'))
    fixed = read(HERE / '事前固定.json')
    validate(fixed)
    results = [read(HERE / 'front/results' / (config['id'] + '.json')) for config in fixed['条件']]
    active = [result for result in results if all(
        result['periods']['前16'][symbol]['campaigns'] >= 20
        and result['periods']['前16'][symbol]['active_sessions'] >= 8 for symbol in catalog.SYMBOLS)]
    positive = [result for result in active if all(
        result['periods']['前16'][symbol]['net'] > 0 for symbol in catalog.SYMBOLS)]
    good = [result for result in positive if all(
        result['periods']['前16'][symbol]['payoff'] is not None
        and result['periods']['前16'][symbol]['payoff'] > 1 for symbol in catalog.SYMBOLS)]
    robust = [result for result in good if all(
        result['periods']['前16'][symbol]['without_best_day']['net'] > 0 for symbol in catalog.SYMBOLS)]
    target = [result for result in robust if all(
        result['periods']['前16'][symbol]['profit_share'] >= .8 for symbol in catalog.SYMBOLS)]
    pool = target or robust or good or positive or active or results
    chosen = min(pool, key=score)['config']['id']
    save(HERE / '前16参考代表.json', dict(全合格=True, selected=chosen, primary=catalog.PRIMARY,
         level=0 if target else 1 if robust else 2 if good else 3 if positive else 4 if active else 5,
         priority='セッション損失安定性。下方偏差→活動黒字率→最大赤字→収支下位25%→金額利益割合→ID。',
         eligible=[result['config']['id'] for result in pool],
         scores={result['config']['id']: score(result) for result in pool},
         後15正式損益前選定=True, 全31既知=True, 固定SHA256=data.digest(HERE / '事前固定.json'),
         結果SHA256={str(path.relative_to(ROOT)): data.digest(path) for path in
                      sorted((HERE / 'front/results').glob('*.json'))}))
    print(f'前16参考 {chosen} を固定。後15も既知として次に確認します。', flush=True)


def main() -> None:
    """
    機能: 固定、前16、参考選定、後15の順序を守って保存済みデータを実行する。
    引数: コマンド引数の段階と並列数。
    返り値: None。通信と実注文を行わない。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ('freeze', 'run-front', 'select', 'run-back'):
        group.add_argument('--' + name, action='store_true')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    socket.create_connection = deny
    socket.socket.connect = deny
    if args.freeze:
        freeze()
        return
    if args.select:
        select()
        return
    fixed = read(HERE / '事前固定.json')
    validate(fixed)
    if args.run_back:
        chosen = read(HERE / '前16参考代表.json')
        assert chosen['後15正式損益前選定']
        assert chosen['固定SHA256'] == data.digest(HERE / '事前固定.json')
        for relative, expected in chosen['結果SHA256'].items():
            assert data.digest(ROOT / relative) == expected, relative
    sessions = fixed['前16' if args.run_front else '後15']
    base = HERE / ('front' if args.run_front else 'back')
    material = data.load_inputs()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_config, config, sessions, base, material):
                   config['id'] for config in fixed['条件']}
        for future in as_completed(futures):
            print(future.result() + ' 完了', flush=True)


if __name__ == '__main__':
    main()
