# HTML transform stream

_Transform HTML in a single pass_

When rendering components in django-components / citry, there are multiple cases when we need to set attributes on the generated HTML:

1. **Component IDs**: Each component leaves behind an ID on the generated HTML, e.g., data attributes like `data-djc-c12345`. These need to be applied to all root tags of the component's HTML fragment.

2. **Parent-to-child attribute passing**: Parent components may pass down HTML attributes to their children.

To do this efficiently, this package, `citry_html_transform` takes the information on what HTML attributes need to be set where, and modifies the HTML in a **single pass**.

## How it works

The transformer processes HTML using a streaming XML/HTML parser ([`quick-xml`](https://github.com/tafia/quick-xml)) that reads and writes the HTML simultaneously. This approach should be efficient, memory-friendly, and should preserve the original structure.

**Transformations:**

1. **Add root attributes**: Attributes specified in `root_attributes` are added only to root-level elements.

2. **Add attributes to all elements**: Attributes specified in `all_attributes` are added to every element in the HTML.

## Usage

### Rust API

```rust
use citry_html_transform::{transform_html, HtmlTransformerConfig};

// Create config
let config = HtmlTransformerConfig::new(
    // root_attributes
    vec!["data-djc-c12345".to_string()],
    // all_attributes
    vec!["data-v-123".to_string()],
    // check_end_names
    false,
    // track_added_attributes_for_tags_with_this_attribute
    Some("id".to_string()),
);

let html = r#"
  <div id="xyz">
    <p>Hello</p>
  </div>
"#;

// Transform HTML
let (transformed_html, captured) = transform_html(&config, html)?;

// transformed_html:
// <div
//   id="xyz"
//   data-djc-c12345="" 
//   data-v-123=""
// >
//   <p data-v-123="">Hello</p>
// </div>
//
// captured:
// [
//   (
//     "xyz",
//     vec![
//       "data-djc-c12345",
//       "data-v-123"
//     ]
//   )
// ]
```

### Python API

```python
from citry_core.html_transformer import set_html_attributes

# Transform HTML with attributes
html = '<div id="xyz"><p>Hello</p></div>'
result, captured = set_html_attributes(
    html,
    root_attributes=['data-djc-c12345'],
    all_attributes=['data-v-123'],
    track_added_attributes_for_tags_with_this_attribute='id'
)

# transformed_html:
# <div
#   id="xyz"
#   data-djc-c12345="" 
#   data-v-123=""
# >
#   <p data-v-123="">Hello</p>
# </div>
#
# captured:
# {
#   "xyz": [
#     "data-djc-c12345",
#     "data-v-123"
#   ]
# }
```

## Configuration

### `HtmlTransformerConfig`

- **`root_attributes`**: `Vec<String>` - Attributes to add only to root-level elements (depth 0)
- **`all_attributes`**: `Vec<String>` - Attributes to add to all elements
- **`check_end_names`**: `bool` - Whether to validate that closing tags match their opening tags
- **`track_added_attributes_for_tags_with_this_attribute`**: `Option<String>` - If set, tracks which attributes were added to elements with this attribute
