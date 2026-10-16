"""新九条件と保存三条件の主判定を、金融再運転なしで射影する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def line(cid: str, symbol: str, kind: str, mean: float, share: float | None,
         activity: list[int], passed: bool, parents: int) -> None:
    """
    機能: 主基準と全場平均を、新金融と保存引用を区別して表示する。
    引数: cid/symbol/kind(str)、mean(float)、share(float|None)、activity(list[int])、passed(bool)、parents(int)。
    返り値: None。黒字・赤字・無取引の順に場数を表示する。
    """
    print(json.dumps(dict(条件=cid, 商品=symbol, 根拠種別=kind, 全場平均=round(mean, 2),
                         金額利益割合=share, 黒赤無=activity, 主条件=passed, 親数=parents),
                     ensure_ascii=False, allow_nan=False))


def main() -> None:
    """
    機能: 新495口座・内部同値99・旧保存198の全場・容量・除外後を一目的一読で整理する。
    引数: なし。完了した新保存結果だけを読み、原入力と実台帳は読まない。
    返り値: None。12比較を12新金融や独立な新標本に数えない。
    """
    result_path = HERE / 'engine/finance/結果.json'
    destination = HERE / '十二比較の主判定と全場平均の小射影.json'
    assert not destination.exists(), 'この目的の読取を自動で反復しない。'
    content = result_path.read_bytes()
    result = json.loads(content.decode('utf-8-sig'))
    assert result['全合格'] and result['source開始終端一致']
    assert result['counts'] == {'既input一読': 33, '価格票準備口座': 66,
                                '新account金融': 495, '内部同値会計再利用': 99}
    assert len(result['configs']) == 12 and len(result['sessions']) == 33
    fresh = [c for c in result['configs'] if c['actual_financial']]
    old = [c for c in result['configs'] if not c['actual_financial']]
    assert len(fresh) == len(result['results']) == 9
    assert len(old) == len(result['reused_price_cases']) == 3
    assert result['PRICE再金融'] == 0
    assert result['内部同値再金融'] == 0 and len(result['internal_aliases']) == 3
    cases = {}
    for config in fresh:
        cid = config['id']
        group = result['results'][cid]
        cases[cid] = {}
        for symbol, cap in (('TOPIX', 10), ('NK225', 20)):
            periods = group['periods'][symbol]
            full = periods['全33']
            economy = full['economic']
            stability = full['stability']
            assert economy['session_count'] == 33
            assert economy['maximum_same_direction_quantity'] <= cap
            assert economy['mean_initial_quantity'] in (None, float(cap))
            own = [r for r in group['rows'] if r['symbol'] == symbol]
            assert len(own) == 33
            assert abs(sum(r['収支'] for r in own) / 33 - economy['mean_session_net_yen']) < 1e-5
            cases[cid][symbol] = dict(全場=full, 上位三除外=periods['上位3正収支場除外'],
                                      買売=group['directional_symbols'][symbol])
            line(cid, symbol, config['execution_kind_by_symbol'][symbol],
                 economy['mean_session_net_yen'], stability['profit_share'],
                 [stability['positive_sessions'], stability['losing_sessions'], stability['no_trade_sessions']],
                 stability['all_economic_targets'], economy['parent_count'])

    # ----------------------------------------
    # 完全同一PRICE対照は保存引用の分母を保持し、新再生へ数えない。
    reused = {}
    for config in old:
        cid = config['id']
        item = result['reused_price_cases'][cid]
        assert item['config'] == config and item['paired_price_id'] == config['paired_price_id']
        case = item['saved_public_case']
        assert len(case['rows']) == 66
        reused[cid] = item
        for symbol in ('TOPIX', 'NK225'):
            metric = case['metrics'][symbol]['full']
            own = [r for r in case['rows'] if r['symbol'] == symbol]
            assert len(own) == metric['sessions'] == 33
            assert abs(sum(r['net'] for r in own) / 33 - metric['mean_session_net']) < 1e-5
            line(cid, symbol, '00109保存引用・再金融0', metric['mean_session_net'], metric['profit_share'],
                 [metric['positive'], metric['negative'], metric['no_trade']],
                 metric['primary_pass'], metric['campaigns'])

    summary = dict(全合格=True, 結果SHA256=hashlib.sha256(content).hexdigest(),
                   source_SHA256=result['source_SHA256'], cases=cases, 保存PRICE=reused,
                   counts=result['counts'], 比較条件=12, 新条件=9, 保存条件=3,
                   新場会計=495, 内部同値場会計=99, 保存場会計=198, 比較場会計=792,
                   PRICE再金融=0, 内部同値再金融=0,
                   結果読取=1, 原入力=0, 台帳=0, 新金融=0, API=0)
    destination.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                           encoding='utf-8', newline='\n')
    print('保存結果SHA256=' + summary['結果SHA256'])


if __name__ == '__main__':
    main()
