from __future__ import annotations

from copy import deepcopy
from unittest import TestCase
import json

from referencing.jsonschema import DRAFT202012
import referencing
import referencing.exceptions

from jsonschema import BundleError, Draft202012Validator, bundle


def registry_of(pairs):
    """Build an in-memory registry from ``(uri, schema)`` pairs."""
    return referencing.Registry().with_resources(
        (uri, DRAFT202012.create_resource(contents)) for uri, contents in pairs
    )


def bundled_registry(document):
    """A registry containing *only* the single bundled document."""
    return referencing.Registry().with_resource(
        document["$id"],
        DRAFT202012.create_resource(document),
    )


class TestBundle(TestCase):
    def main_schema(self):
        return {
            "$id": "https://example.com/schemas/main.json",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"$ref": "types.json#/$defs/name"},
                "address": {"$ref": "types.json#/$defs/address"},
            },
        }

    def types_schema(self):
        return {
            "$id": "types.json",  # a *relative* identifier, as on disk
            "$defs": {
                "name": {"type": "string", "minLength": 1},
                "address": {
                    "$id": "address.json",  # nested relative identifier
                    "type": "object",
                    "properties": {
                        "city": {"$ref": "types.json#/$defs/zip"},
                    },
                },
                "zip": {"type": "string"},
            },
        }

    def registry(self):
        return registry_of(
            [
                (
                    "https://example.com/schemas/types.json",
                    self.types_schema(),
                ),
                (
                    "https://example.com/unrelated/thing.json",
                    {
                        "$id": "https://example.com/unrelated/thing.json",
                        "type": "integer",
                    },
                ),
            ],
        )

    def test_embeds_reachable_resource_and_rewrites_relative_identifier(self):
        main = self.main_schema()
        bundled = bundle(main, self.registry())

        [name] = bundled["$defs"]
        embedded = bundled["$defs"][name]
        # the copy's relative $id is now the absolute original location ...
        self.assertEqual(
            embedded["$id"],
            "https://example.com/schemas/types.json",
        )
        # ... while reference strings are left untouched
        self.assertEqual(
            main["properties"]["name"]["$ref"],
            "types.json#/$defs/name",
        )
        self.assertEqual(
            embedded["$defs"]["address"]["properties"]["city"]["$ref"],
            "types.json#/$defs/zip",
        )

    def test_unrelated_registry_resources_are_not_embedded(self):
        bundled = bundle(self.main_schema(), self.registry())
        self.assertEqual(len(bundled["$defs"]), 1)
        self.assertNotIn(
            "https://example.com/unrelated/thing.json",
            bundled["$defs"],
        )

    def test_existing_definitions_are_preserved_and_not_overwritten(self):
        registry = registry_of(
            [
                ("https://example.com/types.json", self.types_schema()),
            ],
        )
        main = {
            "$id": "https://example.com/main.json",
            "$defs": {
                "https___example_com_types_json": {"type": "null"},
                "kept": {"const": "kept"},
            },
            "properties": {
                "name": {"$ref": "types.json#/$defs/name"},
            },
        }
        bundled = bundle(main, registry)

        self.assertEqual(
            bundled["$defs"]["https___example_com_types_json"],
            {"type": "null"},
        )
        self.assertEqual(bundled["$defs"]["kept"], {"const": "kept"})
        # the new entry got a disambiguating suffix instead
        self.assertIn("https___example_com_types_json_1", bundled["$defs"])

    def test_inputs_are_not_mutated(self):
        main = self.main_schema()
        registry = self.registry()
        main_before, registry_before = deepcopy(main), deepcopy(registry)

        bundle(main, registry)

        self.assertEqual(main, main_before)
        self.assertEqual(
            sorted(registry.crawl().keys()),
            sorted(registry_before.crawl().keys()),
        )
        # the relative identifier in the source schema is untouched
        self.assertEqual(
            self.types_schema()["$id"],
            "types.json",
        )

    def test_returned_document_does_not_share_mutable_content(self):
        main = self.main_schema()
        bundled = bundle(main, self.registry())

        bundled["properties"]["name"]["$ref"] = "mutated"
        bundled["$defs"][next(iter(bundled["$defs"]))]["$defs"].clear()

        self.assertEqual(
            main["properties"]["name"]["$ref"],
            "types.json#/$defs/name",
        )
        self.assertIn("name", self.types_schema()["$defs"])

    def test_repeated_bundling_is_stable(self):
        main, registry = self.main_schema(), self.registry()
        self.assertEqual(bundle(main, registry), bundle(main, registry))

    def test_references_inside_defaults_and_examples_are_ignored(self):
        schema = {
            "$id": "https://example.com/tricky.json",
            "properties": {
                "field": {
                    "type": "object",
                    "default": {"$ref": "not-a-dependency.json"},
                    "examples": [
                        {"$dynamicRef": "also-not-a-dependency.json"},
                    ],
                },
            },
        }
        bundled = bundle(schema, self.registry())
        self.assertNotIn("$defs", bundled)

    def test_internal_references_need_no_embedded_resources(self):
        schema = {
            "$id": "https://example.com/internal.json",
            "$dynamicAnchor": "root",
            "$defs": {"thing": {"type": "integer", "$anchor": "anchored"}},
            "properties": {
                "pointer": {"$ref": "#/$defs/thing"},
                "anchor": {"$ref": "#anchored"},
                "dynamic": {"$dynamicRef": "#root"},
            },
        }
        bundled = bundle(schema, referencing.Registry())
        self.assertEqual(set(bundled["$defs"]), {"thing"})

    def test_named_and_dynamic_anchors_in_external_resources(self):
        external = {
            "$id": "https://example.com/ext.json",
            "$defs": {
                "number": {"$anchor": "numberAnchor", "type": "integer"},
                "text": {
                    "$dynamicAnchor": "textAnchor",
                    "type": "string",
                },
            },
            "allOf": [{"$dynamicRef": "#textAnchor"}],
        }
        registry = registry_of(
            [
                ("https://example.com/ext.json", external),
            ],
        )
        main = {
            "$id": "https://example.com/main.json",
            "properties": {
                "n": {"$ref": "ext.json#numberAnchor"},
                "s": {"$ref": "ext.json#textAnchor"},
            },
        }
        bundled = bundle(main, registry)
        self.assert_validation_equivalent(
            main,
            bundled,
            registry,
            [
                {"n": 3, "s": "ok"},
                {"n": "no", "s": "ok"},
                {"n": 3, "s": 5},
                {},
            ],
        )

    def test_cross_document_dynamic_scope_is_preserved(self):
        # The canonical dynamic-scope example: the dynamicRef in the referenced
        # document must resolve to the dynamic anchor introduced by the root.
        root = {
            "$id": "https://example.com/tree.json",
            "$dynamicAnchor": "node",
            "type": "object",
            "properties": {
                "data": True,
                "children": {
                    "type": "array",
                    "items": {"$ref": "reftree.json"},
                },
            },
        }
        referenced = {
            "$id": "https://example.com/reftree.json",
            "$defs": {
                "resource": {
                    "$dynamicAnchor": "node",
                    "type": "object",
                    "properties": {"data": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            "$ref": "#/$defs/resource",
        }
        registry = registry_of(
            [
                ("https://example.com/reftree.json", referenced),
            ],
        )
        bundled = bundle(root, registry)
        self.assert_validation_equivalent(
            root,
            bundled,
            registry,
            [
                {"data": 1, "children": []},
                {"data": "ok", "children": [{"data": "x"}]},
                {"data": "ok", "children": [{"unknown": 1}]},
                {"children": [{"data": 5}]},
            ],
        )

    def test_mutually_referencing_documents_are_both_embedded(self):
        first = {
            "$id": "https://example.com/a.json",
            "type": "object",
            "properties": {"b": {"$ref": "b.json"}},
        }
        second = {
            "$id": "https://example.com/b.json",
            "type": "object",
            "properties": {"a": {"$ref": "a.json"}},
        }
        registry = registry_of(
            [
                ("https://example.com/a.json", first),
                ("https://example.com/b.json", second),
            ],
        )
        main = {"$id": "https://example.com/main.json", "$ref": "a.json"}

        bundled = bundle(main, registry)
        self.assertEqual(len(bundled["$defs"]), 2)
        self.assert_validation_equivalent(
            main,
            bundled,
            registry,
            [
                {"b": {"a": {}}},
                {"b": {"a": {"b": {}}}},
                12,
            ],
        )

    def test_boolean_schemas_can_be_referenced(self):
        registry = registry_of(
            [
                ("https://example.com/false.json", False),
                ("https://example.com/true.json", True),
            ],
        )
        main = {
            "$id": "https://example.com/main.json",
            "allOf": [
                {"$ref": "false.json"},
                {"$ref": "true.json"},
            ],
        }
        bundled = bundle(main, registry)
        self.assertIn(False, bundled["$defs"].values())
        self.assertIn(True, bundled["$defs"].values())
        # references now point at the embedded boolean copies
        rewritten = bundled["allOf"][0]["$ref"]
        self.assertTrue(rewritten.startswith("#/$defs/"))
        self.assert_validation_equivalent(
            main,
            bundled,
            registry,
            [
                1,
                "anything",
                {},
                None,
            ],
        )

    def test_multi_hop_relative_references(self):
        leaf = {"$id": "leaf.json", "type": "string", "minLength": 2}
        middle = {
            "$id": "base.json",
            "type": "object",
            "properties": {"value": {"$ref": "../b/leaf.json"}},
        }
        registry = registry_of(
            [
                ("https://example.com/schemas/a/base.json", middle),
                ("https://example.com/schemas/b/leaf.json", leaf),
            ],
        )
        main = {
            "$id": "https://example.com/schemas/a/main.json",
            "$ref": "base.json#",
        }
        bundled = bundle(main, registry)
        self.assertEqual(len(bundled["$defs"]), 2)
        self.assert_validation_equivalent(
            main,
            bundled,
            registry,
            [
                {"value": "abc"},
                {"value": "x"},
                {"value": 5},
                {},
                42,
            ],
        )

    def test_reference_to_nested_subresource_embeds_enclosing_document(self):
        nested = {
            "$id": "https://example.com/nested.json",
            "$defs": {
                "sub": {
                    "$id": "https://example.com/sub.json",
                    "type": "integer",
                },
            },
        }
        registry = registry_of(
            [
                ("https://example.com/nested.json", nested),
            ],
        )
        main = {"$id": "https://example.com/main.json", "$ref": "sub.json"}
        bundled = bundle(main, registry)
        self.assertEqual(
            list(bundled["$defs"]),
            ["https___example_com_nested_json"],
        )

    def test_nested_resource_inside_main_schema_is_not_re_embedded(self):
        main = {
            "$id": "https://example.com/main.json",
            "$defs": {
                "sub": {
                    "$id": "https://example.com/sub.json",
                    "type": "integer",
                },
            },
            "properties": {
                "direct": {"$ref": "sub.json"},
                "empty_fragment": {"$ref": "sub.json#"},
            },
        }
        bundled = bundle(main, referencing.Registry())
        # the main schema's own $defs is untouched and nothing extra is added
        self.assertEqual(list(bundled["$defs"]), ["sub"])
        self.assert_validation_equivalent(
            main,
            bundled,
            referencing.Registry(),
            [
                {"direct": 1},
                {"direct": "no"},
            ],
        )

    def test_anchor_inside_nested_resource_of_main_schema_resolves(self):
        main = {
            "$id": "https://example.com/main.json",
            "$defs": {
                "sub": {
                    "$id": "https://example.com/sub.json",
                    "$defs": {
                        "a": {"$anchor": "anch", "type": "string"},
                    },
                },
            },
            "$ref": "sub.json#anch",
        }
        bundled = bundle(main, referencing.Registry())
        self.assertEqual(list(bundled["$defs"]), ["sub"])
        self.assert_validation_equivalent(
            main,
            bundled,
            referencing.Registry(),
            [
                "a string",
                12,
            ],
        )

    def test_bundled_document_round_trips_through_json(self):
        main, registry = self.main_schema(), self.registry()
        bundled = bundle(main, registry)
        decoded = json.loads(json.dumps(bundled))
        self.assertEqual(decoded, bundled)
        self.assert_validation_equivalent(
            main,
            decoded,
            registry,
            [
                {"name": "x", "address": {"city": "123"}},
                {"name": "", "address": {}},
                {"name": 12},
            ],
        )

    def test_missing_resource_is_reported_not_retrieved(self):
        calls = []

        def retrieve(uri):
            calls.append(uri)
            raise referencing.exceptions.NoSuchResource(ref=uri)

        registry = referencing.Registry(retrieve=retrieve)
        schema = {"$id": "https://example.com/m.json", "$ref": "missing.json"}

        with self.assertRaises(BundleError):
            bundle(schema, registry)
        self.assertEqual(calls, [])

    def test_missing_anchor_is_reported(self):
        registry = registry_of(
            [
                ("https://example.com/ext.json", {"$defs": {}}),
            ],
        )
        schema = {
            "$id": "https://example.com/m.json",
            "$ref": "ext.json#no-such-anchor",
        }
        with self.assertRaises(BundleError):
            bundle(schema, registry)

    def test_missing_json_pointer_location_is_reported(self):
        registry = registry_of(
            [
                ("https://example.com/ext.json", {"$defs": {}}),
            ],
        )
        schema = {
            "$id": "https://example.com/m.json",
            "$ref": "ext.json#/nowhere/here",
        }
        with self.assertRaises(BundleError):
            bundle(schema, registry)

    def test_pointer_into_boolean_resource_is_reported(self):
        registry = registry_of(
            [
                ("https://example.com/bool.json", False),
            ],
        )
        schema = {
            "$id": "https://example.com/m.json",
            "$ref": "bool.json#/something",
        }
        with self.assertRaises(BundleError):
            bundle(schema, registry)

    def test_main_schema_requires_an_absolute_identifier(self):
        with self.assertRaises(BundleError):
            bundle({"type": "integer"}, referencing.Registry())
        with self.assertRaises(BundleError):
            bundle(
                {"$id": "relative.json", "type": "integer"},
                referencing.Registry(),
            )

    def test_boolean_main_schema_is_rejected(self):
        with self.assertRaises(BundleError):
            bundle(True, referencing.Registry())
        with self.assertRaises(BundleError):
            bundle(False, referencing.Registry())

    def assert_validation_equivalent(
        self,
        original_schema,
        bundled_schema,
        original_registry,
        instances,
    ):
        original = Draft202012Validator(
            original_schema,
            registry=original_registry,
        )
        # The bundle is registered as a single resource in an otherwise empty
        # registry, mirroring the offline import program's usage.
        bundled = Draft202012Validator(
            bundled_schema,
            registry=bundled_registry(bundled_schema),
        )
        for instance in instances:
            self.assertEqual(
                original.is_valid(instance),
                bundled.is_valid(instance),
                msg=f"divergent result for instance {instance!r}",
            )
