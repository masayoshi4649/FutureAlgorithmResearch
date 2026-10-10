"""補充監視の原因分析を、短い説明・表・検算可能な CSV にまとめる。"""

import csv
import hashlib
import html
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
OUT = ROOT / 'アルゴリズム調査/00055_補充監視が赤字になった原因'
TITLE = '赤字の原因と理論の検証'
SYMBOLS = ('TOPIX', 'NK225')
NAMES = {'TOPIX': 'TOPIX mini', 'NK225': 'NK225 micro'}
FAMILIES = {'R1': '補充後の反転', 'R2': '補充停止後の突破', 'R3': '補充価格の移動に追従'}
MODES = {'A': '壁＋即時トレール（元条件）', 'B': '壁だけ', 'C': '即時トレールだけ', 'D': '壁＋1幅順行後トレール'}


def read(relative: str) -> dict:
    """機能: 作業内の保存済み JSON を読む。

    引数: relative(str) は作業フォルダからの相対パス。
    返り値: 読み取った内容(dict)。原本や売買条件は変更しない。
    """
    return json.loads((WORK / relative).read_text(encoding='utf-8'))


def esc(value: object) -> str:
    """機能: 表示文字列を HTML 用にエスケープする。

    引数: value(object) は表示する値。
    返り値: 安全な表示文字列(str)。
    """
    return html.escape(str(value), quote=True)


def number(value: float, digits: int = 0, signed: bool = False) -> str:
    """機能: 数値を桁区切り付きの文字列にする。

    引数: value(float) は値、digits(int) は小数桁、signed(bool) は正号の有無。
    返り値: 書式化した文字列(str)。欠測値はダッシュで示す。
    """
    if value is None:
        return '—'
    return format(value, f'{"+" if signed else ""},.{digits}f').replace('-', '−')


def money(value: float) -> str:
    """機能: 符号と色を付けて収支を表示する。

    引数: value(float) は円単位の収支。
    返り値: HTML の断片(str)。
    """
    color = 'positive' if value > 0 else 'negative' if value < 0 else 'flat'
    return f'<span class="{color}">{number(value, signed=True)}</span>'


def table(headers: list[str], rows: list[list[str]], css: str = '') -> str:
    """機能: 横スクロール可能な表を作る。

    引数: headers(list[str]) は見出し、rows(list[list[str]]) は HTML セル、css(str) は追加クラス。
    返り値: 完成した HTML 表(str)。セルのエスケープは呼出側で行う。
    """
    head = ''.join(f'<th scope="col">{esc(x)}</th>' for x in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{x}</td>' for x in row) + '</tr>' for row in rows)
    return f'<div class="table-wrap"><table class="{css}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def export_csv(name: str, rows: list[dict]) -> None:
    """機能: 計算結果を UTF-8 BOM 付き CSV に保存し、全セルを再読込で照合する。

    引数: name(str) は出力ファイル名、rows(list[dict]) は同じ列を持つ行。
    返り値: なし(None)。数式や新しい損益計算は追加しない。
    """
    path = OUT / name
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        actual = list(csv.DictReader(stream))
    expected = [{k: '' if v is None else str(v) for k, v in row.items()} for row in rows]
    assert actual == expected, name


def main() -> None:
    """機能: 確定済み診断・出口対照から短い HTML と詳細 CSV を生成する。

    引数: なし。
    返り値: なし(None)。元結果の総額と場別 CSV を検算してから保存する。
    """
    entry = read('entry/入口固定時点の診断.json')
    exits = read('exit/出口対照結果.json')
    assessment = read('報告評価.json')
    episodes = read('review/表示回復と出来高の独立照合.json')
    risk = read('元手法の初期保護線.json')
    decomposition = read('exit/入口集合変化の会計分解.json')
    OUT.mkdir(parents=True, exist_ok=True)
    assert len(exits['methods']) == 12
    assert all(len(m['accounts']) == 46 for m in exits['methods'])

    # ----------------------------------------
    # 元条件の勝率と将来方向は、既に計算済みの診断をそのまま表示する。
    accounting_rows, direction_rows, direction_details, entry_csv = [], [], [], []
    for method in entry['手法別']:
        family = method['手法ID'].split('_')[0]
        for symbol in SYMBOLS:
            data = method['銘柄別'][symbol]
            account = data['元売買の中値会計']
            accounting_rows.append([
                family, NAMES[symbol], f"{account['同値除外勝率'] * 100:.2f}%",
                f"{account['一枚平均勝ち負け比']:.2f}倍",
                f"{account['損益分岐勝率'] * 100:.2f}%", money(account['収支円']),
            ])
            cells = [family, NAMES[symbol]]
            for seconds in (60, 300, 900, 1800):
                value = data['固定時点別'][str(seconds)]
                ticks = value['呼値']
                cells.append(f"<strong>{number(ticks['entry加重平均'], 3, True)}</strong><small>有効 {value['有効率'] * 100:.1f}%</small>")
                direction_details.append([
                    family, NAMES[symbol], f'{seconds // 60}分',
                    number(ticks['entry加重平均'], 3, True),
                    number(ticks['場平均の等ウェイト平均'], 3, True),
                    f"{ticks['二十三場中で場平均が正の場数']}/23",
                    f"{ticks['正方向割合'] * 100:.1f}% / {ticks['逆方向割合'] * 100:.1f}% / {ticks['同値割合'] * 100:.1f}%",
                    f"{value['有効入口数']:,}/{value['入口数']:,}",
                ])
                for session in value['各場']:
                    entry_csv.append({
                        '手法ID': method['手法ID'], '銘柄': symbol, '経過秒': seconds,
                        'セッション': session['セッション'], '入口数': session['入口数'],
                        '有効入口数': session['有効入口数'], '欠測数': session['欠測数'],
                        '平均方向付き呼値': session['平均呼値'], '平均方向付きbps': session['平均bps'],
                    })
            direction_rows.append(cells)

    # ----------------------------------------
    # 12 対照の総額・場別表・枚数は、出口台帳の会計値から展開する。
    exit_rows, full_sessions, session_csv = [], [], []
    for method in exits['methods']:
        row = [method['id'], MODES[method['mode']]]
        for symbol in SYMBOLS:
            totals = method['summary'][symbol]
            chosen = [a for a in method['accounts'] if a['symbol'] == symbol]
            for field in ('profit', 'loss', 'net', 'win_qty', 'loss_qty', 'flat_qty', 'cycles'):
                assert sum(a[field] for a in chosen) == totals[field], (method['id'], symbol, field)
            assert totals['profit'] - totals['loss'] == totals['net']
            row.extend([number(totals['profit']), number(totals['loss']), money(totals['net'])])
        exit_rows.append(row)
        session_rows = []
        for account in sorted(method['accounts'], key=lambda a: (a['session'], SYMBOLS.index(a['symbol']))):
            assert account['profit'] - account['loss'] == account['net']
            record = {
                '手法ID': method['id'], '入口条件': FAMILIES[method['family']], '出口条件': MODES[method['mode']],
                '銘柄': account['symbol'], 'セッション': account['session'],
                '利益円': account['profit'], '損失円': account['loss'], '収支円': account['net'],
                '利益返済枚数': account['win_qty'], '損失返済枚数': account['loss_qty'],
                '同値返済枚数': account['flat_qty'], '勝ち枚数引く負け枚数': account['win_qty'] - account['loss_qty'],
                '往復組数': account['cycles'],
                '元条件と共通入口数': account['entry_comparison']['common_entries'],
                '追加入口数': account['entry_comparison']['added_entries'],
                '除外入口数': account['entry_comparison']['removed_entries'],
            }
            session_csv.append(record)
            session_rows.append([
                esc(account['session']), NAMES[account['symbol']], number(account['profit']), number(account['loss']),
                money(account['net']), f"{account['win_qty']:,} / {account['loss_qty']:,} / {account['flat_qty']:,}",
            ])
        full_sessions.append(f'<details><summary>{method["id"]}：{MODES[method["mode"]]}・全23場×2銘柄</summary>' +
                             table(['セッション', '銘柄', '利益円', '損失円', '収支円', '勝ち / 負け / 同値枚数'], session_rows) + '</details>')
    assert len(session_csv) == 552 and len(entry_csv) == 552
    export_csv('出口12対照_全セッション損益.csv', session_csv)
    export_csv('入口後固定時点_場別方向診断.csv', entry_csv)

    # ----------------------------------------
    # 解釈の限界や検証済みの数値は折畳みに分離し、最初の画面を短くする。
    episode_rows = []
    for symbol in SYMBOLS:
        value = episodes['銘柄別'][symbol]
        episode_rows.append([f'{symbol}（ラージ板）', number(value['表示回復完了数']), number(value['周期中出来高ゼロ数']),
                             f"{value['周期中出来高既知でゼロの割合'] * 100:.2f}%"])
    risk_rows = [[x['手法'].split('_')[0], NAMES[x['銘柄']], number(x['壁保護線距離中央値呼値'], 1),
                  f"{x['壁保護線距離2呼値以下割合'] * 100:.1f}%"] for x in risk['集計']]
    decomp_rows = []
    for value in decomposition['details']:
        if value['method'].endswith('_A'):
            continue
        assert value['common_delta'] + value['added_variant_net'] - value['removed_baseline_net'] == value['total_delta']
        decomp_rows.append([
            value['method'], NAMES[value['symbol']], money(value['total_delta']), money(value['common_delta']),
            money(value['added_variant_net']), money(-value['removed_baseline_net']),
        ])
    findings = ''.join(f'<p>{esc(x)}</p>' for x in assessment['findings'])
    method_map = ' ／ '.join(f'<b>{k}</b> {v}' for k, v in FAMILIES.items())
    style = '''
    :root{color-scheme:dark;--bg:#0b111a;--panel:#121c2a;--text:#e5ebf5;--muted:#a9b7cc;--line:#2a3b50;--accent:#76b9ff}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.7 system-ui,"Yu Gothic UI",sans-serif}
    main{max-width:1190px;margin:0 auto;padding:34px 24px 64px}h1{font-size:30px;margin:5px 0 15px;line-height:1.4}
    h2{font-size:21px;margin:0 0 12px}h3{font-size:17px}p{margin:9px 0 15px}a{color:var(--accent)}
    .eyebrow,.muted,small{color:var(--muted)}.eyebrow{font-size:13px;letter-spacing:.07em}small{display:block;font-size:12px;font-weight:400}
    .lead{border-left:4px solid #eeb864;background:#24241e;padding:18px 20px;font-size:18px;line-height:1.8}
    .scope{font-size:13px;color:var(--muted)}section{margin-top:28px;padding:23px;background:var(--panel);border:1px solid var(--line);border-radius:10px}
    .table-wrap{overflow-x:auto;margin:14px 0}table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
    th,td{padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap;text-align:right;vertical-align:middle}
    th{background:#1c2a3c;color:#cbd8e9;font-weight:600}td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){text-align:left}
    tbody tr:nth-child(even){background:#162130}tr:hover td{background:#1b2b3e}.positive{color:#76dfbe}.negative{color:#ff969e}.flat{color:var(--muted)}
    .method-map{padding:10px 0;color:#b6c7dd;font-size:14px}.note{font-size:13px;color:var(--muted)}
    details{border:1px solid var(--line);border-radius:7px;margin-top:13px;padding:12px 15px}details[open]{padding-bottom:16px}
    summary{cursor:pointer;color:#c0d6ef;font-weight:600}details p{font-size:14px}.downloads{display:flex;gap:10px;flex-wrap:wrap;margin:15px 0}
    .downloads a{border:1px solid #3e5b7d;padding:8px 13px;border-radius:6px;text-decoration:none;background:#19283a;font-size:13px}
    footer{margin-top:24px;font-size:12px;color:var(--muted)}.definitions li{margin:7px 0}.definitions{padding-left:22px}
    @media(max-width:700px){main{padding:22px 12px 40px}section{padding:17px 12px}h1{font-size:25px}.lead{font-size:16px;padding:14px}th,td{padding:9px}.method-map{line-height:2}}
    '''
    content = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{TITLE}</title><style>{style}</style></head>
<body>
<!--
[コンポーネント概要]
main は原因分析レポートです。表示回復の観測、入口後の方向、出口の対照を分離します。
.table-wrap は狭い画面でも数値を省略しない横スクロール領域です。
details は厳密定義と全セッションを任意で開く領域です。売買の再計算は行いません。
.positive と .negative は暗色背景で収支の正負を識別する表示色です。
-->
<main><div class="eyebrow">作業 00055 · 保存済み23セッションの原因分析</div><h1>{TITLE}</h1>
<div class="lead">板の補充を見る考え方だけでは、入った後の利益までは保証できません。<br><strong>今回の入口・出口の組合せを、安定した共通手法として採用できる結果は得られませんでした。</strong></div>
<p class="scope">対象：2026/09/21 デイ〜10/06 デイの23場。中値評価・費用0、TOPIX mini 5枚／NK225 micro 10枚、追加なし、全て場内返済。ATR不使用。中値は価格評価の基準で、実約定を保証する価格ではありません。</p>
<div class="method-map">{method_map}</div>

<section><h2>1. 赤字の直接的な理由：利益の大きさに勝率が届かなかった</h2>
<p>平均利益は平均損失の約1.8〜3倍でしたが、全6組で収支がゼロになる勝率を下回りました。これは損益の分解であり、板の動きそのものが原因だと証明する数字ではありません。</p>
{table(['入口', '銘柄', '実際の勝率', '1枚平均利益／損失', '損益分岐勝率', '23場合計収支円'], accounting_rows)}
<p class="note">勝率・損益分岐勝率は同値決済を除外。分岐勝率＝平均損失÷（平均利益＋平均損失）。元条件Aの実績です。</p></section>

<section><h2>2. 「数量が戻った」から「支え続ける」へ飛躍していた</h2>
<p>全10段の回復周期の62〜67%では、周期中の出来高増加が保存値上ありませんでした。表示数量の回復を数えるだけでは、売買を受け止めて補充したことも、その価格で今後支え続けることも確認できません。</p>
<p class="note"><strong>入口に採用された壁だけの割合ではありません。</strong>この事実だけで損失の原因と断定はしません。</p>
<details><summary>回復周期の全数と、観測できないこと</summary>
{table(['銘柄', '表示回復完了周期', '周期中の出来高増加0', '出来高増加0の割合'], episode_rows)}
<p>価格ごとの周期は重複します。出来高は市場全体の累積値であり、増加していてもその壁での約定とは限りません。同時に起きる約定・取消・追加の内訳や参加者の心理は、この記録から特定できません。</p></details></section>

<section><h2>3. 入った後の方向は、小さく、不揃いだった</h2>
<p>採用できた入口の1分後は平均+0.015〜+0.158呼値。5〜30分後は手法と銘柄で正負が分かれ、確認後の継続性が共通して強い結果にはなりませんでした。</p>
{table(['入口', '銘柄', '1分後', '5分後', '15分後', '30分後'], direction_rows)}
<p class="note">各セルは入口方向への平均中値変化［呼値］と測定有効率。正なら順行、負なら逆行。1呼値＝TOPIX 0.5pt／NK225 10円。元の出口と無関係な固定時点の診断で、実行可能利益ではありません。有効率47〜67%のため、全入口へ一般化できません。</p>
<details><summary>相関した入口をまとめた場別平均・正負割合</summary>
{table(['入口', '銘柄', '時点', '入口平均呼値', '場の等加重平均呼値', '平均が正の場', '正 / 負 / 同値', '有効 / 全入口'], direction_details)}
<p>多数の近接入口を独立した試行とは扱いません。補充なしの対照がないため、補充の追加的な予測力を測った検証ではありません。</p></details></section>

<section><h2>4. 出口だけを変えても、共通の黒字にはならなかった</h2>
<p>12対照で両銘柄同時に黒字のものはありません。例外のR2・壁だけはTOPIXで<strong>+415,000円</strong>でしたが、NKは−120,000円、TOPIXの黒字場は11/23場で、安定した共通手法には達していません。</p>
{table(['条件', '出口', 'TOPIX利益円', 'TOPIX損失円', 'TOPIX収支円', 'NK利益円', 'NK損失円', 'NK収支円'], exit_rows)}
<p class="note">A＝元条件。壁は入口時の補充価格の外1呼値に置く保護線、1幅は場の観測始値の0.05%を呼値に切り上げた固定追跡幅（最低2呼値）。Dは1幅順行してから追跡を開始。いずれも場末には返済します。</p>
<p>R3の保護線は中央値1.5呼値と近い一方、壁の保護線を外したときの共通入口の決済差は6組中5組で悪化しました。「損切りが近いだけ」とは説明できません。</p>
<div class="downloads"><a href="出口12対照_全セッション損益.csv" download>全552口座の損益・枚数 CSV</a><a href="入口後固定時点_場別方向診断.csv" download>入口後の場別方向 CSV</a></div>
<details><summary>出口変更で入口集合も変わるため、純粋な出口効果ではない</summary>
<p>候補の時刻・方向は固定していますが、長く保有すると次の候補を見送り、返済後の休止時間も変わります。下表は総額差を会計上分けたもので、共通入口も運用履歴で選ばれた部分集合です。</p>
{table(['条件', '銘柄', 'Aとの差円', '共通入口の決済差円', '追加入口の収支円', '見送りによる差円'], decomp_rows)}
<p>R2_B TOPIXは最大利益場を除いても+198,750円ですが、取引勝率は全往復組に対して5.1%、最大資産減少は523,750円。少数の大きな利益と、入らなくなる損失取引の両方が総額に影響しています。</p></details>
<details><summary>元条件の保護線の近さ</summary>{table(['入口', '銘柄', '中値からの距離中央値［呼値］', '2呼値以内の割合'], risk_rows)}<p>入口時に既知だった線までの距離です。近さだけで損失原因を証明する集計ではありません。</p></details>
<details><summary>12対照の各セッション利益・損失・収支・枚数</summary><p class="note">枚数は決済の延べ枚数。再エントリーを含むため、同時保有枚数とは異なります。</p>{''.join(full_sessions)}</details></section>

<section><h2>今回の判定</h2><p><strong>市場の一般原理を否定したのではなく、表示回復から未来の方向と支持の持続を読む今回の具体条件を、この保存期間では支持できなかった</strong>、という結果です。出口の変更で改善する例はあっても、入口の予測を含めて安定して稼げる証拠にはなりませんでした。</p>
<details><summary>判断の根拠・未検証事項・厳密な定義</summary>
{findings}<p>{esc(assessment['next_required_evidence'])}</p>
<ul class="definitions"><li>将来診断の起点は元条件の実新規約定行の中値。指定秒後以下の最後の有効原本行を採用し、同時刻の複数行は原本順の最後を使います。未来価格は診断にのみ使用します。</li>
<li>対象時点が場の返済判断時刻を超える場合、または採用行の約定時計が対象時点から5秒超古い場合は欠測。保存時刻は約定時計で、受信時刻の鮮度を保証しません。</li>
<li>23場は既に研究に使用した保存期間です。今回の対照を固定しても真の未見検証ではなく、普遍的な理論の反証や十分な統計検定とはしません。</li>
<li>板の偏りと同区間の価格形成に関する研究は、今回のルールで観測後に利益が出ることの証明ではありません。研究の位置付けと引用は下記の独立反証に記載しています。</li></ul>
<p><a href="../../work/wave_v58/review/理論の独立反証.md">理論の独立反証・研究根拠</a> ／ <a href="../../work/wave_v58/entry/入口固定時点の診断.json">入口診断の元データ</a> ／ <a href="../../work/wave_v58/exit/出口対照結果.json">出口12対照の台帳</a> ／ <a href="../../work/wave_v58/review/">独立監査資料</a></p>
</details></section>
<footer>保存原本のみ使用・現在セッションAPI取得0回・新たな勝者探索なし。00054の元結果は変更していません。<br><a href="README.md">読む順序と分析範囲</a> ／ <a href="../index.html">調査一覧</a></footer>
</main></body></html>'''
    report = OUT / f'{TITLE}.html'
    report.write_text(content, encoding='utf-8')
    evidence = {
        '合格': True, '入口会計行数': len(accounting_rows), '固定時点集計行数': len(direction_details),
        '出口条件数': len(exits['methods']), '出口セッションCSV行数': len(session_csv),
        '入口場別CSV行数': len(entry_csv), 'CSV全セル再読込一致': True,
        '全24総計と場別の利益損失収支枚数一致': True, '全18会計分解の総額差一致': True,
        'HTML_SHA256': hashlib.sha256(report.read_bytes()).hexdigest(),
        '元データSHA256': {str(p.relative_to(WORK)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            WORK / 'entry/入口固定時点の診断.json', WORK / 'exit/出口対照結果.json',
            WORK / 'review/表示回復と出来高の独立照合.json', WORK / '報告評価.json')},
    }
    (HERE / '出力照合.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    main()
