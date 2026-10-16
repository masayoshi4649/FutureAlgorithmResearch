"""全31正式完了の根許可後だけ、96の結果を開く独立レビュー共通処理。"""

import argparse
from datetime import datetime
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
SYMBOLS = ('TOPIX', 'NK225')
AUTHORIZED = False
OLD = ROOT / 'work/wave_v94/review'


def module(name: str, path: Path) -> object:
    """
    機能: mainを呼ばず固有名で既存の読取又は独立検算関数を取り込む。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。旧領域は変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 一定メモリーで資料の内容指紋を求める。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


LEGACY = module('固定94の独立読取を96へ接続', OLD / '共通独立読取.py')
BASE = LEGACY.BASE
clean, totals, equal = BASE.clean, BASE.totals, BASE.equal
clock, parent_map, published_grid, raw_point = LEGACY.clock, LEGACY.parent_map, LEGACY.published_grid, LEGACY.raw_point
partitions = LEGACY.partitions


def read(path: Path) -> object:
    """
    機能: 根許可前には96の正式結果を開かない読取境界を設ける。
    引数: path(Path)。
    返り値: objectは保存内容。未許可の正式結果参照は例外で停止する。
    """
    absolute = path.resolve()
    formal = [WORK / 'front', WORK / 'back', WORK / 'analysis', WORK / '前16参考代表.json']
    if any(absolute == value.resolve() or absolute.is_relative_to(value.resolve()) for value in formal):
        assert AUTHORIZED, '根の全31正式完了通知前は新条件の損益を開きません'
    return BASE.read(path)


def permission() -> None:
    """
    機能: 全31正式段階完了の根許可を受けた実行だけを認める。
    引数: コマンド行の--根許可後(bool)。
    返り値: None。未指定なら正式結果を開く前に終了する。
    """
    global AUTHORIZED
    parser = argparse.ArgumentParser(description='根の全31正式完了許可後だけ独立レビューする')
    parser.add_argument('--根許可後', action='store_true')
    if not parser.parse_args().根許可後:
        raise SystemExit('根の全31正式完了許可が必要です。新正式損益を読みません。')
    AUTHORIZED = True


def save(name: str, value: dict) -> None:
    """
    機能: 自担当の新96reviewへだけ独立証拠を保存する。
    引数: name(str)、value(dict)。
    返り値: None。固定依存・root正式会計・公開成果を変更しない。
    """
    target = HERE / name
    assert target.resolve().is_relative_to(HERE.resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def validate() -> tuple[dict, dict]:
    """
    機能: 固定依存と全18の前後正式結果及び全31集計を確認する。
    引数: なし。permission後だけ呼ぶ。
    返り値: tuple[dict,dict]は固定定義と根集計。
    """
    assert AUTHORIZED
    fixed = read(WORK / '事前固定.json')
    assert len(fixed['条件']) == 18 and len(fixed['全31']) == 31 and fixed['主'] == 'S10_M1_UNL'
    assert fixed['全31既知'] and fixed['新未見確認場数'] == 0
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    for stage in ('front', 'back'):
        assert len(list((WORK / stage / 'results').glob('*.json'))) == 18
        assert len(list((WORK / stage / 'ledgers').glob('*.pkl'))) == 18
    value = read(WORK / 'analysis/比較結果.json')
    assert value['全合格'] and value['primary'] == fixed['主'] and len(value['results']) == 18
    assert value['sessions'] == fixed['全31'] and value['全31既知']
    return fixed, value


def load_ledgers(ident: str) -> dict:
    """
    機能: 完成した前後台帳を指紋確認付きで接続する。
    引数: ident(str)は条件ID。
    返り値: dict[tuple,dict]は全62口座。
    """
    assert AUTHORIZED
    out = {}
    for stage in ('front', 'back'):
        path = WORK / stage / 'ledgers' / f'{ident}.pkl'
        result = read(WORK / stage / 'results' / f'{ident}.json')
        assert result['ledger_SHA256'] == digest(path)
        value = read(path)
        assert not set(out) & set(value)
        out.update(value)
    assert len(out) == 62
    return out


def material() -> dict:
    """
    機能: 独立診断用に価格及び旧板だけを読み、戦略再生は呼ばない。
    引数: なし。
    返り値: dictは全62の正常LP、旧執行、候補素材。
    """
    assert AUTHORIZED
    value = module('96独立レビュー入力読取', WORK / 'data.py')
    return value.load_inputs()


def lp_point(key: tuple, index: int, material: dict, wanted: dict) -> dict:
    """
    機能: 独立LP源を原seqで記録し、執行indexへ変換しない。
    引数: key(tuple[str,str])、index(int)、material/wanted(dict)。
    返り値: dictは原本LP価格点。不正な最良板を執行可能へ救済しない。
    """
    raw = material['raw_last_records'][key]
    assert 0 <= index < len(raw['seq'])
    point = dict(商品=key[1], LP独立index=index, 原本seq=int(raw['seq'][index]),
        時刻=clock(raw['time_s'][index]), LastPrice=float(raw['last'][index]),
        価格有効=bool(raw['valid'][index]), 価格reset=bool(raw['reset'][index]), 源種類='独立LP')
    wanted.setdefault(key, {}).setdefault(point['原本seq'], []).append(point)
    return point


def point(key: tuple, row: int, material: dict, mapped: np.ndarray, wanted: dict) -> dict:
    """
    機能: 判断原板と当時公開済みのLP・旧BBO・OFIを別源で保存する。
    引数: key(tuple[str,str])、row(int)、material(dict)、mapped(ndarray)、wanted(dict)。
    返り値: dictは時計・原seq・方向の具体根拠。事後値を入口へ戻さない。
    """
    record = material['prices'][key]
    out = raw_point(key, record, row, wanted)
    g = int(mapped[row])
    out.update(格子番号=g, 両市場={})
    if g < 0:
        return out
    source = material['trend_prices']['I3'][key[0]]
    out.update(格子時刻=clock(source['grid'][g]), 格子鮮度秒=float(record['time_s'][row] - source['grid'][g]))
    for symbol in SYMBOLS:
        market = source['markets'][symbol]
        old = material['grids'][key[0]]['markets'][symbol]
        current, execution = market['current'], old['current']
        value = dict(LP有効=bool(current['valid'][g]), LP独立index=int(current['index'][g]),
            LP原seq=int(current['raw_seq'][g]), LP時計=clock(current['time_s'][g]) if np.isfinite(current['time_s'][g]) else None,
            LP値=float(current['value'][g]), BBO有効=bool(execution['valid'][g]),
            BBO源index=int(execution['index'][g]), bid=float(execution['bid'][g]), ask=float(execution['ask'][g]))
        for seconds in (15, 300):
            window = market['windows'][seconds]
            value[f'LP{seconds}秒窓'] = dict(有効=bool(window['source_valid'][g]),
                変位bp=float(window['ret_bp'][g]), 候補用旧式変位bp=float(window['ratio_ret_bp'][g]),
                現在源=int(window['now'][g]), 起点源=int(window['old'][g]))
        flow = old['flow'][15]
        value['旧15秒板'] = dict(源有効=bool(flow['source_valid'][g]), 有効=bool(flow['valid'][g]),
            OFI不明=bool(flow['missing_ofi'][g]), OFI非零数=int(flow['nonzero_ofi_count'][g]),
            OFI比=float(flow['ofi_ratio'][g]), bid進行tick=float(flow['bid_change_ticks'][g]),
            ask進行tick=float(flow['ask_change_ticks'][g]))
        if current['index'][g] >= 0:
            value['LP原観測'] = lp_point((key[0], symbol), int(current['index'][g]), material, wanted)
        if execution['index'][g] >= 0:
            value['BBO原観測'] = raw_point((key[0], symbol), material['prices'][key[0], symbol], int(execution['index'][g]), wanted)
        out['両市場'][symbol] = value
    return out


def attach_raw(wanted: dict) -> dict:
    """
    機能: 原本同seqの価格と上位3段板を直接照合し各点へ追記する。
    引数: wanted(dict)は原seq別の診断点。
    返り値: dictは原本別の照合件数とSHA256。LP正常からBBO正常を推定しない。
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
                    assert clock(datetime.fromisoformat(raw['CurrentPriceTime']).timestamp()) == value['時刻']
                    if 'bid' in value:
                        assert float(raw['Buy1']['Price']) == value['bid']
                        assert float(raw['Sell1']['Price']) == value['ask']
                    value['原本板'] = dict(CurrentPriceTime=raw.get('CurrentPriceTime'),
                        買い=[raw[f'Buy{i}'] for i in (1, 2, 3)], 売り=[raw[f'Sell{i}'] for i in (1, 2, 3)],
                        TradingVolume=raw.get('TradingVolume'))
                checked += 1
        assert checked == len(requested), (key, checked, len(requested))
        proofs['|'.join(key)] = dict(同seq照合=checked, SHA256=digest(path))
    return proofs


def provenance() -> dict:
    """
    機能: 固定定義及び根集計と読取部品の指紋を保存する。
    引数: なし。
    返り値: dictは独立レビューの根拠。
    """
    assert AUTHORIZED
    return dict(固定SHA256=digest(WORK / '事前固定.json'), 根集計SHA256=digest(WORK / 'analysis/比較結果.json'),
        共通読取SHA256=digest(Path(__file__)), 旧独立基礎会計SHA256=LEGACY.PREVIOUS_BASE_SHA,
        全31既知=True, API取得=0, 実注文=0, 新戦略再生=0)
