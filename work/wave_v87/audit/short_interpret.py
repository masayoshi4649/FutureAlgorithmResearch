"""短期支持の更新が利益へつながったか、固定主と全条件の結果を簡潔に整理する。"""

import hashlib
from pathlib import Path
from diagnose import HERE,read,save


def main():
    """
    機能: 独立会計済みの十条件から固定主二つの成否と料金前後をまとめる。
    引数: なし。
    返り値: None。条件再選抜や損益再生を行わない。
    """
    source=HERE/'全10支持条件の入口変更と料金前後の独立分解.json'
    proof=read(HERE/'全10支持条件の独立会計と直前公開根拠.json')
    assert proof['全合格'] and proof['条件数']==20
    data=read(source);models={}
    for model,packet in data['モデル別'].items():
        table=[];mains=[]
        for result in packet['全10条件']:
            entry=dict(条件=result['条件'],元=result['元条件'],固定主=result['固定主仮説'],期間別={})
            for period,products in result['期間別'].items():
                entry['期間別'][period]={s:dict(集計=v['集計'],元との差=v['同親方式F0との差'],買売=v['買売']) for s,v in products.items()}
            table.append(entry)
            if result['固定主仮説']:
                details={}
                for symbol,value in result['期間別']['全30'].items():
                    matching=value['入口変更の料金前後']
                    assert matching['同行同方向の差']==dict(料金前=0.,料金=0.,料金後=0.)
                    details[symbol]=dict(集計=value['集計'],元との差=value['同親方式F0との差'],
                        同一原本行の親組数=matching['同行同方向の元']['親組数'],
                        同一原本行の収支は完全同額=True,
                        旧入口が消えた側=matching['消失した旧入口'],新しい入口側=matching['追加の新入口'],
                        場別差={k:v for k,v in result['場別差'][symbol].items() if k!='全30差額'})
                mains.append(dict(条件=result['条件'],商品別=details))
        models[model]=dict(全10条件=table,固定主の入口対応=mains)
    observed=data['モデル別']['observed']['全10条件']
    gu=next(r for r in observed if r['条件']=='GU_F0')
    for symbol in ('TOPIX','NK225'):
        for metric in ('net','campaign_profit_share'):
            maximum=max(r['期間別']['全30'][symbol]['集計'][metric] for r in observed)
            assert gu['期間別']['全30'][symbol]['集計'][metric]==maximum
    save('最新支持改修の独立解釈.json',dict(固定主仮説=['GU_F2','P1_F2'],主の差替え=False,
        結論=[
            '最新の30秒支持と追跡極値後の新根拠を使う仕組みは、未来を見ず正しく動いている。しかし今回の主仮説では収益の改善につながらなかった。',
            '観測価格のGU_F2はTOPIX54万8892円・日経21万8400円。旧GUより7万1837円・2460円減り、最大下落は3万1919円・1万4400円増えた。前16/後14は両商品とも黒字だが、後14から最大利益一場を除くと両赤字になる。',
            '狭い追尾と利確後再参加を残したP1_F2はTOPIX25万4086円・日経30万4900円の赤字。元P1より5万5821円・5万4800円悪化し、前16/後14も両商品で赤字だった。',
            'P1_F2は取引を両商品各10組減らし、料金を4179円・2200円節約したが、料金前の収支が6万円・5万7000円悪化した。手数料だけを原因とする説明では足りない。',
            'GU_F2の取引は136→138組、142→145組へむしろ増えた。入口の許可を厳しくしても、準備時点やその後の保有経路が変わるため、取引数が単調に減るとは限らない。',
            '同行同方向で対応できる主二条件の親組は、旧方式とすべて同収支。差は入口時点が変わった取引群にある。ただし原本一行のずれでも対応から外れるため、消失した旧勝ちの総額をそのまま純粋な見送り損失とは呼ばない。',
            '全十条件の観測価格では、支持を改めないGU_F0が両商品の収支と金額利益割合で最高。双方の短期支持を足したF3/F4も共通の収益改善にはならなかった。これで短期支持一般を否定せず、今回の定義では置換根拠が得られなかったと結論する。',
            '全条件とも全30場で取引しており、無取引を勝ちに数えていない。未知将来の保証、毎場黒字、金額利益80%はいずれも確認できていない。'
        ],モデル別=models,
        注意=['同じ入口行と方向を対応し、それ以外を消失・追加へ分けた会計分解。因果的に完全独立な取引機会へ分解したものではない。',
            '前16・後14を含む全30場は既知。固定主は結果で選び直していない。',
            '観測価格はCurrentPriceの代理時計付き記録。指定価格モデルとは別で、売買気配や真の受信時計を再現した数値ではない。'],
        根拠SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
        監査器SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    print('最新支持の独立解釈を保存',flush=True)


if __name__=='__main__':
    main()
