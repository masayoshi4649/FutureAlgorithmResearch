"""新反対票の推論部品だけを独立集合差に接続する。信号stateはまだ未固定。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/e01_current_reassessment_20261015/prepare/window_evidence.py'
OUTPUT = HERE/'新反対票下限部品だけの独立SOURCE_ONLY接続.json'
CHECKS = []


def check(ok: bool, label: str) -> None:
    """
    機能: 独立の集合差期待と部品の判断を照合する。
    引数: ok(bool)、label(str) は判断と分類。
    返り値: None。不一致は停止する。
    """
    assert bool(ok), label
    CHECKS.append(label)


def observation(up: list[int], down: list[int], first: int, end: int) -> dict:
    """
    機能: 原行の買売票集合を直接数え、型を明示した人工窓を作る。
    引数: up/down(list[int])、first/end(int) は人工票と範囲。
    返り値: dict は同源同窓の人工。ownerのfixtureは使わない。
    """
    return dict(known=True, reason=0, known_continuously_from_previous=True,
        source_SHA256='独立合成同一源', window_seconds=60,
        first_vote_raw_row=first if first <= end else -1,
        candidate_raw_row=end, candidate_raw_seq=end+1000,
        candidate_price_time_s=300.+end,
        up_votes=sum(up[first:end+1]), down_votes=sum(down[first:end+1]))


def main() -> None:
    """
    機能: 完成推論source一つだけの境界を検証し、信号本体の完成とは区別する。
    引数: なし。
    返り値: None。元cache・金融・APIを読まず、owner源を変更しない。
    """
    assert not OUTPUT.exists()
    saved = SOURCE.read_bytes()
    source_sha = hashlib.sha256(saved).hexdigest()
    snapshot = HERE/'新反対票推論の私有複製.py'
    assert not snapshot.exists()
    snapshot.write_bytes(saved)
    spec = importlib.util.spec_from_file_location('independent_window_infer', snapshot)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    examples = []
    tapes = [([0]*8, [0]*8), ([1]*8, [0]*8), ([0]*8, [1]*8),
             ([1,0,0,1,0,0,0,1], [0,0,1,0,1,1,0,0]),
             ([0,0,1,0,0,1,0,0], [1,1,0,0,1,0,1,0])]
    ranges = [(0,3,0,7), (0,3,2,7), (0,2,4,7), (2,2,6,7),
              (4,3,4,7), (0,3,8,7), (4,3,8,7), (3,3,4,4)]
    for up, down in tapes:
        for s0, r0, s1, r1 in ranges:
            a, b = observation(up, down, s0, r0), observation(up, down, s1, r1)
            for side, tape, key in ((1, down, 'down_votes'), (-1, up, 'up_votes')):
                value = owner.infer(a, b, side)
                old_rows = set(range(s0,r0+1))
                new_rows = set(range(s1,r1+1))
                new_retained = sum(tape[row] for row in new_rows-old_rows)
                old_expired = sum(tape[row] for row in old_rows-new_rows)
                delta = new_retained-old_expired
                check(value['count_change'] == delta and value['opposite_counter'] == key, '独立集合差と買売対称')
                check(value['new_opposite_updates_lower_bound'] == max(0,delta) <= sum(tape[r0+1:r1+1]), '全新票数の下限であり失効相殺を許す')
                check(value['exact_new_opposite_updates'] == (delta if s0 == s1 else None), '同firstだけ追加票exact')
                check(value['positive_change_proves_new_opposite_update'] == (delta > 0), '正増分の存在証明')
                check(value['zero_or_negative_change_does_not_prove_absence'] == (s0 != s1 and delta <= 0), '窓始前進の零負差から活動停止を推論しない')
                examples.append(dict(side=side, old_interval=[s0,r0], new_interval=[s1,r1], delta=delta,
                                     lower_bound=value['new_opposite_updates_lower_bound'], exact=value['exact_new_opposite_updates']))
    a = observation([0]*8,[0,1,0,1,0,0,1,0],0,3)
    b = observation([0]*8,[0,1,0,1,0,0,1,0],0,7)
    same_clock = dict(b, candidate_price_time_s=a['candidate_price_time_s'])
    check(owner.infer(a,same_clock,1)['exact_new_opposite_updates'] == 1, '同clock候補原行前進は新票を含み得る')
    for key in ('known', 'known_continuously_from_previous'):
        value = owner.infer(a,dict(b,**{key:False}),1)
        check(value['new_opposite_updates_lower_bound'] is None and value['exact_new_opposite_updates'] is None, '未知又は未知跨ぎはdebug票推論を停止')
    bad_values = [('source_SHA256','別源'),('window_seconds',30),('candidate_raw_seq',1000),
                  ('candidate_raw_row',2),('candidate_price_time_s',200.),('first_vote_raw_row',-1),
                  ('first_vote_raw_row',9),('reason',8),('up_votes',-1)]
    for key, wrong in bad_values:
        try:
            owner.infer(a,dict(b,**{key:wrong}),1)
        except AssertionError:
            CHECKS.append('source窓候補系譜clock正票空範囲の不整合拒否')
        else:
            raise AssertionError('不整合を許可 '+key)
    late = observation([0]*8,[0,1,0,1,0,0,1,0],2,3)
    early = observation([0]*8,[0,1,0,1,0,0,1,0],0,7)
    try:
        owner.infer(late,early,1)
    except AssertionError:
        CHECKS.append('窓始後退の偽新票を拒否')
    else:
        raise AssertionError('窓始後退を許可')
    check(hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_sha, '推論source開始終端不変')
    value = dict(全合格=True,状態='推論部品一つの完成sourceへの独立接続。信号state/正式spec/新金融は未完成。',
        source_path=SOURCE.relative_to(ROOT).as_posix(),source_SHA256=source_sha,
        監査source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),検査数=len(CHECKS),検査=CHECKS,人工例=examples,
        判定='方向別範囲和の新反対票下限とsamefirst exactだけを確認。count水準/釣合い改善を新票として扱わない。',
        未測=['実データのknown連続性','最後の個別新票seq','非追従と再進行の実場面','新アルゴの先着率と収支'],
        実cache=0,金融本文=0,新金融=0,NPZ=0,実台帳=0,原board=0,API=0,共有編集=0)
    OUTPUT.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('推論部品だけの独立接続 '+str(len(CHECKS))+'合格。SHA '+hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        p=HERE/'推論部品接続初版False.json'
        assert not p.exists()
        p.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),検査=CHECKS,元cache=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
