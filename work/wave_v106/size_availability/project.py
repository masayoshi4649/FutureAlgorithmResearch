"""根の確認後だけ公開299のATR・当行BBOを射影し、最小量の受付可用性を測る。"""

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import math
from pathlib import Path
import pickle
import time
import traceback

import numpy as np

import common
import risk


def fix() -> None:
    """
    機能: 公開予定リスク診断の単一式・全299分母・入力33指紋を大型読取前に固定する。
    引数: なし。
    返り値: None。小metadataとsourceだけ読み、cache・NPZ・金融は読まない。
    """
    path = common.ROOT/'work/wave_v106/e01_trade_gate/全33場のE01取引更新準備.json'
    meta = common.read_json(path)
    artificial_path = common.HERE/'公開予定リスクの純算術人工.json'
    artificial = common.read_json(artificial_path)
    assert meta['全合格'] and artificial['全合格']
    assert len(meta['sessions']) == len(meta['cache']) == 33
    assert artificial['source_SHA256'] == common.sources()
    expected = {}
    for symbol in ('TOPIX', 'NK225'):
        v = meta['aggregate'][symbol]['60_VETO']
        c = meta['aggregate'][symbol]['60_CONFIRM']
        expected[symbol] = dict(publish=v['紙上公開新規数'], VETO=v['公開許可数'], CONFIRM=c['公開許可数'],
                                KNOWN_VETO=v['公開許可数']-v['未知数']-v['既知2票未満'])
    assert expected['TOPIX']['publish'] == 147 and expected['NK225']['publish'] == 152
    proof_sources = ['work/wave_v85/catalog.py', 'work/wave_v106/e01_trade_gate/prepare.py',
                     'work/wave_v106/e01_trade_gate/policy.py', 'work/wave_v106/e01_known_veto/policy.py']
    plan = dict(全合格=True, 目的='公開時予定リスクによる初回最小1枚受付可用性の非金融診断',
        分母='元paperの新規publish299（TOP147/NK152）。実口座のquiet/busy/goalstop採否を適用した取引集合ではない。',
        Gate別='VETO/CONFIRM/KNOWN_VETOによる元公開許可に対する静的可用性。新門前、実約定数・勝率ではない。',
        計算='q*(公開1ATR+公開ask−bid)*商品倍率+2floor(q*片道料)<=初回全予算',
        予算=risk.BUDGET, 元初回上限=risk.CAP, 価格倍率=risk.VALUE, 片道料=risk.FEE,
        紙上停止係数=risk.PAPER_STOP_ATR,
        係数の意味='元E01_G_Uの出口影は0.75ATR。今回1ATRで予定する保守的な可用性であり実約定後の実損失でも損失保証でもない。',
        数量='公開時に元初回5/10枚以下を整数列挙。q0は見送り相当、未知をq0へ補完しない。将来fillで再選択しない。',
        固定原稿='1ATR、TOP5000/NK2000、上限5/10は結果を見る前にroot指定。複数ATR係数・予算の探索なし。',
        実口座='今回remainingbudget・未約定fill・UID・料金実支払・部分返済を運転しない。初回fullbudgetで統一。',
        入力元=dict(path=path.relative_to(common.ROOT).as_posix(), SHA256=common.digest(path)),
        input33=meta['cache'], sessions=meta['sessions'], expected=expected,
        source_SHA256=common.sources(),
        小source契約={p: common.digest(common.ROOT/p) for p in proof_sources},
        owner_artificial=dict(path=artificial_path.relative_to(common.ROOT).as_posix(), SHA256=common.digest(artificial_path)),
        測定する列=['session', 'symbol', 'paper_parent', 'side', 'publish_normal_row', 'raw_row', 'raw_seq',
                  'price_time_s', 'ATR', 'bid', 'ask', 'original_qty', 'W60原票', '三元採否', '予定qと各qリスク'],
        検査='公開feed[0]→normal、保存mapping→raw。seq/価格時計をW60候補由来と一致させる。feed[9]が当時ATR。',
        大型読取=0, NPZ=0, 原板=0, 原paper再計算=0, 新金融=0, 登録変更=0, API=0)
    common.write(common.HERE/'公開299予定リスクの非金融固定計画.json', plan)
    print('299公開、単一1ATR式、初回全予算と3元門の非金融計画を固定。大型読取0。', flush=True)


def group(rows: list, mode: str | None = None) -> dict:
    """
    機能: 全公開又は元公開門の候補で、予定q0・正量・未知を区別して数える。
    引数: rows(list[dict])は小射影、mode(str|None)は元公開門。
    返り値: dictは静的受付可用性。実取引・無取引場の成績ではない。
    """
    selected = rows if mode is None else [r for r in rows if r['old_gate'][mode]['allowed']]
    known = [r for r in selected if r['sizing']['known']]
    zero = sum(r['sizing']['proposed_quantity'] == 0 for r in known)
    return dict(公開分母=len(selected), 予定量既知=len(known), 予定量未知=len(selected)-len(known),
                q0公開=zero, 正量公開=len(known)-zero,
                q0割合_全公開分母=zero/len(selected) if selected else None,
                q0割合_予定量既知分母=zero/len(known) if known else None,
                数量分布=dict(Counter(str(r['sizing']['proposed_quantity']) for r in known)))


def run() -> None:
    """
    機能: 許可後だけ保存tradegate33を各一読し、299公開の当時リスク入力を射影する。
    引数: なし。
    返り値: None。数量金融・remainingbudget・NPZ・原JSON・APIは運転しない。
    """
    plan_path = common.HERE/'公開299予定リスクの非金融固定計画.json'
    fixed = common.read_json(plan_path)
    assert fixed['全合格'] and fixed['source_SHA256'] == common.sources()
    assert common.digest(common.ROOT/fixed['入力元']['path']) == fixed['入力元']['SHA256']
    for source, sha in fixed['小source契約'].items():
        assert common.digest(common.ROOT/source) == sha
    assert common.digest(common.ROOT/fixed['owner_artificial']['path']) == fixed['owner_artificial']['SHA256']
    common.write(common.HERE/'公開予定リスク測定開始.json', dict(全合格=True, 計画SHA256=common.digest(plan_path), 新金融=0))
    rows = []
    per_session = {}
    checks = Counter()
    started = time.monotonic()
    for session in fixed['sessions']:
        item = fixed['input33'][session]
        saved = (common.ROOT/item['path']).read_bytes()
        assert hashlib.sha256(saved).hexdigest() == item['SHA256']
        packet = pickle.loads(gzip.decompress(saved))
        assert packet['session'] == session
        checks['tradegate33別目的一読'] += 1
        per_session[session] = {}
        for symbol in ('TOPIX', 'NK225'):
            account = packet['accounts'][symbol]
            entries = account['feed'][account['feed'][:, 7] == 1]
            own = []
            for entry in entries:
                normal_row, side, parent = int(entry[0]), int(entry[3]), int(entry[2])
                assert side in (-1, 1) and int(entry[4]) == risk.CAP[symbol]
                base = account['trade_features']['60'][normal_row]
                raw_row = int(account['mapping'][normal_row])
                seq = int(account['record']['seq'][normal_row])
                stamp = float(account['record']['time_s'][normal_row])
                assert math.isfinite(stamp)
                assert base['candidate_raw_row'] == raw_row and base['candidate_raw_seq'] == seq
                assert base['candidate_price_time_s'] == stamp
                checks['公開原行時計一致'] += 1
                atr = float(entry[9])
                bid, ask = float(account['quotes']['bid'][normal_row]), float(account['quotes']['ask'][normal_row])
                sizing = risk.measure(atr, bid, ask, symbol)
                if not bool(account['quotes']['quote_valid'][normal_row]):
                    sizing = dict(known=False, reason=16, proposed_quantity=None, risk_by_quantity=[],
                                  budget_yen=risk.BUDGET[symbol], maximum_quantity=risk.CAP[symbol],
                                  paper_stop_atr=risk.PAPER_STOP_ATR)
                public = dict(session=session, symbol=symbol, paper_parent=parent, side=side,
                    publish_normal_row=normal_row, raw_row=raw_row, raw_seq=seq, price_time_s=stamp,
                    JST=datetime.fromtimestamp(stamp, timezone(timedelta(hours=9))).isoformat(),
                    ATR=atr if math.isfinite(atr) else None,
                    bid=bid if math.isfinite(bid) else None, ask=ask if math.isfinite(ask) else None,
                    quote_valid=bool(account['quotes']['quote_valid'][normal_row]), original_qty=int(entry[4]),
                    published_Last=float(entry[5]), W60=base,
                    old_gate={mode: dict(zip(('allowed', 'reason'), risk.gate(base, mode)))
                              for mode in ('VETO', 'CONFIRM', 'KNOWN_VETO')}, sizing=sizing)
                rows.append(public)
                own.append(public)
            per_session[session][symbol] = {mode: group(own, None if mode == '全公開' else mode)
                                           for mode in ('全公開', 'VETO', 'CONFIRM', 'KNOWN_VETO')}
        del saved, packet
        print(session+' 公開ATR/BBOと予定整数量を小射影、金融0', flush=True)
    assert checks['tradegate33別目的一読'] == 33 and len(rows) == 299
    summary = {}
    for symbol in ('TOPIX', 'NK225'):
        own = [r for r in rows if r['symbol'] == symbol]
        summary[symbol] = {mode: group(own, None if mode == '全公開' else mode)
                           for mode in ('全公開', 'VETO', 'CONFIRM', 'KNOWN_VETO')}
        assert summary[symbol]['全公開']['公開分母'] == fixed['expected'][symbol]['publish']
        for mode in ('VETO', 'CONFIRM', 'KNOWN_VETO'):
            assert summary[symbol][mode]['公開分母'] == fixed['expected'][symbol][mode]
            checks['元門分母一致'] += 1
    assert fixed['source_SHA256'] == common.sources()
    common.write(common.HERE/'公開299のATR両気配と予定数量可用性.json', dict(
        全合格=True, 計画SHA256=common.digest(plan_path), source_SHA256=fixed['source_SHA256'],
        入力元=fixed['入力元'], witness=rows, 商品別=summary, 各場=per_session, 一致検査=dict(checks),
        分母=fixed['分母'], Gate別=fixed['Gate別'],
        計算=fixed['計算'], 予算=risk.BUDGET, 元初回上限=risk.CAP, 紙上停止係数=risk.PAPER_STOP_ATR,
        説明='q0はこの予定式で最小1枚を受け付けられない公開候補。勝ち・利益・実無取引とは判定していない。',
        初回全予算のみ=True, remainingbudget運転=False, 実busy判定=False, fill後数量選択=False,
        大型読取=33, NPZ=0, 原板=0, 原paper再計算=0, 新金融=0, 登録変更=0, API=0,
        開始終端source不変=True, 経過秒=time.monotonic()-started))
    print('299公開の予定数量可用性を保存。金融0、実口座運転0。', flush=True)


def main() -> None:
    """
    機能: 静的固定又は根が明示した非金融小射影を一回だけ実行する。
    引数: CLI --fix-only/--root-measurement-reviewed(bool)。
    返り値: None。自動再開始・新金融・現在APIの経路はない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--fix-only', action='store_true')
    parser.add_argument('--root-measurement-reviewed', action='store_true')
    args = parser.parse_args()
    assert args.fix_only != args.root_measurement_reviewed
    if args.fix_only:
        fix()
        return
    assert not (common.HERE/'公開予定リスク測定開始.json').exists()
    assert not (common.HERE/'公開予定リスク測定False.json').exists()
    assert not (common.HERE/'公開299のATR両気配と予定数量可用性.json').exists()
    try:
        run()
    except Exception:
        common.write(common.HERE/'公開予定リスク測定False.json', dict(
            全合格=False, 原因=traceback.format_exc(), 自動再開始=False, 新金融=0, 原板=0, NPZ=0, API=0))
        raise


if __name__ == '__main__':
    main()
