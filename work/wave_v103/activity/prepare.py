"""新損益を見る前に、全32場の状態可用性を一回だけ測る。"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
from pathlib import Path
import socket
import time
import traceback

import core
import data


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V2 = HERE.parent/'input_v2'
PLAN = HERE/'全32活動測定前の固定.json'
RESULT = HERE/'全32の状態可用性と発火.json'
ARTIFICIAL = HERE/'人工発火の正常列直接投影と未来不変.json'


def sources() -> dict:
    """
    機能: 現activity source・確定入口・v2と人工由来を小直接指紋へ固定する。
    引数: なし。
    返り値: dict[str,str]。金融結果及び生原本を読まない。
    """
    paths = [HERE/name for name in ('core.py', 'data.py', 'prepare.py', 'artificial.py', 'states_snapshot.py', '活動cache仕様.json', ARTIFICIAL.name)]
    paths += [HERE.parent/'catalog.py', HERE.parent/'engine/states.py',
        HERE.parent/'engine/独立状態と厳密過去接続及び実配分の人工検査_補足07確定.json',
        HERE.parent/'engine/固定2場の実状態と二市場pulseの接頭不変.json',
        HERE.parent/'review/補足07独立入口と現source及びv2由来の金融前判定.json',
        V2/'data.py', V2/'correction.py', V2/'入力schema.json', V2/'metadata.json',
        V2/'前価格時計逆行の二列訂正と人工未来不変.json', V2/'v2派生前の由来固定.json']
    paths += [HERE.parent/'数値設計草案.json'] + [HERE.parent/f'数値設計補足{index:02d}.json' for index in range(1, 8)]
    return {str(path.relative_to(ROOT)): core.digest(path) for path in paths}


def qualification() -> dict:
    """
    機能: 完了v2と補足07人工・実接頭・独立レビューを金融なしで要求する。
    引数: なし。
    返り値: dictは64口座metadata。NPZ本体をこの関数では読まない。
    """
    metadata = core.read(V2/'metadata.json')
    assert metadata['全合格'] and metadata['schema']['version'] == 2
    assert metadata['対象場数'] == 32 and metadata['口座数'] == metadata['正式全64派生'] == 64
    for name, wanted in metadata['小直接依存SHA256'].items():
        assert core.digest(ROOT/name) == wanted, name
    official = core.read(HERE.parent/'engine/独立状態と厳密過去接続及び実配分の人工検査_補足07確定.json')
    prefix = core.read(HERE.parent/'engine/固定2場の実状態と二市場pulseの接頭不変.json')
    independent = core.read(HERE.parent/'review/補足07独立入口と現source及びv2由来の金融前判定.json')
    assert official['全合格'] and prefix['全合格'] and independent['全合格']
    wanted = core.digest(HERE.parent/'engine/states.py')
    for proof in (official, prefix):
        bindings = proof['SHA256']
        assert wanted in bindings.values(), '確定状態sourceの由来が一致しません'
    assert core.digest(HERE/'states_snapshot.py') == wanted
    assert core.read(HERE/'活動cache仕様.json') == core.schema()
    own = core.read(ARTIFICIAL)
    assert own['全合格'] and own['人工専用'] and own['正式口座読取'] == own['正式金融再生'] == 0
    for name, value in own['source_SHA256'].items():
        assert core.digest(ROOT/name) == value, name
    return metadata


def prepare_plan() -> None:
    """
    機能: rootの活動レビュー前に対象64口座と現sourceを固定する。
    引数: なし。
    返り値: None。NPZの正式読取・状態計算を行わない。
    """
    assert not PLAN.exists()
    metadata = qualification()
    before = sources()
    core.save(PLAN, dict(全合格=True, sessions=metadata['sessions'], 対象場数=32, 口座数=64,
        case数=19, single数=14, local種類数=12, union数=1, portfolio数=3, OLD_G0=None,
        source_SHA256=before, v2口座={key: dict(位置=item['出力位置'], SHA256=item['出力SHA256']) for key, item in metadata['accounts'].items()},
        活動定義=core.schema(), 正式口座読取=0, 正式金融再生=0, 現在API取得=0, 実注文=0))
    print('全32場64口座の活動測定前固定を保存。正式入力読取・金融再生は0', flush=True)


def one_session(session: str, metadata: dict, values: list[dict]) -> tuple[str, dict, dict]:
    """
    機能: 一場のv2NPZ2口座を各一回読み、状態・pulse・由来cacheを保存する。
    引数: session(str)、metadata(dict)は確定v2、values(list[dict])は根19条件。
    返り値: tuple[str,dict,dict]は場名、活動summary及び出力証跡。金融を再生しない。
    """
    raw, items = {}, {}
    for symbol in core.SYMBOLS:
        item = metadata['accounts'][session+'|'+symbol]
        path = ROOT/item['出力位置']
        assert path.resolve().is_relative_to(V2.resolve())
        arrays = data.read_npz_once(path, item['出力SHA256'])
        data.verify_arrays(arrays, item, metadata['schema'])
        raw[symbol], items[symbol] = arrays, item
    payload = core.build_session(session, raw, items, values)
    target = HERE/'cache'/(session+'.pkl.gz')
    fingerprint = data.dump_session(target, payload)
    evidence = dict(位置=str(target.relative_to(ROOT)), SHA256=fingerprint,
        v2入力={symbol: dict(位置=item['出力位置'], SHA256=item['出力SHA256'], NPZ読取回数=1,
            raw_rows=item['raw_rows'], normal_execution_rows=item['normal_execution_rows'], 旧normal五列一致=True) for symbol, item in items.items()})
    return session, payload['summary'], evidence


def totals(by_session: dict, values: list[dict]) -> dict:
    """
    機能: 全32の活動場数と買売発火を集計し、無発火を未活動と記録する。
    引数: by_session(dict)、values(list[dict])は一場活動と根19条件。
    返り値: dictは条件・商品ごとの非金融集計。配分は二腿の件数を別に保持する。
    """
    result = {}
    fields = ('raw_pulses', 'normal_pulses', 'non_normal_pulses', 'reception_pulses',
              'outside_reception_pulses', 'reception_normal_pulses', 'reception_non_normal_pulses')
    for config in values:
        ident = config['id']
        if config['kind'] == 'previous':
            result[ident] = None
            continue
        result[ident] = {}
        for symbol in core.SYMBOLS:
            rows = [summary[symbol][ident] for summary in by_session.values()]
            if config['kind'] == 'portfolio':
                result[ident][symbol] = dict(kind='portfolio', 対象場数=len(rows),
                    leg_pulses=sum(row['leg_pulses'] for row in rows),
                    reception_normal_leg_pulses=sum(row['reception_normal_leg_pulses'] for row in rows),
                    活動場数=sum(row['leg_pulses'] > 0 for row in rows),
                    受付内normal対応場数=sum(row['reception_normal_leg_pulses'] > 0 for row in rows),
                    未活動場数=sum(row['leg_pulses'] == 0 for row in rows),
                    legs={component: result[component][symbol] for component in ('C1', 'R1')})
            else:
                result[ident][symbol] = dict(kind=config['kind'], 対象場数=len(rows),
                    活動場数=sum(row['pulse']['raw_pulses'] > 0 for row in rows),
                    受付内normal対応場数=sum(row['pulse']['reception_normal_pulses'] > 0 for row in rows),
                    未活動場数=sum(row['pulse']['raw_pulses'] == 0 for row in rows),
                    **{field: sum(row['pulse'][field] for row in rows) for field in fields},
                    sides={side: {field: sum(row['pulse']['sides'][side][field] for row in rows) for field in fields} for side in ('1', '-1')})
                if config['kind'] == 'single':
                    result[ident][symbol]['local'] = dict(
                        qualified_rows=sum(row['local']['qualified_rows'] for row in rows),
                        ready_rows=sum(row['local']['ready_rows'] for row in rows),
                        episodes=sum(row['local']['episodes'] for row in rows),
                        ready_episodes=sum(row['local']['ready_episodes'] for row in rows))
    return result


def formal(workers: int) -> None:
    """
    機能: rootの別許可後に一回だけ全32活動を測定し、開始終端のsource一致を保存する。
    引数: workers(int)は1又は2の同時場数。
    返り値: None。新損益・旧損益・現在APIを読まない。
    """
    assert workers in (1, 2) and PLAN.exists() and not RESULT.exists()
    assert not list((HERE/'cache').glob('*.pkl.gz')), '既存cacheがあるため再開始を拒否します'
    plan, metadata = core.read(PLAN), qualification()
    before = sources()
    assert plan['source_SHA256'] == before
    assert plan['sessions'] == metadata['sessions'] and len(metadata['sessions']) == 32
    assert plan['v2口座'] == {key: dict(位置=item['出力位置'], SHA256=item['出力SHA256']) for key, item in metadata['accounts'].items()}
    values, by_session, cache = core.catalog(), {}, {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        jobs = [executor.submit(one_session, session, metadata, values) for session in metadata['sessions']]
        for job in as_completed(jobs):
            session, summary, evidence = job.result()
            by_session[session], cache[session] = summary, evidence
            primary = {symbol: summary[symbol]['U_C1R1']['pulse']['reception_normal_pulses'] for symbol in core.SYMBOLS}
            print(session+' 主の受付内normal対応pulse '+str(primary)+' / 金融0', flush=True)
    assert len(by_session) == len(cache) == 32 and sources() == before
    ordered = {session: by_session[session] for session in metadata['sessions']}
    result = dict(全合格=True, sessions=metadata['sessions'], 対象場数=32, 口座数=64,
        case数=19, raw_single数=14, local計算種類数=12, local計算口座数=12*64,
        paired又はown_pulse口座数=14*64, union口座数=64, portfolio再計算=0, OLD_G0=None,
        v2NPZ読取回数=64, v2指紋一致口座数=64, normal五列一致口座数=64,
        primary='U_C1R1', catalog=values, schema=core.schema(), case_routes=core.routes(values),
        by_session=ordered, aggregate=totals(ordered, values), cache={session: cache[session] for session in metadata['sessions']},
        開始終端source一致=True, 開始SHA256=before, SHA256=sources(), 事前固定SHA256=core.digest(PLAN),
        発火0を勝ちに含めない=True, 原本再抽出=0, 旧金融結果読取=0, 正式金融再生=0, 現在API取得=0, 実注文=0,
        限界='活動の存在だけ。受付内normal対応pulseは新規注文や約定の数ではない。保有、返済優先、cooldownによる拒否は金融再生で初めて判定する。価格代理時計による接続で実受信先後は不明。')
    core.save(RESULT, result)
    data.load_session(metadata['sessions'][0], verify=True)
    print('全32場の状態可用性と発火を保存。金融0。証跡SHA256 '+core.digest(RESULT), flush=True)


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 活動測定からの外部通信を拒絶する。
    引数: args(tuple)、kwargs(dict)は通信引数。
    返り値: None。常にRuntimeErrorを送出する。
    """
    raise RuntimeError('活動測定ではAPI及び注文へ接続しません')


def main() -> None:
    """
    機能: 計画作成又はrootのレビュー後だけ正式活動測定を開始する。
    引数: CLI --prepare-plan(bool)又は--root-activity-reviewed(bool)、--workers(int)。
    返り値: None。無指定は正式入力の読取前に拒否する。
    """
    parser = argparse.ArgumentParser(description='損益前の全32状態可用性測定')
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--prepare-plan', action='store_true')
    choice.add_argument('--root-activity-reviewed', action='store_true')
    parser.add_argument('--workers', type=int, default=2)
    arguments = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    prepare_plan() if arguments.prepare_plan else formal(arguments.workers)


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        target = HERE/('活動False_'+time.strftime('%Y%m%d_%H%M%S')+'.json')
        core.save(target, dict(全合格=False, 内容=str(error), traceback=traceback.format_exc(),
            source_SHA256=core.digest(Path(__file__)), 正式金融再生=0, 現在API取得=0, 実注文=0))
        raise
