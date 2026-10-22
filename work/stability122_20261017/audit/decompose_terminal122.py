"""同一入口の二終端差を、Last移動・中値乖離・気配幅の会計恒等式へ分解する。"""

import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
OWN = HERE/'result/owned'
RESULT_SHA = 'ea3632b2e7bf2e9eb3e73addfede7f87deda0069efb30e4a3fd2647550dbab72'


def totals(rows: list) -> dict:
    """
    機能: 確認済み四十場の金額射影と正負場数だけを集計する。
    引数: rows(list[dict])は場ごとの独立会計分解。
    返り値: dictは合計とLast参考評価の場数。新しい戦略順位を作らない。
    """
    fields = ('early_net','close_net','difference','last_move','last_to_mid_basis_change',
              'half_spread_change','bbo_minus_last_change','early_last_reference_net',
              'close_last_reference_net','early_bbo_minus_last','close_bbo_minus_last')
    result = {key:sum(row[key] for row in rows) for key in fields}
    result.update(sessions=len(rows), lots=sum(row['lots'] for row in rows),
        close_last_positive=sum(row['close_last_reference_net']>0 for row in rows),
        close_last_negative=sum(row['close_last_reference_net']<0 for row in rows),
        close_last_flat=sum(row['close_last_reference_net']==0 for row in rows))
    return result


def main() -> None:
    """
    機能: 既監査所有の四十NPZ内の注文・気配だけから二終端の差を会計分解する。
    引数: なし。元measurement、旧NPZ、原市場、売買エンジンは読まない。
    返り値: None。同じ注文数量を固定した価格感応度の小証跡を保存する。
    """
    raw = (OWN/'完成結果.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RESULT_SHA
    data = json.loads(raw)
    rows = {(row['session'],row['method']):row for row in data['runs']}
    reports = []
    total_fees = 0
    for ref in data['cache']:
        raw = (OWN/(ref['session']+'.npz')).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == ref['sha256']
        with np.load(BytesIO(raw),allow_pickle=False) as stored:
            early = stored['0__orders']
            close = stored['1__orders']
            q = {key:stored['quotes__'+key] for key in ('row','time','last','bid','ask')}
        entries = early[early[:,1]==1]
        exits = early[early[:,1]==2]
        assert np.array_equal(entries,close) and len(entries) == len(exits)
        exit_by_uid = {int(row[0]):row for row in exits}
        session = ref['session']
        row_e, row_c = rows[session,'HOLD_EARLY'], rows[session,'HOLD_CLOSE_6M']
        reference = row_c['context']
        index = int(np.searchsorted(q['row'],reference['reference_row']))
        assert q['row'][index] == reference['reference_row'] and q['time'][index] == reference['reference_time']
        last_c, bid_c, ask_c = (float(q[key][index]) for key in ('last','bid','ask'))
        mid_c, spread_c = (bid_c+ask_c)/2, ask_c-bid_c
        early_net = close_net = early_last = close_last = 0.0
        last_move = basis_change = spread_change = 0.0
        early_bbo_last = close_bbo_last = 0.0
        for entry in entries:
            exit_ = exit_by_uid[int(entry[0])]
            side, entry_price = entry[2],entry[7]
            assert exit_[2] == -side and entry[8] == exit_[8] == 41
            last_e,bid_e,ask_e = exit_[13:16]
            mid_e,spread_e = (bid_e+ask_e)/2, ask_e-bid_e
            price_e = bid_e if side == 1 else ask_e
            price_c = bid_c if side == 1 else ask_c
            assert price_e == exit_[7]
            fee = entry[8]+exit_[8]
            early_net += side*(price_e-entry_price)*1000-fee
            close_net += side*(price_c-entry_price)*1000-fee
            early_last += side*(last_e-entry_price)*1000-fee
            close_last += side*(last_c-entry_price)*1000-fee
            a = side*(last_c-last_e)*1000
            b = side*((mid_c-last_c)-(mid_e-last_e))*1000
            c = -(spread_c-spread_e)*500
            delta = side*(price_c-price_e)*1000
            assert a+b+c == delta
            last_move += a
            basis_change += b
            spread_change += c
            early_bbo_last += side*(price_e-last_e)*1000
            close_bbo_last += side*(price_c-last_c)*1000
            total_fees += fee
        assert early_net == row_e['net'] and close_net == row_c['net']
        assert close_last == reference['last_price_reference_net']
        assert row_e['fees'] == row_c['fees'] == len(entries)*82
        delta = close_net-early_net
        assert delta == last_move+basis_change+spread_change
        assert close_bbo_last-early_bbo_last == basis_change+spread_change
        assert early_net-early_last == early_bbo_last and close_net-close_last == close_bbo_last
        reports.append(dict(session=session,lots=len(entries),
            long=int(np.count_nonzero(entries[:,2]==1)),short=int(np.count_nonzero(entries[:,2]==-1)),
            early_net=float(early_net),close_net=float(close_net),difference=float(delta),
            last_move=float(last_move),last_to_mid_basis_change=float(basis_change),
            half_spread_change=float(spread_change),bbo_minus_last_change=float(basis_change+spread_change),
            early_last_reference_net=float(early_last),close_last_reference_net=float(close_last),
            early_bbo_minus_last=float(early_bbo_last),close_bbo_minus_last=float(close_bbo_last),
            fees_each_condition=len(entries)*82,reference_time=reference['reference_time'],
            reference_last=last_c,reference_bid=bid_c,reference_ask=ask_c))
    result = totals(reports)
    assert result['lots'] == 653 and total_fees == 53546
    assert (result['early_net'],result['close_net'],result['difference']) == (-573046,-1031046,-458000)
    assert (result['close_last_reference_net'],result['close_last_positive'],result['close_last_negative']) == (-287546,14,26)
    grouped = {name:totals([row for row in reports if (row['long']==row['short']) == same])
               for name,same in (('同枚数',True),('非同枚数',False))}
    proof = dict(passed=True,result_sha256=RESULT_SHA,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),totals=result,
        inventory_groups=grouped,sessions=reports,financial_replay=0,original_market_reads=0,
        original_measurement_reads=0,old_npz_reads=0,owned_cache_reads=40,
        恒等式='引け代理net−早期net＝Σ side×(Last終端−Last早期)×倍率＋Σ side×[(中値−Last)終端−(中値−Last)早期]×倍率−Σ(気配幅終端−気配幅早期)×倍率÷2。全入口と両道手数料は同じで相殺する。',
        留保='Last参考は同じ全入口・数量・両道手数料を固定して終端価格だけLastへ置いた感応度で、実行可能な別売買や独立戦略成績ではない。LastとBBOの乖離は純粋な気配幅と同一ではなく、古いLast等の理由も断定しない。分解は会計恒等式で因果効果や未来予測ではない。')
    target = HERE/'result/二終端悪化のLast移動と気配乖離の独立会計分解.json'
    assert not target.exists()
    payload = (json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    target.write_bytes(payload)
    print(json.dumps(dict(passed=True,sha256=hashlib.sha256(payload).hexdigest(),totals=result,
        september24=next(row for row in reports if row['session']=='2026-09-24_Day'),inventory_groups=grouped),ensure_ascii=False))


if __name__ == '__main__':
    main()
