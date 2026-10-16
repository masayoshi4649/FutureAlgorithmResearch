"""旧GUの損失診断に基づく逆行保険の三案と敵対的な反証を保存する。"""

from pathlib import Path
import hashlib
import importlib.util
import json
import pickle
import sys
from datetime import datetime

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True


def read(path):
    """
    機能: 保存JSONを読み込む。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def artificial():
    """
    機能: 保険機会の診断関数について上下反射と未来切断を検査する。
    引数: なし。
    返り値: dict の合否と比較数。未来最大幅は事後列なので比較対象外。
    """
    spec = importlib.util.spec_from_file_location('wave87_core_reversal_design', HERE / 'core_loss_reversal.py')
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    function = source.first_trigger
    causal = ('成立行', '成立価格', '指定可能な逆指値線', '直前までの極値', '極値行', '成立時順行ATR', '成立前最大順行ATR')
    comparisons = 0
    for prices in ([100., 99., 98., 97.], [101., 103., 102., 101.], [102., 99.],
                   [100., 100., 100.], [101., 102., 103., 104.], [101., 100., 104., 99.]):
        base = np.asarray(prices)
        indices = np.arange(1, len(base)+1)
        for arm in (0., .25, .5):
            for width in (.25, .5):
                for direction in (1, -1):
                    transformed = 100. + direction * (base-100.)
                    complete = function(indices, transformed, 100., 4., direction, 1., arm, width)
                    for length in range(1, len(base)+1):
                        prefix = function(indices[:length], transformed[:length], 100., 4., direction, 1., arm, width)
                        if complete is None or complete['成立行'] > length:
                            assert prefix is None
                        else:
                            assert prefix is not None
                            assert {k: prefix[k] for k in causal} == {k: complete[k] for k in causal}
                        comparisons += 1
                forward = function(indices, base, 100., 4., 1, 1., arm, width)
                reverse = function(indices, 200.-base, 100., 4., -1, 1., arm, width)
                assert (forward is None) == (reverse is None)
                if forward:
                    assert forward['成立行'] == reverse['成立行']
                    assert forward['成立価格'] + reverse['成立価格'] == 200.
                    assert forward['指定可能な逆指値線'] + reverse['指定可能な逆指値線'] == 200.
    immediate = function(np.arange(1, 4), np.array([99., 98., 97.]), 100., 4., 1, 1., 0., .25)
    assert immediate['成立行'] == 1
    assert function(np.arange(1, 4), np.array([99., 98., 97.]), 100., 4., 1, 1., .25, .25) is None
    return dict(未来切断比較数=comparisons, 上下反射と初期逆行境界=True, 新PL試行=False,
                注記='将来の追加逆行最大幅は事後ラベル。検査は現在までに確定する開始条件列だけを対象にする。')


def raw_examples(rows):
    """
    機能: 各商品の初期不発・順行後負け・勝ち反例を原板行で直接確認する。
    引数: rows(list[dict])。
    返り値: list[dict] の先頭順に選んだ六例。最適値探しには使わない。
    """
    proof = read(ROOT / 'work/wave_v85/prepared/入力準備の完了.json')
    inputs = {}
    for pair in proof['入力対応']:
        inputs.update(pickle.loads((ROOT / pair['inputs']).read_bytes()))
    choices = []
    for symbol in ('TOPIX', 'NK225'):
        local = [r for r in rows if r['銘柄'] == symbol]
        choices.extend([
            ('一度も順行せず負け', next(r for r in local if r['収支'] < 0 and r['最大順行ATR'] == 0)),
            ('025以上順行後に負け', next(r for r in local if r['収支'] < 0 and r['最大順行ATR'] >= .25)),
            ('同じ保険条件に触れる勝ち', next(r for r in local if r['収支'] > 0 and r['逆行開始診断']['順行025_逆行025'] is not None)),
        ])
    results = []
    for label, row in choices:
        ready = inputs[row['セッション'], row['銘柄']]
        trigger = row['逆行開始診断']['順行不要_逆行025'] if row['最大順行ATR'] == 0 else row['逆行開始診断']['順行025_逆行025']
        requested = {row['新規行'], row['返済行']}
        if trigger:
            requested.add(trigger['成立行'])
            if trigger['極値行'] >= 0:
                requested.add(trigger['極値行'])
        lookup = {int(ready['seq'][i])+1: i for i in requested}
        found = []
        path = ROOT / 'book' / row['銘柄'] / (row['セッション']+'.jsonl')
        with path.open(encoding='utf-8-sig') as stream:
            for number, text in enumerate(stream, 1):
                if number not in lookup:
                    continue
                raw = json.loads(text)
                raw = raw.get('data', raw)
                i = lookup[number]
                assert float(raw['CurrentPrice']) == ready['last'][i]
                assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp() == ready['time_s'][i]
                found.append(dict(原本行=number, 保存行=i, 価格=raw['CurrentPrice'], 時計=raw['CurrentPriceTime']))
                if len(found) == len(lookup):
                    break
        assert len(found) == len(lookup)
        results.append(dict(区分=label, セッション=row['セッション'], 銘柄=row['銘柄'], 親=row['組'],
                            旧親収支=row['収支'], 最大順行ATR=row['最大順行ATR'], 保険機会=trigger,
                            原本照合=found, 原本SHA256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return results


def main():
    """
    機能: 診断の結論、三つの事前仮説、未証明の点を日本語で保存する。
    引数: なし。
    返り値: None。report・取引実装・損益台帳は変更しない。
    """
    diagnostic_path = HERE / '元GU負け初回の順行前後別損失と保険機会.json'
    diagnostic = read(diagnostic_path)
    rows = read(HERE / '元GU逆行開始の全278親診断.json')
    basic = {}
    for symbol, value in diagnostic['期間別']['全30'].items():
        buckets = value['負親の最大順行別']
        zero = buckets['一度も建値より順行しない']['損失']
        slight = buckets['一度は順行したが025ATR未満']['損失']
        total = value['元負親']['損失']
        basic[symbol] = dict(元負親数=value['元負親']['負親数'], 元負親損失=total,
            一度も順行なし損失=zero, 一度も順行なし損失割合=zero/total,
            微小順行025未満まで含む損失=zero+slight,
            順行025以上の後で負けた損失=total-zero-slight,
            順行025以上の後で負けた損失割合=(total-zero-slight)/total,
            保険条件順行025逆行025=value['保険開始の機会と反例']['順行025_逆行025'])
    payload = dict(
        対象='元GU完全固定、現在までの順行極値から逆行したときだけ一度の独立保険を開始する案',
        新PL試行=False, 全場既知=True,
        短い結論=[
            '一度も順行しない負けは損失額のTOPIX13.7%・日経21.4%。0.25ATR以上順行してから負けた損失はTOPIX68.8%・日経57.8%。最初から違う方向へ入ったことだけでは説明できない。',
            'ただし0.25ATR順行後の0.25ATR逆行は、元の勝親TOPIX52/55・日経60/61にも成立する。逆行そのものが敗退の特異な兆候ではない。',
            '今回の変更は反転が観測されてから保険を建てるので、順行中の固定水準に反対玉を置くround7のフェードと別。下げ始める前から上昇利益を相殺する区間は減らせるが、通常の押しで保険損切りを支払う副作用が残る。',
            '原GUを固定したままなら合計改善額は保険の料金後収支。救済可能な負親の元損失額を、そのまま改善額又は的中額にはできない。',
        ],
        金額診断=basic,
        事前比較三案=[
            {'ID': '保険R0', '準備条件': '順行を待たず、新規実約定価格を最初の極値にする。以後の有利極値から0.25ATR逆行で反対玉を一度だけ開始。',
             '狙い': '初期の即逆行も対象にし、保険が広い初期損切りまでの追加損失を緩和できるか検証。',
             '反証': 'ほぼ全親に保険が触れる。旧勝親TOPIX53/55・日経60/61にも開始機会があり、最初のノイズへの保険料負担が大きくなり得る。'},
            {'ID': '保険R025', '準備条件': '0.25ATR順行が観測された後だけ準備し、その後の順行極値から0.25ATR逆行で反対玉を一度だけ開始。',
             '狙い': '初期不発を救うことは諦め、順行後に収益を失う機構へ絞る。0.25は既存入口の反発幅に合わせた粗い対照。',
             '反証': '0.25未満で終わる負けは対象外。通常の押しから伸びる既存勝ちにもほぼ全て触れるため、反対玉を外す判断が主要な勝負となる。'},
            {'ID': '保険R050', '準備条件': '0.5ATR順行が観測された後だけ準備。逆行幅は他案と同じ0.25ATR。',
             '狙い': '準備するまでの順行量だけを変える対照。新規する逆行幅や保険出口を同時に変更しない。',
             '反証': '救済対象の負親はさらに減る一方、元勝親TOPIX52/55・日経59/61にも触れる。強めの準備条件だけで通常の押しを除けるとは言えない。'},
        ],
        三案共通の仮仕様={
            '主玉': '元GUの注文・実約定・通常影・出口影・B00減量・部分利確・1R組予算・U回避・再参加時計を完全に不変にする。保険損益を渡さない。',
            '情報': '価格現在値と主玉実約定時の固定ATRだけ。将来の最大順行や親の最終勝敗で対象を選ばない。',
            '数量': '開始注文を出す時点の主玉残枚数以下を一度だけ反対に建てる案が自然。後の主玉減量で保険の方が多くなる場合は純反対露出を別記する。数量追従させるなら独立した変更として固定し、途中で都合よく選ばない。',
            '保険出口': '初期停止0.25ATR、順行0.5ATRで追尾開始、追尾幅0.25ATRを共通の機構対照とする。狭い往復に触れ続けることを隠さず、同一親で再保険しない。',
            '成立と約定': '極値と開始逆指値線は現在行で更新し次の保存観測から有効。指定線モデルと観測現在値モデルを別再生し、既通過の古い有利価格に戻して約定しない。',
            '主玉終了': '当行の既知主玉全返済を見て、保険残玉返済を次観測へ予約。未来の主玉終了行を事前に渡さない。同一行の保険新規と主玉終了が重なると往復料を残す。',
            '未確定範囲': 'これは本実験の事前提案。数量・出口の最終凍結と新PL再生は親担当で行う。診断の0.5ATR逆行は粗い感度資料であり、結果に応じて三案を選び替えない。',
        },
        救える可能性がある原因=[
            '準備後の反転が続き、逆向き保険の開始後も同方向へ動く。主玉が失う一部を保険の含み益・実現益で相殺できる。',
            '広い主玉の初期停止又は追尾停止までの逆行を、先に建てた保険が一時的に受ける。主玉を永久に閉じずに一時的な露出縮小にできる。',
            '追加床が主玉まで早く返したround6の失敗は避けられる。保険の停止・追尾で主玉を返済しないため、元の大波を取る主玉経路は残せる。',
        ],
        救えない又は悪化し得る原因=[
            '準備する順行に届かない初期失敗はR025/R050では対象外。開始前に失った金額は保険を建てた瞬間には回復しない。',
            '逆行線を一度に飛び越える価格跳躍では、有利な過去価格で保険を建てられない。元玉と保険が同時に終了して料金だけ増える場合がある。',
            '通常の押しで反対玉を建て、直後に元方向へ伸びると保険停止の損失が主玉利益を削る。保険の勝率より合算親収支を見る。',
            '同枚数の両建て中は、同価格・費用前なら合計損益がその場で固定される。伸び続ける主玉の利益も保険損失で相殺する。利益側だけを数えてはならない。',
            '保険を利益確定した後に再び逆行すると、一回だけの保険はその後を覆わない。一方、再保険を許すと往復料と複数回損切りが累積する別戦略になる。',
            '主玉減量後の保険過大数量は、主玉保護ではなく純逆方向への取引になる。片方向上限と純数量・総枚数の両方を検査する。',
        ],
        狭い初期損切りとの違い=[
            '初期損切りを狭めると主玉を閉じ、元の影時計によって再参加も変わり得る。独立保険は主玉の全経路を残し、露出を一時相殺するため制御対象が異なる。',
            'ただし理想同価格・同数量なら、保険を売って買い戻す操作は主玉を一度閉じて同じ時点で買い直す操作と同じ経済露出を作る。両建てという会計形式自体は優位の証明ではない。',
            '主玉を固定することは比較として有効だが、保険の停止損失と料金を追加するため総口座の初期リスクが同じとは言えない。',
        ],
        既検証との非同値={
            'wave_v25': '直近有利価格から0.75ATR戻った半量保険と0.5ATR追尾は既検証。全玉合算管理・異なる入口配分で、元GU固定の独立一回保険ではない。',
            'wave_v70': 'grid_mode=1で現在までの有利価格へ基準を更新し、逆行格子で段階保険する類似機構あり。複数回・複数枚追加、保険全体の利益限定追尾、主玉全体の共通停止・保有期限であり、今回と完全同値ではない。',
            'wave_v71': '旧70と同じエンジンで主玉と保険の追尾幅を個別比較したが、保険単独の初期停止はなかった。入口のE01Pも元GU全実注文固定を意味しない。',
            'wave_v87_round7': '主玉建値から0.5/1ATR順行する固定線で反対玉を新規する。反転確認前から元方向利益を相殺するのに対し、新案は実際の押し戻りが生じてから開始する。',
            'まとめ': '逆行保険や極値追随自体が未発見だったわけではない。今回は元GUを制御として固定し、一回・保険単独停止で作用を分離する未同値の検証案。',
        },
        本実験で必要な反証=[
            '追加有効時にも主玉台帳の全配列一致。合算改善額が保険全脚の料金後収支に一致すること。',
            '同じ条件を元の全278親へ適用し、事後の負け親だけに保険を付けない。元勝親の減益、負親救済、勝親赤字化、全口座DDを併記する。',
            '同一親での保険回数1回、初回・部分返済・保険終了での消費フラグ維持、同一行の注文順序と実保有/予約上限を人工試験する。',
            '下落から上昇への鏡像でも同結果、未来切断、価格跳躍、同時計行、欠測、Uと場末返済を検査する。',
            '全期間は既知なので事前仕様固定でも未見成功とは呼ばない。前16/後14/各セッション/最大勝日除外を同条件で確認し、後半から最適幅を選ばない。',
        ],
        診断関数の人工検査=artificial(),
        六例の原板独立照合=raw_examples(rows),
        診断SHA256=hashlib.sha256(diagnostic_path.read_bytes()).hexdigest(),
    )
    target = HERE / '順行極値からの逆行保険三案と敵対的結論.json'
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(保存先=str(target), 人工検査=payload['診断関数の人工検査'],
                         原板例数=len(payload['六例の原板独立照合']),
                         原板照合行数=sum(len(v['原本照合']) for v in payload['六例の原板独立照合'])), ensure_ascii=False))


if __name__ == '__main__':
    main()
