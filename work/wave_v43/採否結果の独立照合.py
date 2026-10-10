"""保存された約定価格と元組から、採否の金額・比率・活動・中心差を別式で確認する。"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REFERENCES = {}


def read(path: Path) -> object:
    """機能: 内容を指紋へ結び、通常又は圧縮した保存結果を読む。

    引数: path(Path)。返り値: 保存された資料(object)。新しい売買は計算しない。
    """
    raw = path.read_bytes()
    REFERENCES[path.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def equal(left: float, right: float) -> None:
    """機能: 有限数値の差が既定誤差内であることを確認する。

    引数: left/right(float)。返り値: なし(None)。
    """
    assert math.isfinite(left) and math.isfinite(right) and abs(left-right) <= 1e-6, (left,right)


def main() -> None:
    """機能: 全32台帳を別算術で集計し、固定採否と実際の差の一致を保存する。

    引数: なし。返り値: なし(None)。注文器・採否関数を呼ばず、既存結果だけを読む。
    """
    guard = read(HERE/'追加完備監査.json')
    assert guard['全合格'] is True and guard['追加完備完了'] is True
    for relative, expected in guard['参照資料SHA256'].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == expected
    fixed = read(HERE/'探索条件の固定.json')
    decision = read(HERE/'assess_results.json')
    specs = fixed['conditions']
    names = fixed['全セッション']
    cells, summaries = {}, {}
    row_count = leg_count = group_count = 0
    for spec in specs:
        identifier = spec['id']
        books = read(HERE/'ledgers'/(identifier+'.json.gz'))
        rows = read(HERE/'sessions'/(identifier+'.json.gz'))
        summary = read(HERE/'summaries'/(identifier+'.json'))
        summaries[identifier] = summary
        mapping = {(r['session'],r['symbol']):r for r in rows}
        measured = {}
        for book in books:
            key = book['session'],book['symbol']
            factor = 1000. if key[1] == 'TOPIX' else 10.
            trades = book['trades']
            profits = [(t[5]-t[4])*t[2]*t[3]*factor for t in trades]
            gains, losses = sum(v for v in profits if v>0), -sum(v for v in profits if v<0)
            values = dict(gross_profit_yen=gains,gross_loss_yen=losses,net_yen=sum(profits),
                profit_units=sum(t[3] for t,p in zip(trades,profits) if p>0),
                loss_units=sum(t[3] for t,p in zip(trades,profits) if p<0),
                zero_units=sum(t[3] for t,p in zip(trades,profits) if p==0))
            for field,value in values.items():
                equal(value,mapping[key][field])
            cycles = book['cycles']
            cp = [c[3]*factor for c in cycles]
            equal(sum(cp),sum(profits))
            measured[key] = dict(**values,group_profits=cp,longs=sum(c[8]==1 for c in cycles),
                shorts=sum(c[8]==-1 for c in cycles),net_r=sum(c[3]/c[4] for c in cycles))
            row_count += 1; leg_count += len(trades); group_count += len(cycles)
        details = {}
        for period,used in (('all_symbols',names),('symbols',names[6:])):
            details[period] = {}
            for symbol in ('TOPIX','NK225'):
                part = [measured[(n,symbol)] for n in used]
                pnl = [v for row in part for v in row['group_profits']]
                wins,losses = [v for v in pnl if v>0],[-v for v in pnl if v<0]
                net = sum(pnl)
                pf = sum(wins)/sum(losses) if losses else None
                payoff = (sum(wins)/len(wins))/(sum(losses)/len(losses)) if wins and losses else None
                removed_group = net-max([0.]+wins)
                removed_session = net-max([0.]+[r['net_yen'] for r in part])
                two = net-sum(sorted(wins,reverse=True)[:2])
                active = len(pnl)>0 and sum(r['longs'] for r in part)>0 and sum(r['shorts'] for r in part)>0
                basic = net>0 and pf is not None and pf>1 and payoff is not None and payoff>1
                base = basic and removed_group>=-1e-6 and removed_session>=-1e-6 and active
                saved = decision['全条件'][identifier]['期間別'][period][symbol]
                for field,value in [('収支円',net),('最大勝ち元組除外収支円',removed_group),
                    ('最大黒字場除外収支円',removed_session),('上位二勝ち元組同時除外収支円',two),
                    ('買い元組数',sum(r['longs'] for r in part)),('売り元組数',sum(r['shorts'] for r in part)),
                    ('元組数',len(pnl)),('稼働セッション数',sum(bool(r['group_profits']) for r in part))]:
                    equal(value,saved[field])
                assert saved['実取引と買売双方'] is active and saved['活動込み基礎候補'] is base
                assert all(saved['基礎検査'].values()) is basic
                if pf is None: assert saved['比率']['元組PF'] is None
                else: equal(pf,saved['比率']['元組PF'])
                if payoff is None: assert saved['比率']['平均元組勝敗比'] is None
                else: equal(payoff,saved['比率']['平均元組勝敗比'])
                for field in ('gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units','net_r'):
                    equal(sum(r[field] for r in part),summary[period][symbol][field])
                dd = summary[period][symbol]['drawdown_yen']
                equal(dd,saved['時価最大下落円'])
                details[period][symbol] = dict(収支円=net,時価DD円=dd,基礎候補=base,執行基礎=basic,
                    最大一勝除外円=removed_group,最大一場除外円=removed_session,上位二勝同時除外円=two)
        expected_base = all(c['基礎候補'] for p in details.values() for c in p.values())
        assert decision['全条件'][identifier]['基礎候補'] is expected_base
        cells[identifier] = details

    exits = {}
    for manager in ('A0','B00_RB00_F25_N1'):
        label = decision['出口別'][manager]
        primary,reference = f'M2_100__{manager}__V000',f'S100__{manager}__V000'
        assert label['主案ID']==primary and label['単一中央ID']==reference
        gaps=[]
        for period in ('all_symbols','symbols'):
            for symbol in ('TOPIX','NK225'):
                candidate,original = cells[primary][period][symbol],cells[reference][period][symbol]
                gap = dict(期間=period,銘柄=symbol,収支差円=candidate['収支円']-original['収支円'],
                    最大下落差円=candidate['時価DD円']-original['時価DD円'])
                gaps.append(gap)
        assert gaps == label['中央の収益DD関係']['差']
        improved = all(r['収支差円']>1e-6 for r in gaps if r['期間']=='symbols') and all(
            r['収支差円']>=-1e-6 for r in gaps if r['期間']=='all_symbols')
        noninferior = all(r['収支差円']>=-1e-6 and r['最大下落差円']<=1e-6 for r in gaps)
        dominated = all(r['収支差円']<=1e-6 and r['最大下落差円']>=-1e-6 for r in gaps)
        changed = any(abs(r[k])>1e-6 for r in gaps for k in ('収支差円','最大下落差円'))
        relation = '同値' if not changed else '同時改善' if noninferior else '対照優位' if dominated else '交換又は混在'
        assert label['中央の収益追加改善'] is improved and label['中央の収益DD関係']['関係']==relation
        robustness = all(c['基礎候補'] for center in ('080','100','120')
            for p in cells[f'M2_{center}__{manager}__V000'].values() for c in p.values())
        central = all(c['基礎候補'] for p in cells[primary].values() for c in p.values())
        execution = all(c['執行基礎'] for v in ('L001','L005','L015','O000')
            for c in cells[f'M2_100__{manager}__{v}']['symbols'].values())
        assert label['三中心耐性'] is robustness and label['中央の基礎候補'] is central
        assert label['四執行基礎'] is execution
        assert label['経済目安合格'] is (central and improved and robustness)
        assert label['既知比較の研究候補'] is (central and improved and robustness)
        exits[manager]=dict(中央基礎=central,中央追加増益=improved,収支DD関係=relation,
            三中心耐性=robustness,四執行基礎=execution,研究候補=label['既知比較の研究候補'],差=gaps)
    assert row_count==832 and len(cells)==32
    for relative,sha in REFERENCES.items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==sha
    REFERENCES[Path(__file__).relative_to(ROOT).as_posix()] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output=dict(全合格=True,全条件数=32,全入力数=row_count,全返済脚数=leg_count,全元組数=group_count,
        金額枚数元組比率活動除外一致=True,固定採否と数値差一致=True,旧採否関数呼出=False,
        追加売買再生=False,DD='完備済みの全時価監査値を使用し、条件間の差と採否を別計算。時価曲線を再生しない。',
        出口別=exits,参照資料SHA256=REFERENCES,現在API取得数=0)
    (HERE/'採否結果の独立照合.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k not in ('参照資料SHA256','出口別')},ensure_ascii=False))


if __name__=='__main__':main()
