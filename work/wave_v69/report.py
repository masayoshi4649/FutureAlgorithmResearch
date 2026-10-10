"""ティックの四機構と全192条件を、短い説明・全場会計・売買図へまとめる。"""

import csv
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import pickle

import study

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00066_ティック入口とIFDトレール'
MAIN = 'ティック入口とIFDトレールの損益.html'
ALL = '全192条件の比較.html'
EXAMPLE = 'T3L1_E0_O16A8W8_H60'
EXPLANATIONS = {
    1: '中値が8呼値進んだ後、4呼値逆へ戻り、両側の気配も逆方向へ動いたら反転方向へ入る。買われた後の反落、売られた後の反発を取る。',
    2: '中値が4呼値進み、2呼値押し戻され、そこから2呼値元の方向へ戻り、両側の気配も同方向なら入る。往復が終わり、元の動きが再開すると読む。',
    3: '最良気配から2呼値以内で、最良数量の0.5倍以上の表示回復を検出。直近8中値イベントで2呼値接近し、補充後の接近が1呼値を超える前に、中値が2呼値反転して両気配も反転したら入る。',
    4: '近くで板数量の回復を検出。その価格を2呼値突破し、両側の気配と直近16中値イベントの気配数量変化が突破方向を支持したら入る。',
}


def load(path: Path) -> object:
    """機能: 作業内の固定済みJSON又は台帳を読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path, data: object) -> None:
    """機能: 新作業又は公開先へ日本語JSONを保存する。

    引数: path(Path)、data(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE) or path.resolve().is_relative_to(OUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def weekly(rows: list[dict], symbol: str, sessions: list[str]) -> list[dict]:
    """機能: 日付の属する月曜を基準に、場内完結会計を週へ集計する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 週集計(list[dict])。
    """
    groups = {}
    for session in sessions:
        day = date.fromisoformat(session[:10])
        monday = day-timedelta(days=day.weekday())
        groups.setdefault(monday,[]).append(session)
    out = []
    for monday, keys in sorted(groups.items()):
        a = study.aggregate(rows,symbol,keys)
        a['label'] = f'{monday:%m/%d}週（{len(keys)}場）'
        out.append(a)
    return out


def charts(sessions: list[str]) -> dict:
    """機能: 読取専用の五分足を表示用の数値配列へ変換する。

    引数: sessions(list[str])。返り値: 場・銘柄キーの五分足(dict)。
    """
    out = {}
    for session in sessions:
        for symbol in study.SYMBOLS:
            path = ROOT/'candle_5min'/symbol/(session+'.csv')
            with path.open(encoding='utf-8-sig',newline='') as stream:
                bars = [[datetime.fromisoformat(r['time']).timestamp(),
                         *[float(r[k]) for k in ('open','high','low','close')]] for r in csv.DictReader(stream)]
            out[session+'|'+symbol] = bars
    return out


def enrich(result: dict, selected: dict, ready: dict, sessions: list[str]) -> dict:
    """機能: 前半だけで選んだ結果へ、週会計と固定台帳の約定時刻を追加する。

    引数: result/selected/ready(dict)、sessions(list[str])。返り値: 表示用手法(dict)。
    """
    method = dict(result)
    method.update(id=result['config']['id'],family=result['config']['family'],
                  eligible=selected.get('eligible',False),explanation=EXPLANATIONS[result['config']['family']])
    method['weeks'] = {s:weekly(result['rows'],s,sessions) for s in study.SYMBOLS}
    method['orders'] = {}
    ledger = load(HERE/'ledgers'/(method['id']+'.pkl'))
    for key, account in ledger.items():
        values = []
        for row in account['orders']:
            value = row.tolist()
            value.append(float(ready[key]['time_s'][int(row[0])]))
            values.append(value)
        method['orders']['|'.join(key)] = values
    return method


def current_note() -> dict:
    """機能: 一度取得した現在場の状態から未検証理由を保存する。

    引数: なし。返り値: 現在場の確認内容(dict)。
    """
    state = load(HERE/'current/取得時の状態.json')
    target = [r for r in state['current'] if r['code'] in study.SYMBOLS]
    assert len(target)==2 and all(r['records']==0 for r in target)
    note = dict(状態API取得回数=1,現在板取得回数=0,実注文=0,
                session=target[0]['sessionId'],records={r['code']:r['records'] for r in target},
                evaluated=False,message='一度確認した現在ナイトは両銘柄データ0件。現在場の答え合わせは未実施、無取引を勝ちには数えません。')
    save(HERE/'current/現在場の確認.json',note)
    return note


def fill(template: Path, data: dict, target: Path) -> None:
    """機能: 表示用JSONをHTMLへ安全に埋め込む。

    引数: template/target(Path)、data(dict)。返り値: なし(None)。
    """
    source = template.read_text(encoding='utf8')
    assert source.count('__DATA__')==1
    embedded = json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    target.write_text(source.replace('__DATA__',embedded),encoding='utf8')


def main() -> None:
    """機能: 独立監査完了を確認し、主レポートと全条件比較を生成する。

    引数: なし。返り値: なし(None)。
    """
    frozen = load(HERE/'事前固定.json')
    selection = load(HERE/'機構別の前半選定.json')
    audit = load(HERE/'audit/全条件の独立監査.json')
    assert audit['全合格']
    sessions = frozen['全セッション']
    assert len(sessions)==28
    results = [load(p) for p in sorted((HERE/'results').glob('*.json'))]
    assert len(results)==192
    by_id = {r['config']['id']:r for r in results}
    ready = load(HERE/'prepared/inputs.pkl')
    methods = [enrich(by_id[s['id']],s,ready,sessions) for s in selection['選定']]
    example = enrich(by_id[EXAMPLE],{},ready,sessions)
    example['explanation'] = '最良数量の1倍以上の表示回復を検出。4呼値接近した後、さらに1呼値を超えて進む前に中値が4呼値反転し、両気配も反転したら入る。損切り16呼値、8呼値順行で幅8呼値の返済トレール。最長60分。'
    live = current_note()
    notes = [
        '28セッション・両銘柄・192条件。入口4機構×2強度、新規逆指値／新規トレール、出口4設定、最長5／30／60分。ATR・移動平均は使用しません。',
        '価格ティックは最良買い・売り気配の中値の変化です。呼値幅は参照ラージでTOPIX0.5pt、日経10円。板更新行数、約定件数とは別です。',
        '初回TOPIXミニ5枚・日経マイクロ10枚、片方向上限10枚・20枚。増玉・両建てなし。枚数を増やして収支を良くする比較は行っていません。',
        '親予約→次の原本行から条件監視→成立した次の有効気配行で約定。子は新規約定後の次の観測から監視し、成立後の次の有効気配で返済。買いask・売りbidです。',
        'IFD-OCOの子の損切り・追跡開始価格は親予約時点の気配から設定する絶対価格です。実約定価格で再設定しません。通信等によるギャップは損失幅を広げる場合があります。',
        '親は120秒で取消、全返済後30秒休止。日中15:34／夜間05:49に場内返済を判断。最長保有はスクリプトが取消・成行返済を判断する処理で、注文の有効期限だけではありません。',
        '時計は最終約定時刻。同時計の更新は原本行順です。実際の板受信遅延、個別注文・取消、補充した人の意図は識別していません。表示回復は補充の代理指標です。',
        '参照ラージの気配をミニ・マイクロの仮想約定価格に使います。実商品の気配、100%約定、数量による価格悪化、通信・取消競合は再現していません。',
        '手数料は片道TOPIXmini41.8円／枚、NK225micro11円／枚。新規・返済の1注文合計を切捨て。利益・損失・収支に既に含めています。手数料列を再度引かないでください。',
        '中値感度は同じ注文行の買い・売り価格だけを中値へ置換した参考値です。条件を再生成した別バックテストでも、実際に約定できる成績でもありません。',
        '各機構の代表は前16だけで選択。両銘柄20取引・8取引場以上で、1取引平均の料金後呼値収支が悪い銘柄を最大化。両方黒字かつ平均勝ち／負け比>1なら有望。全4代表が未達でした。',
        '全28は過去の研究でも既知です。途中切断と未来改変は合格していますが、前半・後半比較を完全な未知データ検証とは呼びません。',
        '10,752口座・647,676注文・323,838決済について、次原本気配、FIFO、整数料金、全観測の含み時価、期間最大下落を独立照合。人工経路12種と途中切断・未来改変も合格。',
    ]
    data = dict(title='ティック入口とIFDトレールの損益',sessions=sessions,methods=methods,exploratory=example,
                bars=charts(sessions),values={'TOPIX':1000,'NK225':10},fees={'TOPIX':41.8,'NK225':11},
                conclusion='ティックの反転・再開・補充・突破を192条件で検証。前半だけで選んだ4代表は全期間赤字でした。両銘柄で黒字の条件は1つありますが、取引が少なく損小利大も未達のため、有望な手法とはまだ判断しません。',
                live=live,notes=notes,conditionsUrl=ALL)
    OUT.mkdir(parents=True,exist_ok=True)
    fill(HERE/'report/template.html',data,OUT/MAIN)
    all_data = dict(title='全192条件の比較',sessions=sessions,methods=results,
                    selectedIds=[s['id'] for s in selection['選定']],mainUrl=MAIN)
    fill(HERE/'report/all_template.html',all_data,OUT/ALL)
    save(HERE/'公開会計.json',dict(選定=selection,現在場=live,主HTML_SHA256=hashlib.sha256((OUT/MAIN).read_bytes()).hexdigest(),
                               全条件HTML_SHA256=hashlib.sha256((OUT/ALL).read_bytes()).hexdigest(),全セッション=sessions))
    print('作業00066の主HTML・全192条件HTMLを生成:',OUT)


if __name__=='__main__':
    main()
