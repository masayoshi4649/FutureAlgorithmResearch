"""追加完備の欠落・重複・旧指紋差・波差を人工資料で拒否する。"""

from copy import deepcopy
from datetime import datetime
import hashlib
from pathlib import Path

import numpy as np

import completion_guard as guard


def rejected(function: object) -> bool:
    """機能: 人工の破損資料が判定前に停止することを確認する。

    引数: function(Callable)。返り値: 例外で拒否された場合True(bool)。
    """
    try:
        function()
    except (AssertionError, KeyError, ValueError, TypeError):
        return True
    return False


def main() -> None:
    """機能: 新損益を読まず、追加する3検査の正常例と反例を保存する。

    引数: なし。返り値: なし(None)。実相場結果や注文器は再生しない。
    """
    tests = []
    counts = 0

    def check(name: str, result: bool) -> None:
        """機能: 検査名と成功を保存する。

        引数: name(str)、result(bool)。返り値: なし(None)。
        """
        assert result, name
        tests.append(dict(検査=name, 一致=True))

    fixed = guard.runner.read(guard.HERE/'探索条件の固定.json')
    specs = fixed['conditions']
    sha = 'a'*64
    records = {s['id']:dict(id=s['id'], 全合格=True, 探索固定SHA256=sha, 全入力数=26, 因果入力数=4,
        旧単一窓一致入力数=26 if guard.runner.legacy_id(s) else 0,
        出力SHA256={p:'b'*64 for p in guard.paths_for(s['id'])}) for s in specs}
    for spec in specs:
        guard.record_check(spec,records[spec['id']],sha)
    check('全32の必須224パスと旧6件指定を受理', sum(len(r['出力SHA256']) for r in records.values()) == 224)
    one = next(s for s in specs if guard.runner.legacy_id(s))
    for path in guard.paths_for(one['id']):
        broken = deepcopy(records[one['id']]); broken['出力SHA256'].pop(path)
        check('必須実体欠落'+path, rejected(lambda: guard.record_check(one,broken,sha))); counts += 1
    for field, value in [('id','別ID'),('探索固定SHA256','c'*64),('全合格',False),
        ('全入力数',25),('因果入力数',3),('旧単一窓一致入力数',0)]:
        broken = deepcopy(records[one['id']]); broken[field] = value
        check('記録差:'+field,rejected(lambda:guard.record_check(one,broken,sha))); counts += 1
    broken = deepcopy(records[one['id']]); broken['出力SHA256']['work/他.json']='b'*64
    check('余分な成果参照を拒否',rejected(lambda:guard.record_check(one,broken,sha))); counts += 1
    nonlegacy = next(s for s in specs if not guard.runner.legacy_id(s))
    broken = deepcopy(records[nonlegacy['id']]); broken['旧単一窓一致入力数']=26
    check('非単一への旧同値件数付替を拒否',rejected(lambda:guard.record_check(nonlegacy,broken,sha))); counts += 1

    episodes = guard.runner.read(guard.HERE.parent/'wave_v38/探索条件の固定.json')['指定波']
    waves = [dict(method=one['id'], wave=e['id'],session=e['session'],symbol=s,
        波方向=e['side'],開始=e['start'],終了=e['end'],波名=e['name'],
        区間分=(datetime.fromisoformat(e['end'])-datetime.fromisoformat(e['start'])).total_seconds()/60,
        正方向ネット保有分=20.,正方向ネット20分目安達成=True) for e in episodes for s in guard.runner.old.SYMBOLS]
    guard.wave_check(one['id'],waves,episodes)
    check('固定8波を受理',len(waves)==8)
    broken = deepcopy(waves); broken[0]=deepcopy(broken[1])
    check('8行でも同波重複を拒否',rejected(lambda:guard.wave_check(one['id'],broken,episodes))); counts += 1
    for field,value in [('method','別手法'),('波方向',-1),('開始','2000-01-01T00:00:00+09:00'),
        ('終了','2000-01-01T00:01:00+09:00'),('波名','別名'),('区間分',0),
        ('正方向ネット保有分',float('nan')),('正方向ネット20分目安達成',False)]:
        broken=deepcopy(waves);broken[0][field]=value
        check('波属性差:'+field,rejected(lambda:guard.wave_check(one['id'],broken,episodes))); counts += 1

    expected={(n,s) for n in fixed['全セッション'] for s in guard.runner.old.SYMBOLS}
    value=np.asarray([],dtype=np.float64)
    fp=dict(shape=[0],dtype=value.dtype.str,SHA256=hashlib.sha256(value.tobytes()).hexdigest())
    books=[dict(session=n,symbol=s,result_fingerprints={f:dict(fp) for f in guard.runner.FIELDS},
        shadow_fingerprints={f:dict(fp) for f in guard.runner.reference.EXPECTED_SHADOW_FIELDS},
        **{f:[] for f in guard.runner.STORED}) for n,s in sorted(expected)]
    check('旧26口座の全指紋同値を受理',guard.legacy_check(books,deepcopy(books),expected)==26)
    broken=deepcopy(books);broken[0]=deepcopy(broken[1])
    check('台帳26行でも場重複を拒否',rejected(lambda:guard.legacy_check(broken,books,expected))); counts += 1
    broken=deepcopy(books);broken[0]['result_fingerprints']['curve']['SHA256']='f'*64
    check('保存されない曲線指紋差も拒否',rejected(lambda:guard.legacy_check(broken,books,expected))); counts += 1
    broken=deepcopy(books);broken[0]['shadow_fingerprints']['plans']['SHA256']='f'*64
    check('影公開計画指紋差も拒否',rejected(lambda:guard.legacy_check(broken,books,expected))); counts += 1
    broken=deepcopy(books);broken[0]['trades']=[1.]
    check('実台帳配列の内容差を拒否',rejected(lambda:guard.legacy_check(broken,books,expected))); counts += 1
    payload=dict(全合格=True,検査数=len(tests),破損拒否数=counts,検査=tests,
        新損益読取=False,売買再生=False,現在API取得数=0,
        実装SHA256=guard.runner.digest(guard.HERE/'completion_guard.py'),
        検査実装SHA256=guard.runner.digest(Path(__file__)))
    guard.runner.save(guard.HERE/'completion_guard_test.json',payload)
    print(f'人工{len(tests)}検査・破損{counts}拒否が全合格。新損益未読。',flush=True)


if __name__=='__main__':main()
