"""固定した8比較と全240条件を短い暗色HTMLへ表示する。売買は再実行しない。"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import gzip
import hashlib
import html
import json
from pathlib import Path

import trade_statistics as statistics


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00034_予想外の板圧力と独立価格対照'
MAIN = '予想外の板圧力と独立価格対照.html'
ALL = '全条件損益.html'
COMPARISONS = ('I00', 'I01', 'I02', 'I03', 'I19', 'I04', 'I05', 'I06')
SYMBOLS = ('TOPIX', 'NK225')
MONEY_FIELDS = ('profit_yen', 'loss_yen', 'net_yen')
UNIT_FIELDS = ('profit_units', 'loss_units', 'net_units', 'zero_units')
LABELS = dict(profit_yen='利益 円', loss_yen='損失 円', net_yen='収支 円', profit_units='勝ち 枚',
    loss_units='負け 枚', net_units='勝ち−負け 枚', zero_units='同値 枚',
    profit_factor='利益÷損失', average_payoff='平均利益÷平均損失', net_r='合計R', drawdown_yen='最大下落 円',
    件数='候補数', 正方向数='正方向', 逆方向数='逆方向', 同値数='同値', 平均ATR反応='平均ATR反応')
DECIMALS = {'profit_factor':2, 'average_payoff':2, 'net_r':2, '平均ATR反応':3}
STYLE = '''<style>:root{color-scheme:dark;background:#0b121b;color:#e5edf7;font-family:"Yu Gothic UI",Meiryo,sans-serif}body{max-width:1340px;margin:auto;padding:24px 18px;line-height:1.75}a{color:#8bcaff}h1{font-size:25px;margin:10px 0}h2{font-size:20px;margin-top:28px}h3{font-size:17px}p{margin:10px 0}small,.muted{color:#adc0d5}.box,details{background:#142131;border:1px solid #30455c;border-radius:8px;padding:14px;margin:15px 0}.warning{background:#382813;border-color:#99793d;color:#ffe0a1}.status{display:flex;gap:10px;flex-wrap:wrap}.status span{padding:8px 14px;background:#172b3c;border-radius:6px}.yes,.positive{color:#8ce5ba}.no,.negative{color:#ffb2a9}summary{cursor:pointer;font-weight:600}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}th,td{border-bottom:1px solid #2d4055;padding:8px 10px;text-align:right;font-variant-numeric:tabular-nums}th{background:#1a2a3d;color:#d1e1f2;position:sticky;top:0}th:first-child,td:first-child{text-align:left}select{background:#15283a;color:#e5edf7;border:1px solid #5d7a96;border-radius:5px;padding:9px;font:inherit;max-width:100%}button{font:inherit}section[hidden]{display:none}code{color:#bfe2ff}nav{display:flex;gap:18px;flex-wrap:wrap}.table-note{font-size:13px;color:#b7c9dc}.method{border-top:1px solid #33495e;margin-top:18px;padding-top:8px}.checks{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:10px}.checks p{margin:2px}</style>'''


def read(path: Path) -> object:
    """機能: 保存済みのJSONだけを読み込む。

    引数: path(Path)。返り値: 内容(object)。原本や売買器を使わない。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def digest(path: Path) -> str:
    """機能: 表示元と出力の指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def week(session_id: str) -> str:
    """機能: セッション開始日の属する月曜日を求める。

    引数: session_id(str)。返り値: 週の開始日(str)。ナイトも開始日で分類。
    """
    day = date.fromisoformat(session_id[:10])
    return (day - timedelta(days=day.weekday())).isoformat()


def number(value: float | int | None, field: str) -> str:
    """機能: 比率の未定義を無限大へ変えず、表示桁を統一する。

    引数: value(float|int|None)、field(str)。返り値: 表示文字(str)。
    """
    return '未定義' if value is None else f'{value:,.{DECIMALS.get(field,0)}f}'


def description(spec: dict) -> str:
    """機能: 固定パラメータから売買方向の決め方を短い日本語へ変換する。

    引数: spec(dict)。返り値: 説明(str)。成績によって説明を選ばない。
    """
    modes = dict(residual='観測した板圧力から、過去データで予想した圧力を引く。',
        raw='観測した板圧力をそのまま使う。', predicted='過去データで予想した板圧力を使う。',
        price='主案と同じ板の利用可能時刻に、価格変化だけで方向を決める。',
        price_independent='板の利用可否で間引かず、連続した価格観測だけで方向を決める。')
    text = modes[spec['mode']]
    if spec['mode'] in ('price', 'price_independent'):
        text += f' 価格変化が{.05*spec["threshold"]:g}ATRへ到達した方向で発火。'
    else:
        text += f' 過去の尺度に対して{spec["threshold"]:g}以上へ到達した方向で発火。'
        text += f' 同方向へ{spec["price_confirm"]:g}ATRの価格変化も確認。' if spec['price_confirm'] else ' 価格の順行確認は省略。'
    if spec['peer'] != 'none':
        text += ' 60秒遅らせた相手市場の'+('残差圧力' if spec['peer']=='residual' else '価格変化')+'が同方向の場合だけ採用。'
    if spec['invert']:
        text += ' 候補成立後の売買方向を反転。'
    if spec['seed'] is not None:
        text += f' 候補時刻を保ち、固定seed {spec["seed"]}の符号で方向を無作為化。'
    if spec['delay']:
        text += f' 親注文と返済子注文にそれぞれ最低{spec["delay"]:g}秒の伝達待ち。'
    if spec['observed']:
        text += ' 返済条件の成立後、観測価格で約定。'
    return text


def add_units(value: dict) -> dict:
    """機能: 勝ち枚数と負け枚数の差を表示用に追加する。

    引数: value(dict)。返り値: 元値を変更しない表示用辞書(dict)。
    """
    return dict(value, net_units=value['profit_units']-value['loss_units'])


def periods(rows: list[dict]) -> list[tuple[str, dict]]:
    """機能: 全13、開始日による2週、各13セッションの表示順を作る。

    引数: rows(list[dict])、同一銘柄。返り値: 期間と表示値(list[tuple])。
    """
    result = [('全13セッション', add_units(statistics.aggregate(rows)))]
    for first in ('2026-09-21', '2026-09-28'):
        result.append((first+'週', add_units(statistics.aggregate([row for row in rows if week(row['session'])==first]))))
    result.extend((row['session'], add_units(row)) for row in sorted(rows, key=lambda row:row['session']))
    assert len(result) == 16
    return result


def cell(field: str, value: float | int | None) -> str:
    """機能: 可視文字と監査用の数値を同じ値から作る。

    引数: field(str)、value(float|int|None)。返り値: セルHTML(str)。
    """
    encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
    sign = ' positive' if field in ('net_yen','net_units') and value is not None and value>0 else ''
    if field in ('net_yen','net_units') and value is not None and value<0:
        sign = ' negative'
    return f'<td class="num{sign}" data-field="{field}" data-value="{html.escape(encoded,quote=True)}">{number(value,field)}</td>'


def row_html(identifier: str, symbol: str, period: str, value: dict, fields: tuple,
             kind: str, label: str | None = None) -> str:
    """機能: 1行の条件・銘柄・期間を欠落なく監査可能にする。

    引数: identifier/symbol/period/kind(str)、value(dict)、fields(tuple)、label(str|None)。
    返り値: 行HTML(str)。
    """
    attributes = f'data-kind="{kind}" data-id="{identifier}" data-symbol="{symbol}" data-period="{period}"'
    text = label if label is not None else period
    return f'<tr {attributes}><td>{html.escape(text)}</td>'+''.join(cell(field,value[field]) for field in fields)+'</tr>'


def table(rows: list[str], fields: tuple, first: str = '期間') -> str:
    """機能: 横幅を保ち、小画面でも読める数表を作る。

    引数: rows(list[str])、fields(tuple)、first(str)。返り値: 表HTML(str)。
    """
    head = '<th>'+html.escape(first)+'</th>'+''.join('<th>'+LABELS[field]+'</th>' for field in fields)
    return '<div class="scroll"><table><thead><tr>'+head+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'


def shell(title: str, body: str, preview: bool) -> str:
    """機能: 共通の暗色画面と暫定表示を作る。

    引数: title/body(str)、preview(bool)。返り値: 完全HTML(str)。
    """
    warning = '<p class="box warning" id="preview">暫定版：検証の完備確認前です。採用・運用の結論には使いません。</p>' if preview else ''
    return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title>'+STYLE+'</head><body>'+warning+body+'</body></html>'


def render_main(payload: dict, preview: bool) -> str:
    """機能: 固定8比較と3つの判定を短い主画面へまとめる。

    引数: payload(dict)、preview(bool)。返り値: 主HTML(str)。
    """
    verdict = payload['assessment']
    headline = '主案I00は、既知11セッションの事前基準を通過しました。' if verdict['既知経済目安合格'] else '主案I00は、既知11セッションの事前基準を満たしませんでした。'
    chart_link = '<a href="５分足と売買.html">５分足と売買</a>' if payload.get('chart_ready') else ''
    body = f'<nav><a href="{ALL}">全240条件の損益</a>{chart_link}</nav><h1>予想外の板圧力と独立価格対照</h1><p><strong>{headline}</strong></p>'
    body += '<p>過去から予想できる板圧力を差し引き、残った圧力と価格の順行が一致した時に1枚で入ります。価格だけの入口などと、同じ返済条件で比べました。</p>'
    body += '<div class="status">'
    for key, label in (('基礎候補','基礎成績'), ('板の比較付加価値','板情報の比較付加価値'), ('実行感度','伝達遅延・観測約定')):
        passed = verdict[key]
        body += f'<span data-verdict="{key}" data-value="{str(passed).lower()}" class="{"yes" if passed else "no"}">{label}：{"通過" if passed else "未達"}</span>'
    body += '</div><p class="muted">初めの2セッションは学習のみ、後の11も既知データです。未見期間の有効性は確認していません。TOPIXミニ1枚／NK225マイクロ1枚、費用0。銘柄間の円額で優劣を付けません。</p>'
    fields = MONEY_FIELDS + ('profit_factor','average_payoff','net_r','drawdown_yen')
    comparison_rows = []
    for identifier in COMPARISONS:
        for symbol in SYMBOLS:
            value = payload['index'][identifier]['symbols'][symbol]
            comparison_rows.append(row_html(identifier,symbol,'全13セッション',value,fields,'comparison',f'{identifier} {symbol}'))
    body += '<h2>固定した8比較</h2>'+table(comparison_rows,fields,'手法・銘柄')
    body += '<p class="table-note">損失は正の額で表示。R＝その取引の初期予定損失、合計R＝各取引の損益÷Rの和。最大下落は含み損益を含む口座曲線。利益÷損失と平均比率の未定義は合格にしません。</p>'
    body += '<details><summary>各手法の違い</summary>'
    for identifier in COMPARISONS:
        spec = payload['index'][identifier]['spec']
        body += f'<p><strong>{identifier} {html.escape(spec["name"])}</strong><br>{html.escape(description(spec))}</p>'
    body += '</details><details><summary>エントリー・返済と採否条件</summary>'
    body += '<p>主案は過去3区間の板圧力などから次の圧力を推定し、観測値との差を過去の誤差尺度で割ります。絶対値1に達した方向と、0.05ATR以上の価格順行が一致すれば発注。弱まって0.5未満へ戻るまで同じ強さを繰り返し発火させません。係数と尺度はセッション開始前に固定します。</p>'
    body += '<p>新規は次の原本行の観測価格。判断時の公開ATRと2呼値の大きい方を呼値へ切り上げ、幅rを固定します。約定後に1r損切り・2r利確のOCOを発注し、子注文も次行から有効。約定30分後または場末で成行返済を予約し、返済後は5分休止します。時間返済は予約時刻の次行以降に執行します。ナイトも場内で全返済します。</p>'
    body += '<p>両銘柄で20決済・6活動セッション・買い売り各3以上、黒字、利益÷損失と平均利益÷平均損失が各1.2以上、最大勝ち取引と最大黒字セッションをそれぞれ除いても非赤字が必要です。さらにI00の合計RがI01・I03・I19・I04・乱数64通りの中央値を全て超え、1／5／15秒伝達と観測価格返済の4条件も基礎基準を満たす必要があります。</p>'
    body += '<p>I03は板が使える時刻を共有する価格対照、I19は板の可用性で間引かない価格対照です。差は市場への因果効果や正式な有意確率ではありません。相手確認I05/I06の結果は主案と分けて扱います。</p></details>'
    response_fields = ('件数','正方向数','逆方向数','同値数','平均ATR反応')
    response_rows = []
    for identifier in COMPARISONS:
        for symbol in SYMBOLS:
            for horizon in ('5','15'):
                item = payload['responses'][identifier][symbol][horizon]
                response_rows.append(row_html(identifier,symbol,horizon,item,response_fields,'response',f'{identifier} {symbol} {horizon}分'))
    body += '<details><summary>5分・15分後の価格反応（評価専用）</summary><p>候補の次行を起点に後の価格を測った資料です。売買の判断には使いません。窓は重複し、実約定時刻や独立標本数とは一致しません。</p>'+table(response_rows,response_fields,'手法・銘柄・時間')+'</details>'
    body += '<details><summary>監査・再現資料</summary><ul>'
    for label, name in (('固定した条件','探索条件の固定.json'), ('経済判定','assess_results.json'),
                        ('全再生の完了','主再生の完了.json'), ('集計・採否の人工検査','check_assessment.md'),
                        ('注文の人工反証','check_engine_adversarial.md'), ('表示数表の監査','report_audit.json')):
        body += f'<li><a href="../../work/wave_v39/{name}">{label}</a></li>'
    body += '</ul></details>'
    return shell('予想外の板圧力と独立価格対照',body,preview)


def render_all(payload: dict, preview: bool) -> str:
    """機能: 全240条件を選択し、2市場の全期間・週・セッション数表を読む画面を作る。

    引数: payload(dict)、preview(bool)。返り値: 全条件HTML(str)。
    """
    body = f'<nav><a href="{MAIN}">短い比較へ戻る</a></nav><h1>全240条件の損益</h1><p>1回の決済は1枚。利益・損失は別集計し、同値は勝敗から分けます。週はセッション開始日で区切ります。</p>'
    body += '<label for="method">手法 </label><select id="method">'
    for spec in payload['specs']:
        body += f'<option value="{spec["id"]}">{html.escape(spec["id"]+" "+spec["name"])}</option>'
    body += '</select><p class="muted">全13のうち初めの2は学習のみで取引0。後の11も既知データです。金額はTOPIXミニ／NK225マイクロ、各1枚・費用0。</p>'
    fields = MONEY_FIELDS + UNIT_FIELDS
    for i, spec in enumerate(payload['specs']):
        identifier = spec['id']
        body += f'<section class="method" id="method-{identifier}" data-method="{identifier}"'+(' hidden' if i else '')+'>'
        body += f'<h2>{html.escape(identifier+" "+spec["name"])}</h2><p>{html.escape(description(spec))}</p>'
        body += '<p class="muted">共通返済：固定1r損切り／2r利確。約定30分後・場末に市場返済を予約、返済後5分休止。</p>'
        for symbol in SYMBOLS:
            rows = [row for row in payload['sessions'][identifier] if row['symbol']==symbol]
            display = periods(rows)
            body += f'<h3>{symbol}</h3>'+table([row_html(identifier,symbol,period,value,fields,'profit') for period,value in display[:3]],fields)
            body += '<details><summary>各13セッションの内訳</summary>'+table([row_html(identifier,symbol,period,value,fields,'profit') for period,value in display[3:]],fields)+'</details>'
        body += '</section>'
    body += '''<!--
機能: 選択した固定手法の2市場の表だけを表示する。データの再計算・順位変更はしない。
引数: 手法選択欄のvalue(str)。返り値: なし。全240条件の表はHTML内に保持する。
--><script>
const select=document.getElementById('method');
/**
 * 機能: 選択IDの表示へ切り替える。
 * 引数: なし。返り値: なし。
 */
function showMethod(){document.querySelectorAll('[data-method]').forEach(section=>{section.hidden=section.dataset.method!==select.value;});}
select.addEventListener('change',showMethod);showMethod();
</script>'''
    return shell('全240条件の損益',body,preview)


def load_payload() -> tuple[dict, dict]:
    """機能: 完了した全240条件の保存結果だけから表示資料を作る。

    引数: なし。返り値: 表示値・全参照指紋(tuple[dict,dict])。未完了の一部条件は表示しない。
    """
    references = {}
    def source(path: Path) -> object:
        """機能: 読取資料を指紋へ結ぶ。

        引数: path(Path)。返り値: 保存内容(object)。
        """
        value = read(path)
        references[path.relative_to(ROOT).as_posix()] = digest(path)
        return value
    fixed = source(HERE/'探索条件の固定.json')
    complete = source(HERE/'主再生の完了.json')
    assert complete['全条件数']==240 and complete['全入力数']==6240 and complete['全独立会計合格']
    assert complete['固定SHA256']==digest(HERE/'探索条件の固定.json')
    index = source(HERE/'全条件の期間集計.json.gz')
    verdict = source(HERE/'assess_results.json')
    specs = fixed['主条件'] + fixed['補助条件']
    assert len(specs)==240 and set(index)=={spec['id'] for spec in specs}
    sessions = {}
    for spec in specs:
        identifier = spec['id']
        assert index[identifier]['spec']==spec
        rows = source(HERE/'sessions'/(identifier+'.json.gz'))
        assert len(rows)==26 and len({(row['session'],row['symbol']) for row in rows})==26
        sessions[identifier] = rows
    responses = {}
    for identifier in COMPARISONS:
        values = source(HERE/'responses'/(identifier+'.json.gz'))
        responses[identifier] = {}
        for symbol in SYMBOLS:
            responses[identifier][symbol] = {}
            for horizon in ('5','15'):
                details = [record for row in values if row['symbol']==symbol for record in row['評価専用未来反応'][horizon]['明細']]
                moves = [record[4] for record in details]
                responses[identifier][symbol][horizon] = dict(件数=len(moves), 正方向数=sum(v>0 for v in moves),
                    逆方向数=sum(v<0 for v in moves), 同値数=sum(v==0 for v in moves), 平均ATR反応=sum(moves)/len(moves) if moves else None)
    return dict(specs=specs,index=index,assessment=verdict,sessions=sessions,responses=responses,
        chart_ready=(OUT/'５分足と売買.html').is_file()), references


def verify_guard() -> dict:
    """機能: 正式表示の前に親が作る完備証跡と全参照を照合する。

    引数: なし。返り値: 完備記録(dict)。未保存・不成功・指紋差は拒否する。
    """
    path = HERE/'完備監査.json'
    value = read(path)
    assert value['検証完了'] is True
    for relative, sha in value['参照資料SHA256'].items():
        assert digest(ROOT/relative)==sha, relative
    return value


def main() -> None:
    """機能: 完備経由又は明示的な暫定表示として2つのHTMLを生成する。

    引数: --preview(bool)。返り値: なし(None)。売買・学習・採否は変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args()
    if not args.preview:
        verify_guard()
    payload, references = load_payload()
    if not args.preview:
        references[(HERE/'完備監査.json').relative_to(ROOT).as_posix()]=digest(HERE/'完備監査.json')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/MAIN).write_text(render_main(payload,args.preview), encoding='utf-8')
    (OUT/ALL).write_text(render_all(payload,args.preview), encoding='utf-8')
    manifest = dict(暫定版=args.preview, 固定比較=list(COMPARISONS), 全条件数=240, 比較行数=16,
        損益行数=7680, 未来反応行数=32, 参照資料SHA256=references,
        生成実装SHA256=digest(Path(__file__)),
        出力SHA256={path.relative_to(ROOT).as_posix():digest(path) for path in (OUT/MAIN, OUT/ALL)})
    (HERE/'report_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(暫定版=args.preview, 比較行数=16, 損益行数=7680, 出力=str(OUT)),ensure_ascii=False))


if __name__=='__main__':
    main()
