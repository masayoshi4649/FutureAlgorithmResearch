"""最悪方式の反転を日本語の報告書と暗色の５分足図解へまとめる。"""

from __future__ import annotations

import html
import json
from pathlib import Path
import re
import shutil

import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
DEST = ROOT / 'アルゴリズム調査' / '00007_最悪成績の反転検証'
PAGE = '最悪成績の反転検証.html'
COMPLETE = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day', '2026-09-22_Night', '2026-09-23_Day']
PHILOSOPHIES = ['予測主導', '予測と注文の組合せ', '注文主導']
MAIN = 'P_P16_05'


def yen(value: float, signed: bool = True) -> str:
    """機能: 円の値を読みやすい万円表記にする。

    引数: value (float)、signed (bool)。返り値: 万円表記 (str)。
    """
    if pd.isna(value):
        return '—'
    value = float(value) / 10000
    number = f'{abs(value):,.2f}'.rstrip('0').rstrip('.')
    sign = '−' if value < 0 else '＋' if value > 0 and signed else ''
    return sign + number + '万円'


def table(headers: list[str], rows: list[list], caption: str = '') -> str:
    """機能: エスケープした横スクロール可能なHTML表を作る。

    引数: headers (list[str])、rows (list[list])、caption (str)。返り値: HTML (str)。
    """
    out = '<div class="table-wrap"><table>'
    if caption:
        out += f'<caption>{html.escape(caption)}</caption>'
    out += '<thead><tr>' + ''.join(f'<th>{html.escape(str(c))}</th>' for c in headers) + '</tr></thead><tbody>'
    for row in rows:
        out += '<tr>' + ''.join(f'<td>{html.escape(str(c))}</td>' for c in row) + '</tr>'
    return out + '</tbody></table></div>'


def load_json(name: str) -> object:
    """機能: 作業フォルダの日本語JSONを読み込む。

    引数: name (str)。返り値: JSONの内容 (object)。
    """
    return json.loads((WORK / name).read_text(encoding='utf-8'))


def normalise_direction(trades: list[dict]) -> list[dict]:
    """機能: 元・信号反転の売買記録を図解用の小さな共通辞書にする。

    引数: trades (list[dict])。返り値: 主方式の売買記録 (list[dict])。
    """
    result = []
    for trade in trades:
        if trade['方式'] != MAIN or trade['データ区分'] == '既知ナイト00:02':
            continue
        multiplier = 1000 if trade['銘柄'] == 'NK225' else 10000
        result.append(dict(method=MAIN, session=trade['セッション'], symbol=trade['銘柄'],
            execution='元の方向' if trade['方向'] == '元の方向' else '予測方向反転',
            entry=trade['entry_time_s'], ep=trade['entry_price'],
            exit=trade.get('exit_time_s', trade.get('mark_time_s')), xp=trade.get('exit_price', trade.get('mark_price')),
            side=trade['side'], closed=trade['closed'], net=trade['net_points'] * multiplier,
            reason=trade.get('exit_reason', '末尾の含み損益'), entry_seq=trade['entry_seq'], exit_seq=trade.get('exit_seq')))
    return result


def chart_data() -> dict:
    """機能: 保存済み５分足と主方式の元・反転取引を図解用にまとめる。

    引数: なし。返り値: ローソク足・売買・既読区間表示の辞書 (dict)。
    """
    candles = {}
    for symbol in ['NK225', 'TOPIX']:
        for session in COMPLETE + ['2026-09-23_Night']:
            base = ROOT if session in COMPLETE else ROOT / 'work' / 'wave_v11' / 'live'
            frame = pd.read_csv(base / 'candle_5min' / symbol / f'{session}.csv')
            rows = []
            for row in frame.to_dict('records'):
                rows.append([pd.Timestamp(row['time']).timestamp(), row['open'], row['high'], row['low'], row['close']])
            candles[f'{session}|{symbol}'] = rows
    trades = normalise_direction(load_json('方向反転_全取引.json'))
    mirrors = load_json('反転_代表取引.json')
    mirrors = [dict(t, reason='仮想手法の返済に連動') for t in mirrors if t['method'] == MAIN and t['session'] in COMPLETE]
    recent_path = WORK / '反転_既読ナイト代表取引.json'
    if recent_path.exists():
        mirrors += [dict(t, reason='仮想手法の返済に連動') for t in load_json(recent_path.name) if t['method'] == MAIN]
    trades += mirrors
    return dict(candles=candles, trades=trades, main=MAIN,
                current_mirror_available=recent_path.exists(), sessions=COMPLETE + ['2026-09-23_Night'])


def summary_sections(mirror: pd.DataFrame, direction: pd.DataFrame) -> tuple[str, str]:
    """機能: 主方式の損益・費用分解・全反転探索をHTMLとMarkdownにする。

    引数: mirror/direction (DataFrame)。返り値: HTMLとMarkdown (tuple[str,str])。
    """
    complete = mirror.loc[mirror.セッション.isin(COMPLETE)]
    main = complete.loc[complete.方式 == MAIN]
    numbers = main.select_dtypes(include='number').sum()
    decomposition = []
    for label, frame in [('NK225', main.loc[main.銘柄 == 'NK225']), ('TOPIX', main.loc[main.銘柄 == 'TOPIX']), ('合計', main)]:
        s = frame.select_dtypes(include='number').sum()
        decomposition.append([label, yen(s['元mid値動き益円']), yen(-s['元半spread円']), yen(-s['元追加費用円']),
                              yen(s['元収支円']), yen(s['理論反転収支円']), yen(s['次行反転収支円'])])
    parts = '''<section id="cost"><div class="eyebrow">01 ／ 最悪方式で起きていたこと</div><h2>値動きの損益はプラスだったが、費用が上回った</h2>
    <p>５完全セッションで、全方式から元の純収支を設定枚数上限で割って最悪を選ぶと、<code>P_P16_05</code>でした。板の約定方向推定と気配更新が同方向に続いたときに入り、５分後に返済する方式です。両銘柄合計280取引となりました。</p>
    <p>元方向の中値の値動き益は<strong>＋78.75万円</strong>。そこから観測された入口・出口の気配差312.75万円と、<strong>仮定した往復追加２呼値の費用401万円</strong>が引かれ、−635万円になっています。401万円は実測の手数料ではありません。反転すると値動き益が−78.75万円へ変わり、費用は引かれ続けます。</p>'''
    parts += table(['銘柄', '元の中値変化', '気配差負担', '追加費用', '元の純収支', '同時点の理論反転', '次行から反転'], decomposition)
    parts += '''<div class="formula"><b>同じ時点に１枚ずつ売買する理論比較</b><br>元の純益 ＝ 値動き益 − 費用<br>反転の純益 ＝ −値動き益 − 費用 ＝ −元の純益 − ２×費用</div>
    <p class="note">ここでの費用は売買気配差と往復追加２呼値の合計です。NK225は１呼値10円・倍率1,000円、TOPIXは１呼値0.5ポイント・倍率10,000円のラージを想定。次行約定では価格と数量の都合で時刻が変わるため、理論反転と区別します。</p>
    <div class="banner">追加費用をゼロとしても、観測気配差だけで元−234万円、次行反転−398万円でした。反転が赤字になる理由は追加２呼値の仮定だけではありません。</div>
    <p class="note">費用感度は２呼値で計算した注文イベントを固定して追加費用だけを変えた会計比較です。主例は固定時間返済のため注文経路そのものは費用に依存しません。</p><h3>「最悪」をどう選ぶかも比較</h3>{{WORST_COMPARISON}}</section>'''
    session_rows = []
    for session in COMPLETE:
        for symbol in ['NK225', 'TOPIX']:
            row = main.loc[(main.セッション == session) & (main.銘柄 == symbol)].iloc[0]
            rev = direction.loc[(direction.データ区分 == '完全５セッション') & (direction.方式 == MAIN)
                                & (direction.セッション == session) & (direction.銘柄 == symbol) & (direction.方向 == '予測方向反転')].iloc[0]
            session_rows.append([session.replace('_', ' '), symbol, int(row['元取引数']), yen(row['元収支円']),
                                 yen(row['次行反転利益円'], False), yen(row['次行反転損失円'], False),
                                 yen(row['次行反転収支円']), yen(rev['収支円'])])
    session_rows.append(['合計', '両銘柄', int(numbers['元取引数']), yen(numbers['元収支円']),
                         yen(numbers['次行反転利益円'], False), yen(numbers['次行反転損失円'], False),
                         yen(numbers['次行反転収支円']), yen(direction.loc[(direction.データ区分 == '完全５セッション')
                             & (direction.方式 == MAIN) & (direction.方向 == '予測方向反転'), '収支円'].sum())])
    parts += '<section id="sessions"><div class="eyebrow">02 ／ セッションごとの利益と損失</div><h2>最悪の１条件を反転しても赤字が残った</h2>'
    parts += table(['セッション', '銘柄', '元取引数', '元の収支', '次行反転の利益', '次行反転の損失', '次行反転の収支', '予測方向反転の収支'], session_rows)
    parts += '<p class="note">利益・損失は費用控除後の各取引を正負に分けて合計。主方式は各銘柄１枚です。方向反転は固定５分返済で売買時刻が一致したため、同時点の理論反転と一致しました。損切り・追跡を持つ方式にはこの一致を仮定していません。</p></section>'
    totals = complete.groupby(['思想', '方式'], as_index=False)[['元収支円', '次行反転収支円', '次行反転費用倍収支円']].sum()
    count_rows = []
    for philosophy in PHILOSOPHIES:
        sub = totals.loc[totals.思想 == philosophy]
        count_rows.append([philosophy, len(sub), int((sub['元収支円'] > 0).sum()),
                           int((sub['次行反転収支円'] > 0).sum()), int((sub['次行反転費用倍収支円'] > 0).sum())])
    top = totals.sort_values('次行反転収支円', ascending=False).head(10)
    parts += '<section id="all"><div class="eyebrow">04 ／ 全1,598条件の反転</div><h2>反転後に黒字の条件は10個。ただし費用を増やすと全て赤字</h2><p>「全部赤字」は前回の予測を使わない注文主導60条件の結果です。前回の全1,598条件が赤字という意味ではありません。今回は予測・組合せ・注文の全条件を仮想運転して、次行から反対売買しました。</p>'
    parts += table(['思想', '条件数', '元の黒字条件', '次行反転の黒字条件', '追加費用４呼値で黒字'], count_rows)
    parts += '<p>反転成績を見て選ぶ探索内の最大は、２銘柄の相対的な価格乖離を使う<code>P_P21_60</code>の＋33万円です。追加費用を往復２呼値から４呼値にすると−５万円。下表は反転結果を見て並べた参考であり、「元の最悪を選ぶ」主方針とは別です。</p>'
    parts += table(['方式', '思想', '元の収支', '次行反転の収支', '追加費用４呼値'],
                   [[r['方式'], r['思想'], yen(r['元収支円']), yen(r['次行反転収支円']), yen(r['次行反転費用倍収支円'])] for r in top.to_dict('records')])
    invert = direction.loc[(direction.データ区分 == '完全５セッション') & (direction.方向 == '予測方向反転')]
    inverted_totals = invert.groupby('方式', as_index=False)[['収支円', '費用倍収支円', '取引数']].sum()
    parts += '<h3>予測方向だけを反転する14条件</h3><p>元の最悪候補を、各思想・銘柄・学習期間・枚数換算/実額から選んだ重複なしの14条件です。これらは反転後の側に通常の入口・損切り・追跡を適用しました。両銘柄の５完全セッション合計では全14条件が赤字でした。方向予測を持たない純注文方式はこの比較の対象外です。</p>'
    parts += table(['方式', '取引脚数', '予測方向反転の収支', '追加費用４呼値'],
                   [[r['方式'], int(r['取引数']), yen(r['収支円']), yen(r['費用倍収支円'])] for r in inverted_totals.to_dict('records')])
    parts += '</section>'
    md = '# 最悪成績の反転検証\n\n最初に見る資料は[最悪成績の反転検証.html](最悪成績の反転検証.html)です。\n\n'
    md += '## 結論\n\n反転は検証すべき仮説ですが、今回の最悪方式は主に費用で負けていました。全方式から設定最大枚数で割った収支が最悪の `P_P16_05` を選ぶと、完全５セッション・両銘柄計で元−635万円、同時点の理論反転−792.5万円、次行からの反対売買−799万円でした。予測方向だけの反転も−792.5万円です。\n\n実額での最悪は３枚方式 `M_P16_O08_G2_X1` で、元−832.5万円、次行反転−448万円でした。最悪の尺度によって選ばれる条件は異なります。\n\n'
    md += '前回「全部赤字」と述べた対象は注文主導60条件であり、全1,598条件ではありません。今回、次行反転の探索内で黒字は10条件ありましたが、追加費用４呼値では０条件でした。反転自体が常に無効という結論ではありません。\n\n'
    md += '## 主方式の費用分解\n\n元方向の中値変化益＋78.75万円−観測気配差312.75万円−仮定した往復追加２呼値401万円＝−635万円。401万円は実測手数料ではありません。追加費用をゼロにしても元−234万円・次行反転−398万円でした。これは２呼値基準の注文イベントを固定した会計感度です。反転は値動き益の符号が変わりますが費用は残るため、単に−635万円を＋635万円へ読み替えられません。\n\n'
    md += '| 銘柄 | 中値変化益 | 気配差 | 追加費用 | 元収支 | 理論反転 | 次行反転 |\n|---|---:|---:|---:|---:|---:|---:|\n'
    md += ''.join('| ' + ' | '.join(row) + ' |\n' for row in decomposition)
    md += '\n{{WORST_COMPARISON_MD}}\n\n## セッション別損益\n\n| セッション | 銘柄 | 元取引数 | 元収支 | 次行反転利益 | 次行反転損失 | 次行反転収支 | 予測方向反転 |\n|---|---|---:|---:|---:|---:|---:|---:|\n'
    md += ''.join('| ' + ' | '.join(map(str, row)) + ' |\n' for row in session_rows)
    md += '\n## 全条件の反転\n\n| 思想 | 条件数 | 元黒字 | 次行反転黒字 | 費用４呼値で黒字 |\n|---|---:|---:|---:|---:|\n'
    md += ''.join('| ' + ' | '.join(map(str, row)) + ' |\n' for row in count_rows)
    md += '\n反転結果から選んだ探索内最大は `P_P21_60` の＋33万円、追加費用４呼値では−５万円。予測方向だけを反転した最悪候補14条件は全て赤字でした。全条件の結果は[反転セッション集計](資料/反転_全条件セッション集計.csv)で確認できます。\n'
    return parts, md


def supplementary_sections(direction: pd.DataFrame) -> tuple[str, str]:
    """機能: 時間順比較、既読ナイト、再現上の範囲を章として作る。

    引数: direction (DataFrame)。返り値: HTMLとMarkdown (tuple[str,str])。
    """
    walk = pd.read_csv(WORK / '方向反転_選択評価.csv')
    part = walk.loc[(walk.選択尺度 == '枚数上限換算') & (walk.集計用途 == '直後１セッション')]
    group = part.groupby(['思想', '対象', '方向'], as_index=False)[['収支円', '費用倍収支円']].sum()
    rows = [[r['思想'], r['対象'], r['方向'], yen(r['収支円']), yen(r['費用倍収支円'])] for r in group.to_dict('records')]
    out = '<section id="walk"><div class="eyebrow">05 ／ 過去の最悪を次に反転する</div><h2>最悪の条件を更新しても、安定した黒字にはつながらなかった</h2><p>先頭２セッションで元の最悪を選んで３番目、先頭３つで選んで４番目、先頭４つで選んで５番目を評価します。条件の選択に直後の損益を使わず、対象銘柄それぞれで学習期間に取引がある条件だけを選びました。同点はID順です。</p>'
    out += '<div id="mirror-walk">{{MIRROR_WALK}}</div><h3>予測方向だけの反転：３回の合計</h3>' + table(['思想', '選択対象', '実行', '３回合計', '追加費用４呼値'], rows)
    out += '<p class="note">どの方式にするかを毎回選び直す方針の成績です。最後に選んだ１条件を固定した成績とは違います。全期間は過去の探索で閲覧済みであり、今回の反転という発想も既存結果を見た後のため、研究全体で未見の検証とは呼びません。</p></section>'
    recent = direction.loc[(direction.方式 == MAIN) & (direction.データ区分 == '既読ナイト01:53全体')]
    recent_rows = []
    for row in recent.to_dict('records'):
        recent_rows.append([row['銘柄'], row['方向'], int(row['取引数']), yen(row['利益円'], False), yen(row['損失円'], False),
                            yen(row['収支円']), yen(row['評価損益円']), yen(row['清算価値円'])])
    out += '<section id="recent"><div class="eyebrow">06 ／ 既読データの参考評価</div><h2>9月23日ナイト、翌01:53まで</h2><p>前回取得済みの保存データを再利用しています。現在APIの追加取得は０回です。17:00からの全体を状態継続で再生し、未返済の損益を末尾の反対気配と費用引当てで合算しました。途中00:02から運転を始め直していません。</p>'
    out += table(['銘柄', '実行', '返済済み数', '確定利益', '確定損失', '確定収支', '未返済評価', '合計清算価値'], recent_rows)
    out += '<div id="mirror-recent">{{MIRROR_RECENT}}</div><p class="note">ナイト全体はまだ未完了です。末尾評価は実際の返済を意味しません。セッション内返済ルールを守る完全セッションの成績とは分けて読みます。</p></section>'
    out += '''<section id="rules"><div class="eyebrow">07 ／ 実行条件と監査</div><h2>反転の意味を固定して、時間を進めて計算する</h2>
    <h3>主例 P_P16_05 の条件</h3><p>過去60秒の約定方向を価格変化から推定し、出来高偏りが＋0.3以上・確認できた出来高５以上・気配更新偏りも正なら買い、対称なら売り。連続する２つの確定板ブロックで確認します。これは真の成行売買方向を直接観測した値ではありません。同一の最終約定時刻を持つ板を確定し、次の時刻の行で初めて信号として公開します。</p>
    <p>セッション開始20分後から、信号を検知した後の有効な板行で１枚発注。返済後５分は休止、信号の有効期間は２分です。元ルールは損切り・追跡を付けず、約定から５分経過後の返済条件に従い次の有効行で返済します。昼15:35・夜05:50のセッション内返済を優先し、その30分前以降は新規を行いません。</p>
    <h3>仮想手法に連動する反転</h3><p>元の手法を仮想的に動かし、仮想新規・返済のイベントを受けて、次の有効板行以降で反対側に発注します。最良気配の数量を同時注文で共有し、実保有の枚数上限を維持。元の損切りが反転側の利確になる場合もあります。反転側の損益で元の仮想ルールを変更しません。</p>
    <h3>予測方向だけの反転</h3><p>信号の時刻・ATR・市場の板状態は維持し、買い信号と売り信号だけを交換します。入口のトレーリング、損切り、利確、追跡ストップは反転後の建玉で通常通り計算します。元と売買時刻や件数が変わるため、元収支の符号反転で代用していません。</p>
    <p>全1,598条件の元会計・気配差・費用の恒等式を独立検算。数量制約と次行処理、未来の結果を改変しても過去の最悪選択が変わらないこと、方向の２回反転で元入力に戻ることも確認しました。原本や前回の凍結ソースは変更していません。</p>
    <p class="note">この板には受信時計がなく最終約定時計を使います。次の行は厳密な実時間の遅延を保証しません。約定列の受信遅延、待ち行列、市場への影響は完全には再現していません。倍率や費用に関わる仮定は前回と共通です。</p>
    <div class="links"><a href="資料/検証計画.md">反転の定義と選択方針</a><a href="資料/反転検証の監査.md">会計式と独立監査</a><a href="検証結果.md">文章の報告書</a><a href="README.md">資料の読む順序</a></div></section>'''
    md = '\n## 時間順の比較\n\n先頭２→３、３→４、４→５セッションで、過去の元成績が最悪の条件を選び、直後を評価しました。主選択は収支÷設定最大枚数、対象銘柄ごとに過去の取引あり、同点はID順。全データは既読で、未見検証ではありません。\n\n{{MIRROR_WALK_MD}}\n\n'
    md += '予測方向だけの反転は次の通りです。\n\n| 思想 | 対象 | 実行 | ３回合計 | 費用４呼値 |\n|---|---|---|---:|---:|\n'
    md += ''.join('| ' + ' | '.join(row) + ' |\n' for row in rows)
    md += '\n## 既読ナイトの参考\n\n前回保存した9月23日17:00〜翌01:53の全体です。現在API追加取得０回。末尾未返済評価を含みます。\n\n| 銘柄 | 実行 | 返済数 | 確定利益 | 確定損失 | 確定収支 | 含み損益 | 清算価値 |\n|---|---|---:|---:|---:|---:|---:|---:|\n'
    md += ''.join('| ' + ' | '.join(map(str, row)) + ' |\n' for row in recent_rows)
    md += '\n{{MIRROR_RECENT_MD}}\n\n## ルールと再現条件\n\nP_P16_05は、tick-rule推定の過去60秒出来高偏り±0.3、既知出来高５以上、気配更新偏り同方向を２確定ブロックで確認して発注し、５分経過で返済します。１枚・開始20分待機・返済後５分休止・信号有効２分。完全セッションでは必ず同一セッション内に返済します。\n\n連動反転は元仮想約定の次の有効板行以降で反対売買。予測方向反転は信号sideだけを交換して通常の入口・出口を再計算。同時点理論反転は会計分解であり主実行とは区別します。\n\n約定は反対気配と最良数量を使い、追加２呼値と４呼値を比較。先着順位、市場影響、受信遅延の完全再現はできません。枚数上限で割った値は証拠金利回りではありません。\n\n[検証計画](資料/検証計画.md)、[独立監査と出典](資料/反転検証の監査.md)を参照してください。\n'
    return out, md


def update_navigation() -> None:
    """機能: 作業一覧の最新リンクを追加し、過去の調査フォルダは変更しない。

    引数: なし。返り値: なし (None)。
    """
    base = DEST.parent
    readme = (base / 'README.md').read_text(encoding='utf-8')
    readme = re.sub(r'\*\*最新は.*?\*\*', '**最新は00007の[最悪成績の反転検証](00007_最悪成績の反転検証/最悪成績の反転検証.html)です。元の最悪方式を反転し、気配差・費用・数量・時間順評価を確認しています。**', readme, count=1)
    readme = readme.replace('`00006_予測と注文手法の組合せ検証`（最新）', '`00006_予測と注文手法の組合せ検証`')
    line = '| `00007_最悪成績の反転検証`（最新） | 最悪方式の反転、1,598条件の反対売買、14条件の逆信号、費用分解と時間順評価 | [反転の検証と売買図](00007_最悪成績の反転検証/最悪成績の反転検証.html) | [検証結果](00007_最悪成績の反転検証/検証結果.md)・[資料案内](00007_最悪成績の反転検証/README.md) |'
    if not re.search(r'^\| `00007_', readme, re.M):
        readme = readme.replace('| --- | --- | --- | --- |', '| --- | --- | --- | --- |\n' + line)
    readme = readme.replace('今後の新しい作業は `00007_内容`', '今後の新しい作業は `00008_内容`')
    (base / 'README.md').write_text(readme, encoding='utf-8')
    index = (base / 'index.html').read_text(encoding='utf-8')
    index = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は、最も損失が大きい方式の反転仮説を、売買の費用と次行約定を含めて検証した資料です。</p>', index, count=1)
    index = re.sub(r'\s*<!--00007開始-->.*?<!--00007終了-->', '', index, flags=re.S)
    index = index.replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
    article = '''
  <!--00007開始--><article class="task latest" aria-labelledby="reverse-title">
    <div class="number">作業 00007 <span class="badge">最新</span></div>
    <h2 id="reverse-title">最悪成績の反転検証</h2>
    <p>最も赤字の手法を逆に売買すれば利益になるか。全1,598条件の反対売買と14条件の予測反転を、気配差・費用・数量・時系列で比較しました。</p>
    <a class="button" href="00007_最悪成績の反転検証/最悪成績の反転検証.html">反転の結果と５分足売買図を開く →</a>
    <ul><li><a href="00007_最悪成績の反転検証/検証結果.md">セッション別の利益・損失・収支</a></li><li><a href="00007_最悪成績の反転検証/README.md">資料の読む順序と再現方法</a></li></ul>
    <p class="folder">保存先：00007_最悪成績の反転検証</p>
  </article><!--00007終了-->
'''
    index = index.replace('  </header>', '  </header>' + article, 1)
    (base / 'index.html').write_text(index, encoding='utf-8')


def insert_external_reports(page: str, markdown: str) -> tuple[str, str]:
    """機能: 他担当が保存した時間順と既読ナイトの表を報告へ差し込む。

    引数: page/markdown (str)。返り値: 差し込み後のHTMLとMarkdown (tuple[str,str])。
    """
    representatives = pd.read_csv(WORK / '反転_５完全探索代表.csv')
    representatives = representatives.loc[(representatives.対象 == '両銘柄') & (representatives.思想 == '全方式')]
    caps = pd.read_csv(WORK / '反転_全条件セッション集計.csv').groupby('方式').設定最大枚数.max().to_dict()
    rows = [[r['選び方'], r['方式'], int(caps[r['方式']]), yen(r['元収支円']), yen(r['次行反転収支円']),
             yen(r['次行反転設定上限換算収支円']), yen(r['次行反転費用倍収支円'])] for r in representatives.to_dict('records')]
    note = '主方針は元の純益を設定最大枚数で割って最悪を選ぶこと。副比較として実額最悪、費用を除く中値変化益の最悪も選びました。枚数は各銘柄の上限で、両銘柄合計の上限は２倍。換算額は証拠金利回りではありません。'
    page = page.replace('{{WORST_COMPARISON}}', table(['選び方', '選択された方式', '枚数上限', '元収支の実額', '次行反転の実額', '上限換算の反転収支', '４呼値での実額'], rows) + '<p class="note">' + note + '</p>')
    md = '### ５完全セッションで最悪を選ぶ尺度の比較\n\n| 選び方 | 方式 | 枚数上限 | 元実額 | 次行反転実額 | 上限換算反転 | ４呼値実額 |\n|---|---|---:|---:|---:|---:|---:|\n'
    md += ''.join('| ' + ' | '.join(map(str, row)) + ' |\n' for row in rows) + '\n' + note
    markdown = markdown.replace('{{WORST_COMPARISON_MD}}', md)

    # ----------------------------------------
    # 時間順で最悪を選び直す方針の成績を、全方式と思想別で表示する。
    walk = pd.read_csv(WORK / '反転_選択方針要約.csv')
    choices = ['元純益最悪・枚数換算', '元純益最悪・実額', '元仲値変化最悪・枚数換算']
    rows = []
    for choice in choices:
        for target in ['両銘柄', 'NK225', 'TOPIX']:
            r = walk.loc[(walk.選び方 == choice) & (walk.対象 == target) & (walk.思想 == '全方式')].iloc[0]
            rows.append([choice, target, yen(r['元収支円']), yen(r['次行反転収支円']),
                         yen(r['次行反転設定上限換算収支円']), yen(r['次行反転費用倍収支円'])])
    table_html = '<h3>全方式から選ぶ主・副方針：３回の合計</h3>' + table(['選び方', '対象', '元の実額', '次行反転の実額', '上限換算の反転', '４呼値の実額'], rows)
    table_html += '<p>主方針の両銘柄共通条件では、元−336万円に対して反転−543万円。実額の最悪を選ぶ場合も−272万円、中値の値動きが最悪を選ぶ場合も−153.5万円でした。銘柄別に中値変化の最悪を選んだNK225は＋８万円ですが、追加４呼値では−52万円です。</p>'
    details = pd.read_csv(WORK / '反転_時間順選択評価.csv')
    details = details.loc[(details.選び方 == choices[0]) & (details.対象 == '両銘柄') & (details.思想 == '全方式')]
    table_html += table(['過去セッション数', '選択された方式', '評価セッション', '元の収支', '次行反転'],
                        [[int(r['学習数']), r['方式'], r['評価セッション'], yen(r['元収支円']), yen(r['次行反転収支円'])] for r in details.to_dict('records')])
    phi_rows = [[r['思想'], r['対象'], yen(r['元収支円']), yen(r['次行反転収支円']), yen(r['次行反転費用倍収支円'])]
                for r in walk.loc[(walk.選び方 == choices[0]) & (walk.思想 != '全方式')].to_dict('records')]
    table_html += '<details><summary>思想別の主方針を見る</summary>' + table(['思想', '対象', '元実額', '次行反転実額', '４呼値実額'], phi_rows) + '</details>'
    table_html += '<p class="note">全選択記録と実際の採用条件は<a href="資料/反転_時間順選択評価.csv">時間順の選択・評価CSV</a>、<a href="資料/反転_選択方針要約.csv">方針の要約CSV</a>に保存しています。</p>'
    md = '### 仮想売買に連動する次行反転：全方式から選ぶ方針\n\n| 選び方 | 対象 | 元実額 | 次行反転実額 | 上限換算反転 | ４呼値実額 |\n|---|---|---:|---:|---:|---:|\n'
    md += ''.join('| ' + ' | '.join(row) + ' |\n' for row in rows)
    md += '\n[実際の採用条件と時間順評価](資料/反転_時間順選択評価.csv)、[思想別を含む方針要約](資料/反転_選択方針要約.csv)。主方針の両銘柄合計は−543万円で、未見の優位性は確認できません。\n'
    page = page.replace('{{MIRROR_WALK}}', table_html)
    markdown = markdown.replace('{{MIRROR_WALK_MD}}', md)

    # ----------------------------------------
    # 既読ナイトは未返済を含む全体参考。新たな未見照合とは呼ばない。
    recent = pd.read_csv(WORK / '反転_既読ナイトセッション集計.csv')
    recent = recent.loc[recent.方式 == MAIN]
    rows = [[r['銘柄'], int(r['次行反転取引数']), yen(r['次行反転利益円'], False), yen(r['次行反転損失円'], False),
             yen(r['次行反転収支円']), yen(r['次行反転評価損益円']), yen(r['次行反転総評価円'])] for r in recent.to_dict('records')]
    text = '<h3>次行からの反対売買</h3>' + table(['銘柄', '返済済み数', '確定利益', '確定損失', '確定収支', '未返済評価', '合計清算価値'], rows)
    md = '次行反転の参考：\n\n| 銘柄 | 返済数 | 利益 | 損失 | 確定収支 | 未返済評価 | 清算価値 |\n|---|---:|---:|---:|---:|---:|---:|\n'
    md += ''.join('| ' + ' | '.join(map(str, row)) + ' |\n' for row in rows)
    page = page.replace('{{MIRROR_RECENT}}', text)
    markdown = markdown.replace('{{MIRROR_RECENT_MD}}', md)
    return page, markdown


def main() -> None:
    """機能: 図解HTML、結果文書、資料案内を作成して一覧リンクを更新する。

    引数: なし。返り値: なし (None)。元データと凍結済みコードは読み取りのみ。
    """
    DEST.mkdir(parents=True, exist_ok=True)
    materials = DEST / '資料'
    materials.mkdir(exist_ok=True)
    mirror = pd.read_csv(WORK / '反転_全条件セッション集計.csv')
    direction = pd.read_csv(WORK / '方向反転_セッション集計.csv')
    first, md = summary_sections(mirror, direction)
    other, md_other = supplementary_sections(direction)
    first, all_section = first.split('<section id="all">', 1)
    other = '<section id="all">' + all_section + other
    template = (WORK / 'report_template.html').read_text(encoding='utf-8')
    data = json.dumps(chart_data(), ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    page = template.replace('{{SUMMARY}}', first).replace('{{SUPPLEMENT}}', other).replace('{{DATA}}', data)
    page, md = insert_external_reports(page, md + md_other)
    (DEST / PAGE).write_text(page, encoding='utf-8')
    (DEST / '検証結果.md').write_text(md, encoding='utf-8')
    (DEST / 'README.md').write_text('''# 00007 最悪成績の反転検証

最初に見るファイルは **[最悪成績の反転検証.html](最悪成績の反転検証.html)** です。ブラウザーで開くと、費用分解、各セッションの利益・損失、元と反転の５分足売買図を確認できます。外部ライブラリやネットワーク接続は不要です。

## 読む順序

1. [図解HTML](最悪成績の反転検証.html)：結論、反転の定義、費用と売買図。
2. [検証結果](検証結果.md)：数値と解釈を文章で確認。
3. [検証計画](資料/検証計画.md)：何を反転し、どの過去から最悪を選んだか。
4. [反転の全条件・全セッション集計](資料/反転_全条件セッション集計.csv)：1,598条件の元・理論・数量付き・次行の損益。
5. [逆信号のセッション集計](資料/方向反転_セッション集計.csv)、[最悪選択と評価](資料/方向反転_選択評価.csv)：方向だけを反転した14条件。
6. [独立監査](資料/反転検証の監査.md)：会計恒等式、数量・時刻・選択の検査と研究出典。

## 再現方法

実行ソースはプロジェクト内の `work/wave_v12` です。資料内のコピーは参照用で、単独では実行できません。前回 `work/wave_v11` の凍結済み注文器・保存再生入力、および `wave_v7`〜`wave_v10` の依存モジュールを使います。元の `book`・`candle_1min`・`candle_5min` は読み取り専用です。

方向反転：`python work/wave_v12/direction.py`。全条件の連動反転：`python work/wave_v12/mirror.py`。報告再生成：`python work/wave_v12/report.py`。実行はプロジェクトルートで行います。今回は現在APIの再取得を行いません。既読ナイトは前回保存済みの01:53までを使います。

## 読み方の注意

理論反転は同じ板行の会計比較、主実行は仮想約定を観測した次行以降の反対売買です。予測方向反転は入口と出口を反転側で作り直す別手法です。全期間が既読であり、今回の時間順分割も研究全体の未見検証ではありません。枚数上限換算値は証拠金利回りではありません。
''', encoding='utf-8')
    for path in WORK.iterdir():
        if path.suffix in ('.py', '.csv', '.md', '.json', '.npz') and path.name not in ['方向反転_評価曲線.json', '方向反転_全取引.json']:
            shutil.copy2(path, materials / path.name)
    shutil.copy2(WORK / 'report_template.html', materials / 'report_template.html')
    update_navigation()
    print(f'報告書を作成しました: {DEST / PAGE}')


if __name__ == '__main__':
    main()
