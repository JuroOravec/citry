# Template syntax reference

This is the full reference for Citry's template syntax. For a five-minute
introduction, see the [README](../README.md) quickstart; this document goes
deeper into every feature.

The examples use Python, since that is the language Citry ships for today. The
syntax is the same in every language Citry targets; only the code inside
`{{ }}` and `c-*` attributes changes (see
[Multi-language expressions](#multi-language-expressions)).

## Contents

- [The two rules](#the-two-rules)
- [Template expressions](#template-expressions)
- [Dynamic attributes](#dynamic-attributes)
- [Class and style attributes](#class-and-style-attributes)
- [Control flow](#control-flow)
- [Component slots](#component-slots)
- [Nested templates in attributes](#nested-templates-in-attributes)
- [Attribute spreading](#attribute-spreading)
- [Comments](#comments)
- [Built-in tags](#built-in-tags)
- [Multi-language expressions](#multi-language-expressions)

## The two rules

Citry extends HTML with two rules:

1. **`<c-*>` tags are components.** Any tag whose name starts with `c-` is a
   component or one of the built-in tags.
2. **`c-*` attributes are dynamic.** Any attribute whose name starts with `c-`
   has its value evaluated as an expression. The `c-` prefix is stripped from
   the rendered attribute.

```html
<!-- Static HTML attribute -->
<div class="container">
  <!-- Dynamic attribute (evaluated as an expression) -->
  <div c-class="dynamic_classes">
    <!-- A component -->
    <c-MyComponent title="Hello"></c-MyComponent>
  </div>
</div>
```

If you know HTML, you already know most of Citry.

## Template expressions

Use `{{ }}` to embed an expression anywhere in the text. The expression is
written in your host language and can read and combine the values you pass in:
attribute access, arithmetic, comparisons, indexing, slicing, conditional
expressions, and method calls on those values.

```html
<p>{{ user.name }}</p>
<p>{{ price * quantity }}</p>
<p>{{ greeting + ', ' + user.name }}</p>
<p>{{ user.name.upper() }}</p>
<p>{{ 'Member' if user.is_active else 'Guest' }}</p>
<p>{{ items[0] }}</p>
```

### Compute derived values in your component, not in the template

Template expressions cannot reach language builtins. A natural first attempt
like this fails:

```html
<!-- Renders an error: the name `len` is not available in expressions -->
<p>{{ len(items) }} items</p>
```

You will see `KeyError: 'len'`, with a caret pointing at `len` in the
template. The fix is to compute the value in `template_data` (plain Python,
where every builtin is available) and pass the result in:

```python
class Cart(Component):
    template = """
      <p>{{ count }} items</p>
    """

    def template_data(self, kwargs, slots=None):
        return {"count": len(kwargs["items"])}
```

This keeps templates declarative: they display values, and your component code
prepares them.

## Dynamic attributes

To compute an attribute value, prefix the attribute with `c-`. The value is
evaluated as an expression (the same rules as inside `{{ }}`), and the `c-`
prefix is stripped from the rendered attribute.

```html
<!-- Input (button_type = "primary", is_loading = True) -->
<div c-class="'btn ' + button_type">
  <button c-disabled="is_loading">Submit</button>
</div>

<!-- Result: -->
<div class="btn primary">
  <button disabled>Submit</button>
</div>
```

Boolean-style attributes follow HTML conventions:

- A `True` value renders the attribute bare (`disabled` above).
- A `False` or `None` value omits the attribute entirely.

## Class and style attributes

`class` and `style` accept structured values (like Vue), so you can compute
them without string concatenation:

```html
<!-- Input (is_active = True, color = "red") -->
<div c-class="['btn', { 'active': is_active, 'hidden': False }]"></div>
<div c-style="{ 'color': color, 'background-color': 'blue' }"></div>

<!-- Result: -->
<div class="btn active"></div>
<div style="color: red; background-color: blue;"></div>
```

- `class` may be a plain string, a dict of `{ class_name: enabled }` (a falsy
  value drops the class), or a list mixing strings, dicts, and nested lists.
- `style` may be an inline CSS string, a dict of `{ css_property: value }`
  (write property names as CSS spells them, e.g. `background-color`), or a list
  of those. In a merge, a `None` value lets an earlier value stand, while
  `False` removes the property entirely.

When one element gets `class` or `style` from several places (a static
attribute, `c-class` / `c-style`, or a `c-bind` spread), the values **merge**
instead of overwriting each other (see [Attribute spreading](#attribute-spreading)).

The same rules are available in Python as `merge_attrs` and `format_attrs`
(`from citry import merge_attrs, format_attrs`) for building attribute dicts in
your component code.

## Control flow

### If / elif / else

Write conditional branches as tags. Each branch closes its own tag, and the
branches must be adjacent siblings:

```html
<c-if cond="is_visible">
  <div class="panel">Content</div>
</c-if>
<c-elif cond="is_admin">
  <div class="panel">Admin content</div>
</c-elif>
<c-else>
  <c-Login />
</c-else>
```

The same logic can be written as attributes on regular elements, which is
shorter:

```html
<div c-if="is_visible" class="panel">Content</div>
<div c-elif="is_admin" class="panel">Admin content</div>
<c-Login c-else />
```

### For / empty

Loop with `<c-for>`, and supply an empty state with `<c-empty>`:

```html
<ul>
  <li c-for="item in items">{{ item.name }}</li>
  <li c-empty>No items found</li>
</ul>
```

The tag form works too:

```html
<c-for each="item in items">
  <c-Item c-data="item" />
</c-for>
<c-empty>
  <p>No items found</p>
</c-empty>
```

## Component slots

Citry has a Vue-like slot system with two parts.

1. Inside the component template, define insertion points with `<c-slot>`:

   ```html
   <!-- Modal.html -->
   <div class="modal">
     <header>{{ title }}</header>
     <main>
       <c-slot />
     </main>
     <footer>
       <c-slot name="actions" />
     </footer>
   </div>
   ```

2. When using the component, pass content to slots with `<c-fill>`:

   ```html
   <c-Modal title="Confirm">
     <c-fill name="default">
       <p>Are you sure?</p>
     </c-fill>

     <c-fill name="actions">
       <button>Cancel</button>
       <button>Confirm</button>
     </c-fill>
   </c-Modal>
   ```

If you omit the `name` attribute on `<c-slot>`, it defaults to `"default"`.

A slot can be marked `required`, which raises an error if no matching
`<c-fill>` is provided and the slot actually renders:

```html
<c-slot name="actions" required />
```

### Slot fallback

When a `<c-fill>` is provided, the `<c-slot>` renders it. When there is no
matching fill, the slot renders its own body as a fallback:

```html
<!-- Button.html -->
<button>
  <c-slot>Click me</c-slot>
</button>

<!-- Usage without a fill renders the fallback: -->
<c-Button />
<!-- Result: <button>Click me</button> -->

<!-- Usage with a fill renders the fill: -->
<c-Button>Submit</c-Button>
<!-- Result: <button>Submit</button> -->
```

### Default slot shortcut

When you only pass content to the default slot, you can omit `<c-fill>`:

```html
<!-- These are equivalent: -->
<c-Modal title="Confirm">
  <c-fill name="default">
    <p>Are you sure?</p>
  </c-fill>
</c-Modal>

<c-Modal title="Confirm">
  <p>Are you sure?</p>
</c-Modal>
```

### Passing data to a fill (scoped slots)

A slot can expose data to its fill, like Vue's scoped slots.

Any extra attributes on `<c-slot>` become slot data:

```html
<!-- UserList.html -->
<c-for each="user in users">
  <c-slot name="item" c-user="user" c-index="loop.index" />
</c-for>
```

The fill reads that data by binding it to a variable with the `data`
attribute:

```html
<c-UserList c-users="users">
  <c-fill name="item" data="slot">
    <div>{{ slot.index }}: {{ slot.user.name }}</div>
  </c-fill>
</c-UserList>
```

A fill can also wrap the slot's own fallback content. Bind it with the
`fallback` attribute:

```html
<!-- Component template with fallback content -->
<c-slot name="title">
  <h1>Fallback Title</h1>
</c-slot>

<!-- Usage: wrap the fallback with extra markup -->
<c-MyComponent>
  <c-fill name="title" fallback="fallback">
    <div class="custom-wrapper">{{ fallback }}</div>
  </c-fill>
</c-MyComponent>
```

## Nested templates in attributes

A dynamic `c-*` attribute can hold a nested template instead of an expression.
Write the HTML inside the quotes, and Citry renders it as a template:

```html
<c-Card
  title="My Card"
  c-footer="
    <footer>
      <p>Made with care</p>
    </footer>
  "
/>
```

A nested template must have a single root tag. To pass plain text or several
root elements, wrap them in `<>` and `</>` (React-style fragments):

```html
<c-Card
  c-body="<>
    <p>First paragraph</p>
    <p>Second paragraph</p>
  </>"
  c-footer="<>Just some text</>"
/>
```

Citry decides between an expression and a nested template by looking at the
value: a value that starts with `<tag` and ends with `</tag>` (or is wrapped in
`<>...</>`) is a template, and everything else is an expression.

## Attribute spreading

Use `c-bind` to spread a dict of attributes onto an element:

```html
<!-- Input (item.id = 123) -->
<div c-bind="{
  'class': 'btn',
  'disabled': True,
  'data-id': item.id,
}"></div>

<!-- Result: -->
<div class="btn" disabled data-id="123"></div>
```

You can use `c-bind` several times and interleave it with regular or dynamic
attributes. Attributes apply left to right, so for duplicates the last one
wins:

```html
<!-- Input -->
<div
  id="default"
  c-bind="{ 'id': 'first', 'title': 'Hi' }"
  c-id="'override'"
></div>

<!-- Result (last value for each attribute wins): -->
<div id="override" title="Hi"></div>
```

`class` and `style` are the exceptions: their values from every source merge,
so a spread can add classes without wiping out the element's own (see
[Class and style attributes](#class-and-style-attributes)):

```html
<!-- Input -->
<div
  class="default"
  c-bind="{ 'class': 'from-bind', 'id': 'first' }"
  c-class="'override'"
  c-bind="{ 'id': 'second' }"
></div>

<!-- Result (classes merge, id keeps the last value): -->
<div class="default from-bind override" id="second"></div>
```

## Comments

Citry supports three kinds of comment.

**HTML comments** are preserved in the rendered output:

```html
<!-- This comment appears in the final HTML -->
<div>Content</div>
```

**Template comments** are stripped from the output entirely:

```jinja
{# This comment never appears in the rendered HTML #}
<div>Content</div>
```

**Expression comments** are host-language comments inside `{{ }}` or a `c-*`
attribute:

```html
<div c-class="get_classes()  # fetch dynamic classes">
  {{ user.name  # display username }}
</div>
```

## Built-in tags

Beyond your own components, Citry provides 13 built-in tags. With these, Citry
is as expressive as Vue or React.

| Tag             | Purpose                                  |
| --------------- | ---------------------------------------- |
| `<c-if>`        | Conditional branch                       |
| `<c-elif>`      | Else-if branch                           |
| `<c-else>`      | Else branch                              |
| `<c-for>`       | Loop over an iterable                    |
| `<c-empty>`     | Empty state for a `<c-for>` loop         |
| `<c-slot>`      | Define a content insertion point         |
| `<c-fill>`      | Fill a slot when using a component        |
| `<c-component>` | Render a component chosen at render time |
| `<c-element>`   | Render an HTML element whose tag name is chosen at render time |
| `<c-provide>`   | Provide a value to descendant components |
| `<c-css>`       | Render the collected component CSS here  |
| `<c-js>`        | Render the collected component JS here   |
| `<c-raw>`       | Treat the contents as literal text       |

The dynamic `<c-component>` and `<c-element>` tags pick their target at render
time:

```html
<!-- Render whichever component `widget` names -->
<c-component c-is="widget" />

<!-- Render whichever HTML element `tag_name` names -->
<c-element c-is="tag_name">content</c-element>
```

## Multi-language expressions

The code inside `{{ }}` and `c-*` attributes is written in the host language,
so the same template renders in any language Citry ships for. Only the
expressions change:

```html
<!-- Python -->
<p>total: {{ order.total }}</p>

<!-- JavaScript -->
<p>total: {{ order.total }}</p>

<!-- PHP -->
<p>total: {{ $order->total }}</p>
```

Python is the language Citry ships today. See the
[language support table](../README.md#language-support) in the README for the
status of the others.
