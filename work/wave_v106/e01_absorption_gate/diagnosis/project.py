"""固定公開観測を小資料へ射影し、成立0の条件交差だけを診断する。"""

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
import math
from pathlib import Path
import pickle
import time
import traceback

import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
ROOT = HERE.parents[3]
COMPONENTS = ('数量非減少', '支持非進行', '接触二回以上', '活動比一以上')


def digest(path: Path) -> str:
    """
    機能: 小資料又はconsumerの指紋を求める。
    引数: path(Path)は対象位置。
    返り値: strはSHA256。大型入力を先に再走査しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    """
    機能: 固定した小JSONを読む。
    引数: path(Path)は対象位置。
    返り値: dictは保存情報。NPZ・金融結果は読まない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path: Path, value: dict) -> None:
    """
    機能: 所有診断域へ小JSONを未存在の場合だけ保存する。
    引数: path(Path)、value(dict)は位置と情報。
    返り値: None。固定8sourceと既証跡の上書きを拒否する。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                    encoding='utf-8', newline='\n')


def fix() -> None:
    """
    機能: 成立0の非金融原因を測る目的・299候補・部品交差を、読取前に固定する。
    引数: なし。
    返り値: None。準備cache・NPZ・金融会計をまだ読まない。
    """
    path = SOURCE/'全33場の表示維持公開観測の準備.json'
    meta = read_json(path)
    assert meta['全合格'] and len(meta['sessions']) == 33
    assert meta['aggregate']['TOPIX']['全公開の成立数'] == 0
    assert meta['aggregate']['NK225']['全公開の成立数'] == 0
    assert sum(v['紙上公開候補数'] for v in meta['aggregate'].values()) == 299
    for source, sha in meta['source_SHA256'].items():
        assert digest(ROOT/source) == sha
    write(HERE/'固定部品の射影と不成立原因の目的.json', dict(
        全合格=True, 対象='新prepared33を別目的一読し、全299公開観測を小witnessへ射影する。',
        比較='元KNOWN許可全229は追加見送り0のため不変。今回勝敗・金融差を計算しない。',
        元資料=dict(path=path.relative_to(ROOT).as_posix(), SHA256=digest(path)),
        cache=meta['cache'], sessions=meta['sessions'], source_SHA256=meta['source_SHA256'],
        consumer_SHA256=digest(Path(__file__)),
        条件=list(COMPONENTS), 定義='Qmin>=Q0、支持最大順行<=0、接触件数>=2、接触更新公表出来高差>=Q0。閾値不変更。',
        交差='全四成分の16部分集合を、適用対象既知候補と元許可候補に分けて数える。',
        例示='不足成分の組合せ別に最初の原順例を最大2件。既存負け/勝ちの指定時計は説明対象だけ。',
        準備読取=0, NPZ=0, 原板=0, 原paper=0, 新金融=0, 勝敗照合=0, API=0))
    print('299公開の小射影と部品交差の目的を固定、金融0', flush=True)


def known_verdict(base: dict) -> tuple:
    """
    機能: 保存W60票から元KNOWN_VETOの許可を独立な単純式で再計算する。
    引数: base(dict)は当時保存した票。
    返り値: tuple[bool,int]は元許可と拒否理由。入口条件を変更しない。
    """
    if not base['known']:
        return False, 100+int(base['reason'])
    if base['direction_votes'] < 2:
        return False, 200
    return (False, 202) if base['balance'] <= -.25 else (True, 0)


def project(account: dict, session: str, symbol: str) -> list:
    """
    機能: 既存の公開featureと元票・原行由来だけを、小さな一行観測へ射影する。
    引数: account(dict)、session/symbol(str)は新preparedの保存口座と識別子。
    返り値: list[dict]は全paper公開候補。実取引・勝敗・収支を含めない。
    """
    entries = account['feed'][account['feed'][:, 7] == 1]
    output = []
    for order in entries:
        normal_row, side = int(order[0]), int(order[3])
        value = account['absorption_features'][normal_row]
        base = account['trade_features']['60'][normal_row]
        accepted, reason = known_verdict(base)
        assert value['candidate_raw_row'] == int(account['mapping'][normal_row])
        assert value['candidate_raw_seq'] == int(account['record']['seq'][normal_row])
        assert value['side'] == side
        assert value['hit'] is not True
        assert bool(account['absorption_gate_accepted'][normal_row]) == accepted
        assert int(account['absorption_gate_reasons'][normal_row]) == reason
        clock = float(account['record']['time_s'][normal_row])
        assert math.isfinite(clock)
        components = None
        if value['eligible'] and value['known']:
            components = dict(zip(COMPONENTS, (
                value['minimum_quantity'] >= value['initial_quantity'],
                value['maximum_support_advance'] <= 0,
                value['touch_count'] >= 2,
                value['touch_activity_volume'] >= value['initial_quantity'])))
            assert all(components.values()) == value['hit']
            assert value['touch_activity_to_initial_ratio'] == value['touch_activity_volume']/value['initial_quantity']
        output.append(dict(session=session, symbol=symbol, normal_row=normal_row,
            paper_parent=int(order[2]), side=side, direction='買い' if side > 0 else '売り',
            candidate_price_time_s=clock,
            JST=datetime.fromtimestamp(clock, timezone(timedelta(hours=9))).isoformat(),
            base_known=bool(base['known']), base_direction_votes=base['direction_votes'],
            base_balance=base['balance'], base_known_veto_allowed=accepted, base_rejection_reason=reason,
            candidate_raw_row=value['candidate_raw_row'], candidate_raw_seq=value['candidate_raw_seq'],
            eligible=value['eligible'], known=value['known'], hit=value['hit'], feature_reason=value['reason'],
            first_window_raw_row=value['first_window_raw_row'],
            episode_start_raw_row=value['episode_start_raw_row'], episode_start_raw_seq=value['episode_start_raw_seq'],
            opposite_price=value['opposite_price'], Q0=value['initial_quantity'], Qmin=value['minimum_quantity'],
            support_price=value['support_price'], maximum_support_advance=value['maximum_support_advance'],
            touch_rows=value['touch_rows'], touch_raw_seq=value['touch_raw_seq'], touch_count=value['touch_count'],
            touch_activity_volume=value['touch_activity_volume'],
            touch_activity_ratio=value['touch_activity_to_initial_ratio'], components=components))
    return output


def aggregate(rows: list) -> dict:
    """
    機能: 固定四条件の単独・交差・不足組合せを、適用対象既知の分母で数える。
    引数: rows(list[dict])は一商品又は一側の小公開観測。
    返り値: dictは非金融の件数と代表観測。勝率・最適閾値は計算しない。
    """
    known = [r for r in rows if r['eligible'] and r['known']]
    allowed = [r for r in known if r['base_known_veto_allowed']]
    intersections = []
    for bitset in range(16):
        required = [name for index, name in enumerate(COMPONENTS) if bitset & (1 << index)]
        intersections.append(dict(
            条件=required, 適用対象既知分母=len(known),
            件数=sum(all(r['components'][name] for name in required) for r in known),
            元許可分母=len(allowed),
            元許可件数=sum(all(r['components'][name] for name in required) for r in allowed)))
    patterns = {}
    for row in known:
        failures = [name for name in COMPONENTS if not row['components'][name]]
        name = '、'.join(failures) if failures else '不足なし'
        target = patterns.setdefault(name, dict(不足成分=failures, 件数=0, 元許可件数=0, 原順例=[]))
        target['件数'] += 1
        target['元許可件数'] += int(row['base_known_veto_allowed'])
        if len(target['原順例']) < 2:
            target['原順例'].append(row)
    return dict(
        全公開数=len(rows), 元許可数=sum(r['base_known_veto_allowed'] for r in rows),
        適用対象数=sum(r['eligible'] for r in rows), 適用対象既知数=len(known),
        適用対象未知数=sum(r['eligible'] and not r['known'] for r in rows),
        元票未知数=sum(not r['base_known'] for r in rows),
        元票既知二票未満数=sum(r['base_known'] and r['base_direction_votes'] < 2 for r in rows),
        成立数=sum(r['hit'] is True for r in rows), 条件交差=intersections,
        不足組合せ=list(patterns.values()),
        尾部一原行数=sum(r['episode_start_raw_row'] == r['candidate_raw_row'] for r in known),
        接触零数=sum(r['touch_count'] == 0 for r in known),
        接触一回数=sum(r['touch_count'] == 1 for r in known),
        最大接触回数=max((r['touch_count'] for r in known), default=None),
        最大活動比=max((r['touch_activity_ratio'] for r in known), default=None))


def run() -> None:
    """
    機能: 固定目的の新prepared33を各一読し、299公開の小witnessと不成立原因を保存する。
    引数: なし。
    返り値: None。NPZ・旧金融・原板・APIは使用しない。
    """
    fixed = read_json(HERE/'固定部品の射影と不成立原因の目的.json')
    assert fixed['consumer_SHA256'] == digest(Path(__file__))
    assert digest(ROOT/fixed['元資料']['path']) == fixed['元資料']['SHA256']
    meta = read_json(ROOT/fixed['元資料']['path'])
    for source, sha in fixed['source_SHA256'].items():
        assert digest(ROOT/source) == sha
    write(HERE/'小射影開始.json', dict(全合格=True, 新金融=0, 目的SHA256=digest(HERE/'固定部品の射影と不成立原因の目的.json')))
    rows = []
    per_session = {}
    reads = Counter()
    started = time.monotonic()
    for session in fixed['sessions']:
        item = fixed['cache'][session]
        saved = (ROOT/item['path']).read_bytes()
        assert hashlib.sha256(saved).hexdigest() == item['SHA256']
        packet = pickle.loads(gzip.decompress(saved))
        reads['新prepared一読'] += 1
        assert packet['session'] == session
        per_session[session] = {}
        for symbol in ('TOPIX', 'NK225'):
            part = project(packet['accounts'][symbol], session, symbol)
            rows.extend(part)
            per_session[session][symbol] = aggregate(part)
            old = meta['activity'][session][symbol]
            now = per_session[session][symbol]
            for key, reference in (('全公開数', '紙上公開候補数'), ('元許可数', '元KNOWN_VETO許可数'),
                                   ('適用対象数', '追加述語対象数'), ('適用対象既知数', '追加述語既知数'),
                                   ('適用対象未知数', '追加述語未知数'), ('成立数', '全公開の成立数')):
                assert now[key] == old[reference], (session, symbol, key)
                reads['小metadata件数一致'] += 1
        del packet, saved
        print(session+' 小公開観測への射影完了、金融0', flush=True)
    assert reads['新prepared一読'] == 33 and len(rows) == 299
    by_symbol = {s: aggregate([r for r in rows if r['symbol'] == s]) for s in ('TOPIX', 'NK225')}
    by_side = {s: {str(side): aggregate([r for r in rows if r['symbol'] == s and r['side'] == side])
                  for side in (1, -1)} for s in ('TOPIX', 'NK225')}
    scenes = [('TOPIX', '2026-10-05_Night', '18:40:52'), ('NK225', '2026-09-29_Night', '19:12:57'),
              ('NK225', '2026-10-08_Day', '11:37:16'), ('TOPIX', '2026-09-22_Night', '18:06:55'),
              ('NK225', '2026-09-28_Day', '09:51:18'), ('NK225', '2026-10-05_Day', '10:31:00')]
    selected = [dict(symbol=s, session=day, 指定時計=clock,
                     該当公開=[r for r in rows if r['symbol'] == s and r['session'] == day and r['JST'][11:19] == clock])
                for s, day, clock in scenes]
    for source, sha in fixed['source_SHA256'].items():
        assert digest(ROOT/source) == sha
    write(HERE/'全299公開の表示維持観測と条件交差.json', dict(
        全合格=True, source=fixed['元資料'], source_SHA256=fixed['source_SHA256'],
        consumer_SHA256=fixed['consumer_SHA256'], 目的SHA256=digest(HERE/'固定部品の射影と不成立原因の目的.json'),
        元固定値='W60・2接触・公表活動差/Q0>=1・Qmin>=Q0・支持進行<=0。不変更。',
        witness=rows, 商品別=by_symbol, 商品側別=by_side, 各場=per_session, 指定時刻の公開観測=selected,
        一致検査=dict(reads), 新prepared読取=33, NPZ=0, 原板=0, 原paper=0,
        旧金融読取=0, 新金融=0, 勝敗照合=0, API=0, 開始終端固定8source不変=True,
        限界=['公開候補で成立しなかったことは、全板更新や全時間帯でその表示現象が無い証拠ではない。',
              '不足成分を外す新政策は未測定。成績を見ずに固定した閾値をここで変更していない。',
              '同価格接触更新の公表出来高差は真の同価格同方向の約定量ではない。'],
        経過秒=time.monotonic()-started))
    print('全299公開の小witnessと条件交差を保存、金融0、NPZ0', flush=True)


def main() -> None:
    """
    機能: 診断目的固定又はroot許可済み小射影を一回だけ行う。
    引数: CLI --fix-only/--root-diagnosis-approved(bool)。
    返り値: None。自動再開始・入力修正・金融を実行しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--fix-only', action='store_true')
    parser.add_argument('--root-diagnosis-approved', action='store_true')
    args = parser.parse_args()
    assert args.fix_only != args.root_diagnosis_approved
    if args.fix_only:
        fix()
        return
    assert not (HERE/'小射影開始.json').exists()
    assert not (HERE/'小射影False.json').exists()
    assert not (HERE/'全299公開の表示維持観測と条件交差.json').exists()
    try:
        run()
    except Exception:
        write(HERE/'小射影False.json', dict(全合格=False, 原因=traceback.format_exc(),
                                         自動再開始=False, 新金融=0, NPZ=0, 原板=0, API=0))
        raise


if __name__ == '__main__':
    main()
