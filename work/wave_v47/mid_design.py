"""既存の入口と価格退出を固定し、減量後の復元を13条件で分解する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIMARY = 'G150_F50_N1__V000'
BASELINE = 'A0__V000'
MODES = ('none', 'timer', 'signal')
ECONOMIC_FIELDS = ('signal_id', 'policy', 'budget_enabled', 'entry_scale', 'bad_scale',
    'good_scale', 'branch_scale', 'observed_fill', 'min_delay_seconds', 'bad_seed',
    'good_seed', 'branch_seed', 'branch_mode', 'gate_threshold_atr', 'gate_mode')
DESCRIPTIVE_FIELDS = {'id', 'variant_id', 'role', 'primary', 'baseline_policy', 'gate_reference'}


def read(path: Path) -> object:
    """機能: 保存済み仕様又は圧縮証跡を読み取る。

    引数: path(Path)。返り値: JSON内容(object)。原本と現在データは読まない。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def digest(path: Path) -> str:
    """機能: 参照する保存資料の指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 今回の領域だけへ有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)+'\n', encoding='utf-8')


def identifier(gate: float, fraction: int, mode: str) -> str:
    """機能: 復元の違いが衝突しない条件IDを返す。

    引数: gate(float)、fraction(int)、mode(str)。返り値: 条件ID(str)。
    """
    assert gate in (0., 1.5) and fraction in (25, 50) and mode in MODES
    suffix = {'none':'_NONE', 'timer':'_T120', 'signal':''}[mode]
    return f'G{int(gate*100):03d}_F{fraction}{suffix}_N1__V000'


def specification(gate: float, fraction: int, mode: str) -> dict:
    """機能: 旧仕様の減量割合・復元方式だけを明示した経済条件を作る。

    引数: gate(float)、fraction(int)、mode(str)。返り値: 旧runnerと互換の条件(dict)。
    """
    old = read(HERE.parent/'wave_v44/探索条件の固定.json')
    signal_id = identifier(gate, fraction, 'signal')
    value = deepcopy(next(s for s in old['conditions'] if s['id'] == signal_id))
    policies = read(HERE.parent/'wave_v37/partial_design_fixed.json')['conditions']
    policy_id = {'none':f'B00_NONE_F{fraction}', 'timer':f'B00_T120_F{fraction}_N1',
                 'signal':f'B00_RB00_F{fraction}_N1'}[mode]
    candidates = [s['policy'] for s in policies if s['policy']['id'] == policy_id]
    assert candidates and all(p == candidates[0] for p in candidates)
    value['policy'] = deepcopy(candidates[0])
    value['policy']['branch_mode'] = 'fixed'
    value.update(id=identifier(gate, fraction, mode), role='paired_mechanism',
                 baseline_policy=policy_id, primary=identifier(gate, fraction, mode) == PRIMARY)
    return value


def catalog() -> list[dict]:
    """機能: 数量調整なしと2到達条件×2割合×3復元方式を全列挙する。

    引数: なし。返り値: 順位選抜しない13条件(list[dict])。
    """
    base = deepcopy(next(s for s in read(HERE.parent/'wave_v44/探索条件の固定.json')['conditions']
                         if s['id'] == BASELINE))
    base.update(role='reference', primary=False)
    rows = [base] + [specification(g, f, m) for g in (0., 1.5) for f in (25, 50) for m in MODES]
    assert len(rows) == len({s['id'] for s in rows}) == 13
    assert sum(s['primary'] for s in rows) == 1
    return rows


def economic_spec(spec: dict, version: int) -> dict:
    """機能: 名称を除いた全執行条件を、旧版の明示既定値と照合可能にする。

    引数: spec(dict)、version(int:37/38/44/47)。返り値: 経済条件(dict)。
    v37の数量管理は予算ON・遅延0・分岐なし。これを台帳互換の証明とはみなさない。
    """
    assert version in (37, 38, 44, 47)
    value = deepcopy(spec)
    allowed = set(ECONOMIC_FIELDS) | DESCRIPTIVE_FIELDS
    if version == 37:
        assert set(value) <= allowed | {'random_seed'}
        value.update(budget_enabled=True, min_delay_seconds=0., bad_seed=None,
                     good_seed=value.pop('random_seed'), branch_seed=None,
                     branch_mode='fixed', branch_scale=1.)
        value['policy']['branch_mode'] = 'fixed'
    else:
        assert set(value) <= allowed, '未分類の執行項目を名前として捨てない'
    if version in (37, 38):
        assert 'gate_threshold_atr' not in value and 'gate_mode' not in value
        value.update(gate_threshold_atr=0., gate_mode='direction')
    assert set(ECONOMIC_FIELDS) <= set(value)
    result = {key:deepcopy(value[key]) for key in ECONOMIC_FIELDS}
    assert set(result['policy']) == {'id', 'kind', 'reduce_fraction', 'max_reductions',
        'bad_id', 'good_id', 'restore_mode', 'restore_seconds', 'branch_mode'}
    del result['policy']['id']
    return result


def origins() -> dict[str, dict]:
    """機能: 既知・新規と、保存成果再利用・旧版互換再生を別々に定義する。

    引数: なし。返り値: 条件IDから由来を引く辞書(dict)。成績順位は参照しない。
    """
    result = {}
    for spec in catalog():
        mode = spec['policy']['restore_mode']
        fraction = round(spec['policy']['reduce_fraction']*100)
        if spec['id'] == BASELINE or mode == 'signal':
            result[spec['id']] = dict(kind='reuse_v44', known=True, replay=False,
                source_version=44, source_id=spec['id'], source_dir='work/wave_v44')
        elif spec['gate_threshold_atr'] == 0.:
            old_id = f"H019__{spec['policy']['id']}"+('__R1__V000' if fraction == 25 else '__V000')
            result[spec['id']] = dict(kind='reuse_v41' if fraction == 25 else 'known_replay_v37',
                known=True, replay=fraction == 50, source_version=38 if fraction == 25 else 37,
                source_id=old_id, source_dir='work/wave_v38' if fraction == 25 else 'work/wave_v37')
        else:
            result[spec['id']] = dict(kind='new_mechanism', known=False, replay=True,
                source_version=None, source_id=None, source_dir=None)
    assert sum(v['known'] for v in result.values()) == 9
    assert sum(not v['replay'] for v in result.values()) == 7
    assert sum(v['replay'] for v in result.values()) == 6
    return result


def comparisons() -> list[dict]:
    """機能: 13条件の全てを固定した対応差へ接続する。

    引数: なし。返り値: 収支・R・DD・比率を別報告する比較指定(list[dict])。
    """
    rows = []
    for gate in (0., 1.5):
        for fraction in (25, 50):
            for left, right in (('signal','none'), ('signal','timer'), ('timer','none')):
                rows.append(dict(kind='restore', left=identifier(gate,fraction,left),
                    right=identifier(gate,fraction,right), primary=gate == 1.5 and fraction == 50))
    for fraction in (25, 50):
        for mode in MODES:
            rows.append(dict(kind='gate', left=identifier(1.5,fraction,mode),
                             right=identifier(0.,fraction,mode), primary=False))
    return rows


def rules() -> dict:
    """機能: 比較の範囲・元組分母・未見性の限界を計算前に固定する。

    引数: なし。返り値: 今回の解釈と再利用規則(dict)。
    """
    old = read(HERE.parent/'wave_v44/探索条件の固定.json')
    return dict(主比較=PRIMARY, 全条件数=13, 既知条件数=9, 成果再利用条件数=7,
        既知旧版互換再生条件数=2, 未試行機構条件数=4, 再生条件数=6,
        全入力数=338, 再利用入力数=182, 既知互換再生入力数=52, 未試行機構入力数=104,
        全セッション=old['全セッション'], 後半7セッション=old['後半7セッション'], 指定波=old['指定波'],
        入口='H019中央。入口時計1、方向と初回注文を全13条件共通。',
        価格退出='D273固定A0、初回TOPIX5/NK22510、初期1ATR停止、2ATRで元利確枠退役、3ATR追跡・始動1.5ATR、360分、場内返済。',
        予算='全てR1。実現と含みの合計が元q0×A0以下の損失で全返済予約。予算・期限リセットなし。',
        調整='各組最大1回。現在保有nからmin(n-1,max(1,floor(f*n)))を減らす。元利確枠は復元不可。',
        到達='0は旧恒等bypass。1.5は影の初期ATRによる価格順行到達後、source_row>armの新しいB00悪化だけ。',
        復元='noneは復元なし。timerは減量約定120秒後以降に公開された新しい有効な自己B00公開、方向0も許す。signalは新しいB00肯定。',
        執行='全て旧指定価格仮定・追加遅延0、分岐fixed、各乱数seedなし。追加の伝達感度は本13に含めない。',
        比較母集団='同じ影の初回注文・全元組を保持。未減量・未復元・損失・早期退出・閾値未到達を除外しない。',
        差R='各元組の実損益差を共通影の初回q0×A0で割る。円では銘柄倍率を掛ける。独立組番号だけで対応せず初回行/側/価格/数量/A0/影指紋を照合。',
        交互作用='(gate1.5 signal−none)−(gate0 signal−none)、及びsignal−timerを全元組で計算。DDの差は口座曲線の指標差であり組別加法効果とは呼ばない。',
        報告='全13/後7×両銘柄で収支・利益損失・元組PF・平均元組勝敗比・1枚平均勝敗比・DD・最大1/2勝ち組除外・最大黒字場除外・減量復元件数・保有枚数時間・指定8波を別掲。',
        判定='事前指定した対応差の増益/DD減・利益とDDの交換・無差を独立報告。追加の75/80閾値、最良ID差替、p値による有意認定はしない。',
        比率未定義='無取引又は勝敗片側なしの比率は未定義として別表示。0や無限大で優位へ置換しない。',
        比較の限界='復元あり対なしは保有量変更を含む運用総効果。信号対時計と組み合わせても実約定同時刻・同保有量を保証しない。',
        既知再利用='旧9条件は今回の新発見としない。v37の2条件は経済仕様一致だが新版15配列の完全同値証拠が未作成なので互換再生を要求。',
        旧版照合='v37再生2条件は保存した全旧13実配列・旧9影配列と全経済台帳を照合。新列があることだけを差として許し、旧共有項目の不一致は報告して停止。',
        新規性='未試行4条件も既知13セッション内の成分比較。未知期間での成績とは呼ばない。',
        現在API取得数=0, 保存ライブ使用=False, 新9月29日Night使用=False, 費用=0)


def reuse_evidence() -> dict:
    """機能: 既知9条件を旧完備証跡と全26台帳へ結び、再利用可否を保存する。

    引数: なし。返り値: 由来別の資料指紋と一致結果(dict)。旧資料は変更しない。
    """
    specs = {s['id']:s for s in catalog()}; references = {}; records = []
    old44 = read(HERE.parent/'wave_v44/完備監査.json')
    old37 = read(HERE.parent/'wave_v37/完備監査.json')
    state41 = read(HERE.parent/'wave_v41/状態修正の全再生.json')
    assert old44['全合格'] and old37['検証完了'] and state41['全合格']
    assert state41['全条件数'] == 974 and state41['経済全配列完全一致']
    sessions = rules()['全セッション']; keys = {(n,s) for n in sessions for s in ('TOPIX','NK225')}
    anchor_rows = read(HERE.parent/'wave_v44/ledgers/A0__V000.json.gz')
    anchor = {(r['session'],r['symbol']):r for r in anchor_rows}

    def bind(path: Path, expected: str | None = None) -> None:
        """機能: 一資料の参照SHAを上書きなしで結合する。

        引数: path(Path)、expected(str又はNone)。返り値: なし(None)。
        """
        key = path.relative_to(ROOT).as_posix(); actual = digest(path)
        assert expected is None or actual == expected, key
        assert key not in references or references[key] == actual
        references[key] = actual

    for p in (HERE.parent/'wave_v44/完備監査.json', HERE.parent/'wave_v37/完備監査.json',
              HERE.parent/'wave_v41/状態修正の全再生.json', HERE.parent/'wave_v44/ledgers/A0__V000.json.gz'):
        bind(p)
    for identifier_, origin in origins().items():
        if not origin['known']:
            records.append(dict(id=identifier_, **origin)); continue
        base = ROOT/origin['source_dir']; old_id = origin['source_id']
        summary = read(base/'summaries'/f'{old_id}.json')
        assert economic_spec(summary['spec'],origin['source_version']) == economic_spec(specs[identifier_],47)
        ledger = read(base/'ledgers'/f'{old_id}.json.gz')
        assert len(ledger) == 26 and {(r['session'],r['symbol']) for r in ledger} == keys
        for row in ledger:
            key = row['session'],row['symbol']
            assert row['config'] == anchor[key]['config'], (identifier_,key,'D273設定')
        if origin['kind'] == 'reuse_v44':
            done_path = base/'completed'/f'{old_id}.json'; done = read(done_path)
            bind(done_path,old44['参照資料SHA256'].get(done_path.relative_to(ROOT).as_posix()))
            assert done['全合格'] and done['全入力数'] == 26
            for name, sha in done['出力SHA256'].items():
                assert old44['出力SHA256'][name] == sha
                bind(ROOT/name,sha)
        elif origin['kind'] == 'reuse_v41':
            matches = [r for r in state41['結果'] if r['id'] == old_id]
            assert len(matches) == 1 and matches[0]['全合格'] and matches[0]['状態変更行数'] == 0
            detail_path = ROOT/matches[0]['実体']; bind(detail_path,matches[0]['実体SHA256'])
            detail = read(detail_path)
            for flag in ('全合格','原版状態監査合格','経済全配列完全一致','全保存統計一致','影不変'):
                assert detail[flag] is True
            assert detail['spec'] == summary['spec'] and detail['全入力数'] == 26
            assert len(detail['検査']) == 26 and {(r['session'],r['symbol']) for r in detail['検査']} == keys
            for row, proof in zip(sorted(ledger,key=lambda r:(r['session'],r['symbol'])),
                                  sorted(detail['検査'],key=lambda r:(r['session'],r['symbol']))):
                assert row['result_fingerprints'] == proof['修正版全指紋']
                assert row['shadow_fingerprints'] == proof['影全指紋']
            for name, sha in detail['旧成果SHA256'].items():bind(ROOT/name,sha)
        else:
            for name,sha in old37['参照資料SHA256'].items():
                if old_id in name:bind(ROOT/name,sha)
            assert (base/'ledgers'/f'{old_id}.json.gz').relative_to(ROOT).as_posix() in references
        # ----------------------------------------
        # 共通影は元組番号だけでなく保存済み配列指紋で対応させる。
        shared_fields = None
        for row in ledger:
            key = row['session'],row['symbol']
            common = set(row['shadow_fingerprints']) & set(anchor[key]['shadow_fingerprints'])
            assert {'trades','orders','cycles','curve'} <= common
            assert all(row['shadow_fingerprints'][k] == anchor[key]['shadow_fingerprints'][k] for k in common), (identifier_,key,'共通影')
            assert shared_fields is None or shared_fields == sorted(common)
            shared_fields = sorted(common)
        records.append(dict(id=identifier_, **origin, 経済仕様完全一致=True, 全26設定一致=True,
            共通影共有指紋一致=True, 共通影比較列=shared_fields,
            旧版全実配列同値を本再生で要求=origin['kind']=='known_replay_v37'))
    return dict(全合格=True, 条件=records, 全条件数=13, 既知条件数=9,
        成果再利用条件数=7, 既知互換再生条件数=2, 未試行機構条件数=4,
        参照資料SHA256=references, 新実相場再生=False, 現在API取得数=0, 保存ライブ使用=False)


def freeze() -> dict:
    """機能: 合格した人工・再利用証跡と13条件を上書きせず固定する。

    引数: なし。返り値: 設計固定(dict)。新実相場を再生しない。
    """
    test = read(HERE/'check_mid_design.json')
    assert test['全合格'] is True and test['新実相場損益'] is False
    for name,sha in test['参照資料SHA256'].items():assert digest(ROOT/name) == sha,name
    evidence = reuse_evidence(); save(HERE/'mid_reuse_evidence.json',evidence)
    references = dict(test['参照資料SHA256'])
    for path in (Path(__file__),HERE/'check_mid_design.py',HERE/'check_mid_design.json',HERE/'mid_reuse_evidence.json'):
        references[path.relative_to(ROOT).as_posix()] = digest(path)
    for name,sha in evidence['参照資料SHA256'].items():
        assert name not in references or references[name] == sha
        references[name] = sha
    value = dict(conditions=catalog(),rules=rules(),origins=origins(),comparisons=comparisons(),
        SHA256=references, 新実相場損益確認前=True, 新Night使用=False)
    path = HERE/'mid_design_fixed.json'
    if path.exists():assert read(path) == value,'固定後変更'
    else:save(path,value)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze',action='store_true')
    args = parser.parse_args()
    if args.freeze:freeze()
    else:print(json.dumps(dict(conditions=catalog(),origins=origins()),ensure_ascii=False,indent=2))
