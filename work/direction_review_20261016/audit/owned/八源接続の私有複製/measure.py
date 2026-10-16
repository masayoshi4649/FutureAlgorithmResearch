"""登録した同じ候補について、方向の先着だけを一回測定する。"""

import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np

import aggregate
import engine
import input_contract
import plan


OUT = plan.HERE/'measurement'

# ----------------------------------------


def load_once(info: dict, counts: dict, label: str, keys: tuple | None = None) -> dict:
    """
    機能: 小目録の一入力を一回読み、同じbytesでSHAと配列を検査する。
    引数: info/counts(dict)、label(str)、keys(tuple|None) は目録・計数・必要列。
    返り値: dict[str,ndarray]。114の未来先着・終点ラベルはdecodeしない。
    """
    path = plan.ROOT/info['path']
    before = path.stat()
    assert before.st_size == info['bytes']
    if 'mtime_ns' in info:
        assert before.st_mtime_ns == info['mtime_ns']
    counts[label] += 1
    raw = path.read_bytes()
    after = path.stat()
    assert (before.st_size,before.st_mtime_ns) == (after.st_size,after.st_mtime_ns)
    assert hashlib.sha256(raw).hexdigest() == info['SHA256']
    with np.load(BytesIO(raw),allow_pickle=False) as archive:
        selected = tuple(archive.files) if keys is None else keys
        assert set(selected).issubset(archive.files)
        arrays = {key:archive[key] for key in selected}
    for value in arrays.values():
        value.flags.writeable = False
    return arrays


def guard() -> tuple[dict, dict]:
    """
    機能: 八源・十八条件・原小目録・正式登録・人工証拠を実測前に接続する。
    引数: なし。
    返り値: tuple[dict,dict] は固定入力と正式固定。金融呼出は持たない。
    """
    assert not OUT.exists(), '結果または停止記録があるため自動再測定しない'
    frozen = plan.read(plan.HERE/'実測前の正式固定.json')
    proposal = plan.read(plan.HERE/'試行計画.json')
    audit = plan.read(plan.HERE/'実測前の人工と独立監査.json')
    assert frozen['全合格'] and audit['全合格'] and audit['新金融'] == 0
    assert plan.sources() == frozen['source_SHA256'] == audit['source_SHA256']
    assert frozen['widths'] == plan.WIDTHS and frozen['rules'] == plan.RULES and frozen['primary'] == plan.PRIMARY
    for name,key in (('入力と保存公開の固定.json','input_SHA256'),('試行計画.json','proposal_SHA256'),
                     ('実測前の人工と独立監査.json','audit_SHA256')):
        assert plan.digest(plan.HERE/name) == frozen[key]
    for item in audit['evidence']:
        assert plan.digest(plan.ROOT/item['path']) == item['SHA256']
    checked = plan.read(plan.HERE/'正式照合の全出力.json')
    registered = plan.read(plan.HERE/'正式登録の全出力.json')
    assert checked['終了コード'] == registered['終了コード'] == 0
    assert json.loads(checked['stdout'])['proposal_complete'] is True
    table = plan.read(plan.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    rows = [row for row in table['trials'] if row['id'] == plan.TRIAL]
    assert len(rows) == 1 and rows[0]['spec'] == proposal['spec']
    fixed = plan.read(plan.HERE/'入力と保存公開の固定.json')
    assert fixed['全合格'] and len(fixed['inputs']) == 66
    assert len(fixed['sessions']) == len(set(fixed['sessions'])) == 33
    assert proposal['spec']['data']['sessions'] == fixed['sessions']
    assert proposal['spec']['entry']['rules'] == plan.RULES
    assert proposal['spec']['exit']['幅率'] == plan.WIDTHS
    assert proposal['主評価'] == proposal['spec']['management']['主評価'] == plan.PRIMARY
    actual = [(row['raw']['session'],row['raw']['symbol']) for row in fixed['inputs']]
    assert len(set(actual)) == 66 and set(actual) == {(s,y) for s in fixed['sessions'] for y in plan.CAP}
    assert proposal['spec']['data']['inputs'] == plan.registration_inputs(fixed)
    assert proposal['spec']['implementation'] == plan.sources()
    assert frozen['実行予定'] == dict(原NPZ=66,保存eventNPZ=66,非金融測定口座=66,新金融=0,原板=0,API=0)
    return fixed,frozen


def save_observations(result: dict, path: Path) -> dict:
    """
    機能: 採点配列をNaNを保持した非pickleのNPZへ新規保存する。
    引数: result(dict)、path(Path) は純採点と保存位置。
    返り値: dict は出力目録。entryを未来ラベルで選び直さない。
    """
    assert not path.exists() and path.resolve().is_relative_to(OUT)
    arrays = {key:value for key,value in result.items() if isinstance(value,np.ndarray)}
    assert {'events','labels','terminal_rows','eligible','nonoverlap','mfe','mae'}.issubset(arrays)
    assert all(value.dtype != object for value in arrays.values())
    memory = BytesIO()
    np.savez_compressed(memory,**arrays)
    raw = memory.getvalue()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)
    return dict(path=path.relative_to(plan.ROOT).as_posix(),SHA256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),
        arrays={key:dict(dtype=str(value.dtype),shape=list(value.shape)) for key,value in arrays.items()})

# ----------------------------------------


def main() -> None:
    """
    機能: 66原入力と66保存公開を各一回読み、非金融の方向予測を採点する。
    引数: なし。
    返り値: None。停止時はFalseを保存し、登録や実測を自動再試行しない。
    """
    fixed,frozen = guard()
    OUT.mkdir()
    counts = dict(原NPZ=0,保存eventNPZ=0,非金融測定口座=0,新金融=0,原板=0,API=0)
    accounts,outputs,metadata = [],[],[]
    try:
        for index,item in enumerate(fixed['inputs'],1):
            raw_info = item['raw']
            session,symbol = raw_info['session'],raw_info['symbol']
            arrays = load_once(raw_info,counts,'原NPZ')
            input_contract.validate(arrays,fixed['schema'])
            assert len(arrays['raw_seq']) == item['raw_rows']
            saved = load_once(item['events'],counts,'保存eventNPZ',('events',))
            assert len(saved['events']) == item['events']['n']
            start,end = raw_info['bounds']
            signal = input_contract.signal(arrays,saved['events'],item['fields'],start,end)
            policy = {name:item['time_policy'][name] for name in (
                'entry_start_s','entry_end_s','force_start_s','quiet_windows')}
            policy['quiet_windows'] = np.asarray(policy['quiet_windows'],dtype=np.float64).reshape(-1,2)
            counts['非金融測定口座'] += 1
            measured = engine.measure(arrays,signal,symbol,start,end,fixed['観測T'][symbol],policy)
            assert measured['rule_names'] == plan.RULES and list(measured['widths']) == plan.WIDTHS
            account = aggregate.account(symbol,session,measured)
            accounts.append(account)
            outputs.append(dict(session=session,symbol=symbol,**save_observations(measured,
                OUT/'observations'/(session+'_'+symbol+'.npz'))))
            metadata.append(dict(session=session,symbol=symbol,
                fields=measured['fields'],origins=measured['origin_names'],code_names=measured['code_names']))
            del arrays,saved,signal,measured
            print(json.dumps(dict(進捗=index,session=session,symbol=symbol,**counts),ensure_ascii=False),flush=True)
        assert counts == frozen['実行予定'] and plan.sources() == frozen['source_SHA256']
        combined = aggregate.combine(accounts,fixed['sessions'])
        plan.write(OUT/'方向予測の採点結果.json',dict(全合格=True,金融=False,試行=plan.TRIAL,
            source_SHA256=plan.sources(),sessions=fixed['sessions'],counts=counts,
            primary=plan.PRIMARY,widths=plan.WIDTHS,rules=plan.RULES,
            accounts=accounts,combined=combined,outputs=outputs,metadata=metadata,
            留保='旧既知33場の採点。清算気配評価は実返済約定・決済勝率・損益ではない。新しい未知期間は使わない。'))
        print(json.dumps(dict(全合格=True,**counts),ensure_ascii=False),flush=True)
    except BaseException as exc:
        plan.write(OUT/'False.json',dict(全合格=False,counts=counts,例外型=type(exc).__name__,例外=str(exc),自動再試行=False))
        raise


if __name__ == '__main__':
    main()
