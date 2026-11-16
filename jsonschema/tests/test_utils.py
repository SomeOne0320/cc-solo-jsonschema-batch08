from copy import deepcopy
from decimal import Decimal
from math import nan
from unittest import TestCase

from jsonschema._utils import equal, uniq


class TestEqual(TestCase):
    def test_none(self):
        self.assertTrue(equal(None, None))

    def test_nan(self):
        self.assertTrue(equal(nan, nan))


class TestDictEqual(TestCase):
    def test_equal_dictionaries(self):
        dict_1 = {"a": "b", "c": "d"}
        dict_2 = {"c": "d", "a": "b"}
        self.assertTrue(equal(dict_1, dict_2))

    def test_equal_dictionaries_with_nan(self):
        dict_1 = {"a": nan, "c": "d"}
        dict_2 = {"c": "d", "a": nan}
        self.assertTrue(equal(dict_1, dict_2))

    def test_missing_key(self):
        dict_1 = {"a": "b", "c": "d"}
        dict_2 = {"c": "d", "x": "b"}
        self.assertFalse(equal(dict_1, dict_2))

    def test_additional_key(self):
        dict_1 = {"a": "b", "c": "d"}
        dict_2 = {"c": "d", "a": "b", "x": "x"}
        self.assertFalse(equal(dict_1, dict_2))

    def test_missing_value(self):
        dict_1 = {"a": "b", "c": "d"}
        dict_2 = {"c": "d", "a": "x"}
        self.assertFalse(equal(dict_1, dict_2))

    def test_empty_dictionaries(self):
        dict_1 = {}
        dict_2 = {}
        self.assertTrue(equal(dict_1, dict_2))

    def test_one_none(self):
        dict_1 = None
        dict_2 = {"a": "b", "c": "d"}
        self.assertFalse(equal(dict_1, dict_2))

    def test_same_item(self):
        dict_1 = {"a": "b", "c": "d"}
        self.assertTrue(equal(dict_1, dict_1))

    def test_nested_equal(self):
        dict_1 = {"a": {"a": "b", "c": "d"}, "c": "d"}
        dict_2 = {"c": "d", "a": {"a": "b", "c": "d"}}
        self.assertTrue(equal(dict_1, dict_2))

    def test_nested_dict_unequal(self):
        dict_1 = {"a": {"a": "b", "c": "d"}, "c": "d"}
        dict_2 = {"c": "d", "a": {"a": "b", "c": "x"}}
        self.assertFalse(equal(dict_1, dict_2))

    def test_mixed_nested_equal(self):
        dict_1 = {"a": ["a", "b", "c", "d"], "c": "d"}
        dict_2 = {"c": "d", "a": ["a", "b", "c", "d"]}
        self.assertTrue(equal(dict_1, dict_2))

    def test_nested_list_unequal(self):
        dict_1 = {"a": ["a", "b", "c", "d"], "c": "d"}
        dict_2 = {"c": "d", "a": ["b", "c", "d", "a"]}
        self.assertFalse(equal(dict_1, dict_2))


class TestListEqual(TestCase):
    def test_equal_lists(self):
        list_1 = ["a", "b", "c"]
        list_2 = ["a", "b", "c"]
        self.assertTrue(equal(list_1, list_2))

    def test_equal_lists_with_nan(self):
        list_1 = ["a", nan, "c"]
        list_2 = ["a", nan, "c"]
        self.assertTrue(equal(list_1, list_2))

    def test_unsorted_lists(self):
        list_1 = ["a", "b", "c"]
        list_2 = ["b", "b", "a"]
        self.assertFalse(equal(list_1, list_2))

    def test_first_list_larger(self):
        list_1 = ["a", "b", "c"]
        list_2 = ["a", "b"]
        self.assertFalse(equal(list_1, list_2))

    def test_second_list_larger(self):
        list_1 = ["a", "b"]
        list_2 = ["a", "b", "c"]
        self.assertFalse(equal(list_1, list_2))

    def test_list_with_none_unequal(self):
        list_1 = ["a", "b", None]
        list_2 = ["a", "b", "c"]
        self.assertFalse(equal(list_1, list_2))

        list_1 = ["a", "b", None]
        list_2 = [None, "b", "c"]
        self.assertFalse(equal(list_1, list_2))

    def test_list_with_none_equal(self):
        list_1 = ["a", None, "c"]
        list_2 = ["a", None, "c"]
        self.assertTrue(equal(list_1, list_2))

    def test_empty_list(self):
        list_1 = []
        list_2 = []
        self.assertTrue(equal(list_1, list_2))

    def test_one_none(self):
        list_1 = None
        list_2 = []
        self.assertFalse(equal(list_1, list_2))

    def test_same_list(self):
        list_1 = ["a", "b", "c"]
        self.assertTrue(equal(list_1, list_1))

    def test_equal_nested_lists(self):
        list_1 = ["a", ["b", "c"], "d"]
        list_2 = ["a", ["b", "c"], "d"]
        self.assertTrue(equal(list_1, list_2))

    def test_unequal_nested_lists(self):
        list_1 = ["a", ["b", "c"], "d"]
        list_2 = ["a", [], "c"]
        self.assertFalse(equal(list_1, list_2))


class Thing:
    """
    A custom object which is unhashable and unsortable but comparable.
    """

    def __init__(self, id):
        self.id = id

    def __eq__(self, other):
        return isinstance(other, Thing) and self.id == other.id

    __hash__ = None


class TestUniq(TestCase):
    def test_empty(self):
        self.assertTrue(uniq([]))

    def test_all_unique(self):
        self.assertTrue(uniq([1, "1", True, None, [1], {"a": 1}]))

    def test_duplicate_scalar(self):
        self.assertFalse(uniq([1, 2, 1]))

    def test_duplicate_at_end(self):
        records = [{"id": i, "tags": [i, "x"]} for i in range(400)]
        self.assertTrue(uniq(records))
        self.assertFalse(uniq(records + [{"id": 0, "tags": [0, "x"]}]))

    def test_int_and_float_are_equal(self):
        self.assertFalse(uniq([1, 1.0]))
        self.assertFalse(uniq([{"a": 1}, {"a": 1.0}]))

    def test_bool_is_not_a_number(self):
        self.assertTrue(uniq([True, 1]))
        self.assertTrue(uniq([False, 0]))
        self.assertTrue(uniq([True, 1.0]))
        self.assertFalse(uniq([True, True]))
        self.assertTrue(uniq([True, False]))

    def test_none(self):
        self.assertFalse(uniq([None, None]))
        self.assertTrue(uniq([None, 0, False, ""]))

    def test_object_key_order_does_not_matter(self):
        self.assertFalse(uniq([{"a": 1, "b": 2}, {"b": 2, "a": 1}]))
        self.assertFalse(uniq([
            {"a": {"x": 1, "y": [2, 3]}, "b": "s"},
            {"b": "s", "a": {"y": [2, 3], "x": 1}},
        ]))

    def test_array_order_matters(self):
        self.assertTrue(uniq([[1, 2], [2, 1]]))
        self.assertTrue(uniq([{"a": [1, 2]}, {"a": [2, 1]}]))

    def test_nested_bool_is_not_a_number(self):
        self.assertTrue(uniq([{"a": [True]}, {"a": [1]}]))
        self.assertFalse(uniq([{"a": [1]}, {"a": [1.0]}]))

    def test_tuples_compare_like_lists(self):
        self.assertFalse(uniq([[1, 2], (1, 2)]))

    def test_nan(self):
        self.assertFalse(uniq([nan, nan]))
        self.assertTrue(uniq([float("nan"), float("nan")]))
        self.assertFalse(uniq([{"a": nan}, {"a": nan}]))
        self.assertFalse(uniq([2, float("nan"), 2]))

    def test_custom_objects(self):
        self.assertFalse(uniq([Thing(1), Thing(1)]))
        self.assertTrue(uniq([Thing(1), Thing(2)]))

    def test_custom_objects_mixed_with_plain_data(self):
        self.assertFalse(uniq([1, Decimal(1)]))
        self.assertFalse(uniq([Decimal("1.5"), 1.5]))
        self.assertTrue(uniq([{"a": 1}, Decimal(1)]))
        self.assertFalse(uniq([Thing(1), {"a": 1}, Thing(1)]))

    def test_input_is_not_modified(self):
        container = [
            {"b": 2, "a": 1},
            [3, 1, 2],
            {"a": 1, "b": 2},
            "x", 1, True, None,
        ]
        snapshot = deepcopy(container)
        self.assertFalse(uniq(container))
        self.assertEqual(container, snapshot)
        self.assertEqual(list(container[0]), ["b", "a"])
        self.assertEqual(list(container[2]), ["a", "b"])

    def test_sees_current_contents_after_mutation(self):
        record = {"a": [1, 2]}
        container = [record, {"a": [1, 2]}]
        self.assertFalse(uniq(container))
        record["a"].append(3)
        self.assertTrue(uniq(container))
        record["a"].pop()
        self.assertFalse(uniq(container))
