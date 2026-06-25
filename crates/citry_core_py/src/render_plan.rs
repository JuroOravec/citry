//! PyO3 binding for the render-plan prototype.
//!
//! Exposes `compile_render_plan(template)` (a sibling to `compile_template`) and
//! a `RenderPlan` class whose `render()` method walks the plan in Rust, crossing
//! into Python only where the design says it must: once per `{{ expr }}` to
//! evaluate the (Python-compiled) expression, and once per not-yet-modelled
//! ("foreign") node to render it. Static text and the HTML assembly/escaping are
//! done in Rust. This is the measurable core of the render-plan design: the same
//! body, walked in Rust vs walked by the Python `_render_body`, byte-identical.
//!
//! What is modelled in Rust here: `Text`, `{{ expr }}` interpolation of scalar
//! values (escaped to match `markupsafe`, with the `__html__` trust protocol and
//! `None` handled), simple element attribute regions, control flow
//! (`<c-if>`/`<c-for>`), and child components, so the Rust walk can drive a whole
//! component tree. Three small Python helpers keep the parts that need the real
//! node machinery faithful: branch selection, loop iteration, and child-component
//! preparation (build the instance, run `template_data`, hand back the child's
//! body, context, and its own plan). Slots, fills, `on_render` hooks, and
//! `class`/`style`/`c-bind` attribute regions stay Python callbacks, so the
//! executor stays correct on any body while the modelled fast path avoids the
//! per-node Python round-trip.

use std::collections::HashMap;

use pyo3::exceptions::{PySyntaxError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyList, PyString};

use citry_template_parser::Template;
use citry_template_parser::error::CompileError;
use citry_template_parser::render_plan::{PlanNode, RenderPlan, serialize_render_plan};

/// Map a compile error to the same Python exception type the string compiler uses.
fn compile_error_to_py(e: CompileError) -> PyErr {
    match e {
        CompileError::Syntax(_) => PySyntaxError::new_err(e.to_string()),
        CompileError::Generic(_) => PyValueError::new_err(e.to_string()),
    }
}

/// Append `s` to `out`, escaping the five HTML-significant characters exactly as
/// `markupsafe` does (`& < > " '` -> `&amp; &lt; &gt; &#34; &#39;`). Matching the
/// runtime escaper byte-for-byte is what lets the Rust walk be a drop-in.
fn escape_html_into(s: &str, out: &mut String) {
    for ch in s.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&#34;"),
            '\'' => out.push_str("&#39;"),
            _ => out.push(ch),
        }
    }
}

/// Append `escape_to_str(value)`: a value carrying `__html__` (a trusted
/// `SafeString`) contributes its HTML unescaped, anything else contributes
/// `escape(str(value))`. The caller has already handled `None`/`False`/`True`.
fn escape_to_str_into(value: &Bound<'_, PyAny>, out: &mut String) -> PyResult<()> {
    if value.hasattr("__html__")? {
        let html = value.call_method0("__html__")?;
        out.push_str(&html.str()?.extract::<String>()?);
    } else {
        let text = value.str()?.extract::<String>()?;
        escape_html_into(&text, out);
    }
    Ok(())
}

/// The scalar path of `_render_value`: `None` -> empty; anything else ->
/// `escape_to_str`. Slots, elements, and already-rendered subtrees (the
/// component-machinery path) are left to Python, so the harness drives only
/// scalar-valued expressions and this stays byte-identical.
fn render_value_into(value: &Bound<'_, PyAny>, out: &mut String) -> PyResult<()> {
    if value.is_none() {
        return Ok(());
    }
    escape_to_str_into(value, out)
}

/// Format a resolved attribute region into Rust, mirroring `format_attrs` and
/// `ElementAttrsNode._format` for the common case: `None`/`False` omit the
/// attribute, `True` renders the bare key, anything else renders `key="value"`
/// (key and value escaped). The whole chunk gets a single leading space, or is
/// empty when every attribute resolved away.
fn format_attrs_into(
    order: &[String],
    values: &HashMap<String, Bound<'_, PyAny>>,
    out: &mut String,
) -> PyResult<()> {
    let mut chunk = String::new();
    for key in order {
        let value = &values[key];
        if value.is_none() {
            continue;
        }
        if value.is_instance_of::<PyBool>() {
            // `value is True` renders the bare attribute; `value is False` omits it.
            if value.extract::<bool>()? {
                if !chunk.is_empty() {
                    chunk.push(' ');
                }
                escape_html_into(key, &mut chunk);
            }
            continue;
        }
        if !chunk.is_empty() {
            chunk.push(' ');
        }
        escape_html_into(key, &mut chunk);
        chunk.push_str("=\"");
        escape_to_str_into(value, &mut chunk)?;
        chunk.push('"');
    }
    if !chunk.is_empty() {
        out.push(' ');
        out.push_str(&chunk);
    }
    Ok(())
}

/// The Python callables the walk needs for control flow. They are invariant for
/// the whole render, so they ride along the recursion as one reference.
struct Helpers<'a, 'py> {
    /// `(if_node, context) -> int`: the index of the matching `<c-if>` branch, or -1.
    if_select: &'a Bound<'py, PyAny>,
    /// `(for_node, context) -> (loop_contexts, empty_context)`: the per-iteration
    /// scopes for the loop body, plus the `<c-empty>` context (or `None`).
    for_iter: &'a Bound<'py, PyAny>,
    /// `(component_node, context) -> (child_body, child_context, child_plan)`:
    /// build the child component and hand back its body, render context, and own
    /// `RenderPlan`, so the walk can drive across the component boundary.
    prepare: &'a Bound<'py, PyAny>,
    /// `(node, context) -> str`: render a node kind the walk does not model (a
    /// `<c-slot>`, a nested-template attribute, ...) and resolve it to a string
    /// (flatten nested renders, drive deferred children).
    render_foreign: &'a Bound<'py, PyAny>,
}

/// Walk one body's plan entries against its live node list, appending HTML to
/// `out`. Recurses into `<c-if>` branches and `<c-for>` iterations, where the
/// node list and variable scope change to match the body being walked.
fn walk<'py>(
    plan_nodes: &[PlanNode],
    node_list: &Bound<'py, PyAny>,
    variables: &Bound<'py, PyAny>,
    context: &Bound<'py, PyAny>,
    helpers: &Helpers<'_, 'py>,
    out: &mut String,
) -> PyResult<()> {
    for node in plan_nodes {
        match node {
            PlanNode::Text(s) => out.push_str(s),
            PlanNode::Expr { idx, .. } => {
                // The one modelled crossing: evaluate the Python-compiled
                // expression against the live (mutable) variables dict.
                let value = node_list
                    .get_item(*idx)?
                    .call_method1("evaluate", (variables,))?;
                render_value_into(&value, out)?;
            }
            PlanNode::ElementAttrs { idx, keys } => {
                // Resolve each attribute through its Python attribute object, then
                // merge (last-one-wins, first-seen order) and format in Rust.
                let attrs = node_list.get_item(*idx)?.getattr("attrs")?;
                let mut order: Vec<String> = Vec::with_capacity(keys.len());
                let mut values: HashMap<String, Bound<'py, PyAny>> =
                    HashMap::with_capacity(keys.len());
                for (j, key) in keys.iter().enumerate() {
                    let value = attrs.get_item(j)?.call_method1("resolve", (context,))?;
                    if !values.contains_key(key) {
                        order.push(key.clone());
                    }
                    values.insert(key.clone(), value);
                }
                format_attrs_into(&order, &values, out)?;
            }
            PlanNode::If { idx, branches } => {
                // Ask Python which branch matches, then walk that sub-plan against
                // the branch's runtime body list (`if_node.branches[bi][2]`).
                let if_node = node_list.get_item(*idx)?;
                let bi: isize = helpers.if_select.call1((&if_node, context))?.extract()?;
                if bi >= 0 {
                    let bi = bi as usize;
                    let branch_body = if_node.getattr("branches")?.get_item(bi)?.get_item(2)?;
                    walk(
                        &branches[bi],
                        &branch_body,
                        variables,
                        context,
                        helpers,
                        out,
                    )?;
                }
            }
            PlanNode::For {
                idx,
                loop_body,
                empty_body,
            } => {
                // Ask Python for the per-iteration scopes (faithful loop-variable
                // binding via the real ForNode), then walk the loop body once per
                // scope, or the empty body when there were no iterations.
                let for_node = node_list.get_item(*idx)?;
                let result = helpers.for_iter.call1((&for_node, context))?;
                let loop_contexts = result.get_item(0)?;
                let count = loop_contexts.len()?;
                if count > 0 {
                    let loop_nodes = for_node.getattr("branches")?.get_item(0)?.get_item(2)?;
                    for k in 0..count {
                        let child = loop_contexts.get_item(k)?;
                        let child_vars = child.getattr("variables")?;
                        walk(loop_body, &loop_nodes, &child_vars, &child, helpers, out)?;
                    }
                } else if let Some(empty) = empty_body {
                    let empty_ctx = result.get_item(1)?;
                    if !empty_ctx.is_none() {
                        let empty_nodes = for_node.getattr("branches")?.get_item(1)?.get_item(2)?;
                        let empty_vars = empty_ctx.getattr("variables")?;
                        walk(empty, &empty_nodes, &empty_vars, &empty_ctx, helpers, out)?;
                    }
                }
            }
            PlanNode::Component { idx } => {
                // Drive across a component boundary: Python prepares the child
                // (resolve kwargs, build the instance, run template_data, return
                // its body, context, and its own plan), then we walk that plan.
                let comp_node = node_list.get_item(*idx)?;
                let prepared = helpers.prepare.call1((&comp_node, context))?;
                let child_body = prepared.get_item(0)?;
                let child_ctx = prepared.get_item(1)?;
                let child_plan = prepared.get_item(2)?;
                let child_plan = child_plan.cast::<PyRenderPlan>()?;
                let child_plan_ref = child_plan.borrow();
                let child_vars = child_ctx.getattr("variables")?;
                walk(
                    &child_plan_ref.plan.body,
                    &child_body,
                    &child_vars,
                    &child_ctx,
                    helpers,
                    out,
                )?;
            }
            PlanNode::Foreign { idx, .. } => {
                // Not modelled in Rust: hand the node to Python, which renders it
                // and resolves the result to a string (slots flatten in the
                // writer scope; a component inside a fill drives back through here).
                let node = node_list.get_item(*idx)?;
                let s: String = helpers.render_foreign.call1((&node, context))?.extract()?;
                out.push_str(&s);
            }
        }
    }
    Ok(())
}

/// A compiled render plan exposed to Python.
#[pyclass(name = "RenderPlan", module = "citry_core._rust.render_plan")]
pub struct PyRenderPlan {
    plan: RenderPlan,
}

#[pymethods]
impl PyRenderPlan {
    /// Walk the plan and return the assembled HTML string.
    ///
    /// `body` is the live Python node list from `generate_template()` (its items
    /// line up one-to-one with the plan, by position). `variables` is the
    /// per-component scope passed to `{{ expr }}` evaluation. `context` is the
    /// `CitryContext`. `if_select` and `for_iter` are Python helpers the walk
    /// calls for `<c-if>` branch selection and `<c-for>` iteration (they reuse the
    /// real node machinery, so loop-variable scoping stays faithful).
    #[allow(clippy::too_many_arguments)]
    fn render<'py>(
        &self,
        body: &Bound<'py, PyAny>,
        variables: &Bound<'py, PyAny>,
        context: &Bound<'py, PyAny>,
        if_select: &Bound<'py, PyAny>,
        for_iter: &Bound<'py, PyAny>,
        prepare: &Bound<'py, PyAny>,
        render_foreign: &Bound<'py, PyAny>,
    ) -> PyResult<String> {
        let helpers = Helpers {
            if_select,
            for_iter,
            prepare,
            render_foreign,
        };
        let mut out = String::new();
        walk(
            &self.plan.body,
            body,
            variables,
            context,
            &helpers,
            &mut out,
        )?;
        Ok(out)
    }

    /// Number of plan entries (static-text and node entries).
    #[getter]
    fn node_count(&self) -> usize {
        self.plan.len()
    }

    /// A coarse description of each plan entry, for inspection and for the
    /// harness to confirm a body is fully modelled before timing it.
    /// Each is `"text"`, `"expr"`, or `"foreign:<NodeName>"`.
    fn kinds(&self) -> Vec<String> {
        self.plan
            .body
            .iter()
            .map(|n| match n {
                PlanNode::Text(_) => "text".to_string(),
                PlanNode::Expr { .. } => "expr".to_string(),
                PlanNode::ElementAttrs { .. } => "element_attrs".to_string(),
                PlanNode::If { .. } => "if".to_string(),
                PlanNode::For { .. } => "for".to_string(),
                PlanNode::Component { .. } => "component".to_string(),
                PlanNode::Foreign { node, .. } => format!("foreign:{node}"),
            })
            .collect()
    }

    fn __repr__(&self) -> String {
        format!("RenderPlan(nodes={})", self.plan.len())
    }
}

/// Compile a parsed `Template` into a `RenderPlan` (prototype sibling of
/// `compile_template`). `lang` is accepted for signature parity but unused: the
/// plan is host-agnostic and expression parsing already happened at parse time.
#[pyfunction]
#[pyo3(signature = (template, lang=None))]
pub fn compile_render_plan(template: Template, lang: Option<&str>) -> PyResult<PyRenderPlan> {
    let _ = lang;
    let plan = serialize_render_plan(template).map_err(compile_error_to_py)?;
    Ok(PyRenderPlan { plan })
}

/// Unwrap any number of nested `Const` markers (the transparent `_ConstProxy`),
/// matching `const_value`, so the `None`/special-type checks below see the real
/// value rather than the proxy.
fn unwrap_const<'py>(
    value: Bound<'py, PyAny>,
    const_proxy: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let mut current = value;
    while current.is_instance(const_proxy)? {
        current = current.getattr("__wrapped__")?;
    }
    Ok(current)
}

/// Whether an `ElementAttrsNode` is one the Rust fast path can format: every
/// attribute is a plain static/expression attribute (not a nested template), no
/// `c-bind` spread, and no `class`/`style` key (those merge structured values).
/// Mirrors `lower_element_attrs_keys` for the live (folded) node.
fn is_simple_attrs(
    node: &Bound<'_, PyAny>,
    template_attr_type: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let attrs = node.getattr("attrs")?;
    for j in 0..attrs.len()? {
        let attr = attrs.get_item(j)?;
        if attr.is_instance(template_attr_type)? {
            return Ok(false);
        }
        let raw_key: String = attr.getattr("key")?.extract()?;
        if raw_key == "c-bind" {
            return Ok(false);
        }
        let out_key = raw_key.strip_prefix("c-").unwrap_or(&raw_key);
        if out_key == "class" || out_key == "style" {
            return Ok(false);
        }
    }
    Ok(true)
}

/// Resolve and format a simple attribute region in Rust: resolve each attribute
/// through its Python node, merge last-one-wins in first-seen order, and format
/// (mirroring `merge_attrs` + `format_attrs`).
fn format_simple_attrs(
    node: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
    out: &mut String,
) -> PyResult<()> {
    let attrs = node.getattr("attrs")?;
    let n = attrs.len()?;
    let mut order: Vec<String> = Vec::with_capacity(n);
    let mut values: HashMap<String, Bound<'_, PyAny>> = HashMap::with_capacity(n);
    for j in 0..n {
        let attr = attrs.get_item(j)?;
        let raw_key: String = attr.getattr("key")?.extract()?;
        let out_key = raw_key.strip_prefix("c-").unwrap_or(&raw_key).to_string();
        let value = attr.call_method1("resolve", (context,))?;
        if !values.contains_key(&out_key) {
            order.push(out_key.clone());
        }
        values.insert(out_key, value);
    }
    format_attrs_into(&order, &values, out)
}

/// The production body executor: walks a const-folded body and returns a
/// `list[RenderPart]` matching `_render_body` part-for-part. Static text, simple
/// attribute regions, and scalar `{{ expr }}` interpolation are done in Rust;
/// every other node, and any non-scalar expression value (`Slot`/`CitryElement`/
/// `CitryRender`), is handed to a Python callback that returns the live part.
///
/// The invariant Python references (node classes for dispatch, the `Const`
/// proxy, the special value types, and the two callbacks) are captured once when
/// the engine is built; `render` is then called once per component body.
#[pyclass(name = "BodyEngine", module = "citry_core._rust.render_plan")]
pub struct BodyEngine {
    expr_type: Py<PyAny>,
    attrs_type: Py<PyAny>,
    template_attr_type: Py<PyAny>,
    const_proxy: Py<PyAny>,
    special_types: Py<PyAny>,
    /// `(value, context) -> RenderPart`: render a non-scalar expression value
    /// (`_render_value` plus the cross-context dependency merge).
    render_value: Py<PyAny>,
    /// `(node, context) -> RenderPart`: the per-node step for delegated nodes.
    render_node: Py<PyAny>,
    /// `(error, node, context) -> None`: attach the failing node's template
    /// position to an error before it propagates (the Python `_render_body`
    /// does this for every node; the Rust fast paths must too).
    attach_position: Py<PyAny>,
}

/// Run a fast-path branch and, on error, attach the failing node's template
/// position before re-raising (mirroring `_render_body`'s try/except). The
/// delegated `_render_node` path attaches its own position, so only the Rust
/// expression and attribute branches use this.
fn attach_on_err(
    py: Python<'_>,
    result: PyResult<()>,
    node: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
    attach_position: &Bound<'_, PyAny>,
) -> PyResult<()> {
    match result {
        Ok(()) => Ok(()),
        Err(err) => {
            let exc = err.value(py).clone();
            attach_position.call1((exc, node, context))?;
            Err(err)
        }
    }
}

/// Flush the accumulated text run as one string part, if non-empty. Coalescing
/// consecutive text/scalar/attribute output into a single part keeps the common
/// case to one Python list append instead of one per body item.
fn flush_run(py: Python<'_>, run: &mut String, parts: &Bound<'_, PyList>) -> PyResult<()> {
    if !run.is_empty() {
        parts.append(PyString::new(py, run))?;
        run.clear();
    }
    Ok(())
}

/// One entry of a lowered folded body. Static text is owned by Rust, so the walk
/// never crosses to fetch it; a node is kept by reference, classified once at
/// lower time so the walk never repeats `isinstance`.
enum PlanItem {
    Text(String),
    Expr(Py<PyAny>),
    Attrs(Py<PyAny>),
    Node(Py<PyAny>),
}

/// A const-folded body lowered for the Rust executor. Built once and cached per
/// `(component, const signature)` so each render walks it without per-item
/// `get_item` / `isinstance` crossings (the cost that made the naive walk slower
/// than the Python loop).
#[pyclass(name = "FoldedPlan", module = "citry_core._rust.render_plan")]
pub struct FoldedPlan {
    items: Vec<PlanItem>,
}

#[pymethods]
impl BodyEngine {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        expr_type: Py<PyAny>,
        attrs_type: Py<PyAny>,
        template_attr_type: Py<PyAny>,
        const_proxy: Py<PyAny>,
        special_types: Py<PyAny>,
        render_value: Py<PyAny>,
        render_node: Py<PyAny>,
        attach_position: Py<PyAny>,
    ) -> Self {
        BodyEngine {
            expr_type,
            attrs_type,
            template_attr_type,
            const_proxy,
            special_types,
            render_value,
            render_node,
            attach_position,
        }
    }

    /// Lower a const-folded body into a `FoldedPlan`: classify each item once
    /// (text, scalar-expression node, simple-attribute node, or a delegated
    /// node) and keep a reference to it. `attrs_fast_path` is false when
    /// `on_attrs_resolved` is subscribed, which keeps every attribute region on
    /// the delegated path so the hook still fires.
    fn lower(
        &self,
        py: Python<'_>,
        body: &Bound<'_, PyAny>,
        attrs_fast_path: bool,
    ) -> PyResult<FoldedPlan> {
        let expr_type = self.expr_type.bind(py);
        let attrs_type = self.attrs_type.bind(py);
        let template_attr_type = self.template_attr_type.bind(py);
        let n = body.len()?;
        let mut items = Vec::with_capacity(n);
        for i in 0..n {
            let item = body.get_item(i)?;
            if item.is_instance_of::<PyString>() {
                items.push(PlanItem::Text(item.extract::<String>()?));
            } else if item.is_instance(expr_type)? {
                items.push(PlanItem::Expr(item.unbind()));
            } else if attrs_fast_path
                && item.is_instance(attrs_type)?
                && is_simple_attrs(&item, template_attr_type)?
            {
                items.push(PlanItem::Attrs(item.unbind()));
            } else {
                items.push(PlanItem::Node(item.unbind()));
            }
        }
        Ok(FoldedPlan { items })
    }

    /// Walk a lowered `plan` against `variables`/`context`, returning the parts
    /// list (matching `_render_body` part-for-part). `sandboxed` is the instance's
    /// expression-sandbox mode, threaded to expression evaluation. Static text and
    /// scalar interpolation accumulate into one run flushed at object boundaries;
    /// nodes the walk does not model are delegated to Python. No per-item
    /// classification: the plan was classified once at lower time.
    fn render<'py>(
        &self,
        py: Python<'py>,
        plan: &Bound<'py, FoldedPlan>,
        variables: &Bound<'py, PyAny>,
        context: &Bound<'py, PyAny>,
        sandboxed: bool,
    ) -> PyResult<Bound<'py, PyList>> {
        let parts = PyList::empty(py);
        let const_proxy = self.const_proxy.bind(py);
        let special_types = self.special_types.bind(py);
        let render_value = self.render_value.bind(py);
        let render_node = self.render_node.bind(py);
        let attach_position = self.attach_position.bind(py);
        // evaluate(variables, sandboxed=...): the kwarg is the same all walk.
        let eval_kwargs = PyDict::new(py);
        eval_kwargs.set_item("sandboxed", sandboxed)?;

        let plan = plan.borrow();
        // Output of consecutive text / scalar-expression / simple-attribute items
        // accumulates here and is flushed as one part at an object boundary, so a
        // run of cheap items costs one Python list append rather than one per item.
        let mut run = String::new();
        for item in &plan.items {
            match item {
                PlanItem::Text(s) => run.push_str(s),
                PlanItem::Expr(node) => {
                    let node = node.bind(py);
                    let branch: PyResult<()> = (|| {
                        let value =
                            node.call_method("evaluate", (variables,), Some(&eval_kwargs))?;
                        let value = unwrap_const(value, const_proxy)?;
                        if value.is_none() {
                            // Empty string: contributes nothing to the run.
                        } else if value.is_instance(special_types)? {
                            // Slot / CitryElement / CitryRender: a live part, so
                            // flush the run, then the real _render_value (and the
                            // cross-context dependency merge it does).
                            flush_run(py, &mut run, &parts)?;
                            parts.append(render_value.call1((&value, context))?)?;
                        } else {
                            escape_to_str_into(&value, &mut run)?;
                        }
                        Ok(())
                    })();
                    attach_on_err(py, branch, node, context, attach_position)?;
                }
                PlanItem::Attrs(node) => {
                    let node = node.bind(py);
                    let branch: PyResult<()> = (|| {
                        format_simple_attrs(node, context, &mut run)?;
                        Ok(())
                    })();
                    attach_on_err(py, branch, node, context, attach_position)?;
                }
                PlanItem::Node(node) => {
                    // Flush the run, then hand the node to Python (it renders,
                    // attaches the error position, and merges dependencies).
                    flush_run(py, &mut run, &parts)?;
                    parts.append(render_node.call1((node.bind(py), context))?)?;
                }
            }
        }
        flush_run(py, &mut run, &parts)?;
        Ok(parts)
    }
}
