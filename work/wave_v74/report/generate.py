"""始値・前保存場の方向制限と連敗休止の凍結結果だけを、簡潔な暗色レポートへ接続する。"""

import csv
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import pickle


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
OUT = ROOT/'アルゴリズム調査/00070_始値と前終値の方向制限と連敗休止'
MAIN = '基準価格と連敗休止の説明と全セッション損益.html'
ALL = '全480条件の比較とセッション損益.html'
EXT_MAIN = '新規方向だけを制限する方式の損益.html'
EXT_ALL = '追加240条件の比較とセッション損益.html'
SYMBOLS = ('TOPIX','NK225')
PAUSES = ('休止なし','2連敗で10分','2連敗で30分','2連敗で収束待ち','2連敗で10分かつ収束','3連敗で30分')
REFS = ('始値基準','前保存場基準','両基準の方向一致','過去60秒基準')
BASE = 'A0_E0_B0_W10_P0'


def read(path: Path) -> object:
    """機能: 今回の固定資料と台帳を読み取る。

    引数: path(Path)。返り値: 保存資料(object)。旧成果と原本は変更しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def write(path: Path, value: dict) -> None:
    """機能: 担当する報告領域だけへ日本語JSONを保存する。

    引数: path(Path)、value(dict)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE) or path.resolve().is_relative_to(OUT)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def sha(path: Path) -> str:
    """機能: 公開物と入力結果の内容指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def explain(c: dict) -> dict:
    """機能: 固定された入口・途中判断・出口を三つの短い日本語へ整理する。

    引数: c(dict)。返り値: 三段階の説明(dict[str,str])。
    """
    if c['reference'] == 2:
        entry='現在値が始値と前保存場の最終観測より両方高ければ買い、両方低ければ売り。方向が一致しなければ待つ。'
    else:
        ref=('当該場の始値','前保存場の最終観測','両基準','60秒前の価格')[c['reference']]
        entry=f'現在値が{ref}より高ければ買いだけ、低ければ売りだけを許可する。'
    if c['inverse']:
        entry='対照として、基準価格から見た許可方向を反転する。'
    entry+=('方向を確認して次の有効気配で全量を建てる。' if c['entry_type']==0
            else '許可方向への反発・反落を始値0.025%幅の新規トレールで待ち、成立後の次有効気配で全量を建てる。')
    if c['band']:
        entry+='基準の±0.025%内は新規を見送る。'
    middle=PAUSES[c['pause_mode']]+'。'+('許可方向が反対に変われば全返済を判断する。' if c['exit_on_reverse'] else '基準を跨いでも方向だけでは返済しない。')
    if c['pause_mode'] in (3,4):
        middle+='収束は、逆向き中値極値が30秒更新されず0.025%反発し、30秒前より両気配も1呼値進んだ場合。'
    exit_text=f"実建値から始値{c['width_fraction']*100:g}%幅で全量を追跡。逆行も同じ幅で損切り。60分で返済判断。場末は15:34／05:49から全返済を判断し、次の有効気配で約定。"
    return dict(entry=entry,middle=middle,exit=exit_text)


def brief(c: dict) -> str:
    """機能: 全一覧で条件を一行に説明する。

    引数: c(dict)。返り値: 設定の要約(str)。
    """
    return f"{REFS[c['reference']]}／{'次気配新規' if c['entry_type']==0 else '反発追跡新規'}／帯{c['band']*100:g}%／出口幅{c['width_fraction']*100:g}%／{PAUSES[c['pause_mode']]}"


def aggregate(rows: list[dict], symbol: str, sessions: list[str]) -> dict:
    """機能: 週会計を同銘柄の全明細から合算する。

    引数: rows(list[dict])、symbol(str)、sessions(list[str])。返り値: 集計(dict)。
    """
    subset=sorted((r for r in rows if r['symbol']==symbol and r['session'] in sessions),key=lambda r:r['session'])
    fields=('profit','loss','net','gross','fees','wins','losses','flats','trades','winning_lots','losing_lots','flat_lots',
            'pause_count','resume_count','paused_seconds','resumed_trades','resumed_net','hold_seconds','spread_drag')
    a={field:sum(r[field] for r in subset) for field in fields}
    a.update(money_loss_share=a['loss']/(a['profit']+a['loss']) if a['profit']+a['loss'] else None,
        profit_loss_ratio=a['profit']/a['loss'] if a['loss'] else None,
        payoff=(a['profit']/a['wins'])/(a['loss']/a['losses']) if a['wins'] and a['losses'] else None,
        win_rate=a['wins']/a['trades'] if a['trades'] else None,
        max_long=max((r['max_long'] for r in subset),default=0),max_short=max((r['max_short'] for r in subset),default=0),
        active_sessions=sum(r['trades']>0 for r in subset),positive_sessions=sum(r['net']>0 for r in subset),
        without_best_session=a['net']-max((r['net'] for r in subset),default=0))
    total=peak=dd=0.
    for r in subset:
        dd=max(dd,r['drawdown'],peak-total-r['equity_min'])
        peak=max(peak,total+r['equity_max'])
        total+=r['net']
    a['drawdown']=dd
    return a


def weekly(rows: list[dict], sessions: list[str]) -> dict:
    """機能: カレンダー週に分けて同銘柄の週損益を集計する。

    引数: rows(list[dict])、sessions(list[str])。返り値: 銘柄別の週集計(dict)。
    """
    groups={}
    for session in sessions:
        day=date.fromisoformat(session[:10])
        monday=day-timedelta(days=day.weekday())
        groups.setdefault(monday,[]).append(session)
    return {symbol:[dict(aggregate(rows,symbol,scope),label=f'{monday:%m/%d}週（{len(scope)}場）')
                    for monday,scope in sorted(groups.items())] for symbol in SYMBOLS}


def bars(sessions: list[str]) -> dict:
    """機能: 読取専用の五分足を図解用の五列へ接続する。

    引数: sessions(list[str])。返り値: 場・銘柄ごとの足(dict)。
    """
    output={}
    for session in sessions:
        for symbol in SYMBOLS:
            with (ROOT/'candle_5min'/symbol/(session+'.csv')).open(encoding='utf-8-sig',newline='') as stream:
                output[session+'|'+symbol]=[[datetime.fromisoformat(r['time']).timestamp(),
                                           *[float(r[n]) for n in ('open','high','low','close')]] for r in csv.DictReader(stream)]
    return output


def minimal(result: dict) -> dict:
    """機能: 一覧で必要な全明細金額と説明を省容量で保持する。

    引数: result(dict)。返り値: 一覧用の条件(dict)。
    """
    fields=('session','symbol','profit','loss','net','fees','trades','wins','losses','winning_lots','losing_lots',
            'pause_count','resume_count','paused_seconds','resumed_net','money_loss_share','drawdown')
    c=result['config']
    return dict(id=c['id'],config=c,configText=brief(c),rows=[{k:r[k] for k in fields} for r in result['rows']],periods=result['periods'])


def fill(template: str, data: dict, name: str) -> None:
    """機能: 固定JSONを一箇所のHTMLへ安全に埋め込む。

    引数: template/name(str)、data(dict)。返り値: なし(None)。
    """
    text=(HERE/template).read_text(encoding='utf8')
    assert text.count('__DATA__')==1
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    (OUT/name).write_text(text.replace('__DATA__',payload),encoding='utf8')


def build_methods(choices: list[dict], lookup: dict, ready: dict, sessions: list[str], supplemental: bool) -> list[dict]:
    """機能: 固定選定の三代表へ台帳・休止・同設定対照を接続する。

    引数: choices(list[dict])、lookup/ready(dict)、sessions(list[str])、supplemental(bool)。
    返り値: 表示用の三代表(list[dict])。選定と売買条件を変更しない。
    """
    assert len(choices)==3 and {c['reference'] for c in choices}=={0,1,2}
    methods=[]
    for choice in choices:
        result=lookup[choice['id']]
        c=result['config']
        assert len(result['rows'])==58
        ledger_path=WORK/'ledgers'/(c['id']+'.pkl')
        if supplemental and c['pause_mode']:
            ledger_path=WORK/'extension/ledgers'/(c['id']+'.pkl')
        assert sha(ledger_path)==result['ledger_SHA256']
        ledger=read(ledger_path)
        orders,pauses={},{}
        for key,l in ledger.items():
            times=ready[key]['time_s']
            orders['|'.join(key)]=[list(o)+[0,float(times[int(o[0])])] for o in l['orders']]
            events=l['pauses']
            ranges=[]
            for j,event in enumerate(events):
                if event[1]!=0:
                    continue
                start=float(times[int(event[0])])
                raw_end=next((float(times[int(v[0])]) for v in events[j+1:] if v[1]==1),float(ready[key]['limit']-60.))
                end=max(start,min(raw_end,float(ready[key]['limit']-60.)))
                ranges.append([start,end,*[int(v) for v in event[2:]]])
            account=next(r for r in result['rows'] if r['session']==key[0] and r['symbol']==key[1])
            assert abs(sum(p[1]-p[0] for p in ranges)-account['paused_seconds'])<1e-5,('休止秒の不一致',c['id'],key)
            pauses['|'.join(key)]=ranges
        stem=c['id'].rsplit('_P',1)[0]
        pause_compare=[minimal(lookup[stem+'_P'+str(p)]) for p in range(6)]
        suffix=c['id'].split('_',1)[1].rsplit('_P',1)[0]+'_P0'
        prefixes=('A','X') if supplemental else ('X','K')
        controls=[minimal(lookup[prefix+str(c['reference'])+'_'+suffix]) for prefix in prefixes]
        controls.append(minimal(lookup['M3_'+suffix]))
        methods.append(dict(result,id=c['id'],title=REFS[c['reference']]+'の比較代表',steps=explain(c),configText=brief(c),
            eligible=choice['eligible'],followPassed=choice['後13有望条件'],baseline=minimal(lookup[BASE]),
            pauseComparison=pause_compare,controls=controls,weeks=weekly(result['rows'],sessions),orders=orders,pauses=pauses))
    return methods


def verify_methods(methods: list[dict]) -> list[dict]:
    """機能: 公開代表の全場・週合計と全期間金額が一致するか検査する。

    引数: methods(list[dict])。返り値: 六口座分の会計検査記録(list[dict])。
    """
    checks=[]
    for m in methods:
        for symbol in SYMBOLS:
            total=m['periods']['全29'][symbol]
            rows=[r for r in m['rows'] if r['symbol']==symbol]
            for field in ('profit','loss','net','fees','trades'):
                assert abs(sum(r[field] for r in rows)-total[field])<1e-5
                assert abs(sum(w[field] for w in m['weeks'][symbol])-total[field])<1e-5
            assert abs(total['profit']-total['loss']-total['net'])<1e-5
            checks.append(dict(id=m['id'],symbol=symbol,全29=total,全場週一致=True))
    return checks


def main() -> None:
    """機能: 第一段階480と事後追加240の固定結果を四つの報告へ接続する。

    引数: なし。返り値: なし(None)。結果が不足していれば公開しない。
    """
    fixed=read(WORK/'事前固定.json')
    selection=read(WORK/'前半選定.json')
    results=[read(p) for p in sorted((WORK/'results').glob('*.json'))]
    assert len(results)==480 and selection['前16だけで選択'] and selection['後13で変更なし']
    lookup={r['config']['id']:r for r in results}
    meta=read(WORK/'inputs/refmetadata.json')
    ready={}
    for name in meta['input_paths']['ready']:
        ready.update(read(ROOT/name))
    choices=selection['代表']
    methods=build_methods(choices,lookup,ready,fixed['全29'],False)
    passed=[m['id'] for m in methods if m['followPassed']]
    both_positive=sum(all(r['periods']['全29'][s]['net']>0 for s in SYMBOLS) for r in results)
    theory=read(WORK/'theory/基準価格と連敗休止の事前仮説.json')
    research=[dict(title=r['研究'],url=r['一次資料']) for r in theory['市場心理の根拠']]
    conclusion=('後13で両銘柄の有望条件を満たした代表：'+ '、'.join(passed)+'。' if passed
                else '前16から選んだ3代表は、後13で両銘柄の有望条件を満たしませんでした。')
    notes=['前16だけで基準別代表を選び、後13では変更しません。全480は主案288＋対照192。既知データの再探索です。',
           '損失割合＝損失÷（利益＋損失）。50%未満なら黒字です。利益／損失は全決済の料金後金額合計です。',
           '1回の新規は全量TOPIXミニ10枚／日経225マイクロ20枚。ラージ板の買ask・売bid、条件成立後の次有効原本観測で仮想約定。',
           '片道1枚TOPIX41.8円／日経11円。新規・返済の注文合計を切捨て、収支に控除済み。両商品の円金額は合算しません。',
           '開始5分後から新規。安全撤収目安15:35／05:50の5分前から新規停止、15:34／05:49から全返済判断。次有効気配で約定し、欠損時は遅れるため目安時刻の約定保証ではありません。通常は返済後30秒待機、保有60分で返済判断。',
           '価格幅は観測始値に対する率をラージ呼値へ切り上げます。トレール幅は最低2呼値、新規反発幅は最低1呼値。ATRは使いません。',
           '前保存場最終観測は公式終値ではありません。初場の前値欠測は補完せず、前場基準・両基準では新規しません。',
           '参照価格のfeed始値24口座／観測始値34口座。古いOpeningPriceTimeは拒否します。日次PreviousCloseは前保存場参照とは別です。',
           '逆向き・基準跨ぎ返済なし・過去60秒は診断対照。60秒方式は別入口であり同一入口の解除対照ではありません。',
           '後13有望条件：両銘柄とも手数料後黒字・平均勝ち／平均負け＞1・最大黒字場を除いて黒字。将来収益の保証ではありません。',
           '板時計はCurrentPriceTimeの代理時計。ミニ／マイクロ実板の深さ、数量悪化、通信遅延は再現していません。第一段階の返済判断から次気配約定までの最大遅れは227秒でしたが、全口座で保存監視終端までに場内クローズしています。API取得・実注文0。']
    data=dict(title='基準価格と連敗休止の説明と全セッション損益',sessions=fixed['全29'],periodNames=['前16','後13','全29'],
              methods=methods,bars=bars(fixed['全29']),references=meta['references'],notes=notes,conclusion=conclusion,
              allUrl=ALL,selection=selection,baselineId=BASE,research=research,
              summary=dict(bothPositiveCount=both_positive,widths=sorted({m['config']['width_fraction']*100 for m in methods})))
    all_data=dict(title='全480条件の比較とセッション損益',sessions=fixed['全29'],methods=[minimal(r) for r in results],
                  selectedIds=[c['id'] for c in choices],mainUrl=MAIN,notes=notes[:2])

    # ----------------------------------------
    # 基準跨ぎ返済を外した事後追加を、第一段階の選定・結果と分ける。
    ext_selection=read(WORK/'extension/選定.json')
    ext_fixed=read(WORK/'extension/追記固定.json')
    ext_results=[read(p) for p in sorted((WORK/'extension/results').glob('*.json'))]
    assert len(ext_results)==240 and ext_selection['全条件数']==288 and ext_selection['追加実行数']==240
    assert ext_selection['前16だけで選択'] and ext_selection['後13で変更なし'] and ext_selection['第一段階からの事後追加']
    assert ext_fixed['全29']==fixed['全29']
    ext_lookup={r['config']['id']:r for r in ext_results}
    assert not set(ext_lookup).intersection(lookup)
    combined=dict(lookup,**ext_lookup)
    ext_choices=ext_selection['代表']
    ext_methods=build_methods(ext_choices,combined,ready,fixed['全29'],True)
    ext_both_positive=sum(all(r['periods']['全29'][s]['net']>0 for s in SYMBOLS) for r in ext_results)
    ext_passed=[m['id'] for m in ext_methods if m['followPassed']]
    ext_conclusion=('後13で両銘柄の有望条件を満たした追加代表：'+'、'.join(ext_passed)+'。' if ext_passed
                    else '新規方向だけを制限する追加240条件も、全29でTOPIX・日経とも黒字0。前16で選んだ3代表は後13の有望条件も未達でした。基準跨ぎ返済を外せば解決する、とは言えません。')
    comparison=ext_methods[0]
    before=comparison['pauseComparison'][0]['periods']['全29']
    after=comparison['periods']['全29']
    averages='／'.join(f"{'TOPIX' if s=='TOPIX' else '日経'} {before[s]['trades']}→{after[s]['trades']}取引、平均{before[s]['net']/before[s]['trades']:,.0f}→{after[s]['net']/after[s]['trades']:,.0f}円" for s in SYMBOLS)
    pause_effect=f"{comparison['id']}の休止なし→選定休止は、{averages}。取引数は減りましたが平均収支は両方悪化し、損失合計の減少だけを改善とは扱えません。"
    stage_text='第一段階480条件＋第二段階240条件。第二段階は、新規方向制限に加えた基準跨ぎ返済の解釈を分ける事後追加です。同じ既知29場を使っており、未知データ検証ではありません。'
    data['stageText']=stage_text
    data['extensionSummary']=dict(methods=[minimal(m) for m in ext_methods],conclusion=ext_conclusion+' '+pause_effect,url=EXT_MAIN,allUrl=EXT_ALL)
    ext_notes=[
        '第二段階は基準跨ぎ返済なしの240条件を事後追加。既存の同方式・休止なし48条件と合わせ288条件の前16だけで基準別代表を選び、後13では変更しません。未知データの検証ではありません。',
        *notes[1:8],
        '同設定の診断対照は、基準跨ぎ返済あり・逆向き・過去60秒の各休止なし。60秒方式は別入口であり同一入口の解除対照ではありません。',
        *notes[9:],
        pause_effect]
    ext_data=dict(title='新規方向だけを制限する方式の損益',sessions=fixed['全29'],periodNames=data['periodNames'],
        methods=ext_methods,bars=data['bars'],references=data['references'],notes=ext_notes,conclusion=ext_conclusion,
        allUrl=EXT_ALL,allLinkText='追加240条件の一覧と全セッション',selection=ext_selection,baselineId=BASE,research=research,
        stageText=stage_text+' 新規後は基準を跨いでも方向だけでは返済せず、トレール・60分・場内返済まで保有します。',
        summary=dict(bothPositiveCount=ext_both_positive,conditionLabel='追加240',widths=sorted({m['config']['width_fraction']*100 for m in ext_methods})))
    ext_all_data=dict(title='追加240条件の比較とセッション損益',sessions=fixed['全29'],methods=[minimal(r) for r in ext_results],
        selectedIds=[c['id'] for c in ext_choices],mainUrl=EXT_MAIN,notes=ext_notes[:2],
        scopeText='第二段階の追加240条件です。既存の休止なし48条件と合わせ288条件の前16で代表を選び、後13では変更していません。第一段階を見て出口解釈を分けた事後追加で、未知データ検証ではありません。')
    OUT.mkdir(parents=True,exist_ok=True)
    fill('main_template.html',data,MAIN)
    fill('all_template.html',all_data,ALL)
    fill('main_template.html',ext_data,EXT_MAIN)
    fill('all_template.html',ext_all_data,EXT_ALL)
    write(HERE/'主レポートデータ.json',data)
    write(HERE/'追加レポートデータ.json',ext_data)
    checks=verify_methods(methods)
    ext_checks=verify_methods(ext_methods)
    write(OUT/'公開会計.json',dict(全合格=True,条件数=720,第一段階条件数=480,追加条件数=240,追加選定母数=288,
        主代表数=3,追加代表数=3,場数=29,口座数=58,選定=selection,追加選定=ext_selection,
        会計=checks,追加会計=ext_checks,公開SHA256={name:sha(OUT/name) for name in (MAIN,ALL,EXT_MAIN,EXT_ALL)},
        参照固定SHA256=sha(WORK/'inputs/refmetadata.json'),API取得=0,実注文=0))
    print('第一段階と追加の各3章・全480と追加240一覧・公開会計JSONを生成しました。',flush=True)


if __name__=='__main__':
    main()
