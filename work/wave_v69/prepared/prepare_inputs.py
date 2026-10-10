"""保存済みの二十八場を修正済みの原本行ティック特徴へ統一する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / 'work'
PRIOR = WORK / 'wave_v67' / 'prepared'
OLD = WORK / 'wave_v63'
EXTRACTOR = WORK / 'wave_v57' / 'features.py'


def digest(path: Path) -> str:
    """機能: 原本又は特徴ファイルを一定メモリー量で指紋化する。

    引数: path(Path)。返り値: SHA256の十六進文字列(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def extract_one(args: tuple) -> tuple:
    """機能: 未準備の保存場を監査済みの抽出器で前から処理する。

    引数: args(tuple:口座キーと価格入力dict)。返り値: キー、特徴、イベント、監査(tuple)。
    """
    key, ready = args
    spec = importlib.util.spec_from_file_location('tick69_fixed_extract', EXTRACTOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    features, events, audit = module.extract_one(key, ready)
    return key, features, events, audit


def save_pickle(path: Path, value: object) -> None:
    """機能: 今回の準備フォルダーだけへ特徴を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    with path.open('wb') as stream:
        pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)


def quality(key: tuple, ready: dict, features: dict, events: np.ndarray) -> dict:
    """機能: 全行の時計・気配・数量・補充期限と欠測状況を照合する。

    引数: key(tuple)、ready/features(dict)、events(np.ndarray)。返り値: 品質集計(dict)。
    """
    for name in ('seq', 'time_s', 'last'):
        np.testing.assert_array_equal(ready[name], features[name])
    assert (np.diff(features['seq']) > 0).all()
    assert (features['bid'] < features['ask']).all()
    assert np.isfinite(features['bid']).all() and np.isfinite(features['ask']).all()
    np.testing.assert_array_equal(features['mid'], (features['bid'] + features['ask']) / 2.)
    known = np.isfinite(features['volume_delta']) & (features['volume_delta'] >= 0)
    classified = features['exec_buy_qty'] + features['exec_sell_qty'] + features['exec_unknown_qty']
    np.testing.assert_allclose(classified[known], features['volume_delta'][known])
    if len(events):
        i = events['i']
        np.testing.assert_array_equal(events['seq'], features['seq'][i])
        np.testing.assert_array_equal(events['time'], features['time_s'][i])
        assert (events['start_seq'] < events['seq']).all()
        assert (events['qty'] >= .8 * events['decline']).all()
        assert (events['qty'] <= events['decline']).all()
        assert (events['qty'] >= .25 * events['bestqty']).all()
        assert (events['time'] - events['start_time'] <= 30.).all()
        assert (events['seq'] - events['start_seq'] <= 500).all()
    return dict(セッション=key[0], 銘柄=key[1], 行数=len(ready['seq']),
        完全10段行数=int(features['valid'].sum()), リセット行数=int(features['reset'].sum()),
        時計逆行数=int((np.diff(features['time_s']) < 0).sum()),
        同時計更新数=int((np.diff(features['time_s']) == 0).sum()),
        最終約定値変更数=int((np.diff(features['last']) != 0).sum()),
        板中値変更数=int((np.diff(features['mid']) != 0).sum()),
        出来高増分既知行数=int(known.sum()),
        出来高増加数量=float(np.sum(features['volume_delta'][known])),
        執行側不明数量=float(np.sum(features['exec_unknown_qty'][known])),
        補充完了数=len(events), 買い側補充数=int((events['side'] == 1).sum()),
        売り側補充数=int((events['side'] == -1).sum()),
        seq時計最終値一致=True, 補充数量期限一致=True)


def main() -> None:
    """機能: 旧五十口座を照合し、新六口座を追加して全五十六口座を保存する。

    引数: なし。返り値: なし(None)。現在API、売買結果、将来ラベルを参照しない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    assert not (HERE / '入力と特徴の照合.json').exists(), '完成した準備物は上書きしません'
    inputs, source_files = {}, []
    for folder in sorted(PRIOR.iterdir()):
        path = folder / 'new_inputs.pkl'
        if not path.exists():
            continue
        with path.open('rb') as stream:
            current = pickle.load(stream)
        assert not set(inputs) & set(current)
        inputs.update(current)
        source_files.append(path)
    assert len(inputs) == 56 and len({key[0] for key in inputs}) == 28
    with (OLD / 'tick_features.pkl').open('rb') as stream:
        features = pickle.load(stream)
    with (OLD / 'tick_events.pkl').open('rb') as stream:
        events = pickle.load(stream)
    assert len(features) == len(events) == 50 and set(features) <= set(inputs)
    previous = json.loads((OLD / '修正板特徴の照合.json').read_text(encoding='utf8'))
    for path in (OLD / 'tick_features.pkl', OLD / 'tick_events.pkl', EXTRACTOR):
        assert digest(path) == previous['ファイルSHA'][str(path)]
    board_audit = json.loads((OLD / '板特徴の照合.json').read_text(encoding='utf8'))
    expected = {(a['セッション'], a['銘柄']): a['原本SHA'] for a in board_audit['原本']}
    old_keys = sorted(features)
    raw_paths = [ROOT / 'book' / key[1] / f'{key[0]}.jsonl' for key in old_keys]
    with ThreadPoolExecutor(max_workers=4) as pool:
        raw_hashes = dict(zip(old_keys, pool.map(digest, raw_paths)))
    assert all(raw_hashes[key] == expected[key] for key in old_keys)
    missing = sorted(set(inputs) - set(features))
    audits = []
    print(f'旧{len(features)}口座の原本一致、新{len(missing)}口座を抽出', flush=True)
    with ProcessPoolExecutor(max_workers=4) as pool:
        for key, data, ev, audit in pool.map(extract_one, [(key, inputs[key]) for key in missing]):
            features[key], events[key] = data, ev
            raw_hashes[key] = audit['原本SHA256']
            old = PRIOR / key[0] / 'features' / f'{key[1]}_{key[0]}_audit.json'
            old_audit = json.loads(old.read_text(encoding='utf8'))
            assert audit['原本SHA256'] == old_audit['原本SHA256']
            audits.append(audit)
            print(f'{key[0]} {key[1]}: {len(data["seq"]):,}行、補充{len(ev):,}件', flush=True)
    # ----------------------------------------
    # 独立に保存された最良気配とも全原本行を一致させる。
    with (WORK / 'wave_v60' / 'quotes.pkl').open('rb') as stream:
        quotes = pickle.load(stream)
    quality_rows = []
    for key in sorted(inputs):
        data, ready = features[key], inputs[key]
        if key in quotes:
            reference = quotes[key]
        else:
            path = PRIOR / key[0] / 'features' / f'約定系列_{key[1]}_{key[0]}.npz'
            with np.load(path) as arrays:
                reference = {name: arrays[name].copy() for name in ('seq', 'time_s', 'bid', 'ask')}
            source_files.append(path)
        for name in ('seq', 'time_s', 'bid', 'ask'):
            np.testing.assert_array_equal(data[name], reference[name])
        row = quality(key, ready, data, events[key])
        row.update(独立保存気配一致=True, 原本SHA256=raw_hashes[key], 新規抽出=key in missing)
        quality_rows.append(row)
    assert len(features) == len(events) == len(inputs) == 56
    save_pickle(HERE / 'inputs.pkl', inputs)
    save_pickle(HERE / 'features.pkl', features)
    save_pickle(HERE / 'events.pkl', events)
    schema = dict(入力キー='(セッション文字列, 銘柄文字列)のtuple',
        価格入力='inputs.pklはv67の56 readyを変更せず集約。ATRを含む旧互換列は本作業のティック条件には使用しない。',
        特徴列=list(next(iter(features.values()))),
        イベント列=list(next(iter(events.values())).dtype.names),
        最良気配='Buy1がbid、Sell1がask。BidPrice/AskPriceの名称からの推測はしない。',
        時計='time_sはCurrentPriceTime（最終約定時計）の秒。受信時計ではない。同時計の板更新はseqの原本順に処理する。',
        valid='正の最良価格、正の最良数量、完全かつ正順序の両側10段。最良気配自体は入力時点でbid<askの有効行のみ。',
        reset='最初、原本行不連続、不正10段、約定時計逆行、累積出来高リセットで未完了補充状態を破棄。',
        最良OFI='現在と直前の最良気配・数量差分。消失した最良数量を含む。注文の約定と取消は区別できない。',
        執行代理='正の売買代金増分/（正の出来高増分×ラージ倍率）の平均執行価格を直前bid/askと比較する代理。真のaggressorではない。',
        補充='同一価格の既知減少後、30秒・500原本行以内に減少量80%以上かつ開始時最良数量25%以上の表示回復が完了したイベント。',
        公開='各原本行を観測し終わった後に特徴や補充を判断可能。発注判断の実約定は次の原本行以降に分ける。',
        不明出来高='volume_deltaがNaNなら増分不明。exec_*の0を既知の無執行と扱わない。',
        禁止='板減少をすべて成行消費と呼ばない。板受信時刻や真の注文単位履歴があると仮定しない。')
    manifest = dict(合格=True, 作成時刻=datetime.now(timezone.utc).isoformat(),
        セッション数=28, 口座数=56, 総原本有効行数=sum(row['行数'] for row in quality_rows),
        総補充完了数=sum(row['補充完了数'] for row in quality_rows),
        原本SHA一致=True, seq時計最終値気配一致=True, 現在API取得数=0, 実注文数=0,
        旧作業書込数=0, 売買結果参照=False,
        引継元ファイルSHA={str(p.relative_to(ROOT)).replace('\\', '/'): digest(p) for p in
            sorted(set(source_files + [OLD / 'tick_features.pkl', OLD / 'tick_events.pkl',
                OLD / '修正板特徴の照合.json', OLD / '板特徴の照合.json', EXTRACTOR]))},
        出力SHA={p.name: digest(p) for p in (HERE / 'inputs.pkl', HERE / 'features.pkl', HERE / 'events.pkl')},
        準備コードSHA256=digest(Path(__file__)), 口座別=quality_rows, 追加抽出監査=audits)
    for name, value in (('入力と特徴の照合.json', manifest), ('入力と特徴の仕様.json', schema)):
        (HERE / name).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf8')
    print(f'全56口座一致、総{manifest["総原本有効行数"]:,}行', flush=True)


if __name__ == '__main__':
    main()
