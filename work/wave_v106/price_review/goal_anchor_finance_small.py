"""終端0通知後だけ三つの小JSONを各一読し、264会計・初回境界・最新基準を独立再計算する。"""

from pathlib import Path
import hashlib
import json
import math
import sys

from risk_sizing_finance_small import goal, near


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_size_goal_anchor'
READS={}


def read_once(path: Path) -> tuple[dict,str]:
    """
    機能: 許可された新result/plan/fixedの小JSONを各一読する。
    引数: path(Path)は三つの固定位置のいずれか。
    返り値: tuple[dict,str]は保存値と同bytesSHA256。二読及び別ファイルを拒否する。
    """
    allowed={SOURCE/'finance/結果.json',SOURCE/'試行計画.json',SOURCE/'金融事前固定.json'}
    assert path in allowed and path not in READS
    saved=path.read_bytes(); sha=hashlib.sha256(saved).hexdigest(); READS[path]=sha
    return json.loads(saved.decode('utf-8-sig')),sha


def digest_source(path: Path) -> str:
    """
    機能: 凍結した小Python sourceだけの指紋を確認する。
    引数: path(Path)は新所有source。
    返り値: strはSHA256。packet・ledger・旧金融結果を読まない。
    """
    assert path.suffix=='.py'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric_check(r: dict) -> None:
    """
    機能: 完結親金額、枚数、無取引、料金の小会計を独立確認する。
    引数: r(dict)は同商品一場の保存小会計。
    返り値: None。不活動を勝ちと判定しない。
    """
    assert r['全会計合格'] and r['利益']>=0 and r['損失']>=0
    near(r['利益']-r['損失'],r['収支'])
    assert r['親数']==r['勝ち親']+r['負け親']+r['零親']
    assert r['新規枚数']==r['勝ち枚数']+r['負け枚数']+r['零枚数']
    full=5 if r['symbol']=='TOPIX' else 10
    assert 0<=r['最大買枚数']<=full and 0<=r['最大売枚数']<=full
    assert r['費用']>=0 and r['費用']==int(r['費用'])
    near(r['利益割合'],r['利益']/(r['利益']+r['損失']) if r['利益']+r['損失'] else None)
    near(r['PF'],r['利益']/r['損失'] if r['損失'] else None)
    near(r['平均利益'],r['利益']/r['勝ち親'] if r['勝ち親'] else None)
    near(r['平均損失'],r['損失']/r['負け親'] if r['負け親'] else None)
    if not r['親数']: assert r['新規枚数']==r['費用']==r['注文件数']==r['収支']==r['利益']==r['損失']==0


def boundary_check(b: dict, row: dict, config: dict) -> dict:
    """
    機能: 保存小境界のアンカーq/full・未定義・初fillと停止の因果を確認する。
    引数: b/row/config(dict)は初回境界・小会計・凍結条件。
    返り値: dictは確認可能な系譜。全size_eventsの最初選択を再測定したとは扱わない。
    """
    symbol=row['symbol']; full=5 if symbol=='TOPIX' else 10; budget=5000 if symbol=='TOPIX' else 2000
    anchor=b['anchor']; control=b['停止判断']; first=b['実政策初回新規']
    assert anchor['通常全量']==full and anchor['元利益目標円']==config['profit_goal_yen'][symbol]
    assert b['損失予算円']==control['損失予算']==budget
    if not anchor['成立']:
        for name in ('数量','利益目標円','受理行','受理原seq','受理価格時計','紙上親'): assert anchor[name] is None
        assert b['目標円'] is None and control['目標'] is None and not control['発動']
        assert b['受理行の費用後清算円'] is None and first is None and row['親数']==0
        return dict(成立=False,実初回無し=True,目標円=None)
    q=anchor['数量']; assert type(q) is int and 0<q<=full
    expected=config['profit_ticks']*(500 if symbol=='TOPIX' else 100)*q
    near(anchor['利益目標円'],expected); near(b['目標円'],expected); near(control['目標'],expected)
    assert type(anchor['受理行']) is int and anchor['受理行']>=0 and type(anchor['受理原seq']) is int
    assert type(anchor['紙上親']) is int and anchor['紙上親']>=0 and math.isfinite(anchor['受理価格時計'])
    # 最初受理より前に実新規は無く、受理当行の新規fillも無い。旧影は無償なので清算は0。
    near(b['受理行の費用後清算円'],0.)
    if first is None:
        assert row['親数']==row['注文件数']==0
    else:
        assert 0<=anchor['受理行']<=first['source_row']<first['row']
        assert anchor['受理原seq']<first['raw_seq'] and 0<first['quantity']<=full
        assert first['price']>0 and math.isfinite(first['price']) and row['親数']>0
        # 受理後取消は許されるので、初fill数量又は親が初受理と異なっても否定しない。
    if control['発動']:
        assert control['判断行']>=anchor['受理行'] and control['判断原seq']>=anchor['受理原seq']
        assert control['返済行']>=control['判断行'] and control['返済原seq']>=control['判断原seq']
        assert first is not None and control['以後新規なし'] and not control['未来返済テンプレート参照']
        value=control['判断時清算利益']
        assert (value>=expected if control['種別']=='利益目標' else value<=-budget)
        near(control['実返済後収支'],row['収支'])
        near(control['判断から返済の悪化'],row['収支']-value)
    return dict(成立=True,受理q=q,目標円=expected,受理行=anchor['受理行'],初実数量=None if first is None else first['quantity'],
        受理と初実差=first is not None and (first['source_row']!=anchor['受理行'] or first['quantity']!=q),停止=control['発動'])


def main() -> None:
    """
    機能: root終端0通知を明示条件に三つの小JSONだけを各一読し、264行と最新目標を確認する。
    引数: CLIの--root-terminal-zeroはrootが完了を通知した後だけ指定する。
    返り値: Noneは独立小監査。金融・原板・APIを実行しない。
    """
    assert sys.argv[1:]==['--root-terminal-zero'], 'root終端0通知まで読取を開始しない'
    target=HERE/'goal_anchor_全264小会計と寄与境界及び最新三基準の独立確認.json'; assert not target.exists()
    result,result_sha=read_once(SOURCE/'finance/結果.json'); prepared,plan_sha=read_once(SOURCE/'試行計画.json'); fixed,fixed_sha=read_once(SOURCE/'金融事前固定.json')
    assert result['全合格'] and result['source開始終端一致'] and result['source_SHA256']==fixed['source_SHA256']==prepared['spec']['implementation']
    assert len(result['source_SHA256'])==15
    for p,sha in result['source_SHA256'].items(): assert digest_source(ROOT/p)==sha
    assert fixed['計画SHA256']==plan_sha and result['configs']==fixed['configs']==prepared['spec']['entry']['conditions']
    assert result['case_SHA256']==fixed['case_SHA256']
    assert result['sessions']==fixed['sessions']==prepared['spec']['data']['sessions'] and len(result['sessions'])==33
    assert result['counts']==dict(既input一読=33,新GUengine=132,新政策会計=264,旧数量台帳一読=264)
    assert result['新GUengine']==132 and result['新政策会計']==result['会計口座数']==264
    configs={c['id']:c for c in result['configs']}; calculations={}; boundaries={}; checked=0; contributions=0; identities=0
    for cid,data in result['results'].items():
        config=configs[cid]; rows=data['rows']; assert len(rows)==len(data['ledgers'])==66
        index={(r['session'],r['symbol']):r for r in rows}; assert len(index)==66
        assert set(index)=={(s,p) for s in result['sessions'] for p in ('TOPIX','NK225')}
        for r in rows: metric_check(r); checked+=1
        calculations[cid]={}
        for symbol in ('TOPIX','NK225'):
            subset=[index[s,symbol] for s in result['sessions']]; full=goal(subset)
            removed=sorted([r for r in subset if r['収支']>0],key=lambda r:r['収支'],reverse=True)[:3]
            removed_dates={r['session'] for r in removed}; tail=goal([r for r in subset if r['session'] not in removed_dates])
            front=goal(subset[:16]); back=goal(subset[16:]); calculations[cid][symbol]=dict(全場=full,上位3除外=tail,
                除外場=[r['session'] for r in removed],前16=front,後17=back)
            saved=data['symbols'][symbol]
            for before,after in (('利益','利益'),('損失','損失'),('収支','収支'),('利益割合','金額利益割合'),('PF','PF'),
                ('全場','全場'),('活動場','活動'),('黒字場','黒字'),('赤字場','赤字'),('無取引場','無取引'),('最大場損失','最大赤字')):
                near(saved[before],full[after])
            near(saved['上位3利益場除外収支'],tail['収支'])
            for field in ('親数','勝ち親','負け親','零親','費用','新規枚数','勝ち枚数','負け枚数','零枚数'):
                assert saved[field]==sum(r[field] for r in subset)
            leg=data['actual_leg_symbols'][symbol]; near(leg['利益']-leg['損失'],full['収支']); near(leg['収支'],full['収支'])
            assert leg['親数']==leg['実決済玉数']<=saved['新規枚数'] and leg['親数']==leg['勝ち親']+leg['負け親']+leg['零親']
        reference=fixed['comparisons'][cid]; before={(r['session'],r['symbol']):r for r in reference['rows']}
        assert len(before)==66 and reference['id']==config['baseline_id']
        scenes=result['各場寄与'][cid]; assert len(scenes)==66 and {(r['session'],r['symbol']) for r in scenes}==set(index)
        for d in scenes:
            row=index[d['session'],d['symbol']]; old=before[d['session'],d['symbol']]
            assert d['baseline_id']==reference['id']; near(d['収支変化'],row['収支']-old['収支']); identities+=1
            near(d['収支変化'],d['避けた基準損失']-d['失った基準利益']+d['共通入口の数量/出口差']+d['新たな入口の収支']); identities+=1
            assert d['避けた基準損失']>=0 and d['失った基準利益']>=0
            assert all(p['old_net']>0 and p['new_net']<0 for p in d['元勝ち親が赤字化']); identities+=1; contributions+=1
        for symbol,summary in result['diagnosis'][cid].items():
            selected=[d for d in scenes if d['symbol']==symbol]
            for field in ('収支変化','避けた基準損失','失った基準利益','共通入口の数量/出口差','新たな入口の収支'):
                near(summary[field],sum(r[field] for r in selected))
            assert summary['元勝ち親が赤字化']==sum(len(r['元勝ち親が赤字化']) for r in selected)
        boundary=result['初回受理と費用後目標境界'][cid]
        assert len(boundary)==66 and {(b['session'],b['symbol']) for b in boundary}==set(index)
        boundaries[cid]=[dict(session=b['session'],symbol=b['symbol'],**boundary_check(b,index[b['session'],b['symbol']],config)) for b in boundary]
    assert checked==contributions==264 and identities==792 and sum(len(b) for b in boundaries.values())==264 and len(READS)==3
    combined={cid:dict(両商品合計=sum(v['全場']['収支'] for v in products.values()),
        両商品全基準合格=all(v['全場']['全基準合格'] for v in products.values()),
        両商品上位3除外合格=all(v['上位3除外']['全基準合格'] for v in products.values())) for cid,products in calculations.items()}
    proof=dict(全合格=True,範囲='三小JSONの保存小会計・境界系譜を独立再集計。全264大台帳又は最初イベント集合を再読した検証ではない。',
        source_SHA256={p.relative_to(ROOT).as_posix():sha for p,sha in READS.items()},独立source_SHA256=digest_source(Path(__file__)),
        小JSON各一読=3,小会計=checked,比較寄与行=contributions,寄与観点=identities,初回境界=264,
        新基準=calculations,両商品判定=combined,初回受理境界確認=boundaries,
        留保=['792は264寄与行の三検査観点数。旧比較口座又は独立試行792件ではない。',
              '受理アンカーの最初イベント選択は源・人工で確認済み。小境界だけから未保存の過去イベント不存在を再証明しない。',
              '初受理後取消なら実初回qが異なり得る。目標は最初の受理q由来を維持する。',
              '前16/後17は同じ既知33場の時系列参考で、未知期間検証ではない。',
              '金額比は完結親の総利益/(総利益+総損失)。場内相殺後平均や実部分玉とは別。'],
        金融再実行=0,packet=0,ledger=0,原板=0,NPZ=0,API=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,会計=264,寄与行=264,寄与観点=792,境界=264,
        両商品合格=[cid for cid,p in combined.items() if p['両商品全基準合格']],SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__': main()
