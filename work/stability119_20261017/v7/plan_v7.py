"""相対momentum八条件の、過去NT研究との差分と実行前契約を固定する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
TRIAL='119g_相対的な強さの継続と残差追尾の場内対照'


def digest(path: Path) -> str:
    """
    機能: 実装又は小資料の指紋を求める。
    引数: path(Path)は対象位置。
    返り値: strはSHA256。市場本文を読むためには使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 小目録・根担当の人工結合証跡を読む。
    引数: path(Path)はUTF-8 JSON。
    返り値: dict。金融結果・元市場を読まない。
    """
    return json.loads(path.read_text(encoding='utf8'))


def save(path: Path,value: dict) -> None:
    """
    機能: 計画や固定を既存成果に重ねず保存する。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。UTF-8 JSONを新規作成する。
    """
    assert not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def economic_sources() -> dict:
    """
    機能: 二脚核心とdriver・計画を同じ版へ結合する。
    引数: なし。
    返り値: dict[str,str]は三経済sourceの相対位置とSHA。
    """
    return {p.relative_to(ROOT).as_posix():digest(p) for p in (HERE/'plan_v7.py',HERE/'run_v7.py',HERE/'engine_v7.py')}


def prepare() -> None:
    """
    機能: v5小目録だけから40場80既所有入力の読取目的を固定する。
    引数: なし。
    返り値: None。保存NPZ本文・原市場・新金融・登録は0。
    """
    import run_v7 as runner
    origin=BASE/'v5/入力目録.json';payload=origin.read_bytes();old=json.loads(payload.decode('utf8'))
    inputs=[{key:item[key] for key in ('session','symbol','SHA256','bytes','owned_path')} for item in old['inputs']]
    assert len(old['sessions'])==len(set(old['sessions']))==40 and len(inputs)==80
    assert {(v['session'],v['symbol']) for v in inputs}=={(scene,symbol) for scene in old['sessions'] for symbol in ('NK225','TOPIX')}
    for item in inputs:
        assert (ROOT/item['owned_path']).resolve().is_relative_to(BASE.resolve()) and len(item['SHA256'])==64 and item['bytes']>0
    save(HERE/'入力目録.json',dict(sessions=old['sessions'],splits=old['splits'],inputs=inputs,specs=runner.make_specs(),
        inherited_manifest=dict(path=origin.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(payload).hexdigest()),
        order_leg_column='leg',leg_codes=dict(NK225=0,TOPIX=1),
        読取予定='各既所有preparedからbars/quotesだけ各一読。旧policy・旧損益の読取又は選別は使用しない。',
        保存予定='320組小会計、40組cache、80商品脚cache。PAIRの合算収支と各脚の損益を別保存。',
        原市場追加読取=0,保存cache本文読取=0,新金融実行=0,
        留保='全40場は既知開発。相対momentumの価格仮説は過去NTと重なる。v5の負けを見た後の対立仮説であり未知検証成功とは言わない。'))
    print('v7小目録だけ準備完了。保存cache本文/原市場/金融/登録0。',flush=True)


def freeze() -> None:
    """
    機能: 根担当が独立人工のsource結合後に八部品を正式照合・登録する。
    引数: なし。根担当による後段実行専用。
    返り値: None。登録後も金融は別実行とする。
    """
    meta=read(HERE/'入力目録.json');binding=read(HERE/'人工監査の結合.json');assert binding['passed'] is True
    sources=economic_sources();assert binding['economic_sources']==sources
    manifest=dict(path=(HERE/'入力目録.json').relative_to(ROOT).as_posix(),sha256=digest(HERE/'入力目録.json'))
    evidence_paths=[ROOT/'アルゴリズム調査/00009_銘柄別の損小利大と建玉管理/README.md',
        ROOT/'アルゴリズム調査/00009_銘柄別の損小利大と建玉管理/資料/NTペアの条件と端数リスク.md',
        ROOT/'アルゴリズム調査/00011_一週間データでの再検証/README.md',HERE/'相対momentum八設定と二脚保存の接続人工.json',HERE/'人工監査の結合.json']
    evidence=[dict(path=p.relative_to(ROOT).as_posix(),sha256=digest(p)) for p in evidence_paths]
    save(HERE/'固定計画.json',dict(sources=sources,input_manifest=manifest,artificial_binding=binding))
    proposal=dict(id=TRIAL,name='相対的な強さの継続と残差追尾',purpose='条件比較',
        question='v5で逆行した相対的な強さへ付くと、二脚費用と時間差の下で場内収益を安定できるか',
        change='モデル2×過去30/60分×固定退出又は残差追尾2の8条件。入口を現在残差δの方向へし、元MRを正しい実売買向きで再運転する対照とσ基準の損切/追尾を分ける。',
        repeat_reason='v5は全4条件で相対成分自体が負だったため、全40場を知った後の対立仮説を事前固定する。00009/00011のNT momentumと系統は重複するが、旧15分変化の標準化・Last/費用0から、固定局所残差/有料BBO/厳格二脚とσ追尾へ変更する。過去NTを未知の新発見とは呼ばない。',
        compares_to=['119_全玉清算教師と異なる戦略から場内安定黒字を探す','119e_両脚の費用と時間差を含む相対乖離の場内回帰'],
        evidence=evidence,spec=dict(
            entry=dict(条件='method名ratio_mr/ols_mrは推定式の識別子だけを保持。前者log(NK/TOP)・β1、後者過去OLS残差・β0.2〜5。L30/60×exit0/1の8条件。全familyはmomentum。',
                判定='固定分tまでに公開済みの過去だけでモデルを作る。absδ>=2σのときδ正ならNK買いTOP売り、δ負なら逆。両BBO age<=5価格秒。',
                コスト資格='exit0はabsδ×A>=3×予定往復費用、exit1は2σ×A>=3×予定往復費用。Aは予約時NK想定元本。exit1は入口資格も変わるため同じ実受理集合の出口だけ比較とは呼ばない。'),
            management=dict(モデル='予約時のモデル・中心・σ・β・数量を固定。保有中に未来の平均へ目標を動かさない。',
                不成立='各脚は判断時刻より後の独立したquoteで約定。60秒期限は取消を先に処理し、片脚のみならその脚の次quoteで孤立返済。未約定受理を勝ちにしない。',
                比較='320組口座として全40場全8条件を掲載する。個別脚の黒字を両市場単独で儲かる証拠にしない。',
                再準備='受理時δ符号を保存し、固定中心へ戻るまで同じ乖離へ再準備しない。損切りや未約定だけでは復活しない。',
                原因診断='完結二脚はs=NKside,A=qN×10×entryNK,B=qT×1000×entryTOPとしてrelative=sA(rN−βrT),common=s(βA−B)rTへgrossを厳密分解。fees別。単脚/未清算は二要因未知。これは事後恒等式で入口へ戻さない。'),
            exit=dict(対照0='固定中心への復帰又は入口δから外へ追加2σで返済。現金損失枠はabsδ×A。v5の向きだけを正しく運転する基準。',
                追尾1='入口δから順行残差peakを保存。2σ順行後はpeakから1σ戻りで返済、入口から逆σでも停止。現金損失枠はσ×A。モデル/σ/β/中心/数量は予約時固定。',
                共通='条件成立後、各脚の次の厳密に後のquoteで独立返済。未来残差を新規へ戻さない。',
                締切='Day15:00/Night05:20新規終了、Day15:20/Night05:40返済。EOF未返済は評価と実現を分離し成功にしない。',
                失効='片脚60秒timeout。以後の反対脚の遅延fillを許さず、保有脚の孤立返済を記録する。'),
            allocation=dict(上限='NK225micro20枚、TOPIXmini10枚。βに合わせる正整数組を当時価格だけで決定。',
                端数='目標ヘッジの誤差5%以内。単に両建てしたから中立と呼ばず、実元本差と片脚最大元本を記録する。'),
            costs=dict(片道='NKmicro11円、TOPIXmini41.8円。各脚各注文ごとに数量合計を円未満切捨て。',
                評価='全open脚の清算BBOと残返済費を常時計上する。実支払料と予定返済料は分ける。'),
            execution=dict(順序='固定分tでquote<=tを観測後判断し、各脚のtime>判断時刻だけを新規fillに使う。同時計の順序で架空先着を作らない。',
                同時計='同clockの両市場quoteと各脚fillを全て処理した共同スナップショットで、組残差・再準備・清算MTM・最大下落を評価する。片側だけ更新した架空残差を停止根拠にしない。旧逐次版の正式金融0を保持して金融前に訂正する。',
                約定='買ask/売bid。二脚を同じ時刻・同じ価格で約定したと仮定しない。新規/返済のquote待ちも時価損失へ含める。',
                限界='ラージBBOを小口執行の代理とし、真の受信順・実小型板の待ち順位・現実の期限内約定は未証明。'),
            data=dict(input_manifests=[manifest],sessions=meta['sessions'],
                入力='v5小目録から同じ既所有prepared80のSHA/pathを再利用。bars/quotesだけ各一読。原市場/API0。旧policy・旧金融結果を入力選別に使わない。',
                期間='全40場は既知の事後開発。旧確認13/追加3を未知検証成功と呼ばない。'),
            implementation=sources))
    save(HERE/'試行計画.json',proposal)
    manager=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    for command,name in (('check','正式照合'),('register','正式登録')):
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(manager),command,'--proposal',str(HERE/'試行計画.json')],cwd=ROOT,capture_output=True,encoding='utf8')
        save(HERE/(name+'の全出力.json'),dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr));assert process.returncode==0,name
        parsed=json.loads(process.stdout)
        if command=='check':assert parsed['proposal_complete'] is True
        else:assert parsed['id']==TRIAL and parsed['spec']==proposal['spec']
        print(name+'完了。金融は別途根担当だけで実行。',flush=True)


if __name__=='__main__':
    {'prepare':prepare,'freeze':freeze}[sys.argv[1]]()
