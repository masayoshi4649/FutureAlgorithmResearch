"""二市場入口分類のstrict過去・同時計先頭・未知と未来不変を人工で確認する。"""

import json
from pathlib import Path

import numpy as np

import core


def fixture() -> tuple[dict, dict, dict]:
    """
    機能: 同時計更新と支持・逆行のある小さい価格代理時計素材を作る。
    引数: なし。
    返り値: tuple[dict,dict,dict]は原行、公表源、保存104と同じ数値規則。
    """
    times = np.array([0., 10., 10., 20., 30., 40., 50., 60., 70.])
    bid = np.arange(len(times), dtype=float)+100.; bid[2] = 150.
    raw = dict(raw_seq=np.arange(len(times), dtype=np.int64), price_time_s=times,
        bid=bid, ask=bid+1., bbo_valid=np.ones(len(times), bool), qualified=np.ones(len(times), bool),
        price_reset_reason=np.zeros(len(times), np.uint16))
    rows = np.array([0, 1, 3, 4, 5, 6, 7, 8], np.int64)
    public = dict(rows=rows, raw_seq=raw['raw_seq'][rows], times=times[rows])
    policy = dict(max_public_gap_seconds=15., baseline_extra_age_seconds=15.,
        spread_max_ticks=2., spread_increment_ticks=1.)
    return raw, public, policy


def run() -> None:
    """
    機能: 自己同時許可・相手同時禁止・unknown/曖昧・接頭不変を純人工検査する。
    引数: なし。
    返り値: None。金融結果や原板は読まず所有領域へ証跡を保存する。
    """
    raw, public, policy = fixture(); f = core.public_windows(raw, public, 1., policy); checks = []
    own = core.observe(raw, f, 70., 30, 8, False)
    peer = core.observe(raw, f, 70., 30, None, True)
    assert own['source']['raw_seq'] == 8 and peer['source']['raw_seq'] == 7
    assert own['direction'] == peer['direction'] == 1
    checks.append('自己同時計公表可、相手は同時計禁止・strictpast')
    assert core.acceptance(own, peer, 1, 'P') == (True, '採用')
    assert core.acceptance(own, peer, -1, 'N') == (False, '相手逆方向')
    checks.append('方向支持と相手反対なしを区別')
    before = core.observe(raw, f, 10., 10, 2, False)
    assert before['source']['raw_seq'] == 1 and before['source']['bid'] == 101.
    checks.append('同時計後半のbid150を公表先頭へ差し替えない')
    bad = {k:v.copy() for k,v in raw.items()}; bad['qualified'][1] = False
    unknown = core.observe(bad, core.public_windows(bad, public, 1., policy), 10., 10, 2, False)
    assert unknown['state'] == 'UNKNOWN'
    checks.append('同時計先頭の資格不足を後半の正常で救済しない')
    reset = {k:v.copy() for k,v in raw.items()}; reset['price_reset_reason'][6] = 8
    observed = core.observe(reset, core.public_windows(reset, public, 1., policy), 70., 30, 8, False)
    assert observed['state'] == 'UNKNOWN'
    checks.append('inclusive区間内の時計resetでUNKNOWN')
    thin = {k:v.copy() for k,v in raw.items()}; thin['ask'][8] += 5.
    ambiguous = core.observe(thin, core.public_windows(thin, public, 1., policy), 70., 30, 8, False)
    assert ambiguous['state'] == 'AMBIGUOUS' and not core.acceptance(ambiguous, peer, 1, 'P')[0]
    checks.append('spread拡大AMBIGUOUSをneutral扱いしない')
    assert core.observe(raw, f, 5., 60, 0, False)['state'] == 'UNKNOWN'
    assert core.observe(raw, f, 100., 30, None, True)['state'] == 'UNKNOWN'
    checks.append('不足窓・相手公表年齢超過はUNKNOWN')
    cropped = {k:v[:8].copy() for k,v in raw.items()}
    cropped_public = {k:v[:-1].copy() for k,v in public.items()}
    old_peer = core.observe(cropped, core.public_windows(cropped, cropped_public, 1., policy), 70., 30, None, True)
    assert old_peer == peer
    checks.append('当時計以後の追加行によらず相手採用と数値が不変')
    neutral = dict(peer, direction=0, state='NEUTRAL')
    assert core.acceptance(own, neutral, 1, 'N')[0] and not core.acceptance(own, neutral, 1, 'P')[0]
    checks.append('Nは既知neutralを許可、Pは支持を要求')
    here = Path(__file__).resolve().parent; target = here/'二市場入口分類の人工検査.json'
    assert not target.exists()
    target.write_text(json.dumps(dict(全合格=True, 検査数=len(checks), 検査=checks,
        新金融=0, 新注文=0, 原本再読取=0, API=0), ensure_ascii=False, indent=2)+'\n', encoding='utf8', newline='\n')
    print('入口分類の小人工'+str(len(checks))+'項目合格', flush=True)


if __name__ == '__main__':
    run()
