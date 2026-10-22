"""既選定の場だけで、同じ約定時点の観測Lastと実気配約定を符号付き分解する。"""

import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SUBJECT = HERE / 'completed/選択単体と三枠の負け上位及び勝ち対照の具体診断.json'
SHA = 'aade9284f69c748bad2cf64c3c573ce00a61450be55eb62e7a1b95057d3f3753'
OUT = HERE / 'same_time_last_cost'


def digest(value: bytes) -> str:
    """
    機能: 読み取ったbytesの同一性を求める。
    引数: value(bytes) は許可された既選定資料。
    返り値: str はSHA256。
    """
    return hashlib.sha256(value).hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 同時点分解だけの新しい所有証跡を保存する。
    引数: path(Path)、value(dict) は有限な原始型資料。
    返り値: None。元資料又は旧成果を上書きしない。
    """
    assert not path.exists() and path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def decomposition(legs: np.ndarray, quotes: dict, multiplier: float) -> list[dict]:
    """
    機能: 同じ実新規・返済原rowのLast差と、両側の価格差及び料を分離する。
    引数: legs(float[M,16]) は実返済脚、quotes(dict) は既保存正常気配、multiplier(float)。
    返り値: list[dict] は脚別恒等式。Lastでの仮想約定や新しい売買は作らない。
    """
    result = []
    for leg in legs:
        side, q, er, xr = int(leg[5]), int(leg[6]), int(leg[1]), int(leg[2])
        ei, xi = np.flatnonzero(quotes['row'] == er), np.flatnonzero(quotes['row'] == xr)
        assert len(ei) == len(xi) == 1
        ei, xi = int(ei[0]), int(xi[0])
        le, lx, e, x = float(quotes['last'][ei]), float(quotes['last'][xi]), float(leg[7]), float(leg[8])
        assert all(math.isfinite(v) and v > 0 for v in (le, lx, e, x))
        lastgross = side * (lx - le) * q * multiplier
        inadverse = side * (e - le) * q * multiplier
        outadverse = side * (lx - x) * q * multiplier
        actualgross = side * (x - e) * q * multiplier
        fee = float(leg[10] + leg[11])
        assert abs(actualgross - float(leg[9])) <= 1e-5
        assert abs(actualgross - lastgross + inadverse + outadverse) <= 1e-5
        assert abs(actualgross - fee - float(leg[12])) <= 1e-5
        result.append(dict(parent=int(leg[0]), entry_raw_row=er, exit_raw_row=xr,
            entry_price_time_s=float(leg[3]), exit_price_time_s=float(leg[4]), side=side, quantity=q,
            entry_fill=e, exit_fill=x, entry_last=le, exit_last=lx,
            entry_bid=float(quotes['bid'][ei]), entry_ask=float(quotes['ask'][ei]),
            exit_bid=float(quotes['bid'][xi]), exit_ask=float(quotes['ask'][xi]),
            last_gross=lastgross, actual_gross=actualgross, entry_adverse=inadverse,
            exit_adverse=outadverse, adverse_total=inadverse+outadverse, fee=fee, net=float(leg[12])))
    return result


def summary(rows: list[dict]) -> dict:
    """
    機能: 不利差を負値も保持したまま集計する。
    引数: rows(list[dict]) は脚別又は既集計の同じ金額列。
    返り値: dict は円額合計。別商品を円額で順位付けしない。
    """
    keys = ('last_gross', 'actual_gross', 'entry_adverse', 'exit_adverse', 'adverse_total', 'fee', 'net')
    result = {key: float(sum(r[key] for r in rows)) for key in keys}
    assert abs(result['last_gross'] - result['adverse_total'] - result['fee'] - result['net']) <= 1e-4
    return result


def execute() -> None:
    """
    機能: 根の目的別解析授権後に、会計監査の既所有copyを各一読し射影する。
    引数: なし。計画固定済みの診断対象以外へ範囲を増やさない。
    返り値: None。新金融・元市場再読・実売買は行わない。
    """
    raw = SUBJECT.read_bytes()
    assert digest(raw) == SHA and not OUT.exists()
    subject = json.loads(raw)
    save(OUT / 'Last分解の追加目的と既対象固定.json', dict(小射影SHA256=SHA, 根追加目的='同時刻Lastと気配約定の符号付き恒等式',
        原cache追加読取=0, 既所有copy目的別読取予定=21, 原市場再読=0, 金融再生=0, 対象=subject['read_log'],
        source_SHA256=digest(Path(__file__).read_bytes()),
        留保='初回診断のLast不足を申告後、audit119の会計復元時の同bytes保全copyが確認できた。根の目的別解析指示に従い原cacheは再読しない。'))
    copies, read_log = {}, []
    for i, meta in enumerate(subject['read_log']):
        owned = ROOT / 'work/stability119_20261017/audit_result119/recovered_owned'
        owned = owned.joinpath(*Path(meta['path']).parts[-3:])
        assert owned.is_relative_to(ROOT / 'work/stability119_20261017/audit_result119/recovered_owned')
        payload = owned.read_bytes()
        assert digest(payload) == meta['SHA256']
        copy = OUT / 'cache_copies' / (str(i).zfill(2)+'.npz')
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(payload)
        with np.load(BytesIO(payload), allow_pickle=False) as data:
            copies[meta['path']] = {key: data[key].copy() for key in data.files
                if key == 'ledger' or key.startswith('quotes__')}
        read_log.append(dict(**meta, 読取元所有copy=str(owned.relative_to(ROOT)),
                             再保全copy=str(copy.relative_to(ROOT)), 今回原cache読取=0, 今回所有copy目的別読取=1))
    scenes = []
    for detail in subject['details']:
        symbol, scene, mid = detail['symbol'], detail['session'], detail['id']
        pm = next(r for r in read_log if r['kind'] == 'prepared' and f'/{symbol}/' in r['path'] and scene+'.npz' in r['path'])
        base = copies[pm['path']]
        quotes = {key[8:]: value for key, value in base.items() if key.startswith('quotes__')}
        if mid == 'PORT':
            lm = next(r for r in read_log if r['kind'] == 'portfolio' and f'/{symbol}/' in r['path'] and scene+'.npz' in r['path'])
            ledger = copies[lm['path']]['ledger']
        else:
            slots = {p['slot'] for p in detail['親一覧']}
            assert len(slots) == 1
            ledger = base['ledger'][np.isin(base['ledger'][:, 0], list(slots))]
        legs = []
        for slot in np.unique(ledger[:, 0]):
            chosen = ledger[ledger[:, 0] == slot, 1:]
            legs.extend([dict(slot=int(slot), **r) for r in decomposition(chosen, quotes, 1000. if symbol == 'TOPIX' else 10.)])
        sums = summary(legs)
        assert abs(sums['net'] - detail['saved_summary']['net']) <= 1e-4
        assert abs(sums['fee'] - detail['saved_summary']['fees']) <= 1e-4
        scenes.append(dict(symbol=symbol, session=scene, method=mid, role=detail['role'],
                           親数=detail['台帳親数'], 脚数=len(legs), **sums, legs=legs))
    groups = []
    for symbol in ('TOPIX', 'NK225'):
        for kind in ('単体先頭', 'PORT'):
            for role in ('赤字上位', '勝ち反証'):
                selected = [s for s in scenes if s['symbol'] == symbol and s['role'] == role
                            and (s['method'] == 'PORT') == (kind == 'PORT')]
                groups.append(dict(symbol=symbol, method_group=kind, role=role, 場数=len(selected),
                                   親数=sum(s['親数'] for s in selected), **summary(selected)))
    save(OUT / '同じ実時点のLast方向損益と両側約定差及び料の分解.json',
         dict(全合格=True, 小射影SHA256=SHA, source_SHA256=digest(Path(__file__).read_bytes()),
              原市場再読=0, 新金融=0, API=0, 原cache追加読取=0, 既所有copy目的別読取=len(read_log), read_log=read_log,
              groups=groups, scenes=scenes,
              留保='同じ実新規・返済時点を固定した記述。Lastは約定可能価格でなく、退出判断をLastへ変えた新手法成績でもない。符号付き不利差は有利差なら負のまま。'))
    for group in groups:
        print(json.dumps(group, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='根の目的別解析指示で既所有copyだけを同時点Last分解する。')
    parser.add_argument('--root-authorized-additional-purpose', action='store_true')
    args = parser.parse_args()
    assert args.root_authorized_additional_purpose
    execute()
