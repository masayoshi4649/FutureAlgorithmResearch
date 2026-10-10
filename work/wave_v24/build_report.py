"""敵対検証の結果を、短い本文と展開式の詳細に整理する。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from html import escape
import json
from pathlib import Path
import shutil

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
NAME = '00019_X05の敵対的検証'
OUT = ROOT / 'アルゴリズム調査' / NAME
SYMBOLS = ['TOPIX', 'NK225']
LABELS = {'TOPIX': 'TOPIXミニ', 'NK225': 'NK225マイクロ'}


def read(name: str) -> object:
    """機能: 保存済みの検査結果を読む。

    引数: name (str) ファイル名。返り値: JSONの内容 (object)。
    """
    return json.loads((WORK / name).read_text(encoding='utf-8'))


def yen(value: float, signed: bool = True) -> str:
    """機能: 金額を符号付きで表示する。

    引数: value (float)、signed (bool)。返り値: 表示文字列 (str)。
    """
    value = round(value)
    return f'{value:+,}' if signed and value else f'{value:,}'


def table(head: list[str], rows: list[list[str]]) -> str:
    """機能: 横スクロール可能な表を組み立てる。

    引数: head (list[str]) 見出し、rows (list[list[str]]) セル。返り値: HTML (str)。
    """
    return '<div class="scroll"><table><thead><tr>' + ''.join(
        f'<th scope="col">{escape(x)}</th>' for x in head
    ) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{escape(str(x))}</td>' for x in row) + '</tr>' for row in rows
    ) + '</tbody></table></div>'


def money_cells(row: dict) -> list[str]:
    """機能: 利益・損失・収支と決済枚数を同じ順序に整える。

    引数: row (dict) 集計。返り値: 表示セル (list[str])。
    """
    win, loss = int(row['profit_units']), int(row['loss_units'])
    return [yen(row['gross_profit_yen'], False), yen(row['gross_loss_yen'], False),
            yen(row['net_yen']), str(win), str(loss), yen(win - loss)]


def session_name(value: str) -> str:
    """機能: セッション名を日本語へ整える。

    引数: value (str)。返り値: 日本語の表示名 (str)。
    """
    return value.replace('_Day', ' 昼').replace('_Night', ' 夜')


def main() -> None:
    """機能: 結果を再計算せず新しい報告書と作業一覧を更新する。

    引数: なし。返り値: なし (None)。過去作業・入力データは変更しない。
    """
    OUT.mkdir(exist_ok=True)
    cases = read('枝除去と感度.json')
    by_id = {x['id']: x for x in cases}
    base, fixed = by_id['基準_X05'], by_id['固定_F32']
    controls = read('反証対照の要約.json')
    execution = read('exec_adversarial.json')
    branches = read('branch_attribution.json')
    statistics = read('statistical_adversarial.json')
    assert len(cases) == 30 and controls['乱数prefix一致'] == 104
    assert branches['旧入力コード不変'] and statistics['原本と前回成果変更なし']

    # ----------------------------------------
    # 期間・週・セッションの数値は再生済み集計から生成する。
    main_rows, session_rows, week_rows = [], [], []
    for symbol in SYMBOLS:
        for label, case in [('X05_G08：手法を切替', base), ('F32_G08：固定', fixed)]:
            s = case['symbols'][symbol]
            main_rows.append([LABELS[symbol], label, yen(s['gross_profit_yen'], False),
                              yen(s['gross_loss_yen'], False), yen(s['net_yen']),
                              f"{s['money_ratio']:.2f}", f"{s['average_unit_payoff']:.2f}"])
            source = sorted([r for r in case['rows'] if r['symbol'] == symbol], key=lambda r: r['session'])
            groups = defaultdict(list)
            for row in source:
                session_rows.append([LABELS[symbol], label.split('：')[0], session_name(row['session']), *money_cells(row)])
                iso = date.fromisoformat(row['session'][:10]).isocalendar()
                groups[(iso.year, iso.week)].append(row)
            for (year, week), rows in groups.items():
                summed = {k: sum(r[k] for r in rows) for k in ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units']}
                week_rows.append([LABELS[symbol], label.split('：')[0], f'{year}年第{week}週', *money_cells(summed)])
            week_rows.append([LABELS[symbol], label.split('：')[0], '全13セッション', *money_cells(s)])
            for field in ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units']:
                assert sum(r[field] for r in source) == s[field]
    main_table = table(['銘柄', '手法', '利益 円', '損失 円', '収支 円', '利益÷損失', '１勝平均÷１敗平均'], main_rows)
    ledger_head = ['銘柄', '手法', '期間', '利益 円', '損失 円', '収支 円', '勝ち枚数', '負け枚数', '枚数差']

    random_rows = []
    for sample in controls['乱数比較']:
        for symbol in SYMBOLS:
            s = sample['symbols'][symbol]
            random_rows.append([sample['対照'], LABELS[symbol], yen(s['収支百分位'][3]),
                                f"{s['基準以上収支数']}/128", f"{s['基準以上PF数']}/128"])
    random_table = table(['無関係な選択', '銘柄', '収支の中央値 円', 'X05以上の収支', 'X05以上の利益÷損失'], random_rows)
    case_table = table(['診断条件', '変更内容', 'TOPIX収支 円', 'NK収支 円'], [
        [c['id'], c['description'], yen(c['symbols']['TOPIX']['net_yen']), yen(c['symbols']['NK225']['net_yen'])]
        for c in cases
    ])
    execution_rows = []
    for fill in ['指定価格', '到達観測価格']:
        for delay in [0, 1, 5, 15]:
            found = [r for r in execution['期間集計'] if r['手法'] == 'X05_G08' and r['約定モデル'] == fill and r['信号遅延秒'] == delay]
            assert len(found) == 2
            pair = {r['銘柄']: r for r in found}
            execution_rows.append([fill, str(delay), yen(pair['TOPIX']['net_yen']),
                                   f"{pair['TOPIX']['money_ratio']:.2f}", yen(pair['NK225']['net_yen']), f"{pair['NK225']['money_ratio']:.2f}"])
    branch_rows = []
    for symbol in SYMBOLS:
        for bid in ['F32', 'F42', 'F43', 'F44']:
            row = next((r for r in branches['注文起源別合計'] if r['銘柄'] == symbol and r['枝'] == bid), None)
            branch_rows.append([LABELS[symbol], bid, str(row['取引数'] if row else 0), yen(row['収支円'] if row else 0)])

    # ----------------------------------------
    # 本文は結論と主要反証に絞り、全明細は折りたたむ。
    body = f'''
<p class="eyebrow">作業00019 · 既存13セッションの敵対検証</p>
<h1>既存13セッションの黒字は再現する。<br>X05の切替の追加価値は支持不足。</h1>
<div class="verdict"><strong>前回の「有望な選択器」という評価を下げます。</strong>
<p>最大の勝ちを除いても黒字は残りました。ただし、固定手法F32からX05へ置き換える合理性は、現データでは確認できません。板を読む思想は筋が通りますが、今回の数式がその働きを捉えた証拠は弱いです。</p></div>
<p class="muted">対象：2026/9/21昼〜9/29昼、13セッション・７開始日。TOPIXミニ／NK225マイクロ各１枚。費用０・指定価格約定・全玉場内返済。現在APIの追加取得０回。全て設計時に既知の期間です。</p>
<h2>固定手法と比べると</h2>
{main_table}
<p><strong>切替を加えた差はTOPIX −13,000円、NK ＋1,700円。</strong>前回の「１位」は追加360条件内。元の1,160条件と同じ採点式で合わせるとX05は４位、F32は１位でした。金額は同銘柄内で比較しています。</p>
<h2>壊そうとして確かめた結果</h2>
{table(['問い', '実際の結果', '判定'], [
    ['大勝ち１〜２回だけでは？', '最大２勝ちセッションを除外：TOPIX ＋46,500円、NK ＋8,600円。', '黒字は残る'],
    ['切替に意味がなくても稼げるのでは？', '過去の選択頻度に従う無関係な切替128通り中17通りが、両銘柄でX05の収支以上。', '切替の優秀さは未立証'],
    ['４手法が本当に役割を果たす？', 'F43は選択中の信号も取引も０。F32の監視比率はTOPIX87.6%、NK97.8%。', '４手法の広い適応とは言えない'],
    ['少しの変更に耐える？', '切替確認を２回→１回にするとTOPIXは＋90,000円→−65,000円。NKは＋22,900円。', 'TOPIXで脆い'],
    ['時間や約定の仮定による利益では？', '信号１秒遅延：TOPIX ＋29,500円／NK ＋18,400円。観測価格約定のみ：＋86,000円／＋17,900円。', '黒字は残るが時刻に敏感'],
    ['損失を隠す会計や売買の非対称では？', '旧台帳の93取引を再現。次行執行・全玉会計・場内返済・保有上限を確認。価格反射104再生も一致。', '検査範囲では不備なし']
])}
<p class="muted">17/128は有意確率ではありません。同じ相場に異なる乱数を当てた診断です。変更後の好成績を、新しい採用候補へ昇格させてはいません。</p>
<h2>論理として、どこまで言えるか</h2>
<p>売買成立の買い数量と売り数量は同じです。価格方向を考えるなら、どちらが相手の気配へ注文をぶつけ、待機注文が消化・取消・補充され、その結果として価格が動いたかを見る必要があります。注文フローと短期価格変化の関係には研究上の根拠があります。<a href="https://arxiv.org/abs/1011.6402">Contほかの板イベント研究</a></p>
<p><strong>しかし、今回の「補充」は吸収の証明になっていません。</strong>同じ板数量の推移は、約定後の補充でも取消後の再注文でも作れます。「買った人はいずれ売る」からも、この時間内の反落は導けません。取引主体や新規・返済の識別、返済期限が分からないためです。</p>
<p>最良気配の偏りには次の価格変化を予測する根拠がありますが、それだけで長時間の方向持続や利幅を説明することはできません。今回の利益は入口とG08の決済を合わせた結果です。<a href="https://arxiv.org/abs/1512.03492">Gould・Bonartの１ティック先予測研究</a></p>
<details><summary>入口・出口・切替と、論理上の弱点</summary>
<p><strong>F32：</strong>最良売買気配の数量偏りを120秒平均し、価格も同方向へ動いている時だけ方向を出します。X05はこれを基本に、補充偏りならF44、近遠の板圧力一致ならF42、遠方先行ならF43を監視します。１分ごとに選択し、同じ提案２回と切替後３分の維持を要求します。初回は直前切替がないため２回で切り替わります。</p>
<p><strong>G08：</strong>新規は0.25ATR先の逆指値、初期損切り1ATR。1ATRの含み益から2ATR幅で追跡し、最大360分・場内で返済。新規逆指値は120秒期限、決済後５分待機。同方向２敗時の停止・再開、セッション損失予算による返済もあります。選択手法が変わっても保有玉を入れ替えるわけではありません。ATRはその時点で利用可能な値を使います。</p>
<ul><li>F32の加重気配偏差は板偏り÷２と同値。106,451行で確認し、独立した新しい情報ではありません。</li>
<li>近距離・遠距離のフローは重みが違うだけで領域が重なり、相関はTOPIX0.984／NK0.986。別々の証拠が一致した、と強く解釈できません。</li>
<li>F43は選択時に近距離が弱い条件、信号発火時に強い条件を求めます。時間差で成立し得ますが、この期間の選択中には一度も成立しませんでした。選択中のF43を止めても全収支不変です。</li>
<li>X05は自銘柄だけで判定します。２銘柄に共通のコードですが、NKとTOPIXを同時に読む仕組みではありません。</li>
<li>G08と防御を減らしたG00の観測損益は同じ。今回の黒字からG08の防御条件の効用まで証明することはできません。</li></ul>
<p>詳細なコード監査：<a href="logical_audit.md">論理・特徴量の監査</a>。完全な条件は前回の<a href="../00018_市場原理からの再探索/選択から返済まで.html">ルール説明</a>と再現コードを参照。</p>
</details>
<details><summary>無関係な切替・条件除去・感度：全30条件と対照</summary>
<p>４手法を３分ごとに一様に選ぶ対照と、同銘柄の過去完了セッションでの選択頻度に比例して選ぶ対照を各128通り実行。頻度には各手法１回分を加算し、過去データがない初回は一様です。選択後はその時点の実際の方向信号と同じG08で新規・返済を再生します。</p>
{random_table}
<p>一様対照では両銘柄の収支でX05以上は０/128。過去頻度対照では17/128、両銘柄の利益÷損失でX05以上は11/128です。F32を多く使うだけでも近い成績が出るため、一様対照だけで強さを主張できません。現在・未来の頻度や損益は参照せず、データ末尾を切っても乱数選択の過去部分が変わらないことを104件確認しました。</p>
<p>これらは切替回数や保持時間を厳密に合わせた無作為実験ではありません。128通りは128の独立相場でもありません。状態と手法の対応24順列では、元の対応を含め２通りが両銘柄の収支以上でした。</p>
{case_table}
<p>除去後は注文・待機・損失停止を全て再計算します。そのため、部品の収支を単純に足し引きした結果にはなりません。「確認３回」などの良い結果を見て設定を更新してはいません。</p>
</details>
<details><summary>各手法の取引帰属と、切替の純増効果</summary>
{table(['銘柄', '注文起源の手法', '取引数', '収支 円'], branch_rows)}
<p>取引が黒字だったことと、その手法を加えて全体の利益が増えたことは別です。例えばF42起源のTOPIX取引は＋23,000円ですが、F42を選ぶ時間にF32を使うと全体収支は＋90,000円→＋109,500円になります。NKは＋18,800円→＋17,100円です。現実の取引への帰属と、置き換えた時の比較を混同できません。</p>
<p>約定時の選択名ではなく、注文を設置した時の手法へ帰属しました。両者が異なる取引が１件あります。売買明細は<a href="branch_attribution.json">全93取引の監査JSON</a>に保存しています。</p>
</details>
<details><summary>執行条件を変えた８通りと、注文順序の監査</summary>
{table(['約定モデル', '信号遅延 秒', 'TOPIX収支 円', '利益÷損失', 'NK収支 円', '利益÷損失'], execution_rows)}
<p>主結果は指定価格・費用０です。観測価格は補足検査で、実際の約定を保証するものではありません。遅延は方向信号だけに加え、ATR・価格観測・注文送信には加えていません。元データの時刻を使うため実通信の精密再現でもありません。</p>
<p>前行で存在する注文は現在行の新信号より先に執行します。TOPIX７/57件、NK７/36件は、約定行の信号が既に中立でした。これは注文と取消の順序の仕様であり、「約定時も根拠が必ず残る」とは言えません。新設したストップの過去価格への遡及約定は検出されませんでした。</p>
<p>会計と次行執行など416再生、売買対称性104再生を確認。<a href="exec_adversarial.md">執行監査の詳細</a></p>
</details>
<details><summary>偶然・探索バイアス・日中夜間差の検査</summary>
<p>最大２勝ち取引を除いてもTOPIX＋39,000円／NK＋8,800円、最大２黒字開始日を除いても＋23,500円／＋10,000円。一発だけに依存した黒字ではありません。</p>
<p>一方、F32との差はTOPIXの日中＋23,000円・夜間−36,000円。NKの日中＋1,900円・夜間−200円。NKの全期間増分＋1,700円は、9/28を除くと−200円です。これは事後の原因診断で、日中夜間を切り替える新ルールを採用した結果ではありません。</p>
<p>７開始日を両手法・両銘柄で同時に5,000回再抽出した差の中央95%区間は、TOPIX −127,500〜＋98,500円、NK −1,800〜＋6,100円。両方０を含み、優位性を確認できません。少数・不均一な日付ブロックで、日付間の独立性も未保証、探索バイアスも未補正。将来利益の確率ではありません。</p>
<p>F32を全期間で選んだ後、F32を基本とするX05を設計しました。売買の計算で未来を使わないことと、設計が未知相場で検証されたことは別です。過去６セッションで候補を選び次を再生した追加360条件の結果は＋34,500円／＋4,800円ですが、設計自体が事後で、NKは最大勝ちを除くと−400円です。</p>
<p>1,520条件を対象とした最大統計量の参考検査も保存しましたが、正式な補正済み有意確率ではありません。多数の試行後に選んだ好成績へ、通常の検定をそのまま当てられないことは、<a href="https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf">バックテスト過適合研究</a>や<a href="https://users.ssc.wisc.edu/~behansen/718/White2000.pdf">Whiteのデータ再利用研究</a>に沿う問題です。今回、正式なPBOやWhiteの検定を実施したとは主張しません。</p>
<p><a href="statistical_adversarial_結論.md">統計監査の結論</a> · <a href="statistical_adversarial.json">全診断値</a></p>
</details>
<details><summary>週別・全期間の利益／損失／収支（金額・枚数）</summary>
<p>第39週は9/21〜25開始の10セッション、第40週は9/28〜29開始の３セッション。夜間は開始日に所属。損失は正の額、枚数差は勝ち決済枚数−負け決済枚数で、残存建玉ではありません。両手法・両銘柄とも同値決済０枚。</p>
{table(ledger_head, week_rows)}
</details>
<details><summary>13セッションそれぞれの利益／損失／収支（金額・枚数）</summary>
{table(ledger_head, session_rows)}
</details>
<footer><a href="README.md">資料の読む順序・再現方法</a> · <a href="検証結果.md">短い報告</a> · <a href="../index.html">作業一覧</a><br>前回の成果は保存したまま、この作業で評価を修正しています。</footer>
'''
    css = '''
    :root{color-scheme:dark;font-family:"Yu Gothic UI","Meiryo",sans-serif;color:#e4edf7;background:#0c121c}
    *{box-sizing:border-box}body{margin:0;line-height:1.8}main{max-width:1180px;margin:auto;padding:38px 24px 60px}
    h1{font-size:clamp(25px,4vw,36px);line-height:1.5;margin:10px 0 24px}h2{font-size:22px;margin:34px 0 12px}
    p{margin:12px 0}a{color:#92caff;text-underline-offset:3px}.muted,.eyebrow,footer{color:#adbed1}.eyebrow{font-size:14px}
    .verdict{background:#192537;border-left:5px solid #ecc27e;padding:18px 22px;border-radius:6px}.verdict p{margin-bottom:0}
    .scroll{overflow-x:auto;margin:14px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:11px 13px;border-bottom:1px solid #344359;vertical-align:top}
    th{background:#243247;color:#f0f6ff;white-space:nowrap}td{background:#121d2b}tbody tr:nth-child(even) td{background:#182333}
    details{border:1px solid #344359;background:#131e2d;border-radius:9px;padding:15px 20px;margin:15px 0}summary{cursor:pointer;font-weight:700;color:#bfdcff}
    details[open] summary{margin-bottom:18px}details p,details li{font-size:15px}summary:focus-visible,a:focus-visible{outline:3px solid #ecc27e;outline-offset:4px}
    footer{margin-top:32px;font-size:14px}@media(max-width:600px){main{padding:24px 14px}details{padding:13px}.verdict{padding:14px}th,td{padding:9px}}
    '''
    document = '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>X05の敵対的検証</title><style>' + css + '</style></head><body><!--\n[コンポーネント概要]\nmain は結論と検証結果です。details は詳しい条件と損益を展開します。\n.scroll は狭い画面で表を横へスクロールする領域です。外部通信やスクリプトはありません。\n--><main>' + body + '</main></body></html>'
    (OUT / '敵対的検証.html').write_text(document, encoding='utf-8')

    report = '''# X05の敵対的検証

**黒字は再現するが、切替の追加価値は支持不足。前回の「有望な選択器」という評価を下げる。**

2026/9/21昼〜9/29昼の既知13セッション。TOPIXミニ・NK225マイクロ各１枚、費用０・指定価格約定・場内返済。現在APIの追加取得０回。

| 比較 | TOPIX収支 | NK収支 |
|---|---:|---:|
| X05_G08 | ＋90,000円 | ＋18,800円 |
| F32_G08固定 | ＋103,000円 | ＋17,100円 |
| 切替による差 | −13,000円 | ＋1,700円 |

- 最大２勝ちセッションを除いても＋46,500円／＋8,600円。単発の大勝ちだけではない。
- 過去の選択頻度に従う無関係な切替128通り中17通りが両銘柄でX05の収支以上。正式な有意確率ではない。
- F43は選択中に信号が出ず、売買０。F32の監視比率は87.6%／97.8%。
- 確認２回を１回にするとTOPIX −65,000円。信号１秒遅延では＋29,500円。タイミングへの依存が強い。
- 観測価格での約定へ変更しても＋86,000円／＋17,900円。利益を約定仮定だけの産物とは断定できない。
- 旧台帳93取引・全玉会計を再現。売買対称性も104再生で一致した。

板の消化・補充と価格応答を見る思想は合理的。ただし今回の補充特徴量では、約定による消化と取消を区別できない。近遠フローは相関約0.98で大きく重複し、X05は他方銘柄を参照しない。４種類の市場状態を広く使い分けた、という説明は支持されない。

X05は追加360条件内の首位で、同じ採点式で全1,520条件を合わせると４位、F32が１位。全期間を見た後の設計なので、時間順に再生しても未知データの検証にはならない。検査の良い設定を選び直す変更は行っていない。

[全結果・週別とセッション別の金額／枚数](敵対的検証.html)を参照。論理上の根拠と実装の識別力、既知相場の損益と将来再現性を分けて評価した。
'''
    (OUT / '検証結果.md').write_text(report, encoding='utf-8')
    readme = '''# 作業00019：X05の敵対的検証

**最初に見るファイル：[敵対的検証.html](敵対的検証.html)**。冒頭に結論と主要反証、展開欄に週・セッション別の損益を掲載。

読む順序：

1. [敵対的検証.html](敵対的検証.html) または [短い報告](検証結果.md)
2. [論理監査](logical_audit.md)、[注文執行監査](exec_adversarial.md)、[統計監査](statistical_adversarial_結論.md)
3. 詳細JSONと再現コード。`枝除去と感度.json` は30条件、`対応を入れ替える検査.json` は24順列、`無関係な選択の全結果.json` は２方式×128乱数。それぞれ銘柄別・セッション別集計を含む。

同じ作業の元コードは `work/wave_v24`。このフォルダの `.py` は記録用コピーで、実行時の相対依存先を変更していない。プロジェクトルートから以下を実行する。

```powershell
python work/wave_v24/counterfactual.py
python work/wave_v24/exec_adversarial.py
python work/wave_v24/branch_attribution.py
python work/wave_v24/statistical_adversarial.py
python work/wave_v24/build_report.py
```

依存：既存のPython環境（NumPy、pandas、Numba等）、`work/wave_v23` のコード・保存済み入力・信号・前回結果。旧コード・入力のSHA256を監査JSONに記録。生データを重複コピーせず、現在APIの再取得も行わない。報告の再生成だけなら最後のコマンドのみ。

主前提は費用０・指定価格約定・各１枚・場内返済。約定価格変更と遅延は補足診断。最大勝ち除外や再抽出は既知標本の依存性検査で、未知相場の保証ではない。今回の診断条件から新しい最良手法は選ばない。

[前回00018](../00018_市場原理からの再探索/README.md)を上書きせず、今回の評価修正を別記録とした。
'''
    (OUT / 'README.md').write_text(readme, encoding='utf-8')
    for path in WORK.iterdir():
        if path.is_file() and path.suffix in {'.py', '.json', '.md'}:
            shutil.copy2(path, OUT / path.name)

    # ----------------------------------------
    # 作業一覧だけを更新し、過去の成果フォルダには書き込まない。
    index_path = OUT.parent / 'index.html'
    index = index_path.read_text(encoding='utf-8')
    if '<!--00019開始-->' not in index:
        index = index.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
        index = index.replace('最新は00018。手法の選択から新規・返済まで機械化し、計1,520条件を検証。', '最新は00019。X05を固定手法・無関係な切替・条件除去・執行感度から敵対的に検証。')
        card = f'<!--00019開始--><article class="task latest"><div class="number">作業00019 <span class="badge">最新</span></div><h2>X05の敵対的検証</h2><p>黒字は再現するが、切替の追加価値は支持不足。前回の評価を修正し、反証結果と週・セッション別損益を掲載。</p><a class="button" href="{NAME}/敵対的検証.html">敵対的検証を開く →</a><p><a href="{NAME}/検証結果.md">短い報告</a> · <a href="{NAME}/README.md">資料案内</a></p></article><!--00019終了-->'
        index = index.replace('<!--00018開始-->', card + '<!--00018開始-->', 1)
        index_path.write_text(index, encoding='utf-8')
    root_readme = OUT.parent / 'README.md'
    text = root_readme.read_text(encoding='utf-8')
    if f'| `{NAME}`' not in text:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith('**最新は'):
                lines[i] = f'**最新は00019の[敵対的検証]({NAME}/敵対的検証.html)。X05の黒字を再現しつつ、切替の追加価値・論理・執行・選択バイアスを監査し、前回の評価を修正しました。**'
        text = '\n'.join(lines) + '\n'
        text = text.replace('`00018_市場原理からの再探索`（最新）', '`00018_市場原理からの再探索`')
        row = f'| `{NAME}`（最新） | X05への反証と評価修正 | [敵対的検証]({NAME}/敵対的検証.html) | [短い報告]({NAME}/検証結果.md)・[資料案内]({NAME}/README.md) |\n'
        text = text.replace('| `00018_', row + '| `00018_', 1)
        text = text.replace('`00019_内容`', '`00020_内容`')
        root_readme.write_text(text, encoding='utf-8')
    print(json.dumps({'保存先': str(OUT), '条件数': len(cases), 'セッション表行数': len(session_rows), '週表行数': len(week_rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
