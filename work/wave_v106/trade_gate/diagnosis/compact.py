"""完成した診断だけを短い結論と代表具体時刻へ整理する。"""

import json
from pathlib import Path

import analyze


HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 事後順位の首位でも未達であることを、金額/場数/具体seqへ簡潔に整理する。
    引数: なし。
    返り値: None。既診断JSONだけを読み、新金融/台帳/入力は再読しない。
    """
    a=analyze.read(HERE/'全36の安定性とscope寄与の小結.json')
    b=analyze.read(HERE/'全36最悪3場の入口票と費用及び逃した利益.json')
    chosen=a['selected_descriptive_id'];results=a['results'];summary={}
    examples={}
    for symbol in ('TOPIX','NK225'):
        value=results[chosen][symbol]
        summary[symbol]={k:value[k] for k in ('profit','loss','net','profit_share','positive_sessions','losing_sessions','no_trade_sessions','positive_active_rate','median_active_net','without_top3_net','買売','C_R')}
        examples[symbol]=[]
        for day in sorted(b['details'][chosen][symbol],key=lambda r:r['net']):
            losers=sorted([r for r in day['actual_trades'] if r['net']<0],key=lambda r:r['net'])
            representative=losers[0] if losers else None
            examples[symbol].append(dict(session=day['session'],net=day['net'],baseline_net=day['base_net'],five_contributions=day['five_contributions'],
                representative_loss={k:representative[k] for k in ('source','side','net','decision','entry','exit','category','contemporaneous_votes','fees','BBO_cost_relative_to_mid','best_liquidation_net','profit_given_back')} if representative else None,
                removed_profits=[dict(net=r['baseline_net'],cause=r['cause'],decision=r['trade']['decision'],contemporaneous_votes=r['trade']['contemporaneous_votes'])
                    for r in day['removed_baseline_trades'] if r['was_profit']],
                new_later=[dict(net=r['trade']['net'],decision=r['trade']['decision'],cause=r['cause']) for r in day['new_later_trades']]))
    target=dict(全合格=True,description='元二市場AUTOを保ち、直近取引更新の自己方向票をR/C/両方へ確認する36対照。',
        displayed_conditions=36,displayed_accounts=2376,actual_accounts=1129,economic_reused_accounts=1247,
        both_total_positive=sum(all(v[s]['net']>0 for s in ('TOPIX','NK225')) for v in results.values()),
        both_profit_share_80=sum(all(v[s]['profit_share'] is not None and v[s]['profit_share']>=.8 for s in ('TOPIX','NK225')) for v in results.values()),
        both_without_top3_positive=sum(all(v[s]['without_top3_net']>0 for s in ('TOPIX','NK225')) for v in results.values()),
        chosen_descriptive_id=chosen,chosen_description='反発入口だけ直近10代理秒の自己取引更新を確認。元AUTO、帯外2呼値停止・成行新規。事後記述首位で、採用ではない。',
        summary=summary,five_contributions=a['diagnosis'][chosen],worst3=examples,
        結論=['両商品総黒字は9条件あったが、両80%及び両上位3除外黒字は0。小利益毎場の解はまだ得られていない。',
            '当時Last/出来高の方向票が完全一致でも即逆行する実例があり、直前の攻撃方向をその後の持続保証へ変換できない。',
            '首位のworst場にはC側の利益返しと無順行が残る。Rだけの見送りでC損失全体は直らない。',
            '失った基準利益はTOP82492円/NK43240円。回避損失は65426円/79840円で、拒否は利益も除く。'],
        限界='全33既知・同相場36表示の事後診断。票はLast対直前BBOの代理。価格時計は受信時計ではなく、現在Nightは未読。',
        根拠={n:analyze.digest(HERE/n) for n in ('全36の安定性とscope寄与の小結.json','全36最悪3場の入口票と費用及び逃した利益.json')},
        金融再生=0,台帳再読=0,input再読=0,API取得=0,登録source変更=0)
    analyze.write('取引更新確認36の簡潔な結論と赤字3場.json',target)
    print(analyze.digest(HERE/'取引更新確認36の簡潔な結論と赤字3場.json'))


if __name__=='__main__':main()
