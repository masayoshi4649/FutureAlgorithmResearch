"""保存全返済から数表を別集計し、HTMLの全可視数値と固定対象を検算する。"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import gzip
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
from urllib.parse import unquote, urlsplit


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00034_予想外の板圧力と独立価格対照'
MAIN = OUT/'予想外の板圧力と独立価格対照.html'
ALL = OUT/'全条件損益.html'
IDS = ('I00','I01','I02','I03','I19','I04','I05','I06')
SYMBOLS = ('TOPIX','NK225')
FIELDS = ('profit_yen','loss_yen','net_yen','profit_units','loss_units','net_units','zero_units')
COMPARISON_FIELDS = ('profit_yen','loss_yen','net_yen','profit_factor','average_payoff','net_r','drawdown_yen')
RESPONSE_FIELDS = ('件数','正方向数','逆方向数','同値数','平均ATR反応')


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
    expected={('I00','TOPIX','全13セッション'):{'net_yen':1000.}}
    valid='<tr data-kind="profit" data-id="I00" data-symbol="TOPIX" data-period="全13セッション"><td data-field="net_yen" data-value="1000.0">1,000</td></tr>'
    parser=Tables();parser.feed(valid);assert verify_rows(parser.rows,expected,('net_yen',))==1
    broken=(valid.replace('1000.0','1001.0'),valid.replace('>1,000<','>1,001<'),
        valid.replace('I00','I01'),valid+valid,valid.replace('data-field="net_yen"','data-field="loss_yen"'), '')
    rejected=0
    for item in broken:
        try:
            parser=Tables();parser.feed(item);verify_rows(parser.rows,expected,('net_yen',))
        except AssertionError:rejected+=1
    assert rejected==len(broken)
    return dict(全合格=True,人工集計検査数=4,可視数値検査数=1,破損拒否数=rejected,
        実装SHA256=digest(Path(__file__)),実データ計算数=0)


def main() -> None:
    """機能: 全7680損益行・16比較・32未来評価の保存数値と可視文字を全数検算する。

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
    fixed=read(HERE/'探索条件の固定.json');specs=fixed['主条件']+fixed['補助条件'];assert len(specs)==240
    complete=read(HERE/'主再生の完了.json')
    index=read(HERE/'全条件の期間集計.json.gz');verdict=read(HERE/'assess_results.json')
    expected={};comparison={};response={};session_count=trade_count=0
    for spec in specs:
        identifier=spec['id'];saved=read(HERE/'sessions'/(identifier+'.json.gz'))
        path=HERE/'ledgers'/(identifier+'.json.gz');ledgers=read(path);relative=path.relative_to(ROOT).as_posix()
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
            earliest=sorted(own,key=lambda row:row['session'])[:2]
            assert all(row['trades']==0 for row in earliest),(identifier,symbol,'学習期間')
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
    pages={MAIN:parse(MAIN),ALL:parse(ALL)}
    main_page,all_page=pages[MAIN],pages[ALL]
    cells=verify_rows([row for row in all_page.rows if row['kind']=='profit'],expected,FIELDS)
    cells+=verify_rows([row for row in main_page.rows if row['kind']=='comparison'],comparison,COMPARISON_FIELDS)
    cells+=verify_rows([row for row in main_page.rows if row['kind']=='response'],response,RESPONSE_FIELDS)
    assert len(all_page.rows)==7680 and len(main_page.rows)==48
    assert all_page.options==[spec['id'] for spec in specs]
    assert all_page.sections==[(spec['id'],i>0) for i,spec in enumerate(specs)]
    assert main_page.verdict=={key:verdict[key] for key in ('基礎候補','板の比較付加価値','実行感度')}
    for path,page in pages.items():
        assert page.preview is manifest['暫定版']
        for href in page.links:
            url=urlsplit(href);assert url.scheme=='' and url.netloc=='',href
            target=(path.parent/unquote(url.path)).resolve()
            if target==HERE/'report_audit.json':continue
            assert target.is_file(),target
            if url.fragment:
                assert unquote(url.fragment) in parse(target).ids,(target,url.fragment)
    result=dict(全合格=True,全条件数=240,全セッション台帳数=session_count,全返済数=trade_count,
        損益表示行数=len(expected),比較表示行数=len(comparison),未来反応表示行数=len(response),可視数値セル数=cells,
        全返済からの金額枚数R一致=True,各期間の独立再集計一致=True,全選択対象一致=True,
        学習2セッションの全条件取引0=True,全リンク一致=True,暫定版=manifest['暫定版'],
        限定='含み込み当場DDと極値は完備会計の保存値へ依拠し、その場間接続を独立な全組合せ式で検算。未来反応は保存明細の再集計であり未来原本の再探索はしない。',
        参照資料SHA256=references,出力SHA256=manifest['出力SHA256'],
        監査実装SHA256=digest(Path(__file__)),報告実装SHA256=digest(HERE/'report.py'))
    (HERE/'report_audit.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('参照資料SHA256','出力SHA256')},ensure_ascii=False))


if __name__=='__main__':
    main()
