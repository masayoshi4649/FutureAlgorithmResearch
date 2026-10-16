"""最悪場の具体板時刻と、赤字救済・新赤字・大勝ち依存を正式完了後に照合する。"""

import math
from pathlib import Path

import numpy as np

import 共通独立読取 as R
import 全18親会計と安定性及び一軸経路分解 as A


def parent(key: tuple, trade: np.ndarray, ledger: dict, material: dict, config: dict, wanted: dict) -> dict:
    """
    機能: 損失親の候補・判断・実約定・清算順逆行・停止の原板時刻を具体化する。
    引数: key(tuple[str,str])、trade(ndarray)、ledger/material/config/wanted(dict)。
    返り値: dictは当時確認と事後観測を区別した親診断。
    """
    record = material['prices'][key]
    mapped = R.published_grid(record, material['grids'][key[0]]['grid'])
    orders = ledger['orders'][ledger['orders'][:, 2] == trade[0]]
    assert len(orders) == 2 and orders[0, 7] == 1 and orders[1, 7] == 0
    entry, close = orders
    side, entry_row, exit_row = int(trade[4]), int(trade[2]), int(trade[3])
    quote = record['bid'] if side == 1 else record['ask']
    valid = (record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
        & (record['bid'] > 0) & (record['ask'] > record['bid']))
    eligible = np.flatnonzero(valid[entry_row:exit_row + 1]) + entry_row
    signed = side * (quote[eligible] - trade[6])
    peak, trough = int(eligible[np.argmax(signed)]), int(eligible[np.argmin(signed)])
    width = max(2, math.ceil(record['price'][0] * config.get('trend_width_fraction', .004)
        / record['tick'] - 1e-10)) * record['tick']
    candidate = ledger['trend_candidate_state']['candidates']
    found = candidate[(candidate[:, 1] == trade[15]) & (candidate[:, 2] == side)]
    assert len(found) == 1
    g = int(found[0, 0])
    candidate_grid = material['trend_prices']['I3'][key[0]]['candidate_grid']
    result = dict(親=int(trade[0]), 方向=side, 枚数=int(trade[5]),
        新規価格=float(trade[6]), 返済価格=float(trade[7]), 総額円=float(trade[10]),
        料金円=float(trade[8] + trade[9]), 純額円=float(trade[11]),
        返済理由=ledger['reasons'][int(trade[13])], 旧停止追尾幅pt=width,
        候補発火時刻=R.clock(candidate_grid[g]), 候補発火格子=g,
        新規判断時計=R.clock(entry[10]), 実新規時計=R.clock(entry[11]),
        新規判断から実約定秒=float(entry[11] - entry[10]),
        返済判断時計=R.clock(close[10]), 実返済時計=R.clock(close[11]),
        返済判断から実約定秒=float(close[11] - close[10]),
        新規判断原板=R.point(key, int(entry[1]), material, mapped, wanted),
        実新規原板=R.point(key, entry_row, material, mapped, wanted),
        返済判断原板=R.point(key, int(close[1]), material, mapped, wanted),
        実返済原板=R.point(key, exit_row, material, mapped, wanted),
        事後清算最大順行pt=float(signed.max()), 事後清算最大逆行pt=float(signed.min()),
        事後順行頂点=R.point(key, peak, material, mapped, wanted),
        事後逆行底点=R.point(key, trough, material, mapped, wanted))
    result['候補及び許可の別格子'] = dict(候補15秒格子時刻=R.clock(candidate_grid[g]),
        許可5秒格子=int(mapped[int(entry[1])]),
        注意='P0候補は旧midと旧資格。表示I3LPは同時点診断でありP0入口へ使ったとは呼ばない。')
    previous = ledger['trades'][ledger['trades'][:, 3] < entry_row]
    if len(previous):
        old = previous[-1]
        result['直前完了親'] = dict(親=int(old[0]), 方向=int(old[4]), 純額円=float(old[11]),
            停止理由=int(old[13]), 実返済原板=R.point(key, int(old[3]), material, mapped, wanted),
            同方向=old[4] == trade[4])
    loss = ledger['loss_reentry_events']
    columns = {name: i for i, name in enumerate(ledger['loss_event_columns'])}
    evidence = loss[(loss[:, 0] <= trade[15]) & (loss[:, 1] == 4)]
    exact = evidence[evidence[:, 0] == trade[15]]
    result['当該新規の反対gate'] = [{name: float(value[index]) for name, index in columns.items()} for value in exact]
    names = {name:i for i,name in enumerate(ledger['trend_parent_columns'])}
    found_diag = ledger['trend_parent_diagnostics'][ledger['trend_parent_diagnostics'][:,0] == trade[0]]
    assert len(found_diag) == 1
    diagnostic = {name:float(found_diag[0,index]) for name,index in names.items()}
    assert diagnostic['entry_row'] == entry_row and diagnostic['exit_row'] == exit_row
    assert diagnostic['net'] == trade[11] and diagnostic['exit_price'] == trade[7]
    observation_row = int(diagnostic['decision_observation_row'])
    result['保存出口証拠'] = diagnostic
    result['当該実新規の初期S'] = diagnostic['initial_width']
    result['当該実新規の利益追尾D'] = diagnostic['trail_width']
    result['返済判断の観測原板'] = R.point(key, observation_row, material, mapped, wanted)
    result['停止線の所有者'] = [name for bit,name in ledger['trend_line_owners'].items()
        if int(diagnostic['effective_line_owner']) & int(bit)]
    changes = ledger['trend_exit_state_changes']
    columns = {name:i+1 for i,name in enumerate(ledger['trend_exit_state_columns'])}
    active = changes[(changes[:,columns['parent_id']] == trade[0]) &
        (changes[:,columns['protection_active']] == 1)]
    if len(active):
        activation = int(active[0,0])
        result['最初に2S保護が有効化した原板'] = R.point(key,activation,material,mapped,wanted)
        result['保護発火時計'] = R.clock(record['time_s'][activation])
    result['時刻の注意'] = '場末forceは既知予定時刻。decision_observation_rowの気配は観測行の時刻であり予定時刻の板に遡らせない。'
    result['原因の注意'] = 'reason2はpeakが建値から動いただけでも付く。初期/追尾/利益床はownerとline hitで区別する。'
    return result


def worst(ident: str, result: dict, ledgers: dict, material: dict, wanted: dict) -> dict:
    """
    機能: 各商品の最悪3赤字場と大損3親を原本seqへ戻す。
    引数: ident(str)、result/ledgers/material/wanted(dict)。
    返り値: dictは具体時刻・原板・独立停止診断。
    """
    answer = {}
    for symbol in R.SYMBOLS:
        selected = sorted((row for row in result['rows'] if row['symbol'] == symbol and row['net'] < 0),
            key=lambda row: (row['net'], row['session']))[:3]
        answer[symbol] = []
        for row in selected:
            key = row['session'], symbol
            ledger = ledgers[key]
            trades = sorted((trade for trade in ledger['trades'] if trade[11] < 0), key=lambda trade: trade[11])[:3]
            answer[symbol].append(dict(場=key[0], 利益円=row['profit'], 損失円=row['loss'], 収支円=row['net'],
                含み損及び料金込み最大下落円=row['equity_drawdown'],
                大損3親=[parent(key, trade, ledger, material, result['config'], wanted) for trade in trades]))
    return answer


def dependence(results: dict, ledgers: dict, fixed: dict) -> dict:
    """
    機能: 各条件で最大勝ち除外・売買・日夜・前後・無取引を独立照合する。
    引数: results/ledgers/fixed(dict)。
    返り値: dictは全18の依存と活動診断。除外を売買ルールにしない。
    """
    answer = {}
    for ident, result in results.items():
        answer[ident] = {}
        for symbol in R.SYMBOLS:
            trades = np.concatenate([ledgers[ident][session, symbol]['trades'] for session in fixed['全31']])
            best = int(np.argmax(trades[:, 11])) if len(trades) and trades[:, 11].max() > 0 else None
            remaining = np.delete(trades, best, axis=0) if best is not None else trades
            value = result['periods']['全31'][symbol]
            removal = float(trades[best, 11]) if best is not None else 0.
            assert abs(R.totals(remaining)['net'] - value['net'] + removal) < 1e-5
            answer[ident][symbol] = dict(最大利益親除外=R.totals(remaining), 除外最大親純額円=removal,
                最大利益日=value['best_day'], 最大利益日除外=value['without_best_day'], 買売別=value['directions'],
                前16=result['periods']['前16'][symbol], 後15=result['periods']['後15'][symbol],
                デイ=result['periods']['デイ'][symbol], ナイト=result['periods']['ナイト'][symbol],
                活動黒字場=value['positive_sessions'], 活動赤字場=value['losing_sessions'], 無取引場=value['no_trade_sessions'],
                全31安定性=result['stability']['全31'][symbol])
    return answer


def original_false_case(ledgers: dict, fixed: dict, material: dict, wanted: dict) -> dict:
    """
    機能: 95独立LP主の08:51損失親が、96の固定P0入口にも存在するか確認する。
    引数: ledgers/fixed/material/wanted(dict)は新正式保存と原板読取。
    返り値: dict。入口が異なる元親を96で救えたとは呼ばず、同判断がある場合だけ比べる。
    """
    key = ('2026-10-09_Day','NK225')
    old = None
    source = None
    for stage in ('front','back'):
        path = R.ROOT / 'work/wave_v95' / stage / 'ledgers/P3_R3_N.pkl'
        values = R.read(path)
        if key in values:
            old, source = values[key], path
            break
    assert old is not None
    record = material['prices'][key]
    selected = [t for t in old['trades'] if '08:51:' in R.clock(record['time_s'][int(t[15])])]
    assert len(selected) == 1
    trade = selected[0]
    mapped = R.published_grid(record,material['grids'][key[0]]['grid'])
    result = dict(元手法='95 P3_R3_N',元方向=int(trade[4]),元判断行=int(trade[15]),
        元純額円=float(trade[11]),元新規価格=float(trade[6]),元返済価格=float(trade[7]),
        元判断原板=R.point(key,int(trade[15]),material,mapped,wanted),
        元実新規原板=R.point(key,int(trade[2]),material,mapped,wanted),
        元実返済原板=R.point(key,int(trade[3]),material,mapped,wanted),
        元台帳SHA256=R.digest(source),固定P0対照の同判断親=[],全18での同判断親={})
    for ident, values in ledgers.items():
        matches = [t for t in values[key]['trades'] if t[15] == trade[15] and t[4] == trade[4]]
        result['全18での同判断親'][ident] = [dict(親=int(t[0]),新規行=int(t[2]),返済行=int(t[3]),
            新規価格=float(t[6]),返済価格=float(t[7]),純額円=float(t[11]),
            厳密同一実新規=np.array_equal(t[[2,4,5,6,8,15]],trade[[2,4,5,6,8,15]])) for t in matches]
    result['固定P0対照の同判断親'] = result['全18での同判断親'][fixed['対照']]
    result['結論の範囲'] = ('P0固定対照に同判断親が存在。厳密同一実新規かをさらに区別して出口差を評価する。'
        if result['固定P0対照の同判断親'] else
        'P0固定対照に元P3の同判断親は無い。96でこの損失が削れた又は救えたとは認定しない。')
    return result


def main() -> None:
    """
    機能: 主・事前参考・旧追従の最悪板と全18の安定性反例を保存する。
    引数: --根許可後(bool)は必須。全31正式完了通知後だけ実行する。
    返り値: None。新候補、親除外又は時間回避の策略再生はしない。
    """
    R.permission()
    fixed, assembled = R.validate()
    proof_path = R.HERE / '全18条件全31の独立親会計と安定性及び一軸経路分解.json'
    cause_path = R.HERE / '全18の利益床と旧勝ち刈り及び同一実新規の出口差.json'
    proof, cause = R.read(proof_path), R.read(cause_path)
    assert proof['全合格'] and cause['全合格'] and proof['口座'] == cause['口座'] == 1116
    assert proof['根集計SHA256'] == cause['根集計SHA256'] == R.digest(R.WORK / 'analysis/比較結果.json')
    material = R.material()
    roles = list(dict.fromkeys((fixed['主'], assembled['selected'], fixed['対照'])))
    ledgers = {}
    for config in fixed['条件']:
        ident = config['id']
        values = R.load_ledgers(ident)
        ledgers[ident] = values if ident in roles else {key: {'trades': value['trades']} for key, value in values.items()}
    wanted = {}
    cases = {ident: worst(ident, assembled['results'][ident], ledgers[ident], material, wanted) for ident in roles}
    original = original_false_case(ledgers,fixed,material,wanted)
    raw = R.attach_raw(wanted)
    transitions = {f'{fixed["対照"]}→{ident}': A.daily_change(assembled['results'][fixed['対照']], assembled['results'][ident], fixed['全31'])
        for ident in roles if ident != fixed['対照']}
    R.save('主と事前参考及び旧追従の最悪3場原板と赤字救済及び大勝ち依存の独立反証.json', dict(
        全合格=True, 条件数=18, 口座=1116, 主=fixed['主'], 前16固定参考=assembled['selected'],
        最悪3場=cases, 原本同seq照合=raw, 赤字救済と新活動及び新赤字の区別=transitions,
        元正常方向でも失敗した08時51分親の適用範囲=original,
        全18最大勝ち依存及び方向時間活動=dependence(assembled['results'], ledgers, fixed),
        両商品金額80=proof['両商品金額80'], 主変更=False, 参考事後差替え=False,
        注意=['狭SLの損失軽減と回復する勝ちの損失化及び後続新規連鎖を分ける。',
            '原板の量と価格変化から参加者の焦り・取消と約定の内訳・将来方向を断定しない。',
            '頭数又は黒字場増加と既存赤字救済を分ける。無取引・小枚数だけで予測改善と呼ばない。'],
        根拠SHA256={str(path.relative_to(R.ROOT)): R.digest(path) for path in (proof_path, cause_path)},
        計算コードSHA256=R.digest(Path(__file__)), **R.provenance()))
    print('最悪3場の具体板時刻と赤字救済・大勝ち依存を独立反証しました。', flush=True)


if __name__ == '__main__':
    main()
