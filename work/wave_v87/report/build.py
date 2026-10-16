"""原因・対策・全場損益を、短い本文と任意表示の表で公開する。"""

import html
import json
from pathlib import Path
import shutil

import analyze

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
FOLDER = '00083_再参加の損失原因と改善の反復検証'
PUBLIC = ROOT / 'アルゴリズム調査' / FOLDER
MAIN = '損失原因と改善の反復結果.html'
SYMBOLS = ('TOPIX', 'NK225')


def read(path):
    """
    機能: 完成済みの検証資料を読む。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def money(value):
    """
    機能: 料金後金額に符号と色を付ける。
    引数: value(float)。
    返り値: strのHTML。
    """
    n = round(value)
    return f'<span class="{"gain" if n > 0 else "loss" if n < 0 else "neutral"}">{n:+,}円</span>' if n else '0円'


def ratio(value):
    """
    機能: 金額利益割合を表示し、利益損失が共にゼロなら未定義とする。
    引数: value(float又はNone)。
    返り値: str。無取引を勝ちとして表示しない。
    """
    return '—' if value is None else f'{value*100:.1f}%'


def table(heads, rows):
    """
    機能: 表を画面内の横スクロール領域に収める。
    引数: heads(list[str])、rows(list[list[str]])。
    返り値: strのHTML。
    """
    header = ''.join('<th>'+v+'</th>' for v in heads)
    body = ''.join('<tr>'+''.join('<td>'+v+'</td>' for v in row)+'</tr>' for row in rows)
    return '<div class="scroll"><table><thead><tr>'+header+'</tr></thead><tbody>'+body+'</tbody></table></div>'


def describe(config):
    """
    機能: 各条件の入口・数量・出口を短い日本語へまとめる。
    引数: config(dict)。
    返り値: str。仕様の細部は固定資料を参照する。
    """
    if 'offset_atr' in config and config.get('execution_mode') != 'IDEAL':
        if config['execution_mode'] == 'NEXT':
            return '元E01の仮想新規・返済を、次の有効観測でそのまま実行する対照。'
        return (f"元E01が仮想で新規した後、その建値から{config['offset_atr']:g}ATR有利な指値を置きます。"
                '買いは下、売りは上で待ち、到達した観測価格で新規。元E01が最初に部分返済又は全返済するまでに成立しなければ、その組を見送ります。'
                '成立後は元E01の返済枚数・条件を保ち、返済判断の次観測で実行します。見送った利益も含めて比較します。')
    if 'entry_mode' in config and config.get('execution_mode') != 'IDEAL':
        entries = ('元E01の新規を全て許可', '相手の独立した仮想E01も同方向を保有する時だけ新規',
                   '相手も同方向を保有し、当時清算した収支が料金後0円以上の時だけ新規',
                   '相手も同方向を保有し、建値から現在0.25ATR順行する時だけ新規')
        holdings = ('途中は元E01に従います。',
                    '相手の同方向玉が負け損切りされたら、以後の元E01残枚数の半分を切り上げて保有します。',
                    '相手の同方向玉が負け損切りされたら、残玉を返済します。')
        return (entries[config['entry_mode']]+'。'+holdings[config['holding_mode']]+
                '相手は厳密に過去・180秒以内の資料だけを参照。当行の判断は次の有効価格観測で実行します。'
                '拒否した親組への後入りと、減量後の復元は行いません。両方の仮想E01は変更せず運転します。')
    if 'execution_mode' in config:
        mode = config['execution_mode']
        if mode == 'IDEAL':
            return '元E01の観測価格約定をそのまま使う対照。追加の観測待ちは入れません。'
        source = config['source_id']
        if source == 'E01_G_U':
            original = '元E01の判断を仮想で継続。'
        elif source in ('C_H05_S25', 'C_H05_S50'):
            width = '0.25' if source.endswith('25') else '0.5'
            original = '元E01と、0.5ATR順行時の反対玉5枚／10枚を仮想管理。反対玉の停止幅'+width+'ATR。'
        else:
            original = '元E01と、極値から0.5ATR逆行し双方が反対を支持した時の保険玉を仮想管理。'
        execution = {'G': '各仮想新規・返済をそれぞれ実行し、両建てを維持します。',
                     'N': '仮想の買い枚数−売り枚数だけを実際に保有します。',
                     'F': '仮想の差引枚数だけを保有し、元玉の全返済を確認した後は実建玉をゼロにします。'}[mode]
        return (original+execution+'当行の仮想判断を受け、次の有効価格観測で約定。実損益を仮想判断へ戻しません。'
                '途中で実建玉がゼロでも、同じ仮想親組の全利益・損失・料金を合算します。')
    if 'prepare_atr' in config and config.get('relation'):
        confirm = '双方の最新公開30秒変化が反対向きを支持する時だけ' if config['confirm'] else '価格だけで'
        stops = {0: '建値から0.25ATRで停止', 1: '新規前の順行高値・安値で停止',
                 2: '新規前の順行高値・安値の外1呼値で停止', 3: '建値から0.5ATRで停止'}
        stop = stops.get(config.get('stop_mode', 0), stops[0])
        return (f"元E01の初回玉を変更せず、{config['prepare_atr']:g}ATR順行を準備条件とします。"
                f"観測済みの順行極値から{config['pullback_atr']:g}ATR逆行したら、{confirm}逆方向の5枚／10枚を一度建てます。"
                f'保険玉だけを{stop}。追尾開始0.5ATR・幅0.25ATRで返済。元玉終了後は次の観測で保険も返済します。'
                '通常の押しでも発動し、保険の損失が増える場合があります。')
    if 'relation' in config:
        if not config['relation']:
            return '元E01の入口・途中判断・出口をそのまま使い、追加玉は持ちません。'
        direction = '同方向' if config['relation'] > 0 else '反対方向'
        return (f"元E01の初回5枚／10枚は変更せず、初回建値から{config['start_atr']:g}ATR順行したら{direction}へ同枚数を一度追加。"
                f"追加玉だけを停止幅{config['stop_atr']:g}ATR、追尾開始{config['activation_atr']:g}ATR・幅{config['trail_atr']:g}ATRで返済。"
                '元玉が全返済されたら追加玉も次の観測で返済します。追加損失は元玉の予算とは別に発生します。')
    if 'initial_top' in config:
        q = config['initial_top']
        text = f'TOPIXは{q}枚、日経は{q*2}枚で開始。'
        if config['add_mode'] == 0:
            return text+'追加せず、元E01の広いトレールで返済します。'
        if config['add_mode'] == 1:
            text += '1ATR順行したら上限10枚／20枚まで一度追加。'
        else:
            text += f"初回建値から{config['add_step']:g}ATR進むごとに初回と同枚数を追加。"
        text += '悪化による減量又は2ATRの部分利確で、以後の追加を停止。'
        if config['floor_mode'] == 1:
            text += '追加後の返済線は、組全体の料金後損失を初回の損失予算に収めるよう計算します。'
        elif config['floor_mode'] == 2:
            text += '追加後の返済線は、組全体の料金後収支を0円以上に保つよう計算します。'
        else:
            text += '追加用の新しい返済線は置きません。元E01の組全体1ATRの損失予算は維持します。'
        return text+'価格の飛びで設計した損失枠を超える場合はあります。'
    if 'threshold_atr' in config:
        who = '自己' if config['support_mode'] == 1 else '両銘柄'
        return f"元の準備を続けながら、{who}の最新30秒支持が{config['threshold_atr']:g}ATRを超える時だけ新規注文を有効にします。出口は元GUの広幅又はP1の狭幅を維持します。"
    if 'support_mode' in config:
        labels = ('元の120秒支持保持', '自己の最新30秒支持', '自己の追跡極値後の30秒支持',
                  '双方の最新30秒支持', '双方の追跡極値後の30秒支持')
        return labels[config['support_mode']]+'で新規注文を許可。出口は元GUの広幅又はP1の狭幅を維持します。'
    if 'narrow_fraction' in config:
        text = f"初回玉の{config['narrow_fraction']*100:g}%だけを0.75ATR順行後に幅0.5ATRで先に返済し、残りを元E01で追います。"
        return text+('部分返済後は親組全体の料金後0円となる返済線も置きます。' if config['protect_after_narrow'] else '追加の保護線は置きません。')
    if 'reentry_filter' in config:
        labels = ('利確後1分で再準備', '同調の別周期を待って再準備', '前組の高安再突破を新規条件に追加', '同調の別周期と高安再突破を要求')
        return labels[config['reentry_filter']]+f"。初期損切り{config['stop_atr']:g}ATR、0.75ATR順行後は幅0.5ATRで返済します。"
    if config.get('exit_id') == 'T2':
        return '0.75ATR順行したら幅0.5ATRで返済。'+('利確後だけ1分で再準備します。' if config.get('clock_id')=='P1' else '元の次回準備の時計を維持します。')
    return '両市場の方向確認と反発・反落確認で新規。元の広いトレールと途中減量・部分利確で返済します。'


def main():
    """
    機能: 完了した各段階のみを損益比較に載せ、未達と進行中の段階を区別する。
    引数: なし。
    返り値: None。暗色HTML、公開会計、読む順序を新作業へ保存する。
    """
    analysis = read(HERE / '比較結果.json')
    results, locations, stages, hashes = analyze.collect()
    assert hashes == analysis['入力SHA256'], '先にanalyze.pyを更新してください'
    values = results['observed']
    ranked_choice = next(record['id'] for record in analysis['結果']['observed']
                         if all(record['商品別'][s]['campaigns'] >= 20 for s in SYMBOLS))
    main_ids = ['E01_G_U', 'T2_P1', 'R3_S50', 'Q40_B0']
    for stage in stages:
        primary = stage.get('仕様', {}).get('主仮説', [])
        if isinstance(primary, str):
            primary = [primary]
        main_ids.extend(i for i in primary if i in values)
    main_ids = list(dict.fromkeys(i for i in main_ids if i in values))
    if 'GU_G' in values:
        main_ids.append('GU_G')
    if ranked_choice not in main_ids:
        main_ids.append(ranked_choice)
    labels = dict(E01_G_U='基準：元のE01', T2_P1='悪化した狭幅＋利確後再参加',
                  R3_S50='再同調＋高安更新＋損切り縮小', Q40_B0='4割を早めに利確、残りを継続',
                  K_P50_C1_S2='保険の停止線を直前高安の外へ',
                  GU_G='基準：元E01を次の観測で約定',
                  L_GU_NEXT='基準：元E01を次の観測で約定',
                  L_D50='仮想新規後、0.5ATR有利な指値で待つ',
                  L_D30='参考：0.3ATR有利な指値で待つ',
                  P_E1_H1='相手も同方向なら新規・相手の損切りで半減',
                  C_H05_S25_F='差引保有＋元玉終了時に全返済')
    if ranked_choice != 'E01_G_U':
        if ranked_choice == 'C_H05_S25':
            labels[ranked_choice] = '補助候補：逆玉を単独でトレール'
        elif ranked_choice not in labels:
            labels[ranked_choice] = '参考候補：'+values[ranked_choice]['config']['name']
    rows, main_cells = [], {}
    for identifier in main_ids:
        total = values[identifier]['periods']['全30']
        cells = [html.escape(labels.get(identifier, values[identifier]['config']['name']))+
                 '<br><small>'+identifier+'</small>']
        for s in SYMBOLS:
            cells += [money(total[s]['net']), ratio(total[s]['campaign_profit_share'])]
        rows.append(cells)
        main_cells[identifier] = cells
    latest_primary = []
    for stage in reversed(stages):
        if stage['状態'] != '全場計算済み':
            continue
        latest_primary = stage.get('仕様', {}).get('主仮説', [])
        if isinstance(latest_primary, str):
            latest_primary = [latest_primary]
        break
    featured = list(dict.fromkeys(['E01_G_U', ranked_choice]+latest_primary))
    if any('execution_mode' in values[i]['config'] for i in latest_primary):
        featured = list(dict.fromkeys(['E01_G_U', ranked_choice, 'GU_G']+latest_primary))
    main_table = table(['方法', 'TOPIX収支', '利益割合', '日経収支', '利益割合'],
                       [main_cells[i] for i in featured if i in main_cells])
    improvements = [v['id'] for v in analysis['結果']['observed'] if v['両商品四指標改善']]
    raw_targets = [v['id'] for v in analysis['結果']['observed'] if v['両商品八割']]
    targets = [v['id'] for v in analysis['結果']['observed'] if v['両商品八割']
               and all(v['商品別'][s]['campaigns'] >= 20 for s in SYMBOLS)]
    if improvements:
        review = '基準の収支・金額利益割合・黒字場数・最大下落を両銘柄で同時に改善した候補：'+', '.join(improvements)+'。目標80%と期間別安定性は別に確認します。'
    elif targets:
        review = '金額利益80%の候補はありますが、基準以上の収支と安定性を両立するかは未達です。取引数・活動場数も含めて確認しています。'
    else:
        review = '入口を厳しくしても、損切りを縮めても、元の勝ちを失う副作用がありました。完了した比較では、元E01を超える共通の改善にまだ届いていません。'
    status = '調査継続中。両銘柄で金額利益80%となる解は未達です。' if not targets else '金額利益80%の候補を確認。再現性と安定性の検証を継続中です。'
    if raw_targets and not targets:
        status = '金額利益80%は少数取引の条件のみ。両商品20組以上の候補は未達で、調査を継続中です。'
    if 'C_H05_S25' in values:
        review += (' 独立した逆玉C_H05_S25は収支をほぼ維持し、TOPIXの最大下落を242,036円から193,959円へ約20%低減。'
                   '日経は89,520円から89,085円で、改善は小幅です。収益優位が両銘柄で確立したとはいえません。')
    execution_note = ''
    if 'C_H05_S25_F' in values:
        current = values['C_H05_S25_F']['periods']['全30']
        counterpart = values['GU_G']['periods']['全30']
        separate = values['C_H05_S25_G']['periods']['全30']
        changes = [current[s]['net']-counterpart[s]['net'] for s in SYMBOLS]
        saved_fees = [separate[s]['fees']-current[s]['fees'] for s in SYMBOLS]
        assert all(abs(current[s]['gross']-separate[s]['gross']) < 1e-7 for s in SYMBOLS)
        execution_note = ('<p>差引方式の同じ実行待ちの基準との差はTOPIX'+money(changes[0])+'・日経'+money(changes[1])+'。'
                          ' 両建てからの改善'+money(saved_fees[0])+'・'+money(saved_fees[1])+
                          'は料金削減です。約定待ちの有利・不利とは分けて評価しました。費用ゼロでも利益80%には届きません。</p>')
    peer_cases = ''
    diagnostic_hashes = {}
    if 'P_E1_H1' in values:
        before = values['P_E1_H0']['periods']['全30']
        after = values['P_E1_H1']['periods']['全30']
        changes = [after[s]['net']-before[s]['net'] for s in SYMBOLS]
        execution_note = ('<p>相手の保有を必須にした入口は、TOPIXの利益割合を67.6%へ改善しましたが、'
                          '日経では55.5%で後半赤字。さらに相手損切りで半減すると、TOPIX'+money(changes[0])+
                          '・日経'+money(changes[1])+'。後で回復した勝ちを削った額が、損失削減を上回りました。</p>')
        diagnosis_path = WORK / 'round11/analysis/相手GUの入口見送りと途中縮小の全親分解.json'
        diagnosis = read(diagnosis_path)
        for identifier, digest in diagnosis['結果SHA256'].items():
            assert analyze.sha(WORK / 'round11/observed/results' / (identifier+'.json')) == digest
        diagnostic_hashes[str(diagnosis_path.relative_to(ROOT))] = analyze.sha(diagnosis_path)
        examples = [row for group in diagnosis['具体例'] if group['変更ID']=='P_E1_H1'
                    for field in ('後に回復した自己を先に削った例', '通知後に増えた損失を先に減らした例')
                    for row in group[field]]
        cases = []
        for session, symbol, cid, label in [('2026-10-02_Day', 'TOPIX', 1, '損失を削減'),
                 ('2026-10-07_Night', 'TOPIX', 0, '後の回復利益を失う'),
                 ('2026-10-08_Day', 'NK225', 4, 'この1件の損害が他7件の改善を上回る')]:
            row = next(r for r in examples if (r['session'],r['symbol'],r['組'])==(session,symbol,cid))
            stamp = row['通知自己代理時計']
            name = ('TOPIX ' if symbol=='TOPIX' else '日経 ')+stamp[5:10].replace('-','/')+' '+stamp[11:19]
            cases.append([name, money(row['元収支']), money(row['変更収支']), label])
        peer_cases = ('<h3>相手の損切りで減量するとどうなったか</h3>'+table(
            ['商品・通知時刻', '元の1組', '半減後の1組', '診断'], cases)+
            '<p class="note">通知時に自己も損失でも、後で回復したケースがありました。後の回復は事後診断で、発注条件に使っていません。表は各1組でセッション合計ではありません。</p>')
    stability_rows = []
    if 'L_D50' in values:
        diagnosis_path = WORK / 'round12/analysis/有利指値の入口改善と未成立親の全差分.json'
        diagnostic_hashes[str(diagnosis_path.relative_to(ROOT))] = analyze.sha(diagnosis_path)
        execution_note = ('<p>0.5ATR有利な価格を待つと、成立した取引の入口は改善しましたが、戻らず伸びた勝ちを逃しました。'
                          '浅い0.2ATRは全体収支を改善（TOPIX721,398円・日経250,400円）。ただし日経の最大下落は90,205円から103,005円へ増加。'
                          '参考の0.3ATRも日経の後14場は−8,300円で、全日安定と利益80%には未達です。</p>')
    for identifier in dict.fromkeys(['E01_G_U', ranked_choice]):
        record = next(r for r in analysis['結果']['observed'] if r['id']==identifier)
        for symbol in SYMBOLS:
            stat = record['商品別'][symbol]
            stability_rows.append([identifier, 'TOPIX' if symbol=='TOPIX' else '日経',
                f"{stat['positive_sessions']}/30", money(-stat['max_drawdown']),
                money(record['期間別']['前16'][symbol]['net']),
                money(record['期間別']['後14'][symbol]['net']),
                money(record['場の安定性'][symbol]['最大利益三場除外収支'])])
    stability_table = table(['方法', '商品', '黒字場', '最大下落', '前16場', '後14場', '大勝ち3場を除く収支'], stability_rows)
    progress = []
    for stage in stages:
        progress.append(html.escape(stage['段階']+'：'+stage['状態'])+
                        (f"（{stage['条件数']}条件）" if '条件数' in stage else ''))
    comparisons = []
    for model, label in [('observed', '観測現在値で約定'), ('specified', '指定線で約定する対照')]:
        rows = []
        for record in analysis['結果'][model]:
            cells = [record['id']]
            for s in SYMBOLS:
                v = record['商品別'][s]
                cells += [money(v['net']), ratio(v['campaign_profit_share']),
                          money(-v['max_drawdown']), f"{v['positive_sessions']}/30", str(v['campaigns'])]
            rows.append(cells)
        comparisons.append('<h3>'+label+'</h3>'+table(
            ['方法', 'TOPIX収支', '利益割合', '最大下落', '黒字場', '親組数', '日経収支', '利益割合', '最大下落', '黒字場', '親組数'], rows))
    payload = {identifier: dict(name=value['config']['name'], description=describe(value['config']), rows=value['rows'], total=value['periods']['全30'])
               for identifier, value in values.items()}
    selected = targets[0] if targets else ranked_choice
    options = ''.join('<option value="'+i+'"'+(' selected' if i == selected else '')+'>'+html.escape(i+'：'+value['name'])+'</option>'
                      for i, value in payload.items())
    document = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>損失原因と改善の反復結果</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#10151e;color:#e7edf6;font:16px/1.7 system-ui,"Yu Gothic UI",Meiryo,sans-serif}main{max-width:1180px;margin:auto;padding:28px 22px 60px}h1{font-size:28px;line-height:1.45}h2{font-size:20px}h3{font-size:17px}.status{border-left:4px solid #efc57f;padding-left:16px;font-size:18px}.note,small{font-size:13px;color:#b8c7da}section,details{background:#18222f;border:1px solid #344459;border-radius:10px;padding:16px;margin:20px 0}summary{cursor:pointer;font-weight:650}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}td,th{padding:9px;border-bottom:1px solid #344459;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}.gain{color:#78dfb7}.loss{color:#ff9aaa}a{color:#91c1ff}select{font:inherit;width:100%;padding:10px;background:#111a27;border:1px solid #4d6482;color:#e7edf6;margin:10px 0}figure{margin:20px 0}img{max-width:100%;height:auto}.pending{color:#edca87}details[open]>summary{margin-bottom:14px}@media(max-width:650px){main{padding:16px 12px 40px}h1{font-size:23px}section,details{padding:12px}}
</style></head><body><main>
<!--
[コンポーネント概要]
#causes は保存原本から確認した損失原因を示す。
#comparison は各段階の事前主仮説と基準の比較を示す。
#method は全セッション表に表示する方法を選ぶ。
#session-table は選択方法の全30場と合計の利益・損失・収支を示す。
#all-results は全固定条件と約定モデルの違いを示す。
外部通信は行わず、埋め込んだ保存会計のみを表示する。
-->
<p class="note">00083 · 保存済み30セッション · 手数料後</p>
<h1>赤字が増えた理由と、改善の検証</h1><p class="status">__STATUS__</p>
<section id="causes"><h2>何が赤字を増やしたか</h2>
<p><b>利確直後でも、次の上昇・下落が続く根拠は足りませんでした。</b> 両市場の方向表示が続く中で小さな反発・反落へ入り直し、伸びずに損切りする取引が増えています。古いデータを読むバグではありません。</p>
<p>狭幅版は0.75ATR順行すると追尾を始め、最初に守れる幅は約0.25ATR。それに対して初期損切りは0.75ATRのままです。損失額のほぼ全ては、追尾開始前に失敗した組でした。</p>
<p><b>追加玉を守る返済線が、初回玉の利益まで切っていました。</b> 9月28日デイの同じ売りでは、初回2枚／4枚を追加せず持つとTOPIX＋47,335円・日経＋20,112円。追加後に全玉へ保護線を置くと、小さな戻りでTOPIX−9,498円・日経−5,064円となり、その後の下落を逃しました。この原因を受けて初回玉と追加玉の別管理を検証しました。</p>
<p class="note">この分類は事後の価格経路による診断です。入口で負ける組を見抜けた証明ではありません。手数料前でも追加入口は赤字でした。</p>
</section>
<section id="comparison"><h2>原因に対する改修はどうだったか</h2>__MAIN_TABLE__
<p class="note">TOPIXミニ／日経マイクロ、片方向上限10枚／20枚。基準は初回5枚／10枚。数量改修では初回枚数と追加条件を変更します。全てセッション内返済。利益割合＝新規から全返済までの組単位の利益÷（利益＋損失）。勝率ではありません。</p>
<p>__REVIEW__</p>__EXECUTION__
</section>
<details id="stability"><summary>元E01と参考候補の期間別安定性を見る</summary>__STABILITY__
<p class="note">参考候補は全条件を計算した後の比較順位です。前16場・後14場とも既知データで、未見検証ではありません。横ばいはTOPIX1場・日経6場だけで、その相場の安定性は未確立です。</p></details>
<details id="cases"><summary>具体的にどの値動きで失敗したか</summary>
<figure><img src="case_topix_20260925.svg" alt="TOPIXの前高値未更新での買い直しと損切り"><figcaption class="note">TOPIX：前の高値へ戻れていない位置で買い直し、伸びずに損切り。</figcaption></figure>
<figure><img src="case_nk225_20260922.svg" alt="日経の前高値更新後の買い直しと損切り"><figcaption class="note">日経：高値更新・同調の再成立を確認しても失敗した反例。確認を加えるだけでは解決しません。</figcaption></figure>
<figure><img src="case_allocation_topix_20260928.svg" alt="TOPIXの追加後の返済線が初回玉まで早期返済した例"><figcaption class="note">TOPIX：追加後の全玉保護が、その後の下落で得られた初回玉の利益を失う例。</figcaption></figure>
<figure><img src="case_allocation_nk225_20260928.svg" alt="日経の追加後の返済線が初回玉まで早期返済した例"><figcaption class="note">日経：同じ原因を確認。図の金額は各1組で、セッション全体ではありません。返済後の値動きは事後診断です。</figcaption></figure>
__PEER_CASES__
</details>
<details id="sessions"><summary>方法を選び、全30セッションの損益を見る</summary>
<label for="method">表示する方法</label><select id="method">__OPTIONS__</select><p id="method-description" class="note"></p><div id="session-table"></div>
<p class="note">全方法で同じ保存期間を使用。無取引を黒字に数えません。</p></details>
<details id="all-results"><summary>全条件・最大下落・黒字セッション数を見る</summary>__ALL__
<p class="note">__PROGRESS__</p>
<p class="note">差引実行の13条件は観測約定だけで比較。仮想判断を受けた次の有効観測で実行する方式です。指定線対照へ同じ結果を転記していません。</p>
<p class="note">参考順は商品別「収支÷最大下落」の小さい方。参考候補には両商品20親組以上を要求。少数条件も全表へ掲載し、無取引を勝ちに含めません。金額を銘柄間で合算しません。</p></details>
<footer class="note">既知データ内の探索です。前半・後半とも未見検証ではありません。ラージの保存現在値に小型商品の倍率と立会手数料を適用。売買気配差・小型との約定差・固定5秒遅延は含めません。<br>
<a href="README.md">読む順序・再現方法</a> ／ <a href="公開会計.json">全条件の公開会計</a></footer>
</main><script id="accounting" type="application/json">__DATA__</script><script>
const accounting=JSON.parse(document.getElementById('accounting').textContent);
/**
 * 機能: 円金額を符号と色で表示する。
 * @param {number} value - 料金後金額。
 * @returns {string} 表示用HTML。
 */
function money(value){const n=Math.round(value);return n===0?'0円':'<span class="'+(n>0?'gain':'loss')+'">'+(n>0?'+':'')+n.toLocaleString('ja-JP')+'円</span>';}
/**
 * 機能: 選択した方法の全セッションと合計を保存会計から描画する。
 * 引数: なし。
 * 返り値: undefined。
 */
function renderSessions(){
 const value=accounting[document.getElementById('method').value];
 document.getElementById('method-description').textContent=value.description;
 const names=[...new Set(value.rows.map(row=>row.session))].sort();
 let body='';
 for(const name of names){let cells='<td>'+name.replace('_Day',' デイ').replace('_Night',' ナイト')+'</td>';
  for(const symbol of ['TOPIX','NK225']){const row=value.rows.find(r=>r.session===name&&r.symbol===symbol);cells+='<td>'+money(row.campaign_profit)+'</td><td>'+money(-row.campaign_loss)+'</td><td>'+money(row.net)+'</td>';}
  body+='<tr>'+cells+'</tr>';}
 let total='<td>全30合計</td>';for(const symbol of ['TOPIX','NK225']){const row=value.total[symbol];total+='<td>'+money(row.campaign_profit)+'</td><td>'+money(-row.campaign_loss)+'</td><td>'+money(row.net)+'</td>';}
 document.getElementById('session-table').innerHTML='<div class="scroll"><table><thead><tr><th>セッション</th><th>TOPIX利益</th><th>TOPIX損失</th><th>TOPIX収支</th><th>日経利益</th><th>日経損失</th><th>日経収支</th></tr></thead><tbody>'+body+'<tr>'+total+'</tr></tbody></table></div>';
}
document.getElementById('method').addEventListener('change',renderSessions);renderSessions();
</script></body></html>'''
    replacements = dict(STATUS=html.escape(status), MAIN_TABLE=main_table, REVIEW=html.escape(review), PROGRESS=' ／ '.join(progress),
                        OPTIONS=options, ALL=''.join(comparisons), STABILITY=stability_table,
                        EXECUTION=execution_note,
                        PEER_CASES=peer_cases,
                        DATA=json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('</', '<\\/'))
    for key, value in replacements.items():
        document = document.replace('__'+key+'__', value)
    assert '__STATUS__' not in document
    PUBLIC.mkdir(parents=True, exist_ok=True)
    for name in ('case_topix_20260925.svg', 'case_nk225_20260922.svg',
                 'case_allocation_topix_20260928.svg', 'case_allocation_nk225_20260928.svg'):
        shutil.copyfile(HERE / name, PUBLIC / name)
    (PUBLIC / MAIN).write_text(document, encoding='utf-8')
    published = dict(状態=status, 分析=analysis, 各結果={m: {i: dict(config=v['config'], rows=v['rows'], periods=v['periods'])
                                                        for i, v in rv.items()} for m, rv in results.items()})
    (PUBLIC / '公開会計.json').write_text(json.dumps(published, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (PUBLIC / 'README.md').write_text(f'''# 再参加の損失原因と改善の反復検証

最初に [{MAIN}]({MAIN}) を開いてください。調査は継続中です。

1. 主HTMLの原因と各段階の比較。
2. 必要なら具体例の図、方法選択による全30場、全固定条件を開く。
3. 再集計は [公開会計.json](公開会計.json)。因果検査・独立会計・原本照合は `../../work/wave_v87/audit`。

初期の原因診断を受けて条件を作った既知データ内の研究です。未知の将来で同じ成績を証明したものではありません。
旧00082の結果・実装は変更していません。現在セッションAPIと実注文は使っていません。

再生成（プロジェクトルート）:

```text
python -X utf8 work/wave_v87/report/analyze.py
python -X utf8 work/wave_v87/report/build.py
```

各改修の売買再生は `work/wave_v87/roundN/research.py --run`。各段階の `事前固定.json` と指紋を確認してから実行します。
''', encoding='utf-8')
    proof = dict(全合格=True, 状態=status, 改修条件数=sum(s.get('条件数', 0) for s in stages if s['状態']=='全場計算済み'),
                 比較条件数=len(values), 詳細セッション数=30, 主表示=featured, 各段階主仮説=main_ids,
                 四指標改善=improvements, 八割候補=targets, 入力SHA256=hashes,
                 八割観測条件=raw_targets, 参考候補の活動基準='両商品で20親組以上。少数条件も省略せず全表へ掲載。',
                 診断資料SHA256=diagnostic_hashes,
                 HTML_SHA256=analyze.sha(PUBLIC / MAIN))
    (HERE / '公開数値照合.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(PUBLIC / MAIN)


if __name__ == '__main__':
    main()
