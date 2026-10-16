"""赤字上位場の局所回復・中心再参加と実際の保存板を具体時刻で説明する。"""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
JST = timezone(timedelta(hours=9))
SYMBOLS = ('TOPIX', 'NK225')


def module(name: str, path: Path) -> object:
    """
    機能: 独立会計と読取入力を固有名で接続する。
    引数: name(str)、path(Path)。
    返り値: object。実行しない読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    output = importlib.util.module_from_spec(spec)
    sys.modules[name] = output
    spec.loader.exec_module(output)
    return output


REVIEW = module('入口再参加独立会計92', HERE/'全場親会計と入口再参加の経路分解.py')


def clock(stamp: float) -> str:
    """
    機能: 保存された代理時計を日本時間で示す。
    引数: stamp(float、Unix秒)。
    返り値: str。年月日と秒。
    """
    return datetime.fromtimestamp(float(stamp), JST).isoformat(timespec='seconds')


def mapping(record: dict, grid: np.ndarray) -> np.ndarray:
    """
    機能: 格子の公開を当該市場の次原板へ対応させる。
    引数: record(dict)、grid(ndarray)。
    返り値: ndarray[int32]。最新の公開済み格子番号。
    """
    result = np.full(len(record['time_s']), -1, dtype=np.int32)
    for g, row in enumerate(np.searchsorted(record['time_s'], grid, side='left')):
        if row < len(result) and record['time_s'][row]-grid[g] <= 10.:
            result[row] = g
    return np.maximum.accumulate(result)


def state_at(ledger: dict, row: int) -> dict:
    """
    機能: 変更行形式の診断状態をその時点までで復元する。
    引数: ledger(dict)、row(int)。
    返り値: dict。売買の正答根拠に使わない説明用状態。
    """
    changes = ledger['range_state_changes']
    index = int(np.searchsorted(changes[:, 0], row, side='right')-1)
    assert index >= 0
    return {name: float(changes[index, i+1]) for i, name in enumerate(ledger['range_state_columns'])}


def raw_point(key: tuple, record: dict, row: int, wanted: dict) -> dict:
    """
    機能: 原板の価格・実気配差と源行を記録し、原本板の照合対象へ加える。
    引数: key(tuple)、record(dict)、row(int)、wanted(dict)。
    返り値: dict。実観測の価格点。
    """
    row = int(row)
    result = dict(商品=key[1], 行=row, 原本seq=int(record['seq'][row]),
        時刻=clock(record['time_s'][row]), LastPrice=float(record['price'][row]),
        bid=float(record['bid'][row]), ask=float(record['ask'][row]),
        mid=float((record['bid'][row]+record['ask'][row])/2),
        spread_pt=float(record['ask'][row]-record['bid'][row]),
        spread_呼値=float((record['ask'][row]-record['bid'][row])/record['tick']),
        価格有効=bool(record['price_valid'][row]), 気配有効=bool(record['quote_valid'][row]))
    wanted.setdefault(key, {}).setdefault(result['原本seq'], []).append(result)
    return result


def point(key: tuple, row: int, material: dict, mapped: np.ndarray, wanted: dict) -> dict:
    """
    機能: 自己原板時刻で実際に公開済みの両市場情報を表示する。
    引数: key(tuple)、row(int)、material(dict)、mapped(ndarray)、wanted(dict)。
    返り値: dict。原板と公開済み格子・相手価格。
    """
    record, session = material['prices'][key], material['grids'][key[0]]
    result = raw_point(key, record, row, wanted)
    g = int(mapped[row])
    result['格子番号'] = g
    if g < 0:
        return result
    result['格子時刻'] = clock(session['grid'][g])
    result['格子鮮度秒'] = float(record['time_s'][row]-session['grid'][g])
    result['両市場'] = {}
    for symbol in SYMBOLS:
        market = session['markets'][symbol]
        source = int(market['current']['index'][g])
        entry = dict(源行=source, 有効=bool(market['current']['valid'][g]),
            mid=float(market['current']['mid'][g]),
            ER300=float(market['windows'][300]['efficiency'][g]),
            ret300bp=float(market['windows'][300]['ret_bp'][g]),
            ret30bp=float(market['windows'][30]['ret_bp'][g]))
        if source >= 0:
            entry['原板'] = raw_point((key[0], symbol), material['prices'][key[0], symbol], source, wanted)
        result['両市場'][symbol] = entry
    return result


def diagnose(ident: str, result: dict, ledgers: dict, material: dict, wanted: dict,
             controls: dict) -> dict:
    """
    機能: 商品別赤字上位3場と各場の大きな損失親3つを具体的に診断する。
    引数: ident(str)、result/ledgers/material/wanted/controls(dict)。
    返り値: dict。事後診断専用の時刻・中心・極値・気配。
    """
    output = {}
    config = result['config']
    for symbol in SYMBOLS:
        losing = sorted((r for r in result['rows'] if r['symbol'] == symbol and r['net'] < 0),
                        key=lambda r: (r['net'], r['session']))[:3]
        output[symbol] = []
        for summary in losing:
            key = summary['session'], symbol
            record, ledger = material['prices'][key], ledgers[key]
            mapped = mapping(record, material['grids'][key[0]]['grid'])
            parents, details = [], []
            for parent in ledger['trades']:
                parents.append(dict(親=int(parent[0]), 源='J2' if parent[1] == 0 else 'O06',
                    方向='買い' if parent[4] == 1 else '売り', 枚数=int(parent[5]),
                    新規時刻=clock(record['time_s'][int(parent[2])]),
                    返済時刻=clock(record['time_s'][int(parent[3])]),
                    新規価格=float(parent[6]), 返済価格=float(parent[7]), 収支円=float(parent[11]),
                    返済理由=ledger['reasons'][int(parent[13])]))
            for parent in sorted(ledger['trades'], key=lambda t: float(t[11]))[:3]:
                if parent[11] >= 0:
                    continue
                entry, exit_row, decision = int(parent[2]), int(parent[3]), int(parent[15])
                side, source = int(parent[4]), int(parent[1])
                orders = ledger['orders'][(ledger['orders'][:, 2] == parent[0]) & (ledger['orders'][:, 3] == source)]
                assert len(orders) == 2
                state = state_at(ledger, decision)
                events = ledger['events']
                same_cycle = events[(events[:, 2] == 1) & (events[:, 10] == parent[14]) & (events[:, 0] <= decision)]
                timeline = []
                for code in (10, 12, 16, 17, 22, 23, 24, 25, 26):
                    chosen = same_cycle[same_cycle[:, 3] == code]
                    for event in chosen[-1:]:
                        timeline.append(dict(種類=ledger['event_codes'][code],
                            原板=point(key, int(event[0]), material, mapped, wanted),
                            当時基準=float(event[7]), 詳細=float(event[11])))
                recovery = {}
                if source == 1 and config['range_entry_kind'] == 'recovery_market':
                    own_name = 'own_low' if side == 1 else 'own_high'
                    peer_name = 'peer_low' if side == 1 else 'peer_high'
                    extreme_row, peer_row = int(state[own_name+'_row']), int(state[peer_name+'_source'])
                    own_extreme = raw_point(key, record, extreme_row, wanted)
                    peer_symbol = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
                    peer_record = material['prices'][key[0], peer_symbol]
                    peer_extreme = raw_point((key[0], peer_symbol), peer_record, peer_row, wanted)
                    assert abs(own_extreme['mid']-state[own_name]) < 1e-8
                    assert abs(peer_extreme['mid']-state[peer_name]) < 1e-8
                    at_decision = raw_point(key, record, decision, wanted)
                    recovery = dict(自己極値=own_extreme, 相手極値=peer_extreme,
                        自己mid回復pt=float(side*(at_decision['mid']-state[own_name])),
                        自己LastPrice回復pt=float(side*(at_decision['LastPrice']-own_extreme['LastPrice'])),
                        自己spread変化pt=float(at_decision['spread_pt']-own_extreme['spread_pt']),
                        極値から実新規までの取得幅pt=float(side*(parent[6]-state[own_name])),
                        準備中心から実新規までpt=float(side*(parent[6]-state['range_anchor'])),
                        観測極値失敗線=state['witness_stop'])
                valid_rows = np.arange(entry, exit_row+1)[record['quote_valid'][entry:exit_row+1]]
                quote = record['bid'] if side == 1 else record['ask']
                moves = side*(quote[valid_rows]-parent[6])
                maximum = int(valid_rows[int(np.argmax(moves))])
                minimum = int(valid_rows[int(np.argmin(moves))])
                multiplier = 1000. if symbol == 'TOPIX' else 10.
                matched_control = None
                if ident.endswith('_ESTOP'):
                    base = ident.removesuffix('_ESTOP')
                    if base in controls:
                        original = controls[base][key]
                        lookup = REVIEW.parents(original)
                        new_key = (int(parent[15]), entry, source, side, int(parent[5]), float(parent[6]))
                        if new_key in lookup:
                            old = lookup[new_key]
                            old_pair = original['orders'][(original['orders'][:, 2] == old[0])
                                & (original['orders'][:, 3] == old[1])]
                            assert len(old_pair) == 2
                            matched_control = dict(対照=base, 同一新規=True,
                                固定停止返済判断=point(key, int(old_pair[1, 1]), material, mapped, wanted),
                                固定停止返済約定=point(key, int(old[3]), material, mapped, wanted),
                                固定停止返済理由=original['reasons'][int(old[13])],
                                固定停止収支円=float(old[11]), 管理差円=float(parent[11]-old[11]))
                details.append(dict(親=int(parent[0]), 源='J2' if source == 0 else 'O06',
                    方向='買い' if side == 1 else '売り', 枚数=int(parent[5]), 純収支円=float(parent[11]),
                    新規判断=point(key, decision, material, mapped, wanted),
                    新規約定=point(key, entry, material, mapped, wanted),
                    返済判断=point(key, int(orders[1, 1]), material, mapped, wanted),
                    返済約定=point(key, exit_row, material, mapped, wanted),
                    返済理由=ledger['reasons'][int(parent[13])], 当時の準備状態=state,
                    回復の内訳=recovery, 中心と監視の経緯=timeline,
                    同一新規の固定停止対照=matched_control,
                    事後最大順行=dict(原板=point(key, maximum, material, mapped, wanted),
                        順行pt=float(moves.max()), 費用後評価円=float(moves.max()*parent[5]*multiplier-parent[8]-parent[9])),
                    事後最大逆行=dict(原板=point(key, minimum, material, mapped, wanted),
                        順行pt=float(moves.min()), 費用後評価円=float(moves.min()*parent[5]*multiplier-parent[8]-parent[9]))))
            output[symbol].append(dict(場=key[0], 利益円=summary['profit'], 損失円=summary['loss'],
                収支円=summary['net'], 源別=summary['sources'], 全親=parents, 大きな損失親3=details))
    return output


def attach_raw(wanted: dict, material: dict) -> dict:
    """
    機能: 原本JSONL同seqの価格と上位3段板を独立抽出・照合する。
    引数: wanted/material(dict)。
    返り値: dict。原本板の照合件数と指紋。
    """
    proofs = {}
    for key, requested in wanted.items():
        path = ROOT/'book'/key[1]/(key[0]+'.jsonl')
        selected = set(requested)
        checked = 0
        with path.open('rb') as stream:
            for seq, line in enumerate(stream):
                if seq not in selected:
                    continue
                raw = json.loads(line)
                for point_value in requested[seq]:
                    assert float(raw['CurrentPrice']) == point_value['LastPrice']
                    assert float(raw['Buy1']['Price']) == point_value['bid']
                    assert float(raw['Sell1']['Price']) == point_value['ask']
                    point_value['原本板'] = dict(CurrentPriceTime=raw['CurrentPriceTime'],
                        買い=[raw[f'Buy{i}'] for i in (1, 2, 3)],
                        売り=[raw[f'Sell{i}'] for i in (1, 2, 3)],
                        TradingVolume=raw.get('TradingVolume'), TradingVolumeTime=raw.get('TradingVolumeTime'))
                checked += 1
        assert checked == len(selected)
        proofs['|'.join(key)] = dict(同seq板=checked, SHA256=REVIEW.digest(path))
    return proofs


def main() -> None:
    """
    機能: 主と事前参考の最悪場を具体板で診断し、独立原本照合を保存する。
    引数: なし。
    返り値: None。採否ルールや過去公開成果を変更しない。
    """
    fixed = REVIEW.read(WORK/'事前固定.json')
    for relative, expected in fixed['SHA256'].items():
        assert REVIEW.digest(ROOT/relative) == expected, relative
    assembled = REVIEW.read(WORK/'analysis/比較結果.json')
    chosen = REVIEW.read(WORK/'前16参考代表.json')['selected']
    data = module('全31入力読取の原板診断92', WORK/'data.py')
    material = data.load_inputs()
    wanted, output, controls = {}, {}, {}
    identities = list(dict.fromkeys((fixed['主'], chosen)))
    for ident in dict.fromkeys(identities+[i.removesuffix('_ESTOP') for i in identities if i.endswith('_ESTOP')]):
        ledgers = {}
        for stage in ('front', 'back'):
            accounts = REVIEW.read(WORK/stage/'ledgers'/f'{ident}.pkl')
            assert not set(accounts) & set(ledgers)
            ledgers.update(accounts)
        controls[ident] = ledgers
    for ident in identities:
        output[ident] = diagnose(ident, assembled['results'][ident], controls[ident], material, wanted, controls)
    raw_proofs = attach_raw(wanted, material)
    REVIEW.save('主と事前参考の赤字上位3場及び回復中心の具体原板.json', dict(
        全合格=True, 主=fixed['主'], 前16事前参考=chosen, 最悪場=output,
        原本板の同seq照合=raw_proofs, 事後診断のみ=True, API取得=0, 実注文=0,
        固定SHA256=REVIEW.digest(WORK/'事前固定.json'),
        根集計SHA256=REVIEW.digest(WORK/'analysis/比較結果.json'),
        計算コードSHA256=REVIEW.digest(Path(__file__)), 注意=[
            '赤字場、最大順行・逆行の選定は事後診断。売買判断へ逆流しない。',
            '板厚の増減だけから約定・取消・補充の意図を断定しない。',
            '原本CurrentPriceTimeは真の受信時計でない。mini/micro全数量約定は未証明。',
            '保存stateは説明用に表示し、極値値と取得価格は原本同seqから独立照合した。']))
    print('主と事前参考の赤字上位3場を具体原板同seqで照合して保存しました', flush=True)


if __name__ == '__main__':
    main()
