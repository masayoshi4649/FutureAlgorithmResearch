"""固定した即時板・保有管理の結果を、対照と全場会計付きの暗色HTMLへ変換する。"""

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
OUT=ROOT/'アルゴリズム調査/00072_二市場の即時板判断と保有管理'
MAIN='二市場の即時判断と保有管理の説明と損益.html'
ALL='全996条件の比較.html'
SYMBOLS=('TOPIX','NK225')
PERIODS=('前16','後13','全29')
NAMES=('最良板の一致','距離加重板の一致','注文増減の一致','注文増減と板厚の一致',
       '短期価格進行の一致','従来J1入口と短期の保有判断')
SHORT=('両市場の最良買い・売り数量の偏りが同方向なら入る。',
       '両市場の10段板を近いほど重く数え、買い・売りの偏りが同方向なら入る。',
       '最良気配の注文増減を短い窓でまとめ、両市場の偏りが同方向なら入る。',
       '両市場で注文増減と距離加重板の偏りが同方向に揃えば入る。',
       '両市場で買い・売り両気配が同方向へ1呼値以上動けば入る。',
       '従来のJ1で入り、保有中だけ短い注文増減又は板厚との一致で判断する。')
REASONS={1:'保険の初期損切り',2:'保険のトレーリング',3:'保有時間上限',4:'場内全返済',
         6:'両市場の反対合意',7:'両市場の支持消失'}


def load(path: Path) -> object:
    """機能: 固定結果・台帳・準備入力を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。旧成果と原本は変更しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 公開物と台帳の内容指紋を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):h.update(chunk)
    return h.hexdigest()


def save(path: Path,value: object) -> None:
    """機能: 担当する報告領域だけへUTF-8 JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE) or path.resolve().is_relative_to(OUT)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def manager(c: dict) -> str:
    """機能: 途中判断の方式と確認秒数を短く説明する。

    引数: c(dict)。返り値: 管理名(str)。
    """
    label=('M0 保険だけ','M1 反対合意で撤退','M2 撤退後に反転','M3 支持が揃わなければ撤退')[c['manage_mode']]
    return label+(f"・{c['manage_confirm']}秒確認" if c['manage_mode'] else '')


def brief(c: dict) -> str:
    """機能: 入口・管理・保険幅・期限を一行へ整理する。

    引数: c(dict)。返り値: 固定設定の説明(str)。
    """
    hold=f"{c['hold_seconds']/60:g}分返済判断" if c['hold_seconds'] else '固定時間上限なし・場末返済'
    source='従来J1入口' if c['legacy_entry'] else f"{c['name']}・{c['signal_id']}・新規{c['entry_confirm']}秒確認"
    return f"{source}／{manager(c)}／保険幅{c['width_fraction']*100:g}%／{hold}"


def steps(c: dict) -> dict:
    """機能: 実装通りの入口・途中・出口を平易な三文へ整理する。

    引数: c(dict)。返り値: 三段階の説明(dict[str,str])。
    """
    if c['legacy_entry']:
        entry='両指数の中値が過去300秒で同方向へ0.03%以上進む。自分の15秒の両気配が1呼値進み、相手も逆行していなければその方向へ入る。'
    elif c['kind'] in ('Q','D'):
        label='最良数量' if c['kind']=='Q' else '近いほど重く数えた10段数量'
        entry=f"両市場で{label}の買売偏りが同方向へ{c['threshold']*100:g}%以上なら、その方向へ入る。"
    elif c['kind']=='P':
        entry=f"過去{c['window']}秒の両市場で、売買両気配が同方向へ各1呼値以上動けばその方向へ入る。"
    else:
        entry=f"過去{c['window']}秒の最良気配の注文増減について、両市場の符号比が同方向へ10%以上、各3イベント以上なら入る。"
        if c['kind']=='FD':entry+='さらに両市場の距離加重10段板も同方向へ10%以上必要。'
    if not c['legacy_entry']:
        entry+=f"新規確認{c['entry_confirm']}秒。" if c['entry_confirm'] else '新規の持続確認なし。'
    mode=c['manage_mode'];seconds=c['manage_confirm']
    if mode==0:middle='板変化だけでは返済せず、全量を保有する。'
    elif mode==1:middle=f"両市場が強い反対方向に{seconds}秒揃ったら全返済。反転はしない。"
    else:
        middle=f"両市場が強い反対方向に{seconds}秒揃ったら全返済し、約定後の新しい判断で再確認して反対へ入る。"
        if mode==3:middle+=f"両市場の支持が揃わなくなった状態（片側不足を含む）も{seconds}秒で返済。反対合意がなければ待つ。"
    hold=f"{c['hold_seconds']/60:g}分で返済判断。" if c['hold_seconds'] else '固定時間上限は設けず場末まで。'
    exit_=f"始値{c['width_fraction']*100:g}%幅の全量トレールを実建値から常時保険にする。{hold}場末も全返済判断。買ask・売bidの次有効観測で約定。"
    return dict(entry=entry,middle=middle,exit=exit_)


def minimal(r: dict) -> dict:
    """機能: 一覧と対照に必要な全明細会計を保持する。

    引数: r(dict)。返り値: 省容量結果(dict)。
    """
    fields=('session','symbol','profit','loss','net','fees','trades','wins','losses','winning_lots','losing_lots',
            'money_loss_share','drawdown','candidate_count','payoff','flip_count','reasons')
    c=r['config']
    return dict(id=c['id'],config=c,configText=brief(c),rows=[{k:a[k] for k in fields} for a in r['rows']],periods=r['periods'])


def summary(trades: np.ndarray) -> dict:
    """機能: 理由別の決済群を手数料後で集計する。

    引数: trades(ndarray[取引,11])。返り値: 共通表用の会計(dict)。
    """
    net=trades[:,10];wins=net>0;losses=net<0
    p=float(net[wins].sum());loss=float(-net[losses].sum());count=len(trades)
    return dict(profit=p,loss=loss,net=float(net.sum()),trades=count,wins=int(wins.sum()),losses=int(losses.sum()),
        fees=int(trades[:,7:9].sum()),winning_lots=int(trades[wins,4].sum()),losing_lots=int(trades[losses,4].sum()),
        payoff=(p/int(wins.sum()))/(loss/int(losses.sum())) if wins.any() and losses.any() else None,
        money_loss_share=loss/(p+loss) if p+loss else None)


def aggregate(rows: list[dict],symbol: str,sessions: list[str]) -> dict:
    """機能: 同じ商品の金額を週単位で合計する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 週会計(dict)。
    """
    subset=[r for r in rows if r['symbol']==symbol and r['session'] in sessions]
    fields=('profit','loss','net','fees','trades','wins','losses','winning_lots','losing_lots')
    a={k:sum(r[k] for r in subset) for k in fields}
    a.update(money_loss_share=a['loss']/(a['profit']+a['loss']) if a['profit']+a['loss'] else None,
        payoff=(a['profit']/a['wins'])/(a['loss']/a['losses']) if a['wins'] and a['losses'] else None)
    return a


def weeks(rows: list[dict],sessions: list[str]) -> dict:
    """機能: 保存場名の日付から週合計を作る。

    引数: rows(list[dict])、sessions(list[str])。返り値: 商品別週会計(dict)。
    """
    groups={}
    for session in sessions:
        d=date.fromisoformat(session[:10]);monday=d-timedelta(days=d.weekday())
        groups.setdefault(monday,[]).append(session)
    return {s:[dict(aggregate(rows,s,scope),label=f'{monday:%m/%d}週（{len(scope)}場）') for monday,scope in sorted(groups.items())] for s in SYMBOLS}


def bars(sessions: list[str]) -> dict:
    """機能: 読取専用五分足を図解専用五列へ変換する。

    引数: sessions(list[str])。返り値: 場銘柄別の足(dict)。売買判定には使わない。
    """
    output={}
    for session in sessions:
        for symbol in SYMBOLS:
            with (ROOT/'candle_5min'/symbol/(session+'.csv')).open(encoding='utf-8-sig',newline='') as stream:
                output[session+'|'+symbol]=[[datetime.fromisoformat(r['time']).timestamp(),*[float(r[n]) for n in ('open','high','low','close')]] for r in csv.DictReader(stream)]
    return output


def attach(r: dict,ready: dict,fixed: dict) -> dict:
    """機能: 全注文へ判断/約定時刻と決済収支を添え、理由別会計も作る。

    引数: r/ready/fixed(dict)。返り値: 台帳付き表示結果(dict)。
    """
    path=WORK/'ledgers'/(r['config']['id']+'.pkl');assert digest(path)==r['ledger_SHA256']
    archive=load(path);orders={};decisions={};nets={};exit_reasons={};flip_periods={}
    reason_by_key={};flip_by_key={}
    for key,item in archive.items():
        name='|'.join(key);times=ready[key]['time_s'];o=item['orders'];t=item['trades']
        orders[name]=[list(row)+[0,float(times[int(row[0])])] for row in o]
        decisions[name]=[float(times[int(row[1])]) for row in o]
        net={int(row[0]):float(row[10]) for row in t}
        nets[name]=[None if row[7] else net[int(row[2])] for row in o]
        reason_by_key[key]={int(row[2]):int(row[6]) for row in o if row[7]==0}
        flip_by_key[key]={int(row[2]) for row in o if row[7]==1 and row[6]==12}
        assert len(o)==2*len(t)
    for period in PERIODS:
        exit_reasons[period]={};flip_periods[period]={}
        for s in SYMBOLS:
            entries=[];reason_codes=[];is_flip=[]
            for key,item in archive.items():
                if key[1]!=s or key[0] not in fixed[period]:continue
                for row in item['trades']:
                    entries.append(row);reason_codes.append(reason_by_key[key][int(row[0])]);is_flip.append(int(row[0]) in flip_by_key[key])
            all_=np.array(entries,dtype=np.float64).reshape((-1,11));reason_codes=np.array(reason_codes)
            exit_reasons[period][s]={str(reason):summary(all_[reason_codes==reason]) for reason in REASONS}
            flip_periods[period][s]=summary(all_[np.array(is_flip,dtype=bool)])
            checked=summary(all_);expected=r['periods'][period][s]
            for field in ('profit','loss','net','fees','trades'):
                assert abs(checked[field]-expected[field])<1e-5
                assert abs(sum(a[field] for a in exit_reasons[period][s].values())-expected[field])<1e-5
    return dict(minimal(r),weeks=weeks(r['rows'],fixed['全29']),orders=orders,decisionTimes=decisions,orderNet=nets,
        exitReasons=exit_reasons,flipPeriods=flip_periods)


def render(template: str,data: dict,filename: str) -> None:
    """機能: 一箇所の固定JSONを暗色HTMLへ安全に埋め込む。

    引数: template/filename(str)、data(dict)。返り値: なし(None)。
    """
    text=(HERE/template).read_text(encoding='utf8');assert text.count('__DATA__')==1
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    (OUT/filename).write_text(text.replace('__DATA__',payload),encoding='utf8')


def main() -> None:
    """機能: 全結果と分析・固定感度が完成してから主報告と全一覧を生成する。

    引数: なし。返り値: なし(None)。少ない結果だけで都合よく公開しない。
    """
    fixed=load(WORK/'事前固定.json');selection=load(WORK/'前半選定.json')
    assert selection['前16だけで選択'] and selection['後13で変更なし']
    results=[load(p) for p in sorted((WORK/'results').glob('*.json'))];assert len(results)==996
    lookup={r['config']['id']:r for r in results};choices=selection['代表'];assert len(choices)==6
    analysis_path=WORK/'analysis/板支持による途中判断の効果と限界.json';analysis=load(analysis_path)
    assert analysis['代表変更なし'] and analysis['条件追加なし']
    assert load(WORK/'旧J1の完全一致.json')['合格']
    spec=load(WORK/'inputs/入力と即時板特徴の仕様.json');ready={}
    for name in spec['input_paths']['ready']:ready.update(load(ROOT/name))
    attached={}
    def get(ident: str) -> dict:
        """機能: 台帳添付結果を同じIDで再利用する。

        引数: ident(str)。返り値: 台帳付き表示結果(dict)。
        """
        if ident not in attached:attached[ident]=attach(lookup[ident],ready,fixed)
        return attached[ident]
    sensitivity={}
    for ident in selection['感度対象']:
        values=[]
        for delay in (1,5,15):
            base=WORK if delay==5 else WORK/'sensitivity'/f'delay{delay}'
            r=load(base/'results'/(ident+'.json'));assert r['config']['delay']==delay
            for field in ('signal_id','legacy_entry','entry_confirm','manage_mode','manage_confirm','width_fraction','hold_seconds'):
                assert r['config'][field]==lookup[ident]['config'][field]
            values.append(dict(delay=delay,periods=r['periods']))
        sensitivity[ident]=values
    benchmark=dict(get(selection['基準']),name='従来J1基準',sensitivity=sensitivity[selection['基準']])
    families=[];methods=[]
    for choice in choices:
        ident=choice['id'];r=lookup[ident];c=r['config'];d=analysis['固定代表'][ident]
        families.append(dict(id=ident,family=c['family'],name=c['name'],explanation=SHORT[c['family']-1],
            eligible=choice['eligible'],followPassed=choice['後13有望条件'],periods=r['periods'],sensitivity=sensitivity[ident]))
        if ident in selection['主3']:
            method=dict(get(ident),title=c['name'],steps=steps(c),eligible=choice['eligible'],followPassed=choice['後13有望条件'],
                controls=[get(other) for other in choice['controls']],sensitivity=sensitivity[ident],finding='',analysis=d)
            if c['manage_mode']:
                middle=sum(r['reasons'].get('6',0)+r['reasons'].get('7',0) for r in r['rows'])
                method['finding']=f"板判断による返済は{middle}回。通常の新規と反転新規の損益は、理由別の表で全損失込みに分けています。"
            if c['family']==1:
                a=r['periods']['前16']['NK225'];b=r['periods']['全29']['NK225']
                delayed=[x for x in sensitivity[ident] if x['delay']!=5]
                method['finding']+=f" 前16の日経収支は{a['net']:+,.0f}円、全29の日経最大時価下落は{b['drawdown']:,.0f}円。情報遅延1/15秒の全29日経収支は{delayed[0]['periods']['全29']['NK225']['net']:+,.0f}円／{delayed[1]['periods']['全29']['NK225']['net']:+,.0f}円です。"
                exits=method['exitReasons']['全29']
                method['finding']+=f" 板反対合意の返済はTOPIX{exits['TOPIX']['6']['trades']}/{r['periods']['全29']['TOPIX']['trades']}回、日経{exits['NK225']['6']['trades']}/{r['periods']['全29']['NK225']['trades']}回。日経は保険返済{exits['NK225']['1']['trades']+exits['NK225']['2']['trades']}回が主で、保険を最後の補助だけにした方式とはまだ言えません。"
            if c['legacy_entry']:
                delta=r['periods']['後13']['TOPIX']['net']-benchmark['periods']['後13']['TOPIX']['net']
                method['finding']+=f" 後13のTOPIXは旧基準より{delta:+,.0f}円で、全29の改善が期間全体で一貫したわけではありません。"
                counts=[method['exitReasons']['全29'][s]['6']['trades'] for s in SYMBOLS]
                method['finding']+=f" 板反対合意で変わった返済はTOPIX{counts[0]}件／日経{counts[1]}件だけで、追加価値の根拠は少数です。"
            methods.append(method)
    methods.sort(key=lambda m:selection['主3'].index(m['id']))
    short=next((m for m in methods if not m['config']['legacy_entry']),None)
    if short is None:short=get(next(c['id'] for c in choices if c['family']!=6))
    short_choice=next(c for c in choices if c['id']==short['id'])
    pure=next(get(i) for i in short_choice['controls'] if lookup[i]['config']['manage_mode']==0)
    full=next(get(i) for i in short_choice['controls'] if lookup[i]['config']['manage_mode']==3 and lookup[i]['config']['manage_confirm']==(short['config']['manage_confirm'] or 15))
    legacy=get(next(c['id'] for c in choices if c['family']==6))
    comparisons=[dict(minimal(lookup[benchmark['id']]),label='従来J1・保険のみ'),dict(minimal(lookup[pure['id']]),label='入口だけ短期・同設定M0'),
        dict(minimal(lookup[legacy['id']]),label='従来入口・途中の短期判断'),dict(minimal(lookup[full['id']]),label='入口も途中も短期・同設定M3対照')]
    checks=[]
    for value in attached.values():
        for s in SYMBOLS:
            a=value['periods']['全29'][s]
            for field in ('profit','loss','net','fees','trades'):
                assert abs(sum(r[field] for r in value['rows'] if r['symbol']==s)-a[field])<1e-5
                assert abs(sum(r[field] for r in value['weeks'][s])-a[field])<1e-5
            assert abs(a['profit']-a['loss']-a['net'])<1e-5
            checks.append(dict(id=value['id'],symbol=s,全29=a,全場週理由一致=True))
    q=next(f for f in families if f['family']==1);b=next(f for f in families if f['family']==6)
    qa=q['periods']['全29'];ba=b['periods']['全29'];base=benchmark['periods']['全29']
    bdelta=[ba[s]['net']-base[s]['net'] for s in SYMBOLS]
    later=b['periods']['後13']['TOPIX']['net']-benchmark['periods']['後13']['TOPIX']['net']
    conclusions=[f"従来J1入口に反対板合意の撤退を加える方式は、全29でTOPIX{ba['TOPIX']['net']:+,.0f}円／日経{ba['NK225']['net']:+,.0f}円。旧基準比{bdelta[0]:+,.0f}円／{bdelta[1]:+,.0f}円ですが、後13のTOPIXでは{later:+,.0f}円悪化。両商品とも変更は2件だけで、根拠は少数です。",
        f"最良板だけで入り反対合意からドテンするQ25は、主5秒遅延で{qa['TOPIX']['net']:+,.0f}円／{qa['NK225']['net']:+,.0f}円。ただし情報遅延1／15秒では日経が赤字となり、安定採用は未確定です。",
        'Q25の日経は139返済中79回が保険、板反対合意は42回。板判断を主役にしてトレールを最後の保険へ回す狙いは、十分には達成していません。',
        '片側の弱まりを含め支持が揃わなくなっただけで撤退するM3は、利益の継続も切って悪化しました。機械的に実行できることと、利益の安定性は別です。']
    notes=['短期入口896＋従来J1入口100＝996固定条件。六機構代表と重複を除いた主代表は前16だけで選び、後13で差し替えません。29場は旧調査で既知です。',
        '上部の四比較は前半主代表の短期入口設定からM0とM3を取り出し、第6機構の従来入口代表と比べます。後半や全29の首位を選び直した表ではありません。',
        '同じ入口候補でも返済が変わると次新規の可否が変わります。管理対照は売買経路全体の比較であり、取引数削減と一取引平均改善は分けて読みます。',
        '即時判断は5秒格子、主の情報遅延5秒、鮮度30秒。参照は判断−遅延より厳密に過去の同時計先頭だけです。共通受信時計がなく、実際の受信順やリアルタイム性を証明しません。',
        '窓は予定5/15/30/60秒。最終約定代理時計の離散性により実時計差が伸縮します。主5秒窓の実差は中央値6秒・最大34秒。同一始終行や区間resetは無効です。',
        'OFIは約定だけでなく指値追加・取消も含む最良気配の注文増減。窓の符号比はsum/abs-sum、非ゼロ3イベント以上必要。ゼロ分母や少数イベントから強方向を判定しません。',
        '距離重みは各側最良から呼値距離dに1/(1+d)。micropriceは最良数量偏りと代数同値なので独立票として使いません。',
        '新規0/10秒、途中15/30秒の連続有効格子で確認。0秒以外は開始後に両市場の参照行が更新する必要があります。欠測は中立/反対扱いにせず確認を破棄します。',
        'M3の支持消失は、両市場の弱支持が揃わなくなることです。片側不足・中立・不一致も含み、両側の支持が同時に消える必要はありません。',
        'M2/M3反転は元玉の実返済後の新しい共通格子で反対合意を再確認し、さらに次有効気配で新規。確認消失又は30秒期限で取消。反転は別々の返済/新規料金です。',
        '判断後の最初の自原本行へ写像し、10秒超遅れや新規/途中の不正気配を拒否。買ask／売bidの次有効原本行で約定。ラージ板をミニ/マイクロ約定へ代用します。',
        'TOPIXミニ10枚×1000円/pt・片道1枚41.8円、日経225マイクロ20枚×10円/pt・片道11円。新規と返済の各注文合計を1円未満切捨て。両商品円は合算しません。',
        '保険トレールは既知の場始値0.2/0.4%を呼値へ切上げ最低2呼値、実建値から即時に全量へ設定。ATR不使用。30分上限又は固定時間上限なし・場末全返済を比較します。',
        '新規は開始5分後から安全撤収目安5分前未満。15:34／05:49から場末返済判断、次有効気配で約定するため欠測時は遅れます。保存末尾の架空清算はしません。',
        '後13有望条件は両商品黒字・平均利益/平均損失>1・最大黒字場を除き黒字。主代表の必要件数は前16両商品20取引・8活動場以上。無取引を成功と扱いません。',
        '遅延1/15秒は同じ代表・管理対照を固定した感度再生です。最良の遅延で再選定しません。共通29場58口座、追加TOPIX10/09ナイトは相手未保存のため比較外。API0・実注文0。']
    theory=load(WORK/'theory/板の支持で保有を更新する事前仮説.json')
    data=dict(title='二市場の即時判断と保有管理の説明と損益',sessions=fixed['全29'],methods=methods,families=families,
        benchmark=benchmark,comparisons=comparisons,bars=bars(fixed['全29']),notes=notes,conclusions=conclusions,
        selection=selection,allUrl=ALL,research=theory['一次研究'],distribution=analysis['全996の分布'])
    all_data=dict(title='全996条件の比較',sessions=fixed['全29'],methods=[minimal(r) for r in results],
        selectedIds=selection['主3'],representativeIds=[c['id'] for c in choices],mainUrl=MAIN,notes=notes[:4])
    OUT.mkdir(parents=True,exist_ok=True)
    render('main_template.html',data,MAIN);render('all_template.html',all_data,ALL)
    save(HERE/'主レポートデータ.json',data)
    save(OUT/'公開会計.json',dict(全合格=True,条件数=996,機構代表数=6,主代表数=len(methods),場数=29,口座数=58,
        選定=selection,会計=checks,公開SHA256={n:digest(OUT/n) for n in (MAIN,ALL)},
        固定SHA256=digest(WORK/'事前固定.json'),解析SHA256=digest(analysis_path),API取得=0,実注文=0))
    print('二市場の即時判断・全996一覧・公開会計を生成しました',flush=True)


if __name__=='__main__':
    main()
