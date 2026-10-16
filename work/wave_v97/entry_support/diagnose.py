"""売買を再実行せず、保存済み候補と待機の各門番を元入力から独立に数える。"""

from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import socket
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
IDS = tuple(dict.fromkeys([f'A{a}_X3' for a in range(9)] + ['A0_X1', 'A4_X0', 'A4_X1', 'A4_X2']))
sys.dont_write_bytecode = True


def module(name: str, path: Path) -> object:
    """
    機能: 固定済み入力と戦略の準備関数だけを固有名で読む。
    引数: name(str)、path(Path)。
    返り値: object。売買execute/playを呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def sha(path: Path) -> str:
    """
    機能: 根の金融固定又は今回読取台帳の現在指紋を記録する。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 保存入力の理解調査で外部接続を行わない。
    引数: args(tuple)、kwargs(dict)。
    返り値: None。接続は例外で拒絶する。
    """
    raise RuntimeError('保存入力と正式保存台帳の入口だけを診断します')


def expand(changes: np.ndarray, n: int) -> np.ndarray:
    """
    機能: 原行番号付き疎50状態を全原行へ独立復元する。
    引数: changes(ndarray[float])、n(int)。
    返り値: ndarray[float]は50列の保存状態。
    """
    rows = changes[:, 0].astype(np.int64)
    assert rows[0] == 0 and rows[-1] == n - 1 and np.all(np.diff(rows) > 0)
    result = np.repeat(changes[:, 1:], np.diff(np.r_[rows, n]), axis=0)
    assert result.shape == (n, 50)
    return result


def j2_conditions(gridded: dict, side: int) -> dict:
    """
    機能: 旧J2の現在資格を価格窓の不明と価格支持不足に分けて独立に再計算する。
    引数: gridded(dict)、side(int)。
    返り値: dictは観測可否、正方向、比率、十分な逆OFI及び全許可の格子mask。
    """
    n = len(gridded['grid'])
    current = np.ones(n, bool)
    known = np.ones(n, bool)
    direction = np.ones(n, bool)
    reverse = np.zeros(n, bool)
    returns = []
    for symbol in SYMBOLS:
        market = gridded['markets'][symbol]
        current &= market['current']['valid']
        w = market['windows'][300]
        finite = w['source_valid'] & np.isfinite(w['ret_bp'])
        known &= finite
        signed = side * w['ret_bp']
        direction &= signed > 0
        returns.append(signed)
        f = market['flow'][15]
        sufficient = (f['source_valid'] & f['valid'] & ~f['missing_ofi']
            & (f['nonzero_ofi_count'] >= 3) & np.isfinite(f['ofi_ratio']))
        reverse |= sufficient & (side * f['ofi_ratio'] <= -.1)
    ratio = np.minimum(*returns) >= .25 * np.maximum(*returns)
    allowed = current & known & direction & ratio & ~reverse
    return dict(current=current, known=known, direction=direction, ratio=ratio, reverse=reverse, allowed=allowed)


def observe(record: dict, signal: dict, dense: np.ndarray, config: dict) -> dict:
    """
    機能: 保存watch50の各門番を自己原板と既公開peer及び旧J2から独立に復元する。
    引数: record/signal/config(dict)、dense(ndarray[float])。
    返り値: dictは門番maskと評価候補行。旗の意味を損益へ読み替えない。
    """
    n = len(record['time_s'])
    latest = np.maximum.accumulate(signal['mapped'])
    safe = np.maximum(latest, 0)
    fresh = (latest >= 0) & (record['time_s'] - signal['grid'][safe] <= 10. + 1e-8)
    qok = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
    qok &= (record['bid'] > 0) & (record['ask'] > record['bid'])
    peer = signal['entry_peer_bbo'][safe]
    observed = np.column_stack((np.arange(n), record['seq'], record['time_s'], record['bid'], record['ask'], peer[:, :5]))
    pair = (qok & fresh & (peer[:, 5] == 1) & np.isfinite(observed).all(axis=1)
        & (peer[:, 0] >= 0) & (peer[:, 1] >= 0) & (peer[:, 3] > 0) & (peer[:, 4] > peer[:, 3])
        & (peer[:, 2] <= record['time_s'] + 1e-8))
    side = dense[:, 2]
    j2 = fresh & np.where(side == 1, signal['entry_j2_long'][safe], signal['entry_j2_short'][safe])
    source = (pair & (dense[:, 27] == 1) & (observed[:, 0] > dense[:, 17])
        & (observed[:, 1] > dense[:, 18]) & (observed[:, 2] > dense[:, 16])
        & (observed[:, 2] > dense[:, 19]) & (observed[:, 5] > dense[:, 22])
        & (observed[:, 6] > dense[:, 23]) & (observed[:, 7] > dense[:, 16])
        & (observed[:, 7] > dense[:, 24]))
    tick, peer_tick = record['tick'], signal['peer_tick']
    quotes = (source & (side * (observed[:, 3] - dense[:, 20]) >= tick - tick*1e-8)
        & (side * (observed[:, 4] - dense[:, 21]) >= tick - tick*1e-8)
        & (side * (observed[:, 8] - dense[:, 25]) >= peer_tick - peer_tick*1e-8)
        & (side * (observed[:, 9] - dense[:, 26]) >= peer_tick - peer_tick*1e-8))
    quote = np.where(side == 1, record['ask'], record['bid'])
    kind = config['entry_wait_kind']
    price = (np.ones(n, bool) if kind == 1 else side * (quote - dense[:, 7]) >= dense[:, 10] - tick*1e-8
             if kind in (2, 3, 4) else ((kind == 5) | (dense[:, 1] == 2))
             & (side * (quote - dense[:, 14]) >= dense[:, 12] - tick*1e-8))
    normal = qok & signal['quality'] & ~signal['reset'] & fresh & pair
    return dict(latest=latest, fresh=fresh, qok=qok, pair=pair, j2=j2, source=source,
        quotes=quotes, price=price, normal=normal, observed=observed)


def episode_count(mask: np.ndarray, dense: np.ndarray) -> int:
    """
    機能: 行数だけでなく、条件を一度でも経験した受理候補数を数える。
    引数: mask(ndarray[bool])、dense(ndarray[float])。
    返り値: intは候補番号が正の異なる候補数。
    """
    values = dense[mask, 3]
    return len(np.unique(values[values > 0]))


def main() -> None:
    """
    機能: 全31の入力と既存台帳から観測門番を集計し、接続ずれと活動不足を分離する。
    引数: なし。
    返り値: Noneは入口支持診断JSON。損益による条件変更や新しい売買を行わない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    data = module('待機支持の固定入力97', WORK / 'data.py')
    strategy = module('待機支持の固定準備97', WORK / 'strategy.py')
    catalog = module('待機支持の固定条件97', WORK / 'catalog.py')
    fixed = json.loads((WORK / '事前固定.json').read_text(encoding='utf-8'))
    configs = {c['id']: c for c in catalog.catalog()}
    material = data.load_inputs()
    prepared = strategy.prepare(material, configs['A0_X3'])
    j2, input_checks = {}, dict(格子J2全許可一致=0, 元P0候補方向一致=0, 候補row現在J2許可一致=0,
        候補row公開格子時刻一致=0, 候補row及びlatestの接続ずれ=0)
    for session, grid in material['grids'].items():
        for side in (1, -1):
            conditions = j2_conditions(grid, side)
            name = 'long_allowed' if side == 1 else 'short_allowed'
            np.testing.assert_array_equal(conditions['allowed'], material['entries'][session]['entries']['J2'][name])
            j2[session, side] = conditions
            input_checks['格子J2全許可一致'] += len(grid['grid'])
        for symbol in SYMBOLS:
            key = session, symbol
            value = prepared[key]
            r, signal = value['record'], value['signal']
            expected = np.zeros(len(r['time_s']), np.int8)
            for row in material['legacy'][key]['candidates']:
                i, side = int(row[1]), int(row[2])
                g = int(signal['mapped'][i])
                if g >= 0 and j2[session, side]['allowed'][g]:
                    expected[i] = side
            np.testing.assert_array_equal(expected, signal['event'])
            candidates = np.flatnonzero(expected)
            input_checks['元P0候補方向一致'] += len(candidates)
            for i in candidates:
                side, g = int(expected[i]), int(signal['mapped'][i])
                assert g == np.maximum.accumulate(signal['mapped'][:i+1])[-1]
                assert signal['grid'][g] <= r['time_s'][i] <= signal['grid'][g] + 10.
                assert j2[session, side]['allowed'][g]
                input_checks['候補row現在J2許可一致'] += 1
                input_checks['候補row公開格子時刻一致'] += 1
    print('全31入力の旧J2・P0候補・現在格子接続は独立式と一致', flush=True)
    rows, hashes, samples, a4orders = [], {}, [], {}
    for ident in IDS:
        config = configs[ident]
        for part, session_names in (('front', fixed['前16']), ('back', fixed['後15'])):
            path = WORK / part / 'ledgers' / (ident + '.pkl')
            assert path.exists(), '完了通知後の既存台帳だけを読む'
            hashes[str(path.relative_to(ROOT))] = sha(path)
            with path.open('rb') as stream:
                ledgers = pickle.load(stream)
            assert set(ledgers) == {(s, m) for s in session_names for m in SYMBOLS}
            for key, ledger in sorted(ledgers.items()):
                value = prepared[key]
                r, signal = value['record'], value['signal']
                n = len(r['time_s'])
                assert ledger['input_rows'] == n
                for name, expected in ledger['wait_input_SHA256'].items():
                    assert hashlib.sha256(signal[name].tobytes()).hexdigest() == expected
                assert hashlib.sha256(signal['event'].tobytes()).hexdigest() == ledger['trend_event_SHA256']
                if ident.startswith('A4_'):
                    a4orders[ident, key] = ledger['orders'].copy()
                events = np.asarray(ledger['entry_wait_events'])
                accepted = events[events[:, 1] == 1]
                triggers = events[events[:, 1] == 8]
                canceled = events[events[:, 1] == 3]
                ignored = events[events[:, 1] == 2]
                summary = dict(条件=ident, 期間='前16' if part == 'front' else '後15', 場=key[0], 商品=key[1],
                    元候補=int(np.count_nonzero(signal['event'])), 待機受理=len(accepted), 市場新規予約=len(triggers),
                    取消=len(canceled), 新候補不参加=len(ignored),
                    取消理由={str(k):int(v) for k,v in Counter(canceled[:, 2].astype(int)).items()},
                    不参加理由={str(k):int(v) for k,v in Counter(ignored[:, 2].astype(int)).items()})
                if config['entry_wait_kind'] == 0:
                    rows.append(summary)
                    continue
                assert len(accepted) == len(triggers) + len(canceled)
                dense = expand(np.asarray(ledger['watch_state_changes']), n)
                assert hashlib.sha256(dense.tobytes()).hexdigest() == ledger['watch_state_SHA256']
                # 触発行の50列は解除後phase0と解除前flagsの複合記録。
                # 独立の門番再計算には57イベントの当時phaseを用い、金融台帳は変更しない。
                trigger_rows = triggers[:, 0].astype(int)
                dense[trigger_rows, :32] = triggers[:, 7:39]
                obs = observe(r, signal, dense, config)
                live = dense[:, 0] == 1
                live[trigger_rows] = True
                for field, column in (('j2', 43), ('source', 45), ('quotes', 46), ('price', 47), ('pair', 49)):
                    np.testing.assert_array_equal(obs[field][live], dense[live, column].astype(bool))
                np.testing.assert_array_equal(obs['latest'][live], dense[live, 42].astype(int))
                np.testing.assert_array_equal(obs['observed'][live], dense[live, 32:42])
                structural = np.zeros(n, bool)
                structural[events[np.isin(events[:, 1], [1, 3, 5, 6, 7]), 0].astype(int)] = True
                evaluate = live & ~structural & (np.arange(n) > dense[:, 15])
                mandatory = evaluate & obs['normal']
                price = mandatory & obs['price']
                supported = price & obs['j2']
                final = supported & (obs['quotes'] if config['entry_bbo_confirm'] else True)
                np.testing.assert_array_equal(np.flatnonzero(final), trigger_rows)
                summary['有効評価原行'] = int(evaluate.sum())
                summary['門番漏斗原行'] = {name:int(mask.sum()) for name,mask in (
                    ('現在正常pairと自己品質',mandatory), ('価格条件も成立',price),
                    ('現在旧J2も成立',supported), ('両BBO条件も成立',final))}
                summary['門番を一度でも満たした候補'] = {name:episode_count(evaluate & mask,dense) for name,mask in (
                    ('正常pair',obs['pair']), ('旧J2',obs['j2']), ('源厳密更新',obs['source']),
                    ('両BBO価格進行',obs['quotes']), ('価格条件',obs['price']))}
                summary['価格成立候補の不足'] = {name:episode_count(mask,dense) for name,mask in (
                    ('価格条件だけは満たした',evaluate & obs['price']),
                    ('価格成立時にpair不明',evaluate & obs['price'] & ~obs['pair']),
                    ('価格成立時に旧J2不許可',price & ~obs['j2']),
                    ('価格と旧J2成立でも両BBO不足',supported & ~obs['quotes']))}
                latest = np.maximum(obs['latest'],0)
                sides = dense[:, 2]
                causes = {}
                for name in ('current','known','direction','ratio','reverse'):
                    values = np.where(sides == 1,j2[key[0],1][name][latest],j2[key[0],-1][name][latest])
                    causes[name] = values
                categories = dict(現在価格源不明=~causes['current'],
                    五分価格窓不明=causes['current'] & ~causes['known'],
                    五分方向支持なし=causes['current'] & causes['known'] & ~causes['direction'],
                    二市場の進行比不足=causes['current'] & causes['known'] & causes['direction'] & ~causes['ratio'],
                    十五秒逆OFI=causes['current'] & causes['known'] & causes['direction'] & causes['ratio'] & causes['reverse'])
                union = np.zeros(n,bool)
                for mask in categories.values():
                    union |= mask
                np.testing.assert_array_equal(union[live], ~obs['j2'][live])
                summary['価格成立時J2不許可の理由原行'] = {name:int(np.count_nonzero(price & mask)) for name,mask in categories.items()}
                summary['押しを一度経験した候補'] = episode_count(live & (dense[:,1] == 2),dense)
                summary['何も条件を変えない'] = True
                for name,mask in categories.items():
                    chosen = np.flatnonzero(price & mask)
                    if len(chosen) and ident in ('A3_X3','A7_X3'):
                        i = int(chosen[0])
                        samples.append(dict(条件=ident, 場=key[0], 商品=key[1], 原行=i,
                            時計=datetime.fromtimestamp(r['time_s'][i], timezone(timedelta(hours=9))).isoformat(),
                            原因=name, 候補番号=int(dense[i,3]), 候補原行=int(dense[i,4]),
                            方向=int(sides[i]), 現在格子=int(obs['latest'][i]), 価格条件=True,
                            pair=bool(obs['pair'][i]), 源更新=bool(obs['source'][i]), 両気配進行=bool(obs['quotes'][i])))
                rows.append(summary)
            del ledgers
        print(ident+': 待機50列と元入力の門番が一致',flush=True)
    aggregate = {}
    for ident in IDS:
        aggregate[ident] = {}
        for period in ('前16','後15','全31'):
            aggregate[ident][period] = {}
            for symbol in SYMBOLS:
                subset = [r for r in rows if r['条件']==ident and r['商品']==symbol and (period=='全31' or r['期間']==period)]
                totals = {name:sum(r[name] for r in subset) for name in ('元候補','待機受理','市場新規予約','取消','新候補不参加')}
                for field in ('取消理由','不参加理由','門番漏斗原行','門番を一度でも満たした候補',
                              '価格成立候補の不足','価格成立時J2不許可の理由原行'):
                    counter = Counter()
                    for r in subset:
                        counter.update(r.get(field,{}))
                    totals[field] = dict(counter)
                totals['押しを一度経験した候補'] = sum(r.get('押しを一度経験した候補',0) for r in subset)
                aggregate[ident][period][symbol] = totals
    same_a4 = {}
    for symbol in SYMBOLS:
        keys = [(s,symbol) for s in fixed['全31']]
        base = [a4orders['A4_X3',key] for key in keys]
        same_a4[symbol] = {ident:dict(全31注文完全同一=all(np.array_equal(a4orders[ident,key],reference)
            for key,reference in zip(keys,base)), 新規注文数=int(sum(np.count_nonzero(reference[:,7]) for reference in base)),
            相違する場=[key[0] for key,reference in zip(keys,base) if not np.array_equal(a4orders[ident,key],reference)])
            for ident in ('A4_X0','A4_X1','A4_X2')}
    paths = [Path(__file__), WORK/'engine.py',WORK/'strategy.py',WORK/'catalog.py',WORK/'data.py',
        WORK/'事前固定.json',ROOT/'work/wave_v77/signals.py']
    proof = dict(全合格=True, 調査='損益から選ばず入力資格と待機の流れを理解する', 条件=list(IDS),
        対象口座=len(rows), 入力整合=input_checks, 集計=aggregate, 具体原行=samples,
        A4四出口の注文同一性=same_a4, 場別の門番=rows,
        読取範囲='全31完了の根通知後のfront/back既存台帳。取引の利益・損失・収支項目を集計に用いない。',
        誤解防止='行数及び候補の門番経験を数えた診断であり、各門番を外した時の収益や予測正答率ではない。未知五分窓を価格の反証に読み替えない。',
        五十列の解釈='trigger行は解除後phase0と解除前の判定flagsを保存しているため、独立再計算のphaseだけ57イベントの同じtrigger行から当時値を復元した。固定台帳は変更しない。',
        新売買実行=0, 売買条件変更=0, 固定依存変更=0, API取得=0, 実注文=0,
        SHA256={**hashes,**{str(p.relative_to(ROOT)):sha(p) for p in paths}})
    destination = HERE/'全31の候補許可と現在門番及び待機不成立の独立入力診断.json'
    destination.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True, 対象口座=len(rows), 入力整合=input_checks,
        主前16=aggregate['A7_X3']['前16'], 主全31=aggregate['A7_X3']['全31'],
        A4四出口の注文同一性=same_a4, 新売買実行=0),ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
