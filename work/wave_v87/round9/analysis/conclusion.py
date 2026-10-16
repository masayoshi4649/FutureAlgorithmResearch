"""初期停止を広げた得失を、共通改善と一部救済を混同せず短く記録する。"""
from pathlib import Path
import json

HERE=Path(__file__).resolve().parent
ROUND=HERE.parent


def read(path):
    """
    機能: 保存された日本語JSONを読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    """
    機能: 全対応診断から、固定主案の改善額と悪化額・初期リスクを取り出す。
    引数: なし。
    返り値: None。新しい売買再生やパラメータ選択は行わない。
    """
    source=read(HERE/'同じ入口の停止価格と返済差の全分解.json')
    comparisons=[]
    for symbol in ('TOPIX','NK225'):
        row=next(x for x in source['停止基準の全対応比較'] if x['model']=='observed' and x['symbol']==symbol
            and x['period']=='全30' and x['元条件']=='K_P50_C1_S0' and x['新条件']=='K_P50_C1_S2')
        better=[x for x in row['全対応'] if x['新収支']>x['元収支']]
        worse=[x for x in row['全対応'] if x['新収支']<x['元収支']]
        comparisons.append(dict(symbol=symbol,差額=row['差額'],改善件数=len(better),悪化件数=len(worse),
            不変件数=len(row['全対応'])-len(better)-len(worse),改善合計=sum(x['新収支']-x['元収支'] for x in better),
            悪化合計=sum(x['新収支']-x['元収支'] for x in worse),料金差寄与=row['料金差寄与'],
            元玉又は保険勝敗別=[x for x in row['同値又は旧勝敗別'] if x['分類']!='初期線同値']))
    matrix=[]
    for model in ('observed','specified'):
        for path in sorted((ROUND/model/'results').glob('*.json')):
            result=read(path)
            for symbol in ('TOPIX','NK225'):
                q=result['periods']['全30'][symbol]
                matrix.append(dict(model=model,id=result['config']['id'],symbol=symbol,収支=q['net'],
                    最大下落=q['max_drawdown'],黒字場=q['positive_sessions'],金額利益割合=q['cycle_profit_share'],
                    後14収支=result['periods']['後14'][symbol]['net'],後14最大一場除外=result['periods']['後14'][symbol]['best_session_removed']))
    examples=[]
    for symbol,session,cid in (('TOPIX','2026-09-29_Night',6),('NK225','2026-09-22_Night',0)):
        pair=[x for x in source['全親組'] if x['model']=='observed' and x['symbol']==symbol and x['session']==session
            and x['campaign']==cid and x['id'] in ('K_P50_C1_S0','K_P50_C1_S2')]
        examples.append(dict(symbol=symbol,session=session,組=cid,対応=pair))
    s1s3=[{k:v for k,v in x.items() if k!='全対応'} for x in source['停止基準の全対応比較']
        if x['period']=='全30' and x['元条件'].endswith('_S1') and x['新条件'].endswith('_S3')]
    output=dict(結論=[
        '主案の構造停止S2は同じ入口の旧S0よりTOPIXを82,500円改善したが、NKを74,000円悪化させた。新しい停止12条件のいずれも、両商品で同時に旧S0の収支を改善しない。',
        'TOPIXは25組の改善410,000円が36組の悪化327,500円を上回った。NKは12組の改善83,000円より44組の悪化157,000円が大きかった。残る31/33組は旧保険の勝ちで損益も同じ。新規も手数料も同じなので、差は全て停止後の返済価格の違いである。',
        'TOPIXの元玉赤字43組では保険による救済が197,500円増えた一方、元玉黒字49組では保険損失が115,000円増えた。NKは元玉赤字33組の救済増が5,000円だけで、元玉黒字56組の保険損失増79,000円を補えなかった。今回の価格経路で確認した差であり、銘柄固有の恒久的性質とは断定しない。',
        '構造停止S1と固定0.5ATR停止S3は、指定モデル・確認なしでは準備0と0.5の両方で全新規の停止線も返済も同じ。主案の観測モデルでもTOPIX66/92、NK59/89組が同じ。構造という名前自体に追加の予測力がある結果ではない。',
        '主案の初期停止距離中央値は両商品とも約0.30から0.70ATRへ増加した。名目料金込損失中央値はTOPIX5,418円から15,418円、NK3,220円から6,220円。保険勝率は31/92から54/92、33/89から45/89へ上がったが、NK収支は悪化した。勝ち数増加を損小利大の達成と呼ばない。',
        '主案の全30収支はTOPIX582,273円/NK154,280円で元GU620,729円/220,860円を双方下回る。最大下落はTOPIX191,459円へ減るがNK141,405円へ増える。旧C_H05_S25のリスク候補は保持し、新主案への共通昇格はしない。'],
        主案差分=comparisons,全条件=matrix,
        主案リスク=[x for x in source['初期リスク'] if x['id'] in ('K_P50_C1_S0','K_P50_C1_S1','K_P50_C1_S2','K_P50_C1_S3') and x['period']=='全30'],
        S1と固定半ATRの分離=s1s3,具体例=examples,
        限界='全30場は既知。原本順・CurrentPriceTime代理時計であり、実通信時計を再現したものではない。元玉最終勝敗と未来経路は事後診断だけに用い、入口へ戻していない。初期線までの円リスクは約定保証ではない。')
    (HERE/'構造停止と単なる幅拡大の短い結論.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('構造停止の得失と幅拡大の分離を保存しました')


if __name__=='__main__':main()
