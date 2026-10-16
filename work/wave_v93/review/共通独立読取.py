"""正式完了の根許可後だけ結果を開く、独立会計レビューの共通読取。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
JST = timezone(timedelta(hours=9))
OLD_REVIEW = ROOT / 'work/wave_v92/review/全場親会計と入口再参加の経路分解.py'
OLD_SHA256 = '034d994de37d2f506a7cf0d830d9690fe89da32485e6ea19d657cbded7ce1f0d'


def module(name: str, path: Path) -> object:
    """
    機能: 売買再生を伴わない読取モジュールを固有名で接続する。
    引数: name (str)、path (Path)。
    返り値: object は読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 参照資料の内容をバイト単位で識別する。
    引数: path (Path)。
    返り値: str はSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


assert digest(OLD_REVIEW) == OLD_SHA256
BASE = module('固定親会計の独立読取92から93', OLD_REVIEW)
read, clean, totals, equal = BASE.read, BASE.clean, BASE.totals, BASE.equal


def permission() -> None:
    """
    機能: 根から全正式段階完了通知を受けた後の明示引数を必須にする。
    引数: コマンド行の --根許可後 (bool)。
    返り値: None。未指定なら結果を開く前に停止する。
    """
    parser = argparse.ArgumentParser(description='全正式段階完了の根許可後だけ独立レビューする')
    parser.add_argument('--根許可後', action='store_true')
    args = parser.parse_args()
    if not args.根許可後:
        raise SystemExit('正式前後完了の根許可が必要です。新正式損益を読み取りません。')


def save(name: str, value: dict) -> None:
    """
    機能: 所有する新93のreviewだけへ独立証拠を保存する。
    引数: name (str)、value (dict)。
    返り値: None。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE.resolve())
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def validate() -> tuple[dict, dict]:
    """
    機能: 固定依存を検証し、全16の前後正式結果と根集計の存在を確認する。
    引数: なし。permissionの後でだけ呼び出す。
    返り値: tuple[dict,dict] は固定定義と根集計。
    """
    fixed = read(WORK / '事前固定.json')
    assert len(fixed['条件']) == 16 and len(fixed['全31']) == 31 and fixed['主'] == 'C11'
    assert fixed['全31既知'] and fixed['新しい未見確認場数'] == 0
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    for stage in ('front', 'back'):
        assert len(list((WORK / stage / 'results').glob('*.json'))) == 16
        assert len(list((WORK / stage / 'ledgers').glob('*.pkl'))) == 16
    assembled = read(WORK / 'analysis/比較結果.json')
    assert assembled['primary'] == fixed['主'] and len(assembled['results']) == 16
    return fixed, assembled


def load_ledgers(ident: str) -> dict:
    """
    機能: 保存された前後台帳を排他的に接続し、各段階の指紋を確認する。
    引数: ident (str) は固定条件ID。
    返り値: dict[tuple,dict] は全62口座。
    """
    output = {}
    for stage in ('front', 'back'):
        path = WORK / stage / 'ledgers' / f'{ident}.pkl'
        result = read(WORK / stage / 'results' / f'{ident}.json')
        assert result['ledger_SHA256'] == digest(path)
        value = read(path)
        assert not set(output) & set(value)
        output.update(value)
    assert len(output) == 62
    return output


def clock(stamp: float) -> str:
    """
    機能: 保存された代理時計を日本時間へ変換する。
    引数: stamp (float) はUnix秒。
    返り値: str は秒までのISO時刻。
    """
    return datetime.fromtimestamp(float(stamp), JST).isoformat(timespec='seconds')


def state_at(ledger: dict, row: int, kind: str = 'range') -> dict:
    """
    機能: 疎形式の保存状態を指定行までで復元する。
    引数: ledger (dict)、row (int)、kind (str、range又はrisk)。
    返り値: dict[str,float] は当時の診断状態。真の正答根拠とは扱わない。
    """
    changes = ledger[f'{kind}_state_changes']
    index = int(np.searchsorted(changes[:, 0], row, side='right') - 1)
    assert index >= 0
    return {name: float(changes[index, i + 1]) for i, name in enumerate(ledger[f'{kind}_state_columns'])}


def parent_map(ledger: dict, source: int | None = None) -> dict:
    """
    機能: 源・新規判断行・方向の同じ親を一対一対応する。
    引数: ledger (dict)、source (int | None) は任意の源制限。
    返り値: dict[tuple,ndarray] は口座内同一判断キーから親への写像。
    """
    output = {}
    for trade in ledger['trades']:
        if source is not None and int(trade[1]) != source:
            continue
        key = int(trade[1]), int(trade[15]), int(trade[4])
        assert key not in output, key
        output[key] = trade
    return output


def provenance() -> dict:
    """
    機能: 凍結条件と正式集計及び独立基礎会計の参照指紋を記録する。
    引数: なし。
    返り値: dict は追跡可能な証拠指紋。
    """
    return {'固定SHA256': digest(WORK / '事前固定.json'),
            '根集計SHA256': digest(WORK / 'analysis/比較結果.json'),
            '独立基礎会計SHA256': OLD_SHA256, '共通読取SHA256': digest(Path(__file__)),
            'API取得': 0, '実注文': 0, '新売買再生': 0, '全31既知探索': True}


def published_grid(record: dict, grid: np.ndarray) -> np.ndarray:
    """
    機能: 厳密過去格子を次の自己原板へ公開した時点だけから最新格子を復元する。
    引数: record (dict)、grid (ndarray[float])。
    返り値: ndarray[int] は各原板行の公開済み最新格子。
    """
    output = np.full(len(record['time_s']), -1, dtype=np.int32)
    for g, row in enumerate(np.searchsorted(record['time_s'], grid, side='left')):
        if row < len(output) and record['time_s'][row] - grid[g] <= 10.:
            output[row] = g
    return np.maximum.accumulate(output)


def raw_point(key: tuple, record: dict, row: int, wanted: dict) -> dict:
    """
    機能: 原板価格を記録し、原本同seq照合の対象へ登録する。
    引数: key (tuple[str,str])、record (dict)、row (int)、wanted (dict)。
    返り値: dict は代理時計・価格・気配・源行。
    """
    row = int(row)
    value = {'商品': key[1], '行': row, '原本seq': int(record['seq'][row]),
             '時刻': clock(record['time_s'][row]), 'LastPrice': float(record['price'][row]),
             'bid': float(record['bid'][row]), 'ask': float(record['ask'][row]),
             'mid': float((record['bid'][row] + record['ask'][row]) / 2),
             'spread_pt': float(record['ask'][row] - record['bid'][row]),
             '価格有効': bool(record['price_valid'][row]), '気配有効': bool(record['quote_valid'][row])}
    wanted.setdefault(key, {}).setdefault(value['原本seq'], []).append(value)
    return value


def point(key: tuple, row: int, material: dict, mapped: np.ndarray, wanted: dict) -> dict:
    """
    機能: 当時の自己原板と、その時までに公開済みの両市場格子を記録する。
    引数: key (tuple)、row (int)、material (dict)、mapped (ndarray)、wanted (dict)。
    返り値: dict は売買判断へ逆流させない原板診断。
    """
    record, session = material['prices'][key], material['grids'][key[0]]
    value = raw_point(key, record, row, wanted)
    g = int(mapped[row])
    value['格子番号'] = g
    if g < 0:
        return value
    value['格子時刻'] = clock(session['grid'][g])
    value['格子鮮度秒'] = float(record['time_s'][row] - session['grid'][g])
    value['両市場'] = {}
    for symbol in SYMBOLS:
        market = session['markets'][symbol]
        source = int(market['current']['index'][g])
        item = {'源行': source, '有効': bool(market['current']['valid'][g]),
                'mid': float(market['current']['mid'][g]),
                'ER300': float(market['windows'][300]['efficiency'][g]),
                'ret300bp': float(market['windows'][300]['ret_bp'][g]),
                'ret30bp': float(market['windows'][30]['ret_bp'][g])}
        if source >= 0:
            item['原板'] = raw_point((key[0], symbol), material['prices'][key[0], symbol], source, wanted)
        value['両市場'][symbol] = item
    return value


def attach_raw(wanted: dict) -> dict:
    """
    機能: 読取専用の原本JSONLで同seqの価格と上位3段板を直接照合する。
    引数: wanted (dict) は照合対象の価格点。
    返り値: dict は原本ファイル別の同seq件数と指紋。
    """
    proofs = {}
    for key, requested in wanted.items():
        path = ROOT / 'book' / key[1] / f'{key[0]}.jsonl'
        checked = 0
        with path.open('rb') as stream:
            for seq, line in enumerate(stream):
                if seq not in requested:
                    continue
                raw = json.loads(line)
                for value in requested[seq]:
                    assert float(raw['CurrentPrice']) == value['LastPrice']
                    assert float(raw['Buy1']['Price']) == value['bid']
                    assert float(raw['Sell1']['Price']) == value['ask']
                    value['原本板'] = {'CurrentPriceTime': raw['CurrentPriceTime'],
                                      '買い': [raw[f'Buy{i}'] for i in (1, 2, 3)],
                                      '売り': [raw[f'Sell{i}'] for i in (1, 2, 3)],
                                      'TradingVolume': raw.get('TradingVolume')}
                checked += 1
        assert checked == len(requested)
        proofs['|'.join(key)] = {'同seq板': checked, 'SHA256': digest(path)}
    return proofs
