"""旧商品別二代表の全場割合と大勝ち三場除外を、保存小会計だけで独立検算する。"""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import statistics


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'
CASES = {'TOPIX': 'E01_TRADE_W60_VETO_D0_P1L8', 'NK225': 'E01_TRADE_W60_CONFIRM_D0_P1L8'}


def read(path: Path) -> tuple[dict, str]:
    """
    機能: 保存小 JSON を一回読み、同 bytes の内容と SHA256 を返す。
    引数: path(Path) は既存の公開会計又は根の再集計資料。
    返り値: tuple[dict,str] は読み取った資料と指紋。台帳・板・金融へ接続しない。
    """
    saved = path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')), hashlib.sha256(saved).hexdigest()


def amount(value: int | float) -> Decimal:
    """
    機能: 保存円額を十進数へ写し、独立合算の丸め混入を防ぐ。
    引数: value(int|float) は有限の保存会計額。
    返り値: Decimal はその文字列と同値の十進数。
    """
    result = Decimal(str(value)); assert result.is_finite()
    return result


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 実親の相殺前利益・損失を場ごとに合算し、金額加重割合を求める。
    引数: rows(list[dict]) は同商品同条件の保存セッション小会計。
    返り値: dict は円合計・金額利益割合・場数平均。無取引を勝ちへ数えない。
    """
    gain = sum((amount(r['profit']) for r in rows), Decimal(0))
    loss = sum((amount(r['loss']) for r in rows), Decimal(0))
    net = sum((amount(r['net']) for r in rows), Decimal(0))
    assert gain >= 0 and loss >= 0 and gain - loss == net
    return dict(利益=float(gain), 損失=float(loss), 収支=float(net),
        金額利益割合=float(gain / (gain + loss)) if gain + loss else None,
        場数=len(rows), 全場数分母の平均収支=float(net / len(rows)) if rows else None,
        活動場数=sum(r['campaigns'] > 0 for r in rows), 無取引場数=sum(r['campaigns'] == 0 for r in rows),
        黒字場数=sum(r['net'] > 0 for r in rows), 赤字場数=sum(r['net'] < 0 for r in rows))


def compare(actual: object, expected: object, label: str, checks: list[str]) -> None:
    """
    機能: 独立数値と根の保存値を照合し、確認対象を残す。
    引数: actual/expected(object) は比較値、label(str) は対象、checks(list[str]) は検査記録。
    返り値: None。不一致又は None の不正補完は assertion で拒否する。
    """
    if actual is None or expected is None: assert actual is expected, label
    elif isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        assert abs(amount(actual) - amount(expected)) < Decimal('0.000000000001'), (label, actual, expected)
    else: assert actual == expected, (label, actual, expected)
    checks.append(label)


def run() -> None:
    """
    機能: 二代表の全66行、前後期間、三場除外、分母と表現を独立確認する。
    引数: なし。旧公開会計と根の小集計だけを読む。
    返り値: None。証跡を所有域へ新規保存し、公開・共通知見を編集しない。
    """
    public_path = PUBLIC / 'E01取引更新と損失予算の公開会計.json'
    reference_path = ROOT / 'work/wave_v106/代表二条件の場内金額比と全期間比.json'
    public, public_sha = read(public_path); reference, reference_sha = read(reference_path)
    assert reference['全合格'] and len(public['sessions']) == 33 and set(reference['商品別']) == set(CASES)
    checks = []; result = {}; selected_snapshot = {}
    for symbol, cid in CASES.items():
        ref = reference['商品別'][symbol]; compare(ref['条件'], cid, symbol + '/条件', checks)
        by_session = {r['session']: r for r in public['cases'][cid]['rows'] if r['symbol'] == symbol}
        assert len(by_session) == 33 and set(by_session) == set(public['sessions'])
        rows = [by_session[s] for s in public['sessions']]; selected_snapshot[symbol] = rows
        individual = []
        for i, r in enumerate(rows):
            gain, loss, net = (amount(r[k]) for k in ('profit','loss','net'))
            assert gain >= 0 and loss >= 0 and gain - loss == net
            assert r['winning_campaigns'] + r['losing_campaigns'] == r['campaigns'], '今回の二代表は零親なし'
            assert (r['campaigns'] == 0) == (gain + loss == 0), '今回の二代表は活動零益なし'
            share = float(gain / (gain + loss)) if gain + loss else None
            expected = ref['場ごとの値'][i]; compare(r['session'], expected['session'], symbol + '/' + r['session'] + '/場', checks)
            for name, value in (('利益',float(gain)),('損失',float(loss)),('収支',float(net)),('金額利益割合',share)):
                compare(value, expected[name], symbol + '/' + r['session'] + '/' + name, checks)
            individual.append(dict(session=r['session'], 金額利益割合=share, 利益=float(gain), 損失=float(loss), 収支=float(net)))
        valid = [r['金額利益割合'] for r in individual if r['金額利益割合'] is not None]
        distribution = dict(全場数=len(rows), 活動場数=len(valid), 無取引場数=len(rows)-len(valid),
            場内金額比の最小=min(valid), 場内金額比の最大=max(valid), 場内金額比の中央値=float(statistics.median(valid)),
            百パーセント場数=sum(x == 1 for x in valid), 零パーセント場数=sum(x == 0 for x in valid),
            金額比八割以上の場数=sum(x >= .8 for x in valid))
        for name, value in distribution.items(): compare(value, ref[name], symbol + '/' + name, checks)
        periods = {}
        for name, subset in (('全33金額比', rows),('前16金額比',rows[:16]),('後17金額比',rows[16:])):
            periods[name] = aggregate(subset)
            for key in ('利益','損失','収支','金額利益割合'): compare(periods[name][key],ref[name][key],symbol+'/'+name+'/'+key,checks)
        # ----------------------------------------
        # 上位場は合算収支で選ぶ。同額なら公開の固定場順を維持する。場内混在利益も一緒に除く。
        positive = sorted((r for r in rows if r['net'] > 0), key=lambda r:amount(r['net']), reverse=True)
        excluded_rows = positive[:3]; assert len(excluded_rows) == 3
        excluded = {r['session'] for r in excluded_rows}; rest = [r for r in rows if r['session'] not in excluded]
        stripped = aggregate(rest)
        compare(excluded, set(ref['利益上位3場除外']['除外場']),symbol+'/除外場集合',checks)
        compare(len(rest),ref['利益上位3場除外']['残場数'],symbol+'/残場数',checks)
        for key in ('利益','損失','収支','金額利益割合'): compare(stripped[key],ref['利益上位3場除外'][key],symbol+'/三場除外/'+key,checks)
        compare(stripped['収支'],public['cases'][cid]['summary'][symbol]['top3_excluded'],symbol+'/公開上位三場除外収支',checks)
        compare(round(stripped['金額利益割合']*100,1),57.1 if symbol=='TOPIX' else 67.5,symbol+'/公表一桁比率',checks)
        compare(round(stripped['全場数分母の平均収支']),1021 if symbol=='TOPIX' else 598,symbol+'/公表残三十場平均円',checks)
        result[symbol] = dict(条件=cid, 分布=distribution, 場ごとの値=individual, 期間=periods,
            三場除外=dict(**stripped, 除外場=[r['session'] for r in rows if r['session'] in excluded],
                除外行=excluded_rows, 平均収支分母='残り30セッション。NKの無取引8場も含む。',
                活動場だけの平均収支=stripped['収支']/stripped['活動場数'] if stripped['活動場数'] else None,
                金額利益割合の分母='残る決済親の利益円合計＋損失円合計。場割合の単純平均ではない。'))
    compare(result['TOPIX']['分布']['百パーセント場数'],28,'TOPIX/100割合28場',checks)
    compare(result['TOPIX']['分布']['零パーセント場数'],4,'TOPIX/0割合4場',checks)
    compare(result['NK225']['分布']['百パーセント場数'],23,'NK225/100割合23場',checks)
    compare(result['NK225']['分布']['零パーセント場数'],2,'NK225/0割合2場',checks)
    compare(result['NK225']['分布']['無取引場数'],8,'NK225/None8場',checks)
    assert all(result[s]['分布']['場内金額比の最小'] == 0 and result[s]['分布']['場内金額比の最大'] == 1 for s in CASES)
    proof = dict(全合格=True, 独立検査件数=len(checks), 検査対象=checks, 商品別=result,
        source=[dict(path=public_path.relative_to(ROOT).as_posix(),SHA256=public_sha,
                     pointer='/cases/{条件}/rows',範囲='商品別二代表の各33行を全数独立合算'),
                dict(path=reference_path.relative_to(ROOT).as_posix(),SHA256=reference_sha,
                     pointer='/商品別',範囲='全33個別割合・分布・全期間・前後期間・除外合計と照合')],
        表現確認=dict(対象二候補='TOPIXとNKで異なる公開入口条件を商品別代表として選んだ二候補。銘柄共通の一手法ではない。',
            最小最大='両代表とも場内割合の最小0%、最大100%。分母がある活動場だけで測る。NKの無取引8場はNone。',
            勝率とは別='場内100%はその場の決済親に損失円がなかったこと。全33場の金額利益割合とは別。',
            元本利回りではない='利益÷(利益＋損失)は金額利益割合。投資元本や必要証拠金が未定義なのでROIは求めていない。',
            平均の分母='残30場の収支合計÷30。平均親利益、総利益÷黒字場数、活動場だけの平均ではない。',
            商品内比較='TOPIXミニ5枚と日経マイクロ10枚の金額を単純順位比較せず、各商品の利益対損失をそれぞれ測る。',
            証拠の限界='既知保存会計の独立再集計であり、新しい金融成果・効能・未見成功確率の証拠ではない。'),
        一読した小資料数=2, 原板読取=0, 原NPZ読取=0, 大型台帳読取=0, 金融再生=0, API=0,
        公開編集=0, 共通知見編集=0,
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    path = HERE / 'session_distribution_代表二候補の全場割合と上位三場除外の独立検算.json'
    assert not path.exists()
    saved = (json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8');path.write_bytes(saved)
    print(hashlib.sha256(saved).hexdigest(),flush=True)
    for symbol,v in result.items(): print(symbol,v['三場除外'],flush=True)


if __name__ == '__main__': run()
