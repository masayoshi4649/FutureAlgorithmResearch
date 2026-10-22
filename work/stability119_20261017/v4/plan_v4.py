"""元候補の同時点逆建てを、新kernel無しの入口対照として金融前に固定する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
TRIAL='119d_広い共同進行と離脱及び遅行追随を同時点で逆建て'
SOURCE_IDS=tuple(f'{family}_L20_X0_E0_G0' for family in ('COMMON','OPEN','LAG'))


def digest(path: Path) -> str:
    """
    機能: source又は小目録の指紋を求める。
    引数: path(Path)は対象位置。
    返り値: strはSHA256。保存市場本文を読むためには使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 小さい固定目録又は監査証跡を読み込む。
    引数: path(Path)はUTF-8 JSON。
    返り値: dict。原市場・金融結果は読まない。
    """
    return json.loads(path.read_text(encoding='utf8'))


def save(path: Path,value: dict) -> None:
    """
    機能: 計画と読取目的を上書きせず保存する。
    引数: path(Path)、value(dict)は出力位置と内容。
    返り値: None。既存成果を保全する。
    """
    assert not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def economic_sources() -> dict:
    """
    機能: 新しいdriver二源と再利用する既存経済五源の現在SHAを結合する。
    引数: なし。
    返り値: dict[str,str]はプロジェクト相対source位置とSHA。新kernelは含まれない。
    """
    files=[HERE/'plan_v4.py',HERE/'run_v4.py',BASE/'v2/engine_v2.py',BASE/'v2/run_v2.py',
        BASE/'v2/catalog_v2.py',BASE/'engine119.py',BASE/'catalog119.py']
    return {path.relative_to(ROOT).as_posix():digest(path) for path in files}


def prepare() -> None:
    """
    機能: v2の小目録だけから三元入口と既所有80cacheの読取予定を固定する。
    引数: なし。
    返り値: None。市場cache本文・新金融・登録は全て0。
    """
    origin=BASE/'v2/入力目録.json';payload=origin.read_bytes();old=json.loads(payload.decode('utf8'))
    indexes=[]
    for ident in SOURCE_IDS:
        matches=[k for k,spec in enumerate(old['old_specs']) if spec['id']==ident]
        assert len(matches)==1,(ident,matches)
        indexes.append(matches[0])
    inputs=[{key:item[key] for key in ('session','symbol','SHA256','bytes','owned_path')} for item in old['inputs']]
    assert len(old['sessions'])==40 and len(inputs)==80
    assert len({(i['session'],i['symbol']) for i in inputs})==80
    assert {(i['session'],i['symbol']) for i in inputs}=={(scene,symbol) for scene in old['sessions'] for symbol in ('TOPIX','NK225')}
    for item in inputs:
        owned=(ROOT/item['owned_path']).resolve()
        assert owned.is_relative_to(BASE.resolve()) and len(item['SHA256'])==64 and item['bytes']>0
    save(HERE/'入力目録.json',dict(sessions=old['sessions'],splits=old['splits'],inputs=inputs,
        source_ids=list(SOURCE_IDS),source_indexes=indexes,source_specs=[old['old_specs'][k] for k in indexes],
        inherited_manifest=dict(path=origin.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(payload).hexdigest()),
        原市場追加読取=0,保存cache本文読取=0,新金融実行=0,
        注意='全40場は既知。成績から入口を再選択せず、明示した元G0三入口の候補公開時点だけを順逆比較する。'))
    print('v4小目録だけ準備完了。保存cache本文/原市場/金融/登録0。',flush=True)


def freeze() -> None:
    """
    機能: 根担当が独立人工のsource結合後、八部品仕様を正式照合・登録する。
    引数: なし。根担当による後段実行専用。
    返り値: None。登録完了まで新金融を開始させない。
    """
    meta=read(HERE/'入力目録.json');binding=read(HERE/'人工監査の結合.json')
    assert binding['passed'] is True
    sources=economic_sources()
    assert binding['economic_sources']==sources,'独立人工と全経済sourceの一致が必要。'
    manifest=dict(path=(HERE/'入力目録.json').relative_to(ROOT).as_posix(),sha256=digest(HERE/'入力目録.json'))
    save(HERE/'固定計画.json',dict(sources=sources,artificial_binding=binding,input_manifest=manifest))
    evidence_paths=[BASE/'diagnosis/選択単体と三枠は何で負けたか.md',
        ROOT/'アルゴリズム調査/00116_全赤字手法の売買反転を同条件で検証/README.md',
        HERE/'元入口と反転接続及び接頭の純人工.json',HERE/'人工監査の結合.json']
    evidence=[dict(path=p.relative_to(ROOT).as_posix(),sha256=digest(p)) for p in evidence_paths]
    proposal=dict(id=TRIAL,name='広い進行の同時点順逆入口対照',purpose='条件比較',
        question='元の共同追従・開始帯離脱・遅行追随を同時点で逆建てすると、広い価格幅と実反対気配の下で損失が減るか',
        change='保存COMMON/OPEN/LAG L20 X0 E0 G0の元entryを保持又は符号反転、逆側の仮説撤回を交換し、2出口×2執行×既知時刻窓有無で48。新kernel0。',
        repeat_reason='v2即逆張りCは共同進行を2Rへ変え、波の再準備も制限した。元.75R共同追従と同時点の逆建てとは異なる。00116は小幅停止の別入口。未整理の全過去と重複なしとは断言しない。',
        compares_to=['119_全玉清算教師と異なる戦略から場内安定黒字を探す','119b_共同進行の失速復帰と事前価格保護の原因対照'],
        evidence=evidence,
        spec=dict(
            entry=dict(元候補=list(SOURCE_IDS),参照='v2入力目録に固定された既所有prepared80内のpoliciesを索引再利用。catalogの再計算・成績再選択を行わない。',
                順逆='directは元五配列を保持。reverseはentry=-entry、exit_long=元exit_short、exit_short=元exit_long。valid/widthは完全同じ。',
                解釈='同じ元候補の公開時点を比較する。忙しさ・返済・cooldown・場停止が変わるため実受理集合は一致を要求しない。',
                時刻因子='time0は全時間、time1は価格公開時計でJP08:45以上09:15未満、NY08:15以上08:45未満及び09:15以上09:45未満を回避。NYはAmerica/New_YorkでDST、毎日で休日例外なし。ニュース値・将来P/L不使用。'),
            management=dict(新kernel=0,再使用='凍結engine_v2/engine119/run_v2/catalog_v2/catalog119。両方とも新しい建玉の損益で出口と再参加を判定する。',
                禁止='旧net/gross/cashの符号反転を会計としない。逆向きでも買ask/売bidと料金を負担する。中立だけで返済しない。',
                比較='三入口×順逆二×二出口×二執行×時刻二=48。同じ48IDを両商品へ適用し、方向や時刻を別familyへ水増ししない。追加探索はこの時刻一因子だけ。全数掲載。',
                時刻適用='窓内公開barはentry0/validFalse/exit両方True。窓開始そのもののtimerではなく公開時に取消/返済判断する。quote先行の同row新規約定は起き得る。validを消すので場リスクの最初有効Rも遅れ得る。'),
            exit=dict(方式='exit5は建値±1R。exit4は−1R停止・+1Rから.5R追尾。元撤回boolは順逆対応で適用する。',
                場予算='guard2。最初の有効R×上限数量10/20×倍率を円尺度とし、費用込み清算時価が−2倍で返済停止。v3のscout尺度とは異なる。次気配超過を隠さない。',
                執行='0は判断後の正常反対気配。3はv2の新規・返済保護をそのまま使い、返済はLast±2観測tick固定線・価格時計30秒でfallback。場末は待たない。',
                締切='Day15:00/Night05:20新規終了、Day15:20/Night05:40返済判断。EOF未返済を勝ちにしない。'),
            allocation=dict(数量='全48はTOPIXミニ10枚/NK225マイクロ20枚。単一玉・同方向追加なし。',方向='順逆の同時両建て配分ではなく独立口座の対照。'),
            costs=dict(片道='TOPIXmini41.8円/NK225micro11円。新規・返済各注文の合計を円未満切捨て。',気配差='ラージBBO代理。逆方向でも当時の買ask/売bid全差を負担。'),
            execution=dict(順序='同rawrowはquote観測→足公開。新規判断行の同row約定を禁止し後rowで実行。',
                呼値='TOPIXmini.25/NK225micro5。数量待ち順位と実小型板の約定は未確認。',
                時計='保存価格時計の順序のみ。真受信時刻・現実の30秒約定保証はない。保護拒否や待機損失も記録。'),
            data=dict(input_manifests=[manifest],sessions=meta['sessions'],
                入力='既所有prepared80を各1読。原市場0/API0。今回のprepareは小目録1読のみ。',
                期間='既知40場すべて事後開発。旧選択6/確認13/追加3を未知の成功と呼ばない。'),
            implementation=sources))
    save(HERE/'試行計画.json',proposal)
    manager=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    for command,name in (('check','正式照合'),('register','正式登録')):
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(manager),command,'--proposal',str(HERE/'試行計画.json')],cwd=ROOT,capture_output=True,encoding='utf8')
        save(HERE/(name+'の全出力.json'),dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
        assert process.returncode==0,name
        parsed=json.loads(process.stdout)
        if command=='check':assert parsed['proposal_complete'] is True
        else:assert parsed['id']==TRIAL and parsed['spec']==proposal['spec']
        print(name+'完了。新金融は別途根担当のみ実行。',flush=True)


if __name__=='__main__':
    {'prepare':prepare,'freeze':freeze}[sys.argv[1]]()
