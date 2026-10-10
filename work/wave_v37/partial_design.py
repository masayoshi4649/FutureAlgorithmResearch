"""同じ元組の減量と復元を、結果を見る前の有限格子へ固定する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SIGNALS = tuple(f'H{i:03d}' for i in (3, 11, 19, 27, 35, 43, 51, 59, 67, 75, 83, 91))
CONDITIONS = ('B00', 'B01', 'B02', 'B03', 'B06', 'B07', 'B08', 'B09')
PRIMARY_POLICY = 'B06_RB06_F50_N1'
PRIMARY_ID = 'H019__' + PRIMARY_POLICY + '__V000'
COMPARISON_POLICIES = ('A0', 'CORE50', 'SMALL50', 'B06_NONE_F50', PRIMARY_POLICY)


def digest(path: Path) -> str:
    """機能: ファイルの内容を指紋へ固定する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def policies() -> list[dict]:
    """機能: 基準5、信号復元256、減量のみ16、時計復元32を列挙する。

    引数: なし。返り値: 全309管理 (list[dict])。
    """
    rows = [dict(id='A0', kind='baseline', reduce_fraction=0., max_reductions=0,
        bad_id=None, good_id=None, restore_mode='none', restore_seconds=120.)]
    for fraction in (.25, .5):
        for name, kind in (('CORE', 'static_core'), ('SMALL', 'static_split')):
            rows.append(dict(rows[0], id=name + str(round(fraction * 100)), kind=kind, reduce_fraction=fraction))
    for bad in CONDITIONS:
        for fraction in (.25, .5):
            common = dict(kind='dynamic', reduce_fraction=fraction, bad_id=bad, restore_seconds=120.)
            label = f'{bad}_NONE_F{round(fraction * 100):02d}'
            rows.append(dict(common, id=label, good_id=bad, restore_mode='none', max_reductions=1))
            for maximum in (1, 3):
                label = f'{bad}_T120_F{round(fraction * 100):02d}_N{maximum}'
                rows.append(dict(common, id=label, good_id=bad, restore_mode='timer', max_reductions=maximum))
                for good in CONDITIONS:
                    label = f'{bad}_R{good}_F{round(fraction * 100):02d}_N{maximum}'
                    rows.append(dict(common, id=label, good_id=good, restore_mode='signal', max_reductions=maximum))
    assert len(rows) == len({r['id'] for r in rows}) == 309
    assert len([r for r in rows if r['restore_mode'] == 'signal']) == 256
    assert len([r for r in rows if r['restore_mode'] == 'timer']) == 32
    assert len([r for r in rows if r['kind'] == 'dynamic' and r['restore_mode'] == 'none']) == 16
    assert any(r['id'] == PRIMARY_POLICY for r in rows)
    return deepcopy(rows)


def condition(signal: str, policy: dict, variant: str = 'V000', role: str = 'main',
              entry_scale: float = 1., bad_scale: float = 1., good_scale: float = 1.,
              observed_fill: bool = False) -> dict:
    """機能: 管理機構と入口・窓・約定診断を一意の仕様へ結合する。

    引数: signal/variant/role (str)、policy (dict)、各scale (float)、observed_fill (bool)。
    返り値: 一条件 (dict)。
    """
    return dict(id=signal + '__' + policy['id'] + '__' + variant, signal_id=signal,
        policy=deepcopy(policy), variant_id=variant, role=role, entry_scale=entry_scale,
        bad_scale=bad_scale, good_scale=good_scale, observed_fill=observed_fill,
        random_seed=None, primary=signal == 'H019' and policy['id'] == PRIMARY_POLICY and variant == 'V000')


def catalog() -> list[dict]:
    """機能: 主309と、成績で選ばない診断54を固定する。

    引数: なし。返り値: 全363条件 (list[dict])。
    """
    managers = policies(); by_id = {p['id']: p for p in managers}
    rows = [condition('H019', p) for p in managers]
    for signal in SIGNALS:
        if signal == 'H019':
            continue
        for manager in ('A0', PRIMARY_POLICY, 'B06_NONE_F50'):
            rows.append(condition(signal, by_id[manager], role='diagnostic'))
    for variant, scale in (('E080', .8), ('E120', 1.2)):
        for manager in COMPARISON_POLICIES:
            rows.append(condition('H019', by_id[manager], variant, 'diagnostic', entry_scale=scale))
    for manager in COMPARISON_POLICIES:
        rows.append(condition('H019', by_id[manager], 'O000', 'diagnostic', observed_fill=True))
    for variant, scale in (('D080', .8), ('D120', 1.2)):
        for manager in (PRIMARY_POLICY, 'B06_NONE_F50'):
            rows.append(condition('H019', by_id[manager], variant, 'diagnostic', bad_scale=scale))
    for variant, scale in (('R080', .8), ('R120', 1.2)):
        rows.append(condition('H019', by_id[PRIMARY_POLICY], variant, 'diagnostic', good_scale=scale))
    assert len(rows) == len({r['id'] for r in rows}) == 363
    assert sum(r['role'] == 'main' for r in rows) == 309
    assert sum(r['primary'] for r in rows) == 1
    return rows


def supplementary() -> list[dict]:
    """機能: 主方式の回復だけを公開機会ごとの64符号対照へ置換する。

    引数: なし。返り値: 補助64条件 (list[dict])。最良seedを採用しない。
    """
    source = next(r for r in catalog() if r['primary'])
    return [dict(deepcopy(source), id='H019__' + PRIMARY_POLICY + f'__U{seed:03d}',
        variant_id=f'U{seed:03d}', role='supplementary', primary=False, random_seed=seed)
        for seed in range(64)]


def rules() -> dict:
    """機能: 数量枠・約定優先・予算・比較解釈を一箇所に固定する。

    引数: なし。返り値: 共通機械仕様 (dict)。
    """
    return dict(主仮説=PRIMARY_ID, 主格子数=309, 診断数=54, 全主再生条件数=363, 補助条件数=64,
        初回枚数={'TOPIX': 5, 'NK225': 10}, 片方向上限={'TOPIX': 10, 'NK225': 20},
        円倍率={'TOPIX': 1000., 'NK225': 10.}, 費用=0, 影は実口座から独立=True,
        初期R='全方式共通で元q0×元A0。小数量でも共有。実初回枚数×A0は参考尺度として別表示。',
        影継承='初回ATR、方向、元建値、初期R、期限、価格ストップ、2ATR利確、3ATR追跡、次組の休止を変更しない。',
        枠='1..q0。影2ATRは小番号floor(q0/2)枠を永久終了。空き枠も復元権を消す。',
        減量='影生存nに対しmin(n-1,max(1,floor(f*n)))を小さい生存番号から閉じる。最低1枠残す。',
        復元='調整で空いて影が生存する枠のみ。元利確済み枠を買い直さず、損益を許否に使わない。',
        新情報='判断行のsource_rowが直前の組開始/減量約定/復元約定/競合取消行より後。source_rowはready配列行。',
        時計復元='減量約定120秒後以降に公開された新しい有効自市場行で判断。source行の公開時刻も期限以上を要求。方向0可、peer同意不要、欠測/期限切れ不可。',
        予約='判断した行の次の有効原本行で調整を成行執行。当行に逆の調整を再予約しない。',
        優先='元A0で有効な全返済/部分利確→実口座予算全返済→予約済み調整。元部分利確時の調整予約は取消。',
        元全返済='前行から有効だった条件を実にも並行配置し、影の終了後へ保有しない。終了行を事後コピーしない。',
        予算='組内全実現＋全含みが-元R以下なら次有効行への全返済予約。元返済と競合する行は元を優先し、部分利確後も予算予約を保持。追加遅延/超過を記録し、R以内や必ず次一行で全返済の保証としない。',
        固定コア='初回の低番号floor(f*q0)枠を永久に不保有。残枠だけ元返済に従う。',
        小数量半分利確='qs=q0-floor(f*q0)。元利確ブロック小番号floor(qs/2)枠と元残ブロック大番号qs-floor(qs/2)枠だけ初回保有。退出価格は影共通。',
        乱数='元B06方向×公開source rawseqごとのSHA256符号。v37|seed|session|symbol|rawseq、先頭8byte littleの偶奇。元非0機会を保持。',
        再参加='先に実が終了しても旧影組へ再参加しない。復元権・回数・期限を次組へ持ち越さない。',
        比較='銘柄別の全13/後7/週/全セッション、返済脚の金額枚数と組収支・初回R・時価DD・純枚数分を分ける。',
        データ='全13既知。初期6は祝日開始へ偏る。現在APIも保存ライブも使わない。',
        未達時='主仮説を格子最良へ差し替えない。追加機序は次の仮説として別扱い。')


def freeze() -> dict:
    """機能: 格子と共通規則の設計を結果前に保存する。変更後の上書きは拒否する。

    引数: なし。返り値: 設計固定 (dict)。
    """
    value = dict(conditions=catalog(), supplementary=supplementary(), rules=rules(),
        実装SHA256=digest(Path(__file__)), 新損益読取=False)
    path = HERE / 'partial_design_fixed.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        assert {k: v for k, v in old.items() if k != '固定日時'} == value
        return old
    value['固定日時'] = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return value


if __name__ == '__main__':
    freeze()
    print('主309＋診断54、補助64の設計を固定。新損益なし。')
