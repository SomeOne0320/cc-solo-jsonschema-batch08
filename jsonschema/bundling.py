"""
Offline bundling of a JSON Schema together with the resources it references.

The :func:`bundle` function produces a single, self-contained Draft 2020-12
schema document. Starting from a *main* schema which carries an absolute
:kw:`$id`, it follows every reference reachable from the main schema (and from
the resources those references lead to), and embeds copies of the referenced
*external* resources inside the resulting document's :kw:`$defs` keyword.

Only resources already present in the in-memory `referencing.Registry`
provided by the caller are considered. The registry's external retrieval
callback is never invoked -- a reference which cannot be satisfied from the
registry is reported as a `jsonschema.exceptions.BundleError` instead of
producing an incomplete document.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any
from urllib.parse import urldefrag, urljoin, urlsplit

import referencing.exceptions
import referencing.jsonschema

from jsonschema.exceptions import BundleError

if TYPE_CHECKING:
    from collections.abc import Callable

#: The only JSON Schema dialect understood by this module.
_SPECIFICATION = referencing.jsonschema.DRAFT202012

#: Keywords whose string values are JSON references rather than annotations.
_REFERENCE_KEYWORDS = ("$ref", "$dynamicRef")


def _is_absolute(uri: str) -> bool:
    """Whether the given URI carries a scheme (and is therefore absolute)."""
    return bool(urlsplit(uri).scheme)


def _walk_references(
    schema: referencing.jsonschema.Schema,
    base_uri: str,
    emit: Callable[[str, str], None],
) -> None:
    """
    Visit every reference found at a real subschema position.

    References are reported via ``emit`` together with the base URI in scope
    at the point where they appear. Nested :kw:`$id` keywords update the base
    URI exactly as they do during normal reference resolution.

    Keywords which merely *contain* data -- such as :kw:`default`,
    :kw:`examples` or :kw:`enum` -- are never descended into, so a ``$ref``
    appearing inside an example is not mistaken for a dependency.
    """
    if isinstance(schema, bool):
        return

    for keyword in _REFERENCE_KEYWORDS:
        reference = schema.get(keyword)
        if isinstance(reference, str):
            emit(reference, base_uri)

    identifier = schema.get("$id")
    if isinstance(identifier, str):
        base_uri = urljoin(base_uri, identifier)

    for subschema in _SPECIFICATION.subresources_of(schema):
        _walk_references(subschema, base_uri, emit)


def _nested_identifiers(
    contents: referencing.jsonschema.Schema,
    base_uri: str,
) -> set[str]:
    """
    Return the absolute canonical URIs of every nested :kw:`$id` resource.

    The document's own identifier (at the entry point) is not included; only
    identifiers found at subschema positions are reported.
    """
    nested: set[str] = set()
    _collect_nested_identifiers(contents, base_uri, nested, top_level=True)
    return nested


def _collect_nested_identifiers(
    contents: referencing.jsonschema.Schema,
    base_uri: str,
    nested: set[str],
    top_level: bool = False,
) -> None:
    if isinstance(contents, bool):
        return

    identifier = contents.get("$id")
    if isinstance(identifier, str):
        base_uri = urljoin(base_uri, identifier).rstrip("#")
        if not top_level:
            nested.add(base_uri)

    for subschema in _SPECIFICATION.subresources_of(contents):
        _collect_nested_identifiers(subschema, base_uri, nested)


def _collect_nested_resources(
    contents: referencing.jsonschema.Schema,
    base_uri: str,
    containment: dict[str, str],
    root_uri: str,
) -> None:
    """
    Record which top-level document each nested :kw:`$id` resource belongs to.

    ``containment`` maps the absolute canonical URI of every resource nested
    inside the document rooted at ``root_uri`` back to ``root_uri``. This lets
    a reference aimed at a nested subresource pull in the whole enclosing
    document rather than a detached fragment of it.
    """
    for nested_uri in _nested_identifiers(contents, base_uri):
        containment[nested_uri] = root_uri


def _def_key_for(uri: str, defs: dict[str, Any], names: dict[str, str]) -> str:
    """
    Find a stable, unique :kw:`$defs` key for the resource at ``uri``.

    The same URI always maps to the same key. Keys already present in the
    main schema's own :kw:`$defs` are never overwritten; a numeric suffix is
    appended instead.
    """
    existing = names.get(uri)
    if existing is not None:
        return existing

    candidate = (
        "".join(
            character if character.isalnum() else "_" for character in uri
        ).strip("_")
        or "resource"
    )

    key = candidate
    counter = 0
    while key in defs:
        counter += 1
        key = f"{candidate}_{counter}"

    names[uri] = key
    return key


def _rewrite_boolean_references(
    node: Any,
    root_id: str,
    boolean_roots: dict[str, str],
) -> None:
    """
    Point references at embedded boolean documents through internal pointers.

    A boolean schema cannot carry an :kw:`$id`, so once a ``True``/``False``
    document has been embedded under :kw:`$defs`, references to its original
    URI are rewritten to point at the embedded copy.
    """
    if isinstance(node, bool):
        return
    if isinstance(node, list):
        for item in node:
            _rewrite_boolean_references(item, root_id, boolean_roots)
        return
    if not isinstance(node, dict):
        return

    for keyword in _REFERENCE_KEYWORDS:
        reference = node.get(keyword)
        if not isinstance(reference, str):
            continue
        if reference.startswith("#"):
            uri, fragment = root_id, reference[1:]
        else:
            uri, fragment = urldefrag(urljoin(root_id, reference))
        key = boolean_roots.get(uri.rstrip("#"))
        if key is not None:
            suffix = f"#{fragment}" if fragment else ""
            node[keyword] = f"#/$defs/{key}{suffix}"

    for value in node.values():
        _rewrite_boolean_references(value, root_id, boolean_roots)


def bundle(
    schema: referencing.jsonschema.ObjectSchema,
    registry: referencing.jsonschema.SchemaRegistry,
) -> referencing.jsonschema.ObjectSchema:
    """
    Bundle a Draft 2020-12 schema with the external resources it references.

    Arguments:

        schema:

            the main schema to bundle. It must be a JSON object (not a
            boolean) and must declare an absolute :kw:`$id` which identifies
            it.

        registry:

            an in-memory `referencing.Registry` holding every external
            resource the main schema may reference. Only resources reachable
            by following references from the main schema are embedded;
            unrelated entries in the registry are left out. The registry's
            retrieval callback is never called.

    Returns:

        a new schema object. The main schema's own keywords -- including any
        existing :kw:`$defs` -- are preserved, and copies of the reachable
        external resources are added under :kw:`$defs`. Neither the input
        schema nor the registry is modified, and the returned document shares
        no mutable structure with the inputs.

    Raises:

        `jsonschema.exceptions.BundleError`:

            if the main schema lacks an absolute :kw:`$id`, or if a reference
            targets a resource, named/dynamic anchor, or JSON-pointer
            location that is not present in the registry.

    """
    if not isinstance(schema, dict):
        raise BundleError(
            "The main schema must be a JSON object with an absolute $id; "
            f"boolean schemas cannot be bundled, got {schema!r}.",
        )

    root_id = schema.get("$id")
    if not isinstance(root_id, str) or not _is_absolute(root_id):
        raise BundleError(
            "The main schema must declare an absolute $id so that its "
            f"references have a stable resolution base; got {root_id!r}.",
        )
    root_id = root_id.rstrip("#")

    root_resource = _SPECIFICATION.create_resource(schema)

    def _forbid_retrieval(uri: str):  # pragma: no cover -- defensive guard
        raise referencing.exceptions.NoSuchResource(ref=uri)  # type: ignore[call-arg]

    # Rebuild the registry from its in-memory resources, dropping any
    # retrieval callback. This guarantees the caller's external-read hook is
    # never invoked even accidentally; every dependency must be in memory.
    working = (
        referencing.Registry(  # type: ignore[call-arg]
            retrieve=_forbid_retrieval,
        )
        .with_resources(
            (uri, resource) for uri, resource in registry.crawl().items()
        )
        .with_resource(root_id, root_resource)
        .crawl()
    )

    # Map each nested subresource URI to the top-level document enclosing it,
    # using only the resources the caller actually registered.
    containment: dict[str, str] = {}
    for registered_uri in registry:
        registered_uri = registered_uri.rstrip("#")
        if registered_uri == root_id:
            continue
        _collect_nested_resources(
            working[registered_uri].contents,
            registered_uri,
            containment,
            registered_uri,
        )

    # Resources nested *inside the main schema itself* are part of the main
    # document and must never be re-embedded as external resources.
    nested_in_root = _nested_identifiers(schema, root_id)

    external_roots: list[str] = []

    def _resolve(reference: str, base_uri: str) -> None:
        if reference.startswith("#"):
            uri, fragment = base_uri.rstrip("#"), reference[1:]
        else:
            uri, fragment = urldefrag(urljoin(base_uri, reference))
        uri = uri.rstrip("#")

        if uri == root_id or uri in nested_in_root:
            # Part of the main document itself (possibly a nested $id).
            resource = working[uri]
        else:
            try:
                resource = working[uri]
            except referencing.exceptions.NoSuchResource:
                raise BundleError(
                    f"Cannot bundle reference {reference!r}: the resource "
                    f"{uri!r} is not registered in the provided registry. "
                    "Register it before bundling; external resources are not "
                    "retrieved automatically.",
                ) from None

            document_root = containment.get(uri, uri)
            if document_root not in external_roots:
                external_roots.append(document_root)

        if not fragment:
            return

        if fragment.startswith("/"):
            try:
                resource.pointer(fragment, working.resolver(uri))
            except (
                referencing.exceptions.PointerToNowhere,
                TypeError,
            ):
                raise BundleError(
                    f"Cannot bundle reference {reference!r}: the JSON "
                    f"pointer {fragment!r} does not identify a location "
                    f"within the resource at {uri!r}.",
                ) from None
        else:
            try:
                working.anchor(uri, fragment)
            except referencing.exceptions.NoSuchAnchor:
                raise BundleError(
                    f"Cannot bundle reference {reference!r}: no anchor named "
                    f"{fragment!r} exists within the resource at {uri!r}.",
                ) from None

    def _walk_and_resolve(
        contents: referencing.jsonschema.Schema,
        base_uri: str,
    ) -> None:
        references: list[tuple[str, str]] = []
        _walk_references(
            contents,
            base_uri,
            lambda reference, scope: references.append(
                (reference, scope),
            ),
        )
        for reference, scope in references:
            _resolve(reference, scope)

    # First satisfy everything the main schema points at, then follow the
    # references of each newly discovered external document. A worklist makes
    # cycles between mutually referencing documents terminate naturally.
    _walk_and_resolve(schema, root_id)
    index = 0
    while index < len(external_roots):
        document_root = external_roots[index]
        _walk_and_resolve(working[document_root].contents, document_root)
        index += 1

    bundled = deepcopy(schema)
    defs: dict[str, Any] = (
        bundled.setdefault("$defs", {}) if external_roots else {}
    )
    names: dict[str, str] = {}
    boolean_roots: dict[str, str] = {}

    for uri in sorted(external_roots):
        resource = working[uri]
        contents = resource.contents
        key = _def_key_for(uri, defs, names)

        if isinstance(contents, bool):
            defs[key] = contents
            boolean_roots[uri] = key
            continue

        embedded = deepcopy(contents)
        # Give the copy its canonical absolute URI. A originally relative
        # $id is rewritten to the absolute location it resolved to, so that
        # reference strings left untouched in the copy keep their meaning.
        embedded["$id"] = uri
        defs[key] = embedded

    if boolean_roots:
        _rewrite_boolean_references(bundled, root_id, boolean_roots)

    return bundled
