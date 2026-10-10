"""凍結した選抜関数の旧主案・同入口L000・乱数・思想境界を合成だけで検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import context_split_runner as runner
import research_selection as selector


def candidate(identifier: str, net: float = 75., drawdown: float = 80.) -> dict:
    """機能: 選抜の境界値だけに使う架空の候補を作る。

    引数: identifier (str)、net/drawdown (float)。返り値: 合成候補 (dict)。
    """
    signal, manager = identifier.split('__')
    row = {'net_yen': net, 'drawdown_yen': drawdown, 'best_removed_pf': 2., 'win_sessions': 9}
    return {'id': identifier, 'signal_id': signal, 'manager_id': manager, 'failures': [],
            'symbols': {symbol: deepcopy(row) for symbol in ('TOPIX', 'NK225')}}


def fixture() -> dict:
    """機能: 旧主案と同入口基準の両方の75%/80%境界を満たす合成資料を作る。

    引数: なし。返り値: 仮想ファイルごとの資料 (dict)。
    """
    own = candidate('H000__L001')
    modes = [{'発火時刻限定': gate, '試行数': 64, '両銘柄で候補以上の収支seed数': 3,
              'symbols': {symbol: {'候補以上のPF_seed数': 6} for symbol in ('TOPIX', 'NK225')}} for gate in (False, True)]
    return {'旧比較': {'上位30': [candidate('H019__D273', 100., 100.)]},
            '全条件の期間集計.json.gz': [deepcopy(own), candidate('H000__L000', 100., 100.)],
            '一次反証の結果.json': [{'candidate': deepcopy(own), 'first_stage_failures': []}],
            '無関係対照の要約.json': [{'candidate': deepcopy(own), 'summary': modes}],
            '無関係対照前の候補固定.json': [deepcopy(own)],
            'episode_audit.json': {'方法別要約': [{'method': own['id'], '対象区間数': 8, '目安達成区間数': 8}]},
            '探索条件の固定.json': {'signals': [{'id': 'H000', 'params': {'main_kind': 'ema8_30'}},
                                           {'id': 'H016', 'params': {'main_kind': 'ema15_60'}},
                                           {'id': 'H032', 'params': {'main_kind': 'momentum'}}],
                                  'managers': [{'id': 'L000'}, {'id': 'L001'}]}}


def invoke(files: dict) -> dict:
    """機能: 読取りと保存をメモリへ差し替えて元の選抜関数をそのまま実行する。

    引数: files (dict)。返り値: 選抜結果 (dict)。実相場資料を読まず、選抜結果も保存しない。
    """
    virtual = selector.HERE / '__合成境界検査専用__'
    assert not virtual.exists()

    def memory_read(path: Path) -> object:
        """機能: ファイル要求を同名の架空資料へ置き換える。

        引数: path (Path)。返り値: 合成内容のコピー (object)。
        """
        return deepcopy(files['旧比較' if path.name == '反証前の候補固定.json' else path.name])

    with patch.object(selector, 'HERE', virtual), patch.object(selector, 'plan', return_value={'合成': True}), \
            patch.object(runner, 'read', side_effect=memory_read), patch.object(runner, 'save'):
        return selector.select()


def main() -> None:
    """機能: 同入口基準の成立・不成立と片銘柄境界、両基準の独立性等を確認する。

    引数: なし。返り値: なし (None)。凍結した元選抜コードは変更しない。
    """
    output = []
    result = invoke(fixture())
    assert result['主候補'] == 'H000__L001'
    output.append({'検査': '旧主案・同入口とも収支75%/DD80%、乱数3/6の等号境界', '合格': True})
    for symbol in ('TOPIX', 'NK225'):
        for name, field, number, expected in (
            ('同入口だけ収支基準を超える', 'net_yen', 101., 'の同入口収益75%維持未達'),
            ('同入口だけDD基準を超える', 'drawdown_yen', 99., 'の同入口下落20%削減未達'),
            ('同入口収支0', 'net_yen', 0., 'の同入口基準が黒字かつ正のDDではない'),
            ('同入口収支が負', 'net_yen', -1., 'の同入口基準が黒字かつ正のDDではない'),
            ('同入口DD0', 'drawdown_yen', 0., 'の同入口基準が黒字かつ正のDDではない'),
        ):
            files = fixture()
            files['全条件の期間集計.json.gz'][1]['symbols'][symbol][field] = number
            result = invoke(files)
            assert result['主候補'] is None
            assert symbol + expected in result['棄却'][0]['reasons']
            output.append({'検査': symbol + ':' + name, '合格': True})
        for field, number, expected in (('net_yen', 101., 'の主案収益75%維持未達'),
                                         ('drawdown_yen', 99., 'の主案下落20%削減未達')):
            files = fixture()
            files['旧比較']['上位30'][0]['symbols'][symbol][field] = number
            result = invoke(files)
            assert result['主候補'] is None and symbol + expected in result['棄却'][0]['reasons']
            output.append({'検査': symbol + ':' + '同入口合格でも旧主案基準だけ未達', '項目': field, '合格': True})
    files = fixture()
    files['全条件の期間集計.json.gz'].append(candidate('H016__L000', 1000., 1.))
    assert invoke(files)['主候補'] == 'H000__L001'
    output.append({'検査': '他の入口L000を同入口比較へ誤用しない', '合格': True})
    files = fixture()
    files['全条件の期間集計.json.gz'] = files['全条件の期間集計.json.gz'][:1]
    try:
        invoke(files)
    except KeyError:
        output.append({'検査': '同入口L000欠落を拒否', '合格': True})
    else:
        raise AssertionError('L000欠落を許可した')
    for mode, field, symbol in ((0, '両銘柄で候補以上の収支seed数', None), (1, '候補以上のPF_seed数', 'TOPIX'),
                                (1, '候補以上のPF_seed数', 'NK225')):
        files = fixture()
        target = files['無関係対照の要約.json'][0]['summary'][mode]
        if symbol:
            target['symbols'][symbol][field] = 7
        else:
            target[field] = 4
        assert invoke(files)['主候補'] is None
        output.append({'検査': '乱数の境界超過を拒否', '対象': symbol or '両銘柄収支', '合格': True})
    for field in ('一次反証', '指定波'):
        files = fixture()
        if field == '一次反証':
            files['一次反証の結果.json'][0]['first_stage_failures'] = ['合成失敗']
        else:
            files['episode_audit.json']['方法別要約'][0]['目安達成区間数'] = 7
        assert invoke(files)['主候補'] is None
        output.append({'検査': field + 'の未達を拒否', '合格': True})

    # ----------------------------------------
    files = fixture()
    for index, signal in enumerate(('H016', 'H032'), 1):
        own = candidate(signal + '__L001')
        for row in own['symbols'].values():
            row['best_removed_pf'] = 2. - .1 * index
        files['全条件の期間集計.json.gz'].extend([deepcopy(own), candidate(signal + '__L000', 100., 100.)])
        files['一次反証の結果.json'].append({'candidate': deepcopy(own), 'first_stage_failures': []})
        files['無関係対照前の候補固定.json'].append(deepcopy(own))
        files['無関係対照の要約.json'].append({'candidate': deepcopy(own), 'summary': deepcopy(files['無関係対照の要約.json'][0]['summary'])})
        files['episode_audit.json']['方法別要約'].append({'method': own['id'], '対象区間数': 8, '目安達成区間数': 8})
    assert [row['id'] for row in invoke(files)['候補']] == ['H000__L001', 'H032__L001']
    output.append({'検査': 'EMA両系列を一思想にまとめ最大2案を選抜', '合格': True})
    path = Path(__file__).with_suffix('.json')
    record = {'新損益未読': True, '現在データ未読': True, '旧選抜コード変更なし': True, '合成境界検査': output,
              '研究選抜コードSHA256': hashlib.sha256(Path(selector.__file__).read_bytes()).hexdigest()}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'同入口・旧主案・乱数・波・思想の合成境界{len(output)}件を確認。新損益は未読。', flush=True)


if __name__ == '__main__':
    main()
