"""十分な観測を要求する新入口二出口と同出口VETOを、全33場の短い比較へ表示する。"""

import hashlib
import html
import json
from pathlib import Path

import e01_trade_report
import range_report
import trade_report


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = range_report.PUBLIC
SOURCE = HERE / 'e01_known_veto/finance/結果.json'
FIXED = HERE / 'e01_known_veto/金融事前固定.json'
TITLE = '情報不足を見送る入口と全セッション損益'


def read(path: Path) -> tuple[dict, str]:
    """
    機能: 完成した小会計と結果前固定資料を一読して出典指紋を残す。
    引数: path(Path)は保存済みJSON。
    返り値: tuple[dict,str]は内容とSHA256。大入力又は金融は利用しない。
    """
    saved = path.read_bytes()
    return json.loads(saved), hashlib.sha256(saved).hexdigest()


def explanation(case: dict) -> str:
    """
    機能: 情報資格の追加と元の逆票拒否を区別して入口・途中・出口を説明する。
    引数: case(dict)は表示条件と変更元ラベル。
    返り値: strは日本語の三行HTML。観測成立を方向支持と混同しない。
    """
    gate = ('直近60代理秒を測れ、方向更新2票以上がある場合だけ対象にする。その中で強い逆票（注文方向の釣合い≤−0.25）なら見送る。'
            if case['kind'] == '新条件' else
            '強い逆票があれば見送る。観測不明・方向更新2票未満は許可する元の条件。')
    exit_text = ('場の料金込み清算利益がTOPIX2,500円・日経1,000円、又は損失が20,000円・8,000円へ達したら、次正常気配で残UIDを返済し場内の新規を終える。'
                 if case['config']['exit'] == 'P1L8' else '元E01の途中・追跡返済を維持し、全玉を場内返済する。')
    return '<p><b>入口：</b>'+gate+' 次正常気配で新規。</p><p><b>途中：</b>元の紙上候補と実建玉を順番に運転し、拒否後の再参加も再現する。保有後へ更新票の条件は追加しない。</p><p><b>出口：</b>'+exit_text+'</p>'


def diagnostic(case: dict) -> str:
    """
    機能: 同出口VETOからの五寄与を、避け損失と失った利益に分けて表示する。
    引数: case(dict)は新条件の診断、又は診断のない保存対照。
    返り値: strは折畳み表。変更元でないCONFIRMとの差を混ぜない。
    """
    if case['diagnosis'] is None:
        return ''
    rows = []
    for symbol in ('TOPIX','NK225'):
        value = case['diagnosis'][symbol]
        row = '<tr><td>'+symbol+'</td>'
        for key in ('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支'):
            row += range_report.cell(value[key], key == '失った基準利益')
        rows.append(row+'</tr>')
    return '<details><summary>同じ出口の旧条件との差</summary><div class="scroll"><table><thead><tr><th>商品</th><th>収支差</th><th>避けた損失</th><th>失った利益</th><th>共通出口差</th><th>後続入口</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></details>'


def main() -> None:
    """
    機能: 新二条件と同exit保存二対照の全33場を、未達の結論付きで表示する。
    引数: なし。金融完成・132会計・不変sourceの証跡だけを利用する。
    返り値: None。現在板、金融又は元paperを再生しない。
    """
    source, source_sha = read(SOURCE)
    fixed, fixed_sha = read(FIXED)
    assert source['全合格'] and source['新政策会計'] == 132 and source['新gateengine'] == 66
    assert source['configs'] == fixed['configs'] and source['source開始終端一致']
    cases = {}
    for config in source['configs']:
        identifier = config['id']
        for kind, selected, rows, values in (
                ('新条件', identifier, source['results'][identifier]['rows'], source['diagnosis'][identifier]),
                ('保存対照', config['baseline_id'], fixed['baseline'][identifier]['rows'], None)):
            mapped = [e01_trade_report.mapped(r) for r in rows]
            assert len(mapped) == 66
            cases[selected] = dict(kind=kind,config=config,rows=mapped,
                                   summary={s:e01_trade_report.summarize(mapped,s) for s in ('TOPIX','NK225')},diagnosis=values)
    # ----------------------------------------
    # 当時の入口を変えた後の全運転として比較する。
    summary_rows, sections, options = [], [], []
    for identifier, case in cases.items():
        row = '<tr><td>'+case['kind']+'・'+case['config']['exit']+'</td>'
        for symbol in ('TOPIX','NK225'):
            value = case['summary'][symbol]
            row += range_report.cell(value['net'])+f'<td>{value["positive"]}/{value["negative"]}/{value["no_trade"]}</td>'
            row += '<td>'+range_report.number(value['profit_share']*100,1)+'%</td>'+range_report.cell(value['top3_excluded'])
        summary_rows.append(row+'</tr>')
        options.append('<option value="'+html.escape(identifier,quote=True)+'">'+case['kind']+'：'+html.escape(identifier)+'</option>')
        sections.append('<section data-case="'+html.escape(identifier,quote=True)+'" hidden><h2>'+html.escape(identifier)+'</h2>'+explanation(case)+diagnostic(case)+trade_report.session_table(case,source['sessions'])+'</section>')
    first = next(c['id'] for c in source['configs'] if c['exit'] == 'P1L8')
    css = '*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#dce4f2;font:16px/1.7 system-ui}main{max-width:1360px;margin:auto;padding:26px 20px}h1{font-size:26px}h2{font-size:20px;overflow-wrap:anywhere}a{color:#8fbeff}.note{color:#aab9d0}.scroll{overflow:auto;max-width:100%;margin:16px 0}table{border-collapse:collapse;min-width:1120px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #33425a;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;background:#18263b;color:#dce4f2;border:1px solid #72819a;padding:12px;font-size:15px}section{border:1px solid #33425a;padding:20px;border-radius:10px;margin:22px 0}section[hidden]{display:none}details summary{cursor:pointer;color:#b6caff}@media(max-width:600px){main{padding:16px 12px}section{padding:12px}h1{font-size:23px}}'
    script = '''/**
 * 機能: 保存された四比較の説明と全33場の表を切り替える。
 * @param {string} id - 表示する条件ID。
 * @returns {undefined} 表示だけを更新し、金融・通信は行わない。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase(__FIRST__);'''.replace('__FIRST__',json.dumps(first))
    document = '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+'</title><style>'+css+'</style></head><body><!--\n[コンポーネント概要]\n#comparison は同出口の新旧条件を比較します。#case は全33場の表示選択です。\n[data-case] は選択した条件だけ表示し、.scroll は狭い画面の表横スクロールを管理します。\n--> <main><h1>'+TITLE+'</h1><p><b>情報不足を避けても、両商品共通の安定利益は得られませんでした。</b>小利益終了版のTOPIXは旧版比+999円、日経は−1,780円。TOPIXは4赤字場が残り、金額利益80%も未達です。</p><p>旧損失40,836円を避けた一方、旧利益16,083円を捨て、新たな参加で23,754円を失ったため、TOPIXの純改善は小さくなりました。</p><p class="note">既知33場。初回TOPIXミニ5枚／日経マイクロ10枚、上限10枚／20枚。手数料とラージ気配差込み。更新窓は現在値時計の代理で、真の攻撃売買方向や受信順は未確認。公開時の観測資格だけを変えています。</p><div class="scroll"><table id="comparison"><thead><tr><th rowspan="2">比較</th><th colspan="4">TOPIXミニ</th><th colspan="4">日経マイクロ</th></tr><tr>'+('<th>収支</th><th>黒字/赤字/無取引</th><th>金額利益割合</th><th>上位3利益場除外</th>'*2)+'</tr></thead><tbody>'+''.join(summary_rows)+'</tbody></table></div><select id="case" aria-label="比較条件">'+''.join(options)+'</select>'+''.join(sections)+'<p class="note">無取引は勝ちに含めません。平均的な利益範囲の質問には、旧商品別代表の大勝ち3場を除いた全期間金額比57.1%／67.5%を別に報告しています。本表の新条件は日経の肯定票要求版を上回る条件ではありません。</p><p><a href="今回の結論と残す候補.html">中断前に残した比較基準</a> · <a href="E01で残った損失と改善の具体例.md">具体損失と失った勝ち</a> · <a href="README.md">継続段階と読む順序</a></p></main><script>'+script+'</script></body></html>'
    # ----------------------------------------
    # 表示根拠を金融結果から分離して公開する。
    public = dict(sessions=source['sessions'],cases=cases,
                  sources={SOURCE.relative_to(ROOT).as_posix():source_sha,FIXED.relative_to(ROOT).as_posix():fixed_sha},
                  新金融再生=0,現在金融='未測定',未見確認=0)
    (PUBLIC/'情報不足見送りの公開会計.json').write_text(json.dumps(public,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    (PUBLIC/(TITLE+'.html')).write_text(document,encoding='utf8')
    print('新二条件・保存二対照の全33場を公開。金融再生0。')


if __name__ == '__main__':
    main()
