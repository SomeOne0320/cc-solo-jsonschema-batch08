"""
A workload comparison for `uniqueItems` (``jsonschema._utils.uniq``).

This is not a timing benchmark. It counts the actual work performed when
checking that a container's elements are unique:

* ``equal()`` calls -- pairwise equality comparisons between two nodes,
  including recursive comparisons inside nested elements. This is what the
  old, quadratic implementation spends its time on: each element is compared
  with every element before it, so n records cost ~n**2/2 top-level
  comparisons (each of which may recurse into the records' fields).
* ``_plain_json_key()`` calls -- node visits the new implementation makes
  while hashing plain JSON data. Every node of every element is visited
  exactly once, so the total is proportional to the size of the data, plus
  one set lookup/insert per element (not counted here).

For each scenario the script also verifies that both implementations return
the same result and that neither modifies the input.

Scenarios cover a normal batch of nested records, a batch whose only
duplicate is the very last element (the worst case for pairwise checking),
and a number of different data shapes, including custom objects which
intentionally still use the old comparison rules.
"""

from collections import namedtuple
from copy import deepcopy
from decimal import Decimal
import itertools

import jsonschema._utils as _utils


def uniq_before(container):
    """
    The implementation before this change, copied verbatim.

    It tries to rely on the container being recursively sortable, and
    otherwise falls back on (slow) brute force.
    """
    try:
        sort = sorted(_utils.unbool(i) for i in container)
        sliced = itertools.islice(sort, 1, None)

        for i, j in zip(sort, sliced):
            if _utils.equal(i, j):
                return False

    except (NotImplementedError, TypeError):
        seen = []
        for e in container:
            e = _utils.unbool(e)

            for i in seen:
                if _utils.equal(i, e):
                    return False

            seen.append(e)
    return True


class Counter:
    equal_calls = 0
    key_visits = 0


_counter = Counter()
_real_equal = _utils.equal
_real_key = _utils._plain_json_key


def _counting_equal(one, two):
    _counter.equal_calls += 1
    return _real_equal(one, two)


def _counting_key(element):
    _counter.key_visits += 1
    return _real_key(element)


def measure(function, container):
    """
    Run ``function`` and count the comparisons/visits it performs.
    """
    _counter.equal_calls = 0
    _counter.key_visits = 0
    _utils.equal = _counting_equal
    _utils._plain_json_key = _counting_key
    try:
        result = function(container)
    finally:
        _utils.equal = _real_equal
        _utils._plain_json_key = _real_key
    return result, _counter.equal_calls, _counter.key_visits


def records(n):
    """
    A batch of nested records, as in the import-before-deduplication case.
    """
    return [
        {
            "id": i,
            "name": f"record-{i}",
            "active": i % 2 == 0,
            "score": i * 1.5,
            "tags": ["tag", str(i), i],
            "address": {
                "city": "somewhere", "zip": str(i), "lines": [i, None],
            },
        }
        for i in range(n)
    ]


Scenario = namedtuple("Scenario", "name container")

scenarios = [
    # The normal case: a whole batch of unique nested records.
    Scenario("normal batch, 400 records", records(400)),
    Scenario("normal batch, 800 records", records(800)),
    # The worst case for pairwise checking: the only duplicate is last.
    Scenario("duplicate at end, 400 records", records(399) + [records(1)[0]]),
    Scenario("duplicate at end, 800 records", records(799) + [records(1)[0]]),
    # Different data shapes (all unique elements).
    Scenario("flat integers, 800", list(range(800))),
    Scenario("flat strings, 800", [str(i) for i in range(800)]),
    Scenario(
        "mixed scalars, 800",
        [x for i in range(400) for x in (i, f"text-{i}")],
    ),
    Scenario("arrays of arrays, 800", [[i, i + 1] for i in range(800)]),
    Scenario(
        "nested objects, 800",
        [{"a": {"b": i, "c": "x"}, "d": [i]} for i in range(800)],
    ),
    # Custom objects: still checked with the old comparison rules.
    Scenario(
        "custom objects (Decimal), 300",
        [{"id": Decimal(i), "kind": "custom"} for i in range(300)],
    ),
]


if __name__ == "__main__":
    print(
        f"{'scenario':<34} {'unique?':>7} {'old: equal() calls':>18} "
        f"{'new: key() visits':>18} {'new: equal() calls':>18}",
    )
    for scenario in scenarios:
        snapshot = deepcopy(scenario.container)

        old_result, old_equal, _ = measure(uniq_before, scenario.container)
        assert scenario.container == snapshot, "old implementation mutated!"

        new_result, new_equal, new_visits = measure(
            _utils.uniq, scenario.container,
        )
        assert scenario.container == snapshot, "new implementation mutated!"

        assert old_result == new_result, (
            f"result mismatch on {scenario.name!r}: "
            f"old={old_result} new={new_result}"
        )

        print(
            f"{scenario.name:<34} {str(old_result):>7} {old_equal:>18,} "
            f"{new_visits:>18,} {new_equal:>18,}",
        )

    print()
    print("equal() calls  = pairwise node comparisons (old: ~n**2/2 pairs,")
    print("                 each recursing into the elements' fields)")
    print("key() visits   = nodes hashed once each (new: proportional to the")
    print("                 data size, plus one set lookup per element)")
    print("Note: for the sortable shapes (flat integers/strings, arrays of")
    print("arrays) the old implementation additionally sorts the container,")
    print("an O(n log n) cost in C-level comparisons not counted above.")
    print("The custom-object shape falls back to the old algorithm in the")
    print("new implementation, hence identical counts.")
