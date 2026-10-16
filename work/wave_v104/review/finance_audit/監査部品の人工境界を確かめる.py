"""監査の別算式が人工財務と破損を区別できるか確認する。正式結果は読まない。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WAVE = HERE.parents[1]


def module(name: str, path: Path) -> object:
    """
    機能: 小さい人工と監査sourceを読取接続する。
    引数: name(str)、path(Path)は固有名とsource。
    返り値: object。正式cache、正式金融結果、原本は読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def main() -> None:
    """
    機能: 正常人工と改変した料・時価・予約・停止線を監査へ渡す。
    引数: なし。
    返り値: None。私有監査人工だけを保存する。正式台帳読取は0。
    """
    auditor = module('104人工監査runner', HERE/'全121条件の会計と安定性を独立監査する.py')
    fixture = module('104監査人工素材', WAVE/'review/停止予約と注文経済の独立人工.py')
    core = module('104の支持境界と利益追尾執行', WAVE/'engine/core.py')
    catalog = module('104監査人工条件', WAVE/'catalog.py')
    checked, corrupt = 0, 0
    for symbol, cap in (('TOPIX', 10), ('NK225', 20)):
        for quantity in (1, cap//2):
            for side in (1, -1):
                for ident in ('B1', 'B2', 'B4', 'T2', 'T4'):
                    for name in ('平坦で長く保持', '支持ちょうど', '支持線を越えたfill', '利益発動後に次quote悪化',
                                 '返済予約中の不明', '受付境界と返済後停止', '候補なし'):
                        record, signal = fixture.fixture(symbol, side, ident, quantity, name)
                        exit_config = dict(catalog.exit_config(ident), quantity=quantity)
                        ledger = core.execute(record, signal, exit_config)
                        cfg = dict(id='人工', kind='single', entry_id='人工', exit_id=ident, quantity={symbol: quantity})
                        qok = record['quote_valid']
                        context = dict(symbol=symbol, record=record, raw=dict(qualified=np.ones(len(qok), bool), execution_to_raw_index=signal['execution_to_raw_index']),
                            cases={'人工': signal}, qok=qok, good=np.flatnonzero(qok),
                            last=np.maximum.accumulate(np.where(qok, np.arange(len(qok)), -1)),
                            prepared=dict(reference_open=signal['reference_open'], signal=dict(trend_width=signal['trend_width'])))
                        row, connection = auditor.LEDGER.audit(ledger, context, cfg)
                        independent = fixture.oracle(record, signal, exit_config)
                        assert row['net'] == float(independent['cash'])
                        checked += 1
                        if symbol == 'TOPIX' and quantity == 1 and side == 1 and ident == 'T2' and name == '支持ちょうど':
                            for field in ('fee', 'curve', 'trace', 'judgment'):
                                changed = deepcopy(ledger)
                                if field == 'fee':
                                    changed['orders'][0, 9] += 1
                                elif field == 'curve':
                                    changed['curve'][2] += 1
                                elif field == 'trace':
                                    changed['target_trace'][1, 4] += 1
                                else:
                                    changed['judgments'][0, 17] += record['tick']
                                try:
                                    auditor.LEDGER.audit(changed, context, cfg)
                                except AssertionError:
                                    corrupt += 1
                                else:
                                    raise AssertionError('破損を拒否しませんでした。'+field)
    paths = [Path(__file__), HERE/'全121条件の会計と安定性を独立監査する.py', HERE/'入力と集計の独立部品.py', HERE/'台帳と停止線の独立部品.py']
    value = dict(全合格=True, scope='新監査部品の私有人工財務。全state入力と正式結果は未読。',
        検査件数=dict(人工口座=checked, 破損拒否=corrupt),
        SHA256={str(path.relative_to(WAVE)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        正式新台帳読取=0, 正式入力読取=0, 正式金融再生=0, 原本読取=0, NPZ読取=0, API=0, goal操作=0)
    target = HERE/'全数監査部品の私有人工.json'
    assert not target.exists()
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=value['検査件数'], SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
