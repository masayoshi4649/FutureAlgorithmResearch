"""部品と統合の確定集計から、比較範囲を明示した日本語所見を作る。"""

from pathlib import Path

import replay_parts as replay

HERE=Path(__file__).resolve().parent


def read(name: str) -> object:
    """機能: 完了した検証の保存結果を読む。

    引数: name(str)。返り値: JSONの内容(object)。
    """
    return replay.previous.read(HERE/name)


def main() -> None:
    """機能: 同一条件の増減を検算し、主報告用の所見を保存する。

    引数: なし。返り値: なし(None)。損益による追加探索や条件変更はしない。
    """
    assessment=read('integrated_assessment.json')
    assert assessment['全合格'] and read('integration_followup/new/complete.json')['全合格']
    cells=assessment['四セル群'];comparisons=[];additional=[]
    for quantity in ('A0','C01','F50','F50_NONE'):
        for suffix in ('','__M080','__M120'):
            for exit_id in ('E10','E11'):
                for period in ('all_symbols','symbols'):
                    for symbol in ('TOPIX','NK225'):
                        base=next(r for r in cells if r['id']==quantity+'__E00'+suffix and r['period']==period and r['symbol']==symbol)
                        value=next(r for r in cells if r['id']==quantity+'__'+exit_id+suffix and r['period']==period and r['symbol']==symbol)
                        comparisons.append(dict(id=value['id'],period=period,symbol=symbol,
                            増益円=value['net_yen']-base['net_yen'],最大下落増減円=value['drawdown_yen']-base['drawdown_yen']))
        base={r['symbol']:r for r in read('integration_followup/new/sessions/'+quantity+'__E00.json.gz')}
        for exit_id in ('E10','E11'):
            for value in read('integration_followup/new/sessions/'+quantity+'__'+exit_id+'.json.gz'):
                old=base[value['symbol']]
                additional.append(dict(id=value['id'],symbol=value['symbol'],
                    増益円=value['net_yen']-old['net_yen'],最大下落増減円=value['drawdown_yen']-old['drawdown_yen']))
    assert len(comparisons)==96 and len(additional)==16
    assert all(r['増益円']>0 and r['最大下落増減円']<=0 for r in comparisons+additional)
    assert not any(r['全12セル合格'] for r in assessment['主窓領域'])
    # ----------------------------------------
    # 代表は旧期間から選んだE10を維持し、追加場で選び直さない。
    labels={'F50__E00':'元出口・50%減量復元','F50__E10':'E10・3ATR後1.5ATR幅','F50__E11':'E11・3ATR後0.75ATR幅'}
    rows=[]
    for identifier,label in labels.items():
        new={r['symbol']:r for r in read('integration_followup/new/sessions/'+identifier+'.json.gz')}
        for symbol in ('TOPIX','NK225'):
            original=next(r for r in cells if r['id']==identifier and r['period']=='all_symbols' and r['symbol']==symbol)
            full=assessment['全14期間'][identifier][symbol]
            assert abs(original['net_yen']+new[symbol]['net_yen']-full['net_yen'])<1e-6
            rows.append([label,'TOPIXミニ' if symbol=='TOPIX' else 'NKマイクロ',
                f"{original['net_yen']:+,.0f}",f"{new[symbol]['net_yen']:+,.0f}",f"{full['net_yen']:+,.0f}",
                f"{full['money_ratio']:.2f}／{full['average_unit_payoff']:.2f}"])
    result=dict(
        検証完了=True,
        主結論='今回、最も一貫した改善は「十分に順行した後の出口短縮」でした。入口の時間幅依存と、途中復元の銘柄差は残りました。',
        統合説明='入口を固定し、途中4方式×出口3方式＝12方式を統合。さらに入口の主方向窓を±20%にした24方式でも比較しました。全13・後7×両銘柄の96対応すべてで、E10/E11は元出口より増益し、最大下落も非増でした。同じ相場を使う対応比較であり、96個の独立標本ではありません。下表は50%減量・回復復元を共通にした実行口座です（金額は円）。',
        表見出し=['方式','銘柄','既知13収支','追加9/29夜収支','全14収支','全14 金額比／1枚平均比'],
        表行=rows,
        時間幅結論='出口の改善は入口の主窓3点で再現し、旧36方式は両銘柄の全13・後7で黒字・1枚平均勝敗比>1でした。ただし「上位利益2組を除いても黒字」まで主窓3点すべてで通った方式は0/12。未達の理由は赤字ではなく、大勝ちへの依存です。',
        追加ナイト結論='追加ナイトでもE10/E11は4途中方式・両銘柄すべてで元出口より増益。ただしNKは全12方式が赤字で、改善は1組に集中し、その1組を除くと増益差は0です。TOPIXは11組中3組の改善。毎場の安定黒字を確かめたとは言えません。',
        採否='出口部品はE10を次の比較基準に採用し、E11を強い短縮の対照として残します。E11は今回の総収支が上でも、既知前6のNKでは減益するため優越とは断定しません。入口はH019を暫定維持、EMAの単純な前場引継ぎは不採用。途中復元は一律必須とせず、復元なしも残します。状況を見て後から有利な方式へ切り替える裁量は、この統合成績に含めていません。',
        検証区分=[
            ['入口の方向','26入口×3管理。主窓・短期窓・相手確認を分解。全発火と実初回の先行価格を別集計。','追跡新規が良い機会を選ぶ因果効果は未確定。同じ準備機会から即時・固定逆指値・追跡を比較する余地。'],
            ['入口の開始直後','EMA履歴引継ぎ12×3管理は減益。各場初期化では主方向開始が約1時間遅い構造を確認。','単純引継ぎ以外の休場ギャップ処理・ATR暖機・開始直後専用ルール。早く入れるだけでは増益にならない。'],
            ['途中の枚数','減量開始2×割合2×復元3＋固定の13条件。信号復元・時計復元・復元なしを同条件で比較。','新出口と初回枚数を超える増玉、独立ドテン、回復方式の自動選択の追加価値。今回の統合は4方式それぞれ固定。'],
            ['出口','同初回102組×13診断、途中と同期した36方式。部分利確・追跡・期限の除去と幅変更、上下対称の人工反例。','他系統の入口にも共通する優位性、新出口で待たず再入場する効果、初動逆行の削減。短縮だけで全ては解決しない。'],
            ['板の情報','過去にOFI、補充代理、出来高通過、距離別・価格帯の変化、両市場を個別比較。現有望部品は主に価格条件。','板読み一般の否定は不可。全行から価格帯も生成し直す方式は未検証。取消・約定・隠れ補充・他者の意図は原本だけでは特定不可。'],
            ['統合と追加ナイト','固定12方式で各セッションの全原本行を再生。全返済・枚数上限・現金と建玉・未来改変・途中切断を検査。','完全未見の複数期間、長期一方向相場や構造変化での安定性。追加ナイトの一部既読と繰返し探索による選択偏りは残る。'],
            ['データと実行','保存板の行順・代理公開時刻で因果性を検査。現在API追加取得0、費用0・指定価格約定。','実受信時刻・待ち行列・実約定の再現。この統合12方式の注文伝達遅延感度は未実施（従来方式では別途実施済み）。']
        ],
        出口対応差=comparisons,
        追加出口対応差=additional,
        独立標本扱い=False,
        代表方式='F50__E10',
        追加結果で代表変更=False
    )
    replay.save(HERE/'統合所見.json',result)
    print('旧96対応・追加16対応の増益と最大下落非増を検算。部品の採否と未検証範囲を保存。',flush=True)


if __name__=='__main__':main()
