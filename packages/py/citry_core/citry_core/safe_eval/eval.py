import builtins
from typing import Any, Callable, Mapping, Optional, Tuple

from citry_core import _rust
from citry_core.safe_eval.error import error_context, format_error_with_context
from citry_core.safe_eval.sandbox import (
    is_safe_attribute,
    is_safe_callable,
    is_safe_variable,
)


class SecurityError(Exception):
    """An error raised when a security violation occurs."""


def safe_eval(
    source: str,
    *,
    validate_variable: Optional[Callable[[str], bool]] = None,
    validate_attribute: Optional[Callable[[Any, str], bool]] = None,
    validate_subscript: Optional[Callable[[Any, Any], bool]] = None,
    validate_callable: Optional[Callable[[Callable], bool]] = None,
    validate_assign: Optional[Callable[[str, Any], bool]] = None,
) -> Callable[[Mapping[str, Any]], Any]:
    """
    Compile a Python expression string into a safe evaluation function.

    This function takes a Python expression string and transforms it into safe code
    by wrapping potentially unsafe operations (like variable access, function calls,
    attribute access, etc.) with sandboxed function calls.

    This is the re-implementation of Jinja's sandboxed evaluation logic.

    Args:
        source: The Python expression string to transform.
        validate_variable: Optional extra validation for variable lookups.
        validate_attribute: Optional extra validation for attribute access.
        validate_subscript: Optional extra validation for subscript access.
        validate_callable: Optional extra validation for function calls.
        validate_assign: Optional extra validation for variable assignments.

    Returns:
        A compiled function that takes a context mapping and evaluates the expression.
        The function signature is: `func(context: Mapping[str, Any]) -> Any`

        The returned function may raise SecurityError if the expression is unsafe.

    Raises:
        SyntaxError: If the input is not valid Python syntax or contains forbidden constructs.

    Example:
        >>> compiled = safe_eval("my_var + 1")
        >>> result = compiled({"my_var": 5})
        >>> print(result)
        6

        >>> compiled = safe_eval("lambda x: x + my_var")
        >>> func = compiled({"my_var": 10})
        >>> print(func(5))
        15

        >>> compiled = safe_eval("unsafe_var + 1", validate_variable=lambda name: name != "unsafe_var")
        >>> result = compiled({"unsafe_var": 5})
        SecurityError: variable 'unsafe_var' is unsafe

    """
    # If user specified extra validation functions, wrap the original functions with them
    if validate_variable is not None:

        @error_context("variable")
        def variable_fn(
            __context: Mapping[str, Any],
            __source: str,
            __token: Tuple[int, int],
            var_name: str,
        ) -> Any:
            if not validate_variable(var_name):
                raise SecurityError(f"variable '{var_name}' is unsafe")
            return variable(__context, __source, __token, var_name)
    else:
        variable_fn = variable

    if validate_attribute is not None:

        @error_context("attribute")
        def attribute_fn(
            __context: Mapping[str, Any],
            __source: str,
            __token: Tuple[int, int],
            obj: Any,
            attr_name: str,
        ) -> Any:
            if not validate_attribute(obj, attr_name):
                raise SecurityError(f"attribute '{attr_name}' on object '{type(obj)}' is unsafe")
            return attribute(__context, __source, __token, obj, attr_name)
    else:
        attribute_fn = attribute

    if validate_subscript is not None:

        @error_context("subscript")
        def subscript_fn(
            __context: Mapping[str, Any],
            __source: str,
            __token: Tuple[int, int],
            obj: Any,
            key: Any,
        ) -> Any:
            if not validate_subscript(obj, key):
                raise SecurityError(f"key '{key}' on object '{type(obj)}' is unsafe")
            return subscript(__context, __source, __token, obj, key)
    else:
        subscript_fn = subscript

    if validate_callable is not None:

        @error_context("call")
        def call_fn(
            __context: Mapping[str, Any],
            __source: str,
            __token: Tuple[int, int],
            func: Callable,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            if not validate_callable(func):
                raise SecurityError(f"function '{func!r}' is unsafe")
            return call(__context, __source, __token, func, *args, **kwargs)
    else:
        call_fn = call

    if validate_assign is not None:

        @error_context("assign")
        def assign_fn(
            __context: Mapping[str, Any],
            __source: str,
            __token: Tuple[int, int],
            var_name: str,
            value: Any,
        ) -> Any:
            if not validate_assign(var_name, value):
                raise SecurityError(f"assignment to variable '{var_name}' is unsafe")
            return assign(__context, __source, __token, var_name, value)
    else:
        assign_fn = assign

    # Create evaluation namespace with wrapped functions
    # These are captured in the closure of the lambda function we'll create
    eval_namespace = {
        "variable": variable_fn,
        "attribute": attribute_fn,
        "subscript": subscript_fn,
        "call": call_fn,
        "assign": assign_fn,
        "slice": slice,
        "interpolation": interpolation,
        "template": template,
        "format": format,
        # Pass through the source string. This way we won't have to re-define
        # the functions on each evaluation.
        "source": source,
    }

    # Get transformed code from Rust
    transformed_code = _rust.safe_eval.safe_eval(source)

    # Wrap the transformed code in a lambda that captures the helper functions
    # This avoids the overhead of calling eval() and creating a dict on each evaluation
    # NOTE: The lambda is assigned to a variable because we use `exec()` instead of `eval()`
    #       to support triple-quoted multi-line strings (which `eval()` doesn't handle).
    #       And while `eval()` returns its result directly, with `exec()` we need to assign it to a variable.
    #       We wrap with parentheses and newlines to allow multi-line expressions and trailing comments:
    #       the newlines ensure that trailing comments don't swallow the closing parenthesis.
    lambda_code = f"_eval_expr = lambda context: (\n{transformed_code}\n)"

    return _exec_func_with_error_handling(lambda_code, "_eval_expr", source, "expression", eval_namespace)


# NOTE: This is used also in citry_template_parser.
def _exec_func_with_error_handling(
    func_string: str, func_name: str, source: str, kind: str, global_scope: Mapping[str, Any]
) -> Callable[..., Any]:
    local_scope = {}

    # The `func_string` code should create a function and assign it to the local_scope[func_name] variable.
    # We do so to avoid the overhead of calling `exec()` on each evaluation.
    try:
        exec(func_string, global_scope, local_scope)
    except Exception as e:
        # If the error hasn't been processed by `error_context` decorator,
        # include the whole expression in the error message (without the "Error in..." prefix)
        if not getattr(e, "_error_processed", False):
            format_error_with_context(e, source, 0, len(source), kind, add_prefix=False)
            # Mark it as processed to avoid double-formatting if re-raised
            e._error_processed = True  # type: ignore[attr-defined]
        raise
    else:
        # Get the function from the local scope
        compiled_func = local_scope[func_name]

    # Return a function that calls the compiled function
    # We return this wrapper function so that we can intercept errors and add context to the error message.
    def evaluate(*args, **kwargs) -> Any:
        """Evaluate the compiled function with the given arguments."""
        try:
            return compiled_func(*args, **kwargs)
        except Exception as e:
            # If the error hasn't been processed by `error_context` decorator,
            # include the whole source code in the error message (without the "Error in..." prefix)
            if not getattr(e, "_error_processed", False):
                format_error_with_context(e, source, 0, len(source), kind, add_prefix=False)
                # Mark it as processed to avoid double-formatting if re-raised
                e._error_processed = True  # type: ignore[attr-defined]
            raise

    evaluate._source_code = func_string
    return evaluate


# Following are the operations that we intercept. These functions are called by the transformed code.
#
# E.g.
# ```python
# my_var
# obj := {"attr": 2}
# ```
#
# is transformed into:
# ```python
# variable((0, 4), source, context, "my_var")
# assign((0, 18), source, context, "obj", {"attr": 2})
# ```
#
# Each interceptor function receives the same 3 first positional arguments:
# - __context: Mapping[str, Any] - The evaluation context
# - __source: str - The source code
# - __token: Tuple[int, int] - The token tuple (start_index, end_index)
#
# The __source and __token arguments are used by `@error_context` decorator to add the position
# where the error occurred to the error message.
# E.g.
# ```
# obj := eval("unsafe code")
#        ^^^^^^^^^^^^^^^^^^^
# SecurityError: <built-in function eval> is unsafe
# ```


@error_context("variable")
def variable(__context: Mapping[str, Any], __source: str, __token: Tuple[int, int], var_name: str) -> Any:
    """Look up a variable in the evaluation context, e.g. `my_var`"""
    if not is_safe_variable(var_name):
        raise SecurityError(f"variable '{var_name}' is unsafe")
    return __context[var_name]


@error_context("attribute")
def attribute(
    __context: Mapping[str, Any],
    __source: str,
    __token: Tuple[int, int],
    obj: Any,
    attr_name: str,
) -> Any:
    """Access an attribute of an object, e.g. `obj.attr`"""
    if not is_safe_attribute(obj, attr_name):
        raise SecurityError(f"attribute '{attr_name}' on object '{type(obj)}' is unsafe")
    return getattr(obj, attr_name)


@error_context("subscript")
def subscript(
    __context: Mapping[str, Any],
    __source: str,
    __token: Tuple[int, int],
    obj: Any,
    key: Any,
) -> Any:
    """Access a key of an object, e.g. `obj[key]`"""
    # NOTE: Right now subscript uses the same logic as attribute
    if not is_safe_attribute(obj, key):
        raise SecurityError(f"key '{key}' on object '{type(obj)}' is unsafe")
    return obj[key]


# NOTE: Our internal args are prefixed with `__` to avoid keyword argument conflicts with the original input.
@error_context("call")
def call(
    __context: Mapping[str, Any],
    __source: str,
    __token: Tuple[int, int],
    func: Callable,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Call a function, e.g. `func(arg1, arg2, ...)`"""
    is_safe, replacement_message = is_safe_callable(func)
    if not is_safe:
        error_msg = f"function '{func!r}' is unsafe"
        if replacement_message:
            error_msg += f". {replacement_message}"
        raise SecurityError(error_msg)
    return func(*args, **kwargs)


@error_context("assign")
def assign(
    __context: Mapping[str, Any],
    __source: str,
    __token: Tuple[int, int],
    var_name: str,
    value: Any,
) -> Any:
    """Assign a value to a variable in the evaluation context, e.g. `(x := 5)`"""
    if not is_safe_variable(var_name):
        raise SecurityError(f"variable '{var_name}' is unsafe")
    __context[var_name] = value
    return value


# NOTE: We don't need to validate the slice arguments as they are always safe.
#       Slice had to be redefined from bracket syntax `obj[lower:upper:step]` to function call syntax
#       `slice(lower, upper, step)` because we convert brackets to function calls `subscript(obj, key)`.
#       But since we had to intercept it, this function ensures we show the correct position in the error message.
@error_context("slice")
def slice(
    __context: Mapping[str, Any],
    __source: str,
    __token: Tuple[int, int],
    lower: Any = None,
    upper: Any = None,
    step: Any = None,
) -> builtins.slice:
    """Create a slice object, e.g. `obj[lower:upper:step]`"""
    return builtins.slice(lower, upper, step)


# For compatiblity with Python 3.14+:
# - on 3.14+, t-strings are created as normal
# - on >=3.13, using t-strings raises an error
# See: https://docs.python.org/3.14/library/string.templatelib.html#template-strings
@error_context("interpolation")
def interpolation(
    __context: Mapping[str, Any],
    __source: str,
    __token: Tuple[int, int],
    value: Any,
    expression: str,
    conversion: Optional[str],
    format_spec: str,
) -> Any:
    """Process t-string interpolation."""
    try:
        from string.templatelib import Interpolation  # type: ignore[import-untyped]
    except ImportError:
        raise NotImplementedError("t-string interpolation is not supported")
    return Interpolation(value, expression, conversion, format_spec)


@error_context("template")
def template(__context: Mapping[str, Any], __source: str, __token: Tuple[int, int], *parts: Any) -> Any:
    """Construct a template from parts."""
    try:
        from string.templatelib import Template  # type: ignore[import-untyped]
    except ImportError:
        raise NotImplementedError("t-string template construction is not supported")
    return Template(*parts)


@error_context("format")
def format(
    __context: Mapping[str, Any],
    __source: str,
    __token: Tuple[int, int],
    template_string: str,
    *args: Any,
) -> str:
    """
    Format a template string with arguments.

    Each argument is a tuple (value, conversion_flag, format_spec) where:
    - value: The expression value to format
    - conversion_flag: "r", "s", "a", or None
    - format_spec: A string for static specs, or a tuple (template, *args) for dynamic specs

    This wraps the built-in str.format() method so that errors inside f-strings get nice
    error reporting with underlining via the `@error_context` decorator.
    """
    processed_args = []
    for value, conversion_flag, format_spec in args:
        # Apply conversion flag if present
        if conversion_flag == "r":
            value = repr(value)
        elif conversion_flag == "s":
            value = str(value)
        elif conversion_flag == "a":
            value = ascii(value)
        # If None, keep value as-is

        # Apply format spec if present (non-empty string or tuple)
        if format_spec:
            if isinstance(format_spec, tuple):
                # Dynamic format spec: (template, *args)
                spec_template, *spec_args = format_spec
                # Format the spec template with its args
                format_spec_str = spec_template.format(*spec_args)
            else:
                # Static format spec: already a string
                format_spec_str = format_spec

            # Only apply format spec if it's non-empty
            if format_spec_str:
                value = builtins.format(value, format_spec_str)

        processed_args.append(value)

    return template_string.format(*processed_args)
