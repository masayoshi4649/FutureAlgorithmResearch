"""新6窓と役割別の公開元乱数だけを監査し、既存列は証跡を継承する。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent/'wave_v37'))
import partial_input_audit as previous
sys.path.insert(0, str(HERE))
import prepare_branch_inputs as prepare
import branch_inputs as adapter

source = prepare.source


def independent_bits(row: np.ndarray, ready: dict, key: tuple, seed: int, role: str) -> np.ndarray:
    """機能: 公開元rawseqへ別実装で固定hashを割り当てる。

    引数: row (ndarray[int64])、ready (dict)、key (tuple)、seed (int)、role (str)。
    返り値: 別計算したbit0の列 (ndarray[int8])。
    """
    table = {}
    for index in set(row.tolist()):
        sequence = -1 if index < 0 else int(ready['seq'][index])
        data = '|'.join(('v38', role, str(seed), key[0], key[1], str(sequence))).encode('utf-8')
        table[index] = hashlib.sha256(data).digest()[0] % 2
    return np.fromiter((table[int(i)] for i in row), dtype=np.int8, count=len(row))


def synthetic() -> dict:
    """機能: 中立/無効/未公開、同時刻源、役割差、反射を人工列で検査する。

    引数: なし。返り値: 合成証跡 (dict)。
    """
    key = ('人工_Day','TOPIX')
    ready = dict(session=key[0],symbol=key[1],seq=np.array([101,104,107,110,113,116,119,122]),
        time_s=np.array([0.,1.,1.,2.,3.,3.,3.,4.]),last=np.ones(8))
    direction = np.array([0,1,1,0,-1,-1,0,0],np.int8)
    row = np.array([-1,1,1,3,4,4,6,-1],np.int64)
    event = np.array([-1,0,0,1,2,2,3,-1],np.int32)
    adapter.initialize({key:ready})
    path = adapter.condition_artifact('B01')
    adapter._COLUMNS[path] = {'direction::'+'|'.join(key):direction,'source_row::'+'|'.join(key):row,'event_index::'+'|'.join(key):event}
    adapter._QUALITY[adapter.condition_artifact('B01',evidence=True),key] = np.array([True,False,True,True])
    expected_quality = np.array([False,True,True,False,True,True,True,False])
    np.testing.assert_array_equal(adapter.publication_valid('B01',key),expected_quality)
    tests = 0; role_outputs = {}
    for seed in range(64):
        for role in ('bad','good','branch'):
            bits = adapter.source_bits(row,ready,key,seed,role)
            np.testing.assert_array_equal(bits,independent_bits(row,ready,key,seed,role))
            np.testing.assert_array_equal(bits[:6],adapter.source_bits(row[:6],previous.clipped(ready,6),key,seed,role))
            assert bits[1] == bits[2] and bits[4] == bits[5] and bits[0] == bits[-1]
            if role != 'branch':
                actual = adapter.random_direction(direction,row,ready,key,seed,role)
                np.testing.assert_array_equal(actual,direction*(1-2*bits))
                np.testing.assert_array_equal(-actual,adapter.random_direction(-direction,row,ready,key,seed,role))
                np.testing.assert_array_equal(actual==0,direction==0)
            else:
                np.testing.assert_array_equal(adapter.branch_choice(key,seed),bits)
            role_outputs[seed,role] = bits
            tests += 1
    assert any(not np.array_equal(role_outputs[s,'bad'],role_outputs[s,'good']) for s in range(64))
    assert any(not np.array_equal(role_outputs[s,'branch'],role_outputs[s,'bad']) for s in range(64))
    rejected = 0
    for seed in (-1,64,True,1.5):
        try: adapter.source_bits(row,ready,key,seed,'bad')
        except AssertionError: rejected += 1
        else: raise AssertionError('不正seedを受理した')
    future = row.copy(); future[2] = 3
    try: adapter.source_bits(future,ready,key,0,'bad')
    except AssertionError: rejected += 1
    else: raise AssertionError('未来公開元を受理した')
    return dict(全合格=True, 人工役割seed件数=tests, 不正入力拒否数=rejected,
        同時刻は公開元固定=True, 公開元なしは同一欠測符号=True, rawseqとready行を分離=True,
        valid中立とinvalidを分離=True, 役割間salt分離=True, 全64seed別式一致=True,
        方向反射でbadgood反転かつbranch不変=True, 新損益読取=False, 売買再生=False)


def random_checks(inputs: dict) -> tuple[list[dict],list[dict]]:
    """機能: 全64seedを両役割の基準4方向・分岐へ適用し、未来長と方向反射への不変性を検査する。

    引数: inputs (dict)。返り値: 方向対照・分岐対照の明細 (tuple[list,list])。
    """
    direction_rows, branch_rows = [], []
    for key, ready in inputs.items():
        cuts = previous.cuts(ready)
        for condition_id in adapter.CONDITIONS:
            direction, row, event = adapter.condition(condition_id,key)
            for role in ('bad','good'):
                for seed in range(64):
                    actual = adapter.random_direction(direction,row,ready,key,seed,role)
                    for n in cuts:
                        np.testing.assert_array_equal(actual[:n],adapter.random_direction(direction[:n],row[:n],previous.clipped(ready,n),key,seed,role))
                    np.testing.assert_array_equal(-actual,adapter.random_direction(-direction,row,ready,key,seed,role))
                    np.testing.assert_array_equal(direction==0,actual==0)
                    direction_rows.append(dict(condition_id=condition_id,role=role,seed=seed,session=key[0],symbol=key[1],
                        prefix=2,reflection=1,非0保持=True,公開元保持=True,SHA256=hashlib.sha256(actual.tobytes()).hexdigest()))
        # 分岐の感度窓でも公開元・無効性はその窓の列から取る。選択自体は価格/方向に依存しない。
        for scale in adapter.SCALES:
            _, row, _ = adapter.condition('B01',key,scale)
            for seed in range(64):
                choice = adapter.branch_choice(key,seed,scale)
                np.testing.assert_array_equal(choice,adapter.source_bits(row,ready,key,seed,'branch'))
                for n in cuts:
                    np.testing.assert_array_equal(choice[:n],adapter.source_bits(row[:n],previous.clipped(ready,n),key,seed,'branch'))
                mirrored = dict(ready,last=50000-ready['last'])
                np.testing.assert_array_equal(choice,adapter.source_bits(row,mirrored,key,seed,'branch'))
                branch_rows.append(dict(scale=scale,seed=seed,session=key[0],symbol=key[1],prefix=2,reflection=1,
                    欠測偽装なし=True,SHA256=hashlib.sha256(choice.tobytes()).hexdigest()))
        print(f'役割別乱数 {key[0]} {key[1]} 一致',flush=True)
    return direction_rows,branch_rows


def main() -> None:
    """機能: 新156入力と公開元乱数を検査し、入力の最終参照指紋を保存する。

    引数: なし。返り値: なし (None)。旧全格子・新売買は再生しない。
    """
    socket.socket.connect = prepare.previous.reject_network; socket.create_connection = prepare.previous.reject_network
    tests = synthetic()
    material = prepare.read(HERE/'branch_input_artifacts.json')
    references = dict(material['SHA256'])
    for path in (Path(__file__),HERE/'branch_input_artifacts.json',Path(previous.__file__)):
        references[path.relative_to(ROOT).as_posix()] = prepare.digest(path)
    for name,sha in references.items(): assert prepare.digest(ROOT/name) == sha
    inputs = pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    features = pickle.loads((HERE.parent/'wave_v23/features_depth.pkl').read_bytes())
    adapter.initialize(inputs)
    records, reused = [], []
    for h in adapter.SIGNALS:
        for scale in ((.8,1.,1.2) if h == 'H019' else (1.,)):
            for key in inputs:
                value = adapter.entry(h,scale,key)
                reused.append(dict(kind='entry',id=h,scale=scale,session=key[0],symbol=key[1],n=len(value)))
    for identifier in adapter.CONDITIONS:
        for scale in ((.8,1.,1.2) if identifier == 'B06' else (1.,)):
            for key in inputs:
                direction, row, event = adapter.condition(identifier,key,scale)
                quality = adapter.publication_valid(identifier,key,scale)
                assert quality[direction!=0].all()
                reused.append(dict(kind='condition',id=identifier,scale=scale,session=key[0],symbol=key[1],n=len(direction)))
    reflected_inputs, reflected_features = previous.reflected(inputs,features)
    for spec in prepare.specs():
        source.clear_cache(); full = source.build(spec,inputs,features)
        identifier, scale = spec['id'][:3],int(spec['id'][-3:])/100.
        for key,ready in inputs.items():
            peer = key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225'
            expected = full[key]; previous.evidence(ready,expected,inputs[peer])
            for name,array in zip(('direction','source_row','source_event_index'),adapter.condition(identifier,key,scale),strict=True):
                np.testing.assert_array_equal(expected[name],array)
            np.testing.assert_array_equal(previous.valid_column(expected),adapter.publication_valid(identifier,key,scale))
            for n in previous.cuts(ready):
                t = ready['time_s'][n-1]
                partial = {key:previous.clipped(ready,n),peer:previous.clipped(inputs[peer],int(np.searchsorted(inputs[peer]['time_s'],t,side='right')))}
                source.clear_cache(); result = source.build(spec,partial,features)[key]
                previous.same_prefix(expected,result,n)
                rr,ff = previous.future_pair(inputs,features,key,n)
                source.clear_cache(); result = source.build(spec,rr,ff)[key]
                previous.same_prefix(expected,result,n)
            records.append(dict(id=spec['id'],session=key[0],symbol=key[1],prefix=2,future=2,reflection=1,
                同時刻群途中=True,公開根拠照合=True,n=len(ready['seq'])))
        source.clear_cache(); mirrored = source.build(spec,reflected_inputs,reflected_features)
        for key in inputs:
            np.testing.assert_array_equal(mirrored[key]['direction'],-full[key]['direction'])
            for name in ('source_row','source_event_index'):
                np.testing.assert_array_equal(mirrored[key][name],full[key][name])
            np.testing.assert_array_equal(previous.valid_column(mirrored[key]),previous.valid_column(full[key]))
        print(f'新窓 {spec["id"]} 全26入力因果一致',flush=True)
    source.clear_cache()
    random_directions,random_branches = random_checks(inputs)
    assert len(reused) == (14+6)*26 and len(records) == 6*26
    assert len(random_directions) == 4*2*64*26 and len(random_branches) == 3*64*26
    for name,sha in references.items(): assert prepare.digest(ROOT/name) == sha
    originals = material['再利用']['原本78SHA256']
    for name,sha in originals.items(): assert prepare.digest(ROOT/name) == sha
    value = dict(全入力監査合格=True, 再利用列入力数=len(reused),再利用列=reused,
        新窓入力数=len(records),新窓prefix数=312,新窓future数=312,新窓reflection数=156,新窓検査=records,
        方向乱数入力数=len(random_directions),方向乱数prefix数=len(random_directions)*2,
        方向乱数reflection数=len(random_directions),方向乱数検査=random_directions,
        分岐乱数入力数=len(random_branches),分岐乱数prefix数=len(random_branches)*2,
        分岐乱数reflection数=len(random_branches),分岐乱数検査=random_branches,
        合成検査=tests,原本78SHA256=originals,参照SHA256=references,
        新損益読取=False,売買再生=False,現在保存物使用=False,API取得数=0)
    prepare.save(HERE/'branch_input_causality.json',value)
    fixed = dict(全入力監査合格=True,再利用入口数=14,再利用方向数=6,新窓方向数=6,乱数seed数=64,
        方向乱数役割=['bad','good'],分岐乱数役割='branch',新損益読取=False,
        SHA256={**references,**originals,(HERE/'branch_input_causality.json').relative_to(ROOT).as_posix():prepare.digest(HERE/'branch_input_causality.json')})
    prepare.save(HERE/'branch_input_fixed.json',fixed)
    print(dict(全入力監査合格=True,新窓入力数=156,方向乱数入力数=len(random_directions),分岐乱数入力数=len(random_branches)),flush=True)


if __name__ == '__main__':
    main()
