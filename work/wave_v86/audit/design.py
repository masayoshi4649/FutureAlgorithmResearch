"""実返済後の再参加と従来の仮想取引時計を、旧資料だけから区別する。"""

from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))


def read(path):
    """
    機能: 保存済みの圧縮又は通常JSONを読取専用で読む。
    引数: path (Path)。
    返り値: dict又はlistの保存内容。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def clock(stamp):
    """
    機能: 保存価格時計の秒数を日本時間の説明表示にする。
    引数: stamp (float)。
    返り値: strのISO形式。実受信時刻を意味しない。
    """
    return datetime.fromtimestamp(float(stamp), JST).isoformat()


def historical():
    """
    機能: 旧28場の通常時計と旧resetの保存会計を抽出する。
    引数: なし。
    返り値: dictの4条件と差分。新規戦略再生は行わない。
    """
    models = {}
    fields = ('gross', 'fees', 'net', 'campaigns', 'campaign_profit', 'campaign_loss',
              'positive_sessions', 'negative_sessions')
    for ident in ('E01', 'R01', 'R10', 'R11'):
        old = read(ROOT / 'work/wave_v67/observed' / (ident + '.json.gz'))
        models[ident] = {symbol: {k: old['periods']['全28'][symbol][k] for k in fields}
                        for symbol in ('TOPIX', 'NK225')}
    differences = {}
    for before, after in (('E01', 'R10'), ('R01', 'R11')):
        differences[before + '→' + after] = {
            symbol: {k: models[after][symbol][k] - models[before][symbol][k] for k in fields}
            for symbol in ('TOPIX', 'NK225')}
    return dict(期間='旧28場。現行30場との混合比較をしない。', 約定='観測CurrentPriceで経路再計算、実手数料込み。',
                条件=models, 差分=differences,
                解釈='旧resetは取引数と利益も増やしたが、損失の増加が利益増加を上回った。料金増加だけでは説明できない。',
                制約='旧resetは実玉ゼロ基準ではない。通常影を出口影へ置換して半減根拠の参照も変わるため、今回のA時計の結果とは同一視しない。')


def old_wait_examples():
    """
    機能: 米国開始前の実返済後に、元時計で次に準備した時刻を旧台帳から抽出する。
    引数: なし。
    返り値: list[dict]。空白の全てを影の待ちに帰属させるものではない。
    """
    path = ROOT / 'work/wave_v85/observed/ledgers/E01_G_U.pkl'
    ledgers = pickle.loads(path.read_bytes())
    values = []
    for (session, symbol), ledger in ledgers.items():
        for cycle in ledger['cycles']:
            if int(cycle[-1]) != 71:
                continue
            legs = [v for v in ledger['net_trades'] if v['組'] == int(cycle[0])]
            closed = max(v['返済時刻'] for v in legs)
            following = [p for p in ledger['prepare_events'] if p[1] > cycle[2]]
            if not following:
                continue
            # ----------------------------------------
            # 元の準備期限は準備時計+300秒で固定。更新注文元行から推定しない。
            prep = following[0]
            prepared = float(prep[5] - 300.)
            window = next(w for w in ledger['time_windows'] if w['start'] <= closed)
            values.append(dict(セッション=session, 銘柄=symbol, 組=int(cycle[0]),
                実全返済=clock(closed), 予定静観終了=clock(window['end']),
                次の元影準備=clock(prepared), 実返済から次準備の秒数=prepared - closed,
                予定静観終了から次準備の秒数=prepared - window['end'],
                準備行=int(prep[1]), 注記='窓内の旧影準備も含む。実発注許可ではなく元影の準備記録。長い空白には方向条件不成立も含み得る。'))
    return values


def main():
    """
    機能: 実装根拠・旧成績・新設計で必要な因果検査を日本語JSONへ保存する。
    引数: なし。
    返り値: None。旧資料は一切変更しない。
    """
    sources = [ROOT / p for p in ('work/wave_v67/replay.py', 'work/wave_v67/engine_shadow.py',
        'work/wave_v85/strategy.py', 'work/wave_v85/engine.py', 'work/wave_v86/catalog.py',
        'work/wave_v85/observed/ledgers/E01_G_U.pkl')]
    sources += [ROOT / 'work/wave_v67/observed' / (i + '.json.gz') for i in ('E01', 'R01', 'R10', 'R11')]
    value = dict(
        結論=[
            '原版は実玉が全部なくなっても通常影が終了するまで新準備できず、その後の5分休止もある。実返済からの再参加とは別の時計である。',
            '旧R10/R11のresetは出口影の終了から5分を数える。実玉が先にゼロとなる予算返済などへ必ず追随する仕組みではない。',
            'v85のUは実玉を返済して古い新規を拒否するが、通常影を温存する。静観終了と再参加可能化が一致しない。',
            '今回A時計は実返済を次の観測で通常影・出口影へ返す因果的な状態遷移が必要。全場の影計画を先に作り、将来の実返済行を過去へ代入してはならない。',
            '高頻度化の論理は利益を取り逃した後の再機会を増やすことであり、同じ弱い根拠への反復参入も増える。料金と親組損失を同時に検証する。'],
        新実装の監査項目=[
            '新規注文のsource行はfill行より前。A0でも全返済行には準備せず、次観測で準備し、その後の観測から約定可能。',
            '0/60/300秒は実全返済時刻から測る。指定線約定でも時間は当該観測時刻。片脚返済・半減では時計を初期化しない。',
            '古い準備・出口・半減予約・部分返済枠・組MFEを破棄し、全場EMA/ATR/B00の公開履歴は保持する。',
            '通常影と出口影を並行し、原半減のMFE基準を通常影のままに保つ。A時計は両影を同時に切る。',
            '時間静観中に準備せず、静観前の待機は終了後に約定させない。窓後の新準備にも実返済後休止を適用する。',
            'T4は保有開始後の新しい自己B00逆行、最大順行1ATR以上でのみ発動。幅を元へ戻さず、新しい線は次観測から有効。',
            '実返済がない間は親組・R・料金・部分返済枠を連続保持し、再参加で旧利益を新利益として重複計上しない。',
            '原板同時計重複に対して原本行順を保持する。次行は実時間1秒経過を保証せず、欠測を仮想の約定で埋めない。',
            '台帳・準備配列の上限を超えたら明示停止し、切捨てない。元のentry_preparations上限2000も点検する。',
            '代表4口座で未来切断し、通常影・出口影・実玉・全イベント・行前計画・行後計画を過去部分で全列一致させる。'],
        旧resetの保存成績=historical(), 旧U返済後の次準備例=old_wait_examples(),
        数値解釈の制約='ここに示す準備までの空白は機会損失や取れる利益の証拠ではない。条件の再成立を含むため、新A時計との同条件再生で初めて効果を比較する。',
        API取得=0, 新戦略損益再生=0,
        参照SHA256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / '再参加時計と因果設計の独立確認.json').write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('旧資料だけによる再参加時計の確認を保存しました。', flush=True)


if __name__ == '__main__':
    main()
