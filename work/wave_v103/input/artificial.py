"""全原行抽出の小人工だけを検査し、正式64原本及び金融結果を読まない。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import traceback

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import core
import data

JST = timezone(timedelta(hours=9))
START = datetime(2000, 1, 3, 17, tzinfo=JST).timestamp()
END = START + 1000


def text_time(offset: float) -> str:
    """
    機能: 人工時計をtimezone付き文字列へ変換する。
    引数: offset(float)は人工開始からの秒数。
    返り値: strは日本時間の日時文字列。
    """
    return datetime.fromtimestamp(START+offset, JST).isoformat()


def fixture(count: int = 5) -> list[tuple[int, dict]]:
    """
    機能: 正常十段と別出来高時計を持つ小人工原行を作る。
    引数: count(int)は人工行数。
    返り値: list[tuple[int,dict]]は実データと混同しない原seqと人工原行。
    """
    rows = []
    for index in range(count):
        bid = 100.+index*.5
        row = dict(Symbol='人工TOPIX', SymbolName='人工入力検査専用', Exchange=2,
            CurrentPrice=bid+.25, CurrentPriceTime=text_time(index*10),
            TradingVolume=100.+index*5, TradingVolumeTime=text_time(index*10),
            TradingValue=100000.+index*1000)
        for depth in range(1, 11):
            row[f'Buy{depth}'] = dict(Price=bid-(depth-1)*.5, Qty=3.+depth)
            row[f'Sell{depth}'] = dict(Price=bid+depth*.5, Qty=4.+depth)
        rows.append((index, row))
    return rows


def extract(rows: list[tuple[int, dict]]) -> dict:
    """
    機能: 人工原行だけを同じ正式抽出器へ渡す。
    引数: rows(list[tuple[int,dict]])は人工原行。
    返り値: dictは全原行の配列。原本ファイル及び金融結果は読まない。
    """
    return core.extract_rows(rows, START, END)[0]


def past_equal(left: dict, right: dict, count: int) -> int:
    """
    機能: 抽出済み配列の過去部分を欠損込みで比較する。
    引数: left/right(dict)、count(int)は二入力と比較行数。
    返り値: intは一致した配列数。執行対応の空配列は全体を比較する。
    """
    assert left.keys() == right.keys()
    for name in left:
        a, b = (left[name], right[name]) if name == 'execution_to_raw_index' else (left[name][:count], right[name][:count])
        np.testing.assert_array_equal(a, b)
    return len(left)


def raises(callback: object) -> str:
    """
    機能: 拒否すべき人工入力が例外で停止することを確かめる。
    引数: callback(Callable[[],object])は人工処理。
    返り値: strは例外型。拒否されなければ検査を失敗させる。
    """
    try:
        callback()
    except AssertionError as error:
        return type(error).__name__
    raise AssertionError('拒否すべき人工入力が通過しました')


def main() -> None:
    """
    機能: 時計の分離、不明・reset、原seq対応、未来不変及び保存往復を小人工で検算する。
    引数: なし。
    返り値: None。正式原本抽出、金融再生、API取得及び実注文はいずれも0。
    """
    destination = HERE/'人工抽出と時計及び欠測と執行対応の検査.json'
    assert not destination.exists(), '完成人工検査を上書きしません'
    baseline = fixture()
    normal = dict(seq=np.array([0, 1, 4], np.int64),
        time_s=np.array([START, START+10, START+40]), price=np.array([100.25, 100.75, 102.25]),
        bid=np.array([100., 100.5, 102.]), ask=np.array([100.5, 101., 102.5]))
    arrays, diagnosis = core.extract_rows(baseline, START, END, normal)
    assert diagnosis['raw_rows'] == 5 and diagnosis['normal_execution_rows'] == 3
    assert arrays['execution_to_raw_index'].tolist() == [0, 1, 4]
    assert arrays['normal_execution_row'].tolist() == [0, 1, -1, -1, 2]
    assert arrays['volume_delta_known'].tolist() == [False, True, True, True, True]
    assert arrays['volume_delta_usable'].tolist() == [False, True, True, True, True]
    assert np.isnan(arrays['volume_delta'][0]) and (arrays['volume_delta'][1:] == 5).all()
    assert not arrays['trading_value_time_known'].any()
    assert not diagnosis['inferred_aggressor_volume'] and not diagnosis['trade_or_cancel_identified']
    cases = ['正常全原行と旧執行5列の全対応', '累計売買代金の時計不明を別保持し方向約定へ再構成しない']

    # ----------------------------------------
    # 同clock後続は独立原行として保存し、既知0の出来高差と不明を区別する。
    rows = fixture()
    rows[1][1]['CurrentPriceTime'] = rows[0][1]['CurrentPriceTime']
    rows[1][1]['TradingVolumeTime'] = rows[0][1]['TradingVolumeTime']
    rows[1][1]['TradingVolume'] = rows[0][1]['TradingVolume']
    value = extract(rows)
    assert value['raw_seq'].tolist() == list(range(5))
    assert value['price_time_s'][0] == value['price_time_s'][1]
    assert value['volume_delta_usable'][1] and value['volume_delta'][1] == 0
    assert value['bid'][0] != value['bid'][1]
    cases.append('同価格clock後続の板変更を削除せず既知0と不明を区別')

    for missing in ('TradingVolume', 'TradingVolumeTime'):
        rows = fixture()
        rows[1][1][missing] = None
        value = extract(rows)
        assert not value['volume_delta_known'][1:3].any()
        assert np.isnan(value['volume_delta'][1:3]).all()
        assert value['volume_delta_usable'][3]
        cases.append(missing+'の欠測と次原行を0又は支持へ補完しない')

    rows = fixture()
    rows[1][1]['CurrentPriceTime'] = None
    value = extract(rows)
    assert value['volume_delta_known'][1:3].all()
    assert not value['volume_delta_usable'][1:3].any()
    assert np.isnan(value['volume_delta'][1:3]).all()
    assert value['price_reset_reason'][1] & 4 and value['price_reset_reason'][2] & 64
    assert value['volume_delta_usable'][3]
    cases.append('価格代理時計欠測では出来高差knownとusableを分離')

    rows = fixture()
    rows[1][1]['TradingVolumeTime'] = text_time(11)
    value = extract(rows)
    assert value['volume_delta_known'][1:3].all()
    assert not value['volume_delta_usable'][1:3].any()
    assert value['volume_delta_usable'][3]
    cases.append('両原行それぞれvolume時計<=price時計がなければ支持用差はNaN')

    rows = fixture()
    rows[2][1]['CurrentPriceTime'] = text_time(5)
    value = extract(rows)
    assert value['price_reset_reason'][2] & 8 and value['price_reset_reason'][3] & 64
    assert not value['price_transition_valid'][2:4].any()
    assert not value['volume_delta_usable'][2:4].any() and value['volume_delta_usable'][4]
    cases.append('価格clock逆行をソートせず拒否flagと次原行の断裂で保持')

    rows = fixture()
    rows[2][1]['TradingVolumeTime'] = text_time(5)
    value = extract(rows)
    assert value['volume_reset_reason'][2] & 64 and value['volume_reset_reason'][3] & 128
    assert not value['volume_delta_known'][2:4].any()
    assert value['volume_delta_known'][4]
    cases.append('出来高clock逆行を独立resetへ分離')

    rows = fixture()
    rows[2][1]['TradingVolume'] = 1.
    rows[3][1]['TradingVolume'] = 4.
    rows[4][1]['TradingVolume'] = 8.
    value = extract(rows)
    assert value['volume_reset_reason'][2] & 32 and not value['volume_delta_known'][2]
    assert value['volume_delta_usable'][3] and value['volume_delta'][3] == 3
    cases.append('累計出来高減少をresetとし後の新しい基準間の差だけを許可')

    rows = fixture()
    rows = [(seq if seq < 2 else seq+1, raw) for seq, raw in rows]
    value = extract(rows)
    assert value['raw_seq'].tolist() == [0, 1, 3, 4, 5]
    assert value['price_reset_reason'][2] & 2 and value['volume_reset_reason'][2] & 2
    assert not value['volume_delta_known'][2] and value['volume_delta_known'][3]
    cases.append('原seq断裂の未知区間へ量や表示変化を補完しない')

    rows = fixture()
    rows[1][1]['Sell10'] = None
    rows[2][1]['Buy5']['Price'] = rows[2][1]['Buy4']['Price']
    value = extract(rows)
    assert np.isnan(value['ask_prices'][1, 9]) and not value['ask_element_valid'][1, 9]
    assert not value['depth_valid'][1:3].any() and value['price_row_valid'][1:3].all()
    assert value['depth_reset_reason'][1] & 128 and value['depth_reset_reason'][3] & 256
    assert value['bid_prices'][2, 4] == value['bid_prices'][2, 3]
    cases.append('十段欠測及び重複価格を修復せず最良資格と分離')

    rows = fixture()
    rows[1][1]['Buy1']['Qty'] = 0
    rows[2][1]['Sell8']['Qty'] = -2
    rows[3][1]['Buy2']['Qty'] = True
    value = extract(rows)
    assert value['bid_qty'][1] == 0 and not value['best_quantity_valid'][1]
    assert value['ask_quantities'][2, 7] == -2 and not value['ask_element_valid'][2, 7]
    assert np.isnan(value['bid_quantities'][3, 1]) and not value['bid_element_valid'][3, 1]
    assert value['lp_row_valid'][1:4].all()
    cases.append('最良数量0・負数量・boolを別資格としLPで板を救済しない')

    rows = fixture()
    rows[1][1]['CurrentPriceTime'] = text_time(-1)
    rows[1][1]['TradingVolumeTime'] = text_time(-1)
    value = extract(rows)
    assert len(value['raw_seq']) == 5 and not value['in_session'][1]
    assert value['price_reset_reason'][1] & 16 and value['volume_reset_reason'][1] & 16
    cases.append('場外原行を落とさず使用不能の資格へ保持')

    rows = fixture()
    rows[1][1]['Symbol'] = '別限月'
    identity_rejection = raises(lambda: extract(rows))
    rows = fixture()
    del rows[1][1]['Exchange']
    missing_identity_rejection = raises(lambda: extract(rows))
    wrong = dict(normal, bid=normal['bid']+.5)
    mismatch_rejection = raises(lambda: core.extract_rows(baseline, START, END, wrong))
    prefix = extract(baseline[:3])
    complete = extract(baseline)
    changed = deepcopy(baseline)
    changed[3][1]['Buy1']['Qty'] = 50000
    changed[4][1]['TradingVolume'] = None
    equal_count = past_equal(prefix, complete, 3) + past_equal(prefix, extract(changed), 3)
    cases.append('未来原行の切断及び変更で全過去入力列は不変')

    # ----------------------------------------
    # 一回JSONL読取hash・npz保存往復を人工ファイルだけで確認する。
    folder = HERE/'人工保存'
    folder.mkdir(exist_ok=False)
    raw_path = folder/'人工.jsonl'
    encoded = b''.join((json.dumps(raw, ensure_ascii=False)+'\n').encode('utf-8') for _, raw in baseline)
    raw_path.write_bytes(encoded)
    one, one_diagnosis = core.extract_jsonl(raw_path, START, END, normal)
    assert one_diagnosis['raw_SHA256'] == hashlib.sha256(encoded).hexdigest()
    assert one_diagnosis['raw_bytes'] == len(encoded)
    for name in arrays:
        np.testing.assert_array_equal(one[name], arrays[name])
    output_path = folder/'人工.npz'
    np.savez_compressed(output_path, **one)
    with np.load(output_path, allow_pickle=False) as saved:
        assert set(saved.files) == set(one)
        for name in one:
            np.testing.assert_array_equal(saved[name], one[name])
    specifications = core.schema()['columns']
    assert set(specifications) == set(one)
    for name, value in one.items():
        assert str(value.dtype) == specifications[name]['dtype'], name
    command = subprocess.run([sys.executable, '-X', 'utf8', str(HERE/'prepare.py')],
                             cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert command.returncode == 2 and '--root-schema-reviewed' in command.stderr
    code_sha = {str((HERE/name).relative_to(ROOT)): data.digest(HERE/name)
                for name in ('core.py', 'data.py', 'prepare.py', 'artificial.py')}
    schema_path = HERE/'入力schema.json'
    assert not schema_path.exists()
    schema_path.write_text(json.dumps(core.schema(), ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    result = dict(全合格=True, 人工原行数=5, 人工旧正常執行対応数=3, 検査種類=cases,
        原seq及び価格気配全件対応=True, 同時計後続を保持=True, 不明量を0補完しない=True,
        価格時計と出来高時計を分離=True, knownとusableを分離=True,
        十段外量の生成=0, 方向約定量の再構成=0,
        混在限月の拒否例外=identity_rejection, 識別欠測の拒否例外=missing_identity_rejection,
        旧正常執行の不一致拒否例外=mismatch_rejection, 接頭及び未来変更一致配列数=equal_count,
        人工一回読取hash=True, 人工pickleなし保存往復=True, CLI無フラグ拒否終了コード=command.returncode,
        コードSHA256=code_sha, 入力schemaSHA256=data.digest(schema_path),
        人工保存SHA256={str(path.relative_to(ROOT)): data.digest(path) for path in (raw_path, output_path)},
        正式全64原本抽出=0, 金融再生=0, 現在API取得=0, 実注文=0)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('人工の原行・二時計・十段・不明量・旧執行対応・未来不変・一回hash・保存往復が一致', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        index = 1
        while (HERE/f'人工抽出不合格_{index:05d}.json').exists():
            index += 1
        failure = dict(全合格=False, 例外型=type(error).__name__, 内容=str(error), 診断=traceback.format_exc(),
            コードSHA256={name: data.digest(HERE/name) for name in ('core.py', 'data.py', 'prepare.py', 'artificial.py')},
            正式全64原本抽出=0, 金融再生=0, 現在API取得=0, 実注文=0)
        (HERE/f'人工抽出不合格_{index:05d}.json').write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding='utf-8')
        raise
