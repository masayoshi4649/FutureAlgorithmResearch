"""手法選択・エントリー・返済を一体評価した資料を最初の入口にする。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle
import shutil

import report as r

OUT = Path(__file__).resolve().parent
DEST, ROOT = r.DEST, r.ROOT


def main() -> None:
    """機能: 選択を含む実装と成績を短く表示し、単独手法資料へ接続する。

    引数: なし。返り値: なし (None)。新規通信は行わない。
    """
    ranking = r.read('選択統合の期間集計.json')
    chosen = r.read('選択統合の結果.json')
    rows = r.read('選択統合のセッション集計.json')
    walks = r.read('選択統合の逐次選択.json')
    events = r.read('手法選択の履歴.json')
    mapping = {v['id']:v for v in ranking}
    primary = mapping[chosen['primary']]
    top = chosen['finalists']
    byid = {v['id']:[] for v in ranking}
    for row in rows: byid[row['id']].append(row)
    text = '''<p><strong>選択・新規・返済を一つのアルゴリズムにして、追加360条件を検証しました。</strong></p>
<p>相場状態による選択10種類＋完了済み成績による選択８種類。それぞれ20種類の注文管理で、建玉・待機・連敗を引き継いで再生しています。人が相場を見て手法を選ぶ工程はありません。</p>
<div class="panel"><h2>今回の候補：X05_G08</h2><p><strong>板の補充と近い板・遠い板の変化で４手法を選択 → 逆指値で１枚新規 → 損切り／追跡で返済。</strong></p><p>全13区間でTOPIX ＋90,000円、NK ＋18,800円。最大勝ちセッションを除いても、それぞれ＋65,000円／＋13,600円です。</p></div>
<p class="warning">選択器自体を過去６区間から選び、次１区間ずつ評価した７区間も、TOPIX ＋34,500円／NK ＋4,800円でした。ただし全13区間は既読で、ルールを作った後の時系列再現です。未見相場で安定利益が証明されたとは扱いません。</p>
<h2>選択も含めた上位５つ</h2><p class="muted">X05/X04/X01は１枚、P03はTOPIX５枚／NK10枚、X08は予定損失２万円以内の可変枚数。円収支だけで順位付けしません。</p>'''
    text += r.table(['アルゴリズム','銘柄','利益 円','損失 円','収支 円','金額PF','1枚平均勝/負','黒字区間','時価最大下落 円'], [[f'<a href="#{i}">{i}</a>',r.NAMES[s],r.yen(a['gross_profit_yen']),r.yen(a['gross_loss_yen']),r.balance(a['net_yen']),r.number(a['money_ratio']),r.number(a['average_unit_payoff']),f"{a['win_sessions']}/13",r.yen(a['drawdown_yen'])] for i in top for s,a in mapping[i]['symbols'].items()])
    text += '''<p>X08のTOPIXは１枚平均勝/負が0.76で、平均幅としての損小利大には未達です。全体PFが１を超えることと区別します。</p>
<h2>X05_G08 の実行順</h2><ol>
<li><strong>開始20分後から毎分判定。</strong>その時点までに解放された板だけを使用する。</li>
<li><strong>優先順に手法を選ぶ。</strong>①同価格補充が片側へ偏り、30秒価格も反発：補充壁F44。②近い板と遠い板の圧力が一致：近い板の変化F42。③遠い板が先に変化：先行圧力F43。④それ以外：最良板F32。</li>
<li><strong>２回連続の確認で切り替える。</strong>切替後は最低３分維持する。選んだ手法がまだ中立なら新規しない。手法選択は毎分、選択後の売買方向は原本更新ごとに更新する。</li>
<li><strong>方向が出たら、0.25ATR先へ１枚の逆指値。</strong>有効２分、取消後の再設定は可能。次の原本行から有効にし、返済後５分は新規しない。</li>
<li><strong>１ATR損切り、１ATR順行後は２ATR追跡。</strong>同方向２連敗停止とセッション損失予算を併用。ATRは新規注文時に固定する。</li>
<li><strong>保有中も選択判断を続ける。</strong>G08では手法の切替自体では玉を閉じず、既存の損切り・追跡・損失予算で管理。反対判断で返済するG01、反転するG02も同じ選択器で比較済み。</li>
<li><strong>全玉を場内返済。</strong>保有360分上限。日中15:35／夜間05:50に返済指示、次の観測で執行。新規は５分前まで。</li></ol>
<details><summary>数値の定義・起動状態・例外</summary><p>補充は同じ価格で直近30秒以内の数量減少を埋めた増加。約定か取消か、同じ注文者かは判別しません。近い板は距離d呼値に対しexp(−d/2)、遠い板はexp(−d/8)で上位10段へ重み付けします。</p><p>過去120秒の補充差/合計の絶対値≥0.20と30秒の価格方向一致を最優先。次に近遠の板圧力が各絶対値≥0.10で同符号。次に遠い板数量変化の絶対値≥0.05かつ近い側&lt;0.05。該当しなければF32。各選択先の発注方向条件は別途F44/F42/F43/F32の定義を満たす必要があります。</p><p>初期監視手法はF32。最低３分は直前の切替時刻から計るため、初回切替は２回確認で可能。判断観測が90秒を超えて欠けた場合は確認回数をリセット。セッション毎に状態・建玉を初期化。</p><p>同方向２連敗後は反対信号、または損切り成立行の観測価格から１ATR順行で再開。最初に置いた注文の予定損失をR0として、セッション時価損益が−3R0以下なら停止・返済。観測間の飛びでは超過し得ます。</p><p>ATRは確定５分足TRをα=1/12で平滑化、最低３本、足終了から１分遅らせて使用。すべて未来足不要です。</p></details>
<h2>手法の切替時に、どう決済するか</h2>'''
    text += r.table(['共通の選択器X05＋管理','TOPIX収支 円','NK収支 円','TOPIX金額PF','NK金額PF'], [[f'{i} {mapping[i]["manager"]["name"]}',r.balance(mapping[i]['symbols']['TOPIX']['net_yen']),r.balance(mapping[i]['symbols']['NK225']['net_yen']),r.number(mapping[i]['symbols']['TOPIX']['money_ratio']),r.number(mapping[i]['symbols']['NK225']['money_ratio'])] for i in ['X05_G00','X05_G01','X05_G02','X05_G08','X05_G18']])
    text += '<p>方向の再判断だけでなく、決済の扱いも成績へ含めています。既存候補の損益を継ぎ足したものではありません。</p><h2>選択ルール自体を、過去だけで選ぶ再現</h2>'
    text += r.table(['評価セッション','その前に選んだID','TOPIX収支 円','NK収支 円'], [[f['評価'],f['採用ID'],r.balance(next(x['net_yen']for x in f['結果']if x['symbol']=='TOPIX')),r.balance(next(x['net_yen']for x in f['結果']if x['symbol']=='NK225'))] for f in walks['folds']])
    text += '<p>機械的な順位式は元探索と同じ。最大勝ち区間除外後の損益比について両銘柄の弱い側を優先します。X05_G08を６回、X09_G02を１回選択。先の固定手法群だけから選ぶ逐次評価（TOPIX−79,500円／NK−13,700円）とは別の追加検証です。過去全体を見て設計した選択器である点は変わりません。</p>'
    text += '<h2>各アルゴリズムの金額・枚数</h2><p class="muted">利益枚数と損失枚数は決済枚数。差は金銭収支ではありません。全13区間・9/21の週10区間・9/28の週３区間を分けています。</p>'
    representatives=list(top)
    seen={mapping[i]['signal_id']for i in top}
    for item in ranking:
        if item['signal_id']not in seen:
            representatives.append(item['id']);seen.add(item['signal_id'])
    for i in representatives:
        item=mapping[i]
        text += f'<details id="{i}"><summary>{i} ／ {r.esc(item["signal"]["name"])} ＋ {r.esc(item["manager"]["name"])}</summary><p>{r.esc(item["signal"]["description"])}</p><p>{r.esc(item["manager"]["description"])}</p>'
        if item['manager_id']=='G13':
            text += '<p>TOPIXは５枚中２枚を利確して３枚継続、NKは10枚中５枚を利確して５枚継続します。</p>'
        for s in r.NAMES:
            a=item['symbols'][s]
            text += f'<h3>{r.NAMES[s]}版</h3><p>全期間 {r.balance(a["net_yen"])}円、金額PF {r.number(a["money_ratio"])}、組PF {r.number(a["cycle_ratio"])}。１枚平均勝/負 {r.number(a["average_unit_payoff"])}。最大勝ち区間除外 {r.balance(a["best_removed_net"])}円。</p><p class="muted">最大同時買い{a["max_long"]}枚／売り{a["max_short"]}枚、{a["cycles"]}組。全玉の含み損益を入れた最大下落{r.yen(a["drawdown_yen"])}円。</p>'
            text += r.period_table([v for v in byid[i]if v['symbol']==s])
        text += '<details><summary>選択・注文の固定パラメータ</summary><pre>'+r.esc(json.dumps(dict(選択=item['signal'],注文=item['manager']),ensure_ascii=False,indent=2))+'</pre></details></details>'
    current=OUT/'selector_live_result.json'
    if current.exists():
        live=r.read('selector_live_result.json')
        text += '<h2>取得済み現在セッションでの事後診断</h2><p>9/29ナイト17:25締切の保存物を再利用。追加取得はしていません。選択器は取得後に実装したため、この欄を未見データの答え合わせとは呼びません。先に凍結した固定５候補の一回照合は<a href="結果.html">別欄</a>です。</p>'
        text += r.table(['選択一体アルゴリズム','銘柄','実現収支 円','含み損益 円','合算 円','買い保有','売り保有'], [[v['手法ID'],r.NAMES[v['銘柄']],r.balance(v['実現収支円']),r.balance(v['含み損益円']),r.balance(v['合算損益円']),str(v['保有買い枚数']),str(v['保有売り枚数'])] for v in live['結果']])
    text += '''<h2>検証したことと、まだ言えないこと</h2><p>売買原理を観測可能な条件へ変え、手法の選択・注文・損失玉の処理を実装して検証しました。X05は板の状態で機械的に切り替わる実装で、LSTMは不要です。</p><p>全相場で黒字になること、長期下落でも必ず波を取れること、未見期間で同じ成績になることは確認できていません。滑らかな相場では逆指値の失効問題も残ります。元データは先物原本、小型契約倍率、費用0・指定価格約定、片方向同時上限TOPIX10枚／NK20枚という条件です。</p>
<p><a href="selector_signals.py">相場状態の選択コード</a> · <a href="selector_past.py">過去成績の選択コード</a> · <a href="selector_research.py">選択から返済までの実行コード</a> · <a href="手法選択の履歴.json">全判断履歴</a> · <a href="選択統合の期間集計.json">全360条件</a> · <a href="５分足と売買.html">売買の図解</a></p>'''
    (DEST/'選択から返済まで.html').write_text(r.page('手法選択から返済までのアルゴリズム',text),encoding='utf-8')
    files=['selector_signals.py','selector_past.py','selector_research.py','selector_report.py','探索前の選択条件.json','selector_past_fixed.json','選択統合の探索前固定.json','選択統合の探索前固定_境界修正前.json','選択境界修正の全長一致.json','選択統合の結果.json','選択統合の全条件.json','選択統合の期間集計.json','選択統合のセッション集計.json','選択統合の逐次選択.json','手法選択の履歴.json','selector_past_audit.json','selector_market_audit.json','selector_selected_audit.json','selector_live_result.json','philosophical_evidence.py']
    for name in files:
        if(OUT/name).exists():shutil.copy2(OUT/name,DEST/name)
    base=r.read('全条件の期間集計.json')
    merged={v['id']:v for v in base+ranking}
    oldchosen=r.read('選択結果.json')['finalists']
    payload=r.chart_payload(top+oldchosen,merged,pickle.loads((OUT/'inputs.pkl').read_bytes()))
    chart=(DEST/'５分足と売買.html').read_text(encoding='utf-8')
    start=chart.index('<script id="chart-data" type="application/json">')+len('<script id="chart-data" type="application/json">')
    end=chart.index('</script>',start)
    chart=chart[:start]+json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')+chart[end:]
    chart=chart.replace('上位５候補の確定５分足','選択一体５候補と固定５候補の確定５分足')
    (DEST/'５分足と売買.html').write_text(chart,encoding='utf-8')
    original=(DEST/'結果.html').read_text(encoding='utf-8')
    marker='<!--選択統合追記-->'
    if marker not in original:
        block=marker+'<div class="panel"><h2>最新：手法選択も含めたアルゴリズム</h2><p>追加360条件を一体検証。首位X05_G08はTOPIX＋90,000円／NK＋18,800円。選択器を過去だけで選ぶ７区間の再現も＋34,500円／＋4,800円。</p><p><strong><a href="選択から返済まで.html">選択・新規・返済とセッション別損益を開く →</a></strong></p><p class="muted">以下は先に行った固定信号1,160条件の結果です。追加分も全13区間既読での再現。</p></div>'
        pos=original.index('</h1>')+len('</h1>');original=original[:pos]+block+original[pos:]
        (DEST/'結果.html').write_text(original,encoding='utf-8')
    p=DEST/'README.md';text=p.read_text(encoding='utf-8')
    if '最初に見るファイルは **[選択から返済まで' not in text:
        text=text.replace('最初に見るファイルは **[結果.html](結果.html)** です。','最初に見るファイルは **[選択から返済まで.html](選択から返済まで.html)** です。手法選択も機械化した18×20条件の追加結果です。')
        text=text.replace('読む順序：','追加実行コードは `work/wave_v23/selector_research.py`。先行の1,160条件が準備済みの状態で、選択後の方向を単一の注文管理器へ渡して再生します。原本→先行検証→追加選択統合→`report.py`→`selector_report.py` の順。実発注はしません。\n\n読む順序：\n\n0. [手法選択から返済まで](選択から返済まで.html)：新しい入口、実装済み選択器、期間・週・セッション損益。')
        p.write_text(text,encoding='utf-8')
    p=ROOT/'アルゴリズム調査/index.html';text=p.read_text(encoding='utf-8')
    text=text.replace('href="00018_市場原理からの再探索/結果.html">結論と反証を開く →','href="00018_市場原理からの再探索/選択から返済まで.html">手法選択から返済までを開く →')
    p.write_text(text,encoding='utf-8')
    p=ROOT/'アルゴリズム調査/README.md';text=p.read_text(encoding='utf-8')
    text=text.replace('[市場原理からの再検証](00018_市場原理からの再探索/結果.html)','[手法選択から返済まで](00018_市場原理からの再探索/選択から返済まで.html)')
    text=text.replace('[結論](00018_市場原理からの再探索/結果.html)','[選択一体の結果](00018_市場原理からの再探索/選択から返済まで.html)')
    p.write_text(text,encoding='utf-8')
    summary='\n\n## 追加：手法選択も一体化\n\n18選択器×20管理の追加360条件。首位X05_G08は、板の補充・近遠の圧力からF44/F42/F43/F32を毎分選び、同じ口座で新規から場内返済まで行う実装。TOPIX利益188,000円／損失98,000円／収支+90,000円、NK利益32,000円／損失13,200円／収支+18,800円。\n\n選択器自体を過去６区間から次１区間ずつ機械選択した７区間はTOPIX+34,500円／NK+4,800円。全期間既読の事後設計であり未見証明ではない。詳細は[選択から返済まで](選択から返済まで.html)。\n'
    p=DEST/'検証結果.md';text=p.read_text(encoding='utf-8')
    if'## 追加：手法選択も一体化'not in text:p.write_text(text+summary,encoding='utf-8')
    print('選択一体の資料を更新しました。',flush=True)


if __name__=='__main__':
    main()
