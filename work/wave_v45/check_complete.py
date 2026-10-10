"""新戦略収支を読まず、完備ゲートの局所APIへ人工破損を投入する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from unittest.mock import patch
from pathlib import Path

import numpy as np
import complete as target

HERE, ROOT = target.HERE, target.ROOT
RESULTS = []


def accepted(name: str, function) -> None:
    """機能: 正常な人工資料が完備判定を通過することを記録する。

    引数: name (str)、function (callable)。返り値: なし (None)。
    """
    function(); RESULTS.append(dict(検査=name, 不正資料=False, 合格=True))


def rejected(name: str, function) -> None:
    """機能: 人工破損を受け入れた場合に検査全体を停止する。

    引数: name (str)、function (callable)。返り値: なし (None)。
    """
    try: function()
    except (AssertionError, KeyError, TypeError, ValueError, OverflowError):
        RESULTS.append(dict(検査=name, 不正資料=True, 合格=True)); return
    raise AssertionError('拒否されない人工不正: '+name)


def array(value: np.ndarray) -> dict:
    """機能: 人工配列の形状・型・全バイト指紋を作る。

    引数: value (ndarray)。返り値: 指紋 (dict)。
    """
    return dict(shape=list(value.shape), dtype=value.dtype.str,
                SHA256=hashlib.sha256(value.tobytes()).hexdigest())


def ledger() -> dict:
    """機能: 金額・枚数を手計算できる保存配列を作る。

    引数: なし。返り値: 人工台帳 (dict)。新注文器は呼ばない。
    """
    widths = dict(trades=11, cycles=10, orders=8, curve=8, atr_curve=12, prepare_events=7,
                  entry_preparations=4, control_curve=20, slot_curve=5, slot_events=11,
                  adjustment_events=11, budget_events=8, branch_events=10, branch_curve=4,
                  plans=37, execution_plans=37)
    data = {name: np.zeros((1, widths[name]), np.float64) if name != 'stats' else np.zeros(11, np.float64)
            for name in set(target.runner.FIELDS) | set(target.runner.reference.EXPECTED_SHADOW_FIELDS)}
    data['orders'] = np.zeros((2, 8), np.float64)
    data['trades'] = np.array([[0,0,1,2,100,103,1,3,0,2,6], [1,1,-1,1,105,107,4,6,0,1,-2],
                               [2,2,1,1,100,100,7,8,0,9,0]], np.float64)
    return dict(**{name:data[name].tolist() for name in target.runner.STORED},
                shadow_cycles=data['cycles'].tolist(), shadow_orders=data['orders'].tolist(),
                result_fingerprints={name:array(data[name]) for name in target.runner.FIELDS},
                shadow_fingerprints={name:array(data[name]) for name in target.runner.reference.EXPECTED_SHADOW_FIELDS},
                config=dict(point_value=1000., audit_cap=10))


def reuse_tests(specs: list[dict]) -> None:
    """機能: 既知11条件の由来・不変仕様・全成果接続へ人工破損を投入する。

    引数: specs(list[dict])。返り値: なし(None)。読取・指紋関数を人工資料へ置換する。
    """
    prepare=target.prepare
    originals={s['id']:s for s in target.runner.design.previous()['conditions']}
    known=[s for s in specs if s['id'] in prepare.REUSED_IDS]
    assert len(known)==11 and set(prepare.REUSED_IDS)==set(target.runner.design.KNOWN_IDS)
    for spec in known:
        accepted('既知全仕様/'+spec['id'],lambda s=spec:prepare.reuse_spec_check(s,originals[s['id']]))
    spec=next(s for s in known if s['id']=='G150_F50_N1__V000')
    original=originals[spec['id']]
    metadata=deepcopy(spec);metadata['role']='別の説明';metadata['primary']=not metadata['primary']
    accepted('主案と役割だけの変更',lambda:prepare.reuse_spec_check(metadata,original))
    for field in spec:
        if field in ('primary','role'):continue
        damaged=deepcopy(spec);damaged[field]='改変'
        rejected('経済仕様変更/'+field,lambda d=damaged:prepare.reuse_spec_check(d,original))
    for label,operation in (
        ('入れ子の減量率',lambda d:d['policy'].update(reduce_fraction=.25)),
        ('数量回数',lambda d:d['policy'].update(max_reductions=3)),
        ('仕様追加',lambda d:d.update(隠れた規則=True)),
        ('仕様欠落',lambda d:d.pop('gate_reference')),
        ('数値と真偽の混同',lambda d:d.update(entry_scale=True)),
        ('価格数値NaN',lambda d:d.update(gate_threshold_atr=float('nan'))),
        ('主案偽型',lambda d:d.update(primary=1)),
        ('役割偽型',lambda d:d.update(role=1))):
        damaged=deepcopy(spec);operation(damaged)
        rejected(label,lambda d=damaged:prepare.reuse_spec_check(d,original))
    # ----------------------------------------
    # 11条件の旧完備→旧completed→7成果の経路を、実損益なしで組み立てる。
    blobs={}; digests={}; old_sha='e'*64
    proof=dict(全合格=True,探索固定SHA256=old_sha,全条件数=163,全入力数=4238,
               因果入力数=652,旧単一窓一致入力数=156,出力SHA256={})
    for current in known:
        identifier=current['id'];record_path=prepare.PRIOR/'completed'/(identifier+'.json')
        outputs={}
        for folder,suffix in target.FOLDERS:
            path=prepare.PRIOR/folder/(identifier+suffix)
            relative=path.relative_to(ROOT).as_posix()
            sha=hashlib.sha256(relative.encode()).hexdigest();digests[path]=sha;outputs[relative]=sha
        old_record=dict(id=identifier,全合格=True,探索固定SHA256=old_sha,全入力数=26,因果入力数=4,
                        全原本行会計数=100,旧単一窓一致入力数=26 if target.runner.legacy_id(current) else 0,
                        出力SHA256=outputs)
        blobs[record_path]=old_record;digests[record_path]=hashlib.sha256(str(record_path).encode()).hexdigest()
        proof['出力SHA256'].update(outputs)
        proof['出力SHA256'][record_path.relative_to(ROOT).as_posix()]=digests[record_path]
        blobs[prepare.PRIOR/'summaries'/(identifier+'.json')]=dict(id=identifier,spec=originals[identifier],
            探索固定SHA256=old_sha,all_symbols={'TOPIX':{'net_yen':123.}},symbols={},wave_passes=3)

    def fake_verify(values: dict) -> None:
        """機能: 人工保存物の指紋表を厳密に照合する。

        引数: values(dict)。返り値: なし(None)。
        """
        for name,sha in values.items():assert digests[ROOT/name]==sha

    previous=dict(conditions=list(originals.values()),supplementary=[])
    with patch.object(target.runner,'read',side_effect=lambda p:deepcopy(blobs[p])), \
         patch.object(target.runner,'digest',side_effect=lambda p:digests[p]), \
         patch.object(target.runner,'verify',side_effect=fake_verify):
        manifests=prepare.inheritance(specs,previous,proof,old_sha)
        accepted('旧11全8資料の連結',lambda:prepare.inheritance(specs,previous,proof,old_sha))
        rejected('既知11の欠落',lambda:prepare.inheritance([s for s in specs if s['id']!=spec['id']],previous,proof,old_sha))
        rejected('既知11の重複',lambda:prepare.inheritance(specs+[spec],previous,proof,old_sha))
        bad=deepcopy(proof);bad['出力SHA256'].pop(next(iter(bad['出力SHA256'])))
        rejected('旧完備から実物欠落',lambda:prepare.inheritance(specs,previous,bad,old_sha))
        bad=deepcopy(proof);bad['探索固定SHA256']='f'*64
        rejected('旧完備と固定の断絶',lambda:prepare.inheritance(specs,previous,bad,old_sha))
        source=manifests[spec['id']]
        prior_record=blobs[ROOT/source['completed']]
        outputs={}
        for folder,suffix in target.FOLDERS:
            now=(target.destination(spec)/folder/(spec['id']+suffix)).relative_to(ROOT).as_posix()
            before=(prepare.PRIOR/folder/(spec['id']+suffix)).relative_to(ROOT).as_posix()
            outputs[now]=source['出力SHA256'][before] if folder!='summaries' else 'a'*64
        record=dict(id=spec['id'],全合格=True,全入力数=26,因果入力数=4,全原本行会計数=100,
                    旧単一窓一致入力数=prior_record['旧単一窓一致入力数'],探索固定SHA256='a'*64,
                    出力SHA256=outputs,既知成果引継ぎ=True,新売買再生=False,reuse_source=source)
        prior_summary=blobs[prepare.PRIOR/'summaries'/(spec['id']+'.json')]
        payload=dict(summaries=dict(prior_summary,spec=spec,探索固定SHA256='a'*64))
        fixed=dict(既知再利用=manifests)
        accepted('旧六資料と集計メタの厳密引継ぎ',lambda:target.reuse_check(spec,record,payload,fixed))
        for folder,suffix in target.FOLDERS:
            if folder=='summaries':continue
            changed=deepcopy(record)
            name=(target.destination(spec)/folder/(spec['id']+suffix)).relative_to(ROOT).as_posix()
            changed['出力SHA256'][name]='9'*64
            rejected('引継バイト変更/'+folder,lambda c=changed:target.reuse_check(spec,c,payload,fixed))
        for label,operation in (
            ('集計金額',lambda d:d['all_symbols']['TOPIX'].update(net_yen=124.)),
            ('波数',lambda d:d.update(wave_passes=4)),
            ('集計余分',lambda d:d.update(後付け=True)),
            ('集計不足',lambda d:d.pop('symbols')),
            ('集計旧仕様残留',lambda d:d.update(spec=original)),
            ('集計旧固定残留',lambda d:d.update(探索固定SHA256=old_sha))):
            changed=deepcopy(payload);operation(changed['summaries'])
            rejected(label,lambda c=changed:target.reuse_check(spec,record,c,fixed))
        for label,operation in (
            ('元資料SHA変更',lambda d:d['reuse_source']['出力SHA256'].update({source['completed']:'0'*64})),
            ('元条件変更',lambda d:d['reuse_source']['spec'].update(gate_threshold_atr=1.8)),
            ('元参照欠落',lambda d:d.pop('reuse_source')),
            ('旧会計行数変更',lambda d:d.update(全原本行会計数=101)),
            ('旧因果数変更',lambda d:d.update(因果入力数=3))):
            changed=deepcopy(record);operation(changed)
            rejected(label,lambda c=changed:target.reuse_check(spec,c,payload,fixed))
        fresh=next(s for s in specs if s['id'] not in prepare.REUSED_IDS)
        accepted('新規を旧成果と混同しない',lambda:target.reuse_check(fresh,dict(reuse_source=None),{},fixed))
        rejected('新規へ旧成果付替え',lambda:target.reuse_check(fresh,dict(reuse_source=source),{},fixed))


def main() -> None:
    """機能: 153対象のパス・7成果・26区間・8波・配列・金額を人工で検査する。

    引数: なし。返り値: なし (None)。対象設計以外の新戦略成果は読まない。
    """
    specs = target.runner.design.catalog()+target.runner.design.supplementary()
    assert len(specs) == len({s['id'] for s in specs}) == 153
    assert sum(s['role'] != 'supplementary' for s in specs) == 25
    assert sum(s['role'] == 'supplementary' for s in specs) == 128
    assert sum(target.runner.legacy_id(s) is not None for s in specs) == 6
    all_paths = set()
    for spec in specs:
        paths = target.required(spec)
        assert len(paths) == 7 and not (paths & all_paths); all_paths |= paths
        record = dict(id=spec['id'], 全合格=True, 探索固定SHA256='a'*64, 全入力数=26,
                      因果入力数=4, 全原本行会計数=100, 既知成果引継ぎ=spec['id'] in target.prepare.REUSED_IDS,
                      新売買再生=spec['id'] not in target.prepare.REUSED_IDS,
                      reuse_source={} if spec['id'] in target.prepare.REUSED_IDS else None,
                      旧単一窓一致入力数=26 if target.runner.legacy_id(spec) else 0,
                      出力SHA256={p:'b'*64 for p in paths})
        accepted('完了正常/'+spec['id'], lambda s=spec,r=record: target.record_check(s,r,'a'*64))
    assert len(all_paths) == 1071
    spec = specs[0]
    normal = dict(id=spec['id'], 全合格=True, 探索固定SHA256='a'*64, 全入力数=26,
                  因果入力数=4, 全原本行会計数=100, 既知成果引継ぎ=True, 新売買再生=False, reuse_source={}, 旧単一窓一致入力数=26, 出力SHA256={p:'b'*64 for p in target.required(spec)})
    changes = [('別ID','id','未知'), ('偽合格','全合格',1), ('固定SHA','探索固定SHA256','c'*64),
               ('入力欠落','全入力数',25), ('因果欠落','因果入力数',3),
               ('旧一致不足','旧単一窓一致入力数',25), ('旧一致偽型','旧単一窓一致入力数',26.),
               ('再利用偽旗','既知成果引継ぎ',False),('再利用偽型','既知成果引継ぎ',1),
               ('再実行偽旗','新売買再生',True),('元資料欠落','reuse_source',None),
               ('原本行数ゼロ','全原本行会計数',0),('原本行数偽型','全原本行会計数',100.)]
    for label, field, value in changes:
        bad = deepcopy(normal); bad[field] = value
        rejected(label, lambda b=bad: target.record_check(spec,b,'a'*64))
    for field in normal:
        bad = deepcopy(normal); del bad[field]
        rejected('完了必須欠落/'+field, lambda b=bad: target.record_check(spec,b,'a'*64))
    for label, operation in (
        ('成果1欠落', lambda v:v.pop(next(iter(v)))),
        ('成果余分', lambda v:v.update({'work/wave_v45/未知.json':'b'*64})),
        ('成果別条件', lambda v:v.update({v.pop(next(iter(v))):'b'*64})),
        ('SHA短縮', lambda v:v.update({next(iter(v)):'b'*63})),
        ('SHA非16進', lambda v:v.update({next(iter(v)):'g'*64})),
        ('SHA非文字', lambda v:v.update({next(iter(v)):0}))):
        bad = deepcopy(normal); operation(bad['出力SHA256'])
        rejected(label, lambda b=bad: target.record_check(spec,b,'a'*64))
    for name in ('../例','例/名前','例\\名前',''):
        rejected('不正ID/'+name, lambda n=name:target.required(dict(spec,id=n)))
    # ----------------------------------------
    # 元26組と固定波を、重複で件数だけ満たしても通さない。
    names = [f'人工区間{i:02d}' for i in range(13)]
    keys = {(s,k) for s in names for k in target.runner.old.SYMBOLS}
    rows = [dict(session=s,symbol=k) for s,k in sorted(keys)]
    accepted('全26一意', lambda:target.keyed(rows,keys))
    for label, bad in (('区間不足',rows[:-1]),('区間重複',rows[:-1]+[rows[0]]),
                       ('区間余分',rows+[rows[0]]),('区間なし',[]),
                       ('区間未知',rows[:-1]+[dict(session='未知',symbol='TOPIX')])):
        rejected(label,lambda b=bad:target.keyed(b,keys))
    episodes = [dict(id=f'E{i}',session=names[i],side=1 if i%2 else -1,
                     start='2026-09-21T09:00:00+09:00',end='2026-09-21T10:00:00+09:00',name=f'人工波{i}') for i in range(4)]
    waves = [dict(wave=e['id'],session=e['session'],symbol=s,method=spec['id'],波方向=e['side'],
                  開始=e['start'],終了=e['end'],波名=e['name'],区間分=60.,正方向ネット保有分=20.,
                  正方向ネット20分目安達成=True) for e in episodes for s in target.runner.old.SYMBOLS]
    accepted('波8一意',lambda:target.wave_check(spec['id'],waves,episodes))
    for label,field,value in [('波方式','method','未知'),('波方向','波方向',0),('波時刻','開始','未知'),
                              ('波名','波名','未知'),('波区間','区間分',59.),('波NaN','区間分',float('nan')),
                              ('保有NaN','正方向ネット保有分',float('nan')),('保有負','正方向ネット保有分',-1.),
                              ('保有超過','正方向ネット保有分',61.),('20分偽判定','正方向ネット20分目安達成',False),
                              ('20分偽型','正方向ネット20分目安達成',1)]:
        bad=deepcopy(waves);bad[0][field]=value
        rejected(label,lambda b=bad:target.wave_check(spec['id'],b,episodes))
    for label,bad in [('波不足',waves[:-1]),('波重複',waves[:-1]+[waves[0]]),('波余分',waves+[waves[0]])]:
        rejected(label,lambda b=bad:target.wave_check(spec['id'],b,episodes))
    for minutes, passed in ((0.,False),(19.999,False),(20.-5e-10,True),(20.,True),(60.,True)):
        value=deepcopy(waves);value[0]['正方向ネット保有分']=minutes;value[0]['正方向ネット20分目安達成']=passed
        accepted('20分境界/'+str(minutes),lambda v=value:target.wave_check(spec['id'],v,episodes))
    # ----------------------------------------
    # 保存された型・形状・バイトと、返済価格からの金額／枚数を分けて照合する。
    book=ledger();accepted('保存配列正常',lambda:target.array_check(book))
    for field in target.runner.STORED:
        bad=deepcopy(book)
        if field=='stats':bad[field][0]=100
        else:bad[field][0][0]=100
        rejected('配列値破損/'+field,lambda b=bad:target.array_check(b))
    for field in ('result_fingerprints','shadow_fingerprints'):
        bad=deepcopy(book);bad[field].pop(next(iter(bad[field])))
        rejected('指紋対象欠落/'+field,lambda b=bad:target.array_check(b))
    bad=deepcopy(book);bad['result_fingerprints']['orders']['shape']=[4,4]
    rejected('同要素数の誤shape',lambda:target.array_check(bad))
    for label, field, metadata, value in (
        ('型をfloat32へ','orders','dtype','<f4'),
        ('型名を別形式へ','orders','dtype','float64'),
        ('shape列幅違い','trades','shape',[3,10]),
        ('shape実行数違い','orders','shape',[1,8]),
        ('shape型浮動小数','orders','shape',[2.,8]),
        ('shape負数','orders','shape',[-2,8]),
        ('stats二次元','stats','shape',[1,11]),
        ('stats要素不足','stats','shape',[10])):
        bad=deepcopy(book);bad['result_fingerprints'][field][metadata]=value
        rejected(label,lambda b=bad:target.array_check(b))
    empty=deepcopy(book)
    for field in target.runner.STORED:
        if field=='stats': continue
        width=book['result_fingerprints'][field]['shape'][1]
        empty[field]=[];empty['result_fingerprints'][field]=array(np.empty((0,width),np.float64))
    for field in ('orders','cycles'):
        width=book['shadow_fingerprints'][field]['shape'][1]
        empty['shadow_'+field]=[];empty['shadow_fingerprints'][field]=array(np.empty((0,width),np.float64))
    accepted('空台帳の既定列幅復元',lambda:target.array_check(empty))
    bad=deepcopy(empty);bad['result_fingerprints']['orders']['shape']=[0,7]
    rejected('空台帳の列幅偽装',lambda:target.array_check(bad))
    money=dict(gross_profit_yen=6000.,gross_loss_yen=2000.,net_yen=4000.,profit_units=2,
               loss_units=1,zero_units=1,closed_units=4,max_long=2,max_short=1)
    accepted('価格式の金額と枚数',lambda:target.money_check(book,money))
    for field in ('gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units','closed_units'):
        bad=deepcopy(money);bad[field]+=1
        rejected('金額枚数破損/'+field,lambda b=bad:target.money_check(book,b))
        bad=deepcopy(money);bad[field]=float('nan')
        rejected('金額枚数NaN/'+field,lambda b=bad:target.money_check(book,b))
    for field in ('max_long','max_short'):
        bad=deepcopy(money);bad[field]=11
        rejected('上限超過/'+field,lambda b=bad:target.money_check(book,b))
    reuse_tests(specs)
    # ----------------------------------------
    # 統合コードが局所検査と前後SHA確認を実際に呼ぶことを構文から確認する。
    code=(HERE/'complete.py').read_text(encoding='utf-8');tree=ast.parse(code)
    main_body=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='complete')
    calls={n.func.id for n in ast.walk(main_body) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
    assert {'record_check','keyed','wave_check','array_check','money_check','reuse_check'} <= calls
    assert "proof['原本行数']==fixed['原本行数']['|'.join(key)]" in code
    assert code.count("runner.verify(fixed['参照資料SHA256'])")>=2 and code.count('runner.verify(references)')>=2
    assert '(153,3978,612,156,1224)' in code
    sources=[Path(__file__),HERE/'complete.py',HERE/'prepare.py',HERE/'runner.py',HERE/'design.py']
    value=dict(全合格=True,新実相場損益=False,新売買再生=False,API取得数=0,
               主条件数=25,補助条件数=128,全条件数=153,必須成果数=1071,
               既知引継条件数=11,新規再生条件数=142,既知再利用人工全合格=True,
               全26旧一致対象数=6,旧一致入力数=156,波一意数=8,
               正常人工数=sum(not r['不正資料'] for r in RESULTS),不正拒否数=sum(r['不正資料'] for r in RESULTS),
               結果=RESULTS,統合コード読取=True,実成果の全完備未実施=True,
               参照資料SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (HERE/'check_complete.json').write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(f"人工正常{value['正常人工数']}・不正拒否{value['不正拒否数']}が全合格。新PnL未読。",flush=True)


if __name__=='__main__':main()
