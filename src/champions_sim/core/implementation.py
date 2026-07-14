"""Deterministic source and live-code fingerprints for policy components."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from fractions import Fraction
from types import (
    CodeType,
    FunctionType,
    GetSetDescriptorType,
    MappingProxyType,
    MemberDescriptorType,
    ModuleType,
)

from .canonical import canonical_hash, canonical_json


_STANDARD_CLASS_METADATA = {
    "__annotations__",
    "__dataclass_fields__",
    "__dataclass_params__",
    "__dict__",
    "__doc__",
    "__match_args__",
    "__module__",
    "__slots__",
    "__weakref__",
}

_ALWAYS_BOUND_CLASS_METADATA = {
    "__annotations__",
    "__doc__",
    "__match_args__",
    "__module__",
    "__qualname__",
    "__slots__",
}


def class_source_sha256(component: type) -> str:
    return hashlib.sha256(inspect.getsource(component).encode("utf-8")).hexdigest()


def component_state_sha256(component: object) -> str:
    """Fingerprint one component's exact, canonical instance state.

    Container and domain-value types are tagged deliberately, so semantically
    different Python states such as a list and tuple cannot share an identity.
    Arbitrary objects are accepted only at the root component boundary; nested
    state must consist of explicit immutable domain values.
    """

    return canonical_hash(
        _component_state_data(
            component,
            root=True,
            object_stack=frozenset(),
            references={},
        )
    )


def class_runtime_sha256(component: type) -> str:
    """Fingerprint the live effective implementation installed on a class.

    MRO-resolved methods and stable class attributes are included, so a
    monkeypatch on an inherited method or a behavioral class constant is not
    hidden by an otherwise empty subclass.  This deliberately does not claim
    to close over process globals or imported dependencies; process isolation
    remains a separate evaluation gate.
    """

    methods: list[dict[str, object]] = []
    attributes: list[dict[str, object]] = []
    runtime_references: dict[int, tuple[int, object]] = {}
    effective_members: dict[str, tuple[type, object]] = {}
    for owner in component.__mro__:
        if owner is object:
            continue
        for name in owner.__dict__:
            effective_members.setdefault(
                name,
                (owner, inspect.getattr_static(component, name)),
            )

    referenced_names: set[str] = set()
    for _, descriptor in effective_members.values():
        for _, _, function in _descriptor_functions("", descriptor):
            referenced_names.update(_code_referenced_names(function.__code__))

    for name, (owner, descriptor) in sorted(effective_members.items()):
        functions = _descriptor_functions(name, descriptor)
        descriptor_reference_id: int | None = None
        if functions:
            _, descriptor_reference_id = _runtime_reference(
                descriptor, runtime_references
            )
        for method_name, descriptor_kind, function in functions:
            _, function_reference_id = _runtime_reference(
                function, runtime_references
            )
            methods.append(
                {
                    "name": method_name,
                    "owner": f"{owner.__module__}.{owner.__qualname__}",
                    "descriptor_kind": descriptor_kind,
                    "descriptor_reference_id": descriptor_reference_id,
                    "function_reference_id": function_reference_id,
                    "code": _code_data(function.__code__, runtime_references),
                    "defaults": _constant_data(
                        function.__defaults__,
                        frozenset({id(function)}),
                        runtime_references,
                    ),
                    "kwdefaults": _constant_data(
                        function.__kwdefaults__,
                        frozenset({id(function)}),
                        runtime_references,
                    ),
                    "closure": _closure_data(
                        function,
                        frozenset({id(function)}),
                        runtime_references,
                    ),
                    "attributes": _constant_data(
                        function.__dict__,
                        frozenset({id(function)}),
                        runtime_references,
                    ),
                    "module": _constant_data(
                        function.__module__, references=runtime_references
                    ),
                    "name_metadata": _constant_data(
                        function.__name__, references=runtime_references
                    ),
                    "qualname_metadata": _constant_data(
                        function.__qualname__, references=runtime_references
                    ),
                    "doc": _constant_data(
                        function.__doc__, references=runtime_references
                    ),
                    "annotations": _constant_data(
                        function.__annotations__,
                        frozenset({id(function)}),
                        runtime_references,
                    ),
                }
            )
        if (
            not functions
            and (
                name not in _STANDARD_CLASS_METADATA
                or name in _ALWAYS_BOUND_CLASS_METADATA
                or name in referenced_names
            )
        ):
            attributes.append(
                {
                    "name": name,
                    "owner": f"{owner.__module__}.{owner.__qualname__}",
                    "value": _runtime_attribute_data(
                        descriptor, runtime_references
                    ),
                }
            )
    return canonical_hash(
        {
            "component": f"{component.__module__}.{component.__qualname__}",
            "methods": tuple(methods),
            "attributes": tuple(attributes),
        }
    )


def _component_state_data(
    value: object,
    *,
    root: bool = False,
    object_stack: frozenset[int],
    references: dict[int, tuple[int, object]],
) -> object:
    if isinstance(value, Enum):
        reference, reference_id = _component_reference(
            value,
            object_stack=object_stack,
            references=references,
        )
        if reference is not None:
            return reference
        next_stack = object_stack | {id(value)}
        return {
            "reference_id": reference_id,
            "enum": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _component_state_data(
                value.value,
                object_stack=next_stack,
                references=references,
            ),
        }
    if value is None or type(value) is bool:
        return value
    if type(value) in {str, int}:
        reference, reference_id = _component_reference(
            value,
            object_stack=object_stack,
            references=references,
        )
        if reference is not None:
            return reference
        return {
            "reference_id": reference_id,
            "scalar": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": value,
        }
    if isinstance(value, (str, int)):
        raise TypeError("scalar subclasses are not accepted in bound component state")
    if isinstance(value, float):
        raise TypeError("floats are not accepted in bound component state")
    if type(value) is Fraction:
        reference, reference_id = _component_reference(
            value,
            object_stack=object_stack,
            references=references,
        )
        if reference is not None:
            return reference
        next_stack = object_stack | {id(value)}
        return {
            "reference_id": reference_id,
            "fraction": f"{type(value).__module__}.{type(value).__qualname__}",
            "numerator": _component_state_data(
                value.numerator,
                object_stack=next_stack,
                references=references,
            ),
            "denominator": _component_state_data(
                value.denominator,
                object_stack=next_stack,
                references=references,
            ),
        }
    if isinstance(value, Fraction):
        raise TypeError("Fraction subclasses are not accepted in bound component state")
    if isinstance(value, (set, frozenset)):
        raise TypeError("unordered component state is not accepted")
    if is_dataclass(value) and not isinstance(value, type):
        reference, reference_id = _component_reference(
            value,
            object_stack=object_stack,
            references=references,
        )
        if reference is not None:
            return reference
        next_stack = object_stack | {id(value)}
        dataclass_fields = fields(value)
        return {
            "reference_id": reference_id,
            "dataclass": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": {
                field.name: _component_state_data(
                    _raw_instance_attribute(value, field.name),
                    object_stack=next_stack,
                    references=references,
                )
                for field in dataclass_fields
            },
            "extra_state": _instance_storage_data(
                value,
                excluded_names=frozenset(field.name for field in dataclass_fields),
                object_stack=next_stack,
                references=references,
            ),
        }
    if isinstance(value, Mapping):
        if type(value) not in {dict, MappingProxyType}:
            raise TypeError(
                "bound component mappings require exact dict or mappingproxy"
            )
        reference, reference_id = _component_reference(
            value,
            object_stack=object_stack,
            references=references,
        )
        if reference is not None:
            return reference
        next_stack = object_stack | {id(value)}
        converted: list[dict[str, object]] = []
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("bound component mappings require exact string keys")
            converted.append(
                {
                    "key": _component_state_data(
                        key,
                        object_stack=next_stack,
                        references=references,
                    ),
                    "value": _component_state_data(
                        item,
                        object_stack=next_stack,
                        references=references,
                    ),
                }
            )
        return {
            "reference_id": reference_id,
            "mapping": f"{type(value).__module__}.{type(value).__qualname__}",
            # Python mappings may expose iteration order to policy code.  Keep
            # the observed order instead of letting canonical JSON sort it.
            "items": tuple(converted),
            "extra_state": _instance_storage_data(
                value,
                excluded_names=frozenset(),
                object_stack=next_stack,
                references=references,
            ),
        }
    if isinstance(value, tuple):
        if type(value) is not tuple:
            raise TypeError("tuple subclasses are not accepted in bound component state")
        reference, reference_id = _component_reference(
            value,
            object_stack=object_stack,
            references=references,
        )
        if reference is not None:
            return reference
        next_stack = object_stack | {id(value)}
        return {
            "reference_id": reference_id,
            "tuple": f"{type(value).__module__}.{type(value).__qualname__}",
            "items": tuple(
                _component_state_data(
                    item,
                    object_stack=next_stack,
                    references=references,
                )
                for item in value
            ),
            "extra_state": _instance_storage_data(
                value,
                excluded_names=frozenset(),
                object_stack=next_stack,
                references=references,
            ),
        }
    if isinstance(value, list):
        if type(value) is not list:
            raise TypeError("list subclasses are not accepted in bound component state")
        reference, reference_id = _component_reference(
            value,
            object_stack=object_stack,
            references=references,
        )
        if reference is not None:
            return reference
        next_stack = object_stack | {id(value)}
        return {
            "reference_id": reference_id,
            "list": f"{type(value).__module__}.{type(value).__qualname__}",
            "items": tuple(
                _component_state_data(
                    item,
                    object_stack=next_stack,
                    references=references,
                )
                for item in value
            ),
            "extra_state": _instance_storage_data(
                value,
                excluded_names=frozenset(),
                object_stack=next_stack,
                references=references,
            ),
        }
    if root and not isinstance(value, (type, FunctionType, ModuleType)):
        reference, reference_id = _component_reference(
            value,
            object_stack=object_stack,
            references=references,
        )
        if reference is not None:
            return reference
        next_stack = object_stack | {id(value)}
        return {
            "reference_id": reference_id,
            "component": f"{type(value).__module__}.{type(value).__qualname__}",
            "state": _instance_storage_data(
                value,
                excluded_names=frozenset(),
                object_stack=next_stack,
                references=references,
            ),
        }
    raise TypeError(
        "unsupported bound component state: "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _component_reference(
    value: object,
    *,
    object_stack: frozenset[int],
    references: dict[int, tuple[int, object]],
) -> tuple[dict[str, int] | None, int]:
    object_id = id(value)
    if object_id in object_stack:
        raise TypeError("cyclic component state is not accepted")
    existing = references.get(object_id)
    if existing is not None:
        reference_id, existing_value = existing
        if existing_value is not value:
            raise TypeError("component reference identity was reused unexpectedly")
        return {"reference": reference_id}, reference_id
    reference_id = len(references)
    # Keep a strong reference for the duration of normalization so temporary
    # helper mappings cannot be collected and have their process ID reused.
    references[object_id] = (reference_id, value)
    return None, reference_id


def _instance_storage_data(
    value: object,
    *,
    excluded_names: frozenset[str],
    object_stack: frozenset[int],
    references: dict[int, tuple[int, object]],
) -> dict[str, object]:
    state: dict[str, object] = {}
    try:
        instance_dict = object.__getattribute__(value, "__dict__")
    except AttributeError:
        instance_dict = None
    if instance_dict is not None:
        if type(instance_dict) is not dict:
            raise TypeError("component __dict__ must use the exact dict contract")
        extra_dict = {
            key: item
            for key, item in instance_dict.items()
            if key not in excluded_names
        }
        if extra_dict:
            state["dict"] = _component_state_data(
                extra_dict,
                object_stack=object_stack,
                references=references,
            )
    slot_state: list[dict[str, object]] = []
    for owner, name, descriptor in _instance_slot_descriptors(type(value)):
        if name in excluded_names:
            continue
        key = f"{owner.__module__}.{owner.__qualname__}:{name}"
        try:
            item = descriptor.__get__(value, type(value))
        except AttributeError:
            normalized = {"uninitialized_slot": True}
        else:
            normalized = _component_state_data(
                item,
                object_stack=object_stack,
                references=references,
            )
        slot_state.append({"slot": key, "value": normalized})
    if slot_state:
        state["slots"] = tuple(slot_state)
    return state


def _raw_instance_attribute(value: object, name: str) -> object:
    """Read real instance storage without invoking subject code."""

    try:
        instance_dict = object.__getattribute__(value, "__dict__")
    except AttributeError:
        instance_dict = None
    if instance_dict is not None:
        if type(instance_dict) is not dict:
            raise TypeError("component __dict__ must use the exact dict contract")
        if name in instance_dict:
            return instance_dict[name]
    for _, slot_name, descriptor in _instance_slot_descriptors(type(value)):
        if slot_name == name:
            try:
                return descriptor.__get__(value, type(value))
            except AttributeError as error:
                raise TypeError(f"component slot is uninitialized: {name}") from error
    raise TypeError(f"component field has no canonical instance storage: {name}")


def _instance_slot_descriptors(
    component_type: type,
) -> tuple[tuple[type, str, MemberDescriptorType | GetSetDescriptorType], ...]:
    descriptors: list[
        tuple[type, str, MemberDescriptorType | GetSetDescriptorType]
    ] = []
    for owner in component_type.__mro__:
        raw_slots = owner.__dict__.get("__slots__", ())
        slots = (raw_slots,) if isinstance(raw_slots, str) else raw_slots
        for declared_name in slots:
            if declared_name in {"__dict__", "__weakref__"}:
                continue
            storage_name = _mangled_slot_name(owner, declared_name)
            descriptor = owner.__dict__.get(storage_name)
            if not isinstance(descriptor, (MemberDescriptorType, GetSetDescriptorType)):
                raise TypeError(
                    "component slot lacks a canonical storage descriptor: "
                    f"{owner.__module__}.{owner.__qualname__}.{storage_name}"
                )
            descriptors.append((owner, storage_name, descriptor))
    return tuple(descriptors)


def _mangled_slot_name(owner: type, name: str) -> str:
    if name.startswith("__") and not name.endswith("__"):
        return f"_{owner.__name__.lstrip('_')}{name}"
    return name


def _descriptor_functions(
    name: str,
    descriptor: object,
) -> tuple[tuple[str, str, FunctionType], ...]:
    if type(descriptor) is FunctionType:
        return ((name, "instance_method", descriptor),)
    if type(descriptor) is staticmethod:
        return ((name, "staticmethod", descriptor.__func__),)
    if type(descriptor) is classmethod:
        return ((name, "classmethod", descriptor.__func__),)
    if type(descriptor) is property:
        return tuple(
            (f"{name}.{accessor}", f"property_{accessor}", function)
            for accessor, function in (
                ("get", descriptor.fget),
                ("set", descriptor.fset),
                ("delete", descriptor.fdel),
            )
            if function is not None
        )
    return ()


def _code_referenced_names(code: CodeType) -> set[str]:
    names = set(code.co_names)
    for value in code.co_consts:
        if type(value) is str:
            # Dynamic class-member access such as getattr(type(self), NAME)
            # stores NAME in constants rather than co_names.  Treat every
            # exact string constant as a possible member dependency; only
            # actual effective member names are consumed by the caller.
            names.add(value)
        elif isinstance(value, CodeType):
            names.update(_code_referenced_names(value))
    return names


def _code_data(
    code: CodeType,
    references: dict[int, tuple[int, object]],
) -> dict[str, object]:
    _, reference_id = _runtime_reference(code, references)
    exception_table = getattr(code, "co_exceptiontable", None)
    return {
        "reference_id": reference_id,
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "flags": code.co_flags,
        "bytecode_sha256": hashlib.sha256(code.co_code).hexdigest(),
        "exceptiontable_present": exception_table is not None,
        "exceptiontable_sha256": (
            hashlib.sha256(exception_table).hexdigest()
            if exception_table is not None
            else None
        ),
        "constants": tuple(
            _constant_data(value, references=references)
            for value in code.co_consts
        ),
        "names": code.co_names,
        "varnames": code.co_varnames,
        "freevars": code.co_freevars,
        "cellvars": code.co_cellvars,
    }


def _constant_data(
    value: object,
    function_stack: frozenset[int] = frozenset(),
    references: dict[int, tuple[int, object]] | None = None,
) -> object:
    if references is None:
        references = {}
    if isinstance(value, Enum):
        reference, reference_id = _runtime_reference(value, references)
        if reference is not None:
            return reference
        return {
            "reference_id": reference_id,
            "enum": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _constant_data(value.value, function_stack, references),
        }
    if type(value) is Fraction:
        reference, reference_id = _runtime_reference(value, references)
        if reference is not None:
            return reference
        return {
            "reference_id": reference_id,
            "fraction": f"{type(value).__module__}.{type(value).__qualname__}",
            "numerator": _constant_data(
                value.numerator, function_stack, references
            ),
            "denominator": _constant_data(
                value.denominator, function_stack, references
            ),
        }
    if isinstance(value, Fraction):
        raise TypeError("Fraction subclasses are not accepted in runtime fingerprints")
    if value is None or type(value) is bool:
        return value
    if type(value) in {str, int}:
        reference, reference_id = _runtime_reference(value, references)
        if reference is not None:
            return reference
        return {
            "reference_id": reference_id,
            "scalar": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": value,
        }
    if isinstance(value, (str, int)):
        raise TypeError("scalar subclasses are not accepted in runtime fingerprints")
    if type(value) is float:
        reference, reference_id = _runtime_reference(value, references)
        if reference is not None:
            return reference
        return {"reference_id": reference_id, "float_hex": value.hex()}
    if isinstance(value, float):
        raise TypeError("float subclasses are not accepted in runtime fingerprints")
    if type(value) is bytes:
        reference, reference_id = _runtime_reference(value, references)
        if reference is not None:
            return reference
        return {"reference_id": reference_id, "bytes_hex": value.hex()}
    if isinstance(value, bytes):
        raise TypeError("bytes subclasses are not accepted in runtime fingerprints")
    if isinstance(value, CodeType):
        return {"code": _code_data(value, references)}
    if isinstance(value, FunctionType):
        return _function_data(value, function_stack, references)
    if isinstance(value, ModuleType):
        return {"module": value.__name__}
    if isinstance(value, type):
        return {"type_object": f"{value.__module__}.{value.__qualname__}"}
    if isinstance(value, tuple):
        if type(value) is not tuple:
            raise TypeError("tuple subclasses are not accepted in runtime fingerprints")
        reference, reference_id = _runtime_reference(value, references)
        if reference is not None:
            return reference
        return {
            "reference_id": reference_id,
            "tuple": f"{type(value).__module__}.{type(value).__qualname__}",
            "items": tuple(
                _constant_data(item, function_stack, references)
                for item in value
            ),
        }
    if isinstance(value, list):
        if type(value) is not list:
            raise TypeError("list subclasses are not accepted in runtime fingerprints")
        reference, reference_id = _runtime_reference(value, references)
        if reference is not None:
            return reference
        return {
            "reference_id": reference_id,
            "list": f"{type(value).__module__}.{type(value).__qualname__}",
            "items": tuple(
                _constant_data(item, function_stack, references)
                for item in value
            ),
        }
    if isinstance(value, (set, frozenset)):
        if type(value) not in {set, frozenset}:
            raise TypeError("set subclasses are not accepted in runtime fingerprints")
        reference, reference_id = _runtime_reference(value, references)
        if reference is not None:
            return reference
        ordered_values = tuple(
            sorted(
                value,
                key=lambda item: canonical_json(
                    _constant_data(item, function_stack, {})
                ),
            )
        )
        return {
            "reference_id": reference_id,
            "set": f"{type(value).__module__}.{type(value).__qualname__}",
            "items": tuple(
                _constant_data(item, function_stack, references)
                for item in ordered_values
            ),
        }
    if isinstance(value, Mapping):
        if type(value) not in {dict, MappingProxyType}:
            raise TypeError(
                "runtime fingerprint mappings require exact dict or mappingproxy"
            )
        if any(type(key) is not str for key in value):
            raise TypeError("runtime fingerprint mappings require exact string keys")
        reference, reference_id = _runtime_reference(value, references)
        if reference is not None:
            return reference
        return {
            "reference_id": reference_id,
            "mapping": f"{type(value).__module__}.{type(value).__qualname__}",
            "items": tuple(
                {
                    "key": _constant_data(
                        key, function_stack, references
                    ),
                    "value": _constant_data(
                        item, function_stack, references
                    ),
                }
                for key, item in value.items()
            ),
        }
    if is_dataclass(value) and not isinstance(value, type):
        reference, reference_id = _runtime_reference(value, references)
        if reference is not None:
            return reference
        dataclass_fields = fields(value)
        return {
            "reference_id": reference_id,
            "dataclass": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": {
                field.name: _constant_data(
                    _raw_instance_attribute(value, field.name),
                    function_stack,
                    references,
                )
                for field in dataclass_fields
            },
            "extra_state": _instance_storage_data(
                value,
                excluded_names=frozenset(field.name for field in dataclass_fields),
                object_stack=frozenset({id(value)}),
                references=references,
            ),
        }
    if value is Ellipsis:
        return {"constant": "ellipsis"}
    raise TypeError(
        "non-canonical runtime fingerprint value: "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _runtime_attribute_data(
    value: object,
    references: dict[int, tuple[int, object]],
) -> object:
    """Return process-stable data for behavior-relevant class attributes."""

    if isinstance(value, (MemberDescriptorType, GetSetDescriptorType)):
        return {
            "descriptor": f"{type(value).__module__}.{type(value).__qualname__}",
            "name": getattr(value, "__name__", None),
        }
    return _constant_data(value, references=references)


def _function_data(
    function: FunctionType,
    function_stack: frozenset[int],
    references: dict[int, tuple[int, object]],
) -> object:
    path = f"{function.__module__}.{function.__qualname__}"
    reference, reference_id = _runtime_reference(function, references)
    if reference is not None:
        return reference
    if id(function) in function_stack:
        return {"function_cycle": path}
    next_stack = function_stack | {id(function)}
    return {
        "reference_id": reference_id,
        "function": path,
        "code": _code_data(function.__code__, references),
        "defaults": _constant_data(
            function.__defaults__, next_stack, references
        ),
        "kwdefaults": _constant_data(
            function.__kwdefaults__, next_stack, references
        ),
        "closure": _closure_data(function, next_stack, references),
        "attributes": _constant_data(
            function.__dict__, next_stack, references
        ),
    }


def _closure_data(
    function: FunctionType,
    function_stack: frozenset[int],
    references: dict[int, tuple[int, object]],
) -> object:
    cells = function.__closure__
    if cells is None:
        return None
    values: list[object] = []
    for cell in cells:
        try:
            value = cell.cell_contents
        except ValueError:
            values.append({"empty_cell": True})
        else:
            values.append(_constant_data(value, function_stack, references))
    return tuple(values)


def _runtime_reference(
    value: object,
    references: dict[int, tuple[int, object]],
) -> tuple[dict[str, int] | None, int]:
    object_id = id(value)
    existing = references.get(object_id)
    if existing is not None:
        reference_id, existing_value = existing
        if existing_value is not value:
            raise TypeError("runtime reference identity was reused unexpectedly")
        return {"reference": reference_id}, reference_id
    reference_id = len(references)
    references[object_id] = (reference_id, value)
    return None, reference_id
