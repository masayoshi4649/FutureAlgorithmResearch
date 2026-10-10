"""保存全返済から数表を別集計し、HTMLの全可視数値と固定対象を検算する。"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import gzip
import hashlib
from html.parser import HTMLParser
import json
import math
import pickle
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote, urlsplit


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00035_同じ価格帯の防御変化と突破'
MAIN = OUT/'同じ価格帯の防御変化と突破.html'
ALL = OUT/'全条件損益.html'
IDS = ('B00','B01','B02','B03','B05','B06','B07','B08','B09','B10','B11','B12')
SYMBOLS = ('TOPIX','NK225')
FIELDS = ('profit_yen','loss_yen','net_yen','profit_units','loss_units','net_units','zero_units')
COMPARISON_FIELDS = ('profit_yen','loss_yen','net_yen','profit_factor','average_payoff','net_r','drawdown_yen','trades','active_sessions')
RESPONSE_FIELDS = ('件数','正方向数','逆方向数','同値数','平均ATR反応')
FLOW_FIELDS = ('bands','two_trials','completed_breakout','breakout_comparable','candidates','trades','early_breakout','quality_interruption')


def read(path: Path) -> object:
    """機能: 既存JSONを読み、非有限の定数を拒否する。

    引数: path(Path)。返り値: 内容(object)。
    """
    data = path.read_bytes()
    def reject(value: str) -> None:
        """機能: JSONの非有限表現を拒否する。

        引数: value(str)。返り値: なし(None)、例外。
        """
        raise ValueError(value)
    return json.loads(gzip.decompress(data) if path.suffix=='.gz' else data, parse_constant=reject)


def digest(path: Path) -> str:
    """機能: 表示元と出力の内容を指紋へ結ぶ。

    引数: path(Path)。返り値: SHA256(str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(8*1024*1024),b''):
            value.update(data)
    return value.hexdigest()


def close(actual: object, expected: object, label: object) -> None:
    """機能: 未定義と有限値を区別して数値を比較する。

    引数: actual/expected/label(object)。返り値: なし(None)、相違は例外。
    """
    if expected is None:
        assert actual is None, (label,actual,expected)
    else:
        assert actual is not None and math.isfinite(float(actual)), (label,actual)
        assert math.isclose(float(actual),float(expected),rel_tol=1e-11,abs_tol=1e-6), (label,actual,expected)


def ratios(profit: float, loss: float, wins: int, losses: int) -> tuple:
    """機能: 1枚平均と総額の比率を異なる定義として計算する。

    引数: profit/loss(float)、wins/losses(int)。返り値: PF・平均比(tuple)。
    """
    pf = profit/loss if loss>0 else None
    payoff = (profit/wins)/(loss/losses) if wins>0 and losses>0 and loss>0 else None
    return pf,payoff


def from_trades(ledger: dict, factor: float) -> dict:
    """機能: 全1枚返済の符号・初期リスクから損益を独立集計する。

    引数: ledger(dict)、factor(float)。返り値: 表示元の期待統計(dict)。
    """
    records = ledger['trades']
    for trade in records:
        assert len(trade)==10 and trade[2] in (-1,1) and math.isfinite(trade[5]) and trade[5]>0
    pnl = [trade[6] for trade in records]
    wins,losses = sum(p>0 for p in pnl),sum(p<0 for p in pnl)
    profit = math.fsum(p for p in pnl if p>0)*factor
    loss = -math.fsum(p for p in pnl if p<0)*factor
    pf,payoff = ratios(profit,loss,wins,losses)
    return dict(profit_yen=profit, loss_yen=loss, net_yen=math.fsum(pnl)*factor,
        profit_units=wins, loss_units=losses, zero_units=sum(p==0 for p in pnl), net_units=wins-losses,
        trades=len(pnl), net_r=math.fsum(trade[6]/trade[5] for trade in records),
        max_win_yen=max([0.]+pnl)*factor, long_trades=sum(trade[2]>0 for trade in records),
        short_trades=sum(trade[2]<0 for trade in records),
        drawdown_yen=ledger['stats'][1]*factor, profit_factor=pf, average_payoff=payoff)


def aggregate(rows: list[dict]) -> dict:
    """機能: 台帳由来値を合算し、場の極値を全組み合わせで接続する。

    引数: rows(list[dict])。返り値: 期間期待値(dict)。売買側の集計関数は呼ばない。
    """
    rows = sorted(rows,key=lambda row:row['session'])
    fields = ('profit_yen','loss_yen','net_yen','profit_units','loss_units','zero_units','net_units',
              'trades','net_r','long_trades','short_trades')
    value = {key:math.fsum(row[key] for row in rows) for key in fields}
    prior = [math.fsum(row['net_yen'] for row in rows[:i]) for i in range(len(rows))]
    peaks = [0.]+[prior[i]+row['maximum_yen'] for i,row in enumerate(rows)]
    falls = [row['drawdown_yen'] for row in rows]
    for i,row in enumerate(rows):
        trough = prior[i]+row['minimum_yen']
        falls.extend(peak-trough for peak in peaks[:i+1])
    value['drawdown_yen'] = max([0.]+falls)
    value['profit_factor'],value['average_payoff'] = ratios(value['profit_yen'],value['loss_yen'],int(value['profit_units']),int(value['loss_units']))
    value['active_sessions'] = sum(row['trades']>0 for row in rows)
    value['positive_sessions'] = sum(row['net_yen']>0 for row in rows)
    value['without_max_trade'] = value['net_yen']-max([0.]+[row['max_win_yen'] for row in rows])
    value['without_max_session'] = value['net_yen']-max([0.]+[row['net_yen'] for row in rows])
    return value


def trial_values(band: dict, trial: dict) -> tuple:
    """機能: 保存された各公開量と中値から試行の可視比率・押し返しを別計算する。

    引数: band/trial(dict)。返り値: 可視比率又はNone、押し返し(tuple)。
    公開量不明は差分を接続せず、試行全体を比較不可能のままにする。
    """
    previous=None;decreased=False;known=True;down=up=0.
    push=0.
    for sample in trial['samples']:
        push=max(push,band['direction']*(band['price']-sample['mid'])/band['atr'])
        current=sample['quantity']
        if current is None:
            known=False;previous=None;continue
        assert math.isfinite(current) and current>=0
        if previous is not None:
            delta=current-previous
            if delta<0:down-=delta;decreased=True
            elif decreased:up+=delta
        previous=current
    ratio=up/down if trial['complete'] and known and down>0 else None
    close(trial['recovery_ratio'],ratio,'試行の可視比率')
    close(trial['maximum_pushback_atr'],push,'試行の価格押し返し')
    return ratio,push


def independent_flow(ledgers: list[dict], cache: dict) -> dict:
    """機能: 元の帯・試行観測から絞込み段階と主候補集合を独立再集計する。

    引数: ledgers(list[dict])、cache(dict)。返り値: 銘柄別件数(dict)。
    非突破帯の板可用性と、完了後突破に限る板可用性を分けて検算する。
    """
    totals={symbol:{field:0 for field in FLOW_FIELDS} for symbol in SYMBOLS}
    for ledger in ledgers:
        key=(ledger['session'],ledger['symbol']);info=ledger['入口根拠']
        bands=cache[info['母集団キー']][key];counts=info['段階件数']
        local={field:0 for field in FLOW_FIELDS};qualified=[];all_comparable=0
        for band in bands:
            local['bands']+=1
            trials=band['trials'];complete=len(trials)==2 and all(trial['complete'] for trial in trials)
            values=[trial_values(band,trial) for trial in trials]
            comparable=complete and all(value[0] is not None for value in values)
            assert bool(band['features']['two_trials_complete'])==complete
            assert bool(band['features']['quantity_comparable'])==comparable
            local['two_trials']+=int(complete);all_comparable+=int(comparable)
            status=band['status']
            local['early_breakout']+=int(status=='early_breakout')
            local['quality_interruption']+=int(status=='price_quality_interruption')
            if status!='breakout':continue
            assert complete and band['terminal']['event_index']>trials[1]['end']['event_index']
            local['completed_breakout']+=1
            local['breakout_comparable']+=int(comparable)
            if comparable and values[1][0]<values[0][0] and values[1][1]<values[0][1]:
                qualified.append(band)
        assert counts.get('全帯',0)==local['bands']
        assert counts.get('二試行完了',0)==local['two_trials']
        assert counts.get('板比較可能',0)==all_comparable
        assert counts.get('終了:breakout',0)==local['completed_breakout']
        assert counts.get('終了:early_breakout',0)==local['early_breakout']
        assert counts.get('終了:price_quality_interruption',0)==local['quality_interruption']
        saved=info['候補'];local['candidates']=len(qualified)
        assert len(saved)==len(qualified)==counts.get('自己条件通過',0)==counts.get('全候補',0)
        for record,band in zip(saved,qualified):
            assert record['band_id']==band['band_id']
            assert record['decision']==band['terminal']
            assert record['direction']==band['direction']==record['band_direction']
            assert record['price']==band['price'] and record['features']==band['features'] and record['peer'] is None
        local['trades']=len(ledger['trades'])
        chain=[local[field] for field in FLOW_FIELDS[:6]]
        assert chain==sorted(chain,reverse=True),(key,chain)
        for field in FLOW_FIELDS:totals[key[1]][field]+=local[field]
    return totals


class Tables(HTMLParser):
    """機能: 全表示行・セル文字・数値属性・選択肢とリンクを独立に抽出する。

    引数: HTMLParser標準。返り値: インスタンス属性へ抽出結果を保持する。
    """
    def __init__(self) -> None:
        """機能: 抽出先を初期化する。

        引数: なし。返り値: なし(None)。
        """
        super().__init__(convert_charrefs=True)
        self.rows=[];self.current=None;self.current_cell=None
        self.options=[];self.sections=[];self.links=[];self.ids=[];self.verdict={};self.preview=False

    def handle_starttag(self, tag: str, attrs: list[tuple]) -> None:
        """機能: 監査属性と可視数値セルを記録する。

        引数: tag(str)、attrs(list[tuple])。返り値: なし(None)。
        """
        a=dict(attrs)
        if 'id' in a:
            self.ids.append(a['id'])
            self.preview |= a['id']=='preview'
        if tag=='a' and 'href' in a:self.links.append(a['href'])
        if tag=='option':self.options.append(a.get('value'))
        if 'data-method' in a:self.sections.append((a['data-method'],'hidden' in a))
        if 'data-verdict' in a:self.verdict[a['data-verdict']]=json.loads(a['data-value'])
        if tag=='tr' and 'data-kind' in a:
            assert self.current is None
            self.current=dict(kind=a['data-kind'],id=a['data-id'],symbol=a['data-symbol'],period=a['data-period'],cells={})
        if tag=='td' and 'data-field' in a:
            assert self.current is not None and self.current_cell is None
            field=a['data-field'];assert field not in self.current['cells']
            self.current_cell=dict(field=field,value=json.loads(a['data-value']),text='')

    def handle_data(self, data: str) -> None:
        """機能: 数値セルの実際に表示される文字を収集する。

        引数: data(str)。返り値: なし(None)。
        """
        if self.current_cell is not None:self.current_cell['text']+=data

    def handle_endtag(self, tag: str) -> None:
        """機能: セルと行を確定する。

        引数: tag(str)。返り値: なし(None)。
        """
        if tag=='td' and self.current_cell is not None:
            cell=self.current_cell;self.current['cells'][cell['field']]=cell;self.current_cell=None
        if tag=='tr' and self.current is not None:
            self.rows.append(self.current);self.current=None


def parse(path: Path) -> Tables:
    """機能: HTMLを読み、重複要素IDと途切れた行を拒否する。

    引数: path(Path)。返り値: 抽出器(Tables)。
    """
    parser=Tables();parser.feed(path.read_text(encoding='utf-8'));parser.close()
    assert parser.current is None and parser.current_cell is None
    assert len(parser.ids)==len(set(parser.ids)),path
    return parser


def verify_rows(rows: list[dict], expected: dict, fields: tuple) -> int:
    """機能: 全行集合・数値属性・可視丸め文字を期待値へ照合する。

    引数: rows(list[dict])、expected(dict)、fields(tuple)。返り値: 数値セル件数(int)。
    """
    found=set();count=0
    for row in rows:
        key=(row['id'],row['symbol'],row['period'])
        assert key in expected and key not in found,key
        found.add(key);assert tuple(row['cells'])==fields,key
        for field in fields:
            cell=row['cells'][field];value=expected[key][field]
            close(cell['value'],value,(key,field))
            decimals=2 if field in ('profit_factor','average_payoff','net_r') else (3 if field=='平均ATR反応' else 0)
            shown='未定義' if value is None else format(value,','+f'.{decimals}f')
            assert cell['text']==shown,(key,field,cell['text'],shown)
            count+=1
    assert found==set(expected),(len(found),len(expected),set(expected)-found)
    return count


def render_selftest() -> dict:
    """機能: 実成績なしで281条件の全表示と4判定を最後まで生成して検査する。

    引数: なし。返り値: 人工表示の件数(dict)。正式成果フォルダへは書き込まない。
    """
    import design
    import report
    specs=design.catalog()+design.supplementary()
    session_ids=[f'2026-09-{day:02d}_{part}' for day in (21,22,23,24,25,28) for part in ('Day','Night')]+['2026-09-29_Day']
    sessions={};index={};expect_profit={};expect_compare={}
    for spec in specs:
        identifier=spec['id'];saved=[]
        for symbol in SYMBOLS:
            own=[];factor=1000. if symbol=='TOPIX' else 10.
            for i,session_id in enumerate(session_ids):
                net=(-5.,0.,10.,2.,-1.)[i%5];direction=1 if i%2 else -1
                ledger=dict(trades=[[0,1,direction,100.,100.+direction*net,2.,net,1,0,0]],stats=[net,abs(net)+2.])
                row=from_trades(ledger,factor)
                row.update(session=session_id,symbol=symbol,minimum_yen=min(0.,net-1.)*factor,
                    maximum_yen=max(0.,net+1.)*factor,held_minutes=1.,candidates=1,accepted=1,cancelled=0)
                saved.append(row);own.append(row);expect_profit[(identifier,symbol,session_id)]=row
            total=aggregate(own)
            index.setdefault(identifier,dict(spec=spec,symbols={}))['symbols'][symbol]=total
            expect_profit[(identifier,symbol,'全13セッション')]=total
            if identifier in IDS:expect_compare[(identifier,symbol,'全13セッション')]=total
            for start in ('2026-09-21','2026-09-28'):
                selected=[row for row in own if (date.fromisoformat(row['session'][:10])-timedelta(days=date.fromisoformat(row['session'][:10]).weekday())).isoformat()==start]
                expect_profit[(identifier,symbol,start+'週')]=aggregate(selected)
        sessions[identifier]=saved
    responses={identifier:{symbol:{h:dict(件数=0,正方向数=0,逆方向数=0,同値数=0,平均ATR反応=None) for h in ('5','15')} for symbol in SYMBOLS} for identifier in IDS}
    flow={symbol:dict(bands=40,two_trials=35,completed_breakout=30,breakout_comparable=25,
        candidates=15,trades=13,early_breakout=4,quality_interruption=3) for symbol in SYMBOLS}
    verdict=dict(既知経済目安合格=False,基礎候補=False,板の比較付加価値=True,実行感度=False,窓距離感度=False)
    payload=dict(specs=specs,index=index,sessions=sessions,responses=responses,flow=flow,assessment=verdict,chart_ready=False)
    main_html=report.render_main(payload,True);all_html=report.render_all(payload,True)
    pages=[]
    for source in (main_html,all_html):
        page=Tables();page.feed(source);page.close();pages.append(page)
        assert page.preview and page.current is None and len(page.ids)==len(set(page.ids))
    main_page,all_page=pages
    count=verify_rows(all_page.rows,expect_profit,FIELDS)
    count+=verify_rows([row for row in main_page.rows if row['kind']=='comparison'],expect_compare,COMPARISON_FIELDS)
    expect_response={(identifier,symbol,h):responses[identifier][symbol][h] for identifier in IDS for symbol in SYMBOLS for h in ('5','15')}
    count+=verify_rows([row for row in main_page.rows if row['kind']=='response'],expect_response,RESPONSE_FIELDS)
    expect_flow={('B00',symbol,'全13セッション'):flow[symbol] for symbol in SYMBOLS}
    count+=verify_rows([row for row in main_page.rows if row['kind']=='flow'],expect_flow,FLOW_FIELDS)
    assert len(all_page.rows)==8992 and len(main_page.rows)==74
    assert all_page.options==[spec['id'] for spec in specs]
    assert all_page.sections==[(spec['id'],i>0) for i,spec in enumerate(specs)]
    assert main_page.verdict=={key:verdict[key] for key in ('基礎候補','板の比較付加価値','実行感度','窓距離感度')}
    assert '学習用の除外はありません' in main_html and '黒字でも採用しません' in main_html
    return dict(全合格=True,損益行数=8992,比較行数=24,未来反応行数=48,段階行数=2,可視数値セル数=count,全条件選択数=281,実成果書込数=0)


def flow_selftest() -> dict:
    """機能: 非突破帯の板比較可能と早過ぎ突破を混同する表示を人工で拒否する。

    引数: なし。返り値: 段階件数と破損拒否数(dict)。売買器は呼ばない。
    """
    def trial(q: list, push: float, end: int) -> dict:
        """機能: 人工の公開量・価格列を作る。

        引数: q(list)、push(float)、end(int)。返り値: 人工試行(dict)。
        """
        value=2. if q==[10.,5.,15.] else (.5 if q==[10.,6.,8.] else None)
        return dict(complete=True,end=dict(event_index=end),recovery_ratio=value,maximum_pushback_atr=push,
            samples=[dict(quantity=qty,mid=100.-push*10.) for qty in q])
    bands=[]
    for i,status in enumerate(('breakout','breakout','expiry','early_breakout','price_quality_interruption')):
        trials=[trial([10.,5.,15.],.5,10),trial([10.,6.,8.] if i!=1 else [10.,None,8.],.1,30)] if i<4 else []
        f=dict(two_trials_complete=i<4,quantity_comparable=i in (0,2,3))
        bands.append(dict(band_id=i+1,direction=1,price=100.,atr=10.,status=status,trials=trials,features=f,
            terminal=dict(event_index=40,reason=status)))
    primary=bands[0]
    info=dict(母集団キー='人工',段階件数={'全帯':5,'二試行完了':4,'板比較可能':3,'終了:breakout':2,
        '終了:early_breakout':1,'終了:price_quality_interruption':1,'自己条件通過':1,'全候補':1},
        候補=[dict(band_id=1,decision=primary['terminal'],direction=1,band_direction=1,price=100.,features=primary['features'],peer=None)])
    ledger=dict(session='人工',symbol='TOPIX',入口根拠=info,trades=[[0]*10])
    cache={'人工':{('人工','TOPIX'):bands}}
    value=independent_flow([ledger],cache)
    assert value['TOPIX']==dict(bands=5,two_trials=4,completed_breakout=2,breakout_comparable=1,candidates=1,
        trades=1,early_breakout=1,quality_interruption=1)
    bad=[]
    changed=deepcopy(ledger);changed['入口根拠']['段階件数']['板比較可能']=1;bad.append((changed,cache))
    changed=deepcopy(ledger);changed['入口根拠']['候補']=[];bad.append((changed,cache))
    changed=deepcopy(ledger);changed['入口根拠']['候補'][0]['direction']=-1;bad.append((changed,cache))
    changed=deepcopy(cache);changed['人工'][('人工','TOPIX')][1]['features']['quantity_comparable']=True;bad.append((ledger,changed))
    changed=deepcopy(cache);changed['人工'][('人工','TOPIX')][0]['trials'][1]['recovery_ratio']=0.;bad.append((ledger,changed))
    changed=deepcopy(cache);changed['人工'][('人工','TOPIX')][0]['terminal']['event_index']=30;bad.append((ledger,changed))
    rejected=0
    for bad_ledger,bad_cache in bad:
        try:independent_flow([bad_ledger],bad_cache)
        except AssertionError:rejected+=1
    assert rejected==len(bad)
    return dict(全合格=True,人工帯数=5,段階件数=value,破損拒否数=rejected)


def selftest() -> dict:
    """機能: 独立集計の人工曲線とHTML数値の破損拒否を検査する。

    引数: なし。返り値: 合否証跡(dict)。実データは読まない。
    """
    rows=[]
    for i,(net,high,low,dd) in enumerate(((5,12,-4,16),(-8,3,-12,15),(10,18,-3,8))):
        value=from_trades(dict(trades=[[0,1,1,100,100+net,2,net,1,0,0]],stats=[net,dd]),1.)
        value.update(session=f'2026-01-0{i+1}_Day',maximum_yen=high,minimum_yen=low)
        rows.append(value)
    value=aggregate(rows[::-1]);close(value['net_yen'],7,'人工収支');close(value['drawdown_yen'],19,'人工接続DD')
    close(value['profit_yen'],15,'人工利益');close(value['loss_yen'],8,'人工損失')
    expected={('B00','TOPIX','全13セッション'):{'net_yen':1000.}}
    valid='<tr data-kind="profit" data-id="B00" data-symbol="TOPIX" data-period="全13セッション"><td data-field="net_yen" data-value="1000.0">1,000</td></tr>'
    parser=Tables();parser.feed(valid);assert verify_rows(parser.rows,expected,('net_yen',))==1
    broken=(valid.replace('1000.0','1001.0'),valid.replace('>1,000<','>1,001<'),
        valid.replace('B00','B01'),valid+valid,valid.replace('data-field="net_yen"','data-field="loss_yen"'), '')
    rejected=0
    for item in broken:
        try:
            parser=Tables();parser.feed(item);verify_rows(parser.rows,expected,('net_yen',))
        except AssertionError:rejected+=1
    assert rejected==len(broken)
    rendered=render_selftest()
    stages=flow_selftest()
    return dict(全合格=True,人工集計検査数=4,可視数値検査数=1,破損拒否数=rejected,
        全表示の人工検査=rendered,段階集計の人工検査=stages,
        実装SHA256=digest(Path(__file__)),報告実装SHA256=digest(HERE/'report.py'),実データ計算数=0)


def main() -> None:
    """機能: 全8992損益行・24比較・48未来評価・2段階表を全数検算する。

    引数: --selftest(bool)。返り値: なし(None)。新しい売買や採否は計算しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--selftest',action='store_true');args=parser.parse_args()
    if args.selftest:
        value=selftest();(HERE/'report_selftest.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(value,ensure_ascii=False));return
    manifest=read(HERE/'report_manifest.json');references=dict(manifest['参照資料SHA256'])
    for relative,sha in references.items():assert digest(ROOT/relative)==sha,relative
    for relative,sha in manifest['出力SHA256'].items():assert digest(ROOT/relative)==sha,relative
    assert manifest['生成実装SHA256']==digest(HERE/'report.py')
    fixed=read(HERE/'探索条件の固定.json');specs=fixed['主条件']+fixed['補助条件'];assert len(specs)==281
    complete=read(HERE/'主再生の完了.json')
    index=read(HERE/'全条件の期間集計.json.gz');verdict=read(HERE/'assess_results.json')
    expected={};comparison={};response={};session_count=trade_count=0;main_ledgers=[]
    for spec in specs:
        identifier=spec['id'];saved=read(HERE/'sessions'/(identifier+'.json.gz'))
        path=HERE/'ledgers'/(identifier+'.json.gz');ledgers=read(path);relative=path.relative_to(ROOT).as_posix()
        if identifier=='B00':main_ledgers=ledgers
        references[relative]=digest(path);assert references[relative]==complete['参照SHA256'][relative],relative
        ledger_map={(row['session'],row['symbol']):row for row in ledgers}
        assert len(saved)==len(ledger_map)==26
        calculated=[]
        for row in saved:
            key=(row['session'],row['symbol']);factor=1000. if row['symbol']=='TOPIX' else 10.
            item=from_trades(ledger_map[key],factor)
            for field in ('profit_yen','loss_yen','net_yen','profit_units','loss_units','zero_units','trades',
                          'net_r','max_win_yen','long_trades','short_trades','drawdown_yen'):
                close(row[field],item[field],(identifier,key,field))
            item.update(session=row['session'],symbol=row['symbol'],minimum_yen=row['minimum_yen'],maximum_yen=row['maximum_yen'])
            calculated.append(item);session_count+=1;trade_count+=item['trades']
            expected[(identifier,row['symbol'],row['session'])]=item
        for symbol in SYMBOLS:
            own=[row for row in calculated if row['symbol']==symbol];assert len(own)==13
            total=aggregate(own)
            for field,value in total.items():
                if field!='net_units':close(index[identifier]['symbols'][symbol][field],value,(identifier,symbol,field))
            expected[(identifier,symbol,'全13セッション')]=total
            if identifier in IDS:comparison[(identifier,symbol,'全13セッション')]=total
            for start in ('2026-09-21','2026-09-28'):
                selected=[]
                for row in own:
                    day=date.fromisoformat(row['session'][:10]);monday=(day-timedelta(days=day.weekday())).isoformat()
                    if monday==start:selected.append(row)
                expected[(identifier,symbol,start+'週')]=aggregate(selected)
    for identifier in IDS:
        path=HERE/'responses'/(identifier+'.json.gz');values=read(path)
        references[path.relative_to(ROOT).as_posix()]=digest(path)
        for symbol in SYMBOLS:
            for horizon in ('5','15'):
                moves=[]
                for row in values:
                    if row['symbol']==symbol:moves.extend(record[4] for record in row['評価専用未来反応'][horizon]['明細'])
                response[(identifier,symbol,horizon)]=dict(件数=len(moves),正方向数=sum(x>0 for x in moves),
                    逆方向数=sum(x<0 for x in moves),同値数=sum(x==0 for x in moves),平均ATR反応=math.fsum(moves)/len(moves) if moves else None)
    cache_path=HERE/'band_cache.pkl'
    with cache_path.open('rb') as stream:cache=pickle.load(stream)
    references[cache_path.relative_to(ROOT).as_posix()]=digest(cache_path)
    stages=independent_flow(main_ledgers,cache)
    flow={('B00',symbol,'全13セッション'):stages[symbol] for symbol in SYMBOLS}
    pages={MAIN:parse(MAIN),ALL:parse(ALL)}
    main_page,all_page=pages[MAIN],pages[ALL]
    cells=verify_rows([row for row in all_page.rows if row['kind']=='profit'],expected,FIELDS)
    cells+=verify_rows([row for row in main_page.rows if row['kind']=='comparison'],comparison,COMPARISON_FIELDS)
    cells+=verify_rows([row for row in main_page.rows if row['kind']=='response'],response,RESPONSE_FIELDS)
    cells+=verify_rows([row for row in main_page.rows if row['kind']=='flow'],flow,FLOW_FIELDS)
    assert len(all_page.rows)==8992 and len(main_page.rows)==74
    assert all_page.options==[spec['id'] for spec in specs]
    assert all_page.sections==[(spec['id'],i>0) for i,spec in enumerate(specs)]
    assert main_page.verdict=={key:verdict[key] for key in ('基礎候補','板の比較付加価値','実行感度','窓距離感度')}
    for path,page in pages.items():
        assert page.preview is manifest['暫定版']
        for href in page.links:
            url=urlsplit(href);assert url.scheme=='' and url.netloc=='',href
            target=(path.parent/unquote(url.path)).resolve()
            if target==HERE/'report_audit.json':continue
            assert target.is_file(),target
            if url.fragment:
                assert unquote(url.fragment) in parse(target).ids,(target,url.fragment)
    result=dict(全合格=True,全条件数=281,全セッション台帳数=session_count,全返済数=trade_count,
        損益表示行数=len(expected),比較表示行数=len(comparison),未来反応表示行数=len(response),段階表示行数=len(flow),可視数値セル数=cells,
        全返済からの金額枚数R一致=True,各期間の独立再集計一致=True,全選択対象一致=True,
        全13セッション評価=True,学習用除外なし=True,全試行観測からの段階件数と候補一致=True,段階別件数=stages,
        全リンク一致=True,暫定版=manifest['暫定版'],
        限定='含み込み当場DDと極値は完備会計の保存値へ依拠し、その場間接続を独立な全組合せ式で検算。未来反応は保存明細の再集計であり未来原本の再探索はしない。',
        参照資料SHA256=references,出力SHA256=manifest['出力SHA256'],
        監査実装SHA256=digest(Path(__file__)),報告実装SHA256=digest(HERE/'report.py'))
    (HERE/'report_audit.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('参照資料SHA256','出力SHA256')},ensure_ascii=False))


if __name__=='__main__':
    main()
