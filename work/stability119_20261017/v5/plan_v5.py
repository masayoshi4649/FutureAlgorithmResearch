"""二脚相対回帰四条件の、過去NT研究との差分と実行前契約を固定する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
TRIAL='119e_両脚の費用と時間差を含む相対乖離の場内回帰'


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
    return {p.relative_to(ROOT).as_posix():digest(p) for p in (HERE/'plan_v5.py',HERE/'run_v5.py',HERE/'engine_v5.py')}


def prepare() -> None:
    """
    機能: v4小目録だけから40場80既所有入力の読取目的を固定する。
    引数: なし。
    返り値: None。保存NPZ本文・原市場・新金融・登録は0。
    """
    import run_v5 as runner
    origin=BASE/'v4/入力目録.json';payload=origin.read_bytes();old=json.loads(payload.decode('utf8'))
    inputs=[{key:item[key] for key in ('session','symbol','SHA256','bytes','owned_path')} for item in old['inputs']]
    assert len(old['sessions'])==len(set(old['sessions']))==40 and len(inputs)==80
    assert {(v['session'],v['symbol']) for v in inputs}=={(scene,symbol) for scene in old['sessions'] for symbol in ('NK225','TOPIX')}
    for item in inputs:
        assert (ROOT/item['owned_path']).resolve().is_relative_to(BASE.resolve()) and len(item['SHA256'])==64 and item['bytes']>0
    save(HERE/'入力目録.json',dict(sessions=old['sessions'],splits=old['splits'],inputs=inputs,specs=runner.make_specs(),
        inherited_manifest=dict(path=origin.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(payload).hexdigest()),
        order_leg_column='leg',leg_codes=dict(NK225=0,TOPIX=1),
        読取予定='各既所有preparedからbars/quotesだけ各一読。旧policy・旧損益の読取又は選別は使用しない。',
        保存予定='160組小会計、40組cache、80商品脚cache。PAIRの合算収支と各脚の損益を別保存。',
        原市場追加読取=0,保存cache本文読取=0,新金融実行=0,
        留保='全40場は既知開発。相対回帰の価格仮説は過去NTと重なる。新規の必勝法や未知検証成功とは言わない。'))
    print('v5小目録だけ準備完了。保存cache本文/原市場/金融/登録0。',flush=True)


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
        ROOT/'アルゴリズム調査/00011_一週間データでの再検証/README.md',HERE/'二脚核心と固定四条件及び保存接口の人工検査_共同時計修正版.json',HERE/'相対と共通元本差の厳密分解及び接続人工の委譲_共同時計修正版.json',HERE/'人工監査の結合.json']
    evidence=[dict(path=p.relative_to(ROOT).as_posix(),sha256=digest(p)) for p in evidence_paths]
    save(HERE/'固定計画.json',dict(sources=sources,input_manifest=manifest,artificial_binding=binding))
    proposal=dict(id=TRIAL,name='二市場相対回帰の独立二脚と整数ヘッジ',purpose='条件比較',
        question='共通方向の予測をやめ、相対価格の平均回帰を実両脚BBOと有料整数ヘッジで運転すると、場内損失が安定するか',
        change='ratio_mr/ols_mr×過去30/60分の固定4条件。二銘柄を逆方向に独立約定し、片脚失効・孤立返済・両脚の実費用と全資産を記録。',
        repeat_reason='00009/00011のNT相対回帰と仮説は重複する。過去は主にLast次行・費用0・60分/多枚数診断。本試行は既知40場・小口上限20/10・有料BBO・片脚60秒timeoutへ変更し、保存結果を現在の実行模型の収益と同一視しない。全過去重複なしとは主張しない。',
        compares_to=['119_全玉清算教師と異なる戦略から場内安定黒字を探す','119d_広い共同進行と離脱及び遅行追随を同時点で逆建て'],
        evidence=evidence,spec=dict(
            entry=dict(条件='ratio_mrはlog(NK/TOP)・β1、ols_mrは過去対数価格のOLS残差・β0.2〜5。L30/60の4条件。',
                判定='固定した分時刻tの観測後、tまでに実際に公開済みの過去だけでモデルと中心/標準偏差を計算し、中心から2σ以上の乖離を戻す向き。片側5秒超古いBBOは使用しない。',
                コスト資格='中心復帰の予定利益が往復費用の3倍以上。任意閾値や方向の追加探索はしない。'),
            management=dict(モデル='予約時のモデル・中心・σ・β・数量を固定。保有中に未来の平均へ目標を動かさない。',
                不成立='各脚は判断時刻より後の独立したquoteで約定。60秒期限は取消を先に処理し、片脚のみならその脚の次quoteで孤立返済。未約定受理を勝ちにしない。',
                比較='160組口座として全40場全4条件を掲載する。個別脚の黒字を両市場単独で儲かる証拠にしない。',
                原因診断='完結二脚はs=NKside,A=qN×10×entryNK,B=qT×1000×entryTOPとしてrelative=sA(rN−βrT),common=s(βA−B)rTへgrossを厳密分解。fees別。単脚/未清算は二要因未知。これは事後恒等式で入口へ戻さない。'),
            exit=dict(条件='固定モデルの中心復帰、外側への追加2σ、予定中心利益相当の現金損失枠、場末で返済。損切り条件成立後は次の各脚気配で独立返済。',
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
                入力='v4小目録に固定された既所有prepared80のbars/quotesを各一読。原市場/APIは0。旧policy・旧金融結果は選別に使用しない。',
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
