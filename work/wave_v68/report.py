"""損失削減の結論と全場損益を短い暗色HTMLへまとめる。"""

from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import sys

import pandas as pd

import compare

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00065_E01とR01の損失低減'
SYMBOLS = compare.SYMBOLS


def explanation(variant: dict) -> str:
    """機能: 比較部品を機械実行に対応した短い日本語で説明する。

    引数: variant(dict)。返り値: 説明(str)。
    """
    code = variant['id'].removeprefix(variant['base']).lstrip('_')
    texts = {
        '': '元の損失管理を維持する比較基準。',
        'S50': '出口計算用の仮想建玉の損失枠を0.75ATRから0.5ATRへ狭める。',
        'S375': '同じ仮想建玉の損失枠を0.375ATRへ狭める。',
        'T05H': '建てて5分以降、一度も0.5ATRまで伸びず、現在0.25ATR以上逆行していれば一度減量。TOPIX5→3枚、NK10→5枚。',
        'T05X': '建てて5分以降、一度も0.5ATRまで伸びず、現在0.25ATR以上逆行していれば全返済。',
        'T10X': '同じ失敗判定を5分でなく10分以降に行い、全返済する。',
        'T15S': '出口用仮想建玉が15分たっても0.5ATR未達なら、その損失枠を0.5ATRへ狭める。',
        'T30S': '同じ損失枠短縮を30分から適用する。',
        'B15H': '1.5ATRまで伸びず0.25ATR以上逆行し、新しい板中値の2分・30秒の動きも逆なら一度減量する。',
        'B05X': '0.5ATR未達・0.25ATR逆行に加え、新しい板中値の動きが逆なら全返済する。',
        'M25X': '新規後に公開された両市場EMAの開始条件が崩れ、0.25ATR以上逆行していれば全返済する。',
        'A50': '実建玉の評価損益から支払済み料金を引いた損失が初回枚数×ATRの半分に達したら、全返済を予約する。',
        'P2T': '新規から全返済までを1組とし、手数料後2組連続で負けたら新規を30分休む。その後、連敗数を0から数え直す。',
        'P2E': '同じ2連敗で、そのセッションの新規を終了する。',
        'D2R': '手数料後の各組収支を初回枚数×ATRで割った累計が−2に達したら、そのセッションの新規を終了する。',
        'S50_T05H': '仮想損失枠0.5ATRと、5分の失敗建玉減量を組み合わせる。',
        'S50_B15H': '仮想損失枠0.5ATRと、新しい板中値悪化による失敗建玉減量を組み合わせる。',
        'T05H_P2T': '5分の失敗建玉減量に加え、2連敗後30分休む。',
        'M25X_P2T': 'EMA失効時の損失撤退に加え、2連敗後30分休む。',
    }
    return texts[code]


def weekly(rows: list[dict], symbol: str) -> list[dict]:
    """機能: セッションの収録日から週内の決済損益を集計する。

    引数: rows(list[dict])、symbol(str)。返り値: 週別集計(list[dict])。
    """
    groups = {}
    for row in sorted(rows,key=lambda r:r['session']):
        if row['symbol'] != symbol:
            continue
        year,week,_ = datetime.fromisoformat(row['session'][:10]).isocalendar()
        key = (year,week)
        if key not in groups:
            groups[key] = dict(label=row['session'][:10]+'の週（収録分）',sessions=0,
                profit=0.,loss=0.,net=0.,fees=0,winning_lots=0,losing_lots=0)
        target = groups[key]
        for field in ('profit','loss','net','fees','winning_lots','losing_lots'):
            target[field] += row[field]
        target['sessions'] += 1
    return list(groups.values())


def public_data() -> dict:
    """機能: 全38条件の会計、売買図、選定証跡を通信不要の表示形式へ整える。

    引数: なし。返り値: 表示データ(dict)。
    """
    fixed = compare.read(HERE/'事前固定.json')
    decisions = compare.read(HERE/'損失削減の比較と選定.json')
    review = compare.read(HERE/'review/気配価格置換の集計.json')
    quote = {v['id']:v for v in review['methods']}
    assert len(quote) == 38
    methods = {}
    # ----------------------------------------
    # 原本行の時刻は保存入力から得る。チャート足の開始時刻を売買時刻に流用しない。
    sys.path.insert(0,str(ROOT/'work/wave_v67'))
    import study
    inputs,_,hashes = study.load_inputs()
    (HERE/'入力指紋.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf8')
    for variant in fixed['条件']:
        packet = compare.read(HERE/'observed'/(variant['id']+'.json.gz'))
        display = {k:packet[k] for k in ('variant','rows','periods')}
        display['explanation'] = explanation(variant)
        display['review'] = decisions['methods'][variant['id']]
        display['quote'] = quote[variant['id']]['periods']
        display['weeks'] = {s:weekly(packet['rows'],s) for s in SYMBOLS}
        display['orders'] = {}
        for ledger in packet['ledgers']:
            key = (ledger['session'],ledger['symbol'])
            display['orders']['|'.join(key)] = [o+[float(inputs[key]['time_s'][int(o[0])])] for o in ledger['orders']]
        methods[variant['id']] = display
    bars = {}
    for session in fixed['全セッション']:
        for symbol in SYMBOLS:
            frame = pd.read_csv(ROOT/'candle_5min'/symbol/(session+'.csv'))
            bars[session+'|'+symbol] = [[datetime.fromisoformat(r.time).timestamp(),r.open,r.high,r.low,r.close] for r in frame.itertuples()]
    chosen = decisions['selected']
    primary = ['E01','R01']+[r['id'] for r in decisions['front_rank'][:3]]
    primary = list(dict.fromkeys(primary))
    return dict(fixed=fixed, selected=chosen, front_rank=decisions['front_rank'], methods=methods,
        bars=bars, primary=primary, initial='R01_P2T',
        sha={v['id']:hashlib.sha256((HERE/'observed'/(v['id']+'.json.gz')).read_bytes()).hexdigest() for v in fixed['条件']})


def all_conditions(data: dict) -> str:
    """機能: 損失・利益の代償と採否を全条件の別表にする。

    引数: data(dict)。返り値: 暗色HTML(str)。
    """
    rows = []
    for identifier,result in data['methods'].items():
        front = result['review']['comparison']['前16']
        status = '基準' if identifier in ('E01','R01') else ('合格' if all(r['eligible'] for r in front.values()) else '不合格')
        losses = ' / '.join(f"{front[s]['campaign_loss_cut']:.1%}" for s in SYMBOLS)
        profit = ' / '.join(f"{front[s]['campaign_profit_retention']:.1%}" for s in SYMBOLS)
        cells = ''.join(f'<td>{result["periods"][p][s]["net"]:+,.0f}</td>' for p in ('前16','後12','全28') for s in SYMBOLS)
        tests = '、'.join(f'{s}: '+ '・'.join(k for k,v in front[s]['tests'].items() if not v) for s in SYMBOLS if not front[s]['eligible'])
        rows.append(f'<tr><td><a href="損失を減らす改修と全セッション損益.html?method={identifier}">{identifier}</a></td><td class="text">{html.escape(result["explanation"])}</td><td>{status}<br><small>{html.escape(tests) if status=="不合格" else ""}</small></td><td>{losses}</td><td>{profit}</td>{cells}</tr>')
    return '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>損失低減の全38条件</title><style> :root{color-scheme:dark;background:#0c1420;color:#e1eaf6;font-family:Meiryo,sans-serif}body{margin:25px;line-height:1.6}a{color:#9acaff}.scroll{overflow-x:auto}table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #354961;padding:9px;text-align:right;white-space:nowrap}th{background:#192b41}.text{min-width:310px;max-width:400px;white-space:normal;text-align:left}small{font-size:11px;white-space:normal;display:block;min-width:150px}</style></head><body><h1>損失低減の全38条件</h1><p><a href="損失を減らす改修と全セッション損益.html">結論とセッション損益</a></p><p>初回TOPIXミニ5枚／NKマイクロ10枚・増玉なし・手数料後。損失削減／利益維持は各条件の元E01又はR01との比較。合否は前16のみ、TOP／NK両方に事前の基準を適用。後半で選び直していません。</p><p>以下の比率はTOP／NKの順。損失削減がマイナスなら損失増。期間収支は円。IDを開くと全場の利益・損失・枚数を確認できます。</p><div class="scroll"><table><thead><tr><th>ID</th><th>説明</th><th>前半判定</th><th>前半の負け組損失削減</th><th>前半の勝ち組利益維持</th><th>前16 TOP</th><th>前16 NK</th><th>後12 TOP</th><th>後12 NK</th><th>全28 TOP</th><th>全28 NK</th></tr></thead><tbody>'''+''.join(rows)+'</tbody></table></div></body></html>'


def main() -> None:
    """機能: 新番号に主HTML、全条件一覧、表示JSON、短い読み順を保存する。

    引数: なし。返り値: なし(None)。
    """
    data = public_data()
    OUT.mkdir(parents=True,exist_ok=True)
    raw = json.dumps(data,ensure_ascii=False,allow_nan=False)
    (OUT/'報告データ.json').write_text(raw,encoding='utf8')
    source = (HERE/'template.html').read_text(encoding='utf8')
    source = source.replace('__DATA__',raw.replace('</','<\\/'))
    (OUT/'損失を減らす改修と全セッション損益.html').write_text(source,encoding='utf8')
    (OUT/'全38条件の比較.html').write_text(all_conditions(data),encoding='utf8')
    first = '損失を減らす改修と全セッション損益.html'
    (OUT/'README.md').write_text(f'''# 作業00065 E01とR01の損失低減

最初に見るファイルは [{first}]({first}) です。

読む順序は、主HTMLの「結論・損失と利益」→選んだ手法の全セッション損益→5分足の売買図→[全38条件の比較](全38条件の比較.html)です。

[短い検証結果](検証結果.md) / [表示データ](報告データ.json)。

元E01／EMA再確認R01に18部品ずつを適用し、2基準＋36改修を保存28場で比較。初回TOPIXミニ5枚、NK225マイクロ10枚は固定、増玉なし、片方向上限10／20枚以内。途中返済後も元方式の新規時計を維持します。手数料は画像指定の立会料金、1注文合計を切捨て、新規・返済双方に課金。

選定は[事前固定](../../work/wave_v68/事前固定.json)の前16基準、後12で再確認。全28場は既知であり完全な未見検証ではありません。未来不使用は[人工経路](../../work/wave_v68/audit/人工経路の独立検査.json)・[切断と未来変更](../../work/wave_v68/audit/損失制御の因果検査.json)で検査。[独立台帳](../../work/wave_v68/audit/台帳独立会計_observed.json)、[気配価格感度](../../work/wave_v68/review/気配価格置換の完了.json)も保存。

観測値で入口・出口を全再運転した比較と、注文を固定した気配価格置換は別評価です。ラージ価格を小商品の倍率で換算した仮想結果。実小商品の板、遅延・部分約定・証拠金は未評価。A50は支払済み料金までの予算判定で将来返済料金と飛越損失は別。板中値悪化は厚さ・補充を判定する条件ではありません。

既存00064・App/E01は変更していません。現在API取得0、実注文0。
''',encoding='utf8')
    print('00065のHTMLと表示データを保存:',data['selected'])


if __name__ == '__main__':
    main()
