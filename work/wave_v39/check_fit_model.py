"""板圧力推定だけを人工・時系列で検査する。売買損益と未来価格ラベルは作らない。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import fit_model as model


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path: Path) -> str:
    """機能: 参照資料の内容指紋を求める。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1048576):
            value.update(chunk)
    return value.hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 非有限のJSON数値を拒否して監査証拠を保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def same(left: dict, right: dict, mask: np.ndarray | None = None) -> None:
    """機能: 公開イベントの全出力を、必要なら過去範囲に限定して照合する。

    引数: left/right (dict[str, ndarray])、mask (ndarray[bool]又はNone)。
    返り値: なし (None)。一致しない場合は例外。
    """
    assert left.keys() == right.keys()
    for name in left:
        expected = right[name] if mask is None else right[name][mask]
        np.testing.assert_allclose(left[name], expected, rtol=1e-10, atol=1e-10, equal_nan=True,
            err_msg=name)


def fixture(n: int = 30) -> tuple[dict, dict]:
    """機能: 値動きを売買しない人工の公開区間・完了時刻を作る。

    引数: n (int) は各セッションの公開区間数。
    返り値: 6セッション×2銘柄の公開区間と入力 (tuple[dict, dict])。
    """
    events, inputs = {}, {}
    for day in range(6):
        for symbol, offset in (('NK225', .2), ('TOPIX', .5)):
            key = (f'人工{day}', symbol)
            start = float(day*10000)
            times = start+(np.arange(n)+1)*60.
            flow = np.sin(np.arange(n)*.2+day)+offset
            events[key] = dict(indices=np.arange(n), seq=np.arange(n), time_s=times,
                minute=np.arange(n)+1, valid=np.ones(n, bool), flow=flow,
                change=np.cos(np.arange(n)*.3+day), spread=np.ones(n)+.1*np.sin(np.arange(n)))
            inputs[key] = dict(start=start, limit=float(times[-1]+10),
                time_s=np.r_[times, times[-1]+20], seq=np.arange(n+1))
    return events, inputs


def synthetic() -> dict:
    """機能: ridge目的式・共通母集団・学習締切の人工反例を確認する。

    引数: なし。返り値: 人工検査件数と成功状態 (dict)。
    """
    rng = np.random.default_rng(73819)
    x = rng.normal(size=(80, 5)); y = rng.normal(size=80)
    fitted = model.fit(x, y)
    z = (x-np.mean(x, axis=0))/np.std(x, axis=0, ddof=0)
    independent = np.linalg.lstsq(np.vstack((z/np.sqrt(len(y)), np.sqrt(.01)*np.eye(5))),
        np.r_[(y-y.mean())/np.sqrt(len(y)), np.zeros(5)], rcond=None)[0]
    np.testing.assert_allclose(fitted['coefficients'], independent, rtol=1e-11, atol=1e-11)
    predicted = y.mean()+z@independent
    np.testing.assert_allclose(model.predict(fitted, x), predicted, rtol=1e-11, atol=1e-11)
    np.testing.assert_allclose(fitted['residual_rms'], np.sqrt(np.mean((y-predicted)**2)))
    constant = model.fit(np.ones((40, 3)), np.zeros(40))
    assert constant['standard'] == [1., 1., 1.] and constant['coefficients'] == [0., 0., 0.]
    assert constant['residual_rms'] == constant['raw_ofi_rms'] == 1e-6
    rejects = 0
    for bad_x, bad_y in ((x[:39], y[:39]), (x, y[:-1]), (np.full_like(x, np.nan), y),
            (x, np.full_like(y, np.inf)), (x[:, 0], y)):
        try:
            model.fit(bad_x, bad_y)
        except ValueError:
            rejects += 1
        else:
            raise AssertionError('不正訓練入力を受理した')
    assert rejects == 5
    # ----------------------------------------
    # 当該・未来・他銘柄は、現在の係数を変えない。
    events, inputs = fixture()
    catalogs = {}
    for lag in (1, 3, 6):
        outputs, models = model.build(events, inputs, lag)
        catalogs[lag] = (outputs, models)
        for key in inputs:
            assert models[key]['available'] == (int(key[0][-1]) >= 2)
        for key in inputs:
            np.testing.assert_array_equal(outputs[key]['common_valid'], catalogs[1][0][key]['common_valid'])
            np.testing.assert_array_equal(outputs[key]['forecast_valid'], catalogs[1][0][key]['forecast_valid'])
    key = ('人工3', 'NK225'); original_output, original_model = catalogs[3]
    changed = deepcopy(events)
    for other in changed:
        if other[1] != key[1] or inputs[other]['start'] >= inputs[key]['start']:
            for column in ('flow', 'change', 'spread'):
                changed[other][column] = changed[other][column]*-37+100
    _, revised = model.build(changed, inputs)
    assert revised[key] == original_model[key]
    # ----------------------------------------
    # 未来の完成時刻・未完了区間を歴史へ紛れ込ませない。
    boundary = deepcopy(inputs)
    boundary[('人工0', 'NK225')]['time_s'][-1] = inputs[('人工2', 'NK225')]['start']
    _, checked = model.build(events, boundary)
    assert not checked[('人工2', 'NK225')]['available']
    unfinished = deepcopy(inputs)
    unfinished[('人工0', 'NK225')]['limit'] = unfinished[('人工0', 'NK225')]['time_s'][-1]
    _, checked = model.build(events, unfinished)
    assert not checked[('人工2', 'NK225')]['available']
    small_events, small_inputs = fixture(25)
    _, small = model.build(small_events, small_inputs)
    assert small[('人工2', 'NK225')]['training_rows'] == 38
    assert not small[('人工2', 'NK225')]['available'] and small[('人工3', 'NK225')]['available']
    invalid = deepcopy(events); invalid[key]['valid'][12] = False
    _, _, mask = model.matrix(invalid[key], 1)
    assert not mask[12:19].any(), '欠測を落として時間ラグを連結した'
    return dict(全合格=True, 目的式独立解一致=True, 零分散とRMS下限=True,
        不正入力拒否数=rejects, 全ラグ共通母集団=True, 当該未来他銘柄除外=True,
        完了時刻等号拒否=True, 未完了拒否=True, 最低40標本=True, 欠測ラグを接続しない=True)


def slice_ready(ready: dict, end: int) -> dict:
    """機能: 対象セッションの原本入力を先頭で切る。

    引数: ready (dict)、end (int)。返り値: 切断された辞書 (dict)。
    """
    n = len(ready['seq'])
    return {name: value[:end].copy() if isinstance(value, np.ndarray) and value.ndim and len(value) == n
        else value for name, value in ready.items()}


def main() -> None:
    """機能: 事前仕様を保存し、集約監査へ結んで推定・全因果検査を実施する。

    引数: なし。返り値: なし (None)。未来価格ラベルと売買損益は生成しない。
    """
    release_audit = json.loads((HERE/'分公開の因果検査.json').read_text(encoding='utf-8'))
    assert release_audit['全合格'] and release_audit['API取得数'] == 0
    for path, expected in release_audit['SHA256'].items():
        assert digest(ROOT/path) == expected, path
    source_paths = [Path(__file__), Path(model.__file__), HERE/'分公開の因果検査.json']
    fingerprints = dict(release_audit['SHA256'])
    fingerprints.update({p.relative_to(ROOT).as_posix():digest(p) for p in source_paths})
    save(HERE/'モデル学習の仕様.json', dict(仕様=model.specification(), SHA256=fingerprints,
        新売買損益計算=False, 未来価格ラベル作成=False, API取得数=0))
    artificial = synthetic()
    inputs = pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    events = pickle.loads((HERE/'released_minutes.pkl').read_bytes())
    assert len(inputs) == len(events) == 26
    masks, proofs, saved = {}, [], []
    for lag in (1, 3, 6):
        outputs, models = model.build(events, inputs, lag)
        for key, ready in sorted(inputs.items()):
            if lag == 1:
                masks[key] = (outputs[key]['common_valid'], outputs[key]['forecast_valid'])
            else:
                for column, base in zip(('common_valid', 'forecast_valid'), masks[key]):
                    np.testing.assert_array_equal(outputs[key][column], base)
            checked = 0
            n = len(ready['seq'])
            for fraction in (.37, .73):
                end = max(2, int(n*fraction)); cutoff = ready['seq'][end-1]
                selected = events[key]['seq'] <= cutoff
                cut_events = dict(events)
                cut_events[key] = {name: np.asarray(value)[selected].copy() for name, value in events[key].items()}
                cut_inputs = dict(inputs); cut_inputs[key] = slice_ready(ready, end)
                prefix, prefix_models = model.build(cut_events, cut_inputs, lag)
                same(prefix[key], outputs[key], selected)
                assert prefix_models[key] == models[key]
                # ----------------------------------------
                # 現在の未来と将来セッション・他銘柄の全値を変更する。
                altered = dict(events)
                for other in events:
                    if other == key:
                        altered[other] = {name: np.asarray(value).copy() for name, value in events[other].items()}
                        where = ~selected
                    elif other[1] != key[1] or inputs[other]['start'] >= ready['start']:
                        altered[other] = {name: np.asarray(value).copy() for name, value in events[other].items()}
                        where = np.ones(len(events[other]['seq']), bool)
                    else:
                        continue
                    for column in ('flow', 'change', 'spread'):
                        altered[other][column][where] = -37*altered[other][column][where]+100
                    altered[other]['valid'][where] = ~altered[other]['valid'][where]
                future, future_models = model.build(altered, inputs, lag)
                same({name:value[selected] for name,value in future[key].items()}, outputs[key], selected)
                assert future_models[key] == models[key]
                checked += 1
            proofs.append(dict(session=key[0], symbol=key[1], lag=lag,
                全合格=True, 公開区間数=len(outputs[key]['seq']), 共通有効数=int(outputs[key]['common_valid'].sum()),
                予測可数=int(outputs[key]['forecast_valid'].sum()), 過去訓練標本=models[key]['training_rows'],
                過去切断数=checked, 未来改変数=checked, 過去係数不変=True))
        mirrored = {key:{name:np.asarray(value).copy() for name,value in item.items()} for key,item in events.items()}
        for item in mirrored.values():
            item['flow'] *= -1; item['change'] *= -1
        reflected, _ = model.build(mirrored, inputs, lag)
        for key in inputs:
            for name in outputs[key]:
                target = -outputs[key][name] if name in ('observed','prediction','residual') else outputs[key][name]
                np.testing.assert_allclose(reflected[key][name], target, rtol=1e-9, atol=1e-9, equal_nan=True,
                    err_msg=str((lag,key,name)))
        destination = HERE/f'model_outputs_lag{lag}.pkl'
        destination.write_bytes(pickle.dumps(outputs, pickle.HIGHEST_PROTOCOL))
        history = HERE/f'model_history_lag{lag}.json'
        save(history, [models[key] for key in sorted(models)])
        saved.extend([destination, history])
        print(f'lag={lag}: 全26入力の推定・切断・未来改変・反射一致。売買なし。', flush=True)
    for path, expected in fingerprints.items():
        assert digest(ROOT/path) == expected, path
    payload = dict(全合格=True, 段階='板圧力モデルだけ・売買未実施', 人工=artificial,
        条件入力数=len(proofs), 過去切断数=sum(r['過去切断数'] for r in proofs),
        未来改変数=sum(r['未来改変数'] for r in proofs), 反射数=78,
        全ラグ共通母集団=True, 検査=proofs, 新売買損益計算=False,
        未来価格ラベル作成=False, API取得数=0, 現在保存物使用=False,
        仕様=model.specification(), SHA256=fingerprints,
        出力SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in saved})
    save(HERE/'モデル学習の因果検査.json', payload)
    sources = [*source_paths, *saved, HERE/'モデル学習の仕様.json', HERE/'モデル学習の因果検査.json']
    final = dict(fingerprints); final.update({p.relative_to(ROOT).as_posix():digest(p) for p in sources})
    save(HERE/'モデル学習の固定.json', dict(全合格=True, 新売買損益計算=False,
        未来価格ラベル作成=False, API取得数=0, SHA256=final, 仕様=model.specification()))


if __name__ == '__main__':
    main()
