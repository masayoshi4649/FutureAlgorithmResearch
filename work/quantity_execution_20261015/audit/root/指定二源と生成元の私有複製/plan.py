"""価格先着の偏りを実注文と費用へ接続する十二対照の事前固定を管理する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00115_板の短期方向性を実約定と損益へ接続'
REFERENCE = ROOT / 'work/quantity_response_corrected_20261015'
JST = timezone(timedelta(hours=9))
SOURCE_NAMES = ('catalog.py', 'engine.py', 'artificial.py', 'input_contract.py',
                'plan.py', 'finance.py', 'artificial_root.py',
                'metrics/metrics.py', 'metrics/artificial_metrics.py')

# ----------------------------------------


def read(path: Path) -> dict:
    """
    機能: 事前固定・小目録・証跡JSONを読む。
    引数: path(Path) は位置。
    返り値: dict は内容。原NPZ・実金融台帳を隠れて読まない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 小さいsource・目録・研究出力のSHA256を求める。
    引数: path(Path) は位置。
    返り値: str は指紋。原NPZの二重読みには使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    """
    機能: 所有域へ非有限値を禁止したJSONを新規保存する。
    引数: path(Path)、value(dict) は位置と内容。
    返り値: None。旧成功・False・入力を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def sources() -> dict:
    """
    機能: 金額へ影響する実装と対応する人工を固定する。
    引数: なし。
    返り値: dict[str,str] はルート相対pathとSHA256。
    """
    return {(HERE / name).relative_to(ROOT).as_posix(): digest(HERE / name) for name in SOURCE_NAMES}


def time_policy(session: str, start: float, end: float) -> dict:
    """
    機能: 日本の開始静観とNY通常寄付前後の静観窓を結果前に決める。
    引数: session(str)、start/end(float) は場IDと旧入力の観測窓。
    返り値: dict はepochによる新規・全返済予約・静観窓。受信時計の証明ではない。
    """
    date, kind = session.rsplit('_', 1)
    day = datetime.fromisoformat(date)
    ny = day.replace(hour=9, minute=30, tzinfo=ZoneInfo('America/New_York')).timestamp()
    quiet = [[ny - 900, ny + 900]] if start < ny < end else []
    return dict(entry_start_s=start + (1800 if kind == 'Day' else 300),
                entry_end_s=end - 600, force_start_s=end - 300, quiet_windows=quiet,
                calendar_reference='https://www.nyse.com/trade/hours-calendars',
                note='現33場にNYSE休場日はない。通常09:30東部時刻をDST変換。延長データの休場日は別確認。')

# ----------------------------------------


def prepare() -> None:
    """
    機能: 完了した114の入力目録と公開featureの保存位置だけを金融前に固定する。
    引数: なし。
    返り値: None。元NPZ・公開eventNPZ・新金融・APIは0。
    """
    assert not (HERE / '入力と保存公開の固定.json').exists()
    write(HERE / '二つの小資料の一読目的.json', dict(
        目的='同じ原44列と、結果ラベルを渡さない保存公開featureの系譜を固定する。',
        旧入力小固定=1, 旧測定JSON=1, 原NPZ=0, 出力NPZ=0, 新金融=0, API=0))
    fixed_path = REFERENCE / '入力と観測の小固定.json'
    fixed = read(fixed_path)
    raw = (REFERENCE / 'measurement/数量応答の結果.json').read_bytes()
    expected = 'aad49e1186468c8bf069a902126c2f70d6f74a311bfe8ae03ef0978d99325d05'
    assert hashlib.sha256(raw).hexdigest() == expected
    saved = json.loads(raw.decode('utf-8'))
    assert fixed['全合格'] and saved['全合格'] and saved['金融'] is False
    assert len(fixed['inputs']) == len(saved['rows']) == 66
    account = {(row['session'], row['symbol']): row for row in saved['rows']}
    inputs = []
    for item in fixed['inputs']:
        row = account[(item['session'], item['symbol'])]
        event = row['events']
        for info in (item, event):
            path = ROOT / info['path']
            stat = path.stat()
            assert stat.st_size == info['bytes']
            if 'mtime_ns' in info:
                assert stat.st_mtime_ns == info['mtime_ns']
        inputs.append(dict(raw=item, events=event, fields=row['fields'], raw_rows=row['raw_rows'],
                           time_policy=time_policy(item['session'], *item['bounds'])))
    assert {(item['raw']['session'], item['raw']['symbol']) for item in inputs} == {
        (session, symbol) for session in fixed['sessions'] for symbol in ('TOPIX', 'NK225')}
    write(HERE / '入力と保存公開の固定.json', dict(
        全合格=True, sessions=fixed['sessions'], inputs=inputs, schema=fixed['schema'],
        観測T=fixed['観測T'], 旧目録SHA256=digest(fixed_path), 旧測定SHA256=expected,
        観測内容='同じ公表活動と数量feature。先着結果・未来極値はfinance/engineへ渡さない。',
        NYSE通常時間の参照=dict(URL='https://www.nyse.com/trade/hours-calendars', 確認日='2026-10-15',
            内容='通常寄付09:30東部。2026休場表で9/21～10/13の対象日に休場なし。'),
        追加二場='対象外・本文未読', 読取予定=dict(原NPZ=66, 保存eventNPZ=66, 新金融口座=792, 原板=0, API=0)))
    print(json.dumps(dict(全合格=True, 口座数=len(inputs), 原NPZ=0, 新金融=0), ensure_ascii=False))


def freeze() -> None:
    """
    機能: 十二経済条件と実source・料金・時間・入力を登録前に固定する。
    引数: なし。
    返り値: None。正式登録・金融を自動開始しない。
    """
    import catalog
    fixed = read(HERE / '入力と保存公開の固定.json')
    audit = read(HERE / '金融初読前の人工と独立監査.json')
    assert audit['全合格'] and audit['新金融'] == 0 and audit['source_SHA256'] == sources()
    for item in audit['evidence']:
        assert digest(ROOT / item['path']) == item['SHA256']
    proposal = dict(id=catalog.TRIAL_ID, name='板の一呼値方向を実約定と費用へ接続する十二対照',
        purpose='新仮説', question='約80%の一呼値先着を、次raw市場約定と各注文料を負担し2T以上の利確や追尾で収益へ変えられるか。',
        change='保存114の三入口×四実出口。全量market・半分利確、場純損益停止、寄付静観を同条件で運転。',
        repeat_reason='114は価格先着だけで金額未測。113の0/1T FAKは最初の順行を失効させたので、約定選択を市場約定で別検証する。',
        compares_to=[], evidence=[], spec=dict(
            entry=dict(conditions=catalog.configs(), 保存公開='114の各episode初回。結果ラベル不使用。',
                       入口='A初回活動、B初期反対数量を割らずQ0活動へ到達、CはBに当時同方向側数量>=反対数量'),
            management=dict(場損失率=.00125, 場利益率=.00375, 基準='最初の価格known mid×cap×倍率を一回固定',
                            判断='realized+全建玉の返済側quote清算−個別返済料', holding_time='固定なし',
                            価格未知='補完なし。新判断停止・既返済予約は次執行正常行へ。初回不正新規は取消'),
            exit=dict(E1='actualentry基準grossTP2T/SL2T', E2='TP4T/SL2T',
                      E3='SL2T、gross3T後peak−1T/floor2T', E4='SL2T、gross2Tで半分、残peak−1T/floor1T',
                      約定='判断後の次執行正常原row。既half予約を遡及取消しない。未予約残だけ場返済を追加',
                      強制='各場end−300で返済予約。未flatを過去quoteで清算しない'),
            allocation=dict(cap=dict(catalog.CAP), 初回=dict(catalog.CAP), 増玉=False, 同時親=1,
                            費用と枚数='勝負枚数は返済脚net、主金額は全完結親net'),
            costs=dict(fee_ratio=dict(catalog.FEE_RATIO), floor='各実注文ごと1円未満切捨。新規/返済双方',
                       spread='実ask買い/bid売りを負担。中値では約定しない。5秒stressは別'),
            execution=dict(新規='公開直後raw seq+1の一回。価格上限なしmarket。不正なら取消・後へ繰越なし',
                           spread='公開時だけ2T未満必要。到来拡幅を後から取消しない',
                           返済='判定後の最初執行正常row、個別注文/UID/費用',
                           時刻='自身原seqとCurrentPriceTime模型。真受信/ミニ板/queue/実遅延は未証明'),
            data=dict(sessions=fixed['sessions'], inputs=fixed['inputs'],
                      input_manifests=[dict(path=(HERE / '入力と保存公開の固定.json').relative_to(ROOT).as_posix(),
                                            sha256=digest(HERE / '入力と保存公開の固定.json'))],
                      追加二場='未読保持', 時間方針='各inputに固定。Day09:15/Night17:05以降、NYSE09:30±15分静観、end−600新規停止'),
            implementation=sources()),
        表示主候補='QEXEC_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1',
        目標=dict(TOPIX全場平均net=100000, NK円額床='未指定', 金額利益割合=.65,
                  赤字場割合=.2, 最大赤字='平均黒字場net以下', 上位三黒字除外='別途同指標を確認'))
    assert len(catalog.configs()) == 12
    write(HERE / '試行計画.json', proposal)
    write(HERE / '金融前の正式固定.json', dict(全合格=True, source_SHA256=sources(),
          source_configs=catalog.configs(), input_SHA256=digest(HERE / '入力と保存公開の固定.json'),
          proposal_SHA256=digest(HERE / '試行計画.json'), audit_SHA256=digest(HERE / '金融初読前の人工と独立監査.json'),
          実行予定=dict(原NPZ=66, 保存eventNPZ=66, 新金融口座=792, 原板=0, API=0), 自動再実行=False))
    print(json.dumps(dict(全合格=True, 条件数=12, 新金融=0), ensure_ascii=False))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'freeze'))
    args = parser.parse_args()
    prepare() if args.command == 'prepare' else freeze()
