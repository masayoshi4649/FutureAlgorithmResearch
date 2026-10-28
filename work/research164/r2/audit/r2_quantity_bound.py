"""第二巡の延期数量上限を事前定義の算術だけで確認する。"""
from fractions import Fraction
import json
from pathlib import Path
import random


def quantity(initial_want: int, current_want: int, initial_source: int, peak: int, remaining: int) -> tuple[int, Fraction]:
    """希望量の膨張を止め、元係数以下の延期解除量を算出する。

    引数: initial_want/current_want/initial_source/peak/remaining(int)。返り値: tuple[int,Fraction]。
    """
    assert initial_source > 0 and peak >= initial_source and 0 <= remaining <= peak
    result = min(initial_want, current_want) * remaining // peak
    factor = min(Fraction(result, remaining), Fraction(initial_want, initial_source)) if remaining else Fraction(0)
    return result, factor


def main() -> None:
    """既知例と固定乱数の組合せで上限関係を確認する。

    引数: なし。返り値: None。市場データも売買結果も読まない。
    """
    samples = [(25, 88, 50, 50, 50), (25, 88, 50, 100, 100), (25, 88, 50, 100, 20), (25, 10, 50, 100, 20), (0, 88, 50, 50, 50), (25, 88, 50, 100, 0)]
    expected = [25, 25, 5, 2, 0, 0]
    for args, want in zip(samples, expected):
        assert quantity(*args)[0] == want
    rng = random.Random(16413)
    trials = []
    for _ in range(20000):
        q0, current, source = rng.randrange(101), rng.randrange(101), rng.randrange(1, 101)
        peak = rng.randrange(source, 201)
        remaining = rng.randrange(peak + 1)
        accepted, factor = quantity(q0, current, source, peak, remaining)
        assert 0 <= accepted <= q0 and accepted <= current
        assert Fraction(accepted) <= Fraction(q0, source) * remaining
        assert factor <= Fraction(q0, source)
        if current < 100:
            assert quantity(q0, current + 1, source, peak, remaining)[0] >= accepted
        trials.append(accepted)
    result = dict(passed=True, artificial_only=True, financial_replays=0, cases=20006,
        examples=[dict(initial_want=a[0], current_want=a[1], initial_source=a[2], peak=a[3], remaining=a[4], accepted=b) for a,b in zip(samples,expected)],
        limit="数学上の上限確認。第二巡Go実装の人工試験とは別で、実装同値や金融成績を保証しない。")
    Path(__file__).with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, cases=20006, financial_replays=0)))


if __name__ == '__main__':
    main()
