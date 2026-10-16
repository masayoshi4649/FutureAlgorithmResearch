"""TOPIX判断後10ptの予兆を、対象・候補・時系列分割から先に固定する。"""

from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00118_TOPIX十ポイントの予兆と多尺度方向予測'
TRIAL='118_TOPIX十ポイントの予兆を多尺度と異情報で探索'
SOURCES=('plan.py','input.py','artificial_input.py','features.py','artificial_features.py',
    'targets.py','artificial_targets.py','learner.py','artificial_learner.py','run.py')
THRESHOLDS=[.45,.55,.65]
MODEL_GROUPS={'L01_価格':['price'],'L02_多数MA':['price','ma'],
    'L03_MA活動板':['price','ma','volume','book'],
    'L04_MA活動板二市場':['price','ma','volume','book','peer']}
RIDGE=10.
PRIMARY_RISK=5.

# ----------------------------------------


def read(path: Path) -> dict:
    """
    機能: 固定・小集計・証跡を読む。
    引数: path(Path) はJSON位置。
    返り値: dict。原板やNPZを隠れて取得しない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 所有源と結果のSHA256を得る。
    引数: path(Path) は対象。
    返り値: str。市場入力は同bytes読取側で別に検査する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path,value: dict) -> None:
    """
    機能: 新しい所有JSONを有限値だけで保存する。
    引数: path(Path)、value(dict)。
    返り値: None。旧成功・Falseの上書きを禁止する。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def sources() -> dict:
    """
    機能: 因果入力から学習・採点まで十源を固定する。
    引数: なし。
    返り値: dict[str,str] はルート相対pathと指紋。
    """
    return {(HERE/name).relative_to(ROOT).as_posix():digest(HERE/name) for name in SOURCES}


def prepare() -> None:
    """
    機能: 小目録とファイル名だけから既33＋追加4場の74入力を固定する。
    引数: なし。
    返り値: None。原NPZ・新JSONL本文・現在APIを読まない。
    """
    old=read(ROOT/'work/quantity_execution_20261015/入力と保存公開の固定.json')
    names={symbol:sorted(p.stem for p in (ROOT/'candle_1min'/symbol).glob('*.csv')) for symbol in ('TOPIX','NK225')}
    assert names['TOPIX']==names['NK225'] and len(names['TOPIX'])==37
    sessions=names['TOPIX'];known=old['sessions']
    assert sessions[:33]==known and len(set(sessions))==37
    lookup={(row['raw']['session'],row['raw']['symbol']):row['raw'] for row in old['inputs']}
    inputs=[]
    for session in sessions:
        for symbol in ('TOPIX','NK225'):
            if (session,symbol) in lookup:
                info=dict(lookup[session,symbol]);info['kind']='old_npz'
            else:
                day=datetime.fromisoformat(session[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
                start=day+timedelta(hours=8,minutes=45) if session.endswith('_Day') else day+timedelta(hours=17)
                end=day+timedelta(hours=15,minutes=40) if session.endswith('_Day') else day+timedelta(days=1,hours=5,minutes=55)
                path=ROOT/'book'/symbol/(session+'.jsonl');stat=path.stat()
                info=dict(session=session,symbol=symbol,path=path.relative_to(ROOT).as_posix(),bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,bounds=[start.timestamp(),end.timestamp()],kind='jsonl')
            inputs.append(info)
    split=dict(学習=sessions[:21],選択=sessions[21:27],時系列別枠=sessions[27:33],追加別枠=sessions[33:])
    write(HERE/'入力目録と時系列分割.json',dict(全合格=True,sessions=sessions,inputs=inputs,splits=split,
        old_schema=old['schema'],観測T=old['観測T'],金融=0,API=0,
        追加の扱い='今回の候補固定に使わない追加4場。過去すべての読取不存在を証明した完全未見とは称さない。',
        価格模型='自身原順・非減少CurrentPriceTimeの有限正Last。既CSVや真受信時刻の完全再現ではない。'))
    print(json.dumps(dict(対象場=len(sessions),既知=33,追加=4,原NPZ=0,原JSONL=0,分割=split),ensure_ascii=False))


def freeze() -> None:
    """
    機能: 32規則と学習4群×3閾値、採点・学習・選択を実測前に固定する。
    引数: なし。
    返り値: None。登録・市場入力作成を自動実行しない。
    """
    fixed=read(HERE/'入力目録と時系列分割.json')
    audit=read(HERE/'実測前の検査.json')
    assert audit['全合格'] and audit['source_SHA256']==sources()
    for item in audit['evidence']:assert digest(ROOT/item['path'])==item['SHA256']
    import features
    proposal=dict(id=TRIAL,name='TOPIX十ポイントの予兆を入口だけで探索',purpose='新仮説',
        question='多尺度MA・価格経路・活動・板・二市場に、判断後10ptを逆行より先に選ぶ情報があるか。',
        change='Last価格とBBO資格を分離した因果分足と観測原順先着。多数MAと異情報・過去学習を44条件で比較。',
        repeat_reason='117は数量入口の小幅反応で多数BBOcut。今回の10pt・多尺度・時系列選択は未検証。',
        compares_to=['117_実用値幅の方向先着を入口と出口から分離して再点検'],evidence=[],
        spec=dict(
            entry=dict(規則=features.specifications(),学習群=MODEL_GROUPS,学習閾値=THRESHOLDS,
                公開='確定1分足までの現在条件が初めて成立。価格は公開行現在Last。過去足へ建値を巻き戻さない。',
                学習公開='独立両sideの高い見込みが閾値以上かつ差0.1以上となった状態変化。見込みを実測的中率と呼ばない。',
                共通資格='有限anchor・valid足・公開遅れ60秒以内、観測窓末5分前まで。機械学習は価格連続30本以上。'),
            management=dict(時間制限='固定保有時間なし、同じ観測窓の終点まで採点。場跨ぎなし。',
                非重複='各候補の公開後、±10ptの先着又は場末までlock。2.5/5/10逆行の三採点で同じ候補。',
                時系列分割=fixed['splits'],学習='各学習場の5分おき行。場均等weight、標準化も学習場のみ。独立した両side logistic、L2=10。',
                選択='選択6場で件数12以上・活動4場以上・買売各3以上を満たす条件を、10対5の全候補順先率−同じ時点の固定買売の最大率、順先率、活動数、件数の順で異family最大3個選ぶ。同点はID逆順。足りなければ不足を明記し比較用参照も別記。'),
            exit=dict(目的幅=10,逆行幅=[2.5,5,10],主逆行幅=PRIMARY_RISK,
                先着='原順の採用Last scalarだけで判定。公開行を含めず未来原rowから。OHLC同足の順を推測しない。',
                極値='未来観測MFE/MAE、10pt到達前逆行は事後診断。到達一回と先着を混同しない。',
                未決='観測窓末未到達・原EOF・anchor不可を分け、無信号を勝ちにしない。'),
            allocation=dict(用途='入口予測の非金融採点。枚数配分と建玉は作らない。',主商品='TOPIXラージ観測値幅10pt'),
            costs=dict(段階='純価格の予測段階。手数料・気配差を引いた実利益や勝率とは呼ばない。',金融=0),
            execution=dict(価格='自身原順のLast、CurrentPriceTime最大値以上。BBO異常でも価格応答を切らない。',
                他市場='自己確定分より1分以上前かつ相手公開価格時計が自己公開価格時計以下のNK足。真の受信同期ではない。',
                欠測='空分はNaN・価格指標warmupを切る。量/板未知だけでは価格を切らずknown列を別持ち。'),
            data=dict(sessions=fixed['sessions'],inputs=fixed['inputs'],splits=fixed['splits'],
                input_manifests=[dict(path=(HERE/'入力目録と時系列分割.json').relative_to(ROOT).as_posix(),sha256=digest(HERE/'入力目録と時系列分割.json'))]),
            implementation=sources()))
    write(HERE/'試行計画.json',proposal)
    write(HERE/'正式固定.json',dict(全合格=True,source_SHA256=sources(),input_SHA256=digest(HERE/'入力目録と時系列分割.json'),
        proposal_SHA256=digest(HERE/'試行計画.json'),audit_SHA256=digest(HERE/'実測前の検査.json'),
        thresholds=THRESHOLDS,model_groups=MODEL_GROUPS,ridge=RIDGE,
        実行予定=dict(旧原NPZ=66,新JSONL=8,新金融=0,API=0),自動再実行=False))
    print('候補・10pt採点・時系列分割を正式固定。実本文0。')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('prepare','freeze'))
    args=parser.parse_args()
    prepare() if args.command=='prepare' else freeze()
