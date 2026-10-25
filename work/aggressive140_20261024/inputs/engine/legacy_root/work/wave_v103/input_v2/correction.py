"""v1保存npzのみから、前価格clock逆行を除外した二配列のv2を別保存する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import traceback

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V1 = HERE.parent/'input'
CHANGED = ('volume_delta_usable', 'volume_delta')
SOURCE_NAMES = ('data.py', 'correction.py', 'artificial.py')


def module(name: str, path: Path) -> object:
    """
    機能: v2の読取部品だけを固有名で接続する。
    引数: name(str)、path(Path)は名前と位置。
    返り値: objectは読取モジュール。v1 sourceや通常名を変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


DATA = module('v2訂正入力の読取103', HERE/'data.py')


def read(path: Path) -> dict:
    """
    機能: 既保存の入力仕様、由来又はFalse証跡を読む。
    引数: path(Path)はJSONの位置。
    返り値: dictは内容。金融結果及び生原本は読まない。
    """
    assert path.resolve().is_relative_to(HERE.parent.resolve())
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 新v2領域へだけ資料を新規保存する。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。v1及び完成v2の上書きを拒絶する。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def correct_arrays(original: dict) -> tuple[dict, dict]:
    """
    機能: 直前価格clock逆行bit8だけをusableから除き、支持用差をNaNへ訂正する。
    引数: original(dict[str,ndarray])はv1の44配列。
    返り値: tuple[dict,dict]は訂正配列と差分件数。他42配列の型、形状及び値は完全同一。
    """
    assert len(original) == 44 and set(CHANGED) <= set(original)
    n = len(original['raw_seq'])
    usable = original['volume_delta_usable']
    observed = original['volume_delta_observed']
    old_delta = original['volume_delta']
    reason = original['price_reset_reason']
    assert usable.dtype == np.bool_ and usable.shape == (n,)
    assert observed.dtype == old_delta.dtype == np.float64 and observed.shape == old_delta.shape == (n,)
    assert reason.dtype == np.uint16 and reason.shape == (n,)
    assert np.isfinite(observed[usable]).all() and (observed[usable] >= 0).all()
    np.testing.assert_array_equal(old_delta, np.where(usable, observed, np.nan))
    # ----------------------------------------
    # 現在行のv1資格を保持し、直前行だけの既知clock逆行を追加で除外する。
    previous_reverse = np.zeros(n, bool)
    if n > 1:
        previous_reverse[1:] = (reason[:-1] & 8) != 0
    revised_usable = usable & ~previous_reverse
    revised_delta = np.where(revised_usable, observed, np.nan)
    result = dict(original, volume_delta_usable=revised_usable, volume_delta=revised_delta)
    unchanged = [name for name in original if name not in CHANGED]
    assert len(unchanged) == 42
    for name in unchanged:
        assert result[name].dtype == original[name].dtype and result[name].shape == original[name].shape
        np.testing.assert_array_equal(result[name], original[name])
    delta_changed = (old_delta != revised_delta) & ~(np.isnan(old_delta) & np.isnan(revised_delta))
    return result, dict(全合格=True, 不変配列数=42, 変更可能列=list(CHANGED),
        直前価格clock逆行行数=int(previous_reverse.sum()),
        usable変更行数=int(np.sum(usable != revised_usable)), 支持用差変更行数=int(delta_changed.sum()),
        volume_known不変=True, 生観測値不変=True, 原行順及び旧執行map不変=True)


def schema() -> dict:
    """
    機能: 44列を維持したv2の訂正規則及び原本対応の委譲範囲を明示する。
    引数: なし。
    返り値: dictはv2 schema。v1の未訂正usableを合格根拠として継承しない。
    """
    value = deepcopy(read(V1/'入力schema.json'))
    value['version'] = 2
    value['volume_delta_usable'] += ' さらに直前price_reset_reasonの価格clock逆行bit8が0であることを要求。'
    value['訂正'] = dict(元='input/v1の価格時計逆行後usableの反例.json',
        変更列=list(CHANGED), 不変列数=42,
        明示式='usable_v2 = usable_v1 & ~previous(price_reset_reason & 8 != 0); delta_v2 = where(usable_v2, volume_delta_observed, NaN)',
        raw再読取=0, 原本対応の委譲='v1の一回原本hash、全原行保存及び旧正常seq/time/LP/bid/ask全件一致へ委譲。',
        継承しない主張='v1 usableの数理定義が正しいという主張。False反例を保持し別訂正する。')
    return value


def sources() -> dict:
    """
    機能: v2訂正の小さい直接sourceとv1由来資料だけを指紋化する。
    引数: なし。
    返り値: dict[str,str]は指紋。生原本の追加hashは0。
    """
    paths = [HERE/name for name in SOURCE_NAMES]
    paths += [V1/name for name in ('core.py', 'data.py', 'prepare.py', 'artificial.py', '入力schema.json',
        '原本抽出前の32場登録.json', 'metadata.json', 'v1の価格時計逆行後usableの反例.json')]
    return {str(path.relative_to(ROOT)): DATA.digest(path) for path in paths}


def one_account(item: dict) -> tuple[str, dict]:
    """
    機能: 保存v1npzを一回読み、二列訂正を別v2npzへ保存して42不変列を検算する。
    引数: item(dict)はv1の完成口座診断。
    返り値: tuple[str,dict]は口座キーと訂正の由来・新出力指紋。
    """
    source_path = ROOT/item['出力位置']
    assert source_path.resolve().is_relative_to(V1.resolve())
    payload = source_path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == item['出力SHA256']
    with np.load(io.BytesIO(payload), allow_pickle=False) as saved:
        original = {name: saved[name] for name in saved.files}
    corrected, diagnostics = correct_arrays(original)
    target = HERE/'raw'/item['symbol']/(item['session']+'.npz')
    assert target.resolve().is_relative_to(HERE.resolve()) and not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(target, **corrected)
    result = deepcopy(item)
    result.update(v1出力位置=item['出力位置'], v1出力SHA256=item['出力SHA256'],
                  出力位置=str(target.relative_to(ROOT)), 出力SHA256=DATA.digest(target), 訂正=diagnostics)
    result['qualifications']['volume_delta_usable'] = int(corrected['volume_delta_usable'].sum())
    return item['session']+'|'+item['symbol'], result


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 訂正派生からの外部通信を拒絶する。
    引数: args(tuple)、kwargs(dict)は呼出し引数。
    返り値: None。常にRuntimeErrorを送出する。
    """
    raise RuntimeError('v2派生はv1保存npzだけを読み、原本、API及び注文へ接続しません')


def formal(workers: int) -> None:
    """
    機能: 根の別指示後に64口座を派生し、v1保持とv2訂正の由来を保存する。
    引数: workers(int)は1又は2の並列派生数。
    返り値: None。生原本及び既存金融結果は読まない。
    """
    assert workers in (1, 2)
    assert not (HERE/'metadata.json').exists() and not list((HERE/'raw').rglob('*.npz'))
    proof_path = HERE/'前価格時計逆行の二列訂正と人工未来不変.json'
    proof = read(proof_path)
    assert proof['全合格'] and proof['正式全64派生'] == proof['原本再読取'] == proof['金融再生'] == 0
    for name, wanted in proof['コードSHA256'].items():
        assert DATA.digest(ROOT/name) == wanted, name
    false = read(V1/'v1の価格時計逆行後usableの反例.json')
    assert false['全合格'] is False and false['反例を再現できた'] is True
    original = read(V1/'metadata.json')
    assert original['全合格'] and original['口座数'] == original['正式全64原本抽出'] == 64
    before = sources()
    schema_path = HERE/'入力schema.json'
    assert read(schema_path) == schema()
    save(HERE/'v2派生前の由来固定.json', dict(全合格=True, sessions=original['sessions'],
        対象場数=32, 口座数=64, 原本再読取=0, 変更列=list(CHANGED), 不変列数=42,
        v1_falseを保持=True, 小直接依存SHA256=before,
        v1全口座出力SHA256={item['出力位置']: item['出力SHA256'] for item in original['accounts'].values()},
        人工検査SHA256=DATA.digest(proof_path), v2schemaSHA256=DATA.digest(schema_path),
        正式全64派生=0, 金融再生=0, 現在API取得=0, 実注文=0))
    accounts = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(one_account, item) for item in original['accounts'].values()]
        for future in as_completed(futures):
            key, item = future.result()
            accounts[key] = item
            print(key+f" v2二列訂正/42列同一・変更{item['訂正']['usable変更行数']}行", flush=True)
    assert len(accounts) == 64 and set(accounts) == set(original['accounts'])
    assert sources() == before, 'v1又は訂正sourceが派生中に変わりました'
    output = dict(全合格=True, sessions=original['sessions'], 対象場数=32, 口座数=64,
        正式全64派生=64, schema=schema(), accounts=dict(sorted(accounts.items())),
        訂正合計=dict(usable変更行数=sum(item['訂正']['usable変更行数'] for item in accounts.values()),
                     支持用差変更行数=sum(item['訂正']['支持用差変更行数'] for item in accounts.values()),
                     不変配列数毎口座=42),
        小直接依存SHA256=before, 人工検査SHA256=DATA.digest(proof_path), v2schemaSHA256=DATA.digest(schema_path),
        派生前固定SHA256=DATA.digest(HERE/'v2派生前の由来固定.json'),
        v1保持=True, v1の数理不合格を隠さない=True,
        原本対応の委譲='v1のraw SHA、全原行及び旧正常5列一致を使用。原観測値及び42配列を変更しない。',
        原本再読取=0, 金融再生=0, 現在API取得=0, 実注文=0)
    save(HERE/'metadata.json', output)
    DATA.load_account(original['sessions'][0], 'TOPIX')
    print('全64v2の二列訂正と42列同一を保存。v1保持、生原本再読取と金融再生は0', flush=True)


def main() -> None:
    """
    機能: 根の訂正レビュー後の明示指示がある場合だけ正式64派生を許可する。
    引数: CLI --root-v2-reviewed(bool)、--workers(int)。
    返り値: None。無フラグは資料読取前に拒否する。
    """
    parser = argparse.ArgumentParser(description='v1保存npzから二列だけを訂正する')
    parser.add_argument('--root-v2-reviewed', action='store_true', required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    formal(args.workers)


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        index = 1
        while (HERE/f'v2派生不合格_{index:05d}.json').exists():
            index += 1
        save(HERE/f'v2派生不合格_{index:05d}.json', dict(全合格=False, 例外型=type(error).__name__,
            内容=str(error), 診断=traceback.format_exc(), source_SHA256=DATA.digest(Path(__file__)),
            原本再読取=0, 金融再生=0, 現在API取得=0, 実注文=0))
        raise
