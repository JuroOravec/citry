//! Render plan: a walkable lowering of the compiler IR (prototype).
//!
//! This is the visible-in-repo prototype from the render-plan design
//! (`docs/design/render_plan_rust.md`). A "render plan" is the compiled form a
//! Rust executor walks instead of the Python node tree. Today the compiler turns
//! a template into a Python *source string* that builds runtime node objects
//! (`compile_template` / `lang::python`); this module turns the *same*
//! intermediate form (`compile_template_body`) into a flat plan a Rust walk can
//! execute directly.
//!
//! Modelled in Rust: static text, `{{ expr }}` interpolation, the attribute
//! region of plain elements with simple attributes, control flow
//! (`<c-if>`/`<c-for>`), and child components (`<c-child>`), so the walk can drive
//! a whole component tree. Not modelled yet (the executor renders these by calling
//! back into the live Python node): slots, fills, nested-template attribute
//! values, and `class`/`style`/`c-bind` attribute regions. The plan body and the
//! Python `generate_template()` body list both come from the same coalesced
//! `compile_template_body` output, so they line up one-to-one by position (plan
//! entry `i` is Python node `i`); a control-flow branch body lines up the same way
//! with the node's runtime branch body, which is how the executor recurses into
//! it.
//!
//! The plan is intentionally host-agnostic: it carries no Python (or any host)
//! source, only static strings, an index, and the expression text. The executor
//! that walks it, and the per-language callbacks it makes, live in the host
//! binding crate (for Python, `citry_core_py`).

use crate::ast::Template;
use crate::compiler::compile_template_body;
use crate::constants::{
    COMPONENT_NODE, ELEMENT_ATTRS_NODE, EXPR_NODE, FOR_NODE, IF_NODE, TEMPLATE_ATTR_NODE,
};
use crate::error::CompileError;
use crate::lang::lang::{LangSpecArgument, LangSpecStruct};

/// One entry of a render plan body.
///
/// Entries are position-aligned with the Python `generate_template()` body list
/// (both come from the same coalesced IR), so `idx` reaches the live Python node
/// object for the crossings the executor must make.
#[derive(Debug, Clone, PartialEq)]
pub enum PlanNode {
    /// Static literal text or HTML. Appended verbatim: it is trusted template
    /// text, escaped at compile time only where the template author wrote markup.
    Text(String),
    /// A `{{ expr }}` interpolation.
    ///
    /// `idx` is the position of the matching node in the Python body list (the
    /// executor calls `evaluate(variables)` on it). `expr` and `used_vars` are
    /// carried for diagnostics and for the build-time, Python-side Const fold.
    Expr {
        idx: usize,
        expr: String,
        used_vars: Vec<String>,
    },
    /// The attribute region of a plain HTML element with at least one dynamic
    /// attribute, modelled in Rust for the common case (no `class`/`style`
    /// merge, no `c-bind` spread, no nested-template attribute value).
    ///
    /// `idx` is the position of the matching `ElementAttrsNode` in the Python
    /// body list; `keys` are the output attribute keys (the `c-` prefix already
    /// stripped) in source order, one per attribute. The executor resolves each
    /// attribute's value through the Python attribute object at the same index,
    /// then merges (last-one-wins, first-seen order) and formats in Rust.
    ElementAttrs { idx: usize, keys: Vec<String> },
    /// A `<c-if>`/`<c-elif>`/`<c-else>` conditional. `idx` is the position of the
    /// `IfNode` in the body list; `branches` are the lowered sub-plans, one per
    /// branch, position-aligned with the node's runtime branch bodies. The
    /// executor asks Python which branch matches, then walks that sub-plan.
    If {
        idx: usize,
        branches: Vec<Vec<PlanNode>>,
    },
    /// A `<c-for>` loop with an optional `<c-empty>` branch. `idx` is the position
    /// of the `ForNode`; `loop_body` is the lowered loop-body sub-plan and
    /// `empty_body` the optional empty-branch sub-plan. The executor asks Python
    /// for the per-iteration scopes (or the empty fallback) and walks the body.
    For {
        idx: usize,
        loop_body: Vec<PlanNode>,
        empty_body: Option<Vec<PlanNode>>,
    },
    /// A child-component tag (`<c-child>`). `idx` is the position of the
    /// `ComponentNode`. The executor asks Python to prepare the child (resolve
    /// kwargs, build the instance, run `template_data`, return the child's body,
    /// context, and its own render plan), then walks that plan: this is where the
    /// Rust walk drives across a component boundary.
    Component { idx: usize },
    /// Any node kind not modelled in Rust yet (slots, fills, nested-template
    /// attributes, class/style attribute regions). The executor renders it by
    /// calling `render(context)` on the Python node object at `idx`.
    Foreign { idx: usize, node: String },
}

/// A compiled render plan: a flat body the Rust executor walks.
#[derive(Debug, Clone, PartialEq)]
pub struct RenderPlan {
    pub body: Vec<PlanNode>,
}

impl RenderPlan {
    /// Number of body entries (text + nodes).
    pub fn len(&self) -> usize {
        self.body.len()
    }

    /// Whether the plan has no body entries.
    pub fn is_empty(&self) -> bool {
        self.body.is_empty()
    }
}

/// Lower a parsed template into a render plan.
///
/// Reuses the same `compile_template_body` output the string codegen consumes,
/// so control-flow grouping, string coalescing, and used-variable de-duplication
/// are already resolved (the raw AST is not, which is why we start from the IR,
/// not the parse tree).
pub fn serialize_render_plan(template: Template) -> Result<RenderPlan, CompileError> {
    let body_items = compile_template_body(template)?;
    Ok(RenderPlan {
        body: lower_body(body_items),
    })
}

/// Lower a coalesced IR body (a list of strings and node structs) into a list of
/// plan entries. Each entry's `idx` is its position in this body, so it lines up
/// with the runtime node list for the same body (the root body, or a control-flow
/// branch body, which are compiled the same way).
fn lower_body(items: Vec<LangSpecArgument>) -> Vec<PlanNode> {
    items
        .into_iter()
        .enumerate()
        .map(|(idx, item)| lower_item(idx, item))
        .collect()
}

/// Lower one IR item into a plan entry, keeping its body-list position in `idx`.
fn lower_item(idx: usize, item: LangSpecArgument) -> PlanNode {
    match item {
        // After coalescing, static content is a single string item.
        LangSpecArgument::UnsafeString(s) | LangSpecArgument::SafeString(s) => PlanNode::Text(s),
        LangSpecArgument::Struct(s) => lower_struct(idx, s),
        // A bare body item should only ever be a string or a node struct after
        // coalescing; treat anything else as foreign so the executor stays correct.
        _ => PlanNode::Foreign {
            idx,
            node: "unknown".to_string(),
        },
    }
}

/// Dispatch a node struct to the matching plan entry. Unmodelled kinds (and
/// modelled kinds that hit an unsupported shape) become `Foreign`.
fn lower_struct(idx: usize, s: LangSpecStruct) -> PlanNode {
    let LangSpecStruct { name, arguments } = s;
    match name.as_str() {
        EXPR_NODE => {
            let (expr, used_vars) = extract_expr_node(&arguments);
            PlanNode::Expr {
                idx,
                expr,
                used_vars,
            }
        }
        // Model the attribute region when every attribute is a simple key/value
        // (static or single expression). class/style merging, a c-bind spread, or
        // a nested-template value falls back to rendering the node in Python.
        ELEMENT_ATTRS_NODE => match lower_element_attrs_keys(&arguments) {
            Some(keys) => PlanNode::ElementAttrs { idx, keys },
            None => PlanNode::Foreign { idx, node: name },
        },
        IF_NODE => lower_control_flow(idx, name, arguments, false),
        FOR_NODE => lower_control_flow(idx, name, arguments, true),
        COMPONENT_NODE => PlanNode::Component { idx },
        _ => PlanNode::Foreign { idx, node: name },
    }
}

/// Lower an `IfNode`/`ForNode` struct by recursively lowering each branch body.
/// Argument order is `(source, (branch...), (used_vars...))`, and each branch is
/// `((start, end), (attrs...), [body...], (introduced...))` (see
/// `compiler::compile_control_flow_node`). For a `ForNode`, branch 0 is the loop
/// body and branch 1 (when present) is the `<c-empty>` body.
fn lower_control_flow(
    idx: usize,
    name: String,
    arguments: Vec<LangSpecArgument>,
    is_for: bool,
) -> PlanNode {
    let branches_ir = match arguments.into_iter().nth(1) {
        Some(LangSpecArgument::Tuple(branches)) => branches,
        _ => return PlanNode::Foreign { idx, node: name },
    };
    let mut sub_plans: Vec<Vec<PlanNode>> = Vec::with_capacity(branches_ir.len());
    for branch in branches_ir {
        match extract_branch_body(branch) {
            Some(body_items) => sub_plans.push(lower_body(body_items)),
            None => return PlanNode::Foreign { idx, node: name },
        }
    }
    if is_for {
        let mut it = sub_plans.into_iter();
        let loop_body = it.next().unwrap_or_default();
        let empty_body = it.next();
        PlanNode::For {
            idx,
            loop_body,
            empty_body,
        }
    } else {
        PlanNode::If {
            idx,
            branches: sub_plans,
        }
    }
}

/// Pull the body item list out of one control-flow branch tuple
/// `((start, end), (attrs...), [body...], (introduced...))`; the body is at
/// index 2.
fn extract_branch_body(branch: LangSpecArgument) -> Option<Vec<LangSpecArgument>> {
    let parts = match branch {
        LangSpecArgument::Tuple(parts) => parts,
        _ => return None,
    };
    match parts.into_iter().nth(2) {
        Some(LangSpecArgument::List(items)) => Some(items),
        _ => None,
    }
}

/// Pull the expression text and used-variable names out of an `ExprNode` IR
/// struct, whose argument order is
/// `(source, (start, end), """expr""", ("var1", ...))`
/// (see `compiler::format_expr_node`).
fn extract_expr_node(args: &[LangSpecArgument]) -> (String, Vec<String>) {
    let expr = match args.get(2) {
        Some(LangSpecArgument::UnsafeString(s)) => s.clone(),
        _ => String::new(),
    };
    let used_vars = match args.get(3) {
        Some(LangSpecArgument::Tuple(items)) => items
            .iter()
            .filter_map(|a| match a {
                LangSpecArgument::SafeString(v) => Some(v.clone()),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    };
    (expr, used_vars)
}

/// Extract the output attribute keys from an `ElementAttrsNode` IR struct
/// (argument order `(source, (start, end), (HtmlAttr...), (used_vars...))`),
/// or `None` if the region uses a form this prototype does not model in Rust: a
/// `class`/`style` value (these merge across contributions), a `c-bind` spread,
/// or a nested-template attribute value.
fn lower_element_attrs_keys(args: &[LangSpecArgument]) -> Option<Vec<String>> {
    let attrs = match args.get(2) {
        Some(LangSpecArgument::Tuple(attrs)) => attrs,
        _ => return None,
    };
    let mut keys = Vec::with_capacity(attrs.len());
    for attr in attrs {
        let s = match attr {
            LangSpecArgument::Struct(s) => s,
            _ => return None,
        };
        if s.name == TEMPLATE_ATTR_NODE {
            return None;
        }
        let raw_key = match s.arguments.get(2) {
            Some(LangSpecArgument::UnsafeString(k)) => k,
            _ => return None,
        };
        if raw_key == "c-bind" {
            return None;
        }
        let out_key = raw_key.strip_prefix("c-").unwrap_or(raw_key);
        if out_key == "class" || out_key == "style" {
            return None;
        }
        keys.push(out_key.to_string());
    }
    Some(keys)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parser::parse_template;

    fn plan_for(src: &str) -> RenderPlan {
        let template = parse_template(src, None, None).expect("parse failed");
        serialize_render_plan(template).expect("serialize failed")
    }

    #[test]
    fn static_text_is_one_text_node() {
        let plan = plan_for("<p>hello</p>");
        assert_eq!(plan.body, vec![PlanNode::Text("<p>hello</p>".to_string())]);
    }

    #[test]
    fn interpolation_becomes_expr_aligned_by_position() {
        let plan = plan_for("<p>{{ name }}</p>");
        // <p>  /  {{ name }}  /  </p>  -> Text, Expr, Text
        assert_eq!(plan.body.len(), 3);
        assert!(matches!(plan.body[0], PlanNode::Text(_)));
        match &plan.body[1] {
            PlanNode::Expr {
                idx,
                expr,
                used_vars,
            } => {
                assert_eq!(*idx, 1);
                assert_eq!(expr.trim(), "name");
                assert_eq!(used_vars, &vec!["name".to_string()]);
            }
            other => panic!("expected Expr, got {other:?}"),
        }
        assert!(matches!(plan.body[2], PlanNode::Text(_)));
    }

    #[test]
    fn class_attr_element_stays_foreign() {
        // A `class` value merges across contributions, so the region is left to
        // Python.
        let plan = plan_for(r#"<div c-class="cls">x</div>"#);
        assert!(plan
            .body
            .iter()
            .any(|n| matches!(n, PlanNode::Foreign { node, .. } if node == "ElementAttrsNode")));
    }

    #[test]
    fn simple_dynamic_attrs_are_modelled() {
        // id + a static attr, no class/style/bind: modelled in Rust with the
        // output keys (the `c-` prefix stripped).
        let plan = plan_for(r#"<div c-id="x" role="button">y</div>"#);
        let attrs = plan
            .body
            .iter()
            .find_map(|n| match n {
                PlanNode::ElementAttrs { keys, .. } => Some(keys.clone()),
                _ => None,
            })
            .expect("expected a modelled ElementAttrs node");
        assert_eq!(attrs, vec!["id".to_string(), "role".to_string()]);
    }

    #[test]
    fn if_node_lowers_each_branch_body() {
        let plan = plan_for(r#"<c-if cond="x">yes</c-if><c-else>no</c-else>"#);
        let branches = plan
            .body
            .iter()
            .find_map(|n| match n {
                PlanNode::If { branches, .. } => Some(branches.clone()),
                _ => None,
            })
            .expect("expected an If node");
        assert_eq!(branches.len(), 2);
        assert!(matches!(branches[0].as_slice(), [PlanNode::Text(t)] if t.as_str() == "yes"));
        assert!(matches!(branches[1].as_slice(), [PlanNode::Text(t)] if t.as_str() == "no"));
    }

    #[test]
    fn for_node_lowers_loop_and_empty_bodies() {
        let plan =
            plan_for(r#"<c-for each="item in items">{{ item }}</c-for><c-empty>none</c-empty>"#);
        let (loop_body, empty_body) = plan
            .body
            .iter()
            .find_map(|n| match n {
                PlanNode::For {
                    loop_body,
                    empty_body,
                    ..
                } => Some((loop_body.clone(), empty_body.clone())),
                _ => None,
            })
            .expect("expected a For node");
        assert!(matches!(loop_body.as_slice(), [PlanNode::Expr { .. }]));
        let empty = empty_body.expect("expected an empty branch");
        assert!(matches!(empty.as_slice(), [PlanNode::Text(t)] if t.as_str() == "none"));
    }

    #[test]
    fn component_tag_is_modelled() {
        let plan = plan_for("<c-button>x</c-button>");
        assert!(plan
            .body
            .iter()
            .any(|n| matches!(n, PlanNode::Component { .. })));
    }
}
