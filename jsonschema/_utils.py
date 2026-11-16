from collections.abc import Mapping, MutableMapping, Sequence
from urllib.parse import urlsplit
import itertools
import re


class URIDict(MutableMapping):
    """
    Dictionary which uses normalized URIs as keys.
    """

    def normalize(self, uri):
        return urlsplit(uri).geturl()

    def __init__(self, *args, **kwargs):
        self.store = dict()
        self.store.update(*args, **kwargs)

    def __getitem__(self, uri):
        return self.store[self.normalize(uri)]

    def __setitem__(self, uri, value):
        self.store[self.normalize(uri)] = value

    def __delitem__(self, uri):
        del self.store[self.normalize(uri)]

    def __iter__(self):
        return iter(self.store)

    def __len__(self):  # pragma: no cover -- untested, but to be removed
        return len(self.store)

    def __repr__(self):  # pragma: no cover -- untested, but to be removed
        return repr(self.store)


class Unset:
    """
    An as-of-yet unset attribute or unprovided default parameter.
    """

    def __repr__(self):  # pragma: no cover
        return "<unset>"


def format_as_index(container, indices):
    """
    Construct a single string containing indexing operations for the indices.

    For example for a container ``bar``, [1, 2, "foo"] -> bar[1][2]["foo"]

    Arguments:

        container (str):

            A word to use for the thing being indexed

        indices (sequence):

            The indices to format.

    """
    if not indices:
        return container
    return f"{container}[{']['.join(repr(index) for index in indices)}]"


def find_additional_properties(instance, schema):
    """
    Return the set of additional properties for the given ``instance``.

    Weeds out properties that should have been validated by ``properties`` and
    / or ``patternProperties``.

    Assumes ``instance`` is dict-like already.
    """
    properties = schema.get("properties", {})
    patterns = "|".join(schema.get("patternProperties", {}))
    for property in instance:
        if property not in properties:
            if patterns and re.search(patterns, property):
                continue
            yield property


def extras_msg(extras):
    """
    Create an error message for extra items or properties.
    """
    verb = "was" if len(extras) == 1 else "were"
    return ", ".join(repr(extra) for extra in extras), verb


def ensure_list(thing):
    """
    Wrap ``thing`` in a list if it's a single str.

    Otherwise, return it unchanged.
    """
    if isinstance(thing, str):
        return [thing]
    return thing


def _mapping_equal(one, two):
    """
    Check if two mappings are equal using the semantics of `equal`.
    """
    if len(one) != len(two):
        return False
    return all(
        key in two and equal(value, two[key])
        for key, value in one.items()
    )


def _sequence_equal(one, two):
    """
    Check if two sequences are equal using the semantics of `equal`.
    """
    if len(one) != len(two):
        return False
    return all(equal(i, j) for i, j in zip(one, two))


def equal(one, two):
    """
    Check if two things are equal evading some Python type hierarchy semantics.

    Specifically in JSON Schema, evade `bool` inheriting from `int`,
    recursing into sequences to do the same.
    """
    if one is two:
        return True
    if isinstance(one, str) or isinstance(two, str):
        return one == two
    if isinstance(one, Sequence) and isinstance(two, Sequence):
        return _sequence_equal(one, two)
    if isinstance(one, Mapping) and isinstance(two, Mapping):
        return _mapping_equal(one, two)
    return unbool(one) == unbool(two)


def unbool(element, true=object(), false=object()):
    """
    A hack to make True and 1 and False and 0 unique for ``uniq``.
    """
    if element is True:
        return true
    elif element is False:
        return false
    return element


class _NotPlainJSON(Exception):
    """
    Signal (internally) that an element isn't made of plain JSON data.
    """


#: Hash keys standing in for null and the booleans when deduplicating plain
#: JSON data. They keep null and the booleans distinct from each other and
#: from any number, unlike Python's ``True == 1`` and ``False == 0``.
_NULL_KEY = object()
_TRUE_KEY = object()
_FALSE_KEY = object()


def _plain_json_key(element):
    """
    Return a hashable key for an element of plain JSON data, for `uniq`.

    Two elements of plain JSON data are `equal` exactly when their keys are
    equal (and therefore hash equal): object keys are unordered, array order
    is preserved, null and booleans stay distinct from numbers, and ``1``
    and ``1.0`` share a key. Deduplicating the keys with a set then takes
    work proportional to the total size of the data, instead of comparing
    every element with every earlier element. Keys are computed from the
    current contents of the elements on every call, so nothing is cached
    and later mutations of the elements are seen.

    Raises `_NotPlainJSON` for anything that is not plain JSON data (exact
    dicts, lists, tuples, strings, numbers, booleans and null), so `uniq`
    can fall back to generic comparison for custom objects.
    """
    if element is None:
        return _NULL_KEY
    if element is True:
        return _TRUE_KEY
    if element is False:
        return _FALSE_KEY
    type_of = type(element)
    if type_of is str:
        return element
    if type_of is int or type_of is float:
        return element
    if type_of is list or type_of is tuple:
        return tuple(_plain_json_key(item) for item in element)
    if type_of is dict:
        items = []
        for key, value in element.items():
            if type(key) is not str:
                raise _NotPlainJSON
            items.append((key, _plain_json_key(value)))
        return frozenset(items)
    raise _NotPlainJSON


def uniq(container):
    """
    Check if all of a container's elements are unique.

    Plain JSON data is deduplicated by hashing, in a single pass whose work
    is proportional to the total size of the data. Anything else falls back
    to relying on the container being recursively sortable, or otherwise on
    (slow) brute force.
    """
    try:
        seen = set()
        for element in container:
            key = _plain_json_key(element)
            if key in seen:
                return False
            seen.add(key)
        return True
    except (_NotPlainJSON, RecursionError):
        pass  # Fall through to the generic implementation.

    try:
        sort = sorted(unbool(i) for i in container)
        sliced = itertools.islice(sort, 1, None)

        for i, j in zip(sort, sliced):
            if equal(i, j):
                return False

    except (NotImplementedError, TypeError):
        seen = []
        for e in container:
            e = unbool(e)

            for i in seen:
                if equal(i, e):
                    return False

            seen.append(e)
    return True


def find_evaluated_item_indexes_by_schema(validator, instance, schema):
    """
    Get all indexes of items that get evaluated under the current schema.

    Covers all keywords related to unevaluatedItems: items, prefixItems, if,
    then, else, contains, unevaluatedItems, allOf, oneOf, anyOf
    """
    if validator.is_type(schema, "boolean"):
        return []
    evaluated_indexes = []

    if "items" in schema:
        return list(range(len(instance)))

    ref = schema.get("$ref")
    if ref is not None:
        resolved = validator._resolver.lookup(ref)
        evaluated_indexes.extend(
            find_evaluated_item_indexes_by_schema(
                validator.evolve(
                    schema=resolved.contents,
                    _resolver=resolved.resolver,
                ),
                instance,
                resolved.contents,
            ),
        )

    dynamicRef = schema.get("$dynamicRef")
    if dynamicRef is not None:
        resolved = validator._resolver.lookup(dynamicRef)
        evaluated_indexes.extend(
            find_evaluated_item_indexes_by_schema(
                validator.evolve(
                    schema=resolved.contents,
                    _resolver=resolved.resolver,
                ),
                instance,
                resolved.contents,
            ),
        )

    if "prefixItems" in schema:
        evaluated_indexes += list(range(len(schema["prefixItems"])))

    if "if" in schema:
        if validator.evolve(schema=schema["if"]).is_valid(instance):
            evaluated_indexes += find_evaluated_item_indexes_by_schema(
                validator, instance, schema["if"],
            )
            if "then" in schema:
                evaluated_indexes += find_evaluated_item_indexes_by_schema(
                    validator, instance, schema["then"],
                )
        elif "else" in schema:
            evaluated_indexes += find_evaluated_item_indexes_by_schema(
                validator, instance, schema["else"],
            )

    for keyword in ["contains", "unevaluatedItems"]:
        if keyword in schema:
            for k, v in enumerate(instance):
                if validator.evolve(schema=schema[keyword]).is_valid(v):
                    evaluated_indexes.append(k)

    for keyword in ["allOf", "oneOf", "anyOf"]:
        if keyword in schema:
            for subschema in schema[keyword]:
                errs = next(validator.descend(instance, subschema), None)
                if errs is None:
                    evaluated_indexes += find_evaluated_item_indexes_by_schema(
                        validator, instance, subschema,
                    )

    return evaluated_indexes


def find_evaluated_property_keys_by_schema(validator, instance, schema):
    """
    Get all keys of items that get evaluated under the current schema.

    Covers all keywords related to unevaluatedProperties: properties,
    additionalProperties, unevaluatedProperties, patternProperties,
    dependentSchemas, allOf, oneOf, anyOf, if, then, else
    """
    if validator.is_type(schema, "boolean"):
        return []
    evaluated_keys = []

    ref = schema.get("$ref")
    if ref is not None:
        resolved = validator._resolver.lookup(ref)
        evaluated_keys.extend(
            find_evaluated_property_keys_by_schema(
                validator.evolve(
                    schema=resolved.contents,
                    _resolver=resolved.resolver,
                ),
                instance,
                resolved.contents,
            ),
        )

    dynamicRef = schema.get("$dynamicRef")
    if dynamicRef is not None:
        resolved = validator._resolver.lookup(dynamicRef)
        evaluated_keys.extend(
            find_evaluated_property_keys_by_schema(
                validator.evolve(
                    schema=resolved.contents,
                    _resolver=resolved.resolver,
                ),
                instance,
                resolved.contents,
            ),
        )

    properties = schema.get("properties")
    if validator.is_type(properties, "object"):
        evaluated_keys += properties.keys() & instance.keys()

    for keyword in ["additionalProperties", "unevaluatedProperties"]:
        if (subschema := schema.get(keyword)) is None:
            continue
        evaluated_keys += (
            key
            for key, value in instance.items()
            if is_valid(validator.descend(value, subschema))
        )

    if "patternProperties" in schema:
        for property in instance:
            for pattern in schema["patternProperties"]:
                if re.search(pattern, property):
                    evaluated_keys.append(property)

    if "dependentSchemas" in schema:
        for property, subschema in schema["dependentSchemas"].items():
            if property not in instance:
                continue
            evaluated_keys += find_evaluated_property_keys_by_schema(
                validator, instance, subschema,
            )

    for keyword in ["allOf", "oneOf", "anyOf"]:
        for subschema in schema.get(keyword, []):
            if not is_valid(validator.descend(instance, subschema)):
                continue
            evaluated_keys += find_evaluated_property_keys_by_schema(
                validator, instance, subschema,
            )

    if "if" in schema:
        if validator.evolve(schema=schema["if"]).is_valid(instance):
            evaluated_keys += find_evaluated_property_keys_by_schema(
                validator, instance, schema["if"],
            )
            if "then" in schema:
                evaluated_keys += find_evaluated_property_keys_by_schema(
                    validator, instance, schema["then"],
                )
        elif "else" in schema:
            evaluated_keys += find_evaluated_property_keys_by_schema(
                validator, instance, schema["else"],
            )

    return evaluated_keys


def is_valid(errs_it):
    """Whether there are no errors in the given iterator."""
    return next(errs_it, None) is None
