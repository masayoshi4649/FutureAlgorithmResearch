"""取消後の状態表示だけを正規化した人工対照で、後続注文への影響を反証する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sys
import types
import urllib.request

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import engine_partial_restore as engine
import engine_audit as fixtures
import random_path_audit as random_fixture


def reject(*args: object, **kwargs: object) -> None:
    """機能: 通信を拒否する。

    引数: 任意(object)。返り値: なし(None)、常に例外。
    """
    raise AssertionError('人工検査で通信は使用しません')


def digest(path: Path) -> str:
    """機能: 読取対象の内容指紋を返す。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def alternative() -> tuple:
    """機能: 元ファイルを変更せず予算取消後だけ状態を正規化する。

    引数: なし。返り値: 人工専用モジュール・正確な置換記録(tuple)。
    """
    source = Path(engine.__file__).read_text(encoding='utf-8')
    original = '                    pending = 0; pending_slots[:] = False\n            if kind == 3 and not acted and not pending and not budget:'
    changed = '                    pending = 0; pending_slots[:] = False\n                    phase = 2 if np.any(restorable) else 0\n            if kind == 3 and not acted and not pending and not budget:'
    assert source.count(original) == 1
    normalized = source.replace(original, changed).replace('@njit(cache=True)', '@njit(cache=False)')
    module = types.ModuleType('phase_normalization_artificial_only')
    module.__file__ = str(Path(engine.__file__).resolve())
    sys.modules[module.__name__] = module
    exec(compile(normalized, str(Path(__file__).resolve()), 'exec'), module.__dict__)
    return module, dict(置換前=original, 置換後=changed, 置換数=1,
        JIT差分='人工モジュールのキャッシュだけ無効化',
        メモリ内比較実装SHA256=hashlib.sha256(normalized.encode()).hexdigest())


def compare(args: tuple, policy: dict, kwargs: dict, variant: object, label: dict) -> dict:
    """機能: 状態表示以外の全配列を厳密照合し、予算取消とその後を記録する。

    引数: args(tuple)、policy/kwargs/label(dict)、variant(object)。返り値: 検査明細(dict)。
    """
    original = engine.run(*args, policy, **kwargs)
    modified = variant.run(*args, policy, shadow=original['shadow'], **kwargs)
    fields = [k for k, v in original.items() if isinstance(v, np.ndarray)]
    for name in fields:
        if name == 'control_curve':
            keep = [j for j in range(original[name].shape[1]) if j != 2]
            np.testing.assert_array_equal(original[name][:, keep], modified[name][:, keep], err_msg=name)
        else:
            np.testing.assert_array_equal(original[name], modified[name], err_msg=name)
    for name, value in original['shadow'].items():
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(value, modified['shadow'][name], err_msg='影 '+name)
    different = np.flatnonzero(original['control_curve'][:, 2] != modified['control_curve'][:, 2])
    for row in different:
        assert original['control_curve'][row, 13] == 1
        assert original['control_curve'][row, 8] == 0
        assert original['control_curve'][row, 2] in (1, 3)
        assert modified['control_curve'][row, 2] in (0, 2)
    a = original['adjustment_events']
    cancellations = a[(a[:, 2] == 3) & (a[:, 7] == 32)]
    events = []
    for cancellation in cancellations:
        begin, campaign = int(cancellation[0]), int(cancellation[1])
        cycle = original['cycles'][original['cycles'][:, 0] == campaign]
        assert len(cycle) == 1
        end = int(cycle[0, 2])
        original_partial = original['slot_events']
        partial = original_partial[(original_partial[:, 2] == campaign) & (original_partial[:, 4] == 4)]
        # ----------------------------------------
        # 予算解除より先に同組の新しい調整が発火しないことを全行で検査する。
        forbidden = a[(a[:, 1] == campaign) & (a[:, 0] > begin) & (a[:, 0] <= end) & np.isin(a[:, 2], (1, 2))]
        assert not len(forbidden)
        assert np.all(original['control_curve'][begin:end, 13] == 1)
        assert original['control_curve'][end, 13] == 0
        assert original['control_curve'][end, 2] == 0
        events.append(dict(取消行=begin, 組=campaign, 種類=int(cancellation[3]),
            終了行=end, 終了理由=int(cycle[0, 9]),
            予算中の元部分利確=bool(np.any((partial[:, 0] > begin) & (partial[:, 0] < end))),
            後続組あり=bool(np.any(original['cycles'][:, 0] > campaign))))
    return dict(**label, 全注文金銭と状態以外の全配列一致=True, 検査配列数=len(fields),
        状態表示差行数=len(different), 予算取消=events)


def main() -> None:
    """機能: 固定人工経路だけで正規化対照を検査し、証跡を新規保存する。

    引数: なし。返り値: なし(None)。実相場・現在データは再生しない。
    """
    socket.create_connection = reject
    urllib.request.urlopen = reject
    files = [Path(engine.__file__), Path(engine.shadow_engine.__file__), HERE/'adaptive_slot_audit.py',
        HERE.parent/'wave_v37'/'数量調整エンジンの契約.md', Path(__file__)]
    before = {str(p): digest(p) for p in files}
    variant, replacement = alternative()
    policy = deepcopy(fixtures.POLICIES['B06_RB06_F50_N3'])
    rows = []
    # ----------------------------------------
    # 初期保護の成熟前に予算が先行し、未成熟減量を取り消す人工経路。
    for final, name in ((96., '元停止優先'), (100., '予算成行'), (110., '元部分優先')):
        for reflected in (False, True):
            args = list(fixtures.fixture([100,101,101,96,final,final,final], (2,), ()))
            args[0]['time_s'][:7] = [0,15,16,17,30,31,32]
            if reflected:
                args[0]['last'] = 400-args[0]['last']
                for k in (1,3,5): args[k] = -args[k]
            rows.append(compare(tuple(args), policy, dict(min_delay_seconds=15.), variant,
                dict(群='指定人工', 例=name, 反射=reflected, 遅延秒=15.)))
    # ----------------------------------------
    # 64事前固定seedの観測間隔・飛値・繰返し調整。良い結果によるseed選択なし。
    for seed in range(64):
        for symbol in ('TOPIX', 'NK225'):
            material = random_fixture.generated(seed, symbol)
            ready,state,config,bad,bs,good,gs,valid,branch,source,bv,choice = material
            args = (ready,state,config,bad,bs,good,gs)
            for delay in (1.,5.,15.):
                for observed in (False,True):
                    kwargs = dict(good_valid=valid, min_delay_seconds=delay, observed_fill=observed)
                    rows.append(compare(args, policy, kwargs, variant,
                        dict(群='固定乱数人工', seed=seed, 銘柄=symbol, 遅延秒=delay, 観測約定=observed)))
    source = Path(engine.__file__).read_text(encoding='utf-8')
    tree = ast.parse(source)
    refs = [dict(行=x.lineno, 読込=isinstance(x.ctx, ast.Load), 変数=x.id)
        for x in ast.walk(tree) if isinstance(x, ast.Name) and x.id in ('phase','budget')]
    after = {str(p): digest(p) for p in files}
    assert before == after
    events = [e for row in rows for e in row['予算取消']]
    result = dict(全人工対照一致=True, 人工入力数=len(rows), 人工再生数=2*len(rows),
        状態表示差のある人工入力数=sum(r['状態表示差行数']>0 for r in rows),
        取消減量数=sum(e['種類']==-1 for e in events), 取消復元数=sum(e['種類']==1 for e in events),
        取消後元部分優先数=sum(e['予算中の元部分利確'] for e in events),
        取消後後続組あり数=sum(e['後続組あり'] for e in events),
        終了理由別={str(reason):sum(e['終了理由']==reason for e in events) for reason in sorted({e['終了理由'] for e in events})},
        元契約の表示不適合を認める=True, 監査不合格を合格へ置換しない=True,
        正式コア変更=False, 新実相場損益=False, API取得数=0, 現在保存物使用=False,
        比較差分=replacement, 全参照=sorted(refs,key=lambda x:(x['行'],x['変数'])),
        SHA256=before, 前後SHA256一致=True, 検査=rows)
    (HERE/'phase_state_counterfactual.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('検査','全参照','SHA256','比較差分')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
