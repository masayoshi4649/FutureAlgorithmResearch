"""現在の二市場状態から追従と往復を選ぶ案の既往差分と入力接続を整理する。"""

from pathlib import Path
import hashlib
import json
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path):
    """
    機能: 旧素材を変更せず内容指紋を一定メモリーで取得する。
    引数: path(Path)。
    返り値: str。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(8*1024*1024),b''):
            value.update(part)
    return value.hexdigest()


def read(path):
    """
    機能: 保存済みの仕様又は入力を読取専用で読む。
    引数: path(Path)。
    返り値: object。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def connect():
    """
    機能: 既存60口座の原本行と二市場格子の価格・時計接続を検算する。
    引数: なし。
    返り値: dict。新戦略の損益や採否を計算しない。
    """
    meta = read(ROOT/'work/wave_v77/inputs/metadata.json')
    original = {}
    paths = [ROOT/name for name in meta['input_paths']['ready']]
    paths.append(ROOT/meta['extra_paths']['ready'])
    for path in paths:
        additional = read(path)
        assert not set(original) & set(additional)
        original.update(additional)
    prices_path = ROOT/'work/wave_v83/prepared/inputs.pkl'
    price_proof = read(ROOT/'work/wave_v83/prepared/価格入力の照合.json')
    assert sha(prices_path) == price_proof['出力SHA256']
    prices = read(prices_path)
    grids_path = ROOT/'work/wave_v77/inputs/grids_delay1.pkl'
    grids = read(grids_path)
    states_path = ROOT/'work/wave_v78/prepared/signals_delay1.pkl'
    states = read(states_path)
    assert set(original) == set(prices) and len(prices) == 60
    assert set(grids) == set(states) == {key[0] for key in prices} and len(grids) == 30
    accounts, grid_proofs = [], []
    for key, price in prices.items():
        source = original[key]
        for new,old in (('seq','seq'),('time_s','time_s'),('price','last')):
            np.testing.assert_array_equal(price[new],source[old])
        assert np.array_equal(price['source_i'],np.arange(len(price['seq'])))
        accounts.append(dict(session=key[0],symbol=key[1],rows=len(price['seq']),
                             元readyのseq時計CurrentPrice完全一致=True))
    for session, package in grids.items():
        grid = package['grid']
        state = states[session]
        np.testing.assert_array_equal(grid,state['grid'])
        count = dict(session=session,grid_rows=len(grid),markets={})
        for symbol,name in (('TOPIX','source_top'),('NK225','source_nk')):
            market = package['markets'][symbol]
            current = market['current']
            price = prices[session,symbol]
            now = current['index']
            good = now >= 0
            np.testing.assert_array_equal(now,state[name])
            assert ((grid[good]-1.)>price['time_s'][now[good]]).all()
            assert ((grid[good]-1.-price['time_s'][now[good]])<=30.+1e-6).all()
            for field,new in (('last','price'),('bid','bid'),('ask','ask')):
                np.testing.assert_array_equal(current[field][good],price[new][now[good]])
            window = market['windows'][300]
            finite = np.isfinite(window['efficiency'])
            assert np.all(window['source_valid'][finite])
            assert np.all((window['efficiency'][finite]>=0)&(window['efficiency'][finite]<=1.+1e-9))
            count['markets'][symbol] = dict(current_valid=int(good.sum()),ER300有限=int(finite.sum()),
                元原板価格との接続一致=True,代理時計のstrict過去=True)
        grid_proofs.append(count)
    return dict(口座数=60,場数=30,全合格=True,口座=accounts,格子=grid_proofs,
                入力SHA256={str(path.relative_to(ROOT)):sha(path) for path in
                    [*paths,prices_path,grids_path,states_path]})


# ----------------------------------------


def main():
    """
    機能: 現在状態の切替案と既検証差分、最小データ契約をJSONへ保存する。
    引数: なし。
    返り値: None。新条件の損益は計算しない。
    """
    refs = [
        'work/wave_v53/signals.py','work/wave_v53/engine.py','work/wave_v53/backtest.py',
        'work/wave_v76/事前固定.json','work/wave_v76/inputs/core.py',
        'work/wave_v77/事前固定.json','work/wave_v77/inputs/core.py','work/wave_v77/signals.py',
        'work/wave_v77/inputs/metadata.json','work/wave_v78/事前固定.json','work/wave_v78/signals.py',
        'work/wave_v78/engine.py','work/wave_v78/study.py','work/wave_v79/prevention.py',
        'work/wave_v80/初回事前固定.json','work/wave_v80/design/入口仕様.json',
        'work/wave_v81/初回事前固定.json','work/wave_v81/design/方向仕様.json',
        'work/wave_v82/research.py','work/wave_v83/catalog.py','work/wave_v83/persistent_engine.py',
        'work/wave_v83/persistent/固定条件.json','work/wave_v83/data.py',
        'work/wave_v83/prepared/価格入力の仕様.json','work/wave_v84/catalog.py',
        'work/wave_v78/results/J2_F0_B0_H0_R0.json',
        'work/wave_v78/sensitivity/delay1/results/J2_F0_B0_H0_R0.json',
        'work/wave_v83/persistent/results/O06_W08_V2.json',
    ]
    ready_proof = connect()
    old = {}
    for name in refs[-3:]:
        result = read(ROOT/name)
        period = '対象' if '対象' in result['periods'] else '全30'
        old[name] = dict(config=result['config'],
            全30={symbol:{field:result['periods'][period][symbol][field] for field in ('net','profit_share')}
                 for symbol in ('TOPIX','NK225')},
            後14={symbol:{field:result['periods']['後14'][symbol][field] for field in ('net','profit_share')}
                 for symbol in ('TOPIX','NK225')})
    output = dict(
        対象='次段階候補：現在の二市場価格経路で追従と往復を機械的に使い分ける案',
        位置付け='既往と入力接続の読取調査。具体カタログの凍結前であり、採否・新損益・有用性を証明した結果ではない。',
        重要な既検証=[
            dict(出典=refs[:3], 内容='v53はすでにER15分>=.4とEMA/VWAPで追従、ER<=.25で反復を自動分類し、追従/T02等と反復/T01等の入口を固定順で選択。途中のトレール幅や保有期限も状態に応じて短縮している。現在状態による戦略選択という思想自体は新規でない。'),
            dict(出典='work/wave_v77/signals.py', 内容='J3はJ2入口へ双方300秒ER>=.2を追加済み。Qは板一致、Pは共通方向中の反落→再進行を固定入口として比較済み。効率フィルタだけの新名を再発見とは呼ばない。'),
            dict(出典='work/wave_v78/事前固定.json', 内容='162統合はJ0/J1/J2、板反対による出口、利益保護、保有延長、連敗後再準備の直積。H1は保有期限に共通方向、利益、新値の維持を確認して延長する。'),
            dict(出典='work/wave_v79/prevention.py', 内容='双方ER>=.2等の入口改善と短期逆行出口を比較済み。効率を上げれば常に損失が減るという一般結論は不可。'),
            dict(出典=['work/wave_v80/design/入口仕様.json','work/wave_v81/design/方向仕様.json'], 内容='瞬時板フロー/価格反転/両市場支持を入口と継続/降車に使う方式、受動指値待機・取消・価格と板一致は既検証。今回にその名前だけを付け直さない。'),
            dict(出典=['work/wave_v82/research.py','work/wave_v83/catalog.py','work/wave_v84/catalog.py'], 内容='82は固定方向方式の反転対照、83は固定注文家族と持続指値、84は順行新規と追尾後ドテン等。76–84の確認した仕様・実装には、ERでJ2と持続O06を相互選択する同一統合のカタログは見つからない。これは全歴史の不存在の証明ではない。'),
        ],
        残る具体的差分='ATRなし・二市場共通300秒の価格経路効率と方向・J2追従とO06持続指値IFD・未約定指値の市場状態失効取消まで一つの予約状態へ接続する具体構成。旧v53のATR/VWAP/15分系統選択とは入力、窓、源、注文層が異なる。',
        過去親成績ゲートから変更する理由='トレーリング等で閉じた親の最終利益は、往々にしてその波が終わった後に公開される。過去利益で参加を再開することは現在も波が続くという証拠ではない。現在の値動きや注文状態を直接確認する。ただし現在ERも過去窓の統計であり次の方向を保証しない。',
        原理='純変位/総往復値幅のERが大きい状態では順方向へ離れる性質、小さい状態では変位に対し往復距離が大きい性質を観測する。両商品で一致する現在状態を使う。どの価格にも買い手と売り手はいるので、低ERを参加者の焦りや補充の証明と呼ばない。',
        元候補の旧確定成績=old,
        元候補の限界='J2は1秒素材でも両商品・前後期間で黒字だが金額割合は55.8%/56.7%程度。O06持続版は全30NKが-457720円であり、両商品有望な完成手法ではない。低ER選択で改善するかは未検証。両者の旧損益を足して混合の成績としてはならない。',
        既存データ接続=ready_proof,
        最小入力=dict(
            実注文='work/wave_v83/prepared/inputs.pkl：60口座。time_s/seq/price/bid/ask/price_valid/quote_valid/tick/start/limit/end。source_iは元ready行と一致。',
            共通状態='work/wave_v77/inputs/grids_delay1.pkl：30場、各場にTOPIX/NK225両市場。5秒格子、current.index/valid/q_valid/spread_ticks、windows[30,60,180,300,600]、ranges[60,180]、flow[15,30]。',
            元J2='work/wave_v77/prepared/signals_delay1.pklのentries[J2]とlegacy_delay1.pklの原本候補。work/wave_v78/prepared/signals_delay1.pklにcommon/trend300と両市場参照行、既検証反対FD。',
            必須列='current.bid/ask/last、windows[300].ret_bp/efficiency/total_variation/source_valid/unique_observations、windows[30].ret_bp、ranges[180].high/low/position/source_valid、flow[15].ofi_ratio/valid/nonzero_ofi_count/missing_ofi。',
            追加生成='現在データの上記列は既存。戦略採否・取消イベント、共通注文UID/親IDと源別清算時価の新接続だけが必要。raw原本の再収集や機械学習は不要。',
        ),
        時計と鮮度=dict(
            初期時間='格子の開始はstart+300秒。ER300も現在端点と300秒前の端点が別行・正常・窓中resetなしの場合だけ有効。最初5分を無理に往復モードにしない。',
            代理時計='各市場端点はgrid−1秒より厳密に古い最新時計の先頭行。最終約定時計代理であり真の受信順又は先行因果の保証ではない。',
            古さ='保存素材はgrid−1から30秒以内（実代理古さ31秒以内）。新候補でmax実古さ10秒を採る場合はcurrent.actual_age<=10の追加品質として一律適用し、古い良い板へ遡らない。1秒は情報準備条件で、注文まで一律5秒遅延を加える意味ではない。',
            対応='格子から原本への対応は当時以下の最新格子、格子から10秒以内。有効源indexと原本seqの同一性を保持し、同時計末尾へ未来整列しない。',
            無効='どちらか無効・ER総変動0・range幅0・窓未充足は不明。低ER又は売り買い中立へ代用しない。指標欠測だけで既保有玉を強制返済しない。',
        ),
        状態選択の最小案=dict(
            追従='双方300秒ERが高く、J2の共通300秒方向・30秒維持・弱い側1/4以上・明確逆OFI除外を満たす時にその方向の追従新規を許可。',
            往復='双方300秒ERが低く、現在中値が直前180秒範囲内で、双方の新しい共通進行が成立していない時だけO06の上下指値候補を許可。低ERだけで反発確率が高いと決めない。',
            不明='中間ER、二市場の状態不一致、欠測、範囲外は新規を見送る。保有や元の損切り/IFD/追尾は継続。',
            閾値候補='最小主の例はER高.4/低.2の空白帯。既検証J3の.2と旧53の高.4は比較根拠であって収益根拠ではない。近傍高.3/.5、低.1/.3は一軸対照として事前固定を検討。ここではカタログや主条件を正式凍結しない。',
            開始持続='単一格子での頻繁な切替を避けるため、同じ有効状態の2回連続又は15秒持続と両市場源更新を事前定義。新規だけを許可する最初の比較と、途中撤回を追加する比較を分ける。',
            予約取消='O06未約定の間に往復条件を失ったら取消を判断。前に生きていた指値がその観測で約定する場合はそれを先に扱い、今の失効を過去へ遡らせない。次有効観測で取消が有効になるモデルなら、その間の指値約定も保持する。',
            途中撤回='range保有中に両市場の明確な反対追従が成立した場合の全返済等は、入口だけの候補と別の一軸対照にする。追従からrangeへ変化しただけで利益玉を全部切る規則は既往の大勝ち喪失を繰り返す可能性がある。',
            保有時間='元J2 H0の30分は基準比較として保持。混合が時間で都合よく改善したかを分ける。不要な固定持続を新規に追加せず、持続IFDは元の利益/損切り/場末で閉じる。',
            上限='まず一つの統合口座で一源だけ新規、保有と待機指値を含め片方向TOPIX10/NK20。使っていない源の潜在紙上損益を実口座へ計上しない。固定小枠同時運転を調べるなら別配分条件として事前定義。',
        ),
        約定共通化の最小要件=[
            'J2とO06で共通原本seq、CurrentPriceTime、bid/ask、有効性、倍率と注文料金を使用する。旧J2の条件を次有効気配で買ask/売bid、O06指値も予約後の有効気配だけで判定する。',
            '持続指値は買いならask<=limit、売りならbid>=limitで元limitに全量約定した代理モデル。価格改善を勝手に与えない。条件成立行と同じ行を約定に使わない共通モデルへ変えるなら、O06停止なし対照もそのモデルで再生し、旧完全一致との差を明示する。',
            '成行、指値、取消、既知場末の順序を新損益前に固定する。J2の追加情報遅延と注文待ちを二重計上しない。価格フル約定と気配約定の旧差分を費用だけと呼ばない。',
            '新規/返済ごとfloor(q×41.8/11)。失効取消に手数料は課さない。未約定枠は予約時から上限を占有。',
            '新規源と親IDを保持し、源別親netの正負でG/Lを計上。源間の日別相殺から勝率を作らず、全原板行で含み損と残玉返済料を含む清算時価も監査。',
        ],
        最小対照と敵対検査=[
            'J2単独、O06単独、双方固定配分、現在状態で入口だけ選択、未約定取消を追加、途中撤回を追加を同一気配モデル・同じ数量制約で比較する。',
            'ER300はU字反転や一度の跳躍でも小さく/大きくなる。レンジかトレンドかの真理ではない。二市場逆行、価格急変、窓中欠測、ゼロ変動を人工反例にする。',
            '指値が不利な時だけ約定する逆選択と、良い時は未約定のまま利益を逃す効果を別に数える。取消判断前の約定を遡って除外しない。',
            '将来価格、将来OFI、将来モードを改変しても過去の状態、候補新規、取消予約が不変か、素材生成から実注文まで切断する。',
            '元の大勝ちと大負けを両方追跡し、回避損失、失った利益、新しい約定経路、料金を分離する。状態ゲートの拒否率と活動場数も出す。',
            '全30は既知。高/低ERの境界を全損益を見て最適化した参考と、理論指定の主を分ける。両商品80%と全日安定は結果で別判定する。',
        ],
        新条件損益計算=0, 新条件損益閲覧=0, API取得=0, 実注文=0, 旧凍結成果変更=0,
        原典SHA256={name:sha(ROOT/name) for name in refs},
    )
    target = HERE/'現在の二市場状態で追従と往復を選ぶ案の既往差分と最小入力接続.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('二市場現在状態の既往差分、60口座入力接続と最小設計を保存しました。新損益計算は0件です。',flush=True)


if __name__ == '__main__':
    main()
