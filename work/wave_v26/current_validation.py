"""固定した候補だけを、現在セッションの一回保存データで照合する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import argparse
import json
import math
from pathlib import Path
import pickle
import sys
import urllib.parse
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v23'
PREVIOUS = HERE.parent / 'wave_v25'
LIVE = HERE / 'live'
JST = ZoneInfo('Asia/Tokyo')
sys.path.insert(0, str(PREVIOUS))
sys.path.insert(0, str(OLD))
import current_check as legacy
import discovery_signals
import d016_price_control
import ensemble_runner as runner
import ensemble_signals

ORIGINAL_SIGNALS = legacy.signals


class SignalDispatcher:
    """機能: 凍結した信号の種類だけで実装を選ぶ。収支による再選択を行わない。"""

    ROOT = LIVE

    @classmethod
    def clear_cache(cls) -> None:
        """機能: 保存済み現在データを入力根として、過去キャッシュを解除する。

        引数: なし。返り値: なし (None)。
        """
        ORIGINAL_SIGNALS.ROOT = cls.ROOT
        ORIGINAL_SIGNALS.clear_cache()
        discovery_signals.LEGACY.ROOT = cls.ROOT
        discovery_signals.clear_cache()
        ensemble_signals.clear_cache()

    @classmethod
    def build(cls, spec: dict, inputs: dict, features: dict) -> dict:
        """機能: 凍結済みの多窓・板・価格信号を保存入力だけで作る。

        引数: spec/inputs/features (dict)。返り値: 区間別方向 (dict)。
        """
        source = spec['実装元']
        if source == '多窓':
            return ensemble_signals.build(spec, inputs, features)
        if source == '新規板':
            return discovery_signals.build(spec, inputs, features)
        if source == '既存板':
            return ORIGINAL_SIGNALS.build(spec, inputs, features)
        if source == '価格P02':
            models = {key: discovery_signals._book(ready, features[key], spec['params']['seconds'])
                      for key, ready in inputs.items()}
            return d016_price_control.build(inputs, models, spec['params'], 'P02', 'price')[0]
        raise ValueError(f'未定義の凍結信号: {source}')


def fetch_once(helper) -> dict:
    """機能: 最終候補と全依存を凍結し、状態と６URLをそれぞれ一回だけ保存する。

    引数: helper (module) は旧一回取得実装。返り値: 取得記録 (dict)。失敗時も再取得しない。
    """
    LIVE.mkdir(exist_ok=True)
    selected = runner.read(HERE / '現在照合候補の固定.json')
    assert selected['候補'] and selected['候補再選択禁止']
    verify_selection(selected)
    paths = [HERE / '現在照合候補の固定.json', Path(__file__), HERE / 'ensemble_signals.py',
             HERE / 'ensemble_runner.py', PREVIOUS / 'discovery_signals.py',
             PREVIOUS / 'd016_price_control.py', PREVIOUS / 'discovery_runner.py',
             OLD / 'signals.py', OLD / 'engine.py', OLD / 'managers.py', OLD / 'current_check.py',
             OLD / 'depth_features.py']
    # 過去版をまたぐ動的importも含め、旧波版直下のPythonソースを全て固定する。
    for folder in (ROOT / 'work').glob('wave_v*'):
        number = folder.name.removeprefix('wave_v')
        if number.isdigit() and int(number) < 25:
            paths.extend(folder.glob('*.py'))
    paths += [PREVIOUS / 'discovery_managers.py', HERE / 'select_current.py',
              HERE / '現在照合選抜の事前規則.json', HERE / '一次反証の結果.json',
              HERE / '無関係対照の要約.json', HERE / '反証実装の固定.json']
    paths = sorted(set(paths))
    fixed = {'凍結時刻': datetime.now(JST).isoformat(), '主候補': selected['主候補'],
             '最終候補': selected['候補'], 'ファイルSHA256': {p.relative_to(ROOT).as_posix(): runner.digest(p) for p in paths},
             '過去閲覧済み時刻': '2026-09-29T17:25:00+09:00', '条件の再選択なし': True,
             '位置付け': '当該セッションの17:25まで既読。それ以降は未取得。固定前から進行した価格の保存後再生であり、実発注や完全な前向き試験ではない。'}
    with (LIVE / '現在照合の凍結記録.json').open('x', encoding='utf-8') as stream:
        json.dump(fixed, stream, ensure_ascii=False, indent=2)
    now = datetime.now(JST)
    cutoff = now.replace(second=0, microsecond=0)
    record = {'取得開始': now.isoformat(), '共通締切': cutoff.isoformat(), '各URL一回': True,
              '再取得禁止': True, '凍結記録SHA256': runner.digest(LIVE / '現在照合の凍結記録.json'),
              'requests': [], 'ok': False}
    with (LIVE / '一回取得開始.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    try:
        status = helper.fetch_one('status', helper.BASE_URL + '/status', LIVE / 'status.json')
        record['requests'].append(status)
        runner.save(LIVE / '取得記録.json', record)
        if not status['ok']:
            raise RuntimeError('状態の取得失敗。再試行しません。')
        payload = json.loads((LIVE / 'status.json').read_text(encoding='utf-8-sig'))
        session, start, end = helper.identify_session(payload, cutoff)
        record.update(session=session, session_start=start.isoformat(), session_end=end.isoformat())
        query = urllib.parse.urlencode({'from': start.isoformat(), 'to': cutoff.isoformat()})
        requests = []
        for symbol in ['TOPIX', 'NK225']:
            requests.append((f'{symbol}_book', f'{helper.BASE_URL}/{symbol}/book?{query}',
                             LIVE / 'book' / symbol / f'{session}.jsonl'))
            for minutes in [1, 5]:
                requests.append((f'{symbol}_{minutes}min', f'{helper.BASE_URL}/{symbol}/candles/{minutes}min?{query}',
                                 LIVE / '応答原本' / f'{symbol}_{minutes}min.json'))
        with ThreadPoolExecutor(max_workers=6) as pool:
            record['requests'].extend(pool.map(lambda args: helper.fetch_one(*args), requests))
        record['ok'] = all(r['ok'] for r in record['requests'])
        if not record['ok']:
            raise RuntimeError('一部データの取得失敗。再試行しません。')
    except Exception as error:
        record['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        record['取得終了'] = datetime.now(JST).isoformat()
        runner.save(LIVE / '取得記録.json', record)
    return record


def verify_selection(selected: dict) -> None:
    """機能: 空・途中の反証資料を合格扱いせず、選抜に用いた全対照の整合を確認する。

    引数: selected (dict) は凍結する候補集合。返り値: なし (None)。通信しない。
    """
    import select_current
    repeated = select_current.select()
    assert repeated['候補'] == selected['候補'] and repeated['主候補'] == selected['主候補']
    implementation = runner.read(HERE / '反証実装の固定.json')
    validation_sha = runner.digest(HERE / '反証実装の固定.json')
    for relative, expected in implementation['SHA256'].items():
        assert runner.digest(HERE.parent / relative) == expected, f'反証後の変更: {relative}'
    first = runner.read(HERE / '一次反証の結果.json')
    planned = runner.read(HERE / '反証前の候補固定.json')['反証候補']
    assert len(first) == len(planned)
    assert {x['candidate']['id'] for x in first} == {x['id'] for x in planned}
    first_map = {x['candidate']['id']: x for x in first}
    random_plan = runner.read(HERE / '無関係対照前の候補固定.json')
    random_summary = runner.read(HERE / '無関係対照の要約.json')
    assert len(random_summary) == len(random_plan)
    assert {x['candidate']['id'] for x in random_summary} == {x['id'] for x in random_plan}
    expected_pairs = {(gate, seed) for gate in (False, True) for seed in range(64)}
    for entry in random_summary:
        candidate = entry['candidate']
        identifier = candidate['id']
        assert not first_map[identifier]['first_stage_failures']
        assert first_map[identifier]['candidate'] == candidate
        assert first_map[identifier]['validation_sha'] == entry['validation_sha'] == validation_sha
        assert len(entry['summary']) == 2
        assert {x['発火時刻限定'] for x in entry['summary']} == {False, True}
        full = runner.read(HERE / 'randomized' / f'{identifier}.json.gz')
        assert full['candidate'] == candidate and full['validation_sha'] == validation_sha
        assert full['summary'] == entry['summary']
        assert len(full['results']) == 128
        assert {(x['gated'], x['seed']) for x in full['results']} == expected_pairs
        for mode in entry['summary']:
            assert mode['試行数'] == 64
            results = [x for x in full['results'] if x['gated'] == mode['発火時刻限定']]
            count = sum(all(x['symbols'][s]['net_yen'] >= candidate['symbols'][s]['net_yen'] for s in ['TOPIX', 'NK225']) for x in results)
            assert count == mode['両銘柄で候補以上の収支seed数']
            for symbol in ['TOPIX', 'NK225']:
                baseline = candidate['symbols'][symbol]
                pf = baseline['gross_profit_yen'] / baseline['gross_loss_yen'] if baseline['gross_loss_yen'] else math.inf
                above = 0
                for case in results:
                    row = case['symbols'][symbol]
                    ratio = row['gross_profit_yen'] / row['gross_loss_yen'] if row['gross_loss_yen'] else (math.inf if row['gross_profit_yen'] else 0.)
                    above += ratio >= pf
                assert above == mode['symbols'][symbol]['候補以上のPF_seed数']


def evaluate_saved(helper) -> dict:
    """機能: 保存データを再生し、実現・含み損益と前回未読部分を区別する。

    引数: helper (module)。返り値: 現在途中の照合結果 (dict)。末尾を架空決済しない。
    """
    record, fixed = verify_saved()
    converted_path = LIVE / '足変換記録.json'
    converted = runner.read(converted_path) if converted_path.exists() else []
    indexed = {row['path']: row for row in converted}
    start, end, cutoff = [datetime.fromisoformat(record[key]) for key in ['session_start', 'session_end', '共通締切']]
    for symbol in ['TOPIX', 'NK225']:
        for minutes in [1, 5]:
            target = LIVE / f'candle_{minutes}min' / symbol / f"{record['session']}.csv"
            relative = target.relative_to(ROOT).as_posix()
            if target.exists():
                assert relative in indexed, f'来歴のない変換足: {relative}'
                assert runner.digest(target) == indexed[relative]['sha256'], f'変換済み足の変更: {relative}'
            else:
                row = helper.convert_candles(LIVE / '応答原本' / f'{symbol}_{minutes}min.json', symbol,
                                             minutes, record['session'], start, end, cutoff)
                indexed[relative] = row
                runner.save(converted_path, list(indexed.values()))
    legacy.OUT, legacy.LIVE = HERE, LIVE
    legacy.signals = SignalDispatcher
    output = legacy.evaluate_saved(helper)
    saved = pickle.loads((LIVE / 'replay.pkl').read_bytes())
    inputs = pickle.loads((LIVE / 'inputs.pkl').read_bytes())
    old_cutoff = datetime.fromisoformat('2026-09-29T17:25:00+09:00').timestamp()
    suffix = []
    for (identifier, symbol), result in saved.items():
        ready = inputs[(output['セッション'], symbol)]
        before = np.flatnonzero(ready['time_s'] < old_cutoff)
        start_equity = float(result['curve'][before[-1], 0]) if len(before) else 0.
        multiplier = result['config']['point_value']
        suffix.append({'手法ID': identifier, '銘柄': symbol,
                       '17時25分時価損益円': start_equity * multiplier,
                       '17時25分以降増減円': (float(result['curve'][-1, 0]) - start_equity) * multiplier})
    output['前回未読部分の増減'] = suffix
    output['取得前未閲覧の現在セッション'] = False
    output['注意'] = '17:25まで前作業で既読、以降は今回初取得。含み損益込み差額に既存玉の値動きも含む。途中結果は完了13セッションの合計に加えない。'
    verify_saved()
    for relative, row in indexed.items():
        assert runner.digest(ROOT / relative) == row['sha256']
    output['再生前後の固定記録と７応答原本のSHA256一致'] = True
    output['変換足４件のSHA256一致'] = len(indexed) == 4
    runner.save(LIVE / 'current_result.json', output)
    return output


def verify_saved() -> tuple[dict, dict]:
    """機能: 凍結記録、コード、７応答の同一性を再生前後に確認する。

    引数: なし。返り値: 取得記録・凍結記録 (tuple[dict,dict])。
    注意: 応答の参照先は今回LIVE内、ソースの参照先はプロジェクト内に限定する。
    """
    record = runner.read(LIVE / '取得記録.json')
    frozen_path = LIVE / '現在照合の凍結記録.json'
    assert record['ok'] and len(record['requests']) == 7
    assert runner.digest(frozen_path) == record['凍結記録SHA256'], '凍結記録の内容変更'
    fixed = runner.read(frozen_path)
    names = set()
    for item in record['requests']:
        path = (ROOT / item['path']).resolve()
        assert path.is_relative_to(LIVE.resolve()), f'今回取得領域の外を参照: {path}'
        assert item['ok'] and item['attempts'] == 1
        assert runner.digest(path) == item['sha256'], f'取得原本の内容変更: {path.name}'
        names.add(item['name'])
    assert names == {'status', 'TOPIX_book', 'NK225_book', 'TOPIX_1min', 'TOPIX_5min', 'NK225_1min', 'NK225_5min'}
    for relative, expected in fixed['ファイルSHA256'].items():
        path = (ROOT / relative).resolve()
        assert path.is_relative_to(ROOT.resolve())
        assert runner.digest(path) == expected, f'凍結後のソース変更: {relative}'
    return record, fixed


def main() -> None:
    """機能: 明示したモードで一回取得または保存済みデータの再計算を実行する。

    引数: mode (str) はfetch/saved。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['fetch', 'saved'])
    args = parser.parse_args()
    helper = legacy.load_module(ROOT / 'work/wave_v7/fetch_once.py', 'v26_once_helper')
    helper.LIVE = LIVE
    helper.FROZEN = LIVE / '現在照合の凍結記録.json'
    if args.mode == 'fetch':
        fetch_once(helper)
    output = evaluate_saved(helper)
    print(json.dumps({'共通締切': output['共通締切'], '結果': output['結果'],
                      '前回未読部分': output['前回未読部分の増減']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
