"""同じ利確アンカーCONFIRM/P1の二商品差を、完成小資料から診断計画へ固定する。"""

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CID = 'E01_ANCHOR_W60_CONFIRM_D0_P1_L2_A1'
RESULT = 'work/wave_v106/e01_size_goal_anchor/finance/結果.json'
FIXED = 'work/wave_v106/e01_size_goal_anchor/金融事前固定.json'
FORMAL = 'work/wave_v106/e01_size_goal_anchor/試行計画.json'
LEGACY = 'work/wave_v106/e01_trade_gate/finance/結果.json'
OLD_DIAG = 'work/wave_v106/price_review/size_loss_diagnosis/最悪六場と旧勝ち赤字化二例の具体診断.json'
SMALL299 = 'work/wave_v106/size_availability/公開299のATR両気配と予定数量可用性.json'
HELPER = 'work/wave_v106/e01_trade_gate/diagnosis/tools.py'


def read(path: str) -> tuple:
    """
    機能: 完成した小JSONを読み、同bytesの指紋を取る。
    引数: path(str)はroot相対位置。
    返り値: tuple[dict,str]は小資料とSHA256。台帳・packetは読まない。
    """
    saved = (ROOT/path).read_bytes()
    return json.loads(saved.decode('utf-8-sig')), hashlib.sha256(saved).hexdigest()


def digest(path: Path) -> str:
    """
    機能: 小sourceの指紋を取る。
    引数: path(Path)は診断source又は純helper。
    返り値: strはSHA256。大型入力の事前走査をしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> None:
    """
    機能: 全33二商品・43実親・目的別一読一覧と分析定義を保存する。
    引数: なし。
    返り値: None。大型読取前の固定計画だけを自所有域へ作る。
    """
    paths = (RESULT, FIXED, FORMAL, LEGACY, OLD_DIAG, SMALL299)
    saved = {p: read(p) for p in paths}
    result, fixed, formal, legacy = (saved[p][0] for p in (RESULT, FIXED, FORMAL, LEGACY))
    assert result['全合格'] and fixed['全合格'] and formal['正式freeze'] and legacy['全合格']
    assert saved[RESULT][1] == '8959ab1bf2f532e5358c458fc81590b8f88964233b231cb78d48293afd07d0f7'
    assert result['source開始終端一致'] and result['source_SHA256'] == fixed['source_SHA256'] == formal['spec']['implementation']
    assert saved[FORMAL][1] == fixed['計画SHA256']
    assert all(digest(ROOT/p) == sha for p, sha in result['source_SHA256'].items())
    config = next(c for c in result['configs'] if c['id'] == CID)
    assert config['mode'] == 'CONFIRM' and config['profit_ticks'] == 1
    rows = result['results'][CID]['rows']; refs = result['results'][CID]['ledgers']
    row_index = {r['session']+'|'+r['symbol']: r for r in rows}
    specs = {r['session']+'|'+r['symbol']: r for r in refs}
    assert len(row_index) == len(specs) == 66 and set(row_index) == set(specs)
    boundary = {r['session']+'|'+r['symbol']: r for r in result['初回受理と費用後目標境界'][CID]}
    sessions = result['sessions']; assert len(sessions) == 33 and sessions == fixed['sessions']
    expected = {s: result['results'][CID]['symbols'][s] for s in ('TOPIX', 'NK225')}
    assert expected['TOPIX']['親数'] == 19 and expected['NK225']['親数'] == 24
    active, inactive = {}, {}
    for key, row in row_index.items():
        if row['親数']:
            active[key] = specs[key]
        else:
            assert row['利益'] == row['損失'] == row['収支'] == row['費用'] == row['新規枚数'] == 0
            assert not boundary[key]['anchor']['成立'] and boundary[key]['実政策初回新規'] is None
            inactive[key] = dict(row=row, boundary=boundary[key], 台帳読取省略=True)
    assert len(active) == 42 and len(inactive) == 24
    worst = {s: sorted((r for r in rows if r['symbol'] == s and r['収支'] < 0), key=lambda r: (r['収支'], r['session']))[:3]
             for s in ('TOPIX', 'NK225')}
    legacy_summary = {mode: {s: legacy['results']['E01_TRADE_W60_'+mode+'_D0_P1L8']['symbols'][s]
                            for s in ('TOPIX', 'NK225')} for mode in ('CONFIRM', 'VETO')}
    sources = {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(HERE.glob('*.py'))}
    sources[HELPER] = digest(ROOT/HELPER)
    output = dict(全合格=True, 条件ID=CID, config=config, sessions=sessions,
        目的='同じCONFIRM/P1が日経で高い勝数を持ちTOPIXで大きな負けを残す原因を、入口・実効値幅・費用・途中経路・出口に分解する。',
        分母='同母二商品全33場。実親TOP19/NK24、無取引24口座を勝ちに含めない。',
        expected=expected, active_ledgers=active, inactive_metadata=inactive, input_cache=fixed['input_cache'],
        rows=row_index, boundary=boundary, 赤字上位三場=worst, 旧full入口別保存比較=legacy_summary,
        小資料={p: sha for p, (_, sha) in saved.items()}, source_SHA256=sources, 金融source_SHA256=result['source_SHA256'],
        一読上限=dict(因果packet=33, 対象goal実活動台帳=42, 無取引台帳=0, 旧full台帳=0, 旧VETO二例台帳=0),
        既診断='VETO_P2の旧二例は保存JSONだけ参照。同じ公開原行/seq/親が確認できた価格参考に限り、今回CONFIRM_P1の損益へ置換しない。',
        分析定義=dict(
            入口='実新規を作った同paper親の公開normal/raw/seq/価格時計、方向、初回受理q、当該実q、q/full、公開固定ATR、W60初回票数と候補方向釣合い。',
            費用='公開spread/ATR、公開予定往復floor料/R、実往復料/R、約定直後bid/askによる初期清算費用/R。R=当該実初回q×公開ATR×倍率。',
            値幅='名目goal/R・固定loss/Rに加え、公開時の前親清算を反映した残goal/R・残loss/Rを別に測る。',
            必要呼値='全量保持と一往復だけを仮定した(g−公開時前親清算＋往復料)/(実q×倍率)を観測呼値へ切り上げる。実partial後の保証ではない。',
            経路='実約定から実最終返済までのLastと清算側BBOの最大順行/逆行、UID料を含む親清算ピーク/谷。公開固定ATRで正規化し未来ATRを再計算しない。',
            損益='保存親gross/net/料を全数照合。無黒字・利益返し・料だけで赤字化・再参加損失を区別。',
            出口='実注文reason91元GU、92静観、93場末、94利益目標、95損失予算と各判断/実返済clock。政策停止後GU suffixは実損益へ加算しない。',
            場比較='Day/Night、ロング/ショート、当時票数/釣合い・各連続尺度の分布、赤字上位最大3場の全親を具体時刻で比較。NK赤字は2場なので3件へ補完しない。'),
        因果留保=['未来の最大順行/逆行は診断のみ。最適出口・救済PL・新金融を算出しない。',
            '単純な料率はTOP1枚82/500=16.4%、NK1枚22/100=22%で、TOP悪化を費用だけで断定しない。',
            '旧full段階でもCONFIRM/VETOの銘柄差がある。数量や利確尺度だけで差が生じたとは断定しない。',
            '価格時計は実受信時計ではない。同clock未来原rowを入口観測へ含めず、実約定後経路は事後診断として分離。'],
        仮説の検討順=['利益/損失の実効呼値とATR比が同じでない尺度差：値幅パラメータ一部品の対照候補。',
            '公開から実約定までの不利移動や無黒字が商品で違う：入口執行の一部品対照候補。',
            '同方向票の強さに対する価格応答・回復/利益返しが違う：入口又は保有中価格応答条件の一部品対照候補。'],
        金融化='測定後に原因と勝ち反証を確認し、根/engineが条件を固定してから。無差別な閾値探索はしない。',
        大型読取=0, 台帳読取=0, 原板=0, NPZ=0, API=0, 新金融=0, 公開変更=0, 共通知見変更=0)
    target = HERE/'同母二商品差の診断固定計画.json'; assert not target.exists()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    print('同母全33、43実親、33packet/42活動台帳、未読で診断計画を固定。', flush=True)


if __name__ == '__main__':
    run()
