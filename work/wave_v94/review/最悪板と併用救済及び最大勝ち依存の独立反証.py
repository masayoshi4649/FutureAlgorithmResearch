"""最悪3場を原板へ戻し、併用の救済・新活動・悪化と最大勝ち依存を分ける。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R
import 現在LPと板回復及び停止中心の独立診断 as D


def worst(ident: str, result: dict, ledgers: dict, material: dict, wanted: dict) -> dict:
    """
    機能: 商品別最悪3場と各場の大損3親を、判断時の価格源・板・線へ戻す。
    引数: ident(str)、result/ledgers/material/wanted(dict)。
    返り値: dictは具体的な秒時刻・原本seq・上位板及び停止経路。
    """
    cases = {}
    config = result['config']
    lane = config.get('price_lane','I0')
    for symbol in R.SYMBOLS:
        rows = sorted((row for row in result['rows'] if row['symbol']==symbol and row['net']<0),
                      key=lambda row:(row['net'],row['session']))[:3]
        cases[symbol] = []
        for summary in rows:
            key = summary['session'],symbol
            record,ledger = material['prices'][key],ledgers[key]
            mapped = R.published_grid(record,material['grids'][key[0]]['grid'])
            details = []
            for trade in sorted(ledger['trades'],key=lambda row:row[11])[:3]:
                if trade[11]>=0:
                    continue
                item = D.parent_detail(key,trade,ledger,material,config,wanted,True)
                side,entry,exit_row = int(trade[4]),int(trade[2]),int(trade[3])
                quote = record['bid'] if side==1 else record['ask']
                valid = np.flatnonzero(record['quote_valid'][entry:exit_row+1])+entry
                progress = side*(quote[valid]-trade[6])
                peak,trough = int(valid[np.argmax(progress)]),int(valid[np.argmin(progress)])
                item.update(事後最大清算順行pt=float(progress.max()),事後最大清算逆行pt=float(progress.min()),
                            順行頂点原板=D.point(key,peak,material,mapped,wanted,lane),
                            逆行底点原板=D.point(key,trough,material,mapped,wanted,lane))
                if int(trade[1])==1:
                    before = ledger['events'][(ledger['events'][:,2]==1)&(ledger['events'][:,0]<=trade[15])]
                    timeline = []
                    for code in (12,16,17,22,27):
                        same = before[before[:,3]==code]
                        if not len(same):
                            continue
                        event = same[-1]
                        timeline.append(dict(種類=ledger['event_codes'][code],原板=D.point(key,int(event[0]),material,mapped,wanted,lane),
                                             当時基準=float(event[7]),当時詳細=float(event[11])))
                    item['準備と回復の時系列'] = timeline
                details.append(item)
            cases[symbol].append(dict(場=key[0],利益円=summary['profit'],損失円=summary['loss'],収支円=summary['net'],
                                      全親独立会計=R.totals(ledger['trades']),源別=summary['sources'],
                                      全玉清算最大下落円=summary['equity_drawdown'],大損3親=details))
    return cases


def distribution(results: dict, ledgers: dict, fixed: dict) -> dict:
    """
    機能: M82の源を同数量単独へ照合し、追加・置換・赤字救済・新活動を別に集計する。
    引数: results/ledgers/fixed(dict)。
    返り値: dictは源非干渉・安定変化・日別補完及び金額比上限。
    """
    answer = {}
    columns = [0,1,3,4,5,6,7,8,9,10,11,12,13,14,15]
    for symbol in R.SYMBOLS:
        counts = [0,0]
        daily = []
        for session in fixed['全31']:
            key = session,symbol
            mixed = ledgers['M82'][key]
            for source,ident in ((0,'J8'),(1,'R2')):
                single = ledgers[ident][key]
                first = single['orders'][single['orders'][:,3]==source]
                second = mixed['orders'][mixed['orders'][:,3]==source]
                np.testing.assert_array_equal(first[:,columns],second[:,columns])
                assert single['source_curve_column_SHA256'][source]==mixed['source_curve_column_SHA256'][source]
                counts[source]+=1
            small = ledgers['R2'][key]
            np.testing.assert_allclose(small['range_parent_diagnostics'][:,1:],mixed['range_parent_diagnostics'][:,1:],equal_nan=True,rtol=0,atol=0)
            assert small['risk_state_SHA256']==mixed['risk_state_SHA256']
            assert small['range_state_SHA256']==mixed['range_state_SHA256']
            assert small['price_source_SHA256']==mixed['price_source_SHA256']
            source = [R.totals(mixed['trades'][mixed['trades'][:,1]==source]) for source in (0,1)]
            daily.append(dict(場=session,追従収支円=source[0]['net'],反発収支円=source[1]['net'],
                              合計収支円=source[0]['net']+source[1]['net'],追従親数=source[0]['campaigns'],反発親数=source[1]['campaigns'],
                              両源赤字=source[0]['net']<0 and source[1]['net']<0,
                              既存追従赤字を合計黒字へ救済=source[0]['net']<0 and source[0]['net']+source[1]['net']>0,
                              既存追従黒字を合計赤字へ悪化=source[0]['net']>0 and source[0]['net']+source[1]['net']<0,
                              追従無取引から新たな黒字活動=source[0]['campaigns']==0 and source[1]['campaigns']>0 and source[1]['net']>0,
                              追従無取引から新たな赤字活動=source[0]['campaigns']==0 and source[1]['campaigns']>0 and source[1]['net']<0))
        mixed = results['M82']['periods']['全31'][symbol]
        original,full,range_only = (results[ident]['periods']['全31'][symbol] for ident in ('J8','J10','R2'))
        assert abs(mixed['net']-original['net']-range_only['net'])<1e-4
        source_shares = [value['profit_share'] for value in mixed['sources'].values() if value['profit_share'] is not None]
        share = mixed['profit']/(mixed['profit']+mixed['loss']) if mixed['profit']+mixed['loss'] else None
        assert share==mixed['profit_share'] and (share is None or min(source_shares)-1e-12<=share<=max(source_shares)+1e-12)
        first = np.array([row['追従収支円'] for row in daily]);second = np.array([row['反発収支円'] for row in daily])
        stable_mixed = results['M82']['stability']['全31'][symbol]
        stable_original = results['J8']['stability']['全31'][symbol]
        stable_full = results['J10']['stability']['全31'][symbol]
        answer[symbol] = dict(同数量全経済注文及び全時価一致口座=dict(追従=counts[0],反発=counts[1]),
            反発源予定状態及び独立価格源一致=True,J8への追加収支円=mixed['net']-original['net'],
            J8への追加最大下落差円=mixed['equity_drawdown']-original['equity_drawdown'],
            J10からの同上限置換収支円=mixed['net']-full['net'],J10からの同上限置換最大下落差円=mixed['equity_drawdown']-full['equity_drawdown'],
            追加主下方偏差差=stable_mixed['downside_rms_units']-stable_original['downside_rms_units'],
            置換主下方偏差差=stable_mixed['downside_rms_units']-stable_full['downside_rms_units'],
            追従活動黒字率=stable_original['positive_session_rate'],併用活動黒字率=stable_mixed['positive_session_rate'],
            追従無取引数=stable_original['no_trade_sessions'],併用無取引数=stable_mixed['no_trade_sessions'],
            各源の親別金額利益割合={name:value['profit_share'] for name,value in mixed['sources'].items()},
            合計金額利益割合=share,最高源金額割合=max(source_shares) if source_shares else None,加重平均上限一致=True,
            場収支相関=float(np.corrcoef(first,second)[0,1]) if np.std(first)>0 and np.std(second)>0 else None,
            両源赤字場=[row['場'] for row in daily if row['両源赤字']],
            既存赤字救済場=[row['場'] for row in daily if row['既存追従赤字を合計黒字へ救済']],
            既存黒字を赤字へ悪化場=[row['場'] for row in daily if row['既存追従黒字を合計赤字へ悪化']],
            新たな黒字活動場=[row['場'] for row in daily if row['追従無取引から新たな黒字活動']],
            新たな赤字活動場=[row['場'] for row in daily if row['追従無取引から新たな赤字活動']],
            各場源別損益=daily,J8安定指標=stable_original,M82安定指標=stable_mixed,J10安定指標=stable_full)
    return answer


def dependence(results: dict, ledgers: dict, fixed: dict) -> dict:
    """
    機能: 最大利益親及び最大利益日除外と売買・日夜・前後の会計を確認する。
    引数: results/ledgers/fixed(dict)。
    返り値: dictは全53の依存診断。除外は売買ルールにしない。
    """
    output = {}
    for ident,result in results.items():
        output[ident] = {}
        for symbol in R.SYMBOLS:
            trades = np.concatenate([ledgers[ident][session,symbol]['trades'] for session in fixed['全31']])
            best = int(np.argmax(trades[:,11])) if len(trades) else None
            removed = float(trades[best,11]) if best is not None and trades[best,11]>0 else None
            remaining = np.delete(trades,best,axis=0) if removed is not None else trades
            metric = result['periods']['全31'][symbol]
            assert abs(R.totals(remaining)['net']-metric['net']+(removed or 0.))<1e-4
            output[ident][symbol] = dict(除外最大利益親収支円=removed,最大親除外=R.totals(remaining),
                最大利益日=metric['best_day'],最大日除外=metric['without_best_day'],買売別=metric['directions'],
                前16=result['periods']['前16'][symbol],後15=result['periods']['後15'][symbol],
                デイ=result['periods']['デイ'][symbol],ナイト=result['periods']['ナイト'][symbol],
                無取引場数=metric['no_trade_sessions'],活動黒字場数=metric['positive_sessions'],活動赤字場数=metric['losing_sessions'],
                全31安定指標=result['stability']['全31'][symbol])
    return output


def main() -> None:
    """
    機能: 根の許可後に主/J8/M82最悪板と併用源及び最大勝ち依存を保存する。
    引数: --根許可後(bool)。
    返り値: None。正式注文を追加又は変更せず、主を差し替えない。
    """
    R.permission()
    fixed,assembled = R.validate()
    proof_path = R.HERE/'全53条件全31の独立親会計と安定性及び一軸経路分解.json'
    cause_path = R.HERE/'全53入口の現在価格資格と回復停止中心の独立診断.json'
    proof,cause = R.read(proof_path),R.read(cause_path)
    assert proof['全合格'] and cause['全合格'] and proof['口座']==cause['口座']==3286
    assert proof['根集計SHA256']==cause['根集計SHA256']==R.digest(R.WORK/'analysis/比較結果.json')
    data = R.module('最悪及び源配分94の入力読取',R.WORK/'data_r1.py')
    material = data.load_inputs()
    ledgers = {config['id']:R.load_ledgers(config['id']) for config in fixed['条件']}
    identities = list(dict.fromkeys((fixed['主'],assembled['selected'],'J8','M82')))
    wanted = {}
    cases = {ident:worst(ident,assembled['results'][ident],ledgers[ident],material,wanted) for ident in identities}
    raw = D.attach_raw(wanted)
    source = distribution(assembled['results'],ledgers,fixed)
    R.save('主とJ8及びM82の最悪3場原板と配分及び依存の独立反証.json',dict(
        全合格=True,条件数=53,口座=3286,場数=31,主=fixed['主'],前16固定参考=assembled['selected'],
        最悪3場=cases,原本同seq照合=raw,配分源非干渉及び追加置換救済新活動=source,
        全53最大利益親日除外及び売買日夜前後=dependence(assembled['results'],ledgers,fixed),
        両商品金額80=proof['両商品金額80'],条件及び主変更=False,後成績で参考差替え=False,
        注意=['新活動黒字と既存赤字救済を同じにしない。','少数枚数への縮小は実額リスク削減でも、元の入口出口が改善した証拠ではない。',
              '源の低相関と思想の違いだけで成功を認定しない。同時赤字と源別金額割合上限を確認する。',
              '同原seq板はその時のsnapshot。食われた量、補充、取消、投資家の意図を直接識別する証明ではない。',
              '事後最大値及び最大勝ち除外を売買判断へ戻さない。mini/micro全量実約定と真受信時計は未証明。'],
        根拠SHA256={str(path.relative_to(R.ROOT)):R.digest(path) for path in (proof_path,cause_path)},
        計算コードSHA256=R.digest(Path(__file__)),**R.provenance()))
    print('最悪3場の原板と配分救済/新活動及び依存を独立診断しました',flush=True)


if __name__=='__main__':
    main()
