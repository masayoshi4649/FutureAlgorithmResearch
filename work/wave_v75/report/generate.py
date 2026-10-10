"""二指数の共同判断と同設定の自己証拠対照を、固定結果から簡潔な暗色報告へ接続する。"""

import csv
from datetime import date,datetime,timedelta
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
OUT=ROOT/'アルゴリズム調査/00071_二指数の共同方向と先行追随'
MAIN='二指数を同時に見る手法と全セッション損益.html'
ALL='全336条件の比較.html'
SYMBOLS=('TOPIX','NK225')
NAMES=('共通方向','先行に追随','先行失敗','相対価格の戻り','両板の圧力先行','片側の吸収失敗','自動選択')
SHORT=(
    '両指数が同方向へ進み、自分の両気配も進んだ所に入る。',
    '相手の進みが大きく、自分の進みが小さい時、自分も同方向へ動き始めたら入る。',
    '自分だけが進み、相手が追随せず、自分の両気配が逆へ動いたら逆方向に入る。',
    '両指数の価格比が過去平均から離れ、偏りが縮み始めたら戻る方向に入る。',
    '両板の注文増減が同方向に偏り、価格の進みは小さい時、自分の気配進行に入る。',
    '相手は進んでいるが、自分の価格が板圧に応えず逆へ動き始めたら、その逆方向に入る。',
    '共通方向→追随→相対価格の戻りの順に、成立した入口を機械的に選ぶ。')


def load(path: Path) -> object:
    """機能: 完成済みの結果・台帳・入力を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。原本と過去成果を変更しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 公開物と台帳の内容指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):
            h.update(chunk)
    return h.hexdigest()


def save(path: Path,value: dict) -> None:
    """機能: 担当する報告領域だけへUTF-8のJSONを保存する。

    引数: path(Path)、value(dict)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE) or path.resolve().is_relative_to(OUT)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def brief(c: dict) -> str:
    """機能: 一覧向けに共同・対照と固定変数を一行で説明する。

    引数: c(dict)。返り値: 日本語説明(str)。
    """
    return f"{'共同' if c['paired'] else '自市場証拠の対照'}／{c['name']}／過去{c['window']}秒／強度{c['level']}／幅{c['width_fraction']*100:g}%／{c['hold_seconds']/60:g}分返済判断"


def steps(c: dict) -> dict:
    """機能: 実装された条件の入口・途中・出口を短い日本語へ整理する。

    引数: c(dict)。返り値: 三段階の説明(dict[str,str])。
    """
    family=c['family']
    threshold=.03 if c['level']==0 else .06
    extra=(f"進行の基準は過去{c['window']}秒で{threshold:g}%、自分の15秒の両気配が1呼値進むこと。" if family in (1,2,3)
        else f"過去{c['window']}秒の板増減の符号比{10 if c['level']==0 else 20}%を使い、自分の15秒の両気配で確認。" if family in (5,6)
        else f"過去{c['window']*4}秒の価格比平均から{1.5 if c['level']==0 else 2.5}標準偏差以上、過去相関0.3以上、自分の両気配で戻りを確認。" if family==4
        else f"過去{c['window']}秒・強度{c['level']}の固定条件で選ぶ。")
    entry=SHORT[family-1]+extra
    if family==1:
        entry=f"両方の中値が過去{c['window']}秒で同方向へ{threshold:g}%以上進み、直近15秒で自分の売買両気配が1呼値以上進み、相手の中値も逆行していなければ、その方向へ入る。"
    return dict(entry=entry,
        middle='全量を保有し、順行する極値を追跡。反対信号だけでは返済せず、追加玉・両建てはしない。',
        exit=f"始値{c['width_fraction']*100:g}%幅で、実建値から即時トレール。同幅の逆行で損切り、{c['hold_seconds']/60:g}分で返済判断。場末も全返済。")


def minimal(result: dict) -> dict:
    """機能: 一覧と対照に必要な明細会計だけを保持する。

    引数: result(dict)。返り値: 省容量の結果(dict)。
    """
    fields=('session','symbol','profit','loss','net','fees','trades','wins','losses','winning_lots','losing_lots',
            'money_loss_share','drawdown','candidate_count','payoff')
    c=result['config']
    return dict(id=c['id'],config=c,configText=brief(c),rows=[{k:r[k] for k in fields} for r in result['rows']],periods=result['periods'])


def aggregate(rows: list[dict],symbol: str,sessions: list[str]) -> dict:
    """機能: 同銘柄の全決済金額と枚数を週単位で合計する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 週会計(dict)。
    """
    subset=[r for r in rows if r['symbol']==symbol and r['session'] in sessions]
    fields=('profit','loss','net','fees','trades','wins','losses','winning_lots','losing_lots')
    a={k:sum(r[k] for r in subset) for k in fields}
    a.update(money_loss_share=a['loss']/(a['profit']+a['loss']) if a['profit']+a['loss'] else None,
        average_net=a['net']/a['trades'] if a['trades'] else None,
        payoff=(a['profit']/a['wins'])/(a['loss']/a['losses']) if a['wins'] and a['losses'] else None,
        win_rate=a['wins']/a['trades'] if a['trades'] else None)
    return a


def weeks(rows: list[dict],sessions: list[str]) -> dict:
    """機能: カレンダー週を保存場名の日付から組み、商品別に合計する。

    引数: rows(list[dict])、sessions(list[str])。返り値: 商品別週会計(dict)。
    """
    groups={}
    for session in sessions:
        day=date.fromisoformat(session[:10]);monday=day-timedelta(days=day.weekday())
        groups.setdefault(monday,[]).append(session)
    return {s:[dict(aggregate(rows,s,scope),label=f'{monday:%m/%d}週（{len(scope)}場）') for monday,scope in sorted(groups.items())] for s in SYMBOLS}


def bars(sessions: list[str]) -> dict:
    """機能: 読取専用五分足を売買図用の五列へ接続する。

    引数: sessions(list[str])。返り値: 場銘柄別の足(dict[str,list])。
    """
    output={}
    for session in sessions:
        for symbol in SYMBOLS:
            with (ROOT/'candle_5min'/symbol/(session+'.csv')).open(encoding='utf-8-sig',newline='') as stream:
                output[session+'|'+symbol]=[[datetime.fromisoformat(r['time']).timestamp(),*[float(r[n]) for n in ('open','high','low','close')]] for r in csv.DictReader(stream)]
    return output


def indexed_prices(sync: dict,ready: dict,book: dict) -> dict:
    """機能: 遅延5秒の同時参照中値を同基準100化した図解専用系列へ変換する。

    引数: sync/ready/book(dict)。返り値: 場別の時刻と二市場指数値(dict)。
    初めて両市場が利用可能な時点を基準100とし、欠測を補間しない。選定には使わない。
    """
    output={}
    for session,value in sync.items():
        valid=value['both_available'][5]
        origins=np.flatnonzero(valid)
        if not len(origins):
            output[session]=[];continue
        initial=int(origins[0])
        prices={s:book[(session,s)]['mid'][np.maximum(value['indices'][5][s],0)] for s in SYMBOLS}
        bases={s:prices[s][initial] for s in SYMBOLS}
        output[session]=[[float(t),*[float(prices[s][i]/bases[s]*100) if valid[i] else None for s in SYMBOLS]]
            for i,t in enumerate(value['grid'])]
    return output


def attach_ledger(result: dict,ready: dict,sessions: list[str]) -> dict:
    """機能: 固定台帳の全注文へ約定時刻を添付し、商品別の週会計を追加する。

    引数: result/ready(dict)、sessions(list[str])。返り値: 表示用台帳付き結果(dict)。
    """
    path=WORK/'ledgers'/(result['config']['id']+'.pkl')
    assert digest(path)==result['ledger_SHA256']
    ledger=load(path)
    orders={'|'.join(k):[list(o)+[0,float(ready[k]['time_s'][int(o[0])])] for o in v['orders']] for k,v in ledger.items()}
    for r in result['rows']:
        assert len(orders[r['session']+'|'+r['symbol']])==2*r['trades']
    return dict(minimal(result),weeks=weeks(result['rows'],sessions),orders=orders)


def render(template: str,data: dict,filename: str) -> None:
    """機能: 一箇所の固定JSONをHTMLへ安全に埋め込む。

    引数: template/filename(str)、data(dict)。返り値: なし(None)。
    """
    text=(HERE/template).read_text(encoding='utf8');assert text.count('__DATA__')==1
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    (OUT/filename).write_text(text.replace('__DATA__',payload),encoding='utf8')


def main() -> None:
    """機能: 全結果・選定・固定遅延感度が揃ってから主報告と全一覧を生成する。

    引数: なし。返り値: なし(None)。不足結果を都合よく省略して公開しない。
    """
    fixed=load(WORK/'事前固定.json');selection=load(WORK/'前半選定.json')
    assert selection['前16だけで選択'] and selection['後13で変更なし']
    results=[load(p) for p in sorted((WORK/'results').glob('*.json'))];assert len(results)==336
    lookup={r['config']['id']:r for r in results}
    choices=selection['代表'];assert len(choices)==7
    analysis=load(WORK/'analysis/二指数情報の追加価値と遅延感度.json')
    assert analysis['代表変更なし'] and analysis['条件追加なし'] and analysis['感度取得済み遅延']==[1,15,60]
    meta=load(ROOT/'work/wave_v74/inputs/refmetadata.json')
    ready,book={},{}
    for p in meta['input_paths']['ready']:ready.update(load(ROOT/p))
    for p in meta['input_paths']['features']:book.update(load(ROOT/p))
    sync=load(WORK/'inputs/sync_fresh30.pkl')
    families=[];methods=[];checks=[]
    for choice in choices:
        ident=choice['id'];r=lookup[ident];c=r['config'];single=lookup['S'+ident[1:]]
        assert c['paired'] and not single['config']['paired']
        for field in ('family','window','level','width_fraction','hold_seconds'):
            assert c[field]==single['config'][field]
        detail=analysis['固定代表'][ident]
        sensitivity=[]
        for delay in (1,5,15,60):
            base=WORK if delay==5 else WORK/'sensitivity'/f'delay{delay}'
            j=load(base/'results'/(ident+'.json'));s=load(base/'results'/('S'+ident[1:]+'.json'))
            sensitivity.append(dict(delay=delay,joint=minimal(j),single=minimal(s)))
        families.append(dict(id=ident,family=c['family'],name=c['name'],explanation=SHORT[c['family']-1],
            eligible=choice['eligible'],followPassed=choice['後13有望条件'],periods=r['periods'],single=minimal(single),
            configText=brief(c),sensitivity=sensitivity,comparison=detail['期間別']))
        if ident in selection['主3']:
            method=dict(attach_ledger(r,ready,fixed['全29']),title=c['name'],steps=steps(c),eligible=choice['eligible'],
                followPassed=choice['後13有望条件'],single=attach_ledger(single,ready,fixed['全29']),
                sensitivity=sensitivity,comparison=detail['期間別'],finding='')
            if c['family']==1:
                exit_counts=[detail['期間別']['全29'][s]['共同出口理由'].get('時間上限返済',{}).get('取引数',0) for s in SYMBOLS]
                holds=[r['periods']['全29'][s]['hold_seconds']/r['periods']['全29'][s]['trades']/60. for s in SYMBOLS]
                method['finding']=f"返済の多くは{c['hold_seconds']/60:g}分期限（TOPIX {exit_counts[0]}/{r['periods']['全29']['TOPIX']['trades']}、日経 {exit_counts[1]}/{r['periods']['全29']['NK225']['trades']}）。平均保有{holds[0]:.1f}／{holds[1]:.1f}分。今回は方向確認後に約30分保有する方式で、広いトレールは主に損失保護の役割です。"
            methods.append(method)
            for variant in (method,method['single']):
                for symbol in SYMBOLS:
                    a=variant['periods']['全29'][symbol]
                    rows=[r for r in variant['rows'] if r['symbol']==symbol]
                    for field in ('profit','loss','net','fees','trades'):
                        assert abs(sum(r[field] for r in rows)-a[field])<1e-5
                        assert abs(sum(r[field] for r in variant['weeks'][symbol])-a[field])<1e-5
                    assert abs(a['profit']-a['loss']-a['net'])<1e-5
                    assert len(variant['orders'][fixed['全29'][0]+'|'+symbol])==2*rows[0]['trades']
                    checks.append(dict(id=variant['id'],symbol=symbol,全29=a,全場週一致=True))
    methods.sort(key=lambda m:selection['主3'].index(m['id']))
    passed=[m['id'] for m in methods if m['followPassed']]
    improved=[]
    for m in methods:
        p=m['comparison']['後13']
        if all(p[s]['平均一取引収支変化'] is not None and p[s]['平均一取引収支変化']>0
            and p[s]['金額損失割合変化'] is not None and p[s]['金額損失割合変化']<0 for s in SYMBOLS):
            improved.append(m['id'])
    conclusions=[f"前16で固定した主代表{len(methods)}方式のうち、後13で両商品とも有望条件を満たしたものは{len(passed)}方式。",
        '後13で単独対照より平均収支と金額損失割合が両方改善：'+('、'.join(improved) if improved else 'なし')+'。']
    joint_direction=next(f for f in families if f['family']==1)
    direction_periods=joint_direction['periods']
    if all(direction_periods[p][s]['net']>0 for p in ('前16','後13') for s in SYMBOLS):
        a=direction_periods['全29']
        conclusions.insert(0,f"共同方向J1は前16・後13とも両商品黒字。全29はTOPIX{a['TOPIX']['net']:+,.0f}円／日経{a['NK225']['net']:+,.0f}円で、検証継続候補です。採用確定には至りません。")
        if not joint_direction['followPassed']:
            weak=[f"{'TOPIX' if s=='TOPIX' else '日経'}の平均利益／損失{direction_periods['後13'][s]['payoff']:.3f}" for s in SYMBOLS
                if direction_periods['後13'][s]['payoff'] is not None and direction_periods['後13'][s]['payoff']<=1]
            if weak:
                conclusions[1]=f"事前の後13有望条件では、J1は{'、'.join(weak)}が基準1を下回りました。前半首位は{methods[0]['id']}のまま、後半で代表順を変更していません。"
    if not methods:conclusions=['件数・活動場数の基準を満たす機構代表がなく、主候補は選べませんでした。無取引を成功とは扱いません。']
    notes=['共同168＋自己証拠対照168＝全336条件。前16だけで7機構代表と重複を除いた主代表を選び、後13で差し替えません。既に知られている29場の再探索です。',
        '主代表の必要件数は前16で両商品20取引・8活動場以上。満たさない機構は少数の比較例として別記します。',
        '自己対照Sも同じ両市場の観測可能時点を使います。相手の価格とOFIの内容を除きますが、再準備や実際の入口時刻が変わるため完全同一機会の対照ではありません。相対価格方式のSは自価格の平均回帰です。',
        '判断は15秒刻み、両市場とも判断時刻−5秒より厳密に前の同時刻先頭観測を使用。参照期限から30秒超・reset・履歴欠損では判断しません。鮮度30秒は損益前に入力充足性だけで固定しました。',
        'CurrentPriceTimeは最終約定の代理時計です。共通受信時計がなく、厳密過去と遅延を守っても現実の受信順や真の先行を証明しません。',
        'イベント発火後は有効な中立が連続60秒必要、最短600秒間隔。欠測は中立扱いせず、保有中の発火も間隔に含みます。',
        '判断時刻以降の最初の自原本行へ写像し、10秒超の遅れや悪い気配なら棄却。さらに次有効原本行で買ask／売bid。ラージ板をミニ・マイクロの約定に代用した成績です。',
        'TOPIXミニ10枚、日経225マイクロ20枚。片道1枚41.8円／11円、新規・返済の注文合計で1円未満切捨て。利益損失とも全決済の手数料後金額です。両商品の円金額は合算しません。',
        '幅0.1／0.2／0.4%は当該場の既知始値からラージ呼値へ切上げ、最低2呼値。ATRは使いません。実建値から即時全量トレール、同幅の逆行損切り、30／60分返済判断。',
        '新規は開始5分後から安全撤収目安5分前未満。場末は15:34／05:49から返済判断、次有効気配で約定するため欠測時は遅れます。保存末尾だから架空約定する処理はありません。',
        '後13の有望条件は両商品で黒字・平均利益／平均損失>1・最大黒字場を除いて黒字。勝率だけや取引数減少だけで成功とは判定しません。',
        '1／15／60秒遅延感度は7代表と対応Sの設定を変えず再生したものです。よい遅延を選び直しません。API取得0・実注文0。']
    theory=load(WORK/'theory/二指数を同時に見る事前仮説.json')
    data=dict(title='二指数を同時に見る手法と全セッション損益',sessions=fixed['全29'],methods=methods,families=families,
        bars=bars(fixed['全29']),indexedPrices=indexed_prices(sync,ready,book),notes=notes,conclusions=conclusions,selection=selection,
        allUrl=ALL,distribution=analysis['全336の分布'],research=theory['一次資料'])
    opportunity_path=WORK/'analysis/同じ新規機会での相手確認診断.json'
    assert opportunity_path.exists(),'同機会診断の完成を待ってから最終公開する'
    data['sharedOpportunity']=load(opportunity_path)
    all_data=dict(title='全336条件の比較',sessions=fixed['全29'],methods=[minimal(r) for r in results],
        selectedIds=selection['主3'],representativeIds=[c['id'] for c in choices],mainUrl=MAIN,notes=notes[:3])
    OUT.mkdir(parents=True,exist_ok=True)
    render('main_template.html',data,MAIN);render('all_template.html',all_data,ALL)
    save(HERE/'主レポートデータ.json',data)
    save(OUT/'公開会計.json',dict(全合格=True,条件数=336,機構代表数=7,主代表数=len(methods),場数=29,口座数=58,
        選定=selection,会計=checks,公開SHA256={name:digest(OUT/name) for name in (MAIN,ALL)},
        固定SHA256=digest(WORK/'事前固定.json'),解析SHA256=digest(WORK/'analysis/二指数情報の追加価値と遅延感度.json'),API取得=0,実注文=0))
    print('二指数の主報告・全336一覧・公開会計を生成しました',flush=True)


if __name__=='__main__':
    main()
