"""全正式段階の根許可後だけ、53条件の結果を読む独立レビュー共通処理。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX','NK225')
PREVIOUS = ROOT/'work/wave_v93/review/共通独立読取.py'
PREVIOUS_BASE = ROOT/'work/wave_v92/review/全場親会計と入口再参加の経路分解.py'
PREVIOUS_BASE_SHA = '034d994de37d2f506a7cf0d830d9690fe89da32485e6ea19d657cbded7ce1f0d'


def module(name: str, path: Path) -> object:
    """
    機能: 読取関数だけを固有名へ接続し、売買又はmainは呼ばない。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name,path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 資料の内容指紋を一定メモリーで求める。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):
            value.update(block)
    return value.hexdigest()


assert digest(PREVIOUS_BASE) == PREVIOUS_BASE_SHA
LEGACY = module('独立親会計93の読取94',PREVIOUS)
BASE = LEGACY.BASE
read,clean,totals,equal = BASE.read,BASE.clean,BASE.totals,BASE.equal
clock,parent_map,published_grid,raw_point,attach_raw = (LEGACY.clock,LEGACY.parent_map,
    LEGACY.published_grid,LEGACY.raw_point,LEGACY.attach_raw)


def permission() -> None:
    """
    機能: 根の全31正式結果完了許可を受けた実行だけを認める。
    引数: コマンド行の--根許可後(bool)。
    返り値: None。未指定なら新正式損益を開く前に停止する。
    """
    parser = argparse.ArgumentParser(description='全正式結果完了の根許可後だけ独立レビューする')
    parser.add_argument('--根許可後',action='store_true')
    if not parser.parse_args().根許可後:
        raise SystemExit('根の全正式完了許可が必要です。新正式損益を読みません。')


def save(name: str, value: dict) -> None:
    """
    機能: 自担当の新94reviewへだけ独立証拠を保存する。
    引数: name(str)、value(dict)。
    返り値: None。凍結資料又は正式会計を書き替えない。
    """
    path = HERE/name
    assert path.resolve().is_relative_to(HERE.resolve())
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def validate() -> tuple[dict,dict]:
    """
    機能: 凍結依存と53条件の前後正式結果及び全31集計を確認する。
    引数: なし。permission後だけ呼び出す。
    返り値: tuple[dict,dict]は固定定義及び根集計。
    """
    fixed = read(WORK/'事前固定.json')
    assert len(fixed['条件']) == 53 and len(fixed['全31']) == 31
    assert fixed['主'] == 'I3_G1_S0_T1' and fixed['全31既知'] and fixed['新しい未見確認場数'] == 0
    for relative,expected in fixed['SHA256'].items():
        assert digest(ROOT/relative) == expected,relative
    for stage in ('front','back'):
        assert len(list((WORK/stage/'results').glob('*.json'))) == 53
        assert len(list((WORK/stage/'ledgers').glob('*.pkl'))) == 53
    assembled = read(WORK/'analysis/比較結果.json')
    assert assembled['全合格'] and assembled['primary'] == fixed['主'] and len(assembled['results']) == 53
    assert assembled['sessions'] == fixed['全31'] and assembled['全31既知']
    return fixed,assembled


def load_ledgers(ident: str) -> dict:
    """
    機能: 完成した前後台帳を指紋確認付きで接続する。
    引数: ident(str)は固定条件ID。
    返り値: dict[tuple,dict]は全62口座。
    """
    value = {}
    for stage in ('front','back'):
        path = WORK/stage/'ledgers'/f'{ident}.pkl'
        result = read(WORK/stage/'results'/f'{ident}.json')
        assert result['ledger_SHA256'] == digest(path)
        loaded = read(path)
        assert not set(value)&set(loaded)
        value.update(loaded)
    assert len(value) == 62
    return value


def state_at(ledger: dict, row: int, kind: str='range') -> dict:
    """
    機能: range/risk/price_sourceの疎状態を指定行までで復元する。
    引数: ledger(dict)、row(int)、kind(str)。
    返り値: dict[str,float]は当時状態。
    """
    prefix = {'range':'range_state','risk':'risk_state','price':'price_source'}[kind]
    changes = ledger[prefix+'_changes']
    index = int(np.searchsorted(changes[:,0],row,side='right')-1)
    assert index >= 0
    return {name:float(changes[index,i+1]) for i,name in enumerate(ledger[prefix+'_columns'])}


def partitions(sessions: list[str]) -> dict[str,list[str]]:
    """
    機能: 固定31場を既存の8期間へ分ける。
    引数: sessions(list[str])。
    返り値: dict[str,list[str]]は期間別場名。
    """
    return dict(全31=sessions,前16=sessions[:16],後15=sessions[16:],旧30=sessions[:-1],
                後14=sessions[16:-1],追加1=sessions[-1:],デイ=[s for s in sessions if s.endswith('_Day')],
                ナイト=[s for s in sessions if s.endswith('_Night')])


def point(key: tuple[str,str], row: int, material: dict, mapped: np.ndarray, wanted: dict, lane: str='I0') -> dict:
    """
    機能: 当時BBOと価格laneの別源・窓・時刻を原板診断として保存する。
    引数: key(tuple[str,str])、row(int)、material(dict)、mapped(ndarray)、wanted(dict)、lane(str)。
    返り値: dict。原本LP系列のindexを執行板indexへ代入しない。
    """
    record = material['prices'][key]
    value = raw_point(key,record,row,wanted)
    grid = material['grids'][key[0]]['grid']
    g = int(mapped[row])
    value.update(格子番号=g,価格lane=lane)
    if g < 0:
        return value
    value.update(格子時刻=clock(grid[g]),格子鮮度秒=float(record['time_s'][row]-grid[g]),両市場={})
    for symbol in SYMBOLS:
        market = material['price_lanes'][lane][key[0]]['markets'][symbol]
        execution = material['grids'][key[0]]['markets'][symbol]['current']
        current = market['current']
        source = int(execution['index'][g])
        item = dict(価格源index=int(current['index'][g]),価格原本seq=int(current['raw_seq'][g]),
                    価格源時計=clock(current['time_s'][g]) if np.isfinite(current['time_s'][g]) else None,
                    価格有効=bool(current['valid'][g]),価格値=float(current.get('value',current.get('mid'))[g]),
                    執行源index=source,執行有効=bool(execution['valid'][g]),
                    ER300=float(market['windows'][300]['efficiency'][g]),
                    TV300=float(market['windows'][300]['total_variation'][g]),
                    ret300bp=float(market['windows'][300]['ret_bp'][g]),ret30bp=float(market['windows'][30]['ret_bp'][g]),
                    範囲180源有効=bool(market['ranges'][180]['source_valid'][g]),
                    範囲180位置有効=bool(market['ranges'][180]['position_valid'][g]),
                    範囲180low=float(market['ranges'][180]['low'][g]),範囲180high=float(market['ranges'][180]['high'][g]))
        if source >= 0:
            item['執行原板'] = raw_point((key[0],symbol),material['prices'][key[0],symbol],source,wanted)
        value['両市場'][symbol] = item
    return value


def provenance() -> dict:
    """
    機能: 正式条件及び根集計と独立基礎会計の指紋を記録する。
    引数: なし。
    返り値: dictは追跡用指紋と禁止した実行の件数。
    """
    return dict(固定SHA256=digest(WORK/'事前固定.json'),根集計SHA256=digest(WORK/'analysis/比較結果.json'),
                独立基礎会計SHA256=PREVIOUS_BASE_SHA,共通読取SHA256=digest(Path(__file__)),
                全31既知探索=True,API取得=0,実注文=0,新売買再生=0)
