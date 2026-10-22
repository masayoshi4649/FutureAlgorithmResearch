"""市場を読まず、v2の36政策・原始型保存・二つの実行前guardを接続する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
V2 = HERE.parent
OWNER = V2.parent
ROOT = OWNER.parents[1]
os.environ['NUMBA_CACHE_DIR'] = str(V2 / 'numba_audit')
sys.dont_write_bytecode = True
sys.path.insert(0, str(OWNER))
import artificial_catalog119 as material
sys.path.insert(0, str(V2))
import run_v2 as run
import plan_v2 as plan

CHECKS = []


def check(name: str, value: bool) -> None:
    """
    機能: 合成接続又は明示した静的条件を記録する。
    引数: name(str)、value(bool) は内容と成否。
    返り値: None。不一致はAssertionError。
    """
    CHECKS.append(dict(項目=name, 合格=bool(value)))
    assert value, name


def digest(path: Path) -> str:
    """
    機能: 読んだ実装源の同一性を確認する。
    引数: path(Path) は市場を含まない源。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def models() -> None:
    """
    機能: 合成足を8入口から32政策へ接続し、旧4執行と同じ実引数で実行する。
    引数: なし。
    返り値: None。源の実行経路だけを検査し市場の有効性を測らない。
    """
    for symbol in ('TOPIX', 'NK225'):
        scene = '2026-10-16_Day'
        bars = material.fixture(symbol, 'mixed', 150)
        peer = material.fixture('NK225' if symbol == 'TOPIX' else 'TOPIX', 'trend', 150)
        start = datetime(2026, 10, 16, 8, 45, tzinfo=timezone(timedelta(hours=9))).timestamp()
        for b in (bars, peer):
            b['t_s'] = start+60*np.arange(1, 151)
            b['pub_price_time_s'] = b['t_s']+1
        tick = .5 if symbol == 'TOPIX' else 10.
        rows = np.column_stack((bars['pub_raw_row'], bars['pub_raw_row']+1)).ravel()
        times = np.column_stack((bars['pub_price_time_s'], bars['pub_price_time_s']+1)).ravel()
        center = np.repeat(bars['anchor'], 2)
        quotes = dict(row=rows, time=times, last=center, bid=center-.5*tick, ask=center+.5*tick)
        base = run.catalog_v2.build(bars, peer, symbol)
        model = run.variants(base)
        check(symbol+'8入口から32へ展開', len(base['specs']) == 8 and len(model['specs']) == 32)
        controls = [dict(id=f'BASELINE_P{p}', execution_mode=p, exit_mode=0, guard=1) for p in range(4)]
        specs = model['specs']+controls
        check(symbol+'36のID一意', len({s['id'] for s in specs}) == 36)
        for key in ('entry', 'exit_long', 'exit_short', 'width', 'valid'):
            check(symbol+key+'の全shape', model[key].shape == (32, 150))
        # ----------------------------------------
        # 旧4対照には同じ入口配列を渡し、執行bit以外を変えない。
        old_policy = dict(entry=np.zeros(150, np.int8), exit_long=np.zeros(150, bool),
                          exit_short=np.zeros(150, bool), width=np.full(150, 1000.*tick), valid=np.ones(150, bool))
        old_policy['entry'][1] = 1
        old_policy['exit_long'][2] = True
        all_ledgers = []
        for k, spec in enumerate(specs):
            policy = {key: model[key][k] for key in ('entry', 'exit_long', 'exit_short', 'width', 'valid')} if k < 32 else old_policy
            setting = run.settings(symbol, scene, spec['execution_mode'], spec['exit_mode'], spec['guard'])
            check(symbol+spec['id']+'E0固定', setting['entry_mode'] == 0)
            check(symbol+spec['id']+'場予算接続', setting['guard'] == (2 if k < 32 else 1))
            answer = run.engine_v2.run_policy(bars, quotes, policy, setting)
            parents = run.episodes(answer['ledger'], quotes, bars, setting['multiplier'])
            for parent in parents:
                check(symbol+spec['id']+'同時点Last恒等式', abs(parent['gross_last_same_times']-parent['entry_adverse']
                      -parent['exit_adverse']-parent['fees']-parent['net']) < 1e-5)
            encoded = json.dumps(run.clean(dict(summary=answer['summary'], episodes=parents)), allow_nan=False)
            check(symbol+spec['id']+'全payload JSON保存', isinstance(encoded, str))
            if len(answer['ledger']):
                all_ledgers.append(np.column_stack((np.full(len(answer['ledger']), k), answer['ledger'])))
        ledger = np.concatenate(all_ledgers) if all_ledgers else np.empty((0, 17))
        check(symbol+'保存台帳17列', ledger.ndim == 2 and ledger.shape[1] == 17)
    # ----------------------------------------
    # 真偽/整数/配列のNumPy型と未知を、経済値0へ補完せずに保存する。
    payload = run.clean(dict(flag=np.bool_(True), count=np.int64(2), price=np.float64(3.5),
                             unknown=np.float64(np.nan), values=np.array([1., np.inf])))
    check('原始型変換と未知null', json.loads(json.dumps(payload, allow_nan=False)) ==
          dict(flag=True, count=2, price=3.5, unknown=None, values=[1., None]))
    for symbol in ('TOPIX', 'NK225'):
        for scene, expected in (('2026-10-16_Day', ('15:00', '15:20')),
                                ('2026-10-16_Night', ('05:20', '05:40'))):
            c = run.settings(symbol, scene, 3, 5, 2)
            clock = tuple(datetime.fromtimestamp(c[key], timezone(timedelta(hours=9))).strftime('%H:%M')
                          for key in ('entry_end', 'close_time'))
            check(symbol+scene+'時刻', clock == expected)
            check(symbol+scene+'量倍率費用と二つの呼値',
                  (c['quantity'], c['multiplier'], c['fee'], c['order_tick'], c['observed_tick']) ==
                  ((10, 1000., 41.8, .25, .5) if symbol == 'TOPIX' else (20, 10., 11., 5., 10.)))


def guards() -> None:
    """
    機能: manifest変造と照合不完全が実入力・登録へ進む前に拒否されることを実関数で検査する。
    引数: なし。合成小JSONと源の私有copyだけを用いる。
    返り値: None。元目録、実登録、実cacheを読まない。
    """
    mock = HERE/'synthetic_guard'
    assert not mock.exists()
    mock.mkdir()
    manifest = mock/'入力目録.json'
    manifest.write_text('{}', encoding='utf-8')
    old_here, old_root, old_read = run.HERE, run.ROOT, run.read
    try:
        run.HERE = mock
        run.ROOT = ROOT
        fixed = dict(input_manifest=dict(path=manifest.relative_to(ROOT).as_posix(), sha256='0'*64), sources={})
        def fake_read(path: Path) -> dict:
            """
            機能: 実行前guardへ合成固定と登録終了コードだけを返す。
            引数: path(Path) はguard要求先。
            返り値: dict。市場読取に達した場合は停止する。
            """
            if path.name == '固定計画.json':
                return fixed
            if path.name == '正式登録の全出力.json':
                return dict(終了コード=0)
            raise RuntimeError('想定外読取: '+str(path))
        run.read = fake_read
        stopped = False
        try:
            run.main()
        except AssertionError:
            stopped = True
        check('manifest SHA不一致は出力作成とcache読取前に停止', stopped and not (mock/'measurement').exists())
    finally:
        run.HERE, run.ROOT, run.read = old_here, old_root, old_read
    fake_plan = HERE/'synthetic_check'
    assert not fake_plan.exists()
    fake_plan.mkdir()
    for name in ('plan_v2.py', 'run_v2.py', 'engine_v2.py', 'catalog_v2.py'):
        shutil.copyfile(V2/name, fake_plan/name)
    (fake_plan/'入力目録.json').write_text(json.dumps(dict(sessions=['合成場'])), encoding='utf-8')
    (fake_plan/'人工監査の結合.json').write_text(json.dumps(dict(passed=True, economic_sources={})), encoding='utf-8')
    old_here, old_subprocess = plan.HERE, plan.subprocess.run
    commands = []
    try:
        plan.HERE = fake_plan
        def fake_process(command: list, **kwargs: object) -> SimpleNamespace:
            """
            機能: 実照合を呼ばず、終了0だが不完全な合成結果を返す。
            引数: command(list)、kwargs(dict) は照合要求。
            返り値: SimpleNamespace は人工stdout/終了コード。
            """
            commands.append(command[4])
            return SimpleNamespace(returncode=0, stdout=json.dumps(dict(proposal_complete=False)), stderr='')
        plan.subprocess.run = fake_process
        stopped = False
        try:
            plan.freeze()
        except AssertionError:
            stopped = True
        check('照合終了0でも不完全なら登録へ進まない', stopped and len(commands) == 1 and
              not (fake_plan/'正式登録の全出力.json').exists())
    finally:
        plan.HERE, plan.subprocess.run = old_here, old_subprocess


def main() -> None:
    """
    機能: 完成源へ小人工とSOURCE_ONLYの接続範囲を束縛する。
    引数: なし。
    返り値: None。新しい実測・金融・APIは0。
    """
    files = [V2/n for n in ('plan_v2.py', 'run_v2.py', 'engine_v2.py', 'catalog_v2.py')]+[OWNER/'engine119.py', OWNER/'catalog119.py']
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    models()
    guards()
    check('源は開始終端一致', before == {p.relative_to(ROOT).as_posix(): digest(p) for p in files})
    proof = dict(全合格=True, 検査数=len(CHECKS), source_SHA256=before,
        人工source_SHA256=digest(Path(__file__)), 実市場=0, 保存cache本文=0, 実登録=0, 新金融=0, API=0,
        検査=CHECKS, 実測前の指摘と是正=[
            '照合終了0だけでなくproposal_complete=Trueを要求した。市場開始前に是正、実害なし。',
            '固定input_manifestのpath/SHAをrunがowned cache読取前に照合するよう是正した。実害なし。'],
        静的留保=['旧primaryは指定復元SHAのselection[symbol].chosen[0]。全40を見た新たな選択ではない。',
                   'MFE/MAEとLast同時点分解はepisodesの事後診断だけ。entry/exit判断へ結果を戻さない。',
                   'guard2は実現現金だけではなく含み損・返済料込み清算資産の−2R停止。',
                   '正式固定とregistry行の最終接続は根担当。純人工の合格は市場収益性を示さない。'])
    target = HERE/'八入口三十六政策と保存型及び実行前guardの独立接続.json'
    assert not target.exists()
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=len(CHECKS)), ensure_ascii=False))


if __name__ == '__main__':
    main()
