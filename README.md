# Citry - Refreshingly elegant templating

Citry is a templating engine that brings the best of **Vue**, **React**,
**Django**, and **Jinja** to every language.

Use the same Vue-like component syntax to write templates everywhere -
**Python**, **JS/TS**, **PHP**, **Go**, or **Rust**:

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

- **Familiar** - if you know HTML and Vue/React, you are ready
- **Simple** - just 2 rules and 13 built-in tags
- **Fast** - Rust-powered parsing
- **Safe** - expressions are sandboxed to block dangerous operations
- **Reliable** - typos and missing props fail at compile time, not in production
- **Universal** - one template language for your entire stack

## Quickstart

Citry ships for Python today.

```sh
pip install citry
```

Define a component by subclassing `Component` and giving it a `template`. Use
`template_data` to prepare the values the template reads. Render it by turning
the component into a string:

```python
from citry import Component

class Welcome(Component):
    template = """
      <div class="card">
        <h1>{{ title }}</h1>
        <p>You have {{ count }} new messages.</p>
      </div>
    """

    # template_data prepares the values your template can read.
    # Run any computation here, in plain Python.
    def template_data(self, kwargs, slots=None):
        return {
            "title": kwargs["title"],
            "count": len(kwargs["messages"]),
        }

component = Welcome(
    title="Welcome back",
    messages=["a", "b", "c"],
)
html = str(component)
```

`html` is now:

```html
<div class="card">
  <h1>Welcome back</h1>
  <p>You have 3 new messages.</p>
</div>
```

Components compose by name. A `<c-Welcome>` tag renders the `Welcome` class.
Pass dynamic props with the `c-` prefix and static ones without:

```python
class Page(Component):
    template = """
      <main>
        <c-Welcome c-title="user.name" c-messages="user.inbox" />
      </main>
    """

    def template_data(self, kwargs, slots=None):
        return {"user": kwargs["user"]}
```

## Two simple rules

Citry extends HTML with two rules:

1. **`<c-*>` tags are components** - any tag starting with `c-` is a component
   or a built-in tag.
2. **`c-*` attributes are dynamic** - any attribute starting with `c-` is
   evaluated as an expression, and the `c-` prefix is stripped from the output.

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

## Built-in tags

Beyond your own components, Citry provides 13 built-in tags. With these, Citry
is as expressive as Vue or React.

| Tag             | Purpose                                                       |
| --------------- | ------------------------------------------------------------- |
| `<c-if>`        | Conditional branch                                            |
| `<c-elif>`      | Else-if branch                                                |
| `<c-else>`      | Else branch                                                   |
| `<c-for>`       | Loop over an iterable                                         |
| `<c-empty>`     | Empty state for a `<c-for>` loop                              |
| `<c-slot>`      | Define a content insertion point                             |
| `<c-fill>`      | Fill a slot when using a component                            |
| `<c-component>` | Render a component chosen at render time                     |
| `<c-element>`   | Render an HTML element whose tag name is chosen at render time |
| `<c-provide>`   | Provide a value to descendant components                     |
| `<c-css>`       | Render the collected component CSS here                      |
| `<c-js>`        | Render the collected component JS here                       |
| `<c-raw>`       | Treat the contents as literal text                           |

## How templates look

A short tour. The [template syntax reference](docs/template-syntax.md) covers
every feature in depth.

**Expressions** with `{{ }}`, written in your host language:

```html
<p>{{ user.name }}</p>
<p>{{ 'Member' if user.is_active else 'Guest' }}</p>
```

**Dynamic attributes** with the `c-` prefix. A `True` value renders the
attribute bare, `False` or `None` omits it:

```html
<button
  c-disabled="is_loading"
  c-class="['btn', { 'active': is_open }]"
>
  Submit
</button>
```

**Control flow** as tags or as attributes on a regular element:

```html
<ul>
  <li c-for="item in items">{{ item.name }}</li>
  <li c-empty>No items found</li>
</ul>

<c-if cond="is_admin">
  <p>Admin</p>
</c-if>
<c-else>
  <p>Guest</p>
</c-else>
```

**Slots** let a component accept content from its caller. Define insertion
points with `<c-slot>`, and fill them with `<c-fill>`:

```html
<!-- Modal.html -->
<div class="modal">
  <header>{{ title }}</header>
  <main><c-slot /></main>
</div>

<!-- Using the component -->
<c-Modal title="Confirm">
  <p>Are you sure?</p>
</c-Modal>
```

## Beyond templates

Citry components are more than templates. A few of the things you can do:

**Type your inputs and catch mistakes at compile time.** Declare a component's
props and slots with plain annotated classes:

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

These declarations become a contract for every template that uses the
component. Mistakes fail when the template is compiled, pointing at the exact
spot in the source:

```html
<c-Card title="Hi" bogus="1" />      <!-- error: unknown prop -->
<c-Card />                           <!-- error: missing required `title` -->
<c-Card title="Hi">
  <c-fill name="headr">...</c-fill>  <!-- error: typo'd slot name -->
</c-Card>
```

**Co-locate JS and CSS with a component**, and render the collected assets
where you want them with `<c-js>` and `<c-css>`:

```python
class Counter(Component):
    template = """
      <button>{{ label }}</button>
    """
    css = """
      button {
        font-weight: bold;
      }
    """
    js = """
      $onComponent(({ els }) => {
        els[0].addEventListener('click', increment);
      });
    """
```

**Provide values to descendant components** with `<c-provide>`, and read them
anywhere below with `inject()`, so you do not thread props through every level:

```python
class Greeting(Component):
    template = """
      <p>{{ label }}</p>
    """

    def template_data(self, kwargs, slots=None):
        # Read a value an ancestor provided, with no prop drilling.
        return {
            "label": self.inject("theme").label,
        }

class Page(Component):
    # <c-Greeting /> renders <p>Dark mode</p>
    template = '''
      <c-provide key="theme" label="Dark mode">
        <c-Greeting />
      </c-provide>
    '''
```

**Wrap a subtree in an error boundary** so a failure in one component renders a
fallback instead of breaking the whole page:

```python
class Page(Component):
    # If <c-Widget /> raises while rendering,
    # the page shows the fallback text instead of
    # letting the error break the page.
    template = '''
      <c-error-fallback fallback="Could not load widget">
        <c-Widget />
      </c-error-fallback>
    '''
```

A `fallback` slot can receive the error itself if you want a custom message.

**Build a component once, then compose and reuse it.** `Component(...)` returns
a value you can render on its own or pass into another component, and the same
instance works in more than one place:

```python
class Layout(Component):
    template = "<main>{{ body }}</main>"

    def template_data(self, kwargs, slots=None):
        return {"body": kwargs["body"]}

card = Card(title="Welcome")

standalone = str(card)        # render the card to HTML on its own
page = Layout(body=card)      # or pass the same card into another component
```

## Use with web framework

Some Citry features need a web server to work.

Citry can be easily integrated with popular Python web frameworks:

```python
from citry import citry  # the default instance
from citry.contrib.fastapi import mount

# `app` is your web framework's application object
mount(app, citry)
```

Supported hosts:

| Host | Entry point |
| ---- | ----------- |
| **FastAPI / Starlette** | `citry.contrib.fastapi.mount(app, citry)` |
| **Flask** | `citry.contrib.flask.mount(app, citry)` |
| **Django** | `citry.contrib.django.urlpatterns(citry)`, added to your `urls.py` |
| **Any ASGI server** | `citry.contrib.asgi.asgi_app(citry)` |
| **Any WSGI server** | `citry.contrib.wsgi.wsgi_app(citry)` |

Cache backends plug in the same way, through `Citry(cache=...)`:
`citry.contrib.caches.RedisCache`, `citry.contrib.caches.DiskCache`, and
`citry.contrib.django.DjangoCache`.

## Installation

```sh
pip install citry
```

`citry` is the runtime you import from. It builds on `citry_core`, the
Rust-powered parser and compiler, and installs it for you.

## Documentation

- [Template syntax reference](docs/template-syntax.md) - every template feature
  in depth.
- [Codebase and development setup](docs/codebase.md) - how to build, test, and
  contribute.

## Help bring Citry to your language

Today Citry ships as a Python package, but it is built to travel. All the hard
parts (parsing, compiling, the template contract) live in a single Rust core,
and each language gets a thin binding on top. The code inside `{{ }}` and `c-*`
attributes is the only host-language-specific piece. Adding a language means
writing that thin binding, not reimplementing the engine.

| Language   | Status  | Binding      |
| ---------- | ------- | ------------ |
| **Python** | Ready   | PyO3/maturin |
| **JS/TS**  | Planned | wasm-bindgen |
| **PHP**    | Planned | FFI          |
| **Go**     | Planned | cgo          |
| **Rust**   | Planned | Native       |

If you want Citry in your stack, this is a great place to contribute. Star the
repo to follow along, and open an issue if you would like to help port it.

## License

MIT License - see [LICENSE](./LICENSE) for details.

## Acknowledgments

This project is the continuation of work originally done in
[django-components](https://github.com/django-components/django-components) and
[django-components/djc-core](https://github.com/django-components/djc-core).
