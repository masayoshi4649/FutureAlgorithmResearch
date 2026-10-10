"""新戦略収支を読まず、完備ゲートの局所APIへ人工破損を投入する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
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


def main() -> None:
    """機能: 163対象のパス・7成果・26区間・8波・配列・金額を人工で検査する。

    引数: なし。返り値: なし (None)。対象設計以外の新戦略成果は読まない。
    """
    specs = target.runner.design.catalog()+target.runner.design.supplementary()
    assert len(specs) == len({s['id'] for s in specs}) == 163
    assert sum(s['role'] != 'supplementary' for s in specs) == 35
    assert sum(s['role'] == 'supplementary' for s in specs) == 128
    assert sum(target.runner.legacy_id(s) is not None for s in specs) == 6
    all_paths = set()
    for spec in specs:
        paths = target.required(spec)
        assert len(paths) == 7 and not (paths & all_paths); all_paths |= paths
        record = dict(id=spec['id'], 全合格=True, 探索固定SHA256='a'*64, 全入力数=26,
                      因果入力数=4, 旧単一窓一致入力数=26 if target.runner.legacy_id(spec) else 0,
                      出力SHA256={p:'b'*64 for p in paths})
        accepted('完了正常/'+spec['id'], lambda s=spec,r=record: target.record_check(s,r,'a'*64))
    assert len(all_paths) == 1141
    spec = specs[0]
    normal = dict(id=spec['id'], 全合格=True, 探索固定SHA256='a'*64, 全入力数=26,
                  因果入力数=4, 旧単一窓一致入力数=26, 出力SHA256={p:'b'*64 for p in target.required(spec)})
    changes = [('別ID','id','未知'), ('偽合格','全合格',1), ('固定SHA','探索固定SHA256','c'*64),
               ('入力欠落','全入力数',25), ('因果欠落','因果入力数',3),
               ('旧一致不足','旧単一窓一致入力数',25), ('旧一致偽型','旧単一窓一致入力数',26.)]
    for label, field, value in changes:
        bad = deepcopy(normal); bad[field] = value
        rejected(label, lambda b=bad: target.record_check(spec,b,'a'*64))
    for field in normal:
        bad = deepcopy(normal); del bad[field]
        rejected('完了必須欠落/'+field, lambda b=bad: target.record_check(spec,b,'a'*64))
    for label, operation in (
        ('成果1欠落', lambda v:v.pop(next(iter(v)))),
        ('成果余分', lambda v:v.update({'work/wave_v44/未知.json':'b'*64})),
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
    # ----------------------------------------
    # 統合コードが局所検査と前後SHA確認を実際に呼ぶことを構文から確認する。
    code=(HERE/'complete.py').read_text(encoding='utf-8');tree=ast.parse(code)
    main_body=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='complete')
    calls={n.func.id for n in ast.walk(main_body) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
    assert {'record_check','keyed','wave_check','array_check','money_check'} <= calls
    assert "proof['原本行数']==fixed['原本行数']['|'.join(key)]" in code
    assert code.count("runner.verify(fixed['参照資料SHA256'])")>=2 and code.count('runner.verify(references)')>=2
    assert '(163,4238,652,156,1304)' in code
    sources=[Path(__file__),HERE/'complete.py',HERE/'prepare.py',HERE/'runner.py',HERE/'design.py']
    value=dict(全合格=True,新実相場損益=False,新売買再生=False,API取得数=0,
               主条件数=35,補助条件数=128,全条件数=163,必須成果数=1141,
               全26旧一致対象数=6,旧一致入力数=156,波一意数=8,
               正常人工数=sum(not r['不正資料'] for r in RESULTS),不正拒否数=sum(r['不正資料'] for r in RESULTS),
               結果=RESULTS,統合コード読取=True,実成果の全完備未実施=True,
               参照資料SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (HERE/'check_complete.json').write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(f"人工正常{value['正常人工数']}・不正拒否{value['不正拒否数']}が全合格。新PnL未読。",flush=True)


if __name__=='__main__':main()
