"""保存段階が欠けても合格にしない報告分岐を、合成保存物だけで検査する。"""

from __future__ import annotations

import copy
from datetime import datetime
import gzip
import json
from pathlib import Path

import report_round4 as report

HERE = Path(__file__).resolve().parent


def save(path: Path, value: object) -> None:
    """機能: 合成のJSON・圧縮JSONを新しい専用領域へ保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.gz':
        with gzip.open(path, 'wt', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def stage_tests() -> dict:
    """機能: 未保存・途中・重複・最終候補なしの保存段階を区別する。

    引数: なし。返り値: 合成分岐の検算件数 (dict)。
    """
    identifier = 'H001__J000'
    candidate = {'id': identifier}
    gate = {'全条件数': 27648, '反証候補': [candidate]}
    first = [{'candidate': candidate, 'first_stage_failures': []}]
    random = [{'candidate': candidate}]
    selected = {'候補': []}
    waves = [report.BASE, 'F32__G08', 'D016__D065', 'P02__D065', identifier]
    episode = {'方法別要約': [{'method': key, '対象区間数': 8} for key in waves],
               '結果': [{'method': key, 'wave': wave, 'symbol': symbol} for key in waves
                        for wave in ('W01', 'W02', 'W03', 'W04') for symbol in report.SYMBOLS]}
    full = (gate, first, random, [candidate], episode, selected, {identifier: True})
    assert report.completeness(*full)['最終資料完備']
    tests = 1
    for slot in range(6):
        changed = list(full)
        changed[slot] = None
        assert not report.completeness(*changed)['最終資料完備']
        tests += 1
    for slot in (1, 2):
        changed = list(full)
        changed[slot] = []
        assert not report.completeness(*changed)['最終資料完備']
        changed[slot] = full[slot] * 2
        assert not report.completeness(*changed)['最終資料完備']
        tests += 2
    changed = list(full)
    changed[6] = {identifier: False}
    assert not report.completeness(*changed)['乱数対照完了']
    tests += 1
    for mutation in ('欠落', '重複'):
        bad = copy.deepcopy(episode)
        if mutation == '欠落':
            bad['結果'].pop()
        else:
            bad['結果'].append(copy.deepcopy(bad['結果'][-1]))
        changed = list(full)
        changed[4] = bad
        assert not report.completeness(*changed)['指定波完了']
        tests += 1
    return {'最終候補なしも資料完了として表示可能': True, '未保存不足重複の拒否を含む検査数': tests}


def random_tests() -> dict:
    """機能: 64seed×２方式の欠落・重複・要約不一致を完了扱いにしないことを確認する。

    引数: なし。返り値: 合成保存物の検算 (dict)。
    """
    fixture = HERE / 'report_contract_fixture' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    identifier = 'H001__J000'
    candidate = {'id': identifier, 'symbols': {s: {'net_yen': 10.} for s in report.SYMBOLS}}
    modes = [{'発火時刻限定': gated, '試行数': 64, '両銘柄で候補以上の収支seed数': 0} for gated in (False, True)]
    item = {'candidate': candidate, 'summary': modes}
    source = {'candidate': candidate, 'summary': modes,
              'results': [{'seed': seed, 'gated': gated, 'symbols': {s: {'net_yen': 0.} for s in report.SYMBOLS}}
                          for gated in (False, True) for seed in range(64)]}
    original = report.HERE
    try:
        report.HERE = fixture
        path = fixture / 'randomized' / (identifier + '.json.gz')
        assert not report.complete_random(item)
        save(path, source)
        assert report.complete_random(item)
        short = copy.deepcopy(source)
        short['results'].pop()
        save(path, short)
        assert not report.complete_random(item)
        duplicate = copy.deepcopy(source)
        duplicate['results'][-1] = copy.deepcopy(duplicate['results'][0])
        save(path, duplicate)
        assert not report.complete_random(item)
        incorrect = copy.deepcopy(source)
        incorrect['results'][0]['symbols'] = {s: {'net_yen': 20.} for s in report.SYMBOLS}
        save(path, incorrect)
        assert not report.complete_random(item)
        return {'全128seed正常': True, '保存なし試行不足重複要約不整合を拒否': 4}
    finally:
        report.HERE = original


def selection_tests() -> dict:
    """機能: 既定の75％収益・80％下落・８波・乱数条件の表示前照合を確認する。

    引数: なし。返り値: 境界と違反検査 (dict)。新しい選抜条件は作らない。
    """
    identifier = 'H001__J000'
    selected = {'候補': [{'id': identifier}]}
    first = [{'candidate': {'id': identifier}, 'first_stage_failures': []}]
    modes = [{'両銘柄で候補以上の収支seed数': 3,
              'symbols': {s: {'候補以上のPF_seed数': 6} for s in report.SYMBOLS}} for _ in range(2)]
    random = [{'candidate': {'id': identifier}, 'summary': modes}]
    episode = {'方法別要約': [{'method': identifier, '対象区間数': 8, '目安達成区間数': 8}]}
    data = {report.BASE: {'symbols': {s: {'net_yen': 100., 'drawdown_yen': 20.} for s in report.SYMBOLS}},
            identifier: {'symbols': {s: {'net_yen': 75., 'drawdown_yen': 16.} for s in report.SYMBOLS}}}
    report.check_selection(selected, first, random, episode, data)
    for field, value in [('net_yen', 74.), ('drawdown_yen', 17.)]:
        bad = copy.deepcopy(data)
        bad[identifier]['symbols']['TOPIX'][field] = value
        try:
            report.check_selection(selected, first, random, episode, bad)
        except AssertionError:
            pass
        else:
            raise AssertionError('金額目標違反を見逃しました')
    bad_episode = copy.deepcopy(episode)
    bad_episode['方法別要約'][0]['目安達成区間数'] = 7
    try:
        report.check_selection(selected, first, random, bad_episode, data)
    except AssertionError:
        pass
    else:
        raise AssertionError('指定波未達を見逃しました')
    try:
        report.read(HERE / 'live' / 'current_result.json')
    except AssertionError:
        pass
    else:
        raise AssertionError('現在スナップショットの参照が許可されました')
    return {'75％収益と80％下落の境界は許可': True, '片側金額目標違反2件と7波を拒否': True,
            '現在保存物の読取りを拒否': True}


def main() -> None:
    """機能: 報告用の分岐・保存物検算だけを実行する。

    引数: なし。返り値: なし (None)。実相場の売買・現在APIを使用しない。
    """
    result = {'段階分岐': stage_tests(), '乱数保存の完全性': random_tests(), '選定表示の境界': selection_tests(),
              '合成だけの検査': True, 'API取得': 0, '売買再生': False,
              '報告コードSHA256': report.sha256((HERE / 'report_round4.py').read_bytes()).hexdigest()}
    save(HERE / 'report_contract_audit.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
