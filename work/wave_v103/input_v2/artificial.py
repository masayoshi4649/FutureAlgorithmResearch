"""保存v1のFalse反例を再現し、二列だけの訂正と人工接頭不変を確認する。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V1 = HERE.parent/'input'
JST = timezone(timedelta(hours=9))
START = datetime(2000, 1, 3, 17, tzinfo=JST).timestamp()


def module(name: str, path: Path) -> object:
    """
    機能: v1抽出器とv2訂正器を固有名で読む。
    引数: name(str)、path(Path)は名前と位置。
    返り値: objectは実装。v1 sourceは変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def fixture(offsets: list[float], volumes: list[float] | None = None) -> list[tuple[int, dict]]:
    """
    機能: 出来高clockを一定とし、価格clockだけを独立に変える人工原行を作る。
    引数: offsets(list[float])、volumes(list[float]|None)は価格秒と累計量。
    返り値: list[tuple[int,dict]]は原seqと人工原行。
    """
    rows = []
    for i, offset in enumerate(offsets):
        bid = 100.+i*.5
        raw = dict(Symbol='人工v2', SymbolName='二時計の独立反例', Exchange=2,
            CurrentPrice=bid+.25,
            CurrentPriceTime=datetime.fromtimestamp(START+offset, JST).isoformat(),
            TradingVolume=100+i*5 if volumes is None else volumes[i],
            TradingVolumeTime=datetime.fromtimestamp(START, JST).isoformat(), TradingValue=100000+i*1000)
        for level in range(1, 11):
            raw[f'Buy{level}'] = dict(Price=bid-(level-1)*.5, Qty=5.+level)
            raw[f'Sell{level}'] = dict(Price=bid+level*.5, Qty=6.+level)
        rows.append((i, raw))
    return rows


def equal_except_changed(old: dict, revised: dict, names: tuple[str, str]) -> int:
    """
    機能: 訂正対象を除く42配列の型、形状及び値を厳密に比較する。
    引数: old/revised(dict)、names(tuple[str,str])は元、訂正及び変更可能列。
    返り値: intは完全一致した不変配列数。
    """
    assert old.keys() == revised.keys()
    count = 0
    for name in old:
        if name in names:
            continue
        assert old[name].dtype == revised[name].dtype and old[name].shape == revised[name].shape
        np.testing.assert_array_equal(old[name], revised[name])
        count += 1
    assert count == 42
    return count


def main() -> None:
    """
    機能: 原本を読まず4行人工でFalse→訂正、42不変列、接頭不変及び保存往復を確かめる。
    引数: なし。
    返り値: None。全64正式派生、原本再読取及び金融再生は0。
    """
    correction = module('v2人工だけの二列訂正103', HERE/'correction.py')
    old_core = module('v2人工だけの不変v1抽出103', V1/'core.py')
    destination = HERE/'前価格時計逆行の二列訂正と人工未来不変.json'
    assert not destination.exists()
    before = {str((V1/name).relative_to(ROOT)): correction.DATA.digest(V1/name)
              for name in ('core.py', 'data.py', 'prepare.py', 'artificial.py', '入力schema.json',
                           '原本抽出前の32場登録.json', 'metadata.json', 'v1の価格時計逆行後usableの反例.json')}
    rows = fixture([0, 10, 5, 20])
    old, _ = old_core.extract_rows(rows, START, START+1000)
    revised, diagnostic = correction.correct_arrays(old)
    assert old['volume_delta_usable'].tolist() == [False, True, False, True]
    assert revised['volume_delta_usable'].tolist() == [False, True, False, False]
    assert old['volume_delta'][3] == 5 and np.isnan(revised['volume_delta'][3])
    assert diagnostic['usable変更行数'] == diagnostic['支持用差変更行数'] == 1
    immutable_arrays = equal_except_changed(old, revised, correction.CHANGED)
    prefix_old, _ = old_core.extract_rows(rows[:3], START, START+1000)
    prefix, _ = correction.correct_arrays(prefix_old)
    changed_rows = deepcopy(rows)
    changed_rows[3][1]['TradingVolume'] = None
    changed_rows[3][1]['Buy1']['Qty'] = 99999
    future_old, _ = old_core.extract_rows(changed_rows, START, START+1000)
    future, _ = correction.correct_arrays(future_old)
    for name in revised:
        if name == 'execution_to_raw_index':
            np.testing.assert_array_equal(prefix[name], revised[name])
            np.testing.assert_array_equal(prefix[name], future[name])
        else:
            np.testing.assert_array_equal(prefix[name], revised[name][:3])
            np.testing.assert_array_equal(prefix[name], future[name][:3])
    controls = []
    for offsets, volumes in (([0, 10, 20, 30], None), ([0, 0, 10, 20], [100, 100, 105, 110])):
        control_old, _ = old_core.extract_rows(fixture(offsets, volumes), START, START+1000)
        control, counts = correction.correct_arrays(control_old)
        for name in control:
            np.testing.assert_array_equal(control_old[name], control[name])
        assert counts['usable変更行数'] == counts['支持用差変更行数'] == 0
        controls.append(dict(価格clock秒=offsets, 変更行数=0, 既知0を保持=True))
    normal = dict(seq=np.array([0, 1, 3], np.int64), time_s=np.array([START, START+10, START+20]),
                  price=np.array([100.25, 100.75, 101.75]), bid=np.array([100., 100.5, 101.5]),
                  ask=np.array([100.5, 101., 102.]))
    mapped_old, _ = old_core.extract_rows(rows, START, START+1000, normal)
    mapped, _ = correction.correct_arrays(mapped_old)
    assert equal_except_changed(mapped_old, mapped, correction.CHANGED) == 42
    assert mapped['execution_to_raw_index'].tolist() == [0, 1, 3]
    folder = HERE/'人工保存'
    folder.mkdir(exist_ok=False)
    path = folder/'二列訂正.npz'
    np.savez_compressed(path, **mapped)
    with np.load(path, allow_pickle=False) as saved:
        assert set(saved.files) == set(mapped)
        for name in mapped:
            np.testing.assert_array_equal(saved[name], mapped[name])
    process = subprocess.run([sys.executable, '-X', 'utf8', str(HERE/'correction.py')],
                             cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert process.returncode == 2 and '--root-v2-reviewed' in process.stderr
    assert before == {name: correction.DATA.digest(ROOT/name) for name in before}
    schema_path = HERE/'入力schema.json'
    correction.save(schema_path, correction.schema())
    source = {str((HERE/name).relative_to(ROOT)): correction.DATA.digest(HERE/name)
              for name in correction.SOURCE_NAMES}
    correction.save(destination, dict(全合格=True, 人工原行数=4,
        v1の局所Falseを再現=True, v1_usable=[False, True, False, True], v2_usable=[False, True, False, False],
        二列だけ訂正=True, 不変配列数=immutable_arrays, 元原行及び旧執行map不変=True,
        known及びraw観測値不変=True, 人工変更行数=1, 対照=controls,
        全44列の実接頭切断及び未来変更不変=True, 人工pickleなし保存往復=True,
        CLI無フラグ拒否終了コード=process.returncode, 保持v1_SHA256=before, コードSHA256=source,
        v2schemaSHA256=correction.DATA.digest(schema_path), 人工保存SHA256=correction.DATA.digest(path),
        正式全64派生=0, 原本再読取=0, 金融再生=0, 現在API取得=0, 実注文=0))
    print('v1 Falseを人工4行で訂正、他42列/原行/旧map不変・接頭不変・保存往復が一致', flush=True)


if __name__ == '__main__':
    main()
