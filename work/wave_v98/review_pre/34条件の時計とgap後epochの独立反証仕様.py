"""34条件の指定仕様を損益前に反証し、実装検査の期待値を先に保存する。"""

import hashlib
import importlib.util
from itertools import product
import json
from pathlib import Path
import sys


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]


def digest(path: Path) -> str:
    """
    機能: 指定した読取専用コード又は設計の内容指紋を求める。
    引数: path(Path)。
    返り値: strはSHA256。旧領域を変更しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(name: str, path: Path) -> object:
    """
    機能: main又は売買を実行せず条件定義だけを読む。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。バイトコードを保存しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def save(name: str, value: dict) -> None:
    """
    機能: 自担当review_preに損益前の仕様と人工期待値を保存する。
    引数: name(str)、value(dict)。
    返り値: None。新正式候補の売買や損益を生成しない。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE.resolve())
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main() -> None:
    """
    機能: 根指定34条件と旧条件の一軸性を確認し、最小境界の期待値を固定する。
    引数: なし。
    返り値: None。engine、正式入力又は新損益は実行・閲覧しない。
    """
    catalog = module('時計政策98の条件定義だけ独立読取', BASE / 'catalog.py')
    values = catalog.catalog()
    assert len(values) == len({value['id'] for value in values}) == 34
    assert catalog.PRIMARY == 'C1_A7_X3' and catalog.CONTROL == 'C0_A7_X3'
    allowed = {'id', 'previous_id', 'entry_clock_policy'}
    for value in values:
        old = catalog.PREVIOUS[value['previous_id']]
        assert {key: item for key, item in value.items() if key not in allowed} == \
            {key: item for key, item in old.items() if key not in allowed}
    cases = [
        dict(id='gap行で価格条件成立', 機構='A3', 進行pt=[0., 6., 6.5], 時計=[300., 320., 321.],
            期待='C0は旧gap取消。C1は正常gap行1で発注判断、次行2で約定。gap行の新発注禁止を隠して足さない。'),
        dict(id='gap行に元候補を受理', 機構='A1', 進行pt=[0., 0., 1., 1.5], 時計=[300., 320., 321., 322.],
            期待='eventは行1のみ。C1は行1で待機受理・gap取消なし、行2以降の新気配で発注。'),
        dict(id='peer時計が自己phaseと等しい新源', 機構='A1', 進行pt=[0., 1., 1.5, 2.],
            時計=[300., 301., 302., 303.], peer時計=[299.75, 300., 301., 302.],
            期待='C1は行1のpeer_clock==phaseを拒否。C2は各anchor後seq更新で行1を許可できる。共通phase後から各自anchor後への意味変更。'),
        dict(id='C2初回fallbackで触発しない', 機構='A3', 進行pt=[0., 4., 4.5, 5., 5.5],
            時計=[300., 301., 302., 303., 304.], peer時計=[299.75, 300., 301., 302., 303.],
            期待='候補のpeerだけ未知。C2の行1正常pairは基準のみ、行2から発注可能。peer>phaseを追加しない。'),
        dict(id='same-clock自己seqだけでは二市場証拠でない', 機構='A1',
            進行pt=[0., 1., 1.5, 2.], 時計=[300., 300., 301., 302.],
            期待='同時計行0/1は同じpeer格子へ写す。自己seq増加のみの行1でC2も発注しない。'),
        dict(id='C3はgap後だけ再準備', 機構='A7', 進行pt=[0., 12., 8., 6., 9., 5., 7., 7.5],
            時計=[300., 301., 320., 321., 322., 323., 324., 325.],
            期待='行2はgap停止・幾何更新禁止。行3はepochから逆方向でも再準備。peak/extremeは現quote6へ初期化しarm解除、行3発注禁止。新peak9から行5で押し、行6回復、次行7fill。'),
        dict(id='A3元候補quoteは再準備で変えない', 機構='A3', 進行pt=[0., 6., 6.5, 7., 7.5],
            時計=[300., 320., 321., 322., 323.],
            期待='C3行1gap停止、行2再準備、行3発注。candidate_quote4000と1W条件を維持。gap時4006や再準備4006.5を新起点にしない。'),
        dict(id='C3epochのpeer未知', 機構='A1', 進行pt=[0., 6., 6., 6., 6., 7., 7.5],
            時計=[300., 320., 321., 322., 323., 324., 325.],
            期待='行1epoch不明、行2peer_clock==epochなら基準不可。行3初正常両clock>epochは基準だけ、行4で両新源により再準備、行4発注禁止。'),
        dict(id='追加gapも元TTLを延ばさない', 機構='A3', 進行pt=[0., 6., 6.5, 7., 7.5, 8., 8.5],
            時計=[300., 320., 321., 340., 341., 342., 343.],
            期待='行2quality不合格で停止継続。行3追加gapでepochを置換、deadlineは600のまま。行4再準備、行5から発注可能。'),
        dict(id='TTLとgap同時・別候補同時', 機構='A3', 進行pt=[0., 0., 6., 6.5],
            時計=[300., 301., 600., 601.],
            期待='全政策でTTL取消先行。C3のepoch作成/再準備なし。解除行2の反対eventは消費し復活しない。'),
        dict(id='resetまたはqok不正とgap同時', 機構='A3', 進行pt=[0., 6., 6.5], 時計=[300., 320., 321.],
            期待='C0は旧gap取消優先を保持。C1～3は旧mandatoryのreset又はqok取消。C3で故障修復へ流さない。'),
        dict(id='原seq欠番へ新取消を足さない', 機構='A3', 進行pt=[0., 4., 4.5], 時計=[300., 301., 302.],
            期待='人工のseqだけ100/102/103、旧reset=Falseとする。C1/C2の追加seq cancelは無い。実上流の旧reset再構成を救済する主張ではない。'),
        dict(id='prefixと未来変形', 機構='A7',
            期待='C1/C2/C3でgap前・gap停止・再準備・押し・発注・fillの境界を切断。未来自己価格/peer BBO変形で過去watch/policy状態・イベント・注文が変わらない。')]
    assert len(cases) == 13
    root_plan = json.loads((BASE / '結果前の設計案.json').read_text(encoding='utf-8'))
    official = json.loads((BASE / '公式仕様の時計項目と保存原本の区別.json').read_text(encoding='utf-8'))
    assert root_plan['予定条件数'] == 34 and root_plan['理論主'] == catalog.PRIMARY
    assert root_plan['対照'] == catalog.CONTROL
    assert official['URL'] == 'https://kabucom.github.io/kabusapi/ptal/push.html'
    mathematical_cases = 0
    for own_now, peer_now, phase in product((99., 100., 101.), repeat=3):
        original = own_now > phase and peer_now > phase and peer_now <= own_now
        self_relaxed = peer_now > phase and peer_now <= own_now
        assert original == self_relaxed
        mathematical_cases += 1
    save('34指定仕様の独立反証と局所人工の事前期待値.json', dict(
        全合格=True,
        状態='損益前の仕様反証。実装検査は本体完成後に別証跡へ保存する。',
        条件数=34, 主=catalog.PRIMARY, 対照=catalog.CONTROL, 出口=['X1', 'X3'],
        共通固定='P0/J8候補、既存J2とQ/F、旧asof peer、8/16枚、W10bp、TTL300、料金、場内返済、次正常行fillを維持。',
        政策={
            'C0': '対応97の旧18配列を完全一致。取消の優先順も旧gapより後のreset/qokを含めて保持。',
            'C1': 'gap取消のみ除去。gap行発注禁止、gap行の幾何停止、gap行候補禁止を暗黙に追加しない。',
            'C2': 'C1から両index/seq>各anchor、各clock>=各anchorへ変更。共通phaseclock比較を除去。正常pairと旧asof上限は維持。fallbackはi>phaseかつownclock>=phase、最初正常pairは基準だけ。',
            'C3': 'C1からgap後だけ停止→epoch基準→両新源再準備。reset/qokは97通り取消。方向quote進行は再準備要件にしない。A3元quote保持、A7arm解除。'},
        epoch区別={
            '記録として保持': ['候補ID', '元candidate_row/seq/time/quote', 'W', 'advance/pullback/recovery幅', '元deadline', '枠占有'],
            'gap行': '正常な自己と公開peerをepoch基準へ固定。不明なら待つ。peak/extreme/armの幾何は更新せず、gap行で再準備又は発注しない。',
            'epoch未知時': '両clockがepoch_timeより厳密に後の最初正常pairを基準だけに固定。その行で再準備しない。',
            '再準備': '後続両index/seq更新、両clock>epochかつ>各anchor、quality/非reset/J2/正常pairを確認。現quoteでpeak/extreme/phase/BBO基準を初期化し、同行発注禁止。',
            '追加gap': '停止中もepochを更新できるが元候補期限は延ばさない。'},
        事前人工期待値=cases,
        必須数理反証=['peer_clock>phaseかつpeer_clock<=ownならown>phaseが必然。自己phase比較だけ除去した同値枝を改善数へ数えない。',
            '旧peer格子がown代理時計の決定関数である限りsame-clock自己seq進行だけでpeer新源は増えない。',
            'C2は共通phase後から各自anchor後へ証拠の意味も変える。真二市場受信順序を証明したとは呼ばない。',
            'gap取消除去が正常なgap行の新規まで禁止すれば、入口条件の追加変更を隠した対照になる。',
            'gapを保持して活動が増えても、高値買い/安値売りと新損失が増える反例を全経路で評価する。'],
        時計冗長性の人工全組合せ=mathematical_cases,
        因果順の留保='今回の再生clockはCurrentPriceTime由来で、真受信時計が無いため二市場の真受信順と真の経過時間は未観測。旧strict過去/同clock先頭の計算仕様を維持しても実受信因果性の証明にはならない。',
        公式仕様との区別={'URL': official['URL'],
            '独立原ページ確認': 'CurrentPriceTimeは現値時刻。BidTime/AskTime/Sell1.Time/Buy1.Timeは先物欄対象外。受信時刻や最良板の更新時計として流用しない。',
            '保存原本範囲': '根の旧97診断は139取消前後278行の時刻項目確認。全62原本の全行検査と拡張して主張しない。',
            '金融原本の時計': '現値、売買高、始値、高値、安値、前終値の時計項目も元原本へ保持する。役割が違うためそれらを共通受信時計と呼ばない。',
            '語の対応': '公式API BidPriceは最良売気配、AskPriceは最良買気配。研究のbid=買気配Buy1、ask=売気配Sell1とは名前を区別する。'},
        結果後評価='同候補実新規価格差、返済差、料金差、旧固有勝負、新固有勝負と活動/無取引を分解。赤字場数/平均最大赤字/RMSを優先し、双方80%と20親8場を別判定。',
        今回未測定='前案C4のreset/Q/深板/volume故障分離は入力再生成を必要とする別課題。今回の活動不足を成功へ言い換えない。',
        catalog_SHA256=digest(BASE / 'catalog.py'),
        根仕様SHA256=digest(BASE / '結果前の設計案.json'),
        公式根拠SHA256=digest(BASE / '公式仕様の時計項目と保存原本の区別.json'),
        計算コードSHA256=digest(Path(__file__)),
        新正式損益閲覧=0, 新正式売買実行=0, API取得=0, 実注文=0, 旧固定編集=0))
    print('34指定仕様と13種の局所境界期待値を損益前保存。正式PL・API・売買は0。', flush=True)


if __name__ == '__main__':
    main()
