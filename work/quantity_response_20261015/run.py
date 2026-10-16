"""事前固定した66保存NPZを一回ずつ読み、注文なしで数量応答を測定する。"""

import gc
import hashlib
import io
import json
from pathlib import Path
import time
import traceback

import numpy as np

import plan


HERE = plan.HERE
ROOT = plan.ROOT
OUT = HERE / 'measurement'
REGISTRY = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json'

# ----------------------------------------


def primitive(value: object) -> object:
    """
    機能: 測定資料の小さい値をJSONで確実に保存できる原始型に変換する。
    引数: value(object) は辞書、配列、numpy scalar等。
    返り値: object は通常のdict/list/int/float/bool等。非有限数値は拒否する。
    """
    if isinstance(value, dict):
        return {str(key): primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [primitive(item) for item in value]
    if isinstance(value, np.ndarray):
        return primitive(value.tolist())
    if isinstance(value, np.generic):
        return primitive(value.item())
    if isinstance(value, float):
        assert np.isfinite(value)
    return value


def validate(arrays: dict, schema: dict) -> None:
    """
    機能: 元44列の型・形・原順・正常行mapを読み取ったメモリ上で検査する。
    引数: arrays(dict[str,ndarray])、schema(dict) は既保存入力と固定schema。
    返り値: None。原本や他の金融cacheを読まず、配列変更を禁止する。
    """
    assert set(arrays) == set(schema) and len(arrays) == 44
    n, m = len(arrays['raw_seq']), len(arrays['execution_to_raw_index'])
    assert n > 0
    for name, wanted in schema.items():
        value = arrays[name]
        shape = tuple(n if size == 'N' else m if size == 'M' else size for size in wanted['shape'])
        assert str(value.dtype) == wanted['dtype'] and value.shape == shape, name
        value.flags.writeable = False
    assert np.all(np.diff(arrays['raw_seq']) > 0)
    mapping = arrays['execution_to_raw_index']
    assert np.all((mapping >= 0) & (mapping < n)) and np.all(np.diff(mapping) > 0)
    np.testing.assert_array_equal(mapping, np.flatnonzero(arrays['normal_execution_row']))


def group(events: np.ndarray, outcomes: np.ndarray, fields: list[str], mask: np.ndarray) -> dict:
    """
    機能: 先着と打切を混同せず、指定した観測群の分母と特徴量を集計する。
    引数: events/outcomes(ndarray)、fields(list[str])、mask(ndarray[bool]) は保存事象と対象条件。
    返り値: dict は全件・各終点・解決例だけの率と参考中央値。
    """
    selected, final = events[mask], outcomes[mask]
    total = len(selected)
    codes = final[:, 0]
    plus, minus = int(np.sum(codes == 1)), int(np.sum(codes == -1))
    unknown, eof = int(np.sum(codes == 0)), int(np.sum(codes == 2))
    window_end = int(np.sum(codes == 3))
    assert total == plus + minus + unknown + eof + window_end
    result = dict(n=total, plus=plus, minus=minus, unknown=unknown, eof=eof, window_end=window_end,
                  resolved=plus + minus, rate=plus / (plus + minus) if plus + minus else None)
    for field in ('opposite_q0', 'quantity_ratio', 'minimum_quantity_ratio', 'total_volume', 'npositive'):
        values = selected[:, fields.index(field)]
        result['median_' + field] = float(np.median(values)) if total else None
    return result


def summarize(events: np.ndarray, outcomes: np.ndarray, fields: list[str], tick: float) -> dict:
    """
    機能: 事前の二観測点・数量二群・維持内訳を方向とspread別にも保存する。
    引数: events/outcomes(ndarray)、fields(list[str])、tick(float) は観測とラージ刻み。
    返り値: dict は相互に独立でない内訳。各内訳を別標本へ合算しない。
    """
    column = {name: events[:, index] for index, name in enumerate(fields)}
    kinds = column['type']
    high = column['quantity_ratio'] >= 1
    always = column['minimum_quantity_ratio'] >= 1
    threshold = kinds == 1
    reached = np.isin(column['episode'], column['episode'][threshold])
    masks = dict(type0_all=kinds == 0, type0_reached=(kinds == 0) & reached,
                 type1_all=threshold, type1_decreased=threshold & ~high,
                 type1_maintained=threshold & high,
                 type1_never_below=threshold & high & always,
                 type1_recovered=threshold & high & ~always)
    sides = dict(all=np.ones(len(events), bool), buy=column['d'] == 1, sell=column['d'] == -1)
    spread = (column['ask'] - column['bid']) / tick
    spreads = dict(all=np.ones(len(events), bool), one=spread == 1, wider=spread > 1, narrower=spread < 1)
    result = {}
    for name, mask in masks.items():
        result[name] = group(events, outcomes, fields, mask)
    result['by_side'] = {side: {name: group(events, outcomes, fields, mask & subset)
                              for name, mask in masks.items()} for side, subset in sides.items() if side != 'all'}
    result['by_spread'] = {spread_name: {name: group(events, outcomes, fields, mask & subset)
                                      for name, mask in masks.items()}
                           for spread_name, subset in spreads.items() if spread_name != 'all'}
    pair0 = events[(kinds == 0) & reached, fields.index('episode')].astype(np.int64)
    pair1 = events[threshold, fields.index('episode')].astype(np.int64)
    assert np.array_equal(pair0, pair1)
    np.testing.assert_array_equal(outcomes[(kinds == 0) & reached], outcomes[threshold])
    assert result['type1_all']['n'] == result['type1_decreased']['n'] + result['type1_maintained']['n']
    assert result['type1_maintained']['n'] == result['type1_never_below']['n'] + result['type1_recovered']['n']
    result['paired_same_bbo_equal'] = True
    return result


def aggregate(rows: list[dict], symbol: str) -> dict:
    """
    機能: 各場の先着件数を合算し、解決例率と場別率の範囲を分離する。
    引数: rows(list[dict]) は口座小集計、symbol(str) は商品。
    返り値: dict は全件及びDay/Night内訳。空群の率はNone。
    """
    output = {}
    for period in ('all', 'Day', 'Night'):
        chosen = [row for row in rows if row['symbol'] == symbol and
                  (period == 'all' or row['session'].endswith('_' + period))]
        main = {}
        for name in ('type0_all', 'type0_reached', 'type1_all', 'type1_decreased',
                     'type1_maintained', 'type1_never_below', 'type1_recovered'):
            values = [row['groups'][name] for row in chosen]
            counts = {key: sum(row[key] for row in values) for key in ('n', 'plus', 'minus', 'unknown', 'eof', 'window_end', 'resolved')}
            rates = [row['rate'] for row in values if row['rate'] is not None]
            counts.update(rate=counts['plus'] / counts['resolved'] if counts['resolved'] else None,
                          active_sessions=sum(row['n'] > 0 for row in values),
                          mean_session_rate=float(np.mean(rates)) if rates else None,
                          min_session_rate=min(rates) if rates else None,
                          max_session_rate=max(rates) if rates else None)
            main[name] = counts
        output[period] = dict(sessions=len(chosen), groups=main)
    return output

# ----------------------------------------


def execute() -> None:
    """
    機能: 正式登録と独立人工後だけ、66入力を各一読して価格応答を保存する。
    引数: なし。
    返り値: None。失敗は保存し、自動再実行・自動修正・金融再生をしない。
    """
    frozen = plan.read(HERE / '実測前の正式固定.json')
    fixed = plan.read(HERE / '入力と観測の小固定.json')
    proposal = plan.read(HERE / '試行計画.json')
    assert frozen['全合格'] and frozen['金融'] is False
    assert frozen['source_SHA256'] == plan.sources()
    assert frozen['input_fixed_SHA256'] == plan.digest(HERE / '入力と観測の小固定.json')
    assert frozen['proposal_SHA256'] == plan.digest(HERE / '試行計画.json')
    audit = plan.read(HERE / '本体初読前の人工と独立監査.json')
    assert frozen['audit_SHA256'] == plan.digest(HERE / '本体初読前の人工と独立監査.json')
    assert audit['全合格'] and audit['入力本文'] == 0 and audit['source_SHA256'] == plan.sources()
    for evidence in audit['evidence']:
        assert plan.digest(ROOT / evidence['path']) == evidence['SHA256']
    assert proposal['spec']['implementation'] == frozen['source_SHA256']
    manifest_path = (HERE / '入力と観測の小固定.json').relative_to(ROOT).as_posix()
    assert proposal['spec']['data']['input_manifests'] == [
        dict(path=manifest_path, sha256=frozen['input_fixed_SHA256'])]
    trials = plan.read(REGISTRY)
    registered = [row for row in trials['trials'] if row['id'] == plan.TRIAL]
    assert len(registered) == 1 and registered[0]['spec'] == proposal['spec']
    assert proposal['spec']['data']['inputs'] == fixed['inputs']
    assert proposal['spec']['data']['sessions'] == fixed['sessions']
    assert len(fixed['inputs']) == 66 and len(set(fixed['sessions'])) == 33
    assert len(fixed['sessions']) == 33
    assert {(row['session'], row['symbol']) for row in fixed['inputs']} == {
        (session, symbol) for session in fixed['sessions'] for symbol in ('TOPIX', 'NK225')}
    assert not OUT.exists()
    OUT.mkdir()
    counts = dict(NPZ本文=0, 同bytesSHA検算=0, 測定口座=0, 原板=0, 足=0, 旧金融=0, 新金融=0, API=0, 追加二場本文=0)
    rows = []
    begun = time.monotonic()
    try:
        import engine
        for item in fixed['inputs']:
            source = ROOT / item['path']
            before = source.stat()
            assert before.st_size == item['bytes'] and before.st_mtime_ns == item['mtime_ns']
            raw = source.read_bytes()
            counts['NPZ本文'] += 1
            assert hashlib.sha256(raw).hexdigest() == item['SHA256']
            counts['同bytesSHA検算'] += 1
            after = source.stat()
            assert before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns
            with np.load(io.BytesIO(raw), allow_pickle=False) as saved:
                arrays = {name: saved[name] for name in saved.files}
            del raw
            validate(arrays, fixed['schema'])
            symbol, session = item['symbol'], item['session']
            tick = fixed['観測T'][symbol]
            result = engine.measure(arrays, item['bounds'][0], item['bounds'][1], tick)
            events, outcomes = result['events'], result['outcomes']
            assert result['outcome_fields'] == ['code', 'end_i']
            assert len(events) == len(outcomes) and np.isfinite(events).all()
            pub = events[:, result['fields'].index('pub_i')].astype(np.int64)
            terminal = outcomes[:, 1].astype(np.int64)
            assert np.all((terminal >= 0) & (terminal < len(arrays['raw_seq'])))
            analysis_outcomes = outcomes.copy()
            scope_end = (outcomes[:, 0] == 0) & np.isfinite(arrays['price_time_s'][terminal]) & (
                arrays['price_time_s'][terminal] >= item['bounds'][1])
            analysis_outcomes[scope_end, 0] = 3
            groups = summarize(events, analysis_outcomes, result['fields'], tick)
            final_clock = arrays['price_time_s'][-1]
            eof_near = bool(np.isfinite(final_clock) and item['bounds'][1] - 1 <= final_clock < item['bounds'][1])
            target = OUT / 'events' / (session + '_' + symbol + '.npz')
            target.parent.mkdir(parents=True, exist_ok=True)
            buffer = io.BytesIO()
            np.savez_compressed(buffer, events=events, outcomes=outcomes, analysis_outcomes=analysis_outcomes,
                                publication_raw_seq=arrays['raw_seq'][pub], publication_time_s=arrays['price_time_s'][pub],
                                terminal_raw_seq=arrays['raw_seq'][terminal], terminal_time_s=arrays['price_time_s'][terminal],
                                terminal_bid=arrays['bid'][terminal], terminal_ask=arrays['ask'][terminal],
                                terminal_price_reason=result['price_reason_mask'][terminal])
            packed = buffer.getvalue()
            assert not target.exists()
            target.write_bytes(packed)
            row = dict(session=session, symbol=symbol, raw_rows=len(arrays['raw_seq']),
                       counts=result['counts'], groups=groups,
                       fields=result['fields'], outcome_fields=result['outcome_fields'],
                       analysis_code='元code0のうち終点の有限価格時計が観測上限以上なら3=観測窓終了を含む資格切断。他原因が併存し得る。3と残り0は排他的内訳。',
                       eof_near_expected=eof_near,
                       events=dict(path=target.relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(packed).hexdigest(),
                                   bytes=len(packed), n=len(events)))
            rows.append(primitive(row))
            counts['測定口座'] += 1
            print(session + ' ' + symbol + ' 数量応答の非金融測定完了', flush=True)
            del arrays, result, events, outcomes, analysis_outcomes, packed, buffer
            gc.collect()
        assert counts['NPZ本文'] == counts['同bytesSHA検算'] == counts['測定口座'] == 66
        assert len({(row['session'], row['symbol']) for row in rows}) == 66
        assert frozen['source_SHA256'] == plan.sources()
        output = dict(全合格=True, 金融=False, sessions=fixed['sessions'], rows=rows,
                      totals={symbol: aggregate(rows, symbol) for symbol in ('TOPIX', 'NK225')},
                      counts=counts, source_SHA256=frozen['source_SHA256'],
                      source開始終端一致=True, 経過秒=time.monotonic() - begun,
                      未測='売買・収益・費用回収・真攻撃量・真補充・テクニカル・相手板・先着後の到達')
        plan.write(OUT / '数量応答の結果.json', primitive(output))
        print(json.dumps(dict(全合格=True, 測定口座=66, 新金融=0), ensure_ascii=False), flush=True)
    except BaseException:
        plan.write(OUT / 'False.json', dict(全合格=False, 原因=traceback.format_exc(), counts=counts,
                                          source_SHA256=frozen['source_SHA256'], 自動再実行=False))
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--registered', required=True, action='store_true')
    parser.parse_args()
    execute()
