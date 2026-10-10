"""既監査の入力を再利用し、価格短長窓と両市場長窓の診断だけ新規生成する。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent/'wave_v37'))
import prepare_partial_inputs as previous
sys.path.insert(0, str(HERE))
import branch_inputs as adapter

source = previous.source
digest, read, save, save_arrays = previous.digest, previous.read, previous.save, previous.save_arrays


def specs() -> list[dict]:
    """機能: 未作成のB00/B01/B07だけの±20%窓を列挙する。

    引数: なし。返り値: 新規6仕様 (list[dict])。peer遅延・鮮度・閾値は不変。
    """
    output = []
    for identifier in ('B00','B01','B07'):
        base = next(s for s in source.catalog() if s['id'] == identifier)
        for scale in (.8,1.2):
            changed = deepcopy(base); changed['id'] = f'{identifier}__W{round(scale*100):03d}'
            changed['params']['window_seconds'] *= scale
            assert {k:v for k,v in changed['params'].items() if k != 'window_seconds'} == {
                k:v for k,v in base['params'].items() if k != 'window_seconds'}
            assert changed['params']['peer_delay_seconds'] == changed['params']['freshness_seconds'] == 60.
            output.append(changed)
    assert len(output) == 6
    return output


def frozen_design() -> dict:
    """機能: 入力だけの数値・乱数・欠測表現を新損益前に固定する。

    引数: なし。返り値: 入力仕様 (dict)。既存固定と違えば停止する。
    """
    value = dict(再利用入口=[dict(id=h,clock_scale=s) for h in adapter.SIGNALS
        for s in ((.8,1.,1.2) if h == 'H019' else (1.,))],
        基準条件=list(adapter.CONDITIONS), 対応窓倍率=list(adapter.SCALES),
        新固有窓=specs(), 再利用変更窓=['B06__W080','B06__W120'],
        source_row='ready配列行のint64。rawseqではない。参照seq=ready.seq[source_row]。未公開/鮮度切れは-1。',
        event_index='証拠表のint32位置。source_row=-1なら-1。', direction='int8の-1/0/1。方向0と欠測を同義にしない。',
        publication_valid='自市場の価格・ATR・過去窓品質が有効、公開後60秒以内ならTrue。方向0の有効中立もTrue。peer同意は要件にしない。',
        通常分岐='減量約定行でbranch_validかつB01方向が保有逆なら信号復元、その他は時計復元。方式をその行で保存する。',
        分岐窓='主案B01は1.0。分岐窓感度.8/1.2と復元根拠B01窓感度は独立の引数。',
        時計='復元96/120/144秒の時間判定は注文器。入力生成では変更しない。',
        乱数役割=['bad','good','branch'], 乱数seed=list(range(64)),
        共通乱数='SHA256(v38|role|seed|session|symbol|source_rawseq)の先頭8byte little bit0。条件ID・将来配列長は含めない。',
        方向乱数='bad/goodはbit0なら+1、bit1なら-1を元方向へ乗算。非0機会/source/event/validを維持。',
        分岐乱数='branchはbit0時計/bit1信号のint8列。減量約定行の公開元に対応する値を一度保存し、方向反射で不変。',
        欠測乱数='source_rowが-1ならsource_rawseq=-1として同セッション同市場同役割で固定。欠測を有効情報へ変換しない。',
        乱数限界='同役割・同公開元では8条件共通。銘柄間/役割間の元の依存を保持しない。発火時刻や基礎価格情報は保持するため、完全な市場無情報ではない。',
        売買再生=False, 新損益読取=False, 現在保存物使用=False, API取得数=0)
    path = HERE/'branch_input_design.json'
    if path.exists(): assert read(path) == value
    else: save(path,value)
    return value


def inherited() -> dict:
    """機能: 今回使用する旧14入口・6方向・6証拠を旧固定SHAへ照合する。

    引数: なし。返り値: 継承指紋と原本78 (dict)。旧全格子再生はしない。
    """
    fixed_path = HERE.parent/'wave_v37/partial_input_fixed.json'
    audit_path = HERE.parent/'wave_v37/partial_input_causality.json'
    fixed, audit = read(fixed_path), read(audit_path)
    assert fixed['全入力監査合格'] and audit['全入力監査合格']
    assert fixed['SHA256'][audit_path.relative_to(ROOT).as_posix()] == digest(audit_path)
    paths = [adapter.entry_artifact(h,s) for h in adapter.SIGNALS for s in ((.8,1.,1.2) if h == 'H019' else (1.,))]
    paths += [adapter.condition_artifact(c,scale,e) for c in adapter.CONDITIONS
        for scale in ((.8,1.,1.2) if c == 'B06' else (1.,)) for e in (False,True)]
    assert len(paths) == len(set(paths)) == 26
    paths += [HERE.parent/'wave_v23/inputs.pkl', HERE.parent/'wave_v23/features_depth.pkl',
              HERE.parent/'wave_v35/deterioration_signals.py', HERE.parent/'wave_v37/partial_inputs.py']
    hashes = {}
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        assert digest(path) == fixed['SHA256'][relative], relative
        hashes[relative] = digest(path)
    original = audit['原本78SHA256']; assert len(original) == 78
    for name, sha in original.items(): assert digest(ROOT/name) == sha
    for path in (fixed_path,audit_path): hashes[path.relative_to(ROOT).as_posix()] = digest(path)
    return dict(旧監査継承=True, 旧全入力の大規模再検査=False, 再利用入口数=14, 再利用方向数=6,
        再利用証拠数=6, SHA256=hashes, 原本78SHA256=original)


def main() -> None:
    """機能: 新6窓だけを生成し、再利用物と指紋で結ぶ。

    引数: なし。返り値: なし (None)。新しい売買損益を計算しない。
    """
    socket.socket.connect = previous.reject_network; socket.create_connection = previous.reject_network
    frozen_design(); reused = inherited()
    inputs = pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    features = pickle.loads((HERE.parent/'wave_v23/features_depth.pkl').read_bytes())
    paths, rows = [], []
    source.clear_cache()
    for spec in specs():
        results = source.build(spec,inputs,features); columns, evidence = {}, {}
        for key,item in results.items():
            label = '|'.join(key)
            columns.update({'direction::'+label:item['direction'], 'source_row::'+label:item['source_row'],
                            'event_index::'+label:item['source_event_index']})
            evidence.update({label+'::'+name:item['events'][name].to_numpy() for name in item['events']})
            rows.append(dict(id=spec['id'],session=key[0],symbol=key[1],原本行数=len(item['direction']),証拠イベント数=len(item['events'])))
        for folder,values in (('deterioration',columns),('evidence',evidence)):
            path = HERE/folder/(spec['id']+'.npz'); save_arrays(path,values); paths.append(path)
    source.clear_cache()
    references = dict(reused['SHA256'])
    references.update({p.relative_to(ROOT).as_posix():digest(p) for p in [Path(__file__), HERE/'branch_inputs.py', HERE/'branch_input_design.json', *paths]})
    save(HERE/'branch_input_artifacts.json',dict(新窓数=6, 新方向入力数=156, 新窓入力=rows,
        再利用=reused, SHA256=references, 新損益読取=False, 売買再生=False, 現在保存物使用=False, API取得数=0))
    print('旧14入口・6方向を継承、新6窓156入力だけ生成。新売買なし。',flush=True)


if __name__ == '__main__':
    main()
