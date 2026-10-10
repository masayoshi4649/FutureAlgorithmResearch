"""既存の固定12方式を、勝率の単位と損小利大から再評価する。"""

from html import escape
import gzip
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00041_入口途中出口の分解検証'


def read(path: Path) -> object:
    """機能: 保存済みJSON又は圧縮JSONを読み出す。

    引数: path(Path)。返り値: 内容(object)。
    """
    raw=path.read_bytes()
    return json.loads((gzip.decompress(raw) if path.suffix=='.gz' else raw).decode('utf-8'))


def ratio(a: float, b: float) -> float | None:
    """機能: 分母がある場合だけ比率を返す。

    引数: a(float)、b(float)。返り値: 比率(float|None)。
    """
    return a/b if b else None


def table(headers: list[str], rows: list[list]) -> str:
    """機能: 再評価値を暗色HTML用の表へ変換する。

    引数: headers(list[str])、rows(list[list])。返り値: HTML(str)。
    """
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def main() -> None:
    """機能: 約8割の勝ちと利益損失比を別集計し、元結果を変更せず補足を作る。

    引数: なし。返り値: なし(None)。新しい売買再生や条件探索は行わない。
    """
    assessment=read(HERE/'integrated_assessment.json');assert assessment['全合格']
    records=[];sources={}
    for identifier,markets in assessment['全14期間'].items():
        sessions=[]
        for folder in ('exit_integration/sessions','integration_followup/new/sessions'):
            path=HERE/folder/(identifier+'.json.gz');sources[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
            sessions+=read(path)
        for symbol,value in markets.items():
            rows=[r for r in sessions if r['symbol']==symbol]
            assert len(rows)==len({r['session'] for r in rows})==14
            wins=[r['net_yen'] for r in rows if r['net_yen']>0]
            losses=[-r['net_yen'] for r in rows if r['net_yen']<0]
            count=sum(r['cycles'] for r in rows);cw=sum(r['cycle_wins'] for r in rows);cl=sum(r['cycle_losses'] for r in rows)
            assert len(wins)==value['win_sessions'] and count==value['cycles'] and cw==value['cycle_wins'] and cl==value['cycle_losses']
            for field in ('gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units'):
                assert abs(sum(r[field] for r in rows)-value[field])<1e-7
            pu=value['profit_units'];lu=value['loss_units'];profit=value['gross_profit_yen'];loss=value['gross_loss_yen']
            unit_payoff=ratio(profit/pu,loss/lu)
            cycle_payoff=ratio(sum(r['cycle_profit_yen'] for r in rows)/cw,sum(r['cycle_loss_yen'] for r in rows)/cl)
            assert abs(unit_payoff-value['average_unit_payoff'])<1e-10
            assert abs(cycle_payoff-value['average_cycle_payoff'])<1e-10
            records.append(dict(id=identifier,symbol=symbol,セッション数=14,黒字数=len(wins),赤字数=len(losses),
                同値セッション数=14-len(wins)-len(losses),セッション勝率=len(wins)/14,
                一連取引数=count,勝ち取引数=cw,負け取引数=cl,同値取引数=count-cw-cl,一連取引勝率=cw/count,
                総利益円=profit,総損失円=loss,収支円=value['net_yen'],金額比=ratio(profit,loss),
                勝ち枚数=pu,負け枚数=lu,一枚平均勝敗比=unit_payoff,一連取引平均勝敗比=cycle_payoff,
                平均黒字場円=sum(wins)/len(wins),平均赤字場円=sum(losses)/len(losses),
                最大赤字場円=max(losses),途中時価を含む最大下落円=value['drawdown_yen']))
    # ----------------------------------------
    # 14場の約8割は11/14=78.6%であり、厳密な80%以上とは分ける。
    near=[];strict=[];trade=[]
    for identifier in assessment['全14期間']:
        pair=[r for r in records if r['id']==identifier]
        assert len(pair)==2
        base=all(r['収支円']>0 and r['一枚平均勝敗比']>1 for r in pair)
        if base and all(r['黒字数']>=11 for r in pair):near.append(identifier)
        if base and all(r['セッション勝率']>=.8 for r in pair):strict.append(identifier)
        if base and all(r['一連取引勝率']>=.8 for r in pair):trade.append(identifier)
    assert near==['A0__E10','C01__E10','F50_NONE__E10','F50_NONE__E11']
    assert not strict and not trade
    labels={'A0__E10':'数量調整なし＋1.5ATR追跡','C01__E10':'25%減量・復元＋1.5ATR追跡',
        'F50_NONE__E10':'50%減量・復元なし＋1.5ATR追跡','F50_NONE__E11':'50%減量・復元なし＋0.75ATR追跡'}
    displayed=[];all_rows=[]
    for row in records:
        values=[labels.get(row['id'],row['id']),'TOPIXミニ' if row['symbol']=='TOPIX' else 'NKマイクロ',
            f"{row['黒字数']}/14（{row['セッション勝率']:.1%}）",f"{row['収支円']:+,.0f}",
            f"{row['一枚平均勝敗比']:.2f}",f"{row['一連取引勝率']:.1%}",f"{row['途中時価を含む最大下落円']:,.0f}"]
        all_rows.append(values)
        if row['id'] in near:displayed.append(values)
    lead=[r for r in records if r['id']=='F50_NONE__E11']
    loss_rows=[[r['symbol'],f"{r['平均黒字場円']:,.0f}",f"{r['平均赤字場円']:,.0f}",f"{r['最大赤字場円']:,.0f}",
        f"{r['勝ち取引数']}/{r['一連取引数']}（{r['一連取引勝率']:.1%}）",f"{r['一連取引平均勝敗比']:.2f}"] for r in lead]
    prior=BeautifulSoup((OUT/'分解と結論.html').read_text(encoding='utf-8'),'html.parser');css=prior.style.string
    headers=['方式','銘柄','黒字セッション','全14収支円','1枚平均勝敗比','一連取引勝率','最大途中下落円']
    body=f'''<p><a href="分解と結論.html">部品別検証へ</a> ／ <a href="全条件の損益.html?method=F50_NONE__E11">代表候補の全損益</a></p>
<h1>約8割の勝ちと、損小利大での再評価</h1>
<p class="box"><strong>セッション単位で約8割の黒字が目安なら、有望候補はあります。毎回勝つことを採用条件にはしません。</strong></p>
<p>セッション勝率と取引勝率を分けて再集計しました。14場では11勝が78.6%、12勝が85.7%。「8割前後」の比較として11勝以上を掲載し、厳密な80%以上とは区別します。</p>
<h2>今回の基準に近い4候補</h2>
{table(headers,displayed)}
<p>費用0・指定価格約定。TOPIXミニ初回5枚／上限10枚、NKマイクロ初回10枚／上限20枚。価格が3ATR順行した後に、表の追跡幅へ短縮します。全返済はセッション内です。</p>
<p><strong>この観点ではF50_NONE__E11を有望候補として扱えます。</strong> 順行後の悪化で50%減量し、減らした枚数を戻さず、伸びた利益を狭い追跡幅で守る方式です。復元後の再逆行による追加損失を避ける一方、再上昇時の数量は少なくなります。</p>
<h2>勝つ頻度と、負けの大きさは別に確認</h2>
{table(['銘柄','平均黒字場円','平均赤字場円','最大赤字場円','一連取引の勝率','一連取引の平均勝敗比'],loss_rows)}
<p>一連取引は「初回新規から全返済まで」の減量・部分利確・復元をまとめたものです。同値も分母に含めます。この単位では約48%／56%で、8割ではありません。負けより勝ちを大きくし、セッション全体を黒字にする結果です。</p>
<p>1枚平均勝敗比＝（総利益÷勝ち返済枚数）÷（総損失÷負け返済枚数）。場末の小さな赤字と、保有途中の下落も別です。上表の最大途中下落は、含み損益を含む全14場の累積時価から計算しています。</p>
<details><summary>評価基準をどう変更したか</summary>
<p>追加1セッションの赤字だけを理由に、不採用とはしません。「上位利益2組を除いても全時間幅で黒字」は利益集中の参考診断として残し、自動的な不合格条件にはしません。勝率・利益損失比・収支・途中下落を並べて判断します。</p>
<p>元のF50__E10はTOPIX12/14場、NK10/14場が黒字でした。NKの勝つ頻度を重視する場合、50%減量後の復元なしが候補になります。取引単位の8割を求める場合、今回の12方式に達成例はありません。</p></details>
<details><summary>固定12方式の全比較</summary>{table(headers,all_rows)}</details>
<p class="muted">これは保存済みの同じ全14場を、新しく示された評価基準で読み直した結果です。売買条件を変更した新実験や、完全未見の成績ではありません。短い標本での有望性と、今後も8割勝つ保証は区別します。</p>'''
    component='<!--\n[コンポーネント概要]\n本文は既存固定方式の勝率と損益を比較します。details は全方式と基準変更の説明を開閉します。\n取引勝率とセッション勝率を別列に置き、外部通信・売買実行は行いません。\n-->'
    html=f'<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>約8割の勝ちと損小利大</title><style>{css}</style><body>{component}{body}</body></html>'
    (OUT/'8割の勝ちと損小利大.html').write_text(html,encoding='utf-8')
    report=dict(全合格=True,方式数=12,入力口座数=336,評価期間='既存全14セッション',新売買再生=False,
        API追加取得数=0,勝率単位='セッションと初回から全返済の一連取引を別評価',
        セッション約8割候補=near,セッション厳密80以上候補=strict,取引厳密80以上候補=trade,
        候補の選び直し='追加ナイトを含む既存結果をユーザーの新基準で再評価。未見で選んだ候補とはしない。',
        結果=records,参照SHA256=sources,補足HTML_SHA256=hashlib.sha256(html.encode('utf-8')).hexdigest())
    (HERE/'8割基準の再評価.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(方式数=12,約8割候補=near,厳密80以上=strict,取引80以上=trade),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
