"""E01の完成済み比較を、短い説明と全セッション損益にする。売買は再生しない。"""

import hashlib
from html import escape
import json
from pathlib import Path
from statistics import median


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'
TITLE = 'E01の改善比較と全セッション損益.html'
SYMBOLS = ('TOPIX','NK225')


def read(path: Path) -> dict:
    """
    機能: 保存された合格済み金融資料を読む。
    引数: path(Path)はUTF-8の完成JSON。
    返り値: dictは既存会計。未完了なら停止する。
    """
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    assert value['全合格'] is True
    return value


def yen(value: float) -> str:
    """
    機能: 保存金額を円単位で整形する。
    引数: value(float)は会計の円額。
    返り値: strは三桁区切り整数文字列。
    """
    return '0' if abs(value)<.5 else f'{value:,.0f}'


def money(value: float) -> str:
    """
    機能: 収支を符号に応じた色で表示する。
    引数: value(float)は会計金額。
    返り値: strは表示HTML。数値を再推計しない。
    """
    color = 'plus' if value>1e-7 else 'minus' if value< -1e-7 else 'neutral'
    return f'<span class="{color}">{yen(value)}</span>'


def explanation(ident: str, config: dict) -> str:
    """
    機能: 入り値変更と場内停止の違いを平易に述べる。
    引数: ident(str)は条件ID、config(dict)は固定条件。
    返り値: strは短い日本語。途中判断を新しい条件へ読み替えない。
    """
    if ident.startswith('E01_PENDING_PRICE_'):
        subject = '相手市場' if config['mode']=='N' else '両市場'
        closing = ('出口は元のE01を保持。' if config['exit']=='GU' else
                   '場の清算利益1呼値分、又は損失8呼値分で残玉を次正常気配で返済し、新規終了。')
        return (f'基準と同じ指値を待つ間、{subject}の直前{config["window_seconds"]}秒の両気配が注文と反対へ1呼値以上進んだら永久取消。'
                '同じ行で既に到達した指値を取り消さず、約定後は新しい撤回条件を足さない。'+closing)
    if ident.startswith('E01_DAILY_'):
        limit = config['loss_ticks']
        loss = '追加の損失上限なし。' if limit is None else f'清算損失{limit}呼値分でも同様に終了。'
        return (f'基準と同じ有利指値で入る。場全体の手数料後清算利益が{config["profit_ticks"]}呼値×初回枚数×倍率に届いたら、'
                '次の正常気配で残玉をUID別に返済し、その場の新規を止める。'+loss)
    references = {'A_EXEC':'買う時は売気配、売る時は買気配','A_MID':'売買気配の中値',
                  'A_PASSIVE':'買う時は買気配、売る時は売気配','L_D20_BBO':'当時の現在値'}
    if ident in references:
        return (references[ident]+'を基準に0.2ATR有利な価格で指値を待つ。公開後の買ask/売bidが届けば実気配で入る。'
                '途中と出口は元のE01判断を保持し、返済は次の正常気配。未約定なら最初の仮想返済で取り消す。')
    if ident=='E01_G_U_BBO':
        return '元のE01の新規判断後、次の正常気配で買ask/売bidに入る。元の途中・出口判断を保持し、返済も次の正常気配。'
    assert ident=='L_D20_PRICE'
    return '旧現在値による理想参考。指値到達も返済も現在値で判断するため、気配約定の実用比較とは分けて見る。'


def table(rows: list[dict], sessions: list[str]) -> str:
    """
    機能: 全場の利益・損失・収支と延べ返済枚数を表示する。
    引数: rows(list[dict])は保存会計、sessions(list[str])は固定対象33場。
    返り値: strは33行と合計を持つHTML。欠けた場を0にしない。
    """
    index = {(r['session'],r['symbol']):r for r in rows}
    assert len(index)==66 and len(sessions)==33
    assert set(index)=={(s,k) for s in sessions for k in SYMBOLS}
    body = []
    for session in sessions:
        label = session.replace('_Day',' デイ').replace('_Night',' ナイト')
        cells = [f'<th>{escape(label)}</th>']
        for symbol in SYMBOLS:
            row = index[session,symbol]
            assert abs(row['利益']-row['損失']-row['収支'])<1e-5
            cells.extend([f'<td>{yen(row["利益"])}</td>',f'<td>{yen(row["損失"])}</td>',
                          f'<td>{money(row["収支"])}</td>',f'<td>{row["勝ち枚数"]}</td>',f'<td>{row["負け枚数"]}</td>'])
        body.append('<tr>'+''.join(cells)+'</tr>')
    totals = ['<th>全33場</th>']
    for symbol in SYMBOLS:
        selected = [r for r in rows if r['symbol']==symbol]
        for key in ('利益','損失','収支','勝ち枚数','負け枚数'):
            value = sum(r[key] for r in selected)
            totals.append('<td>'+(money(value) if key=='収支' else yen(value))+'</td>')
    headers = '<th>利益</th><th>損失</th><th>収支</th><th>勝ち枚数</th><th>負け枚数</th>'
    return ('<div class="scroll"><table><thead><tr><th rowspan="2">セッション</th>'
            '<th colspan="5">TOPIXミニ：初回5枚・上限10枚</th><th colspan="5">日経マイクロ：初回10枚・上限20枚</th>'
            '</tr><tr>'+headers+headers+'</tr></thead><tbody>'+''.join(body)+'</tbody>'
            '<tfoot><tr>'+''.join(totals)+'</tr></tfoot></table></div>')


def main() -> None:
    """
    機能: 三段階の保存会計を確認し、短い比較と条件切替のHTMLを公開する。
    引数: なし。参照結果は完成済み三JSONに固定する。
    返り値: None。公開資料のみ生成し、金融再生・API取得・注文は行わない。
    """
    files = ('e01_reference/結果.json','e01_anchor/結果.json','e01_daily/finance/結果.json',
             'e01_pending_price/finance/結果.json')
    cases, sources, configs = {}, [], {}
    for relative in files:
        path = HERE/relative
        value = read(path)
        configs.update({c['id']:c for c in value.get('configs',[])})
        for ident, candidate in value['results'].items():
            if ident in cases:
                previous = {(r['session'],r['symbol']):r for r in cases[ident]['rows']}
                current = {(r['session'],r['symbol']):r for r in candidate['rows']}
                assert set(previous)==set(current)
                for key in previous:
                    for field in ('利益','損失','収支','費用','勝ち枚数','負け枚数'):
                        assert abs(previous[key][field]-current[key][field])<1e-7
                continue
            cases[ident] = candidate
        sources.append(dict(path='work/wave_v106/'+relative,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    daily = read(HERE/'e01_daily/finance/結果.json')
    sessions = daily['sessions']
    metrics = {}
    for ident,case in cases.items():
        configs.setdefault(ident,case.get('case',{}))
        metrics[ident] = {}
        for symbol in SYMBOLS:
            selected = [r for r in case['rows'] if r['symbol']==symbol]
            assert len(selected)==33
            nets = [r['収支'] for r in selected]
            total = case['symbols'][symbol]
            assert abs(sum(nets)-total['収支'])<1e-5
            metrics[ident][symbol] = dict(中央値=median(nets),上位3利益場除外=sum(nets)-sum(sorted([n for n in nets if n>0],reverse=True)[:3]))
    # ----------------------------------------
    # 全条件は比較表示に使い、結果から自動的な採用や未来の性能保証へ変換しない。
    summary_rows = []
    for ident in ('L_D20_BBO','A_PASSIVE','E01_DAILY_P1_L8'):
        for symbol in SYMBOLS:
            total = cases[ident]['symbols'][symbol]
            stable = metrics[ident][symbol]
            pf = '—' if total['PF'] is None else f'{total["PF"]:.2f}'
            counts = f'{total["黒字場"]}/{total["赤字場"]}/{total["無取引場"]}'
            summary_rows.append(f'<tr><th>{escape(ident)}</th><td>{symbol}</td>'
                f'<td>{money(total["収支"])}</td><td>{counts}</td><td>{100*total["利益割合"]:.1f}%</td><td>{pf}</td>'
                f'<td>{money(stable["中央値"])}</td><td>{money(stable["上位3利益場除外"])}</td></tr>')
    options, panels = [], []
    for ident, case in cases.items():
        options.append(f'<option value="{escape(ident)}">{escape(ident)}</option>')
        panels.append(f'<section data-case="{escape(ident)}"'+('' if ident=='L_D20_BBO' else ' hidden')
            +f'><h2>{escape(ident)}</h2><p>{escape(explanation(ident,configs[ident]))}</p>'
            +table(case['rows'],sessions)+'</section>')
    css = '''
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#e2e8f0;font:15px/1.7 system-ui,sans-serif}main{max-width:1250px;margin:auto;padding:26px 18px}h1{font-size:25px}h2{font-size:20px;overflow-wrap:anywhere}a{color:#9bcfff}.note{color:#a6b5cc;font-size:13px}.scroll{overflow-x:auto;border:1px solid #334155;border-radius:7px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:13px}th,td{text-align:right;padding:9px;border-bottom:1px solid #334155}th:first-child{text-align:left}thead,tfoot{background:#1c2c44}tbody tr:nth-child(even){background:#142137}.plus{color:#79dfb5}.minus{color:#ff9298}.neutral{color:#a6b5cc}select{width:100%;max-width:700px;background:#162238;color:#e2e8f0;padding:12px;font:inherit;margin:12px 0}section{margin:18px 0}summary{cursor:pointer;color:#9bcfff}[hidden]{display:none!important}
'''
    script = '''
/**
 * 保存条件に対応する全セッション表を切り替える。
 * @param {string} ident - 選択された固定条件ID。
 * @returns {void} 一つの表を表示する。計算・通信・売買は実行しない。
 */
function showCase(ident){document.querySelectorAll('[data-case]').forEach(node=>node.hidden=node.dataset.case!==ident);}
document.getElementById('method').addEventListener('change',event=>showCase(event.target.value));
'''
    html = ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{TITLE}</title><style>{css}</style></head><body><main><h1>E01の入り値と小利益停止の比較</h1>'
        '<p><strong>両銘柄で小利益を安定して残す改善は、まだ得られていません。</strong>深い指値は日経の利益機会を減らし、小利益終了は少数の初期損失を補えませんでした。</p>'
        '<p class="note">初回TOPIX5枚・日経10枚。片方向上限10枚・20枚。両側手数料・ラージ気配代理込み、場内全返済。無取引は勝ちに数えません。'
        '同じ仮想E01を使う比較で、実建値へ元の途中停止線を引き直す検証ではありません。</p>'
        '<p class="note">原行順と価格時刻で再生。共通の受信時刻が未保存のため、実際の両市場受信順を完全には再現できません。</p>'
        '<div class="scroll"><table><thead><tr><th>手法</th><th>商品</th><th>収支</th><th>黒字/赤字/無取引</th>'
        '<th>金額利益割合</th><th>利益/損失</th><th>中央値</th><th>上位3利益場除外</th></tr></thead><tbody>'
        +''.join(summary_rows)+'</tbody></table></div><h2>説明と全33セッション</h2><select id="method">'
        +''.join(options)+'</select><p class="note">利益・損失は初回建玉から全返済までを一組にした手数料後会計。枚数は勝ち・負けの延べ返済枚数。'
        '金額利益割合＝総利益÷（総利益＋総損失）。全場は既知の探索対象です。</p>'
        +''.join(panels)+'<p><a href="README.md">資料案内</a> · <a href="E01公開会計.json">公開会計</a></p>'
        f'</main><script>{script}</script></body></html>')
    (PUBLIC/TITLE).write_text(html,encoding='utf-8',newline='\n')
    public = dict(全合格=True,sessions=sessions,results=cases,stability=metrics,根拠=sources,
        表示コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),追加金融再生=0,API取得=0)
    (PUBLIC/'E01公開会計.json').write_text(json.dumps(public,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('E01の',len(cases),'比較を全33場で表示。新金融再生0。')


if __name__=='__main__':
    main()
