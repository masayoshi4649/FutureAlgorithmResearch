"""保存済みの新旧実注文を、金融再生なしで追跡する。"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = HERE.parent
VALUE = {'TOPIX': 1000., 'NK225': 10.}
FEE = {'TOPIX': 41.8, 'NK225': 11.}
FIVE = ('収支変化', '避けた基準損失', '失った基準利益', '共通入口の出口変化', '新たな入口の収支')


def read(path: Path) -> tuple[object, str]:
    """
    機能: 保存資料を一回読み、同じ bytes の指紋と内容を返す。
    引数: path(Path) は work 内の既存資料。
    返り値: tuple[object,str] は JSON 又は pickle と SHA256。
    """
    assert path.resolve().is_relative_to(ROOT / 'work')
    saved = path.read_bytes()
    value = json.loads(saved.decode('utf-8-sig')) if path.suffix == '.json' else pickle.loads(gzip.decompress(saved))
    return value, hashlib.sha256(saved).hexdigest()


def checked(item: dict, evidence: dict) -> dict:
    """
    機能: 固定された資料を一読し、その参照 SHA と同 bytes を照合する。
    引数: item(dict) は path/SHA256、evidence(dict) は読取済み目録。
    返り値: dict は保存資料。既に読んだ資料の再読を拒否する。
    """
    path = item['path']
    assert path not in evidence, '同一資料の二重読取'
    value, sha = read(ROOT / path)
    assert sha == item['SHA256'], path
    evidence[path] = sha
    return value


def plain(value: object) -> object:
    """
    機能: 診断の数値だけを JSON に保存できる型へ変換する。
    引数: value(object) は ndarray、NumPy scalar 又は通常の構造値。
    返り値: object は JSON 対応値。不正な数値は補完せず明示 None とする。
    """
    if isinstance(value, np.ndarray): return plain(value.tolist())
    if isinstance(value, np.generic): return plain(value.item())
    if isinstance(value, dict): return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [plain(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value): return None
    return value


def write(name: str, value: dict) -> str:
    """
    機能: 新しい診断資料だけを所有域へ保存する。
    引数: name(str) は新資料名、value(dict) は内容。
    返り値: str は保存 SHA256。既存証跡と登録 source を上書きしない。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    saved = (json.dumps(plain(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    path.write_bytes(saved)
    return hashlib.sha256(saved).hexdigest()


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 実注文一つの税込料金を切り捨てで求める。
    引数: quantity(int) は枚数、symbol(str) は商品。
    返り値: int は片道円料金。別 UID の残玉を合算しない。
    """
    return int((Decimal(int(quantity)) * Decimal(str(FEE[symbol]))).to_integral_value(rounding=ROUND_FLOOR))


def clock(account: dict, row: int) -> dict:
    """
    機能: 当時 normal 行を保存価格時計、原 seq、原行位置へ結ぶ。
    引数: account(dict) は保存入力、row(int) は normal 行番号。
    返り値: dict は系譜。JST は価格代理時計であり受信時計ではない。
    """
    q = account['quotes']; stamp = float(q['time_s'][row])
    assert q['seq'][row] == account['record']['seq'][row]
    result = dict(normal_row=int(row), raw_seq=int(q['seq'][row]), price_time_s=stamp,
                  価格代理時計JST=datetime.fromtimestamp(stamp, timezone(timedelta(hours=9))).isoformat(),
                  bid=float(q['bid'][row]), ask=float(q['ask'][row]), 正常気配=bool(q['quote_valid'][row]))
    if 'mapping' in account: result['raw_row'] = int(account['mapping'][row])
    return result


def expand(value: object, count: int) -> np.ndarray:
    """
    機能: 保存 plateau を前方保持して元 normal 行へ復元する。
    引数: value(object) は ndarray 又は圧縮辞書、count(int) は行数。
    返り値: ndarray は保存値。価格や判断を再計算しない。
    """
    if isinstance(value, np.ndarray):
        assert len(value) == count
        return value
    assert value['length'] == count and value['rows'][0] == 0
    return value['values'][np.searchsorted(value['rows'], np.arange(count), side='right') - 1]


def parents(ledger: dict) -> dict:
    """
    機能: 実親を紙上 cid で整理し、収支の全額一致を確認する。
    引数: ledger(dict) は保存実台帳。
    返り値: dict[int,dict] は決済済み実親。影親を勝敗へ混ぜない。
    """
    result = {int(p['親']): p for p in ledger['parent']}
    assert len(result) == len(ledger['parent'])
    assert np.isclose(sum(p['収支'] for p in result.values()), ledger['summary']['収支'], atol=1e-5, rtol=0.)
    return result


def contribution(before: dict, after: dict) -> dict:
    """
    機能: 同じ紙上 cid で旧親消失、新親参加、共通親出口差を独立に分解する。
    引数: before/after(dict) は同枚数同出口の保存台帳。
    返り値: dict は五寄与及び対象 cid 集合。
    """
    a, b = parents(before), parents(after)
    removed, added, common = a.keys() - b.keys(), b.keys() - a.keys(), a.keys() & b.keys()
    result = dict(収支変化=after['summary']['収支'] - before['summary']['収支'],
        避けた基準損失=sum(-a[k]['収支'] for k in removed if a[k]['収支'] < 0),
        失った基準利益=sum(a[k]['収支'] for k in removed if a[k]['収支'] > 0),
        共通入口の出口変化=sum(b[k]['収支'] - a[k]['収支'] for k in common),
        新たな入口の収支=sum(b[k]['収支'] for k in added),
        消えた親=sorted(removed), 新たな親=sorted(added), 共通親=sorted(common))
    assert np.isclose(result['収支変化'], result['避けた基準損失'] - result['失った基準利益'] +
        result['共通入口の出口変化'] + result['新たな入口の収支'], atol=1e-5, rtol=0.)
    return result
