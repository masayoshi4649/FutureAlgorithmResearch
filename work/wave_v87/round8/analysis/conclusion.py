"""保険十三条件の全額診断から、共通改善とリスクの得失だけを短く保存する。"""
from pathlib import Path
import json
import numpy as np

HERE=Path(__file__).resolve().parent
ROUND=HERE.parent


def read(path):
    """
    機能: 保存済みの有限値JSONを読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    """
    機能: 条件を選び直さず、主案・全対照・前段リスク候補の得失をまとめる。
    引数: なし。
    返り値: None。新しい売買計算は行わない。
    """
    data=read(HERE/'逆行保険の全額差分と支持確認の分解.json')
    matrix=[];results={}
    for model in ('observed','specified'):
        for path in sorted((ROUND/model/'results').glob('*.json')):
            result=read(path);ident=result['config']['id'];results[model,ident]=result
            for symbol in ('TOPIX','NK225'):
                metric=result['periods']['全30'][symbol]
                own=next(x for x in data['期間成績'] if x['model']==model and x['id']==ident and x['symbol']==symbol and x['period']=='全30')
                matrix.append(dict(model=model,id=ident,symbol=symbol,収支=metric['net'],最大下落=metric['max_drawdown'],
                    黒字場=metric['positive_sessions'],金額利益割合=metric['cycle_profit_share'],
                    追加単独=own['追加単独'],追加料金前=own['追加料金前'],追加料金=own['追加料金'],
                    後14最大一場除外=result['periods']['後14'][symbol]['best_session_removed']))
    main_id='I_P50_R50_C1'
    main_causes=[x for x in data['分類別'] if x['id']==main_id and x['period']=='全30']
    main_periods=[x for x in data['期間成績'] if x['id']==main_id]
    pair_summary=[]
    for row in data['支持確認の対照']:
        if row['period']!='全30':continue
        item={k:row[k] for k in ('model','symbol','価格条件','支持条件','差額')}
        item['価格だけ件数']=row['価格だけ']['追加単独']['件数']
        item['支持確認件数']=row['双方支持']['追加単独']['件数']
        item['内訳']=[{k:v for k,v in part.items() if k!='対応した建値返済'} for part in row['内訳']]
        pair_summary.append(item)
    examples=[]
    for symbol,session,cid in (('TOPIX','2026-09-29_Night',1),('NK225','2026-09-24_Night',5)):
        pair=[x for x in data['全親組'] if x['model']=='observed' and x['symbol']==symbol and x['session']==session and x['campaign']==cid and x['id'] in ('I_P50_R50_C0',main_id)]
        examples.append(dict(symbol=symbol,session=session,組=cid,比較=pair))
    ages=[]
    for symbol in ('TOPIX','NK225'):
        rows=[x for x in data['全親組'] if x['model']=='observed' and x['id']==main_id and x['symbol']==symbol and x['sat_active']]
        for market in ('自己','相手'):
            values=[x['保険入口根拠']['公開元'][market]['判断時点の公開後代理秒数'] for x in rows]
            ages.append(dict(symbol=symbol,市場=market,中央値=float(np.median(values)),
                百分位95=float(np.percentile(values,95)),最大=float(max(values))))
    previous=[]
    for ident in ('C_GU','C_H05_S25'):
        result=read(ROUND.parent/'round7/observed/results'/(ident+'.json'))
        for symbol in ('TOPIX','NK225'):
            q=result['periods']['全30'][symbol]
            previous.append(dict(id=ident,symbol=symbol,収支=q['net'],最大下落=q['max_drawdown'],
                黒字場=q['positive_sessions'],金額利益割合=q['cycle_profit_share']))
    output=dict(結論=[
        '逆行を待つ保険を12条件試したが、両商品とも元GUの料金後収支を増やす条件は無かった。指定線モデルでも同様。主案はTOPIXを悪化させ、NKは全体で微増だが後14では赤字差分。',
        '主案のTOPIX追加損失120,956円は料金前でも82,500円の損失で、費用だけが原因ではない。元玉が最終黒字になる49組の保険合計は175,482円を失い、そのうち38組が初期停止だった。元玉赤字43組での救済54,526円を上回った。',
        '双方支持の確認は主案の取引を各商品3組しか減らさず、TOPIX58組/NK59組の入口を遅らせる効果が中心だった。同じ狭い停止を遅い建値へ置き直すため、その後の小さな戻りで早く止まり、先に入った保険の利益を取り逃した例がある。',
        'ただし遅延や既通過は一律に悪いわけではない。TOPIXの既通過52組は101,736円の赤字だが、NKの既通過52組は13,560円の黒字。全6対照で支持確認の改善方向は銘柄・準備幅・モデルにより混在した。',
        '準備0・逆行0.5・双方支持は両商品の最大下落を減らし、NK収支も増やすが、TOPIX収支を153,086円減らす。共通の収益改善として昇格せず、保険料と下落削減の交換として残せる参考対照。',
        '前段C_H05_S25は独立のリスク候補として維持する。TOPIXは収支15,128円減で最大下落48,077円減、NKは収支460円減で最大下落435円減。今回主案より良い点を保持するが、全日安定・利益割合8割の達成とはしない。'],
        限界='全30場は既知。元玉の損益・時価は全条件不変で、差額は保険全損益と一致。利益・損失をともに集計し、事後の元玉最終結果や最悪例を新規判定には使っていない。公開後代理秒数は通信遅延ではない。',
        全条件=matrix,主案期間=main_periods,主案原因=main_causes,支持確認全6組=pair_summary,
        具体例=examples,主案支持公開後の代理秒数=ages,前段リスク候補=previous)
    (HERE/'逆行保険の短い原因結論.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('共通改善なし・リスク交換を分離して結論を保存しました')


if __name__=='__main__':main()
