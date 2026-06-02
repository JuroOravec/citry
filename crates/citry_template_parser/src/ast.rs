//! # Abstract Syntax Tree (AST) for Citry template parser
//!
//! This module defines the core data structures that represent parsed Citry (V3)
//! templates as an Abstract Syntax Tree (AST).

use std::collections::HashSet;

use pyo3::prelude::*;

use crate::grammar::Rule;

// #########################################################
// TOKEN
// #########################################################

/// Represents a section in the template string.
///
/// The section may represent anything from variable references, Python expressions,
/// entire components or tags, plain text, or even comments.
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub struct Token {
    /// String content of the token
    #[pyo3(get)]
    pub content: String,
    /// Start index in the original input string
    #[pyo3(get)]
    pub start_index: usize,
    /// End index in the original input string
    #[pyo3(get)]
    pub end_index: usize,
    /// Line and column number
    #[pyo3(get)]
    pub line_col: (usize, usize),
}

#[pymethods]
impl Token {
    #[new]
    fn new(
        content: String,
        start_index: usize,
        end_index: usize,
        line_col: (usize, usize),
    ) -> Self {
        Self {
            content,
            start_index,
            end_index,
            line_col,
        }
    }

    fn __eq__(&self, other: &Token) -> bool {
        self.content == other.content
            && self.start_index == other.start_index
            && self.end_index == other.end_index
            && self.line_col == other.line_col
    }

    fn __repr__(&self) -> String {
        format!(
            "Token(content='{}', start_index={}, end_index={}, line_col={:?})",
            self.content, self.start_index, self.end_index, self.line_col
        )
    }
}

// Rust-only methods
impl Token {
    /// Create a Token from a pest Pair without applying any offsets
    ///
    /// This extracts the raw position information and content from the pair.
    pub fn from_pair(pair: &pest::iterators::Pair<'_, Rule>) -> Self {
        let span = pair.as_span();
        let (line, col) = pair.line_col();
        let content = pair.as_str().to_string();

        Self {
            content,
            start_index: span.start(),
            end_index: span.end(),
            line_col: (line, col),
        }
    }

    /// Create a Token from a pest Span without applying any offsets
    ///
    /// This extracts the raw position information and content from the span.
    pub fn from_span(span: pest::Span) -> Self {
        let (line, col) = span.start_pos().line_col();
        let content = span.as_str().to_string();

        Self {
            content,
            start_index: span.start(),
            end_index: span.end(),
            line_col: (line, col),
        }
    }

    pub fn as_span(&self) -> Option<pest::Span<'_>> {
        // Use 0 and content.len() because self.content is already the substring
        // that corresponds to start_index..end_index in the original input
        pest::Span::new(&self.content, 0, self.content.len())
    }

    pub fn as_span_with_input<'i>(&self, input: &'i str) -> Option<pest::Span<'i>> {
        pest::Span::new(input, self.start_index, self.end_index)
    }

    /// Apply column offsets to this token, adjusting content and positions
    ///
    /// # Arguments
    /// * `col_start_offset` - Offset to apply to start position (positive = skip chars at start, negative = extend before)
    /// * `col_end_offset` - Offset to apply to end position (positive = extend after, negative = skip chars at end)
    ///
    /// When offsets are non-zero, the content will be sliced to match the adjusted boundaries.
    ///
    /// # Examples
    /// For a comment `{# text #}`:
    /// - `col_start_offset: 2` skips `{#` at the start
    /// - `col_end_offset: -2` skips `#}` at the end
    pub fn crop_cols(mut self, col_start_offset: isize, col_end_offset: isize) -> Self {
        // Adjust indices
        self.start_index = (self.start_index as isize + col_start_offset) as usize;
        self.end_index = (self.end_index as isize + col_end_offset) as usize;

        // Adjust column (only on first line)
        let (line, col) = self.line_col;
        if line == 1 {
            self.line_col = (line, (col as isize + col_start_offset) as usize);
        }

        // Slice the content to match the adjusted boundaries
        if col_start_offset != 0 || col_end_offset != 0 {
            let content_start = col_start_offset.max(0) as usize;
            let content_end = (self.content.len() as isize + col_end_offset) as usize;
            if content_start < content_end && content_end <= self.content.len() {
                self.content = self.content[content_start..content_end].to_string();
            } else {
                self.content = String::new();
            }
        }

        self
    }

    /// Offset a token by adjusting its indices, line, and column positions.
    /// This is used when a token's positions need to be adjusted relative to a different source context.
    ///
    /// - `index_offset`: Amount to add to start_index and end_index
    /// - `line_offset`: Amount to add to the line number (lines are 1-indexed, so this is added directly)
    /// - `col_offset`: Amount to add to the column (only applied to the first line, columns are 1-indexed)
    pub fn offset(mut self, index_offset: usize, line_offset: usize, col_offset: usize) -> Self {
        // Adjust indices
        self.start_index += index_offset;
        self.end_index += index_offset;

        // Adjust line and column
        let (line, col) = self.line_col;
        let adjusted_line = line + line_offset;

        // Column offset only applies to the first line
        let adjusted_col = if line == 1 { col + col_offset } else { col };

        self.line_col = (adjusted_line, adjusted_col);
        self
    }
}

// #########################################################
// COMMENT
// #########################################################

/// Represents a template comment like `{# ... #}` or `<!-- ... -->`
///
/// - `{# ... #}` comments are NOT included in the output.
/// - `<!-- ... -->` comments ARE included in the output, and treated as text.
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub struct Comment {
    /// Token containing the entire comment span including `{# #}` or `<!-- ... -->` delimiters
    #[pyo3(get)]
    pub token: Token,
    /// Token for the comment text (without the delimiters)
    #[pyo3(get)]
    pub value: Token,
}

#[pymethods]
impl Comment {
    #[new]
    fn new(token: Token, value: Token) -> Self {
        Self { token, value }
    }

    fn __eq__(&self, other: &Comment) -> bool {
        self.token == other.token && self.value == other.value
    }

    fn __repr__(&self) -> String {
        format!("Comment(token={:?}, value={:?})", self.token, self.value)
    }
}

// #########################################################
// HTML ATTRIBUTE
// #########################################################

/// The kind of HTML attribute, determining how it should be processed
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub enum HtmlAttrKind {
    /// Static attribute - name doesn't start with `c-`, value interpreted literally
    ///
    /// May be a boolean attribute (no value), e.g. `disabled`,
    /// or with a value, e.g. `class="static_value"`.
    Static,
    /// Expression attribute - name starts with `c-`, value is a Python expression
    /// (whitespace-trimmed value does NOT start with `<...>` / end with `</...>`)
    ///
    /// May be a boolean attribute (no value), e.g. `c-disabled`,
    /// or with a value, e.g. `c-class="..."`.
    Expression,
    /// Template attribute - name starts with `c-`, value is a nested template
    /// (value DOES start/end with HTML tags)
    ///
    /// Cannot be boolean attribute, as value MUST start/end with HTML tags.
    Template,
}

#[pymethods]
impl HtmlAttrKind {
    fn __repr__(&self) -> String {
        match self {
            HtmlAttrKind::Static => "HtmlAttrKind::Static".to_string(),
            HtmlAttrKind::Expression => "HtmlAttrKind::Expression".to_string(),
            HtmlAttrKind::Template => "HtmlAttrKind::Template".to_string(),
        }
    }
}

/// Represents an HTML attribute
///
/// Attributes can be:
/// - Key-value pairs: `key="value"`, `key='value'`, `key=value`
/// - Boolean attributes: `disabled` (no value)
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub struct HtmlAttr {
    /// Token containing the entire attribute span
    #[pyo3(get)]
    pub token: Token,
    /// The attribute key/name
    #[pyo3(get)]
    pub key: Token,
    /// The attribute value with quotes (None for boolean attributes)
    #[pyo3(get)]
    pub value: Option<Token>,
    /// The attribute value without quotes (None for boolean attributes)
    #[pyo3(get)]
    pub inner_value: Option<Token>,
    /// Whether the value is quoted, e.g. `key="value"` or `key='value'`
    #[pyo3(get)]
    pub quote_char: Option<char>,
    /// The kind of attribute, determining how it should be processed
    pub kind: HtmlAttrKind,
    /// All comments found in the attribute
    #[pyo3(get)]
    pub comments: Vec<Comment>,
    /// All variables used in the attribute
    #[pyo3(get)]
    pub used_variables: Vec<Token>,
}

#[pymethods]
impl HtmlAttr {
    #[new]
    fn new(
        token: Token,
        key: Token,
        value: Option<Token>,
        inner_value: Option<Token>,
        quote_char: Option<char>,
        kind: HtmlAttrKind,
        comments: Vec<Comment>,
        used_variables: Vec<Token>,
    ) -> Self {
        Self {
            token,
            key,
            value,
            inner_value,
            quote_char,
            kind,
            comments,
            used_variables,
        }
    }

    fn __eq__(&self, other: &HtmlAttr) -> bool {
        self.token == other.token
            && self.key == other.key
            && self.value == other.value
            && self.inner_value == other.inner_value
            && self.quote_char == other.quote_char
            && self.kind == other.kind
            && self.comments == other.comments
            && self.used_variables == other.used_variables
    }

    fn __repr__(&self) -> String {
        format!(
            "HtmlAttr(token={:?}, key={:?}, value={:?}, inner_value={:?}, quote_char={:?}, kind={:?}, comments={:?}, used_variables={:?})",
            self.token, self.key, self.value, self.inner_value, self.quote_char, self.kind, self.comments, self.used_variables
        )
    }
}

// #########################################################
// HTML TAG
// #########################################################

/// Represents an HTML tag (start tag, or self-closing tag)
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub struct HtmlStartTag {
    /// Token containing the entire tag span including `<`, `>`, and `/` delimiters
    #[pyo3(get)]
    pub token: Token,
    /// The name of the tag
    #[pyo3(get)]
    pub name: Token,
    /// The attributes of the tag
    #[pyo3(get)]
    pub attrs: Vec<HtmlAttr>,
    /// Whether the tag is self-closing
    #[pyo3(get)]
    pub is_self_closing: bool,
    /// All comments found in the tag
    #[pyo3(get)]
    pub comments: Vec<Comment>,
}

#[pymethods]
impl HtmlStartTag {
    #[new]
    fn new(
        token: Token,
        name: Token,
        attrs: Vec<HtmlAttr>,
        is_self_closing: bool,
        comments: Vec<Comment>,
    ) -> Self {
        Self {
            token,
            name,
            attrs,
            is_self_closing,
            comments,
        }
    }

    fn __eq__(&self, other: &HtmlStartTag) -> bool {
        self.token == other.token
            && self.name == other.name
            && self.attrs == other.attrs
            && self.is_self_closing == other.is_self_closing
            && self.comments == other.comments
    }

    fn __repr__(&self) -> String {
        format!(
            "HtmlStartTag(token={:?}, name={:?}, attrs={:?}, is_self_closing={}, comments={:?})",
            self.token, self.name, self.attrs, self.is_self_closing, self.comments
        )
    }
}

/// Represents an HTML end tag
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub struct HtmlEndTag {
    /// Token containing the entire tag span including `<`, `>`, and `/` delimiters
    #[pyo3(get)]
    pub token: Token,
    /// The name of the tag
    #[pyo3(get)]
    pub name: Token,
    /// All comments found in the tag
    #[pyo3(get)]
    pub comments: Vec<Comment>,
}

#[pymethods]
impl HtmlEndTag {
    #[new]
    fn new(token: Token, name: Token, comments: Vec<Comment>) -> Self {
        Self {
            token,
            name,
            comments,
        }
    }

    fn __eq__(&self, other: &HtmlEndTag) -> bool {
        self.token == other.token && self.name == other.name && self.comments == other.comments
    }

    fn __repr__(&self) -> String {
        format!(
            "HtmlEndTag(token={:?}, name={:?}, comments={:?})",
            self.token, self.name, self.comments
        )
    }
}

// #########################################################
// EXPRESSION
// #########################################################

/// Represents a template expression `{{ ... }}`
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub struct Expr {
    /// Token containing the entire expression span including `{{ }}` delimiters
    #[pyo3(get)]
    pub token: Token,
    /// A single value inside the expression with optional filters
    #[pyo3(get)]
    pub value: Token,
    /// Variables that are used from the outside context
    #[pyo3(get)]
    pub used_variables: Vec<Token>,
    /// Comments found in the original source
    #[pyo3(get)]
    pub comments: Vec<Comment>,
}

#[pymethods]
impl Expr {
    #[new]
    fn new(token: Token, value: Token, used_variables: Vec<Token>, comments: Vec<Comment>) -> Self {
        Self {
            token,
            value,
            used_variables,
            comments,
        }
    }

    fn __eq__(&self, other: &Expr) -> bool {
        self.token == other.token
            && self.value == other.value
            && self.used_variables == other.used_variables
            && self.comments == other.comments
    }

    fn __repr__(&self) -> String {
        format!(
            "Expr(token={:?}, value={:?}, used_variables={:?}, comments={:?})",
            self.token, self.value, self.used_variables, self.comments
        )
    }
}

// #########################################################
// TEXT
// #########################################################

/// Represents plain text in a template
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub struct Text {
    /// Token containing the text content and position information
    #[pyo3(get)]
    pub token: Token,
}

#[pymethods]
impl Text {
    #[new]
    fn new(token: Token) -> Self {
        Self { token }
    }

    fn __eq__(&self, other: &Text) -> bool {
        self.token == other.token
    }

    fn __repr__(&self) -> String {
        format!("Text(token={:?})", self.token)
    }
}

// #########################################################
// AST NODE
// #########################################################

/// Represents a node in the template tree (AST version)
///
/// A node can be:
/// - An HTML element: `<div>...</div>`, `<img/>`
/// - A component: `<c-MyComp>...</c-MyComp>`, `<c-img/>`
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub enum Node {
    /// A node with a body (has opening tag, body content, and closing tag)
    WithBody {
        /// The start tag with attributes
        start_tag: HtmlStartTag,
        /// The end tag
        end_tag: HtmlEndTag,
        /// The body content (template elements inside the node)
        body: Template,
        /// All variables used both within the start tag and the body content
        used_variables: Vec<Token>,
        /// Variables introduced by this node (e.g., loop variables from `<c-for>`)
        introduced_variables: Vec<Token>,
        /// All comments found in the node (start/end tags and body content)
        comments: Vec<Comment>,
        /// Whether this node contains any `<c-fill>` tags in its body
        contains_fills: bool,
    },
    /// A self-closing node (has only a start tag, no body or end tag)
    SelfClosing {
        /// The start tag with attributes
        start_tag: HtmlStartTag,
        /// All variables used both within the start tag and the body content
        used_variables: Vec<Token>,
        /// Variables introduced by this node (e.g., loop variables from `<c-for>`)
        introduced_variables: Vec<Token>,
        /// All comments found in the node (start tag)
        comments: Vec<Comment>,
        /// Whether this node contains any `<c-fill>` tags in its body (always false for self-closing nodes)
        contains_fills: bool,
    },
}

#[pymethods]
impl Node {
    /// Get the name of the node
    #[getter]
    fn name(&self) -> String {
        self.tag_name().to_string()
    }

    fn __repr__(&self) -> String {
        match self {
            Node::WithBody {
                start_tag,
                end_tag,
                body,
                used_variables,
                introduced_variables,
                comments,
                contains_fills: _,
            } => format!(
                "Node::WithBody(start_tag={:?}, end_tag={:?}, body={:?}, used_variables={:?}, introduced_variables={:?}, comments={:?})",
                start_tag, end_tag, body, used_variables, introduced_variables, comments
            ),
            Node::SelfClosing {
                start_tag,
                used_variables,
                introduced_variables,
                comments,
                contains_fills: _,
            } => {
                format!("Node::SelfClosing(start_tag={:?}, used_variables={:?}, introduced_variables={:?}, comments={:?})", start_tag, used_variables, introduced_variables, comments)
            }
        }
    }
}

// Rust-only methods
impl Node {
    pub fn tag_name(&self) -> &str {
        match self {
            Node::WithBody { start_tag, .. } | Node::SelfClosing { start_tag, .. } => {
                start_tag.name.content.as_str()
            }
        }
    }

    pub fn attrs(&self) -> &Vec<HtmlAttr> {
        match self {
            Node::WithBody { start_tag, .. } | Node::SelfClosing { start_tag, .. } => {
                &start_tag.attrs
            }
        }
    }

    pub fn start_tag(&self) -> &HtmlStartTag {
        match self {
            Node::WithBody { start_tag, .. } | Node::SelfClosing { start_tag, .. } => start_tag,
        }
    }

    pub fn used_variables(&self) -> &Vec<Token> {
        match self {
            Node::WithBody { used_variables, .. } => used_variables,
            Node::SelfClosing { used_variables, .. } => used_variables,
        }
    }

    pub fn introduced_variables(&self) -> &Vec<Token> {
        match self {
            Node::WithBody {
                introduced_variables,
                ..
            } => introduced_variables,
            Node::SelfClosing {
                introduced_variables,
                ..
            } => introduced_variables,
        }
    }

    pub fn comments(&self) -> &Vec<Comment> {
        match self {
            Node::WithBody { comments, .. } => comments,
            Node::SelfClosing { comments, .. } => comments,
        }
    }

    pub fn contains_fills(&self) -> bool {
        match self {
            Node::WithBody { contains_fills, .. } => *contains_fills,
            Node::SelfClosing { contains_fills, .. } => *contains_fills,
        }
    }

    pub fn set_contains_fills(&mut self, contains_fills: bool) {
        match self {
            Node::WithBody {
                contains_fills: ref mut cf,
                ..
            } => *cf = contains_fills,
            Node::SelfClosing { .. } => {
                // Self-closing nodes never have fills
                // So we do nothing
            }
        }
    }

    pub fn from_start_and_end_tags(
        start_tag: HtmlStartTag,
        end_tag: HtmlEndTag,
        body: Template,
        introduced_variables: Vec<Token>,
    ) -> Self {
        // Extract comments and used variables from body
        let mut used_variables = body.used_variables.clone();
        let mut comments = body.comments.clone();

        // Extract comments from end tag
        // NOTE: End tags don't use variables
        let comments_from_end_tag = end_tag.comments.clone();
        comments.extend(comments_from_end_tag);

        // Extract comments and used variables from start tag and its attrs
        let used_variables_from_attrs: Vec<Token> = start_tag
            .attrs
            .iter()
            .flat_map(|attr| attr.used_variables.clone())
            .collect();
        let comments_from_attrs = start_tag
            .attrs
            .iter()
            .flat_map(|attr| attr.comments.clone());
        let comments_from_start_tag = start_tag.comments.clone();
        comments.extend(comments_from_attrs);
        comments.extend(comments_from_start_tag);
        used_variables.extend(used_variables_from_attrs);

        // Remove introduced variables from used_variables
        // This prevents variables introduced by this node (e.g., loop variables) from
        // being reported as required by the parent template
        let introduced_var_names: HashSet<&str> = introduced_variables
            .iter()
            .map(|v| v.content.as_str())
            .collect();
        used_variables.retain(|v| !introduced_var_names.contains(v.content.as_str()));

        Self::WithBody {
            start_tag,
            end_tag,
            body,
            used_variables,
            introduced_variables,
            comments,
            contains_fills: false, // Will be set in finalize_node
        }
    }
}

// #########################################################
// TEMPLATE ELEMENT
// #########################################################

/// Represents a single element in a template
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub enum TemplateElement {
    Node(Node),
    Expr(Expr),
    Text(Text),
}

#[pymethods]
impl TemplateElement {
    fn __repr__(&self) -> String {
        match self {
            TemplateElement::Node(node) => format!("TemplateElement::Node({:?})", node),
            TemplateElement::Expr(expr) => format!("TemplateElement::Expr({:?})", expr),
            TemplateElement::Text(text) => format!("TemplateElement::Text({:?})", text),
        }
    }
}

// #########################################################
// SLOT
// #########################################################

/// Represents a slot WITH KNOWN NAME, defined by a `<c-slot>` tag
///
/// At runtime, this will be used to validate whether the slots defined in the template
/// match the slots defined on the component.
///
/// E.g. if we had Python component:
/// ```py
/// class Table(Component):
///     class Slots:
///         foo: str
///         bar: str
/// ```
///
/// And the template contained:
///
/// ```html
/// <c-table>
///     <c-slot name="foo">
///         ...
///     </c-slot>
///     <c-slot name="fee">
///         ...
///     </c-slot>
/// </c-table>
/// ```
///
/// Then we can infer and raise as error that the component declared "bar",
/// but "bar" is missing, and instead there's "fee".
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub struct StaticNamedSlot {
    /// Token containing the slot name (from the `name` attribute's inner value)
    #[pyo3(get)]
    pub token: Token,
    /// Whether this slot is required
    /// - `None`: unknown (no explicit `required` attribute, but has `c-bind` or `c-required`)
    /// - `Some(true)`: required (has `required` attribute)
    /// - `Some(false)`: not required (no `required` attribute, nor `c-bind`, nor `c-required`)
    #[pyo3(get)]
    pub required: Option<bool>,
}

#[pymethods]
impl StaticNamedSlot {
    #[new]
    fn new(token: Token, required: Option<bool>) -> Self {
        Self { token, required }
    }

    fn __eq__(&self, other: &StaticNamedSlot) -> bool {
        self.token == other.token && self.required == other.required
    }

    fn __repr__(&self) -> String {
        format!(
            "StaticNamedSlot(token={:?}, required={:?})",
            self.token, self.required
        )
    }
}

// #########################################################
// TEMPLATE
// #########################################################

/// Represents a complete parsed template
#[pyclass]
#[derive(Debug, PartialEq, Clone)]
pub struct Template {
    /// The elements in the template
    #[pyo3(get)]
    pub elements: Vec<TemplateElement>,

    /// All comments found in the template (at any nesting level)
    /// This is populated only if comment collection is enabled during parsing
    #[pyo3(get)]
    pub comments: Vec<Comment>,

    /// Context variables that this Template needs (used variables from all tags and expressions)
    #[pyo3(get)]
    pub used_variables: Vec<Token>,

    /// All slots defined by `<c-slot>` tags (with static names) found in the template (at any nesting level)
    #[pyo3(get)]
    pub slots: Vec<StaticNamedSlot>,
}

#[pymethods]
impl Template {
    #[new]
    fn new(
        elements: Vec<TemplateElement>,
        comments: Option<Vec<Comment>>,
        used_variables: Vec<Token>,
        slots: Option<Vec<StaticNamedSlot>>,
    ) -> Self {
        Self {
            elements,
            comments: comments.unwrap_or_default(),
            used_variables,
            slots: slots.unwrap_or_default(),
        }
    }

    fn __eq__(&self, other: &Template) -> bool {
        self.elements == other.elements
            && self.comments == other.comments
            && self.used_variables == other.used_variables
            && self.slots == other.slots
    }

    fn __repr__(&self) -> String {
        format!(
            "Template(elements={:?}, used_variables={:?}, slots={:?})",
            self.elements, self.used_variables, self.slots
        )
    }
}
