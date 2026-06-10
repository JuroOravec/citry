"""
Turn a rendered ``CitryRender`` tree into final HTML, tagging each component's
root element(s) with a ``data-cid-<id>`` marker.

This is the serialize half of the pipeline: rendering builds the
``CitryRender`` tree, and this turns it into a string. Each component's HTML
gets a marker attribute on its root element(s), so the browser can tell which
component rendered which part of the page. When one component's root element is
itself another component, that element carries both markers, e.g.
``<div data-cid-child="" data-cid-parent="">``.

It works in two passes, and neither pass calls itself, so a deeply nested page
does not run into Python's recursion limit (the same reason the render side uses
a queue):

1. Top-down: for each component, build its own HTML with its child components
   left as ``<template c-render-id="...">`` placeholders, then call
   ``transform_html`` once to add the markers to that component's root
   element(s). ``transform_html`` also reports which child placeholders ended up
   at the root; those children inherit the parent's markers (that is how a
   parent's marker reaches a child that is its root element).
2. Bottom-up: replace each placeholder with the child's finished HTML.

See docs/design/deferred_rendering.md section 6.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from citry.citry_render import CitryRender
from citry_core.html_transform import transform_html

if TYPE_CHECKING:
    from citry.citry_render import RenderPart
    from citry.component import Component

# The attribute name the placeholder carries, and that transform_html watches so
# it can report which markers were added to each child placeholder.
_RENDER_ID_ATTR = "c-render-id"

# Matches a child placeholder element, e.g.
# `<template c-render-id="cAb3d9"></template>` or, after transform_html has added
# the parent's markers to it, `<template c-render-id="cAb3d9" data-cid-cP=""></template>`.
# Any extra attributes around c-render-id are allowed.
_PLACEHOLDER_RE = re.compile(
    r'<template\b[^>]*?\bc-render-id="(?P<cid>[^"]+)"[^>]*?>\s*</template>',
)


def serialize_render(root: CitryRender) -> str:
    """Serialize a render tree to HTML, adding ``data-cid-<id>`` markers (see module doc)."""
    # Pass 1 (top-down): build each component's HTML with its children still as
    # placeholders, add its markers, and work out which markers each child
    # inherits. An explicit stack keeps depth off the Python call stack.
    #
    # `marked_by_key` holds each component's HTML (children still placeholders),
    # keyed by the component's render id. `order` records the order components
    # were reached, so pass 2 can walk it in reverse (children before parents).
    # The root has no parent and may have no component, so it uses the key "".
    marked_by_key: dict[str, str] = {}
    order: list[str] = []
    root_key = ""

    # Each stack item is (render, markers_inherited_from_parent, key).
    stack: list[tuple[CitryRender, list[str], str]] = [(root, [], root_key)]
    while stack:
        render, inherited, key = stack.pop()
        component = render.context.component

        children: list[tuple[CitryRender, str]] = []
        frame = _build_frame(render, component, children)

        # A render only gets its component's marker when it is that component's
        # root render; a transparent component's output (is_component_root
        # False, e.g. <c-provide>) stays unmarked even when serialized directly.
        own_marker = [f"data-cid-{component.id}"] if component is not None and render.is_component_root else []
        root_markers = own_marker + inherited
        if root_markers and frame:
            frame, added_to_child = transform_html(frame, root_markers, [], None, _RENDER_ID_ATTR)
        else:
            # No markers to add (a render with no component, e.g. a manually
            # built CitryRender), or an empty frame: nothing to transform.
            added_to_child = {}

        marked_by_key[key] = frame
        order.append(key)
        for child_render, child_id in children:
            stack.append((child_render, added_to_child.get(child_id, []), child_id))

    # Pass 2 (bottom-up): replace each child placeholder with the child's
    # finished HTML. Walking `order` in reverse means a child is finished before
    # its parent needs it.
    finished: dict[str, str] = {}

    def fill_placeholder(match: re.Match[str]) -> str:
        # An unknown id (a literal <template c-render-id> a user wrote) is left as-is.
        return finished.get(match.group("cid"), match.group(0))

    for key in reversed(order):
        finished[key] = _PLACEHOLDER_RE.sub(fill_placeholder, marked_by_key[key])

    return finished[root_key]


def _build_frame(
    render: CitryRender,
    component: Component | None,
    children: list[tuple[CitryRender, str]],
) -> str:
    """
    Join one component's parts into an HTML string.

    Plain text passes through. A nested render that is another component's
    completed root render (``is_component_root``) is a child component: it
    becomes a ``<template c-render-id="...">`` placeholder, recorded in
    ``children`` for pass 2 to fill in. Every other nested render joins in
    directly: ``<c-if>``/``<c-for>`` blocks and nested templates (same
    component), and slot-fill content (which carries the context of the
    component that *wrote* the fill, but renders as part of this frame).
    Walking the joined-in blocks only follows the template's own nesting, so it
    does not recurse deeply.
    """
    out: list[str] = []

    def walk(parts: list[RenderPart]) -> None:
        for part in parts:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, CitryRender):
                part_component = part.context.component
                if part.is_component_root and part_component is not None and part_component is not component:
                    # Another component's whole output: leave a placeholder for pass 2.
                    out.append(f'<template c-render-id="{part_component.id}"></template>')
                    children.append((part, part_component.id))
                else:
                    # Interior content (control flow, nested template, slot-fill
                    # content) or a component-less render: join in directly.
                    walk(part.parts)
            else:
                # A DeferredComponent here means render() never resolved it.
                # RuntimeError (not TypeError): the render is unfinished, nothing
                # was given the wrong type.
                msg = "unresolved DeferredComponent at serialize(); render() must process the queue first"
                raise RuntimeError(msg)  # noqa: TRY004

    walk(render.parts)
    return "".join(out)
