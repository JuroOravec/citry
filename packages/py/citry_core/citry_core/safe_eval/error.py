import functools
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T", bound=Callable)


def format_error_with_context(
    error: Exception,
    source: str,
    start_index: int,
    end_index: int,
    func_name: str,
    add_prefix: bool = True,
) -> None:
    """
    Format an error with underlined source code context.

    Modifies the exception's message to include:
    - Up to 2 preceding lines
    - The lines containing the error (start_index to end_index)
    - Up to 2 following lines
    - Underlined code with ^^^ characters

    Example:
    ```
    (a := 1 + my_var)
              ^^^^^^
    NameError: name 'my_var' is not defined
    ```

    """
    # Convert source to lines with line numbers
    lines = source.split("\n")

    # Find which lines contain the error
    line_starts = [0]  # Cumulative character count at start of each line
    for line in lines[:-1]:
        line_starts.append(line_starts[-1] + len(line) + 1)  # +1 for newline

    # Find start and end line numbers (0-indexed)
    start_line = 0
    for i, line_start in enumerate(line_starts):
        if line_start > start_index:
            start_line = max(0, i - 1)
            break
    else:
        start_line = len(lines) - 1

    end_line = start_line
    for i, line_start in enumerate(line_starts):
        if line_start > end_index:
            end_line = max(0, i - 1)
            break
    else:
        end_line = len(lines) - 1

    # Calculate column positions within each line
    def get_column(line_num: int, char_index: int) -> int:
        """Get column number (0-indexed) for a character index in a specific line."""
        if line_num >= len(line_starts):
            return 0
        line_start = line_starts[line_num]
        return max(0, char_index - line_start)

    start_col = get_column(start_line, start_index)
    end_col = get_column(end_line, end_index)

    # Collect lines to show (up to 2 before and 2 after)
    show_start = max(0, start_line - 2)
    show_end = min(len(lines), end_line + 3)  # +3 because end is inclusive

    # Build the formatted error message
    error_lines = []
    if add_prefix:
        error_lines.append(f"Error in {func_name}: {type(error).__name__}: {error}")
    elif len(error.args) and error.args[0] is not None:
        # Just use the original error message. Read it from `args` when
        # possible: `str(error)` re-quotes the message for exceptions like
        # KeyError (whose __str__ is the repr of its argument), which garbles
        # a message that was already rewritten to a multi-line string.
        error_lines.append(str(error.args[0]))
    else:
        error_lines.append(str(error))
    error_lines.append("")

    # Add source lines with line numbers
    for line_num in range(show_start, show_end):
        line_content = lines[line_num]
        line_display_num = line_num + 1  # 1-indexed for display

        # Calculate underline range for this line
        underline_start = 0
        underline_end = len(line_content)

        if line_num == start_line == end_line:
            # Error spans single line
            underline_start = start_col
            underline_end = min(len(line_content), end_col)
        elif line_num == start_line:
            # Error starts on this line
            underline_start = start_col
            underline_end = len(line_content)
        elif line_num == end_line:
            # Error ends on this line
            underline_start = 0
            underline_end = min(len(line_content), end_col)
        elif start_line < line_num < end_line:
            # Error spans this entire line
            underline_start = 0
            underline_end = len(line_content)
        else:
            # No error on this line, don't underline
            underline_start = -1
            underline_end = -1

        # Add line with number
        line_prefix = f"  {line_display_num:4d} | "
        error_lines.append(line_prefix + line_content)

        # Add underline if error is on this line
        if underline_start >= 0:
            # Create underline: prefix spaces + spaces to column + ^ characters
            prefix_len = len(line_prefix)  # "    4 | " = 9 characters
            underline = " " * (prefix_len + underline_start) + "^" * max(1, underline_end - underline_start)
            error_lines.append(underline)

    # Update exception message
    error.args = ("\n".join(error_lines),)
    # Mark that this error has been processed by error_context
    error._error_processed = True  # type: ignore[attr-defined]


def error_context(func_name: str) -> Callable[[T], T]:
    """
    Decorator that wraps functions to add error context reporting.

    Extracts token tuple (start_index, end_index) from the third positional argument,
    and on error, formats the error with underlined source code.
    """

    def decorator(func: T) -> T:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Functions that use this decorator have signature
            # (context: Mapping[str, Any], source: str, token: tuple[int, int], *args: Any, **kwargs: Any) -> Any
            source = args[1]
            start_index, end_index = args[2]

            try:
                # On success return result normally
                return func(*args, **kwargs)
            except Exception as e:
                # On error, modify the error message to include the source code context
                format_error_with_context(e, source, start_index, end_index, func_name)
                raise

        return wrapper

    return decorator
