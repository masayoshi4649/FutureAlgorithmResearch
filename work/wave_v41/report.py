"""既存黒字候補の全返済を再集計し、実装修正とは区別して短い比較表を作る。"""

from __future__ import annotations

from datetime import date, timedelta
import gzip
import hashlib
from html import escape
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIOR = HERE.parent / 'wave_v38'
TITLE = '黒字候補の再評価と状態修正'
OUT = ROOT / ('アルゴリズム調査/00036_' + TITLE)
POLICIES = (
    ('A0', '基本形', '数量の減量・復元は行わず、共通の部分利確とトレーリングで返済。'),
    ('B00_RB00_F25_N1', '自市場2分・25%減量→回復', '自市場の2分の価格反応が逆行したら25%減量。同じ2分の反応が順行へ戻れば復元。1組1回。'),
    ('B00_T120_F25_N1', '自市場2分・25%減量→時計', '自市場2分の逆行で25%減量。120秒後以降の新しい有効観測で復元。1組1回。'),
    ('B00_T120_F25_N3', '自市場2分・25%減量→時計3回', '直前の時計方式を1組最大3回まで繰り返す。'),
    ('B06_RB01_F25_N1', '両市場2分・25%減量→自市場10分回復', '両市場2分の反応がともに逆行したら25%減量。自市場10分の反応が順行へ戻れば復元。1組1回。'),
    ('B06_RB01_F50_N1', '両市場2分・50%減量→自市場10分回復', '直前の信号復元方式の減量率を50%にする。1組1回。'),
    ('B06_T120_F50_N3', '両市場2分・50%減量→時計3回', '両市場2分の逆行で50%減量。120秒後以降の有効観測で復元。1組最大3回。'),
    ('B07_T120_F25_N1', '両市場10分・25%減量→時計', '両市場10分の逆行で25%減量。120秒後以降の有効観測で復元。1組1回。'),
    ('B07_T120_F50_N1', '両市場10分・50%減量→時計', '直前の10分方式の減量率を50%にする。1組1回。'),
    ('B06_CHOICE_B01_F50_N1', '回復待ち／時計待ちを選択', '両市場2分の逆行で50%減量。減量時に自市場10分が逆行なら回復待ち、それ以外は時計待ちを選ぶ。前回の主案。'),
)
FIELDS = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units')


def read(path: Path) -> object:
    """機能: 通常又は圧縮JSONを読み取る。

    引数: path (Path)。返り値: 保存内容 (object)。
    """
    payload = path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.suffix == '.gz' else payload)


def digest(path: Path) -> str:
    """機能: 資料の内容を指紋へ固定する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def totals(rows: list[dict]) -> dict:
    """機能: 並列の期間行の利益と決済枚数を集計する。

    引数: rows (list[dict])。返り値: 合計6項目 (dict)。
    """
    return {name: sum(row[name] for row in rows) for name in FIELDS}


def verify_ledger(ledger: dict, row: dict) -> int:
    """機能: 全返済を建値・返済値・数量から再計算して保存集計と照合する。

    引数: ledger/row (dict)。返り値: 照合した返済明細数 (int)。
    """
    factor = {'TOPIX': 1000., 'NK225': 10.}[row['symbol']]
    result = dict.fromkeys(FIELDS, 0.)
    for trade in ledger['trades']:
        side, quantity, entry, exit_price = trade[2:6]
        assert side in (-1, 1) and quantity > 0 and quantity == int(quantity)
        pnl = side * quantity * (exit_price - entry) * factor
        assert abs(pnl - trade[10] * factor) < 1e-6
        result['net_yen'] += pnl
        if pnl > 0:
            result['gross_profit_yen'] += pnl
            result['profit_units'] += quantity
        elif pnl < 0:
            result['gross_loss_yen'] -= pnl
            result['loss_units'] += quantity
        else:
            result['zero_units'] += quantity
    for field in FIELDS:
        assert abs(result[field] - row[field]) < 1e-6, (row['id'], row['session'], field)
    return len(ledger['trades'])


def collect() -> tuple[list[dict], dict]:
    """機能: 固定10候補を損益順位で選び直さず読み、全セッションを検算する。

    引数: なし。返り値: 表示データと独立集計証跡 (tuple[list[dict],dict])。
    """
    data, references, trades = [], {}, 0
    fixed = read(PRIOR / '探索条件の固定.json')
    expected = {(session, symbol) for session in fixed['全セッション'] for symbol in ('TOPIX', 'NK225')}
    assert len(expected) == 26
    for index, (policy, name, explanation) in enumerate(POLICIES):
        identifier = f'H019__{policy}__R1__V000'
        files = {kind: PRIOR / kind / (identifier + suffix) for kind, suffix in
                 (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('summaries', '.json'))}
        sessions, ledgers, summary = (read(files[k]) for k in ('sessions', 'ledgers', 'summaries'))
        assert len(sessions) == len(ledgers) == 26 and summary['id'] == identifier
        for values in (sessions, ledgers):
            assert {(r['session'], r['symbol']) for r in values} == expected
        lookup = {(r['session'], r['symbol']): r for r in ledgers}
        for row in sessions:
            trades += verify_ledger(lookup[row['session'], row['symbol']], row)
        for symbol in ('TOPIX', 'NK225'):
            summed = totals([r for r in sessions if r['symbol'] == symbol])
            assert all(abs(summed[k] - summary['all_symbols'][symbol][k]) < 1e-6 for k in FIELDS)
        references.update({p.relative_to(ROOT).as_posix(): digest(p) for p in files.values()})
        data.append(dict(alias=f'C{index:02}', id=identifier, policy=policy, name=name,
                         explanation=explanation, sessions=sessions, summary=summary['all_symbols']))
    return data, dict(全返済再計算一致=True,候補数=10,銘柄セッション数=260,
                      返済明細数=trades,参照SHA256=references,新売買条件数=0,現在API取得数=0)


def money(value: float, signed: bool = False) -> str:
    """機能: 円の整数表示を生成する。

    引数: value (float)、signed (bool)。返り値: 表示文字列 (str)。
    """
    value = 0. if value == 0 else value
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def ratio(value: float, divisor: float) -> str:
    """機能: 分母がある場合だけ比率を表示する。

    引数: value/divisor (float)。返り値: 比率又は横線 (str)。
    """
    return f'{value / divisor:.2f}' if divisor else '—'


def financial_row(label: str, row: dict, code: str) -> str:
    """機能: 一期間の金額・枚数・枚数差を省略なく描く。

    引数: label/code (str)、row (dict)。返り値: HTML行 (str)。
    """
    values = [money(row['gross_profit_yen']), money(row['gross_loss_yen']), money(row['net_yen'], True),
              str(int(row['profit_units'])), str(int(row['loss_units'])), str(int(row['zero_units'])),
              f"{int(row['profit_units'] - row['loss_units']):+d}"]
    return f'<tr data-key="{escape(code)}"><th>{escape(label)}</th>' + ''.join(f'<td>{v}</td>' for v in values) + '</tr>'


def table(candidate: dict, symbol: str) -> str:
    """機能: 全期間・週別・13セッションを一市場ずつ表示する。

    引数: candidate (dict)、symbol (str)。返り値: HTML表 (str)。
    """
    rows = sorted([r for r in candidate['sessions'] if r['symbol'] == symbol], key=lambda r: r['session'])
    body = financial_row('全13セッション', totals(rows), candidate['alias'] + '|' + symbol + '|全期間')
    weeks = {}
    for row in rows:
        stamp = date.fromisoformat(row['session'][:10])
        monday = (stamp - timedelta(days=stamp.weekday())).isoformat()
        weeks.setdefault(monday, []).append(row)
    for monday, group in sorted(weeks.items()):
        body += financial_row(monday + '開始週', totals(group), candidate['alias'] + '|' + symbol + '|' + monday)
    for row in rows:
        label = row['session'].replace('_Day', ' 日中').replace('_Night', ' 夜間')
        body += financial_row(label, row, candidate['alias'] + '|' + symbol + '|' + row['session'])
    return '<div class="scroll"><table><thead><tr><th>期間</th><th>利益 円</th><th>損失 円</th><th>収支 円</th><th>勝ち 枚</th><th>負け 枚</th><th>同値 枚</th><th>勝ち−負け 枚</th></tr></thead><tbody>' + body + '</tbody></table></div>'


def main() -> None:
    """機能: 既存損益の再集計表と読取り証跡を作成する。

    引数: なし。返り値: なし (None)。修正版再生の完了や公表は別に検査する。
    """
    data, audit = collect()
    state = read(HERE / '状態修正の全再生.json')
    assert state['全合格'] and state['経済全配列完全一致'] and state['修正後実装状態契約合格']
    assert (state['全条件数'], state['全入力数'], state['状態変更行数']) == (974, 25324, 12)
    audit['状態修正再生SHA256'] = digest(HERE / '状態修正の全再生.json')
    OUT.mkdir(parents=True, exist_ok=True)
    overview, chapters = '', ''
    for candidate in data:
        for symbol in ('TOPIX', 'NK225'):
            row = candidate['summary'][symbol]
            average = (row['gross_profit_yen'] / row['profit_units']) / (row['gross_loss_yen'] / row['loss_units'])
            overview += f'<tr><th><a href="#{candidate["alias"]}">{candidate["alias"]} {escape(candidate["name"])}</a></th><td>{symbol}</td><td>{money(row["net_yen"],True)}</td><td>{money(row["drawdown_yen"])}</td><td>{ratio(row["gross_profit_yen"],row["gross_loss_yen"])}</td><td>{average:.2f}</td></tr>'
        chapters += f'<section id="{candidate["alias"]}"><h2>{candidate["alias"]} {escape(candidate["name"])}</h2><p>{escape(candidate["explanation"])}</p><p class="muted">旧ID：{escape(candidate["id"])}</p>'
        for symbol, title in (('TOPIX', 'TOPIXミニ換算'), ('NK225', 'NK225マイクロ換算')):
            chapters += f'<details><summary>{title}：全期間・各週・各セッション</summary>' + table(candidate, symbol) + '</details>'
        chapters += '</section>'
    html = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>黒字候補の再評価と状態修正</title>
<style>:root{color-scheme:dark}body{margin:0;background:#10151e;color:#e2e8f1;font:16px/1.7 "Yu Gothic UI",Meiryo,sans-serif}main{max-width:1200px;margin:auto;padding:28px 24px 80px}h1{font-size:28px}h2{font-size:21px;margin-top:36px}a{color:#8bbffc}p{max-width:1050px}.notice{padding:16px 20px;background:#17273b;border-left:4px solid #75b6fa;border-radius:6px}.muted{color:#a8b7ca;font-size:13px;overflow-wrap:anywhere}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;white-space:nowrap;margin:14px 0 22px}th,td{padding:9px 12px;border-bottom:1px solid #344256;text-align:right}th:first-child{text-align:left}thead{background:#1e2c40;color:#bad6fa}tbody tr:hover{background:#172234}details{border:1px solid #344256;border-radius:6px;padding:8px 12px;margin:12px 0}summary{cursor:pointer;color:#b3d5ff;font-weight:600}section{border-top:1px solid #344256;margin-top:28px}li{margin:8px 0}.tag{color:#a9e1bd}</style>
<!--
[コンポーネント概要]
main は研究候補の比較と元の全返済を再集計した損益表です。
.notice は結論と対象範囲を示します。採用保証を示す色ではありません。
.scroll は狭い画面でも全金額・枚数の列を読める表の領域です。
details は各候補・各市場の全期間と全セッションを省略せず折り畳みます。
data-key は数表を候補・銘柄・期間へ結び、表示検算に用います。
-->
<main><p><a href="../index.html">調査一覧</a> ／ <a href="README.md">資料案内</a></p><h1>黒字候補の再評価と状態修正</h1>
<div class="notice"><strong>基本形H019＋D273は黒字候補として残ります。</strong><br>数量調整の8候補も黒字ですが、使い分けを複雑にする追加効果は一貫していません。今回は同じ条件の実装を修正・再検算し、新しい板観測の不足も切り分けます。</div>
<p class="muted">保存済み2026/9/21〜9/29日中、全13セッションは既知。旧結果の再集計であり未知検証ではありません。費用0・指定価格約定・場内全返済。大型先物の保存価格をTOPIXミニ（1pt＝1,000円）／NKマイクロ（1pt＝10円）へ換算。初回5枚／10枚、片方向上限10枚／20枚。</p>
<h2>元のアルゴリズム</h2><p>両市場の中期方向と短期の価格進行が一致したとき、0.25ATRの追跡新規注文で入ります。初期ATRを固定し、組全体の損失を約1ATR相当で止め、2ATR進行で整数半分を利確。残りは1.5ATR進行から3ATR幅で追跡します。最長360分、全返済後5分休止、場末は必ず返済します。</p>
<p>下の8調整候補は、逆行したときだけ一部を返済し、回復確認又は時計で元の数量まで戻す方法です。減量は残る有効枠の25%／50%を整数化し、最低1枚は残します。既に利確した枠は復活させず、復元で初期リスクや期限もリセットしません。反応は単なる騰落ではなく、窓全体と直近1/4窓が所定幅を超えて同方向に動く条件です。相手市場は追加60秒遅らせて参照します。</p>
<h2>候補の比較</h2><p>最大下落は含み損益込み。金額比は総利益÷総損失、1枚比は勝ち1枚の平均利益÷負け1枚の平均損失です。両市場の円額は合算して順位付けしません。</p><div class="scroll"><table><thead><tr><th>手法</th><th>市場</th><th>全収支 円</th><th>最大下落 円</th><th>金額比</th><th>1枚比</th></tr></thead><tbody>''' + overview + '''</tbody></table></div>
<h2>何が残り、何が未確認か</h2><p><strong>追加候補ではC01（自市場2分・25%減量→回復）が残ります。</strong>基本形より両市場の収支が増え、最大下落も減りました。減量・回復の方向を別々に乱数化した中央値との比較でも、全期間／後半7の両市場で収支が高く最大下落が小さい結果です。既知結果から選ばれた候補であり、正式な有意確率や将来保証ではありません。</p><ul><li>基本形は両市場黒字。勝ち枚数が負け枚数より少なくても、1枚の平均利益が平均損失を上回りました。</li><li>基本形は上位2勝ち組を同時に除く検査でも黒字。一方、入口の時間窓を20%動かすと、特にTOPIXの利益が大きく減りました。</li><li>多くの試行から選んだ候補です。既知期間で黒字・反証通過であることと、未知期間の優位性が確定したことは別です。</li><li>回復待ち／時計待ちを選ぶC09は黒字ですが、固定方式・逆選択・選択だけ乱数の比較から、選択情報の追加価値は支持されませんでした。</li></ul>
<p><a href="../../work/wave_v41/既存候補の未解決点.md">候補ごとの独立した再評価</a> ／ <a href="../../work/wave_v41/今回の検査計画.md">今回の検査範囲</a> ／ <a href="../../work/wave_v41/状態修正の全再生.json">状態修正の全再生結果</a></p>
<h2>状態修正の確認</h2><p>修正版で974条件・25,324口座を再生し、元の厳格な状態監査を通過しました。既知の12行の状態だけが変わり、注文・全行の損益・数量・保存統計は旧結果と完全一致しました。旧v38の不合格記録は保持しています。これは実装の確認で、候補の収益採用や未知期間の優位性を認定するものではありません。</p>
<h2>板の次の検査</h2><p>固定4例では、公開端点で減少0だった6試行すべてに原本の減少がありました。ただし旧品質を守って二試行を比較できるようになったのは4帯中1帯。原本全行での集計と、板10段の外へ出た欠測を分けて検証します。これは観測の改善であり、収益改善はまだ示していません。</p><p><a href="../../work/wave_v41/板観測の欠落診断.md">原本4例の診断</a> ／ <a href="../../work/wave_v41/手法配分の独立性確認.md">次の新規数量へ手法を配分する案</a> ／ <a href="../../work/wave_v42/比較計画.md">原本全行を使う次の260条件</a></p>
<h2>各候補の損益</h2><p>損失は正の絶対額。枚数は延べ決済枚数で、「勝ち−負け」は収益金額や残玉ではありません。夜間は開始日の所属週へ集計し、9/28開始週は保存済み3セッションのみです。</p>''' + chapters + '''
<p><a href="../00033_復元方式の自動選択と改善8条件の反証/５分足と売買.html">既存候補の5分足と売買図</a> ／ <a href="../../work/wave_v41/report_data_audit.json">全260口座の表示用再集計</a></p></main></html>'''
    target = OUT / (TITLE + '.html')
    target.write_text(html, encoding='utf-8')
    audit.update(HTML_SHA256=digest(target),報告実装SHA256=digest(Path(__file__)),損益表示行数=320,
                 比較表示行数=20,修正版実装の完備をこの集計だけで主張=False)
    (HERE / 'report_data_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('黒字10候補・260口座の全返済を再計算。HTMLの公表は修正版の再生完了後。', flush=True)


if __name__ == '__main__':
    main()
