"""改善8条件の反証と、復元方式の因果的な選択を事前設計する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SELECTED = (
    'B00_RB00_F25_N1', 'B00_T120_F25_N1', 'B00_T120_F25_N3',
    'B06_RB01_F25_N1', 'B06_RB01_F50_N1', 'B06_T120_F50_N3',
    'B07_T120_F25_N1', 'B07_T120_F50_N1',
)
PRIMARY_POLICY = 'B06_CHOICE_B01_F50_N1'
REVERSE_POLICY = 'B06_INVERT_B01_F50_N1'
CLOCK_POLICY = 'B06_T120_GB01_F50_N1'
PRIMARY_ID = 'H019__'+PRIMARY_POLICY+'__R1__V000'


def read(path: Path) -> object:
    """機能: 保存済みの設計を読み出す。

    引数: path (Path)。返り値: JSON内容 (object)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def policies() -> list[dict]:
    """機能: 改善8本と、同じ数量に対応する固定対照を列挙する。

    引数: なし。返り値: 重複IDのない管理条件 (list[dict])。
    """
    old = read(HERE.parent/'wave_v37/partial_design_fixed.json')
    lookup = {s['policy']['id']:s['policy'] for s in old['conditions']}
    found = read(HERE.parent/'wave_v37/全格子の機序診断.json')['A0同時改善IDs']
    assert set(found) == {'H019__'+p+'__V000' for p in SELECTED}
    names = ['A0','CORE25','CORE50','SMALL25','SMALL50',*SELECTED,'B06_RB06_F50_N1',
        'B00_NONE_F25','B06_NONE_F25','B06_NONE_F50','B07_NONE_F25','B07_NONE_F50',
        'B06_T120_F25_N1','B06_T120_F50_N1']
    rows = [dict(deepcopy(lookup[name]), branch_mode='fixed') for name in names]
    for name,mode in ((PRIMARY_POLICY,'adverse_signal'),(REVERSE_POLICY,'reverse')):
        rows.append(dict(deepcopy(lookup['B06_RB01_F50_N1']),id=name,branch_mode=mode))
    rows.append(dict(deepcopy(lookup['B06_T120_F50_N1']),id=CLOCK_POLICY,good_id='B01',branch_mode='fixed'))
    assert len(rows)==len({r['id'] for r in rows})==24
    return rows


def spec(policy: dict, variant: str='V000', role: str='mechanism', budget: bool=True,
         **changes) -> dict:
    """機能: 売買機構と、一軸ずつの変更を一意の条件へ結合する。

    引数: policy (dict)、variant/role (str)、budget (bool)、changes (dict)。
    返り値: 一条件 (dict)。
    """
    row = dict(id='H019__'+policy['id']+f'__R{int(budget)}__'+variant,
        signal_id='H019',policy=deepcopy(policy),variant_id=variant,role=role,
        budget_enabled=budget,entry_scale=1.,bad_scale=1.,good_scale=1.,branch_scale=1.,
        observed_fill=False,min_delay_seconds=0.,bad_seed=None,good_seed=None,
        branch_seed=None,branch_mode=policy['branch_mode'],primary=False)
    row.update(changes)
    row['primary']=row['id']==PRIMARY_ID
    return row


def catalog() -> list[dict]:
    """機能: 基本対照と、感度の一軸変更を成績で選ばず列挙する。

    引数: なし。返り値: 全主条件 (list[dict])。交差総当たりは行わない。
    """
    managers=policies(); by_id={p['id']:p for p in managers}
    rows=[spec(p,budget=budget) for p in managers for budget in (True,False)]
    # ----------------------------------------
    # 8本と選択・逆選択、前主案、対応する固定復元を同じ感度へ置く。
    targets=tuple(dict.fromkeys((*SELECTED,PRIMARY_POLICY,REVERSE_POLICY,
        'B06_RB06_F50_N1','B06_T120_F50_N1',CLOCK_POLICY)))
    for name in targets:
        p=by_id[name]
        for prefix,field in (('E','entry_scale'),('D','bad_scale')):
            for suffix,scale in (('080',.8),('120',1.2)):
                rows.append(spec(p,prefix+suffix,'sensitivity',**{field:scale}))
        if p['restore_mode']=='timer':
            for seconds in (96.,144.):
                modified=dict(p,restore_seconds=seconds)
                rows.append(spec(modified,'T'+str(int(seconds)),'sensitivity'))
        else:
            for suffix,scale in (('080',.8),('120',1.2)):
                rows.append(spec(p,'G'+suffix,'sensitivity',good_scale=scale))
        for seconds in (1.,5.,15.):
            rows.append(spec(p,'L'+str(int(seconds)).zfill(3),'sensitivity',min_delay_seconds=seconds))
        rows.append(spec(p,'O000','sensitivity',observed_fill=True))
    # ----------------------------------------
    # 選択時に読む長窓と、復元時に読む長窓・時計を別々にずらす。
    for name in (PRIMARY_POLICY,REVERSE_POLICY):
        for suffix,scale in (('080',.8),('120',1.2)):
            rows.append(spec(by_id[name],'C'+suffix,'sensitivity',branch_scale=scale))
        for seconds in (96.,144.):
            rows.append(spec(dict(by_id[name],restore_seconds=seconds),'T'+str(int(seconds)),'sensitivity'))
    for suffix,scale in (('080',.8),('120',1.2)):
        rows.append(spec(by_id[CLOCK_POLICY],'G'+suffix,'sensitivity',good_scale=scale))
    # ----------------------------------------
    # 元A0と少数量も同じ入口変形・伝達遅延・観測約定で比較する。
    for name in ('A0','CORE50','SMALL50'):
        for suffix,scale in (('080',.8),('120',1.2)):
            rows.append(spec(by_id[name],'E'+suffix,'sensitivity',entry_scale=scale))
        for seconds in (1.,5.,15.):
            rows.append(spec(by_id[name],'L'+str(int(seconds)).zfill(3),'sensitivity',min_delay_seconds=seconds))
        rows.append(spec(by_id[name],'O000','sensitivity',observed_fill=True))
    assert len(rows)==len({r['id'] for r in rows})
    assert sum(r['primary'] for r in rows)==1
    return rows


def supplementary() -> list[dict]:
    """機能: 減量・回復・分岐を分けた固定乱数の全対照を列挙する。

    引数: なし。返り値: 補助対照 (list[dict])。最良seedへ差し替えない。
    """
    by_id={p['id']:p for p in policies()};rows=[]
    for name in SELECTED:
        p=by_id[name]
        for seed in range(64):
            rows.append(spec(p,f'UB{seed:03d}','supplementary',bad_seed=seed))
            if p['restore_mode']=='signal':
                rows.append(spec(p,f'UG{seed:03d}','supplementary',good_seed=seed))
    for seed in range(64):
        rows.append(spec(by_id[PRIMARY_POLICY],f'UC{seed:03d}','supplementary',
            branch_mode='random',branch_seed=seed))
    assert len(rows)==len({r['id'] for r in rows})==768
    return rows


def rules() -> dict:
    """機能: 既知期間と結果前の変更点を分離して定義する。

    引数: なし。返り値: 共通規則 (dict)。
    """
    return dict(主仮説=PRIMARY_ID,対象8条件=list(SELECTED),
        初回枚数={'TOPIX':5,'NK225':10},片方向上限={'TOPIX':10,'NK225':20},
        円倍率={'TOPIX':1000.,'NK225':10.},費用=0,
        分岐='B06の減量約定行で既公開かつ有効なB01が保有と逆ならB01信号復元、その他は120秒時計復元。減量回ごと固定。',
        信号='減量後の新しい公開が保有方向を肯定したら元の生存枠まで復元。',
        時計='期限以降の新しい有効公開で復元。中立可、失効/欠測不可。',
        対応時計='主の時計分岐と同じB01公開source/validを使う固定時計GB01を追加。旧B06公開時計も別IDで保持。',
        原則='v37の元影枠、初期R、元部分利確、期限、取消・予約優先を継承。復元で損失や期限をリセットしない。',
        R除去='追加の実口座R到達退出だけ無効化。元影の価格退出と場末返済は保持。全口座を再生し相互作用を見る。',
        遅延='判断からδ秒経過し、かつ次以降の有効観測で執行。価格注文は成熟済みの線を有効に保つ。元影と実で二重遅延を掛けない。',
        場末='元の安全返済判断15:35/05:50からδ秒。15:45/06:00の場末後約定禁止。場内有効観測がなければ検査不合格。',
        比較='8本全てを同じ反証へ残し、基準A0・少枚数・復元なし・固定時計・固定信号・逆分岐を保持。',
        乱数='bad/good/branch別に同じseed/sourceの符号・選択を条件間共有。元機会・欠測を保持。銘柄間や役割間の依存は保存しない。',
        限界='対象13区間は既知。8本は過去309からの選抜。今回の固定も未知検証にはならず正式p値を出さない。',
        全体目標達成=False,現在API使用=False,保存ライブ使用=False)


def freeze() -> dict:
    """機能: 売買前の条件を保存し、以後の上書きを拒否する。

    引数: なし。返り値: 条件固定 (dict)。エンジン・採否の最終固定は別途必要。
    """
    value=dict(conditions=catalog(),supplementary_conditions=supplementary(),rules=rules(),
        実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),新売買損益読取=False)
    target=HERE/'adaptive_design_fixed.json'
    if target.exists():
        old=read(target);assert {k:v for k,v in old.items() if k!='固定日時'}==value
        return old
    value['固定日時']=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return value


if __name__=='__main__':
    value=freeze()
    print(f'主{len(value["conditions"])}条件、補助{len(value["supplementary_conditions"])}条件を固定。新損益なし。')
