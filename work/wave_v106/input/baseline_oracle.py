"""正常基準の欠落を、手作り小入力と独立した不明値期待で確かめる。"""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def run() -> dict:
    """
    機能: 基準原行の非対応を数値又は未来正常行で補わないことを独立人工で確認する。
    引数: なし。
    返り値: dictは1種類の物理境界の検査件数。正式入力や金融を読まない。
    """
    name = '106正常基準欠落の独立人工だけの当時特徴'
    spec = importlib.util.spec_from_file_location(name, HERE/'features.py')
    target = importlib.util.module_from_spec(spec)
    sys.modules[name] = target
    spec.loader.exec_module(target)
    checks = 0
    for symbol in ('TOPIX', 'NK225'):
        for side in (-1, 1):
            for published_known in (False, True):
                raw = dict(raw_seq=np.arange(5, dtype=np.int64)+9007199254740993,
                    price_time_s=1000.+np.arange(5, dtype=float), bid=np.array([100.,101.,102.,103.,104.]),
                    ask=np.array([100.5,101.5,102.5,103.5,104.5]), bbo_valid=np.ones(5, bool),
                    qualified=np.array([False,True,True,True,True]),
                    normal_execution_row=np.array([-1,0,1,2,3],np.int32),
                    execution_to_raw_index=np.array([1,2,3,4],np.int64),
                    price_reset_reason=np.zeros(5,np.uint16))
                record = dict(tick=.5, seq=raw['raw_seq'][1:].copy(), time_s=raw['price_time_s'][1:].copy(),
                    bid=raw['bid'][1:].copy(), ask=raw['ask'][1:].copy(), quote_valid=np.ones(4,bool))
                packet = dict(raw={symbol:raw}, normal={symbol:dict(record=record)})
                candidate = dict(side=side, raw_row=2, normal_row=1)
                public = dict(window_seconds=10, baseline=dict(raw_row=0,raw_seq=int(raw['raw_seq'][0])),
                    public_endpoint=dict(raw_row=2,raw_seq=int(raw['raw_seq'][2])),
                    legacy_unknown_reason=0 if published_known else 4, selection_unknown_reason=0,
                    ambiguous=False, ambiguous_spread=False, ambiguous_sign=False,
                    observed_known=published_known)
                actual = target.normal_path_measure(packet,symbol,candidate,public)
                assert not actual['known'] and not actual['observed_known']
                assert actual['normal_baseline_unmapped'] and actual['tail_unknown'] and actual['count']==0
                assert actual['path_source'] is None and actual['best'] is None
                for field in ('directional_net_ticks','total_variation_ticks','efficiency','max_adverse_ticks','retreat_from_best_ticks'):
                    assert actual[field] is None,field
                assert actual['baseline']['raw_row']==0 and actual['endpoint']['raw_row']==2
                checks += 1
                # ----------------------------------------
                # 基準の次正常行や候補後の価格を変えても、不明を数値へ救済しない。
                changed = deepcopy(packet)
                changed['raw'][symbol]['bid'][1] += 999.
                changed['raw'][symbol]['ask'][1] += 999.
                changed['normal'][symbol]['record']['bid'][0] += 999.
                changed['normal'][symbol]['record']['ask'][0] += 999.
                changed['raw'][symbol]['bid'][3:] += 99999.
                changed['raw'][symbol]['ask'][3:] += 99999.
                changed['normal'][symbol]['record']['bid'][2:] += 99999.
                changed['normal'][symbol]['record']['ask'][2:] += 99999.
                future = target.normal_path_measure(changed,symbol,candidate,public)
                assert actual==future
                checks += 1
    return dict(全合格=True, 人工専用=True, 境界種類=1, 独立検査件数=checks,
        定義='基準原行map=-1なら既知/不明の公表旗にかかわらず全normal経路はUNKNOWN。基準rowは維持、次正常row探索0。',
        source_SHA256=hashlib.sha256((HERE/'features.py').read_bytes()).hexdigest(),
        正式packet読取=0, 新金融再生=0, 原本読取=0, API取得=0)
