"""完成した原因表だけから、次の改善の論理と失う可能性を短く整理する。"""

from pathlib import Path
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import diagnose


def compact_parent(session: str, item: dict) -> dict:
    """
    機能: 事前規則で選んだ損失親の時刻・価格・六点・実RRを短く写す。
    引数: session(str)、item(dict)は既存診断の場名と親。
    返り値: dictは保存値の抜粋。ケースを再選定しない。
    """
    a,b,h,e=item['decision'],item['fill'],item['held'],item['exit']
    return dict(場=session,親=item['parent_id'],方向=item['side'],収支=item['net'],分類=item['category'],
        判断時計=a['clock'],判断気配=[a['bid'],a['ask']],自己六点=a['own_six']['midpoint'],相手六点=a['peer_six']['midpoint'],
        自己ER=a['own_six']['ER'],相手ER=a['peer_six']['ER'],予定価格=a['planned_entry'],停止線=a['rounded_stop'],目標=a['rounded_target'],
        予定RR=a['planned_RR'],実約定=b['actual_price'],実RR=b['actual_RR'],不利約定呼値=b['adverse_gap_ticks'],
        反対TREND初時計=h['mode']['first_opposing_trend_before_exit_decision'],最大順行呼値=h['extrema']['MFE_ticks'],
        最大料込清算額=h['extrema']['best_liquidation_net'],利益返し=h['extrema']['profit_given_back'],
        返済時計=e['fill_clock'],返済価格=e['actual_price'],返済次気配悪化=e['next_quote_deterioration'])


def main() -> None:
    """
    機能: 既存全24原因と全体会計を再集計し、3つの機械的改善候補と反証を保存する。
    引数: なし。小さい完成JSONだけを読む。
    返り値: None。新金融・入力cache・台帳・原板・APIの読取はない。
    """
    common=diagnose.common;path=diagnose.HERE/'全24のR損失場と判断約定及びmode変化.json'
    financial_path=diagnose.RANGE/'finance/results.json'
    details=common.read(path);results=common.read(financial_path)
    assert details['全合格'] and results['全合格']
    references={}
    ids=['R_ONLY_ER40_M1_LIMIT','R_ONLY_ER40_M4_LIMIT','AUTO_ER40_M4_LIMIT','AUTO_ER40_M2_MARKET']
    for ident in ids:
        references[ident]={}
        for symbol in ('TOPIX','NK225'):
            d=details['results'][ident][symbol];r=d['all_R'];whole=results['cases'][ident]['summary'][symbol]
            average_win=r['profit']/r['wins'] if r['wins'] else None
            average_loss=r['loss']/r['losses'] if r['losses'] else None
            break_even=average_loss/(average_win+average_loss) if average_win and average_loss else None
            examples=[compact_parent(session,item) for session,selected in d['selected_sessions'].items() for item in selected['parents']]
            references[ident][symbol]=dict(R親=r,R決済勝率=dict(分子=r['wins'],分母=r['parents'],値=r['wins']/r['parents'] if r['parents'] else None),
                平均利益=average_win,平均損失=average_loss,実測平均額での損益分岐勝率=break_even,
                反対TREND観測群=d['qualifiers'].get('opposing_trend_observed=true'),
                費用後順行利益なし群=d['qualifiers'].get('positive_equity_seen=false'),
                利益を一度観測した群=d['qualifiers'].get('positive_equity_seen=true'),方向別R=d['directions'],
                全体=dict(利益=whole['profit'],損失=whole['loss'],収支=whole['net'],黒字場=whole['positive_sessions'],
                    赤字場=whole['losing_sessions'],無取引場=whole['no_trade_sessions'],活動場=whole['active_sessions'],
                    最良暦日除外収支=whole['without_best_day']['net']),事前規則の損失例=examples)
    assert all(d['qualifiers'].get('target_then_worse=true',{}).get('losses',0)==0
        for symbols in details['results'].values() for d in symbols.values())
    gap_example=details['results']['AUTO_ER40_M2_MARKET']['NK225']['selected_sessions']['2026-10-01_Night']['parents'][0]
    returned_example=details['results']['R_ONLY_ER40_M1_MARKET']['TOPIX']['selected_sessions']['2026-09-29_Day']['parents'][0]
    common.write(diagnose.HERE/'R損失の要点と次の改善部品.json',dict(全合格=True,出典調査='00103',新金融再生=0,
        金融結果参照あり=True,保存入力追加読取=0,原板読取=0,API取得=0,
        要点=[
            '予定の利益/損失比1.25以上は到達確率ではない。ER40/余裕1呼値/指値では平均利益は平均損失より大きいが、TOP33/223・NK36/235しか勝っておらず黒字に足りない。',
            '六点の低ERは直前5分が往復したという過去の形。最後1〜2区間が一方向へ強く走る形も含み、1回のBBO反発だけでは下げ止まり/上げ止まりを確かめられていない。',
            '余裕4呼値の指値は両商品R源が黒字になったが、TOP14親/11活動場、NK35親/17活動場しかない。元狭stopとの入口集合も変わるため、stopを広げた単独効果と断定しない。',
            '反対TRENDを見た後に勝った親も多い。TOP余裕4指値は全14親が反対TRENDを観測し6親が黒字。modeだけで降りると勝ちを切る可能性がある。',
            '全24条件とも、中心到達判断後の次気配が悪化した群には最終赤字親がなかった。この群の約定悪化だけを直しても主要損失を消せない。'
        ],
        比較=references,
        約定悪化の具体例=compact_parent('2026-10-01_Night',gap_example),
        利益返しの具体例=compact_parent('2026-09-29_Day',returned_example),
        次の改善部品=[
            dict(部品='レンジ判定と反発確認を別にする',
                機械案='低ERのRANGEだけで参加せず、直前2つの60秒差が自己・相手とも意図と反対ならそのR新規を見送る。閾値はまず符号だけとし、全24結果から細かく最適化しない。',
                根拠='大きな往復後の現在の一方向進行を、低ERがレンジとして通している具体六点がある。',
                犠牲='底/天井の逆張りは元方向が強い時にも成功し得る。勝ち親が消えるため、同入口の比較と全場寄与が必要。',
                状態='この24比較では未検証。既存二市場方向フィルタとの重複・差分を先に照合する。'),
            dict(部品='指値の受け身約定と押し戻し確認を分ける',
                機械案='初回反発では注文を置かず予定指値を監視する。買いaskが監視線以下/売りbidが監視線以上になった後、別正常行でbid/askがともに再び意図側へ1呼値戻った時を新判断とする。初回H/L/中心は交換せず、固定stop外/既知TREND/J/cutは監視取消、現在market気配で料込RRを再審査して次quote注文。',
                根拠='受け身の買い指値は下げに戻った時ほど約定しやすく、単発反発が壊れた候補の約定が増え得る。これは論理仮説であり現在の市場/指値比較だけでは因果を確定しない。',
                犠牲='有利な指値価格での約定を捨て、確認後のmarket価格は高く/安くなる。RR不足と無取引も増え得る。live指値が到達した同rowで架空に取消す手法とは区別する。',
                状態='この24比較では未検証。追従新規・二段待機の既存試行を照合後、注文がない監視と実発注を分けて検証する。'),
            dict(部品='費用後利益が出た玉だけ保護する',
                機械案='清算BBOが料の呼値切上げに加えて1呼値分を超えたら、費用回収床を固定し、以後その床を不利に緩めない。固定中心目標と初期stopは維持、床到達判断後の次正常quoteで返済。',
                根拠='9/29 TOP09:32:39買4057.5は費用後+7082円を09:32:54に観測した後、09:33:30に-7918円となった。',
                犠牲='中心までの正常な押し戻しで利幅を削り、元黒字も途中で切る。狭余裕1指値の損失主群は一度も料込黒字へ到達しておらず、この部品だけでは救えない。',
                状態='利益追尾自体には既存失敗の知見がある。価格Rの固定中心との組合せはこの比較では未検証。次quoteの利益保証はしない。')
        ],
        限界=[
            '全24の条件ごとの分母。繰り返し現れる親を合算して独立試行数にしない。',
            '最大順行/後のTRENDは事後診断。新規時にその未来が見えたとは扱わない。',
            '相手市場TRENDはR意図との逆であって、自己と相手の同時行為者の焦りを直接測ったものではない。',
            '時刻はCurrentPriceTimeの代理。真の到着時計・遅延ではない。6点は全経路を保証せず、大型BBOをmini/microへ代用。'
        ],
        SHA256={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in (Path(__file__),path,financial_path)}))
    print('R損失の要点と3改善部品を保存、金融再生0',flush=True)


if __name__=='__main__':main()
