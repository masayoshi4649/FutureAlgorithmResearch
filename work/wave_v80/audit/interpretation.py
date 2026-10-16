"""最終結果の主張を、独立監査済み会計の範囲へ限定する。"""

import json
import numpy as np

from accounts import HERE,WORK,study


def get(folder: str, identifier: str) -> dict:
    """機能: 既存の結果を読み込む。

    引数: folder/identifier(str)。返り値: 保存結果(dict)。
    """
    return study.load(WORK/folder/'results'/f'{identifier}.json')


def main() -> None:
    """機能: 全赤字・回数減・希少事例・鮮度感度の解釈根拠を保存する。

    引数: なし。返り値: なし(None)。追加の手法探索や注文再生はしない。
    """
    selection=study.load(WORK/'最終前半選定.json');comparisons=[];delays=[];strict=[];direct=[]
    for mode,baseid in [(0,'S3_P6_M0_C5'),(1,'S3_P6_M1_C5')]:
        revised=f'A6_P6_M{mode}'
        base=get('final/delay5',baseid);new=get('final/delay5',revised)
        for symbol in ['TOPIX','NK225']:
            old=base['periods']['対象'][symbol];now=new['periods']['対象'][symbol]
            volume=(now['trades']-old['trades'])*old['average_net']
            average=now['trades']*(now['average_net']-old['average_net'])
            assert abs(now['net']-old['net']-volume-average)<1e-6
            assert now['average_net']<old['average_net']
            fields=['net','trades','average_net','profit','loss','profit_share','average_win','average_loss','payoff']
            comparisons.append(dict(商品=symbol,元手法=baseid,改修代表=revised,
                元={k:old[k] for k in fields},改修={k:now[k] for k in fields},
                収支差=now['net']-old['net'],元平均で回数だけ減らした算術差=volume,
                残りの平均変化項=average,
                注意='算術的な回数×平均の分解であり、入口群が異なるので回数削減だけの因果効果ではない。'))
            original_family=f'S6_P6_M{mode}_C30'
            old_same=get('final/delay5',original_family)['periods']['対象'][symbol]
            direct.append(dict(商品=symbol,確認あり手法=original_family,確認なし手法=revised,
                確認あり={k:old_same[k] for k in fields},確認なし={k:now[k] for k in fields}))
    for config in selection['確認条件']:
        ident=config['id']
        for delay in [0,1,5]:
            result=get(f'final/delay{delay}',ident)
            for symbol in ['TOPIX','NK225']:
                a=result['periods']['対象'][symbol]
                assert a['net']<0
                delays.append(dict(手法=ident,商品=symbol,発注遅延秒=delay,
                    全30収支=a['net'],取引数=a['trades'],金額利益割合=a['profit_share'],
                    後14収支=result['periods']['後14'][symbol]['net']))
        result=get('quality_strict3',ident)
        assert not all(result['periods']['対象'][s]['net']>0 for s in ['TOPIX','NK225'])
        strict.append(dict(手法=ident,商品別={s:{k:result['periods']['対象'][s][k] for k in ['net','trades','profit_share','average_net']} for s in ['TOPIX','NK225']}))
    sparse=selection['少数黒字'];assert len(sparse)==4
    same_paths=[]
    for delay in [0,1,5]:
        packets=[study.load(WORK/'final'/f'delay{delay}'/'ledgers'/f'{c["id"]}.pkl') for c in sparse]
        for key in packets[0]:
            for packet in packets[1:]:
                np.testing.assert_array_equal(packet[key]['trades'],packets[0][key]['trades'])
                # 注文方式の識別列以外の価格・数量・時計・決済理由も同じ経済経路。
                cols=[i for i in range(18) if i!=14]
                np.testing.assert_array_equal(packet[key]['orders'][:,cols],packets[0][key]['orders'][:,cols])
        same_paths.append(dict(発注遅延秒=delay,比較口座数=len(packets[0]),四設定の経済的全経路一致=True))
    sparse_data=[]
    sample=get('final/delay5',sparse[0]['id'])
    for symbol in ['TOPIX','NK225']:
        sparse_data.append(dict(商品=symbol,各期間={period:{k:sample['periods'][period][symbol][k] for k in ['net','trades','profit','loss']} for period in ['前16','後14','対象']}))
    result=dict(合格=True,
        結論='今回固定した11代表は全30場・両商品で、0/1/5秒の全てが赤字。広く全ての秒売買が不可能だという証明ではない。',
        訂正すべき表現=[
            '主5秒全30のS3→A6は1組平均の改善が限定的ではなく、成行・上限付きとも両商品で平均収支が悪化。総赤字縮小と平均改善を区別する。',
            'S3→A6は入口思想・確認待ち・休止も変わる代表同士の比較。3秒持続を省く単独効果はS6確認ありとA6を比べる。',
            '初回両黒字4設定は独立な4証拠ではない。全3遅延で決済経路と経済注文が完全一致し、前16はTOPIX1組・NK2組だけ。',
            '0秒でも全代表が赤字だが、同じ判断列ではないので0秒と5秒の差を純粋な遅延コストとは呼ばない。遅延が長い方が有利な法則とも言わない。',
            '厳格鮮度3秒で一方黒字の設定はあるが数組で、両商品共通黒字の代表はない。無取引の0円を利益へ数えない。',
            'M2の対中値差をすべて市場スプレッドと呼ばない。厳格貫通後の元指値約定という代理仮定の負担を含む。',
            'P6の相対的優位から保有120秒が原因と断定しない。利確幅・損切幅も同時に変わる。',
            '最終約定時計の同時刻後続行が多く、現実の0/1/5秒到達や先行関係を証明しない。'],
        S3代表とA6代表の算術分解=comparisons,同一失速思想の確認有無対照=direct,
        最終11代表と三遅延=delays,厳格鮮度=strict,希少四設定の全経路一致=same_paths,希少設定の実取引数=sparse_data,
        最終選定SHA256=study.digest(WORK/'最終前半選定.json'))
    (HERE/'最終数値の解釈と過剰断定の独立レビュー.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(合格=True,全赤字確認口座集計数=len(delays),平均悪化確認組=len(comparisons),希少四設定の全経路一致=same_paths),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
