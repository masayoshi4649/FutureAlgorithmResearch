"""新十二条件の保存結果を一度読み、全場平均と主判定を小射影へ保存する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 完了した792口座の小結果から主基準・実容量・除外後の数値を抜き出す。
    引数: なし。保存結果JSONだけを読み、原入力と実注文台帳を読まない。
    返り値: None。金融再生を行わず、12条件の短い判定一覧を表示する。
    """
    result_path = HERE / 'engine/finance/結果.json'
    destination = HERE / '十二条件の主判定と全場平均の小射影.json'
    assert not destination.exists(), 'この目的の読取を自動で反復しない。'
    content = result_path.read_bytes()
    result = json.loads(content.decode('utf-8-sig'))
    assert result['全合格'] and result['source開始終端一致']
    assert result['counts'] == {'既input一読': 33, '価格票準備口座': 66, '新account金融': 792}
    assert len(result['configs']) == 12 and len(result['sessions']) == 33
    cases = {}
    for config in result['configs']:
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
            print(json.dumps(dict(条件=cid, 商品=symbol, 全場平均=round(economy['mean_session_net_yen'], 2),
                金額利益割合=stability['profit_share'], 黒赤無=[stability['positive_sessions'],
                stability['losing_sessions'], stability['no_trade_sessions']],
                主条件=stability['all_economic_targets'], 親数=economy['parent_count']), ensure_ascii=False))

    # ----------------------------------------
    # 抜き出した数値を再金融の証拠とせず、元結果の指紋へ結ぶ。
    summary = dict(全合格=True, 結果SHA256=hashlib.sha256(content).hexdigest(),
                   source_SHA256=result['source_SHA256'], cases=cases, counts=result['counts'], 結果読取=1,
                   原入力=0, 台帳=0, 新金融=0, API=0)
    destination.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                           encoding='utf-8', newline='\n')
    print('保存結果SHA256=' + summary['結果SHA256'])


if __name__ == '__main__':
    main()
