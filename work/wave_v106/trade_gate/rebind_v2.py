"""窓資格の局所訂正を新金融前証跡へ結び、旧人工の経済数学を再数えせず委譲する。"""

import json

import common
import runner


ARCHIVE=common.HERE/'archive/初版_窓外基準尾部の資格検査'


def main() -> None:
    """
    機能: driverの変更が証跡/計画のv2参照名だけであることを確認し、旧45結合を委譲する。
    引数: なし。
    返り値: None。新入力や金融を読まず、小source/完成metadata/旧人工だけを接続する。
    """
    old=(ARCHIVE/'runner.py').read_text(encoding='utf8');new=(common.HERE/'runner.py').read_text(encoding='utf8')
    replacements={
        '取引更新maskと単一執行及び料金の結合人工.json':'金融結合の不変委譲_v2.json',
        '取引更新方向票とscope及び接頭の人工検査.json':'窓内資格境界訂正と旧人工委譲_v2.json',
        '入力測定前の固定.json':'入力測定前の固定_v2.json',
        '試行計画.json':'試行計画_v2.json',
        '金融開始前の固定.json':'金融開始前の固定_v2.json',
        '36条件の八部品とdriverを固定。根登録待機。':'36条件v2の八部品とdriverを固定。根登録待機。',
        'cost=dict(TOPIXmini_oneway_yen':'costs=dict(TOPIXmini_oneway_yen'}
    transformed=old
    for before,after in replacements.items():transformed=transformed.replace(before,after)
    assert transformed==new,'許された参照資料名以外の金融source変更'
    oldproof=common.read(ARCHIVE/'取引更新maskと単一執行及び料金の結合人工.json')
    assert oldproof['全合格'] and sum(oldproof['検査件数'].values())==45
    old_input=common.read(ARCHIVE/'取引更新方向票とscope及び接頭の人工検査.json')
    assert old_input['全合格'] and old_input['検査数']==19
    unchanged=('common.py','catalog.py','policy.py','features.py','selection.py','interface.py','finance_artificial.py','engine/core.py','engine/accounting.py','engine/fixture_snapshot.py')
    for name in unchanged:assert (ARCHIVE/name).read_bytes()==(common.HERE/name).read_bytes(),name
    boundary=common.read(common.HERE/'窓内資格境界訂正と旧人工委譲_v2.json');assert boundary['全合格']
    result=dict(全合格=True,source_SHA256=runner.sources(),新金融再生=0,正式input再読=0,現在snapshot読取=0,API取得=0,原book読取=0,
        旧結合45の委譲=dict(path=(ARCHIVE/'取引更新maskと単一執行及び料金の結合人工.json').relative_to(common.ROOT).as_posix(),
            SHA256=common.digest(ARCHIVE/'取引更新maskと単一執行及び料金の結合人工.json'),検査数=45,再実行数=0),
        旧数式19の委譲=dict(SHA256=common.digest(ARCHIVE/'取引更新方向票とscope及び接頭の人工検査.json'),再実行数=0),
        新局所境界5=dict(SHA256=common.digest(common.HERE/'窓内資格境界訂正と旧人工委譲_v2.json'),新金融成功数ではない=True),
        driver経済数学不変=True,driver差分= replacements,不変source=list(unchanged),
        初版入力保持SHA256=common.digest(common.HERE/'全33場の取引更新代理準備.json'),
        新入力SHA256=common.digest(common.HERE/'全33場の取引更新代理準備_v2.json'))
    common.write(common.HERE/'金融結合の不変委譲_v2.json',result)
    print(json.dumps(dict(全合格=True,旧19_45再実行=0,driver経済数学不変=True),ensure_ascii=False))


if __name__=='__main__':main()
