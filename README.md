# Citry - Refreshingly elegant templating

Citry is a templating engine that brings the best of **Vue**, **React**, **Django**, and **Jinja** to every language.

Use the same Vue-like API to write templates everywhere - **Python**, **JS/TS**, **PHP**, **Go**, or **Rust**:

```html
<c-Card title="Welcome" c-class="card_classes">
  <c-fill name="body">
    <c-for each="item in items">
      <c-Item c-data="item" />
    </c-for>
  </c-fill>
  <c-fill name="footer">
    <button c-disabled="is_loading">Submit</button>
  </c-fill>
</c-Card>
```

## Why Citry?

Use Citry to build UI, HTML, XML, SVG, or anything that serializes to text.

Citry is:

- **Familiar** - If you know HTML and Vue/React, you're ready
- **Simple** - Just 2 rules and 12 special tags
- **Fast** - Rust-powered parsing
- **Safe** - Expressions are sandboxed to block dangerous operations
- **Reliable** - Typo'd slot names and missing props fail when the template
  is compiled, with a precise source location - not at render time in
  production
- **Universal** - One template language for your entire stack

## Two simple rules

Citry extends HTML with just **two rules**:

1. **`<c-*>` tags are components** - Any tag starting with `c-` is a component (or special tag)
2. **`c-*` attributes are dynamic** - Any attribute starting with `c-` evaluates as an expression

That's it. If you know HTML, you already know 90% of Citry.

```html
<!-- Static HTML attribute -->
<div class="container">
  <!-- Dynamic attribute (expression) -->
  <div c-class="dynamic_classes">
    <!-- Your component -->
    <c-MyComponent title="Hello"></c-MyComponent>
  </div>
</div>
```

## 12 special tags

Beyond custom components, Citry provides **13 built-in tags** for common patterns.

With just these 13 tags, Citry is as versatile as Vue or React:

| Tag               | Purpose                                | Example                                              |
| ----------------- | -------------------------------------- | ---------------------------------------------------- |
| **Control flow:** |                                        |                                                      |
| `<c-if>`          | Conditional rendering                  | `<c-if cond="is_visible">...</c-if>`                 |
| `<c-elif>`        | Else-if branch                         | `<c-elif cond="is_other">...</c-elif>`               |
| `<c-else>`        | Else branch                            | `<c-else>...</c-else>`                               |
| `<c-for>`         | Loop iteration                         | `<c-for each="item in items">...</c-for>`            |
| `<c-empty>`       | Empty state for loops                  | `<c-empty>No items</c-empty>`                        |
| **Components:**   |                                        |                                                      |
| `<c-slot>`        | Define insertion point                 | `<c-slot name="header" />`                           |
| `<c-fill>`        | Fill a slot                            | `<c-fill name="header">...</c-fill>`                 |
| `<c-component>`   | Dynamic component                      | `<c-component c-is="comp_name" />`                   |
| `<c-element>`     | Dynamic HTML element                   | `<c-element c-is="tag_name">...</c-element>`         |
| **Misc:**         |                                        |                                                      |
| `<c-provide>`     | Dependency injection (ContextProvider) | `<c-provide key="theme" mode="dark">...</c-provide>` |
| `<c-css>`         | Render components' CSS here            | `<c-css />`                                          |
| `<c-js>`          | Render components' JS here             | `<c-js />`                                           |
| `<c-raw>`         | Unprocessed content                    | `<c-raw>{{ not evaluated }}</c-raw>`                 |

## Vue-like shortcuts `c-if` and `c-for`

Control flow can also be written as attributes on regular elements:

**If / elif / else:**

```html
<!-- As tags -->
<c-if cond="is_visible">
  <div class="panel">Content</div>
</c-if>
<c-elif cond="is_admin">
  <div class="panel">Other content</div>
</c-if>
<c-else>
  <c-Login />
</c-if>

<!-- As attributes (shorter!) -->
<div c-if="is_visible" class="panel">Content</div>
<div c-elif="is_admin" class="panel">Other content</div>
<c-Login c-else />
```

**For / empty:**

```html
<!-- Loops work the same way -->
<ul>
  <li c-for="item in items">{{ item.name }}</li>
  <li c-empty>No items found</li>
</ul>
```

## Template expressions

Use `{{ }}` to embed expressions anywhere in the text.

The expression inside `{{ }}` is written in your host language:

```html
<!-- Python -->
<p>{{ len(items) }} items</p>
<p>total: {{ sum(item.price for item in items) }}</p>

<!-- JavaScript -->
<p>{{ items.length }} items</p>
<p>total: {{ items.reduce((a, b) => a + b.price, 0) }}</p>

<!-- PHP -->
<p>{{ count($items) }} items</p>
<p>total: {{ array_sum(array_column($items, 'price')) }}</p>

<!-- Result: -->
<p>3 items</p>
<p>total: 60</p>
```

## Dynamic attributes

To dynamically compute a tag attribute, prefix it with `c-`.

The attribute value is then treated as an expression (same as inside `{{ }}`).

The `c-` prefix is stripped from the rendered attribute.

Just like `{{ }}`, the expression inside is written in your host language:

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

A `True` value renders the attribute bare (`disabled` above); `False` and `None` omit the attribute entirely.

## Class and style attributes

`class` and `style` accept structured values (like Vue), so you can compute them without string concatenation:

```html
<!-- Input (is_active = True, color = "red") -->
<div c-class="['btn', { 'active': is_active, 'hidden': False }]"></div>
<div c-style="{ 'color': color, 'background-color': 'blue' }"></div>

<!-- Result: -->
<div class="btn active"></div>
<div style="color: red; background-color: blue;"></div>
```

- `class` may be a plain string, a dict of `{ class_name: enabled }` (a falsy value drops the class), or a list mixing strings, dicts, and nested lists.
- `style` may be an inline CSS string, a dict of `{ css_property: value }` (write property names as CSS spells them, e.g. `background-color`), or a list of those. In a merge, a `None` value lets an earlier value stand, while `False` removes the property entirely.

When one element gets `class` or `style` from several places (a static attribute, `c-class`/`c-style`, or a `c-bind` spread), the values **merge** instead of overwriting each other - see [Attribute spreading](#attribute-spreading).

The same rules are available in Python as `merge_attrs` and `format_attrs` (`from citry import merge_attrs, format_attrs`) for building attribute dicts in your component code.

## Nested templates

Dynamic `c-*` attributes can contain nested templates instead of expressions.

Simply write the HTML inside the quotes:

```html
<c-Card
  title="My Card"
  c-footer="
    <footer>
      <p>Made with ❤️</p>
    </footer>
  "
/>
```

The nested template must have a single root tag. To pass plain text or multiple root elements,
wrap them in `<>` and `</>` (React-style fragments):

```html
<c-Card
  c-body="<>
    <p>First paragraph</p>
    <p>Second paragraph</p>
  </>"
  c-footer="<>Just some text</>"
/>
```

## Attribute spreading

Use `c-bind` to spread a dictionary of attributes onto an element:

```html
<!-- Input (item.id = 123) -->
<div c-bind="{ 'class': 'btn', 'disabled': True, 'data-id': item.id }"></div>

<!-- Result: -->
<div class="btn" disabled data-id="123"></div>
```

You can use `c-bind` multiple times and interlace it with regular or dynamic attributes. Attributes are applied **left to right** - in case of duplicates, the last one wins:

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

The two exceptions are `class` and `style`: their values from all sources **merge** instead, so a spread can add classes without wiping out the element's own (see [Class and style attributes](#class-and-style-attributes)):

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

## Component slots

Citry supports a Vue-like slot system. This consists of 2 parts:

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

2. When using the component inside another template, pass content to slots with `<c-fill>`:

   ```html
   <!-- Using a component with named slots -->
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

Slots can also be marked as required, causing an error if no `<c-fill>` is provided.

```html
<c-slot name="actions" required />
```

### Slot fallback

When you pass a `<c-fill>` to a component, the `<c-slot>` renders
the provided fill in its place.

When there is no `<c-fill>` for the corresponding `<c-slot>`, it will render
the body within the `<c-slot> ... </c-slot>` tags as a fallback.

```html
<!-- Button.html -->
<button>
  <c-slot>Click me</c-slot>
</button>

<!-- Usage without fill (renders fallback): -->
<c-Button />
<!-- Result: <button>Click me</button> -->

<!-- Usage with fill (renders fill): -->
<c-Button>Submit</c-Button>
<!-- Result: <button>Submit</button> -->
```

### Slot shortcut

When passing only content to the default slot, you can omit `<c-fill>`:

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

### Accessing slot data and fallback

Slots can expose data to the fill, similar to Vue's scoped slots.

**1. Passing data from `<c-slot>`** - Any extra attributes on `<c-slot>` become slot data:

```html
<!-- UserList.html -->
<c-for each="user in users">
  <c-slot name="item" c-user="user" c-index="loop.index" />
</c-for>
```

**2. Accessing data in `<c-fill>`** - Use the `data` attribute to bind slot data to a variable:

```html
<c-UserList c-users="users">
  <c-fill name="item" data="slot">
    <div>{{ slot.index }}: {{ slot.user.name }}</div>
  </c-fill>
</c-UserList>
```

**3. Accessing slot fallback** - Use the `fallback` attribute to access the slot's fallback content:

```html
<!-- Component template with fallback slot content -->
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

## Typed components catch errors early

A component can declare its inputs with plain annotated classes:

```python
from citry import Component, SlotInput

class Card(Component):
    template = '<div>{{ title }}<c-slot name="header" /></div>'

    class Kwargs:
        title: str          # required
        size: int = 10      # optional

    class Slots:
        header: SlotInput
```

The declarations double as a contract for every template that **uses** the
component. Mistakes fail when the template is compiled, pointing at the exact
spot in the template source, instead of surfacing at render time (or not at
all):

```html
<!-- Each of these is a template compile error: -->
<c-Card title="Hi" bogus="1" />          <!-- unknown prop -->
<c-Card />                               <!-- missing required `title` -->
<c-Card title="Hi">
  <c-fill name="headr">...</c-fill>      <!-- typo'd slot name -->
</c-Card>
```

This is possible because fills and props are part of the template's
structure, not strings resolved mid-render. Dynamic usage stays flexible:
`c-bind` spreads and dynamic slot names (`c-name`) are checked at render
time instead.

## Comments

Citry supports three types of comments:

**1. HTML comments** - Preserved in the rendered output:

```html
<!-- This comment will appear in the final HTML -->
<div>Content</div>
```

**2. Template comments** - Stripped from output entirely:

```jinja
{# This comment won't appear in the rendered HTML #}
<div>Content</div>
```

**3. Expression comments** - Language-specific comments inside `{{ }}` or `c-*` attributes:

```html
<!-- Python example -->
<div c-class="get_classes()  # Fetch dynamic classes">
  {{ user.name # Display username }}
</div>
```

## Multi-language support

The expressions inside Citry templates (inside `{{ }}` and `c-*`) are language-specific.

E.g. when you download the `citry` Python package, the expressions will be Python code:

```html
<div>
   {{ len(user.items) if user.logged_in else 0 }}
</div>
```

Citry is designed to integrate with any programming language within its expressions.

This means that the same Citry package can be released for any programming languages.

**Progress on supported languages:**

| Language   | Status | Integration  |
| ---------- | ------ | ------------ |
| **Python** | ✅     | PyO3/maturin |
| **JS/TS**  | ❌     | wasm-bindgen |
| **PHP**    | ❌     | FFI          |
| **Go**     | ❌     | cgo          |
| **Rust**   | ❌     | Native       |

Help us implement Citry package for your language!

Star this repo to follow development.

## Installation

### Python

```sh
pip install citry
```

## Documentation

For development setup and codebase details, see [`docs/codebase.md`](./docs/codebase.md).

## License

MIT License - see [LICENSE](./LICENSE) for details.

## Acknowledgments

This project is the continuation of work originally done in [django-components](https://github.com/django-components/django-components) and [django-components/djc-core](https://github.com/django-components/djc-core).
