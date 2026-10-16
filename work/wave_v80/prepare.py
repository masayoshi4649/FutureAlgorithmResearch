"""保存済み30場から八入口を準備し、因果時計と途中切断を照合する。"""
from pathlib import Path
import hashlib
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode = True
from signals import FAMILIES, build_session, market_features, direction_states


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    """
    機能: ファイルを分割読取してSHA256を計算する。
    引数: path (Path) は読取対象。
    返り値: str のSHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


# ----------------------------------------
def specification():
    """
    機能: 損益を見ない段階の因果仕様と改修方針を定義する。
    引数: なし。
    返り値: dict の数値条件と制約。最終注文条件はrootの事前固定を優先する。
    """
    return {
        '状態': '新しい取引損益を一切参照せず、旧研究の失敗から固定した入口仕様。',
        '範囲': '既知30場。前16で発見・選定し後14で確認するが、後14も未見とは呼ばない。',
        '状態添字': {str(i): s for i, s in enumerate(FAMILIES)},
        '時計': 'grid=start+60からlimit−120まで1秒ごと。各市場はtime<grid−1の最新時計の先頭原本準備行。現在の期限からage<=10秒、reset行は不採用。10秒/30秒の始点もtime<grid−1−window、始点期限からage<=15秒。最新候補が不正な場合に古い良い板へ遡らない。',
        '鮮度仕様変更の理由': '損益計算前に厳格3秒版をstrict3へ保存。代理時計の更新間隔は中央値3/4秒、95%点22/31秒であり、双方の現在/10/30秒始点へ3秒以内を要求すると共通有効格子が7336/1056600まで減り、8入口の多数が比較不能だった。更新頻度に基づき現在10秒/始点15秒へ変更。新損益や後半成績に合わせた緩和ではない。ゼロ機会の入口は無理に再設計しない。',
        '価格品質': '双方の現在/10秒/30秒始点は正の数量・正常なbid<ask・spread<=1ラージ呼値。窓中にvalid=false又はresetを跨がない。S1単独対照にも同じ両市場価格品質を適用し、相手の方向内容だけを外す。',
        '表示数量': '表示板の増減と価格の変化を観測する。成行/取消/補充/参加者の焦りを一意に識別したとは言わない。',
        'F10': '最良OFIのold10行を除きnow行を含む和/絶対和。有限値のみの窓・非ゼロ変化3件以上・絶対和>0を要求。不足時NaN。価格が同時計の後続原本行を現在の端点には使わないが、過去の時計の行は参照期限前の履歴としてOFI集計へ含む。',
        'R10_R30': '窓始点から現在中値までの変化÷ラージ呼値。TOPIX0.5、NK22510。商品間で生の数量や価格変化を加算しない。',
        '持続': '下記瞬時方向が同じ向きに3秒連続し、確認開始後に自己原本参照が更新。S2〜S8は相手参照も更新。欠測で確認を破棄。同じ古い板を繰り返すだけでは成立しない。出力は持続した方向状態で、発注イベント化や休止は注文エンジンの担当。',
        'S1': 'dF自己10>=0.3 かつ 0<=dR自己10<=1。相手の方向は参照しない。',
        'S2': '双方dF10>=0.3、双方dR10>=0、自己dR10<=1。価格がまだ進んでいない板支持を含む。',
        'S3': '双方dR10>=1かつ双方dF10>=0.1。価格が動いた後に追う対照。',
        'S4': '相手dR10>=2、自己0<=dR10<=1、双方dF10>=0.1。先行因果の証明ではなく、代理時計上の遅行状態。',
        'S5': '双方dR30>=2、自己−2<=dR10<=−1、自己dF10>=0.1、相手dF10>=0。自己F10が非正から正又は非負から負へd方向に反転して5秒以内で同方向を維持。欠測で反転履歴を消す。',
        'S6': '旧方向−dへ自己R30が3呼値以上進み、[old10+1,now]の高値/安値が[old30,old10]を更新せず現在値も旧極値から戻る。自己dF10>=0.1、相手dF10>=0。旧進行の反対方向dへ入る失速逆張。',
        'S7': '自己の直近10秒内で同じ最良支持価格が連続表示され、その数量が先行ピークの50%以下に減少し、その後80%以上へ回復した状態。買いはbid、売りはask。価格変更・reset・不正値で回復系列を切る。相手dF10>=0.1、自己−1<=dR10<=1。表示回復は補充の直接証明ではない。',
        'S8': 'grid開始から30秒区間ごとに買い/売りを交互にする。方向は価格・数量・損益の符号に依存しない。品質・持続・更新条件は同じ。乱数の好結果を選ぶことはしない。',
        '約定担当への提案': {
            '比較': '各入口を成行追随と、判断時買bid/売askで待つ指値に分ける。注文の5秒遅れは情報1秒遅れと別に記録。',
            '指値': '注文到着前の価格接触を約定にしない。待ち時間20秒を事前固定する案。接触約定と、反対気配が指値を1呼値越えた保守的約定を区別し、表示数量だけで自分の順番到来と決めない。取消にも注文遅れを課す。',
            '保有': '20/60/120秒を小集合として固定。手数料込みで利確と小損を比較し、セッション内全返済。全量10/20の同一条件で商品別評価。',
            '費用': 'TOPIXmini10枚は往復836円、1呼値5000円、0.1672呼値相当。NK225micro20枚は往復440円、1呼値2000円、0.22呼値相当。両市場1呼値スプレッドでは中値が1呼値しか進まなければ往復成行の粗益は概ね0となり、さらに手数料で赤字。',
            '小幅設計': '利益幅だけを小さくせず、遅延後の平均負けと追加再エントリー費用を含める。2呼値の返済気配での利確・2呼値の損切りと、3呼値利確等の少数対照を固定する案。'
        },
        '損失増加時の事前診断と改修案': [
            {'診断': '判断時点では優位だが、注文到着5秒までに期待方向を使い切る。判断時と到着時の自己気配、入口遅延不利幅、約定後MFEを別計上。', '改修案': '成行追随を上限価格付き指値へ置換し、同じ目標値幅・保有時間を維持。上限を越えたら追わない。ただし不利な時だけ約定する逆選択も検査する。'},
            {'診断': '中値では回収できても気配差・手数料で赤字。費用前/気配後/手数料後を分け、約定回数に比例する損失かを確認。', '改修案': '受動指値入口の対照へ進み、到着前接触・同価格キュー未確認を利益に数えない。待ち伏せが有利かは約定率と約定後の逆行も含めて判断。'},
            {'診断': '短い戻りで損切りし、その後に元方向へ戻る負けが増える。元勝ちの切断損、元負け改善、新規経路を分解。', '改修案': '入口の方向根拠が消えた場合だけ部分縮小する案を事前固定し、単に全てを半数にした対照と比較。全量撤退を何度も繰り返さない。'},
            {'診断': '指値は多く約定するが、約定後すぐ一方向へ突き抜ける。未約定も含めて到着/接触/貫通を数える。', '改修案': '指値送信時に二市場の強い逆向き支持がある場合は見送る。注文後の取消は5秒後に有効とし、その間の約定は残す。'},
            {'診断': '支持は片側だけ、又は低更新窓に集中し、両商品で再現しない。', '改修案': 'S1対S2を同じ価格品質・注文法・時間上限で比較し、支持強度の結果合わせの追加最適化を避ける。'}
        ],
        '改修手順': '初回結果の前16だけから事前診断を選び、原因と一つの変更を記録して再計算。その後14を見た結果による差替えはしない。改修前後と無改修対照の全場を残す。既知標本なので未知将来の証明ではない。',
        '未検証': ['実受信時刻の二市場同期', 'ラージ気配と実ミニ/マイクロの注文板の差', '指値のキュー順位と隠れ数量', '今回の新規則の損益'],
        '旧研究からの制約': [
            {'出典': 'アルゴリズム調査/00056_小幅回収と移動平均の比較/README.md', '知見': 'BB内復帰の小幅回収は旧23場の中値でTOPIX+306250/NK+128500円、追加2場も正だったが、全25場の買ask売bid評価は−1880000/−486000円。費用0なので手数料を入れればさらに不利。'},
            {'出典': 'アルゴリズム調査/00072_二市場の即時板判断と保有管理/README.md', '知見': '板支持の早い入口は情報遅延変更でNKが赤字になる例があり、主5秒だけの好成績を採用根拠にしない。'},
            {'出典': 'work/wave_v79/report/結論レビュー.json', '知見': '30分型の短期逆行撤退は元負けを軽くしても元勝ちをより大きく失った。秒単位へ切り替えても、その事実だけで優位が生まれるとは仮定しない。'}
        ],
        'ネットワーク': '現在API取得0・実注文0。既存原本・旧成果を変更しない。'
    }


# ----------------------------------------
def prefix_check(grid, ready, books, full):
    """
    機能: 将来行を物理的に除いた三地点の特徴と状態を元計算と照合する。
    引数: grid (ndarray)、ready/books/full (dict) は一場の入力と完全出力。
    返り値: int の両商品を別々に数えた照合回数。
    """
    checks = 0
    for fraction in (.2, .5, .8):
        length = max(1, int(len(grid) * fraction))
        short_grid = grid[:length]
        markets = {}
        for symbol in ('TOPIX', 'NK225'):
            r, b = ready[symbol], books[symbol]
            n = len(r['time_s'])
            stop = np.searchsorted(r['time_s'], short_grid[-1] - 1., side='left')
            short_r = {k: v[:stop] if isinstance(v, np.ndarray) and v.ndim > 0 and len(v) == n else v for k, v in r.items()}
            short_b = {k: v[:stop] if isinstance(v, np.ndarray) and v.ndim > 0 and len(v) == n else v for k, v in b.items()}
            markets[symbol] = market_features(short_grid, short_r, short_b)
        for own, peer in (('TOPIX', 'NK225'), ('NK225', 'TOPIX')):
            check = direction_states(short_grid, markets[own], markets[peer])
            for field, value in check.items():
                if isinstance(value, np.ndarray):
                    expected = full[own][field][:, :length] if value.ndim == 2 else full[own][field][:length]
                    assert np.array_equal(value, expected, equal_nan=True), (own, fraction, field)
            checks += 1
    return checks


# ----------------------------------------
def main():
    """
    機能: 同じ30場の因果入力を生成し、照合証跡と数値仕様を保存する。
    引数: なし。
    返り値: None。prepared/signals.pkl、design/入口仕様.json等を保存する。
    """
    meta_path = ROOT / 'work/wave_v77/inputs/metadata.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    paths = {
        'ready': [ROOT / p for p in meta['input_paths']['ready']] + [ROOT / 'work/wave_v77/inputs/extra_inputs.pkl'],
        'features': [ROOT / p for p in meta['input_paths']['features']] + [ROOT / 'work/wave_v77/inputs/extra_features.pkl'],
    }
    inputs = {}
    for kind, group in paths.items():
        inputs[kind] = {}
        for path in group:
            with path.open('rb') as file:
                values = pickle.load(file)
            assert not set(inputs[kind]) & set(values), '入力キーの重複'
            inputs[kind].update(values)
    ready, books = inputs['ready'], inputs['features']
    sessions = meta['sessions']; assert len(sessions) == 30
    assert all((session, symbol) in ready and (session, symbol) in books for session in sessions for symbol in ('TOPIX', 'NK225'))
    prepared, design = HERE / 'prepared', HERE / 'design'
    prepared.mkdir(exist_ok=True); design.mkdir(exist_ok=True)
    spec = specification()
    spec['前16'] = sessions[:16]; spec['後14'] = sessions[16:]
    spec['コードSHA256'] = {name: digest(HERE / name) for name in ('signals.py', 'prepare.py')}
    spec['入力SHA256'] = {str(p.relative_to(ROOT)): digest(p) for group in paths.values() for p in group}
    (design / '入口仕様.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
    output, counts, prefix_total = {}, [], 0
    for session in sessions:
        result = build_session(ready, books, session)
        output.update(result)
        grid = result[(session, 'TOPIX')]['grid']
        prefix_total += prefix_check(grid, {s: ready[(session, s)] for s in ('TOPIX', 'NK225')},
                                    {s: books[(session, s)] for s in ('TOPIX', 'NK225')},
                                    {s: result[(session, s)] for s in ('TOPIX', 'NK225')})
        for symbol in ('TOPIX', 'NK225'):
            signal = result[(session, symbol)]
            peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
            for side, name in (('self', symbol), ('peer', peer)):
                r = ready[(session, name)]
                for window in (0, 10, 30):
                    index = signal[f'source_{side}'] if window == 0 else signal[f'old_{side}{window}']
                    ok = index >= 0
                    deadline = grid[ok] - 1. - window
                    times = r['time_s'][index[ok]]
                    assert np.all(times < deadline) and np.all(deadline - times <= (10. if window == 0 else 15.))
                    assert np.array_equal(np.searchsorted(r['time_s'], times, side='left'), index[ok])
            counts.append({'セッション': session, '商品': symbol, '格子数': len(grid), '価格有効格子数': int(signal['valid'].sum()),
                           '入口状態格子数': {family: int(np.count_nonzero(signal['states'][i])) for i, family in enumerate(FAMILIES)}})
        print(json.dumps({'準備済み': session}, ensure_ascii=False), flush=True)
    target = prepared / 'signals.pkl'
    with target.open('wb') as file:
        pickle.dump(output, file, protocol=pickle.HIGHEST_PROTOCOL)
    proof = {'全合格': True, '口座数': len(output), '途中切断比較数': prefix_total,
             '同時計先頭と厳密過去': True, '現在鮮度10秒以内': True, '10秒30秒始点の鮮度15秒以内': True,
             '入口状態格子数は取引数ではない': True, '各場': counts, 'signals_SHA256': digest(target),
             '新損益参照': False, '現在API取得': 0, '実注文': 0}
    (prepared / '信号準備と因果照合.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'保存': str(target), '口座数': len(output), '途中切断比較数': prefix_total}, ensure_ascii=False))


if __name__ == '__main__':
    main()
