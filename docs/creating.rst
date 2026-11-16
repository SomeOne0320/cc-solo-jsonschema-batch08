.. currentmodule:: jsonschema.validators

.. _creating-validators:

=======================================
Creating or Extending Validator Classes
=======================================

.. autofunction:: create
    :noindex:

.. autofunction:: extend
    :noindex:

.. autofunction:: validator_for
    :noindex:

.. autofunction:: validates
    :noindex:


Creating Validation Errors
--------------------------

Any validating function that validates against a subschema should call
``descend``, rather than ``iter_errors``. If it recurses into the
instance, or schema, it should pass one or both of the ``path`` or
``schema_path`` arguments to ``descend`` in order to properly maintain
where in the instance or schema respectively the error occurred.

Validating functions only need to provide the details which are specific
to the failure (typically just a ``message``, and any ``path`` or
``schema_path`` within the keyword's own value). The ``validator``,
``validator_value``, ``instance``, ``schema`` and type checker of an error
are filled in centrally, and are not overwritten if the validating
function already set them.

The Validator Protocol
----------------------

``jsonschema`` defines a `protocol <typing.Protocol>`, `jsonschema.protocols.Validator` which can be used in type annotations to describe the type of a validator.

For full details, see `validator-protocol`.
