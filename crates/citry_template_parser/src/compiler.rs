//! # Template compiler
//!
//! Compiles a parsed `Template` AST into host-language source code via
//! the `LangImpl` trait. For Python (the default), the output is a
//! `generate_template()` function whose body is a list of node objects.
//! The host-language runtime provides the node classes; this compiler
//! only generates the source string that instantiates them.
//!
//! ## Node types produced
//!
//! The compiler emits calls to these node classes (defined as constants
//! in `constants.rs`). Each language binding must provide implementations
//! for all of them.
//!
//! **Body nodes** (elements of the top-level `body` list):
//!
//! | Node class | Citry source | Signature (Python) |
//! |---|---|---|
//! | (inline string) | Plain text, static HTML | `"""text"""` |
//! | `ExprNode` | `{{ expr }}` | `ExprNode(source, (start, end,), """expr""", ("var1",))` |
//! | `TemplateNode` | Nested template on an HTML tag's dynamic attr | `TemplateNode(source, (start, end,), """expr""", ("var1",))` |
//! | `ComponentNode` | `<c-Card>`, `<c-component>`, any `<c-*>` | `ComponentNode(source, (start, end,), (attrs,), [body], (used_vars,), """name""", contains_fills)` |
//! | `IfNode` | `<c-if>/<c-elif>/<c-else>` | `IfNode(source, (branch, ...,), (used_vars,))` |
//! | `ForNode` | `<c-for>/<c-empty>` | `ForNode(source, (branch, ...,), (used_vars,))` |
//! | `SlotNode` | `<c-slot>` | `SlotNode(source, (start, end,), (attrs,), [body], (used_vars,), (introduced_vars,))` |
//! | `FillNode` | `<c-fill>` | `FillNode(source, (start, end,), (attrs,), [body], (used_vars,), (introduced_vars,))` |
//!
//! Each `IfNode`/`ForNode` branch is a tuple:
//! `((start, end,), (attrs,), [body], (introduced_vars,))`
//!
//! **Attribute nodes** (inside the `(attrs,)` tuple of component/slot/fill nodes):
//!
//! | Attr class | Citry source | Signature (Python) |
//! |---|---|---|
//! | `StaticHtmlAttr` | `title="Hello"` | `StaticHtmlAttr(source, (start, end,), """key""", """value""", (used_vars,))` |
//! | `ExprHtmlAttr` | `c-class="expr"` | `ExprHtmlAttr(source, (start, end,), """key""", """expr""", (used_vars,))` |
//! | `TemplateHtmlAttr` | `c-body="<div>...</div>"` | `TemplateHtmlAttr(source, (start, end,), """key""", """template""", (used_vars,))` |
//!
//! On regular HTML tags (not components), dynamic attributes are **not**
//! wrapped in `*HtmlAttr` calls. Instead they are split inline: static
//! string fragments with an `ExprNode`/`TemplateNode` between them,
//! concatenated at runtime to form the final HTML attribute string.
//!
//! ## Formatting conventions (Python output)
//!
//! - Lists: trailing comma, e.g. `[a, b,]`; empty `[]`.
//! - Tuples: trailing comma, e.g. `(a, b,)`; empty `()`; single `(x,)`.
//! - Strings: triple double-quoted with every `"` escaped as `\"`,
//!   e.g. `"""a \"b\" c"""`.
//! - Consecutive static text/HTML items are coalesced into a single string.
//! - Component names are lowercased: `<c-Card>` -> `"""card"""`.
//!   Kebab-case names are preserved: `<c-my-card>` -> `"""my-card"""`.
//! - `key=""` normalizes to boolean `True` (at compile time, not parse time).
//! - Void elements render compact (`<br/>`); non-void self-closing expand
//!   (`<div></div>`).
//! - `<c-raw>` compiles to a `ComponentNode` named `"""raw"""` whose body
//!   contains the raw, unparsed text.
//!
//! ## Determinism
//!
//! The output must be reproducible across runs. Used-variable names are
//! deduped while preserving first-seen (source) order; never iterate a
//! `HashSet` into the emitted output.

use std::collections::HashSet;
use std::iter::Peekable;
use std::rc::Rc;
use std::vec::IntoIter;

use crate::ast::{
    HtmlAttr, HtmlAttrKind, HtmlEndTag, HtmlStartTag, Node, Template, TemplateElement, Token,
};
use crate::constants::{
    COMPONENT_NODE, CONTROL_FLOW_GROUPS, CONTROL_FLOW_TAGS, C_COMPONENT_TAG, C_ELIF_TAG,
    C_ELSE_TAG, C_EMPTY_TAG, C_FILL_TAG, C_FOR_TAG, C_IF_TAG, C_SLOT_TAG, EXPR_ATTR_NODE,
    EXPR_NODE, FILL_NODE, FOR_NODE, HTML_VOID_ELEMENTS, IF_NODE, SLOT_NODE, STATIC_ATTR_NODE,
    TAG_ATTR_RULES, TEMPLATE_ATTR_NODE, TEMPLATE_NODE,
};
use crate::error::CompileError;
use crate::lang::lang::{Lang, LangImpl, LangSpecArgument, LangSpecStruct};

/// Compile a template AST into language-specific source code.
///
/// For example, for python, this function generates code fo a function
/// that returns a list of node objects (TextNode, ExprNode, etc.)
/// that represent the template structure:
///
/// ```python
/// def generate_template():
///     body = [
///         """Hello, \"John\"!""",
///         ExprNode(source, (14, 19), """a + b""", ("a", "b")),
///         ComponentNode(source, (14, 19), (HtmlAttr(...), ...),
///         """<a href=\"""",
///         ExprNode(source, (14, 19), """base + 'foo'""", ("base",)),
///         """\">Click me!</a>""",
///         ...
///     ]
///     return body
/// ```
///
/// **Arguments**
/// * `template` - The parsed template AST
/// * `lang` - Optional language implementation - Specifies which language to use
///            for code generation (e.g., Python, PHP, JS, ...).
///            Default is Python.
///
/// **Returns**
/// A string containing source code for a function that generates the template tree.
pub fn compile_template(template: Template, lang: Option<Lang>) -> Result<String, CompileError> {
    // Resolve the language enum to an Rc<dyn LangImpl>
    let lang_impl = lang.unwrap_or(Lang::Python).to_lang_impl();
    compile_template_with_custom_lang(template, Some(&lang_impl))
}

/// Compile a template AST into language-specific source code with a custom language implementation.
///
/// This is same as `compile_template()`, but allows you to specify a custom language implementation,
/// instead of using pre-defined enum values.
///
/// **Arguments**
/// * `template` - The parsed template AST
/// * `lang` - Optional language implementation - Specifies which language to use
///            for code generation (e.g., Python, PHP, JS, ...)
///            Default is Python.
///
/// **Returns**
/// A string containing source code for a function that generates the template tree.
pub fn compile_template_with_custom_lang(
    template: Template,
    lang: Option<&Rc<dyn LangImpl>>,
) -> Result<String, CompileError> {
    // NOTE: This function accepts references of Rc's to avoid consuming the Rc instances.
    // But if we receive None, we have to create a new Rc instance.
    // Thus we also clone the Rc internally, so that in both Some/None cases we end up
    // owning the Rc instances.
    let lang_impl = lang
        .map(|l| Rc::clone(l))
        .unwrap_or_else(|| Lang::Python.to_lang_impl());

    // Compile the template body into LangSpecArgument structures
    let body_items = compile_template_body(template)?;

    // Delegate to the language implementation to convert LangSpecArguments to source code
    lang_impl
        .compile(body_items)
        .map_err(|e| CompileError::Generic(e))
}

pub fn compile_template_body(template: Template) -> Result<Vec<LangSpecArgument>, CompileError> {
    // First, process elements to convert control flow attributes (`c-if="..."`)
    // into control flow nodes (`<c-if cond="...">...</c-if>`).
    let processed_elements = wrap_nodes_with_control_flow_attrs(template.elements)?;

    let mut body_items = Vec::new();
    let mut elements_iter = processed_elements.into_iter().peekable();

    // Instead of normally looping over the elements, we'll use an iterator and `.next()`.
    // This is so that we can consume more elements in a single loop, as <c-if> and <c-for>
    // will consume the following <c-elif>/<c-else>/<c-empty> nodes.
    while let Some(element) = elements_iter.next() {
        match element {
            // Plain text
            // Plain text doesn't need any runtime processing.
            // It uses no variables, and can never raise an error.
            // Hence, we don't have to wrap the text in any Node class.
            // We just escape double quotes, and wrap the text in `""""`,
            // so it's safe even if it spans multiple lines.
            TemplateElement::Text(text) => {
                body_items.push(LangSpecArgument::UnsafeString(text.token.content));
            }

            // {{ ... }} expression
            // When we come across a `{{ ... }}` expression, we want to evaluate the Python expression inside.
            // To do that, we generate code like this:
            // `ExprNode(source, (start, end), """expr""", ("var1", "var2"))`
            // Where:
            // - `source` is the original template source string,
            // - `(start, end)` is the position of the expression in the source string,
            // - `"""expr"""` is the Python expression,
            // - `("var1", "var2")` is a tuple of variable names that are used in the expression.
            //
            // `source` and `(start, end)` are used for error handling / diagnostics. When an error
            // happens inside the `{{ ... }}` expression, we'll be able to print to the user the location
            // in the template where the error occurred:
            // ```
            // <div>
            //   {{ 3 > "a" }}
            //   ^^^^^^^^^^^^^
            // </div>
            // TypeError: '>' not supported between instances of 'int' and 'str'
            // ```
            //
            // The Python expression `"""expr"""` is wrapped in triple quotes, so it's safe to use
            // even if it contains double quotes, backslashes, or newlines.
            // The actual implementation of how the expression is executed will be provided
            // by the `ExprNode` class in the Python code. E.g. `ExprNode` should call `safe_eval()`
            // at initialization to generate a function that can be called.
            //
            // Last argument is a tuple of used variables, e.g. `("var1", "var2")`.
            // This will be used for a run-time optimization:
            // If, at first render, we detect that
            // 1) the expression uses NO variables, or
            // 2) all used variables are "constants"
            // Then, we know the output will never change, and we can replace `ExprNode` with its result as text.
            // Thus, on subsequent renders, we won't have to re-evaluate the expression.
            TemplateElement::Expr(expr) => {
                let expr_node = format_expr_node(
                    EXPR_NODE,
                    &expr.token,
                    &expr.value.content,
                    &expr.used_variables,
                );
                body_items.push(expr_node);
            }

            TemplateElement::Node(mut node) => {
                // Determine which Node class to use based on tag name
                match node.tag_name() {
                    // Control flow nodes
                    C_FOR_TAG => {
                        // Collect c-for and c-empty nodes into a group
                        let mut for_group = vec![node];
                        let for_empty_nodes =
                            consume_nodes_into_group(&mut elements_iter, &[C_EMPTY_TAG]);
                        for_group.extend(for_empty_nodes);

                        let for_node = compile_control_flow_node(for_group, FOR_NODE, C_FOR_TAG)?;
                        body_items.push(for_node);
                    }
                    C_IF_TAG => {
                        // Collect c-if, c-elif, and c-else nodes into a group
                        let mut if_group = vec![node];
                        let elif_and_else_nodes =
                            consume_nodes_into_group(&mut elements_iter, &[C_ELIF_TAG, C_ELSE_TAG]);
                        if_group.extend(elif_and_else_nodes);

                        let if_node = compile_control_flow_node(if_group, IF_NODE, C_IF_TAG)?;
                        body_items.push(if_node);
                    }

                    // Special c-* tags
                    C_SLOT_TAG => {
                        let slot_node = compile_simple_node(node, SLOT_NODE)?;
                        body_items.push(slot_node);
                    }
                    C_FILL_TAG => {
                        let fill_node = compile_simple_node(node, FILL_NODE)?;
                        body_items.push(fill_node);
                    }
                    // NOTE: `<c-provide>`, `<c-js>`, and `<c-css>` are not included here
                    // because they can be implemented as user-side components.

                    // Component nodes (render user-defined components)
                    C_COMPONENT_TAG => {
                        // Check if this component is using static `is` attribute
                        // instead of the dynamic `c-is`. If the user is using the static variant,
                        // then we know the component name (the static value), and so we can skip
                        // rendering the dynamic "c-component", and instead render the underlying
                        // named component directly.
                        // For example:
                        // ```html
                        // <c-component is="XyzComp" ...>
                        // ```
                        // should be rendered as:
                        // ```html
                        // <c-XyzComp ...>
                        // ```
                        let mut component_name: Option<String> = None;

                        for attr in node.attrs() {
                            if attr.key.content == "is" {
                                // Found `is` attribute - extract the value if it has any
                                if let Some(inner_value) = &attr.inner_value {
                                    component_name = Some(inner_value.content.clone());
                                    break;
                                }
                            }
                        }

                        if let Some(comp_name) = component_name {
                            // We have found a static `is` attribute with the component name.
                            // Now mutate node to `<c-{comp_name}>` and drop the `is` attribute
                            match &mut node {
                                Node::WithBody { start_tag, .. }
                                | Node::SelfClosing { start_tag, .. } => {
                                    // Update tag name
                                    start_tag.name.content = format!("c-{}", comp_name);
                                    // Remove `is` attribute
                                    start_tag.attrs.retain(|attr| attr.key.content != "is");
                                }
                            }
                        }

                        // Finally, create a ComponentNode, whether we've got `<c-component>` or `<c-MyComp>`
                        let comp_node = compile_component_node(node)?;
                        body_items.push(comp_node);
                    }
                    // Unknown c-* tag => user-defined component
                    // This contains also c-provide, c-js, c-css
                    tag_name if tag_name.starts_with("c-") => {
                        let comp_node = compile_component_node(node)?;
                        body_items.push(comp_node);
                    }

                    // Regular HTML tags e.g. `<div>`, `<a>`, etc.
                    _ => {
                        let html_items = compile_html_node(node)?;
                        body_items.extend(html_items);
                    }
                }
            }
        }
    }

    // Coalesce consecutive string items into single strings.
    let body_items = coalesce_strings(body_items);

    Ok(body_items)
}

/// Compile a regular HTML node, e.g. `<div>`, into a flat list of body items (LangSpecArguments).
///
/// This handles:
/// - Start tag with attributes (static attrs as strings, dynamic attrs as `HtmlAttr` calls)
/// - Body content (recursively compiled)
/// - End tag (if not self-closing or not a void element)
///
/// **Start tag:**
///
/// Since we are handling an HTML tag like `<div>` that actually shows up in the final HTML,
/// the output can be a literal string of that tag.
///
/// **Start tag - static attributes:**
///
/// The start tag may contain static attributes, e.g. `class="foo"`, etc.
///
/// When we come across a static attribute, there's nothing to process.
/// We could generate a call to `StaticHtmlAttr()` in Python to render the static attribute.
/// But to minimize Python-side processing, we directly convert static attributes to literal strings.
///
/// So `<div class="foo">` remains as `"""<div class="foo">"""`.
///
/// **Start tag - dynamic attributes:**
///
/// Dynamic attributes, e.g. `c-class="..."`, NEED to be evaluated at runtime.
///
/// But everything that is NOT dynamic CAN be converted to literal string.
///
/// So we practically end up with a string that is similar to if we had used an F-string to define the template:
///
/// ```python
/// f'<div style="color: red" c-class="{...}">'
/// ```
///
/// Since we're converting the HTML tag to a literal string, the evaluated dynamic attributes
/// will not be passed to another Python-side `Node` class. Instead, the evaluated attributes
/// will be concatenated to the surrounding static text.
///
/// Thus, while in other cases we'd convert dynamic attributes to `ExprHtmlAttr()` or `TemplateHtmlAttr()`,
/// here we generate calls for `ExprNode()` or `TemplateNode()`.
///
/// In the end, the output is similar to this:
///
/// ```py
/// body_parts = [
///     # Beginning
///     """<div""",
///     # Static attribute
///     """ style=\"color: red\" """,
///     # Dynamic attribute key start
///     """ class=\"""",
///     # Dynamic expression
///     ExprNode(source, (14, 19), """base + 'foo'""", ("base",)),
///     # Dynamic attribute key end
///     """\"""",
///     # Ending part
///     """>""",
/// ]
/// ```
///
/// The Python implementation then only needs to evaluate the dynamic parts,
/// and concatenate the result with the static parts to obtain the final HTML.
///
/// **End tag:**
///
/// End tag is the same as start string, except there's no attributes,
/// and thus there's no dynamic parts.
///
/// So the end tag is just a literal string of the tag name.
/// E.g. `</div>` becomes `"""</div>"""`.
///
/// **Body content:**
///
/// Body content is recursively compiled.
/// E.g. `<div>Hello, {{ name }}!</div>` becomes:
///
/// ```py
/// body_parts = [
///     """<div>""",
///     """Hello, """
///     ExprNode(source, (14, 19), """name""", ("a", "b")),
///     """!""",
///     """</div>""",
/// ]
/// ```
///
/// **Self-closing tag:**
///
/// Similarly to Vue, we allow the self-closing syntax even for elements
/// that don't normally allow that as per the HTML spec, e.g. `<div/>`.
///
/// And similarly to Vue, we expand these, so the final output is valid HTML.
///
/// E.g. `<div/>` becomes `"""<div></div>"""`.
///
/// This tag expansion is NOT applied to void elements, e.g. `<img/>`.
///
/// Void elements are elements defined in the HTML spec that cannot have an end tag, e.g. `<img/>`, `<br/>`, etc.
///
/// For void elements, we keep the self-closing syntax as is.
fn compile_html_node(node: Node) -> Result<Vec<LangSpecArgument>, CompileError> {
    let mut items = Vec::new();

    // Get tag info and other properties
    let tag_name = node.tag_name();
    let end_tag_html = &format!("</{}>", tag_name);
    let start_tag_attrs = node.attrs();
    let is_self_closing = match &node {
        Node::WithBody { .. } => false,
        Node::SelfClosing { .. } => true,
    };

    let is_void_element = HTML_VOID_ELEMENTS.contains(&tag_name);

    // Start tag: `<tag`
    // The tag name can technically contain quote characters, so we escape the string.
    items.push(LangSpecArgument::UnsafeString(format!("<{}", tag_name)));

    // Process attributes like `class="..."`, `c-class="..."`, `disabled`, etc.
    for attr in start_tag_attrs {
        match attr.kind {
            // Static attribute: add as string with leading space
            // Format: ` key="value"` or ` key` (for boolean)
            // Note: HTML escaping of quotes in values will be handled at runtime
            HtmlAttrKind::Static => {
                // Note: Use `HtmlAttr.value` so we format also quotes around the value.
                // In HTML, `key=""` and `key=''` are boolean attributes (same as bare `key`),
                // so we normalize empty values to boolean form.
                let has_nonempty_value = attr
                    .inner_value
                    .as_ref()
                    .is_some_and(|v| !v.content.is_empty());
                let attr_str = if has_nonempty_value {
                    format!(
                        " {}={}",
                        attr.key.content,
                        attr.value.as_ref().unwrap().content
                    )
                } else {
                    format!(" {}", attr.key.content)
                };
                items.push(LangSpecArgument::UnsafeString(attr_str));
            }
            HtmlAttrKind::Expression | HtmlAttrKind::Template => {
                let attr_key_without_prefix = attr.key.content.strip_prefix("c-").unwrap();

                // Dynamic attribute with non-empty value: To get the actual value, we'll need to
                // render the attribute expression at runtime. But the scaffolding
                // around the dynamic value is static, so we end up with:
                // `[' key=\"', ExprNode(...), '"']`
                // In HTML, `key=""` is boolean, so empty values are treated as no-value.
                let has_nonempty_value = attr
                    .inner_value
                    .as_ref()
                    .is_some_and(|v| !v.content.is_empty());
                if has_nonempty_value {
                    let inner_value = attr.inner_value.as_ref().unwrap();
                    // ` key="`
                    let attr_start = format!(" {}=\"", attr_key_without_prefix);
                    items.push(LangSpecArgument::UnsafeString(attr_start));

                    // ExprNode/TemplateNode call
                    let node_call = if attr.kind == HtmlAttrKind::Expression {
                        format_expr_node(
                            EXPR_NODE,
                            &inner_value,
                            &inner_value.content,
                            &attr.used_variables,
                        )
                    } else {
                        format_expr_node(
                            TEMPLATE_NODE,
                            &inner_value,
                            &inner_value.content,
                            &attr.used_variables,
                        )
                    };
                    items.push(node_call);

                    // `"`
                    items.push(LangSpecArgument::UnsafeString("\"".to_string()));
                // Expression attribute without value (or empty value): Just add the attribute key as is.
                } else {
                    let attr_str = format!(" {}", attr_key_without_prefix);
                    items.push(LangSpecArgument::UnsafeString(attr_str));
                };
            }
        }
    }

    // Handle closing of start tag
    if is_self_closing && is_void_element {
        // Void element with self-closing: keep as `/>`
        items.push(LangSpecArgument::UnsafeString("/>".to_string()));
    } else if is_self_closing {
        // Non-void element with self-closing: expand to `></tag>`
        items.push(LangSpecArgument::UnsafeString(">".to_string()));
        items.push(LangSpecArgument::UnsafeString(end_tag_html.to_string()));
    } else {
        // Regular start tag: just `>`
        items.push(LangSpecArgument::UnsafeString(">".to_string()));
    }

    // Process body content (if WithBody)
    if let Node::WithBody { body, .. } = node {
        let body_items = compile_template_body(body)?;
        items.extend(body_items);

        // Add end tag
        items.push(LangSpecArgument::UnsafeString(end_tag_html.to_string()));
    }

    Ok(items)
}

/// Compile a simple node (e.g., `<c-slot>`, `<c-fill>`) into a LangSpecArgument.
///
/// Generates code like:
/// ```py
/// NodeClass(
///     source,                   # original template source string
///     (start, end),             # positional metadata
///     (ExprHtmlAttr(...), ...), # attributes (HtmlAttr calls)
///     [body_item1, ...],        # body node list
///     ("var1", "var2", ...),    # used variables tuple
///     ("introduced_var1", "introduced_var2", ...), # introduced variables tuple
/// )
/// ```
///
/// This function is used for all `<c-*>` nodes with "simple" structure, meaning that
/// they have only one body content and are standalone nodes.
///
/// For comparison:
/// - `<c-if>` and `<c-for>` nodes are more complex because we join `<c-if>/<c-elif>/<c-else>` into a single node.
/// - Custom user components and `<c-component>` allow multiple slots defined via `<c-fill>`
///
/// All attributes are kept as `HtmlAttr` calls (StaticHtmlAttr, ExprHtmlAttr, or TemplateHtmlAttr)
/// to preserve positional metadata for error reporting, even for static attributes.
///
/// We do NOT simplify static attributes (StaticHtmlAttr) to literal strings, because it's up to the runtime implementation
/// to decide which attributes are allowed. If the runtime impl decides that an attribute is not allowed,
/// it can use the positional metadata to point out the location of the wrong attribute in the template.
///
/// The body is compiled using `compile_template_body` and inlined as a list `[body_item1, body_item2, ...]`.
/// We're using a list here, NOT tuple, so the nodelist is mutable, so it can be optimized at runtime.
///
/// E.g. `<c-slot>` with following body:
///
/// ```html
/// <c-slot c-name="name">
///     <div>
///         Hello, {{ name }}!
///     </div>
/// </c-slot>
/// ```
///
/// Will have following body node list:
/// ```py
/// [
///     """<div>Hello, """,
///     ExprNode(source, (14, 19), """name""", ("name",)),
///     """!</div>""",
/// ]
/// ```
///
/// The used variables contains all variables used in the node's body AND attributes.
///
/// While we already track used variables for individual `HtmlAttrs`, we need it also on the level of nodes,
/// - Attributes-level allows us to cache the result of individual attributes
/// - Node-level allows us to cache the result of the node as a whole, including its body
///
/// The introduced variables contains all variables introduced by this node.
/// These variables are not available to other nodes outside this one.
/// - `<c-for>` introduces loop variables.
/// - `<c-fill>` introduces data/default variables.
///
/// Introduced variables need to be passed to runtime so that it can assign values to those variables.
fn compile_simple_node(
    node: Node,
    node_class_name: &str,
) -> Result<LangSpecArgument, CompileError> {
    let start_tag = node.start_tag();

    // Get token positions from the start tag
    let start_pos = start_tag.token.start_index;
    let end_pos = match &node {
        Node::WithBody { end_tag, .. } => end_tag.token.end_index,
        Node::SelfClosing { start_tag, .. } => start_tag.token.end_index,
    };

    // Compile all attributes as HtmlAttr calls:
    // `(HtmlAttr(...), HtmlAttr(...), ...)`
    let mut attr_args = Vec::new();
    for attr in node.attrs() {
        attr_args.push(compile_html_attr(attr));
    }

    // Get used variables from the node
    let used_variables: Vec<String> = node
        .used_variables()
        .iter()
        .map(|token| token.content.clone())
        .collect();

    // Get introduced variables from the node
    let introduced_variables: Vec<String> = node
        .introduced_variables()
        .iter()
        .map(|token| token.content.clone())
        .collect();

    // Compile body content as a list: `[item1, item2, ...]`
    // NOTE: We use a list here NOT tuple, so the nodelist is mutable.
    //       This way, after first render, when we detect static parts,
    //       we can replace them with their result as text.
    let body_items = match node {
        Node::WithBody { body, .. } => compile_template_body(body)?,
        Node::SelfClosing { .. } => Vec::new(),
    };

    // Generate node call
    // `NodeClass(
    //    source,
    //    (start, end),
    //    (HtmlAttr(...), HtmlAttr(...), ...),
    //    [body_item1, body_item2, ...],
    //    ("var1", "var2", ...),
    //    ("introduced_var1", "introduced_var2", ...),
    // )`
    Ok(LangSpecArgument::Struct(LangSpecStruct {
        name: node_class_name.to_string(),
        arguments: vec![
            // Argument 1: `source` - original template source string as variable used for error reporting
            LangSpecArgument::Variable("source".to_string()),
            // Argument 2: `(start, end)` - positional metadata for error reporting
            LangSpecArgument::Tuple(vec![
                LangSpecArgument::Int(start_pos),
                LangSpecArgument::Int(end_pos),
            ]),
            // Argument 3: `(HtmlAttr(...), HtmlAttr(...), ...)` - tuple of attributes
            LangSpecArgument::Tuple(attr_args),
            // Argument 4: `[body_item1, body_item2, ...]` - list of body items
            LangSpecArgument::List(body_items),
            // Argument 5: `("var1", "var2", ...)` - tuple of used variables
            LangSpecArgument::Tuple(
                used_variables
                    .iter()
                    .map(|name| LangSpecArgument::SafeString(name.clone()))
                    .collect(),
            ),
            // Argument 6: `("introduced_var1", "introduced_var2", ...)` - tuple of introduced variables
            LangSpecArgument::Tuple(
                introduced_variables
                    .iter()
                    .map(|name| LangSpecArgument::SafeString(name.clone()))
                    .collect(),
            ),
        ],
    }))
}

/// Compile a component node (e.g., `<c-MyComp>`, `<c-component>`) into a LangSpecArgument.
///
/// Generates code like:
/// ```py
/// ComponentNode(
///     source,                   # original template source string
///     (start, end),             # positional metadata
///     (ExprHtmlAttr(...), ...), # attributes (HtmlAttr calls)
///     [body_item1, ...],        # body node list
///     ("var1", "var2", ...),    # used variables tuple
///     "comp-name",              # Component name from the tag (e.g. `<c-comp-name>`).
///                               # This value will be used to search the registry of components
///     has_fills,                # boolean whether the body contains fills
/// )
/// ```
///
/// This function is used for all Component nodes (e.g. `<c-MyComp>`, `<c-component>`).
/// These may contain slot fills `<c-fill>` in their body.
///
/// The component name is extracted from the tag name by removing the "c-" prefix and lowercasing it.
/// For example: "c-MyComp" -> "mycomp", "c-component" -> "component"
///
/// All attributes are kept as `HtmlAttr` calls (StaticHtmlAttr, ExprHtmlAttr, or TemplateHtmlAttr)
/// to preserve positional metadata for error reporting, even for static attributes.
///
/// We do NOT simplify static attributes (StaticHtmlAttr) to literal strings, because it's up to the runtime implementation
/// to decide which attributes are allowed. If the runtime impl decides that an attribute is not allowed,
/// it can use the positional metadata to point out the location of the wrong attribute in the template.
///
/// The body is compiled using `compile_template_body` and inlined as a list `[body_item1, body_item2, ...]`.
/// We're using a list here, NOT tuple, so the nodelist is mutable, so it can be optimized at runtime.
///
/// E.g. `<c-MyComp>` with following body:
///
/// ```html
/// <c-MyComp c-name="name">
///     <div>
///         Hello, {{ name }}!
///     </div>
/// </c-MyComp>
/// ```
///
/// Will have following body node list:
/// ```py
/// [
///     """<div>Hello, """,
///     ExprNode(source, (14, 19), """name""", ("name",)),
///     """!</div>""",
/// ]
/// ```
///
/// The used variables contains all variables used in the node's body AND attributes.
///
/// While we already track used variables for individual `HtmlAttrs`, we need it also on the level of nodes,
/// - Attributes-level allows us to cache the result of individual attributes
/// - Node-level allows us to cache the result of the node as a whole, including its body
///
/// Unlike the "simple nodes", we don't pass the introduced variables to the runtime,
/// because Component nodes cannot introduce variables themselves.
///
/// Lastly, component node receives `has_fills` boolean, which is `True` if the body contains <c-fills>,
/// and `False` when the body has an implicit default slot, or no body at all.
///
/// This is used to determine whether we need to "pre-render" the body to collect the fill nodes.
/// If yes, we will "pre-render" the body to collect the fill nodes.
/// If no, the entire body is the "default" slot, and we can render it as is.
fn compile_component_node(node: Node) -> Result<LangSpecArgument, CompileError> {
    let start_tag = node.start_tag();

    // Get token positions from the start tag
    let start_pos = start_tag.token.start_index;
    let end_pos = match &node {
        Node::WithBody { end_tag, .. } => end_tag.token.end_index,
        Node::SelfClosing { start_tag, .. } => start_tag.token.end_index,
    };

    // Extract component name from tag name (before moving node)
    // Remove "c-" prefix and escape it
    let tag_name = node.tag_name();
    if !tag_name.starts_with("c-") {
        return Err(CompileError::Generic(format!(
            "Component node must start with 'c-' prefix: {}",
            tag_name
        )));
    }
    let comp_name = tag_name[2..].to_lowercase();

    // Get has_fills boolean (before moving node)
    let has_fills = node.contains_fills();

    // Compile all attributes as HtmlAttr calls:
    // `(HtmlAttr(...), HtmlAttr(...), ...)`
    let mut attr_args = Vec::new();
    for attr in node.attrs() {
        attr_args.push(compile_html_attr(attr));
    }

    // Get used variables from the node
    let used_variables: Vec<String> = node
        .used_variables()
        .iter()
        .map(|token| token.content.clone())
        .collect();

    // Compile body content as a list: `[item1, item2, ...]`
    let body_items = match node {
        Node::WithBody { body, .. } => compile_template_body(body)?,
        Node::SelfClosing { .. } => Vec::new(),
    };

    // Generate ComponentNode call
    // `ComponentNode(
    //    source,
    //    (start, end),
    //    (HtmlAttr(...), HtmlAttr(...), ...),
    //    [body_item1, body_item2, ...],
    //    ("var1", "var2", ...),
    //    "comp-name",
    //    has_fills,
    // )`
    Ok(LangSpecArgument::Struct(LangSpecStruct {
        name: COMPONENT_NODE.to_string(),
        arguments: vec![
            // Argument 1: `source` - original template source string as variable used for error reporting
            LangSpecArgument::Variable("source".to_string()),
            // Argument 2: `(start, end)` - positional metadata for error reporting
            LangSpecArgument::Tuple(vec![
                LangSpecArgument::Int(start_pos),
                LangSpecArgument::Int(end_pos),
            ]),
            // Argument 3: `(HtmlAttr(...), HtmlAttr(...), ...)` - tuple of attributes
            LangSpecArgument::Tuple(attr_args),
            // Argument 4: `[body_item1, body_item2, ...]` - list of body items
            LangSpecArgument::List(body_items),
            // Argument 5: `("var1", "var2", ...)` - tuple of used variables
            LangSpecArgument::Tuple(
                used_variables
                    .iter()
                    .map(|name| LangSpecArgument::SafeString(name.clone()))
                    .collect(),
            ),
            // Argument 6: `"comp-name"` - component name
            LangSpecArgument::UnsafeString(comp_name),
            // Argument 7: `has_fills` - boolean whether the body contains fills
            LangSpecArgument::Bool(has_fills),
        ],
    }))
}

/// Compile a group of control flow nodes (e.g., `<c-if>/<c-elif>/<c-else>` or `<c-for>/<c-empty>`)
/// into a Python node call.
///
/// Generates code like:
/// ```py
/// NodeClass(
///     source,
///     (
///         # First branch (e.g., c-if or c-for)
///         ((start, end), (ExprHtmlAttr(...), ...), [body_item1, ...], ("loopvar1", "loopvar2", ...)),
///         # Optional additional branches (e.g., c-elif/c-else or c-empty)
///         ((start, end), (ExprHtmlAttr(...), ...), [body_item1, ...], ()),
///         ...
///     ),
///     ("var1", "var2", ...),  # used variables for all branches
/// )
/// ```
///
/// These control flow nodes are different in that they can have multiple branches (IF/ELSE or FOR/EMPTY).
/// These branches are processed in order.
///
/// While all the branches together are treated as a single node (e.g. IfNode),
/// in the AST each branch is a separate HTML tag (e.g. `<c-if>`, `<c-elif>`, `<c-else>`).
///
/// So the input to this function is a list of HTML tags, and the output is a single node call.
///
/// Each branch contains:
/// - `(start, end)`: Positional metadata from the branch's node
/// - `(HtmlAttr(...), ...)`: Attributes tuple
/// - `[body_items...]`: Body content compiled as a list
/// - `("loopvar1", "loopvar2", ...)`: Tuple of introduced variables (e.g. loop variables used in `<c-for>`)
///
/// This is similar to what we generate for "simple nodes" (e.g. `<c-slot>`), except:
/// - There's a list of branches, and not a single body item.
/// - We don't track used variables for individual branches. Because that's applicable only on the level of entire IfNode,
///   or individual attributes, but not on the level of branches.
/// - But we DO track introduced variables for each branch, because one such branch is <c-for>.
///   It introduces variables to its body, and these variables are not available to other branches.
///
/// At the end of the `NodeClass` call, we generate the used variables tuple.
/// It contains all variables used across all branches, including both attributes and body content.
/// This is used for a run-time optimization, so that we can potentially replace the whole If/elif/else block
/// with a static text if all the variables are "constants".
///
/// **Parameters:**
/// - `nodes`: The group of nodes to compile (e.g., [c-if, c-elif, c-else] or [c-for, c-empty])
/// - `node_class_name`: The Python class name (e.g., "IfNode", "ForNode")
/// - `first_tag_name`: The expected tag name of the first node (e.g., "c-if", "c-for")
fn compile_control_flow_node(
    nodes: Vec<Node>,
    node_class_name: &str,
    first_tag_name: &str,
) -> Result<LangSpecArgument, CompileError> {
    if nodes.is_empty() {
        return Err(CompileError::Generic(format!(
            "{} requires at least one node ({})",
            node_class_name, first_tag_name
        )));
    }

    // Verify the first node matches the expected tag name
    if nodes[0].tag_name() != first_tag_name {
        return Err(CompileError::Generic(format!(
            "First node in {} group must be {}",
            node_class_name, first_tag_name
        )));
    }

    let mut branches = Vec::new();
    // Dedupe used variable names while preserving first-seen (source) order.
    // A plain HashSet would make the generated output non-deterministic across
    // runs, which breaks reproducible compilation and stable cache keys.
    let mut seen_variable_names = HashSet::new();
    let mut unique_variable_names: Vec<String> = Vec::new();

    // Process each branch
    // NOTE: The order of branches is guaranteed by the AST parser. So we don't have to check that here again.
    for node in nodes {
        let start_tag = node.start_tag();
        let start_pos = start_tag.token.start_index;
        let end_pos = match &node {
            Node::WithBody { end_tag, .. } => end_tag.token.end_index,
            Node::SelfClosing { start_tag, .. } => start_tag.token.end_index,
        };

        // Compile attributes as HtmlAttr calls
        let mut attr_args = Vec::new();
        for attr in node.attrs() {
            attr_args.push(compile_html_attr(attr));
        }

        // Collect unique variable names from this branch (first-seen order)
        for var_token in node.used_variables() {
            if seen_variable_names.insert(var_token.content.clone()) {
                unique_variable_names.push(var_token.content.clone());
            }
        }

        let introduced_var_names: Vec<String> = node
            .introduced_variables()
            .iter()
            .map(|token| token.content.clone())
            .collect();

        // Compile body content
        let body_items = match node {
            Node::WithBody { body, .. } => compile_template_body(body)?,
            Node::SelfClosing { .. } => Vec::new(),
        };

        // Format branch as:
        // ```py
        // (
        //     (start, end),
        //     (HtmlAttr(...), ...),
        //     [body_items...],
        //     ("loopvar1", "loopvar2", ...))
        // )
        // ```
        let branch = LangSpecArgument::Tuple(vec![
            // Argument 1: `(start, end)` - positional metadata for error reporting
            LangSpecArgument::Tuple(vec![
                LangSpecArgument::Int(start_pos),
                LangSpecArgument::Int(end_pos),
            ]),
            // Argument 2: `(HtmlAttr(...), ...)` - tuple of attributes
            LangSpecArgument::Tuple(attr_args),
            // Argument 3: `[body_items...]` - list of body items
            LangSpecArgument::List(body_items),
            // Argument 4: `("loopvar1", "loopvar2", ...)` - tuple of introduced variables per branch
            LangSpecArgument::Tuple(
                introduced_var_names
                    .iter()
                    .map(|name| LangSpecArgument::SafeString(name.clone()))
                    .collect(),
            ),
        ]);
        branches.push(branch);
    }

    // Format used variables tuple
    let all_used_variables: Vec<String> = unique_variable_names;

    // Generate node call, e.g.
    // ```py
    // IfNode(
    //    source,
    //    (
    //        ((1, 10), (ExprHtmlAttr(...), ...), [body_item1, ...], ("loopvar1", "loopvar2", ...)),
    //        ((11, 20), (ExprHtmlAttr(...), ...), [body_item2, ...], ("loopvar1", "loopvar2", ...)),
    //        ...,
    //    ),
    //    ("var1", "var2", ...)
    // )
    // ```
    Ok(LangSpecArgument::Struct(LangSpecStruct {
        name: node_class_name.to_string(),
        arguments: vec![
            // Argument 1: `source` - original template source string as variable used for error reporting
            LangSpecArgument::Variable("source".to_string()),
            // Argument 2: `branches` - tuple of branches
            LangSpecArgument::Tuple(branches),
            // Argument 3: `used_variables` - tuple of used variables
            LangSpecArgument::Tuple(
                all_used_variables
                    .iter()
                    .map(|name| LangSpecArgument::SafeString(name.clone()))
                    .collect(),
            ),
        ],
    }))
}

/// Convert a Rust `HtmlAttr` into a LangSpecArgument.
///
/// Returns different classes based on `HtmlAttrKind`:
/// - Static -> `StaticHtmlAttr(source, (start, end), """key""", """value""", ())`
/// - Expression -> `ExprHtmlAttr(source, (start, end), """key""", """value""", ("var1", "var2"))`
/// - Template -> `TemplateHtmlAttr(source, (start, end), """key""", """value""", ("var1", "var2"))`
///
/// **Explanation of arguments**
///
/// Tag attributes may consist of template or Python expression to evaluate. This will be done on Python side.
///
/// To do that, we generate code like this:
/// - `ExprHtmlAttr(source, (start, end), """key""", """value""", ("var1", "var2"))`
/// - `TemplateHtmlAttr(source, (start, end), """key""", """value""", ("var1", "var2"))`
/// - `StaticHtmlAttr(source, (start, end), """key""", """value""", ())`
///
/// Where:
/// - `source` is the original template source string,
/// - `(start, end)` is the position of the expression in the source string,
/// - `"""key"""` is the attribute key (escaped because it may contain double or single quotes)
/// - `"""value"""` is the attribute value (escaped because it may contain double or single quotes, backslashes, or newlines), or `None` for boolean attributes,
/// - `("var1", "var2")` is a tuple of variable names that are used in the expression.
///
/// `source` and `(start, end)` are used for error handling / diagnostics. When an error
/// happens inside an expression or template, we'll be able to print to the user the location
/// in the template where the error occurred:
///
/// ```html
/// <div c-class="3 > 'a'">
///              ^^^^^^^^^
/// </div>
/// TypeError: '>' not supported between instances of 'int' and 'str'
/// ```
///
/// If value is a template or Python expression, the actual implementation will be provided
/// by the `ExprHtmlAttr` or `TemplateHtmlAttr` class in the Python code. E.g. `ExprHtmlAttr`
/// should call `safe_eval()` at initialization to generate a function that can be called.
///
/// The last argument is a tuple of used variables, e.g. `("var1", "var2")`.
/// This will be used for a run-time optimization. If, at first render, we detect that
/// 1) the expression uses NO variables, or
/// 2) all used variables are "constants"
///
/// Then, we know the output will never change, and we can replace `HtmlAttr` instance
/// with its result as text. Thus, on subsequent renders, we won't have to re-evaluate the expression
/// or template.
fn compile_html_attr(attr: &HtmlAttr) -> LangSpecArgument {
    let start_pos = attr.token.start_index;
    let end_pos = attr.token.end_index;

    let var_names: Vec<String> = attr
        .used_variables
        .iter()
        .map(|token| token.content.clone())
        .collect();

    // Use different class based on kind
    let class_name = match attr.kind {
        HtmlAttrKind::Expression => EXPR_ATTR_NODE,
        HtmlAttrKind::Template => TEMPLATE_ATTR_NODE,
        HtmlAttrKind::Static => STATIC_ATTR_NODE,
    };

    // Argument 4: `"""value"""` or `True` - attr value, unsafe string or boolean
    // In HTML, `key`, `key=""`, and `key=''` are all treated as boolean attributes.
    // So we normalize empty-string values to `True` just like missing values.
    let attr_value = match &attr.inner_value {
        // Non-empty string, e.g. `key="value"`
        Some(inner_value) if !inner_value.content.is_empty() => {
            LangSpecArgument::UnsafeString(inner_value.content.clone())
        }
        // Empty string, e.g. `key=""` or `key=''`
        Some(_) => LangSpecArgument::Bool(true),
        // Missing value, e.g. `key`
        None => LangSpecArgument::Bool(true),
    };

    // E.g. `ExprHtmlAttr(source, (14, 19), """key""", """value""", ("a", "b"))`
    //      `TemplateHtmlAttr(source, (14, 19), """key""", """value""", ("a", "b"))`
    //      `StaticHtmlAttr(source, (14, 19), """key""", """value""", ())`
    LangSpecArgument::Struct(LangSpecStruct {
        name: class_name.to_string(),
        arguments: vec![
            // Argument 1: `source` - original template source string as variable used for error reporting
            LangSpecArgument::Variable("source".to_string()),
            // Argument 2: `(start, end)` - positional metadata for error reporting
            LangSpecArgument::Tuple(vec![
                LangSpecArgument::Int(start_pos),
                LangSpecArgument::Int(end_pos),
            ]),
            // Argument 3: `"""key"""` - attr key, unsafe string (may contain quotes)
            LangSpecArgument::UnsafeString(attr.key.content.clone()),
            // Argument 4: `"""value"""` or `True` - attr value, unsafe string or boolean
            attr_value,
            // Argument 5: `("var1", "var2")` or `()` - tuple of used variables (safe strings)
            LangSpecArgument::Tuple(
                var_names
                    .iter()
                    .map(|name| LangSpecArgument::SafeString(name.clone()))
                    .collect(),
            ),
        ],
    })
}

/// Coalesce consecutive `LangSpecArgument::SafeString` or `UnsafeString` items into single strings.
///
/// This merges multiple consecutive strings of the same type into one.
/// E.g., `[SafeString("a"), SafeString("b")]` becomes `[SafeString("ab")]`.
/// E.g., `[UnsafeString("<a>"), UnsafeString("</a>")]` becomes `[UnsafeString("<a></a>")]`.
///
/// When switching between `SafeString` and `UnsafeString`, the accumulated strings are flushed.
/// E.g., `[SafeString("a"), UnsafeString("<b>")]` remains as `[SafeString("a"), UnsafeString("<b>")]`.
fn coalesce_strings(items: Vec<LangSpecArgument>) -> Vec<LangSpecArgument> {
    let mut result = Vec::new();
    let mut current_safe_string_parts: Vec<String> = Vec::new();
    let mut current_unsafe_string_parts: Vec<String> = Vec::new();

    fn flush_strings<F>(
        current_string_parts: &mut Vec<String>,
        result: &mut Vec<LangSpecArgument>,
        create_variant: F,
    ) where
        F: FnOnce(String) -> LangSpecArgument,
    {
        if !current_string_parts.is_empty() {
            let merged_content: String = current_string_parts.join("");
            result.push(create_variant(merged_content));
            current_string_parts.clear();
        }
    }

    fn flush_safe_strings(
        current_string_parts: &mut Vec<String>,
        result: &mut Vec<LangSpecArgument>,
    ) {
        flush_strings(current_string_parts, result, |s| {
            LangSpecArgument::SafeString(s)
        });
    }

    fn flush_unsafe_strings(
        current_string_parts: &mut Vec<String>,
        result: &mut Vec<LangSpecArgument>,
    ) {
        flush_strings(current_string_parts, result, |s| {
            LangSpecArgument::UnsafeString(s)
        });
    }

    for item in items {
        match item {
            LangSpecArgument::SafeString(content) => {
                // If we were collecting UnsafeString, flush it first
                flush_unsafe_strings(&mut current_unsafe_string_parts, &mut result);
                // Add to SafeString buffer
                current_safe_string_parts.push(content);
            }
            LangSpecArgument::UnsafeString(content) => {
                // If we were collecting SafeString, flush it first
                flush_safe_strings(&mut current_safe_string_parts, &mut result);
                // Add to UnsafeString buffer
                current_unsafe_string_parts.push(content);
            }
            _ => {
                // Not a string - flush both types and add this item
                flush_safe_strings(&mut current_safe_string_parts, &mut result);
                flush_unsafe_strings(&mut current_unsafe_string_parts, &mut result);
                result.push(item);
            }
        }
    }

    // Flush and join any remaining accumulated strings
    flush_safe_strings(&mut current_safe_string_parts, &mut result);
    flush_unsafe_strings(&mut current_unsafe_string_parts, &mut result);

    result
}

fn format_expr_node(
    node_class_name: &str,
    token: &Token,
    content: &str,
    used_variables: &Vec<Token>,
) -> LangSpecArgument {
    let start_pos = token.start_index;
    let end_pos = token.end_index;

    let var_names: Vec<String> = used_variables
        .iter()
        .map(|token| token.content.clone())
        .collect();

    // E.g. `ExprNode(source, (14, 19), """expr""", ("var1", "var2"))`
    //      `TemplateNode(source, (14, 19), """template""", ("var1", "var2"))`
    LangSpecArgument::Struct(LangSpecStruct {
        name: node_class_name.to_string(),
        arguments: vec![
            // Argument 1: `source` - original template source string as variable used for error reporting
            LangSpecArgument::Variable("source".to_string()),
            // Argument 2: `(start, end)` - positional metadata for error reporting
            LangSpecArgument::Tuple(vec![
                LangSpecArgument::Int(start_pos),
                LangSpecArgument::Int(end_pos),
            ]),
            // Argument 3: `"""expr"""` - expression to evaluate (unsafe string)
            LangSpecArgument::UnsafeString(content.to_string()),
            // Argument 4: `("var1", "var2")` - tuple of variables used in the expression (safe strings)
            LangSpecArgument::Tuple(
                var_names
                    .iter()
                    .map(|name| LangSpecArgument::SafeString(name.clone()))
                    .collect(),
            ),
        ],
    })
}

/// Given a mutable iterator of TemplateElements, consume the following nodes
/// for as long as they are Nodes and match `node_names`.
///
/// Stop consuming when:
/// - The next element is not a Node
/// - The next element is a Node, but does not match `node_names`
///
/// Return a vector of the consumed nodes, or an empty vector if no nodes were consumed.
fn consume_nodes_into_group(
    elements_iter: &mut Peekable<IntoIter<TemplateElement>>,
    node_names: &[&str],
) -> Vec<Node> {
    let mut group = Vec::new();

    // Consume following nodes while the next element is a Node and matches `node_names`
    while let Some(next_element) = elements_iter.peek() {
        if let TemplateElement::Node(next_node) = next_element {
            if node_names.contains(&next_node.tag_name()) {
                // Pull this node from the iterator and add it to the group
                if let Some(TemplateElement::Node(node)) = elements_iter.next() {
                    group.push(node);
                }
            } else {
                // Not part of the group, stop consuming
                break;
            }
        } else {
            // Not a node, stop consuming
            break;
        }
    }

    group
}

/// Wraps elements to convert control flow attributes (`c-if="..."`)
/// into control flow nodes (`<c-if cond="...">...</c-if>`).
///
/// For each element that is a Node:
/// - If it's already a control flow tag (`<c-if>`, etc), leave it as is. These should NEVER contain
///   other `c-*` attributes.
/// - If it has control flow attributes, wrap it in the appropriate control flow node
///   (e.g. `<div c-if="...">...</div>` -> `<c-if cond="..."><div>...</div></c-if>`)
///
/// If there is multiple control flow attributes on a single node (e.g. both `c-if` and `c-for`),
/// then `c-if` has precedence over `c-for`. This is defined by the order of the groups in `CONTROL_FLOW_GROUPS`.
///
/// E.g.
/// ```html
/// <div c-for="item in items" c-if="item.is_visible" c-class="item.class">...</div>
/// ```
///
/// Will be wrapped as:
/// ```html
/// <c-if cond="item.is_visible">
///   <c-for each="item in items">
///     <div c-class="item.class">...</div>
///   </c-for>
/// </c-if>
/// ```
fn wrap_nodes_with_control_flow_attrs(
    elements: Vec<TemplateElement>,
) -> Result<Vec<TemplateElement>, CompileError> {
    let mut processed: Vec<TemplateElement> = Vec::new();

    for element in elements {
        match element {
            // Text or Expr - keep as is
            TemplateElement::Text(_) | TemplateElement::Expr(_) => processed.push(element),

            // Node - check if it's a control flow tag or has control flow attributes
            TemplateElement::Node(node) => {
                let tag_name = node.tag_name();

                // Check if this is already a control flow tag
                let is_control_flow_tag = CONTROL_FLOW_TAGS.contains(tag_name);

                // If already a control flow tag, then keep as is
                if is_control_flow_tag {
                    processed.push(TemplateElement::Node(node));
                    continue;
                }

                // Check whether this tag even has control flow attributes. And if not, keep it as is
                // NOTE: `.any()` for an empty iterator evaluates to false
                let node_attr_names = node
                    .attrs()
                    .iter()
                    .map(|attr| attr.key.content.clone())
                    .collect::<Vec<String>>();
                let has_control_flow_attr = node_attr_names
                    .iter()
                    .any(|attr_name| CONTROL_FLOW_TAGS.contains(attr_name.as_str()));
                if !has_control_flow_attr {
                    processed.push(TemplateElement::Node(node));
                    continue;
                }

                // Check for control flow attributes group by group (preserving precedence)
                // So we first search for `c-if`/`c-elif`/`c-else`, and only after NOT finding these,
                // we continue onto `c-for`/`c-empty`.
                let mut wrapped_node = node;
                for group in CONTROL_FLOW_GROUPS {
                    // Find the first control flow attribute from this group
                    // We need to check attributes before moving the node
                    let attr_to_wrap = wrapped_node
                        .attrs()
                        .iter()
                        .enumerate()
                        .find(|(_, attr)| group.contains(&attr.key.content.as_str()));

                    // No attribute matched current group, retry with next group.
                    if attr_to_wrap.is_none() {
                        continue;
                    }

                    // Found a control flow attribute - wrap the node
                    // Use the attribute name as the tag name (e.g. `c-if` -> `<c-if>`).
                    let (attr_index, attr) = attr_to_wrap.unwrap();
                    let attr_name = attr.key.content.clone();

                    // Remove the control flow attribute from the original node
                    // and use it to wrap the original node.
                    wrapped_node = _remove_attr_and_wrap_in_control_flow(
                        wrapped_node,
                        attr_index,
                        &attr_name,
                    )?;

                    // Stop processing subsequent control flow attributes on the original node
                    // after we've process the first one.
                    //
                    // In other words, if we have a tag like `<div c-if="x" c-for="y">`,
                    // we now we only convert it to:
                    // ```html
                    // <c-if cond="x">
                    //   <div c-for="y">
                    // </c-if>
                    // ```
                    //
                    // And it will be only in the future when the parsing gets to the body of the generated `<c-if>` tag
                    // that we come across the inner `<div c-for="y">` node again, and convert it to:
                    // ```html
                    // <c-for each="y">
                    //   <div>...</div>
                    // </c-for>
                    // ```
                    //
                    // The reason for this is that the original Node got consumed during wrapping,
                    // so we'd need to search for the inner node again in the body of the generated `<c-if>` tag,
                    // clone it, process it, reassign it, and then doing that recursively for each control flow attribute...
                    //
                    // Instead, a simpler logic is to just rely on the main walking logic to bring us back to the inner node later.
                    break;
                }

                processed.push(TemplateElement::Node(wrapped_node));
            }
        }
    }

    Ok(processed)
}

/// Remove a control flow attribute from a node and wrap the node in a control flow node.
///
/// The control flow attribute's value becomes an attribute on the new control flow node:
/// - `c-if`/`c-elif` → `cond` attribute
/// - `c-for` → `each` attribute
/// - `c-else`/`c-empty` → no attribute (boolean)
fn _remove_attr_and_wrap_in_control_flow(
    mut node: Node,
    attr_index: usize,
    attr_name: &str,
) -> Result<Node, CompileError> {
    // Remove the attribute from the original node
    let attr = match &mut node {
        Node::WithBody { start_tag, .. } => start_tag.attrs.remove(attr_index),
        Node::SelfClosing { start_tag, .. } => start_tag.attrs.remove(attr_index),
    };

    // TAG_ATTR_RULES already contains the info about which tag can have which attributes.
    // So we reuse that so that TAG_ATTR_RULES can remain the source of truth.
    let maybe_tag_rules = TAG_ATTR_RULES.get(attr_name);
    if maybe_tag_rules.is_none() {
        return Err(CompileError::Generic(format!(
            "Unexpected TagRules for control flow tag '{}': not found in rules",
            attr_name
        )));
    }
    let tag_rules = maybe_tag_rules.unwrap();

    // Check allowed_attrs to determine which attribute to use
    let maybe_allowed_attrs = tag_rules.allowed_attrs.as_ref();
    if maybe_allowed_attrs.is_none() {
        // `None` means "allows any attributes", but for control flow tags, this shouldn't happen
        return Err(CompileError::Generic(format!(
            "Unexpected TagRules for control flow tag '{}': allows any attributes",
            attr_name
        )));
    }
    let allowed_groups = maybe_allowed_attrs.unwrap();

    // Create the new attribute for the control flow node, e.g.:
    // - `cond="..."` for `<c-if>`
    // - `each="..."` for `<c-for>`
    // - None for `<c-else>`/`<c-empty>` (boolean attributes).
    let new_attr = if allowed_groups.is_empty() {
        // No attributes allowed (e.g., c-else, c-empty)
        None
    } else {
        // For control flow tags, there should be at most one group with exactly one attribute
        if allowed_groups.len() > 1 {
            return Err(CompileError::Generic(format!(
                "Unexpected TagRules for control flow tag '{}': tag allows multiple attributes, expected at most one",
                attr_name
            )));
        }

        let group = &allowed_groups[0];
        if group.len() > 1 {
            return Err(CompileError::Generic(format!(
                "Unexpected TagRules for control flow tag '{}': tag allows multiple attributes, expected at most one",
                attr_name
            )));
        }

        // Use the single allowed attribute from the single group
        let new_attr_name = group[0].clone();

        // Attribute has a value - create new attribute with the converted name
        // We need to create a new Token for the attribute key
        let attr_key_token = Token {
            content: new_attr_name.to_string(),
            start_index: attr.key.start_index,
            end_index: attr.key.start_index + new_attr_name.len(),
            line_col: attr.key.line_col,
        };

        Some(HtmlAttr {
            key: attr_key_token,
            ..attr
        })
    };

    _wrap_node_in_control_flow(node, attr_name, new_attr)
}

/// Wrap a node in a control flow node (e.g., wrap `<div c-if="...">` in `<c-if>`).
fn _wrap_node_in_control_flow(
    inner_node: Node,
    tag_name: &str,
    cf_attr: Option<HtmlAttr>,
) -> Result<Node, CompileError> {
    // Get metadata from the inner node (before moving it)
    let inner_start_tag = inner_node.start_tag();
    let inner_used_vars = inner_node.used_variables().clone();
    let inner_introduced_vars = inner_node.introduced_variables().clone();
    let inner_comments = inner_node.comments().clone();
    // Get slots from the inner node's body if it exists (WithBody), otherwise empty vec
    let inner_slots = match &inner_node {
        Node::WithBody { body, .. } => body.slots.clone(),
        Node::SelfClosing { .. } => vec![],
    };

    // The control flow attribute may contain comments, e.g. `<div c-if="1 # my comment">`.
    // Move those comments to the outer control flow tag.
    // Extract comments from the HtmlAttr before moving it
    let cf_comments = if let Some(ref attr) = cf_attr {
        attr.comments.clone()
    } else {
        vec![]
    };

    // This is where we assign the `c-if=""` or `c-for=""` attributes from the inner node
    // to the control flow node as `cond=""` or `each=""`.
    let mut cf_attrs = Vec::new();
    if let Some(attr) = cf_attr {
        cf_attrs.push(attr);
    }

    let cf_start_tag = HtmlStartTag {
        // Use the inner node's start token for the outer start tag.
        // Thus, if the outer tag ever raises an error (e.g. error in the `cond=""` attribute),
        // then the error reporting will point to the original start tag that has the `c-if`/`c-for` attribute.
        token: inner_start_tag.token.clone(),
        // For the name token, we'll reuse the positional info of the inner token.
        // However, the content will be the outer tag name, e.g. `<c-if>` or `<c-for>`,
        // as that's used by `compile_template_body()` to identify the tag name.
        name: Token {
            content: tag_name.to_string(),
            start_index: inner_start_tag.token.start_index,
            end_index: inner_start_tag.token.end_index,
            line_col: inner_start_tag.token.line_col,
        },
        attrs: cf_attrs,
        // The outer control flow tag WRAPS the inner node, so it can't be self-closing.
        is_self_closing: false,
        // Copy comments from the HtmlAttr if present
        comments: cf_comments,
    };

    // Create the end tag for the control flow node
    // Use the inner node's end position for the outer end tag
    let (inner_end_start_pos, inner_end_end_pos, inner_end_line_col) = match &inner_node {
        Node::WithBody { end_tag, .. } => (
            end_tag.token.start_index,
            end_tag.token.end_index,
            end_tag.token.line_col,
        ),
        Node::SelfClosing { start_tag, .. } => (
            start_tag.token.start_index,
            start_tag.token.end_index,
            start_tag.token.line_col,
        ),
    };

    let cf_end_token = Token {
        // Again, we reuse the positional info of the inner token,
        // but set custom `content`, so that this end tag will be serialized correctly.
        content: format!("</{}>", tag_name),
        start_index: inner_end_start_pos,
        end_index: inner_end_end_pos,
        line_col: inner_end_line_col,
    };

    let cf_end_name_token = Token {
        content: tag_name.to_string(),
        start_index: cf_end_token.start_index + 2, // `</`
        end_index: cf_end_token.start_index + 3 + tag_name.len(), // `</>`
        line_col: (
            cf_end_token.line_col.0,
            cf_end_token.line_col.1 + 2, // `</`
        ),
    };

    let cf_end_tag = HtmlEndTag {
        token: cf_end_token,
        name: cf_end_name_token,
        comments: vec![],
    };

    // Create the body containing just the inner node
    let body = Template {
        elements: vec![TemplateElement::Node(inner_node)],
        comments: inner_comments,
        used_variables: inner_used_vars,
        slots: inner_slots,
    };

    // Create the outer control flow node
    Ok(Node::from_start_and_end_tags(
        cf_start_tag,
        cf_end_tag,
        body,
        inner_introduced_vars,
    ))
}
