"""売買頻度と出口改善を、利益の取り逃し・損失・場ごとの差へ分ける。"""

from collections import defaultdict
import argparse
import json
import math
import pickle

from support import WORK, digest, save


BASE='E01_G_U'
SYMBOLS=('TOPIX','NK225')


def read(path):
    """
    機能: 完了した日本語JSONを読み込む。
    引数: path (Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def per_session(base, changed, symbol):
    """
    機能: 同じ30場の差を集計し、最大改善場を除いても改善が残るか確認する。
    引数: base/changed (dict)、symbol (str)。
    返り値: dictの全場差と集中度。未来の売買条件に使わない。
    """
    old={r['session']:r for r in base['rows'] if r['symbol']==symbol}
    new={r['session']:r for r in changed['rows'] if r['symbol']==symbol}
    assert old.keys()==new.keys()
    rows=[dict(セッション=s,元収支=old[s]['net'],新収支=new[s]['net'],差=new[s]['net']-old[s]['net'],
               元組数=old[s]['campaigns'],新組数=new[s]['campaigns']) for s in sorted(old)]
    maximum=max(rows,key=lambda r:r['差'])
    worst=max(rows,key=lambda r:-r['差'])
    differences=math.fsum(r['差'] for r in rows)
    by_clock={kind:math.fsum(r['差'] for r in rows if r['セッション'].endswith(kind)) for kind in ('Day','Night')}
    return dict(改善場数=sum(r['差']>1e-7 for r in rows),悪化場数=sum(r['差']<-.0000001 for r in rows),
        同値場数=sum(abs(r['差'])<=1e-7 for r in rows),差引改善=differences,
        最大改善場=maximum,最大悪化場=worst,最大改善場を除く差引改善=differences-maximum['差'],
        昼夜の差引改善=by_clock,全30=rows)


def groups(ledgers,symbol):
    """
    機能: 親組の全決済脚を合算し、同一の入口行・方向で対応可能にする。
    引数: ledgers (dict)、symbol (str)。
    返り値: dict[tuple,dict]の組純収支・利益損失・料。
    """
    result={}
    for (session,product),ledger in ledgers.items():
        if product!=symbol:
            continue
        positions=defaultdict(list)
        for trade in ledger['net_trades']:
            positions[int(trade['組'])].append(trade)
        for cid,trades in positions.items():
            first=trades[0]
            key=(session,int(first['新規行']),int(first['方向']))
            assert key not in result
            result[key]=dict(組=cid,収支=math.fsum(t['収支'] for t in trades),
                料金=math.fsum(t['手数料'] for t in trades),返済行=max(t['返済行'] for t in trades))
    return result


def matching(base, changed, symbol):
    """
    機能: 同入口の出口変更・旧組の消失・追加入口の損益に差額を分解する。
    引数: base/changed (dictの保存台帳)、symbol (str)。
    返り値: dict。経路全体の対照であり追加売買だけの独立効果とは呼ばない。
    """
    old,new=groups(base,symbol),groups(changed,symbol)
    shared=old.keys()&new.keys()
    removed=old.keys()-new.keys()
    added=new.keys()-old.keys()
    sections={}
    for title,keys,account in (
        ('同入口だった旧黒字組', [k for k in shared if old[k]['収支']>0], lambda k:new[k]['収支']-old[k]['収支']),
        ('同入口だった旧赤字組', [k for k in shared if old[k]['収支']<0], lambda k:new[k]['収支']-old[k]['収支']),
        ('同入口だった旧同額組', [k for k in shared if old[k]['収支']==0], lambda k:new[k]['収支']-old[k]['収支']),
        ('消えた旧黒字組', [k for k in removed if old[k]['収支']>0], lambda k:-old[k]['収支']),
        ('消えた旧赤字組', [k for k in removed if old[k]['収支']<0], lambda k:-old[k]['収支']),
        ('消えた旧同額組', [k for k in removed if old[k]['収支']==0], lambda k:-old[k]['収支']),
        ('追加の黒字組', [k for k in added if new[k]['収支']>0], lambda k:new[k]['収支']),
        ('追加の赤字組', [k for k in added if new[k]['収支']<0], lambda k:new[k]['収支']),
        ('追加の同額組', [k for k in added if new[k]['収支']==0], lambda k:new[k]['収支'])):
        sections[title]=dict(組数=len(keys),差額寄与=math.fsum(account(k) for k in keys))
    difference=math.fsum(v['収支'] for v in new.values())-math.fsum(v['収支'] for v in old.values())
    assert abs(math.fsum(v['差額寄与'] for v in sections.values())-difference)<1e-5
    return dict(元組数=len(old),新組数=len(new),共通入口数=len(shared),内訳=sections,差引改善=difference,
                注記='入口行と方向が同じ組だけを対応付け。追加と消失には先行する出口による後続経路変更も含まれる。')


def main():
    """
    機能: 全20条件の頻度と場集中、および固定主仮説と参考首位の組対応を保存する。
    引数: なし。
    返り値: None。新戦略・追加条件の再生や選び直しを行わない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--phase2',action='store_true');args=parser.parse_args()
    home=WORK/'phase2' if args.phase2 else WORK
    fixed=read(home/'事前固定.json')
    packets={c['id']:read(home/'observed/results'/(c['id']+'.json')) for c in fixed['catalog']}
    homes={ident:home for ident in packets}
    if args.phase2:
        packets[BASE]=read(WORK/'observed/results'/f'{BASE}.json')
        homes[BASE]=WORK
    baseline=packets[BASE]
    ranked=sorted(packets,key=lambda i:min(packets[i]['periods']['全30'][s]['net']/packets[i]['periods']['全30'][s]['max_drawdown'] for s in SYMBOLS),reverse=True)
    hypothesis='T3_P1' if args.phase2 else 'T3_A1'
    chosen=list(dict.fromkeys([BASE,hypothesis,ranked[0]]))
    comparisons=[]
    for ident,packet in packets.items():
        product={}
        for symbol in SYMBOLS:
            old=baseline['periods']['全30'][symbol]
            new=packet['periods']['全30'][symbol]
            delta={k:new[k]-old[k] for k in ('net','gross','fees','campaign_profit','campaign_loss','campaigns','positive_sessions','max_drawdown')}
            assert abs(delta['net']-(delta['campaign_profit']-delta['campaign_loss']))<1e-5
            assert abs(delta['net']-(delta['gross']-delta['fees']))<1e-5
            product[symbol]=dict(基準との差=delta,元一組平均=old['net']/old['campaigns'],
                新一組平均=new['net']/new['campaigns'],場別=per_session(baseline,packet,symbol),
                期間別差={p:packet['periods'][p][symbol]['net']-baseline['periods'][p][symbol]['net'] for p in ('前16','後14')})
        comparisons.append(dict(条件=ident,商品別=product))
    ledgers={i:pickle.loads((homes[i]/'observed/ledgers'/(i+'.pkl')).read_bytes()) for i in chosen}
    matched={i:{s:matching(ledgers[BASE],ledgers[i],s) for s in SYMBOLS} for i in chosen if i!=BASE}
    save('利確後だけ再参加の取り逃し分解.json' if args.phase2 else '回転増と取り逃しの独立分解.json',
        dict(約定='観測CurrentPrice・手数料後',主仮説=hypothesis,
        参考首位=ranked[0],基準=BASE,親組対応分解=matched,
        **{('追加10条件と基準' if args.phase2 else '全20比較'):comparisons},
        制約='全30場既知の事後診断。取引していない期間の未来利益を実現可能な利益とは扱わない。',
        参照SHA256={str(p.relative_to(WORK)):digest(p) for ident in packets
            for p in [homes[ident]/'observed/results'/(ident+'.json')]}))
    for ident in chosen:
        c=next(c for c in comparisons if c['条件']==ident)
        print(ident,[(s,v['基準との差'],v['場別']['最大改善場を除く差引改善']) for s,v in c['商品別'].items()],flush=True)


if __name__=='__main__':
    main()
