"""入口を固定し、小試行・全量・当初リスクを増やさない順行追加を比較する。"""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE / 'v2'))
sys.path.insert(0, str(BASE))
import engine119
import run_v2
import engine_v3


ENTRIES = (
    ('COMMON20', '共同進行', '両市場が共通方向へ進み、対象の現在値も平均の同方向側にある時に参加する。'),
    ('OPEN20', '開始帯離脱', '最初20分の高安を価格が抜けた方向へ参加する。'),
    ('CENTER20', '中心への復帰', '安定した近似加重価格から大きく離れ、戻り始めた方向へ参加する。'),
    ('FAIL20', '離脱失敗', '過去20分帯を抜け切れず帯内へ戻った方向へ参加する。'),
    ('A20', '共同失速後の復帰', '両市場の強い進行と停止を確認し、実際に戻り始めてから逆方向へ参加する。'),
    ('D20', '自己失速後の復帰', '対象の強い進行と停止を確認し、実際に戻り始めてから逆方向へ参加する。'),
)
ALLOCATIONS = ((0, 'SCOUT', '少量固定'), (1, 'FULL', '全量固定'), (2, 'GROW', '順行時だけ追加'))


def load_cache(path: Path, expected: str, wanted: list[str]) -> dict:
    """
    機能: 指紋固定した保存配列だけを一回読み、必要な射影を返す。
    引数: path(Path)、expected(str)、wanted(list[str]) は場所・SHA256・必要列。
    返り値: dict[str,ndarray]。価格原本・APIを再読しない。
    """
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == expected
    with np.load(BytesIO(payload), allow_pickle=False) as source:
        return {key: source[key].copy() for key in wanted if key in source.files}


def main() -> None:
    """
    機能: 36政策の配分・リスク保持を固定計画から一回実行する。
    引数: なし。金融前の登録と独立人工監査の源一致を要求する。
    返り値: None。全注文・全親・全場資産を同時に保存する。
    """
    fixed = run_v2.read(HERE / '固定計画.json')
    assert run_v2.read(HERE / '正式登録の全出力.json')['終了コード'] == 0
    for path, sha in fixed['sources'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha
    m = fixed['input_manifest']
    assert (ROOT / m['path']).resolve() == (HERE / '入力目録.json').resolve()
    assert hashlib.sha256((ROOT / m['path']).read_bytes()).hexdigest() == m['sha256']
    meta = run_v2.read(HERE / '入力目録.json')
    lookup = {(item['symbol'], item['session']): item for item in meta['inputs']}
    out = HERE / 'measurement'
    assert not out.exists()
    out.mkdir()
    specs, indexes = [], []
    for k, (eid, name, explanation) in enumerate(ENTRIES):
        for am, tag, title in ALLOCATIONS:
            for tm in (.5, 1.):
                specs.append(dict(id=f'{eid}_{tag}_T{round(tm * 10):02d}', family=eid, entry_id=eid,
                                  name=name + '・' + title, description=explanation,
                                  allocation_mode=am, allocation_name=title, trail_multiple=tm))
                indexes.append(k)
    assert len(specs) == 36
    all_rows, all_episodes, caches, reads = [], [], [], []
    clock = time.monotonic()
    for number, scene in enumerate(meta['sessions']):
        for symbol in ('TOPIX', 'NK225'):
            item = lookup[symbol, scene]
            # ----------------------------------------
            # 値段と旧四入口は初回所有copy、追加二入口は第二試行の保存政策を再利用する。
            payload = (ROOT / item['old_owned_path']).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == item['old_SHA256']
            with np.load(BytesIO(payload), allow_pickle=False) as old:
                bars = {key[6:]: old[key].copy() for key in old.files if key.startswith('bars__')}
                quotes = {key[8:]: old[key].copy() for key in old.files if key.startswith('quotes__')}
                policies = {key: old['policies__' + key][meta['old_indexes']].copy()
                            for key in ('entry', 'exit_long', 'exit_short', 'width', 'valid')}
            payload = (ROOT / item['v2_path']).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == item['v2_SHA256']
            with np.load(BytesIO(payload), allow_pickle=False) as second:
                for key in policies:
                    policies[key] = np.concatenate((policies[key], second['policies__' + key][meta['v2_indexes']].copy()))
            reads.append(dict(symbol=symbol, session=scene, old_owned=item['old_owned_path'], derived_v2=item['v2_path'],
                              original_market_reads=0, financial_replay='配分と逆指値を変更した新運転'))
            with (out / '保存入力読取.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(reads[-1], ensure_ascii=False) + '\n')
            events = engine119.market_events(bars, quotes)
            orders, parents, traces, positions = [], [], [], []
            scene_rows, scene_episodes = [], []
            for k, spec in enumerate(specs):
                policy = {key: value[indexes[k]] for key, value in policies.items()}
                setting = run_v2.settings(symbol, scene, 0, 4, 2)
                setting.update(allocation_mode=spec['allocation_mode'], trail_multiple=spec['trail_multiple'])
                answer = engine_v3.run_policy(bars, quotes, policy, setting, events)
                summary = run_v2.clean(answer['summary'])
                row = dict(symbol=symbol, session=scene, method=spec['id'],
                           signals=int(np.count_nonzero(policy['entry'])), **summary)
                all_rows.append(row)
                scene_rows.append(row)
                for key, sink in (('orders', orders), ('parents', parents)):
                    values = answer[key]
                    if len(values):
                        sink.append(np.column_stack((np.full(len(values), k), values)))
                trade = dict(symbol=symbol, session=scene, method=spec['id'],
                             parent_columns=engine_v3.PARENT_COLUMNS,
                             order_columns=engine_v3.ORDER_COLUMNS,
                             parents=answer['parents'].tolist(), orders=answer['orders'].tolist())
                scene_episodes.append(trade)
                all_episodes.append(trade)
                traces.append(answer['equity'])
                positions.append(answer['position'])
            path = out / symbol / (scene + '.npz')
            path.parent.mkdir(parents=True, exist_ok=True)
            assert not path.exists()
            memory = BytesIO()
            np.savez_compressed(memory, orders=np.concatenate(orders) if orders else np.empty((0, len(engine_v3.ORDER_COLUMNS) + 1)),
                                parents=np.concatenate(parents) if parents else np.empty((0, len(engine_v3.PARENT_COLUMNS) + 1)),
                                equity=np.asarray(traces), position=np.asarray(positions))
            payload = memory.getvalue()
            path.write_bytes(payload)
            caches.append(dict(path=path.relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(payload).hexdigest(),
                               symbol=symbol, session=scene))
            run_v2.save(out / symbol / (scene + '.json'), dict(rows=scene_rows, episodes=scene_episodes))
        print(f'{number + 1}/40 {scene} / 保存入力{2 * len(reads)} / {time.monotonic() - clock:.1f}秒', flush=True)
    for path, sha in fixed['sources'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha
    run_v2.save(out / '小試行と順行追加の全四十場.json', dict(sessions=meta['sessions'], splits=meta['splits'], specs=specs,
               runs=all_rows, episodes=all_episodes, cache=caches, source_SHA256=fixed['sources'],
               原市場追加読取=0, 実注文=0, API=0, reads=reads,
               留保='同じ既知40場の資金管理の原因対照。将来や未知標本の成功を主張しない。'))
    print('三つの張り方と二つの追尾幅の全会計を保存しました。', flush=True)


if __name__ == '__main__':
    main()
