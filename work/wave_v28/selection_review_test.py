"""候補選抜を合成資料だけで点検する。探索損益・現在データ・固定コードは変更しない。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json
import math

import context_runner as runner
import research_selection as selector


def candidate(identifier: str, signal: str, net: float = 75., drawdown: float = 80.) -> dict:
    """機能: 境界判定と順位だけに使う架空の候補を生成する。

    引数: identifier/signal (str)、net/drawdown (float)。返り値: 合成候補 (dict)。
    """
    row = {'net_yen': net, 'drawdown_yen': drawdown, 'best_removed_pf': 2., 'win_sessions': 9}
    return {'id': identifier, 'signal_id': signal, 'manager_id': 'J000',
            'signal_family': signal, 'manager_family': '合成', 'failures': [],
            'symbols': {symbol: deepcopy(row) for symbol in ('TOPIX', 'NK225')}}


def fixture() -> dict:
    """機能: 一候補が全ての宣言済み境界をちょうど満たす合成資料を作る。

    引数: なし。返り値: 仮想ファイル名別の内容 (dict)。
    """
    own = candidate('H000__J000', 'H000')
    modes = [{'発火時刻限定': gate, '試行数': 64, '両銘柄で候補以上の収支seed数': 3,
              'symbols': {symbol: {'候補以上のPF_seed数': 6} for symbol in ('TOPIX', 'NK225')}}
             for gate in (False, True)]
    return {
        '旧比較': {'上位30': [candidate('H019__D273', 'H019', 100., 100.)]},
        '一次反証の結果.json': [{'candidate': deepcopy(own), 'first_stage_failures': [], 'validation_sha': '合成SHA'}],
        '無関係対照の要約.json': [{'candidate': deepcopy(own), 'summary': modes, 'validation_sha': '合成SHA'}],
        '無関係対照前の候補固定.json': [deepcopy(own)],
        'episode_audit.json': {'方法別要約': [{'method': own['id'], '対象区間数': 8, '目安達成区間数': 8}]},
        '探索条件の固定.json': {'signals': [{'id': 'H000', 'params': {'main_kind': 'ema8_30'}},
                               {'id': 'H016', 'params': {'main_kind': 'ema15_60'}},
                               {'id': 'H032', 'params': {'main_kind': 'momentum'}}],
                          'managers': [{'id': 'J000', 'changes': {}}]},
    }


def run_case(name: str, files: dict) -> dict:
    """機能: 全JSON読取りと保存をメモリへ差し替え、実選抜関数を実行する。

    引数: name (str)、files (dict)。返り値: 採用・拒否・参照資料の記録 (dict)。
    実ファイルを読まず、仮想の選抜固定JSONもディスクへ保存しない。
    """
    reads = []
    virtual = selector.HERE / '__合成選抜点検専用__'
    assert not virtual.exists()

    def memory_read(path: Path) -> object:
        """機能: ファイルアクセスを架空資料のコピーへ置き換える。

        引数: path (Path)。返り値: 合成資料 (object)。
        """
        reads.append(path.name)
        key = '旧比較' if path.name == '反証前の候補固定.json' else path.name
        return deepcopy(files[key])

    def memory_save(path: Path, value: object) -> None:
        """機能: 合成選抜の保存要求を受け取り、ディスクへ書かず破棄する。

        引数: path (Path)、value (object)。返り値: なし (None)。
        """
        assert path.name == '研究候補の固定.json'

    with patch.object(selector, 'HERE', virtual), patch.object(selector, 'plan', return_value={'合成': True}), \
            patch.object(runner, 'read', side_effect=memory_read), patch.object(runner, 'save', side_effect=memory_save):
        try:
            result = selector.select()
            return {'検査': name, '資料不正を例外拒否': False,
                    '採用ID': [row['id'] for row in result['候補']],
                    '棄却理由': [row['reasons'] for row in result['棄却']], '読取要求': reads}
        except (AssertionError, KeyError, ValueError, TypeError) as error:
            return {'検査': name, '資料不正を例外拒否': True, '例外種別': type(error).__name__, '読取要求': reads}


def main() -> None:
    """機能: 数値境界と不完全資料の反例を固定コードへ入力して報告する。

    引数: なし。返り値: なし (None)。全て合成であり実際の新探索成績は読まない。
    """
    output = []
    output.append(run_case('75%収支・80%DD・収支seed3・PFseed6の等号境界', fixture()))
    for name, symbol, field, value in [
        ('TOP収益75%未達', 'TOPIX', 'net_yen', 74.99),
        ('NK収益75%未達', 'NK225', 'net_yen', 74.99),
        ('TOPのDD80%超過', 'TOPIX', 'drawdown_yen', 80.01),
        ('NKのDD80%超過', 'NK225', 'drawdown_yen', 80.01),
    ]:
        files = fixture()
        files['無関係対照の要約.json'][0]['candidate']['symbols'][symbol][field] = value
        output.append(run_case(name, files))
    for name, mutation in [
        ('乱数方式不足', 'mode_short'), ('乱数方式重複', 'mode_duplicate'),
        ('同一候補を予定と要約の双方で重複', 'candidate_duplicate'),
        ('一次反証の重複に合格と不合格が混在', 'first_conflict'),
        ('一次反証と乱数要約の候補数値が不一致', 'candidate_mismatch'),
        ('反証SHAが不一致', 'sha_mismatch'),
        ('不正な負のseed該当数', 'negative_count'),
        ('候補の収益とDDがNaN', 'nan'),
        ('一次通過ありだが乱数予定と結果は空', 'empty_random'),
        ('波要約が同一候補の合格と不合格で重複', 'wave_conflict'),
    ]:
        files = fixture()
        if mutation == 'mode_short':
            files['無関係対照の要約.json'][0]['summary'].pop()
        elif mutation == 'mode_duplicate':
            files['無関係対照の要約.json'][0]['summary'][1]['発火時刻限定'] = False
        elif mutation == 'candidate_duplicate':
            for key in ('無関係対照の要約.json', '無関係対照前の候補固定.json'):
                files[key].append(deepcopy(files[key][0]))
        elif mutation == 'first_conflict':
            duplicate = deepcopy(files['一次反証の結果.json'][0])
            duplicate['first_stage_failures'] = ['架空の反証不合格']
            files['一次反証の結果.json'].append(duplicate)
        elif mutation == 'candidate_mismatch':
            files['一次反証の結果.json'][0]['candidate']['symbols']['TOPIX']['net_yen'] = -100.
        elif mutation == 'sha_mismatch':
            files['無関係対照の要約.json'][0]['validation_sha'] = '別SHA'
        elif mutation == 'negative_count':
            files['無関係対照の要約.json'][0]['summary'][0]['両銘柄で候補以上の収支seed数'] = -10
        elif mutation == 'nan':
            for symbol in ('TOPIX', 'NK225'):
                files['無関係対照の要約.json'][0]['candidate']['symbols'][symbol].update(net_yen=math.nan, drawdown_yen=math.nan)
        elif mutation == 'empty_random':
            files['無関係対照の要約.json'] = []
            files['無関係対照前の候補固定.json'] = []
        elif mutation == 'wave_conflict':
            duplicate = deepcopy(files['episode_audit.json']['方法別要約'][0])
            duplicate['目安達成区間数'] = 0
            files['episode_audit.json']['方法別要約'].append(duplicate)
        output.append(run_case(name, files))

    # ----------------------------------------
    files = fixture()
    for index, signal in enumerate(('H016', 'H032'), start=1):
        own = candidate(signal + '__J000', signal, 75. - index * .001, 79.)
        for symbol in own['symbols']:
            own['symbols'][symbol]['best_removed_pf'] = 2. - index * .1
            own['symbols'][symbol]['net_yen'] = 75.
        files['一次反証の結果.json'].append({'candidate': deepcopy(own), 'first_stage_failures': []})
        files['無関係対照前の候補固定.json'].append(deepcopy(own))
        example = deepcopy(files['無関係対照の要約.json'][0])
        example['candidate'] = deepcopy(own)
        files['無関係対照の要約.json'].append(example)
        files['episode_audit.json']['方法別要約'].append({'method': own['id'], '対象区間数': 8, '目安達成区間数': 8})
    output.append(run_case('EMA2系列を一思想にして次の価格差思想を選抜', files))
    assert output[0]['採用ID'] == ['H000__J000']
    assert all(not row.get('採用ID') for row in output[1:5])
    assert output[-1]['採用ID'] == ['H000__J000', 'H032__J000']
    record = {'実データ損益未参照': True, '現在データ未参照': True, '選抜固定コード変更なし': True,
              '合成事例数': len(output), '結果': output}
    path = Path(__file__).with_name('selection_review_test.json')
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps([{k: v for k, v in row.items() if k != '読取要求'} for row in output], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
