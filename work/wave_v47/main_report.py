"""入口・途中・出口の結論を短い主報告へまとめ、証拠は別資料へ分ける。"""

from __future__ import annotations

from html import escape
import json
from pathlib import Path

import financial_report as tables
import replay_parts as replay

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=tables.OUT


def yen(value: float) -> str:
    """機能: 円の増減を符号付きで表示する。

    引数: value(float)。返り値: 日本語数値(str)。
    """
    return f'{value:+,.0f}円'


def table(headers: list[str], rows: list[list]) -> str:
    """機能: 引用資料の数値をエスケープした横スクロール表へ変換する。

    引数: headers(list[str])、rows(list[list])。返り値: HTML(str)。
    """
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def main() -> None:
    """機能: 完了した部品検証と統合所見を短い暗色HTMLにして保存する。

    引数: なし。返り値: なし(None)。索引の更新は公表監査後の別工程。
    """
    assessment=tables.read('entry_assessment.json');warm=tables.read('warm_assessment.json')
    mid=tables.read('mid_result.json');exits=tables.read('exit_results.json')
    integrated=tables.read('統合所見.json')
    assert all(x['全合格'] for x in (assessment,warm,mid,exits)) and integrated['検証完了']
    entry_rows=[]
    for code,label in [('M100_S100_P1_C1_D100','1分足EMA15/60本'),('M080_S100_P1_C1_D100','主窓だけEMA12/48本'),
                        ('M120_S100_P1_C1_D100','主窓だけEMA18/72本')]:
        for symbol in ('TOPIX','NK225'):
            row=next(r for r in assessment['期間銘柄セル'] if r['entry']['id']==code and
                r['base_id']=='G150_F50_N1__V000' and r['period']=='all_symbols' and r['symbol']==symbol)
            entry_rows.append([label,symbol,yen(row['net_yen']),yen(row['top2_removed']),f"{row['average_unit_payoff']:.2f}"])
    mid_rows=[]
    for identifier in ('G150_F50_NONE_N1__V000','G150_F50_T120_N1__V000','G150_F50_N1__V000'):
        result=next(r for r in mid['条件別'] if r['id']==identifier)
        label={'none':'復元しない','timer':'120秒後に復元','signal':'回復方向を待って復元'}[result['spec']['policy']['restore_mode']]
        for cell in result['四セル']:
            if cell['期間']!='all_symbols':continue
            p=cell['保存期間集計'];mid_rows.append([label,cell['symbol'],yen(p['net_yen']),f"{p['drawdown_yen']:,.0f}円",f"{p['average_unit_payoff']:.2f}"])
    exit_rows=[]
    for condition in exits['結果']:
        for symbol in ('TOPIX','NK225'):
            value=condition['symbols'][symbol]['全13']
            exit_rows.append([condition['id']+' '+condition['name'],symbol,yen(value['基準差円']),
                yen(value['最大増益一組除外差円']),f"{value['一枚平均勝敗比']:.2f}" if value['一枚平均勝敗比'] is not None else '—'])
    new=tables.read('new_sessions.json')
    new_rows=[]
    for row in new:
        if row['id']!='G150_F50_N1__V000':continue
        new_rows.append([row['symbol'],f"{row['gross_profit_yen']:,.0f}",f"{row['gross_loss_yen']:,.0f}",
            yen(row['net_yen']),f"{row['profit_units']}／{row['loss_units']}",yen(row['追加21時以降時価差分円'])])
    source_prefix='../../work/wave_v47/'
    links=[('入口の事前棚卸し','入口の証拠棚卸し.md'),('全発火の先行価格','forward/先行価格診断の結論.md'),
        ('実初回の先行価格','forward_actual/実初回の先行価格診断.md'),('EMA暖機の結果','暖機入口の経済結論.md'),
        ('途中判断の事前棚卸し','途中判断の証拠棚卸し.md'),('途中判断13条件の結論','途中判断13条件の結論.md'),
        ('出口の事前棚卸し','出口の証拠棚卸し.md'),('出口13条件の結論','出口部品の結論.md'),
        ('出口短縮の人工反例','出口短縮の人工反例.md'),('統合注文の独立レビュー','統合注文の独立レビュー.md'),
        ('追加ナイト24口座の独立確認','追加Night統合の独立事実確認.md'),
        ('全168方式の表示と統合所見の独立確認','全方式表示と統合所見の最終独立レビュー.md')]
    nav='<a href="全条件の損益.html?method=F50__E10">各セッション・各週・全期間の損益</a> ／ <a href="統合版の５分足と売買.html">統合版の５分足と売買</a> ／ <a href="追加ナイトの５分足と売買.html">従来方式の追加ナイト</a> ／ <a href="出口単独の比較.html">出口だけの全比較</a>'
    revised='<p class="box"><strong>評価基準の補足：</strong>「毎回の利益は不要、損小利大で8割前後」という基準で再評価しました。セッション単位なら有望候補があります。<a href="8割の勝ちと損小利大.html">勝率の単位と再評価を見る</a>。以下は変更前の部品検証と、その再現結果です。</p>' if (OUT/'8割の勝ちと損小利大.html').exists() else ''
    body=f'''<a href="../index.html">作業一覧</a><h1>入口・途中判断・出口を分けた検証</h1>
<p class="box"><strong>{escape(integrated['主結論'])}</strong></p>{revised}<p>{nav}</p>
<p class="muted">既知13セッションで部品を比較し、追加9月29日ナイトへ固定条件を適用。TOPIXミニ初回5枚・上限10枚、NKマイクロ初回10枚・上限20枚。費用0・指定値約定・場内返済。</p>
<h2>1．入口：方向判定と注文の成立を分ける</h2>
<p><strong>元の入口は比較基準として維持。時間幅の弱さは残ります。</strong> 26入口×3管理＝78比較。相手確認・短期確認を単純に取り除いても、主窓3点すべての安定条件を通る組合せはありませんでした。</p>
<p>未確定なのは、方向予測と注文待機それぞれの貢献です。単純なEMA履歴引継ぎは改善しませんでした。</p>
<details><summary>方向一致率・時間幅・暖機36比較</summary>
<p>全発火の60分方向一致率はTOPIX53.1%・NK51.8%。追跡新規が成立した初回では68.4%・67.5%でした。後者は60分を評価できる45組・47組の場等重みで、<strong>決済勝率ではありません</strong>。注文待機・取消・保有中の見送りで、参加する機会が変わります。</p>
{table(['入口','銘柄','全13収支','上位利益2組を除いた収支','1枚平均勝敗比'],entry_rows)}
<p>主窓変更にはEMA本数と傾き差分2／3／4本の両方を含みます。短期30秒と途中50%管理は固定。さらにEMAだけ過去場の確定足で暖機する36条件も検証。中央50%管理の収支はTOPIX357,500円・NK90,300円へ低下し、中央3管理はいずれも両銘柄の全13・後7で減益・最大下落拡大。単純な暖機への変更は不採用です。</p>
<p>主窓3点の安定条件：両銘柄の全13・後7で黒字、1枚平均勝敗比&gt;1、上位利益2組を除いても黒字。未達は、この基準を通らなかったという意味で、全条件赤字という意味ではありません。</p></details>
<h2>2．途中判断：減らす効果と、戻す効果は別</h2>
<p><strong>回復を待つ復元は120秒復元より良好。しかし、復元自体の価値には銘柄差がありました。</strong> 到達条件2×減量割合2×復元3＋数量固定＝13条件。NKの50%管理では、復元しない方が収支と最大下落の両方で良好でした。</p>
<details><summary>同じ入口・出口での復元3方式</summary>
{table(['途中判断','銘柄','全13収支','最大下落','1枚平均勝敗比'],mid_rows)}
<p>1.5ATR順行後に50%減量する条件を固定。回復確認は、買いなら上昇を確認して買い戻すため、直後に反転すると復元分が損失になります。数量を戻すことを一律に必須とはしません。</p></details>
<h2>3．出口：伸びた後だけ追跡幅を狭める</h2>
<p><strong>同じ初回102組の比較では、3ATR順行後に追跡幅を3→1.5ATRへ短縮するE10が有望でした。</strong> 元出口よりTOPIX129,000円・NK57,000円増益。前6・後7の両方で、両銘柄とも増益でした。損切り損失の削減ではなく、伸びた組の利益返却を減らす効果です。</p>
<p>部分利確の除去・3.6ATRへの拡幅・360分期限の除去は両銘柄で減益。3ATR到達後0.75ATRへ強く短縮するE11も残し、統合で比較しました。</p>
<p>人工反例でも確認済みです。短縮は順行後の崩れに強い一方、深い押しを経て再び伸びる波では元出口に負けます。初動で逆行する損失には効きません。</p>
<details><summary>出口13条件の対応差</summary>
<p>以下は同じ元建玉からの独立診断です。旧終了後も自身の出口まで追跡し、重複する建玉を実運用口座の収支へ合算していません。統合結果は次章で別表示します。</p>
{table(['出口','銘柄','元出口との差','最大増益1組を除いた差','1枚平均勝敗比'],exit_rows)}</details>
<h2>4．統合：入口・途中・出口を一つの規則で実行</h2>
<p>{escape(integrated['統合説明'])}</p>
{table(integrated['表見出し'],integrated['表行'])}
<p>{escape(integrated['時間幅結論'])}</p><p>{escape(integrated['追加ナイト結論'])}</p>
<p>{escape(integrated['採否'])}</p>
<details><summary>機械的な入口・途中・出口の具体条件</summary>
<ol><li>確定1分足EMA15/60の差が0.15ATR超、EMA60の3本差分が同方向へ0.02ATR超なら主方向開始。EMA差が反対符号になるまで保持。各場EMAを初期化し、開始20分と必要足数を待つ。中央は連続足でも63本と公開遅延が必要。足は開始時刻＋120秒で公開し、相手はさらに60秒遅延。</li>
<li>相手市場も同方向、公開済み中値の30秒変化が同方向へ0.05ATR超なら新規準備。短期根拠は最後の支持から120秒で失効。買いは追跡安値から0.25ATR反発、売りは追跡高値から0.25ATR反落で入る。注文準備は300秒、方向条件がなくなれば取消。初回ATRは準備時の公開済み値を固定。</li>
<li>元出口は初期1ATR相当の組損失条件、2ATR順行で元枚数の半分切捨てを部分利確、1.5ATR順行から3ATR幅で追跡。E10は3ATR順行後だけ1.5ATR幅へ短縮、E11は0.75ATRへ短縮。既設線は緩めない。</li>
<li>代表のF50は1.5ATR到達後の新しいB00悪化で、生存枠の50%を切捨て、一度だけ減量。新しい同方向のB00で復元。B00は自市場の2分変化がmax(0.25ATR,2呼値)、30秒変化がmax(0.1ATR,1呼値)を同方向へ超える価格条件。板数量ではない。元部分利確で消滅した枠は復元せず、全体R・360分期限もリセットしない。</li>
<li>短縮後は元の仮想運転の次の新規準備まで待つ。仮想運転も当行までで更新し、未来の終了時刻をコピーしない。判定・線の更新は次の有効原本行以降へ反映。360分又は場末で返済し、セッションをまたがない。</li></ol>
<p>ATRは確定5分足TRの指数平滑（α＝1/12、最低3本、最低2呼値）。足開始＋360秒で公開。機械学習や未来の確定足は不要です。</p></details>
<details><summary>追加ナイトの従来方式と、既読区間の扱い</summary>
<p>既存固定5方式はすべて赤字。以前の50%減量版の結果は下表です。これを隠さず、統合結果と区別しました。</p>
{table(['銘柄','利益円','損失円','収支','勝ち枚／負け枚','21時以降の時価変化'],new_rows)}
<p class="muted">21時以前は過去の一回照合で既読。21時以降は建玉をリセットせず、境界の含み損益を差し引いた変化です。部品担当は追加ナイトを見ず旧13から条件を作りましたが、全体担当は既存方式の追加成績を確認しているため、統合の追加適用を完全未見の検証とは呼びません。</p></details>
<h2>検証済みと、まだ結論が出ない範囲</h2>
<details><summary>入口・途中・出口・板・統合の棚卸しを開く</summary><div class="scope">{table(['範囲','検証済み','未検証・未確定'],integrated['検証区分'])}</div></details>
<p class="muted">同じ13場を繰り返し使うため、条件数を独立した相場数には数えません。ここでの高い確度は、実装の因果性、会計一致、同じ条件での部品差の再現に対するものです。将来の全相場で安定黒字という結論とは区別します。</p>
<details><summary>証拠と再現資料</summary><p>「事前棚卸し」は検証開始時点の記録です。その後に実施した入口114比較・途中13比較・出口13診断・統合結果の現状は、このページと各結論資料を参照してください。</p><ul>{''.join('<li><a href="'+source_prefix+escape(path)+'">'+escape(label)+'</a></li>' for label,path in links)}</ul>
<p><a href="README.md">読む順序・実行方法</a>。原本は読取専用のまま、現在セッションAPIの追加取得は0回です。</p></details>'''
    component='<!--\n[コンポーネント概要]\n本文は入口・途中判断・出口・統合の結論を表示します。\ndetails は数値の根拠と未検証範囲を開閉し、.scope は長い説明表を折り返します。\n売買や外部通信を行わず、別HTMLと保存済み証拠を開く静的な報告です。\n-->'
    html=f'<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>入口・途中判断・出口の分解検証</title><style>{tables.CSS}.scope td,.scope th{{white-space:normal;text-align:left;vertical-align:top}}.scope td:first-child{{min-width:100px}}.scope td:not(:first-child){{width:43%}}</style><body>{component}{body}</body></html>'
    (OUT/'分解と結論.html').write_text(html,encoding='utf-8')
    manifest=dict(全合格=True,主HTML_SHA256=replay.previous.digest(OUT/'分解と結論.html'),
        参照SHA256={name:replay.previous.digest(HERE/name) for name in ('entry_assessment.json','warm_assessment.json',
            'mid_result.json','exit_results.json','統合所見.json','new_sessions.json')})
    replay.save(HERE/'main_report_manifest.json',manifest)
    print('部品3章と統合・追加ナイトを主HTMLへ保存。',flush=True)


if __name__=='__main__':main()
