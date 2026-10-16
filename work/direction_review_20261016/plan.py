"""損益を最適化せず、方向予測を広い値幅の先着として事前固定する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT/'work/quantity_execution_20261015'
PUBLIC = ROOT/'アルゴリズム調査/00117_方向予測の有効幅と探索方針の再点検'
TRIAL = '117_実用値幅の方向先着を入口と出口から分離して再点検'
SOURCE_NAMES = ('plan.py','measure.py','input_contract.py','engine.py','artificial.py',
                'aggregate.py','artificial_aggregate.py','artificial_root.py')
WIDTHS = [.0005,.001,.002]
RULES = ['A','B','C']
PRIMARY = dict(rule='C',width_fraction=.001,group='非重複',origin='公開mid')
CAP = dict(TOPIX=10,NK225=20)
MULTIPLIER = dict(TOPIX=1000,NK225=10)
FEE = dict(TOPIX=[418,10],NK225=[11,1])

# ----------------------------------------


def read(path: Path) -> dict:
    """
    機能: 小目録・固定・人工証跡を読む。
    引数: path(Path) はJSON位置。
    返り値: dict は内容。原NPZ・事象本文を隠れて読まない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 所有源・小目録・研究出力の指紋を計算する。
    引数: path(Path) は位置。
    返り値: str はSHA256。原NPZ一読には別の同bytes検査を用いる。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    """
    機能: 所有域へ新しい有限JSONを保存する。
    引数: path(Path)、value(dict) は位置と内容。
    返り値: None。停止記録や旧成功を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def sources() -> dict:
    """
    機能: 入口資格・採点・集計を決める八つの源を固定する。
    引数: なし。
    返り値: dict[str,str] はルート相対位置とSHA256。
    """
    return {(HERE/name).relative_to(ROOT).as_posix():digest(HERE/name) for name in SOURCE_NAMES}


def registration_inputs(fixed: dict) -> list[dict]:
    """
    機能: 対象なし静観窓の空配列を登録表示だけで明示文へ変換する。
    引数: fixed(dict) は実行用小固定。
    返り値: list[dict] は深いコピー。実行時刻・原値は変更しない。
    """
    values = json.loads(json.dumps(fixed['inputs'],ensure_ascii=False,allow_nan=False))
    for row in values:
        if row['time_policy']['quiet_windows'] == []:
            row['time_policy']['quiet_windows'] = '対象窓なし（実行小固定は空配列）'
    return values


def prepare() -> None:
    """
    機能: 旧115の66原列・保存公開の小目録を同bytesで再利用する。
    引数: なし。
    返り値: None。原NPZ・event本文・金融・APIは0。
    """
    source = OLD/'入力と保存公開の固定.json'
    target = HERE/source.name
    assert not target.exists()
    raw = source.read_bytes()
    fixed = json.loads(raw.decode('utf-8'))
    assert fixed['全合格'] is True and len(fixed['inputs']) == 66
    assert len(fixed['sessions']) == len(set(fixed['sessions'])) == 33
    target.write_bytes(raw)
    contract = OLD/'input_contract.py'
    copied = HERE/'input_contract.py'
    assert not copied.exists()
    copied.write_bytes(contract.read_bytes())
    write(HERE/'小目録と入力契約の再利用.json',dict(全合格=True,
        目的='小tickの先着を実用的な幅へ誤って転用していないか、同じ候補を採点する。',
        再利用=dict(path=source.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(raw).hexdigest()),
        入力契約=dict(path=contract.relative_to(ROOT).as_posix(),SHA256=digest(copied)),
        原NPZ=0,保存event本文=0,金融=0,API=0))
    print('既33場66入力の小目録だけを再利用。本文読取・新金融0。')

# ----------------------------------------


def freeze() -> None:
    """
    機能: 十八条件と主評価・全打切・重複除外を結果前に固定する。
    引数: なし。
    返り値: None。登録と実測を自動実行しない。
    """
    fixed = read(HERE/'入力と保存公開の固定.json')
    audit = read(HERE/'実測前の人工と独立監査.json')
    assert audit['全合格'] is True and audit['新金融'] == 0 and audit['source_SHA256'] == sources()
    for item in audit['evidence']:
        assert digest(ROOT/item['path']) == item['SHA256']
    proposal = dict(id=TRIAL,name='方向予測の有効幅を出口から分離する再点検',purpose='新仮説',
        question='一呼値の方向偏りが、重複しない波の±0.05/0.1/0.2%先着にも残るか。新規後の清算気配評価では残るか。',
        change='既114保存公開のA/B/Cを維持し、広い三幅・二起点・共通非重複で非金融採点。新たな損益最適化は行わない。',
        repeat_reason='ユーザーの方向予測自体への問いに答える。114は1T、115/116は狭い出口と場停止で終えたため、実用幅の入口予測率をまだ測っていない。',
        compares_to=['114R2_正常行逆写像を訂正した公表活動と数量後の純先着',
                     '115_板の短期方向性を実約定と損益へ接続する十二対照',
                     '116_同じ板入口の買売方向を反転する十二対照'],evidence=[],
        spec=dict(
            entry=dict(rules=RULES,資格='A=type0。B=type1と反対最小Q>=初期Q。C=Bと元d側Q>=反対Q。元dと保存公開は変更しない。',
                時刻='旧115の各input固定。公開正常行・spread<2観測T。場損益停止・実取引busyは使わない。'),
            management=dict(主評価=PRIMARY,参考='全候補も保存。異なる幅・起点・ruleは同じ経路で独立標本ではない。',
                非重複='rule別に最大0.2%の二起点の先着/打切の遅い終端までlock。終端の次原行から再開。三幅は同じ選択。',
                継続='固定保有時間なし。新規静観窓を跨いでも場内の価格採点を続ける。旧実返済で観測を切らない。'),
            exit=dict(幅率=WIDTHS,値幅='各公開mid×率。丸めなし。予測の符号を基準に順先/逆先を区別。',
                起点='①公開midから未来mid。②直後正常新規の実ask/bidから返済側quoteの評価、往復料点を控除。',
                打切='順先/逆先/観測窓末未決/価格資格切断/原入力EOF/直後新規不可を別記。欠測は勝敗に含めない。',
                極値='同じ価格連続区間のMFE/MAEは事後診断のみ。実返済・決済勝率・新PLではない。'),
            allocation=dict(cap=CAP,multiplier=MULTIPLIER,用途='②の全量往復料点だけの基準。実建玉・増玉・金額収支は作らない。'),
            costs=dict(片道料の分数=FEE,切捨='各全量注文でfloor、往復二注文を合算。',
                気配評価='新規ask/bid→清算bid/askの差から料点を引く。気配差を別に二重控除しない。'),
            execution=dict(新規模型='公開直後seq+1の正常原行一回だけ。未知なら不可で後正常へ繰延しない。',
                非金融参照='②は正常気配を仮に新規価格へ置く診断。直後行のquiet/force到達による旧115の取消を再現せず、実際の新規可能数・約定率とは呼ばない。',
                将来評価='①は公開次原行以降。②は新規行からの清算気配。実返済の次行約定を再生しない。',
                資格='price_validは既115契約。将来Qty/V欠測だけでは価格採点を切らない。真受信順は未保存。'),
            data=dict(sessions=fixed['sessions'],inputs=registration_inputs(fixed),
                input_manifests=[dict(path=(HERE/'入力と保存公開の固定.json').relative_to(ROOT).as_posix(),
                                      sha256=digest(HERE/'入力と保存公開の固定.json'))],
                追加二場='未使用。旧既知33場の再点検で、未知検証とは呼ばない。'),
            implementation=sources()),主評価=PRIMARY,実金融=0)
    write(HERE/'試行計画.json',proposal)
    write(HERE/'実測前の正式固定.json',dict(全合格=True,source_SHA256=sources(),
        input_SHA256=digest(HERE/'入力と保存公開の固定.json'),proposal_SHA256=digest(HERE/'試行計画.json'),
        audit_SHA256=digest(HERE/'実測前の人工と独立監査.json'),widths=WIDTHS,rules=RULES,primary=PRIMARY,
        実行予定=dict(原NPZ=66,保存eventNPZ=66,非金融測定口座=66,新金融=0,原板=0,API=0),自動再実行=False))
    print('十八採点条件と主評価を固定。金融0。')


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=('prepare','freeze'))
    args=parser.parse_args()
    prepare() if args.command=='prepare' else freeze()
