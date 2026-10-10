"""暖機12入口×3管理の全件終了後に、毎場初期化との差と安定領域を集計する。"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

import warm_component_signals as signals


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASES=('A0__V000','G000_F25_N1__V000','G150_F50_N1__V000')
SYMBOLS=('TOPIX','NK225')


def read(path: Path) -> object:
    """機能: 通常又は圧縮された保存JSONを読む。

    引数: path (Path)。返り値: 保存内容 (object)。
    """
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def sha(path: Path) -> str:
    """機能: 全件完了証拠と集計元の指紋を記録する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(8388608):
            h.update(block)
    return h.hexdigest()


def save(path: Path,value: object) -> None:
    """機能: 新作業の評価値を有限JSONとして保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')


def freeze() -> dict:
    """機能: 暖機の経済結果を読む前に旧入口と同じ判断基準を固定する。

    引数: なし。返り値: 評価規則と参照指紋 (dict)。
    """
    value=dict(条件数=36,期間='旧全13と旧後半7。追加9/29ナイトを使わない。',
        基礎='net_yen>0、average_unit_payoff>1、上位利益2元組の同時除外収支>0を全13/後7×両銘柄で確認。',
        領域='相手有無・短期有無・管理を固定し、主倍率0.8/1/1.2の全12セルで基礎合格。全12領域を表示。',
        対応='同じ主倍率・相手・短期・管理を使う毎場初期化版との差。全144期間セルと936セッション差を保存。',
        解釈='最高益への差替えは行わない。暖機で入口経路が変わるため同じ組番号同士の因果対応を作らない。',
        検算='元価格・方向・数量から全返済脚の利益損失枚数を再構成。集中は元組単位、DDは完了済み会計値。',
        参照SHA256={str(path.relative_to(ROOT)).replace('\\','/'):sha(path) for path in (
            Path(__file__),HERE/'暖機経済比較の固定.json',HERE/'入口判定規則.json',HERE/'warm_signals_fixed.json')},
        新ナイト読取=False)
    path=HERE/'暖機判定規則.json'
    if path.exists():
        assert read(path)==value
    else:
        save(path,value)
    return value


def equal(a: float,b: float) -> None:
    """機能: 有限な円又は数量を小さな浮動小数誤差以内で照合する。

    引数: a/b (float)。返り値: なし (None)。
    """
    assert np.isfinite(a) and np.isfinite(b)
    assert np.isclose(a,b,rtol=1e-10,atol=1e-6),(a,b)


def independent_sessions(ledgers: list,sessions: list) -> tuple[dict,int]:
    """機能: 全返済の価格・数量からセッション損益と勝敗枚数を再構成する。

    引数: ledgers/sessions (list[dict])。返り値: キー別独立集計と返済脚数 (tuple[dict,int])。
    """
    by_key={(row['session'],row['symbol']):row for row in sessions}
    assert len(by_key)==26 and len(ledgers)==26
    result={}
    legs=0
    for ledger in ledgers:
        key=ledger['session'],ledger['symbol']
        assert key in by_key and key[0]!='2026-09-29_Night' and key not in result
        trades=np.asarray(ledger['trades'],float).reshape(-1,11)
        cycles=np.asarray(ledger['cycles'],float).reshape(-1,10)
        mult=float(ledger['config']['point_value'])
        profit=loss=0.
        win_qty=loss_qty=zero_qty=0
        campaign={}
        for trade in trades:
            assert trade[3]>0 and trade[3]==int(trade[3]) and trade[2] in (-1,1)
            points=trade[2]*trade[3]*(trade[5]-trade[4])
            equal(points,trade[10])
            money=points*mult
            campaign[int(trade[0])]=campaign.get(int(trade[0]),0.)+money
            if money>0:
                profit+=money
                win_qty+=int(trade[3])
            elif money<0:
                loss-=money
                loss_qty+=int(trade[3])
            else:
                zero_qty+=int(trade[3])
        assert len(campaign)==len(cycles)
        cycle_values=[]
        for cycle in cycles:
            money=cycle[3]*mult
            equal(money,campaign[int(cycle[0])])
            cycle_values.append(float(money))
        value=dict(gross_profit_yen=profit,gross_loss_yen=loss,net_yen=profit-loss,
                   profit_units=win_qty,loss_units=loss_qty,zero_units=zero_qty,
                   closed_units=win_qty+loss_qty+zero_qty,cycle_values=cycle_values)
        for column in ('gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units','closed_units'):
            equal(value[column],by_key[key][column])
        expected_top=sorted([v for v in cycle_values if v>0],reverse=True)[:2]
        np.testing.assert_allclose(expected_top,by_key[key]['two_largest_cycle_profits'],rtol=1e-10,atol=1e-6)
        result[key]=value
        legs+=len(trades)
    return result,legs


def passing(net: float,payoff: float | None,removed: float) -> bool:
    """機能: 事前に固定した三条件を一つの期間銘柄セルへ適用する。

    引数: net/removed (float)、payoff (float|None)。返り値: 基礎合格 (bool)。
    """
    return bool(net>0 and payoff is not None and payoff>1 and removed>0)


def assess(protocol: dict) -> dict:
    """機能: 完備後の36条件と初期化対応版を全件集計する。

    引数: protocol (dict)。返り値: 全期間セル・対応差・安定領域・独立検算 (dict)。
    """
    complete=read(HERE/'warm_complete.json')
    assert complete['全合格'] and complete['条件数']==36 and complete['入力会計数']==936
    assert complete['固定SHA256']==sha(HERE/'暖機経済比較の固定.json')
    assert complete['新Night使用'] is False
    specs=signals.catalog()
    assert {row['入口'] for row in complete['完了']}=={spec['id'] for spec in specs}
    for done in complete['完了']:
        assert done['全合格'] and done['入力会計数']==78
        assert set(done['条件'])=={done['入口']+'__'+base for base in BASES}
    old=read(HERE/'entry_assessment.json')
    assert old['全合格'] and old['完了条件数']==78
    old_rows={(row['entry']['id'],row['base_id'],row['period'],row['symbol']):row for row in old['期間銘柄セル']}
    late=set(read(HERE.parent/'wave_v38/探索条件の固定.json')['後半7セッション'])
    rows=[]
    pairs=[]
    session_pairs=[]
    lookup={}
    reference_paths=[HERE/'warm_complete.json',HERE/'entry_assessment.json']
    checked_legs=0
    for entry in specs:
        done_path=HERE/'entry_completed'/(entry['id']+'.json')
        done=read(done_path)
        assert done in complete['完了']
        reference_paths.append(done_path)
        for base in BASES:
            identifier=entry['id']+'__'+base
            summary_path=HERE/'entry_summaries'/(identifier+'.json')
            session_path=HERE/'entry_sessions'/(identifier+'.json.gz')
            ledger_path=HERE/'entry_ledgers'/(identifier+'.json.gz')
            summary=read(summary_path)
            sessions=read(session_path)
            ledgers=read(ledger_path)
            assert summary['全合格'] and summary['id']==identifier and summary['entry']==entry and summary['base_id']==base
            assert len(sessions)==26
            own,legs=independent_sessions(ledgers,sessions)
            checked_legs+=legs
            reference_paths.extend((summary_path,session_path,ledger_path))
            for period in ('all_symbols','symbols'):
                for symbol in SYMBOLS:
                    value=summary[period][symbol]
                    selected=[r for (session,sym),r in own.items() if sym==symbol and (period=='all_symbols' or session in late)]
                    assert len(selected)==(13 if period=='all_symbols' else 7)
                    for column in ('gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units','closed_units'):
                        equal(sum(r[column] for r in selected),value[column])
                    top2=sorted([profit for r in selected for profit in r['cycle_values'] if profit>0],reverse=True)[:2]
                    removed=value['net_yen']-sum(top2)
                    payoff=(value['gross_profit_yen']/value['profit_units'])/(value['gross_loss_yen']/value['loss_units']) if value['profit_units'] and value['loss_units'] and value['gross_loss_yen'] else None
                    if payoff is not None:
                        equal(payoff,value['average_unit_payoff'])
                    else:
                        assert value['average_unit_payoff'] is None
                    row=dict(id=identifier,entry=entry,base_id=base,period=period,symbol=symbol,
                        top2_removed=float(removed),基礎合格=passing(value['net_yen'],payoff,removed),**value)
                    rows.append(row)
                    lookup[entry['id'],base,period,symbol]=row
                    prior=old_rows[entry['reset']['id'],base,period,symbol]
                    pairs.append(dict(id=identifier,reset_id=prior['id'],base_id=base,period=period,symbol=symbol,
                        暖機収支円=value['net_yen'],初期化収支円=prior['net_yen'],差収支円=value['net_yen']-prior['net_yen'],
                        暖機DD円=value['drawdown_yen'],初期化DD円=prior['drawdown_yen'],差DD円=value['drawdown_yen']-prior['drawdown_yen'],
                        暖機枚平均比=payoff,初期化枚平均比=prior['average_unit_payoff'],暖機上位2除外円=float(removed),
                        初期化上位2除外円=prior['top2_removed'],暖機基礎合格=row['基礎合格'],初期化基礎合格=prior['基礎合格']))
            reset_path=HERE/'entry_sessions'/(entry['reset']['id']+'__'+base+'.json.gz')
            reset_rows={(r['session'],r['symbol']):r for r in read(reset_path)}
            reference_paths.append(reset_path)
            for row in sessions:
                prior=reset_rows[row['session'],row['symbol']]
                session_pairs.append(dict(id=identifier,reset_id=entry['reset']['id']+'__'+base,
                    session=row['session'],symbol=row['symbol'],base_id=base,
                    暖機利益円=row['gross_profit_yen'],暖機損失円=row['gross_loss_yen'],暖機収支円=row['net_yen'],
                    初期化利益円=prior['gross_profit_yen'],初期化損失円=prior['gross_loss_yen'],初期化収支円=prior['net_yen'],
                    差収支円=row['net_yen']-prior['net_yen'],差利益円=row['gross_profit_yen']-prior['gross_profit_yen'],
                    差損失円=row['gross_loss_yen']-prior['gross_loss_yen'],
                    暖機勝枚数=row['profit_units'],暖機負枚数=row['loss_units'],暖機同値枚数=row['zero_units'],
                    初期化勝枚数=prior['profit_units'],初期化負枚数=prior['loss_units'],初期化同値枚数=prior['zero_units']))
    regions=[]
    for peer in (False,True):
        for short in (False,True):
            members=[entry['id'] for entry in specs if entry['reset']['peer_confirm']==peer and entry['reset']['short_confirm']==short]
            assert len(members)==3
            for base in BASES:
                group=[lookup[identifier,base,period,symbol] for identifier in members for period in ('all_symbols','symbols') for symbol in SYMBOLS]
                regions.append(dict(peer=peer,short=short,base_id=base,members=members,
                    全12セル合格=all(row['基礎合格'] for row in group),
                    不合格セル=[dict(entry=row['entry']['id'],period=row['period'],symbol=row['symbol'],
                        net_yen=row['net_yen'],payoff=row['average_unit_payoff'],top2_removed=row['top2_removed'])
                        for row in group if not row['基礎合格']]))
    assert len(rows)==144 and len(pairs)==144 and len(session_pairs)==936 and len(regions)==12
    for path,digest in protocol['参照SHA256'].items():
        assert sha(ROOT/path)==digest,path
    references={path.relative_to(ROOT).as_posix():sha(path) for path in reference_paths}
    return dict(全合格=True,完了条件数=36,期間銘柄セル=rows,主時計領域=regions,
        初期化との期間差=pairs,初期化とのセッション差=session_pairs,
        独立検算=dict(全合格=True,価格方向数量からの返済脚数=checked_legs,入力数=936,
            gross_net_units_top2を別計算=True,DDは完了会計値を使用=True),
        参照SHA256=references,判定規則SHA256=sha(HERE/'暖機判定規則.json'),新ナイト使用=False)


def main() -> None:
    """機能: 規則を固定し、全36完備時にだけ暖機評価を生成する。

    引数: --freeze (bool) は規則保存だけ。返り値: なし (None)。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--freeze',action='store_true')
    args=parser.parse_args()
    protocol=freeze()
    if args.freeze:
        print('暖機評価の基準を固定しました。経済結果未読。',flush=True)
        return
    result=assess(protocol)
    save(HERE/'warm_assessment.json',result)
    print(json.dumps(dict(全合格=True,条件数=36,合格領域=[{k:v for k,v in row.items() if k not in ('members','不合格セル')}
        for row in result['主時計領域'] if row['全12セル合格']]),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
