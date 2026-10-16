"""一部利確の独立会計結果から、確保と取り逃しを対にして短く記述する。"""

import hashlib
from pathlib import Path
from diagnose import ROOT, HERE, read, save, clock


def compact_example(example):
    """
    機能: 同じ入口の代表例を、実際の部分返済と残玉の返済へ平易に分ける。
    引数: example (dict)。
    返り値: dict。原本の代理時計であり真の受信時計とは呼ばない。
    """
    result={k:v for k,v in example.items() if not isinstance(v,list)}
    for label in ('元返済脚','新返済脚'):
        result[label]=[dict(枚数=t['枚数'],返済時刻=clock(t['返済時刻']),
            返済値=t['返済値'],理由番号=t['理由'],料金配賦後収支=t['収支']) for t in example[label]]
    return result


def main():
    """
    機能: 全八条件と固定主仮説の利益確保・旧利益消失を短い数値根拠へまとめる。
    引数: なし。
    返り値: None。選抜を変更せず、独立会計済みの保存結果だけを読む。
    """
    source=HERE/'全8部分確保条件の同入口差分と犠牲利益.json'
    data=read(source);proof=read(HERE/'全8部分確保条件の独立会計.json')
    assert proof['全合格'] and proof['条件数']==16
    models={}
    for model,packet in data['モデル別'].items():
        main=next(r for r in packet['全8条件'] if r['固定主仮説'])
        base=next(r for r in packet['全8条件'] if r['条件']=='Q00_B0')
        products={}
        for symbol in ('TOPIX','NK225'):
            old=base['期間別']['全30'][symbol]['集計']
            new=main['期間別']['全30'][symbol]
            part=new['実際の先行返済があった組'];mapping=new['親組対応']
            assert mapping['同入口数']==mapping['元組数']==mapping['新組数']
            products[symbol]=dict(元GU=old,部分確保40パーセント=new['集計'],
                全額差=new['元GUとの差'],買売=new['買売'],
                全て入口一致=True,入口一致数=mapping['同入口数'],
                旧黒字の利益変化=mapping['内訳']['同入口の旧黒字'],
                旧赤字の損失変化=mapping['内訳']['同入口の旧赤字'],
                部分確保実施組数=part['同入口で先行返済があった親組数'],
                先行分の配賦後利益合計=part['先行分の配賦後利益合計'],
                先行利益があっても最終赤字=part['先行利確しても親組赤字の件数'],
                改善組数=part['改善組数'],悪化組数=part['悪化組数'],
                最大の旧利益取り逃し=compact_example(part['最も旧利益を失った例'][0]),
                最大の損失軽減=compact_example(part['最も確保に寄与した例'][0]),
                場別改善={k:v for k,v in main['全30場差'][symbol].items() if k!='全30差額'},
                期間別={p:{k:main['期間別'][p][symbol]['集計'][k] for k in (
                    'net','campaign_profit_share','positive_sessions','max_drawdown','best_session_removed')}
                    for p in ('前16','後14')})
        table=[dict(条件=r['条件'],商品別={s:dict(**r['期間別']['全30'][s]['集計'],
            純収支対最大下落比=r['期間別']['全30'][s]['集計']['net']/r['期間別']['全30'][s]['集計']['max_drawdown'])
            for s in ('TOPIX','NK225')}) for r in packet['全8条件']]
        floor=[dict(商品=r['商品'],差=r['差'],
            旧黒字の利益変化=r['親組対応']['内訳']['同入口の旧黒字'],
            旧赤字の損失変化=r['親組対応']['内訳']['同入口の旧赤字'])
            for r in packet['親組床だけの有無比較'] if r['元']=='Q40_B0' and r['期間']=='全30']
        models[model]=dict(全8条件=table,固定主仮説の結果=products,先行40パーセントへの親組床追加=floor)
    save('部分確保改修の独立解釈.json',dict(主仮説='Q40_B0',選抜変更=False,
        結論=[
            '一部だけ先に利確して残りを広く保有する方式は、全量を細かく出入りさせる方式より元GUの黒字を保った。ただし元GUを上回る改修にはならなかった。',
            '観測価格の40%先行版はTOPIX49万1779円・日経17万2960円。元GUより12万8950円・4万7900円減り、最大下落は2万4517円・1万3115円減った。収益と下落の交換であり、全面的改善ではない。',
            '入口はTOPIX136組・日経142組すべて元GUと同一。追加回転の問題を除外して出口だけを比較できた。手数料差はTOPIX50円減・日経同額なので、今回の収支低下は手数料増が原因ではない。',
            '旧赤字を軽くした効果はTOPIX25万0029円・日経10万4000円だが、旧黒字の取り逃し37万8979円・15万1900円の方が大きかった。両商品65組で先行利確し、そのうち各22組は残玉を含めると最終赤字だった。',
            '40%先行版は前16・後14それぞれ両商品で黒字だが、後14の日経は最大利益一場を除くと3300円赤字。全場安定や80%の金額利益割合は達成していない。',
            '親組を料金込み0円へ止める床を40%先行版に足すと、さらにTOPIX15万0011円・日経1万9000円減った。TOPIXの最大下落も4002円増えたため、床を置けば総体の安定性も必ず増すとはいえない。',
            '20・40・60%の先行返済は観測価格の両商品で元GUより収支が低い。黒字を保ったことは追加出口の優位ではなく、元の入口と広い残玉が持つ利益を一部残した結果として読む。'
        ],モデル別=models,
        制約=['全30場は既知。前16・後14は説明上の分割であり、今回の未知将来検証ではない。',
            '主評価の観測価格はCurrentPriceであり売買気配ではない。指定価格は別の理想化した約定感度として表示する。',
            '旧黒字だった将来結果は診断にのみ利用。実際の部分返済で、その後の大勝ちを事前に知って選別したわけではない。'],
        根拠SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
        監査器SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    print('一部確保の独立解釈を保存',flush=True)


if __name__=='__main__':
    main()
