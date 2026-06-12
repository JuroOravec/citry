pub mod html_transform;
pub mod safe_eval;
pub mod template_parser;

use pyo3::prelude::*;
use pyo3::types::PyFrozenSet;

use citry_template_parser::constants::HTML_VOID_ELEMENTS;
use citry_template_parser::{
    Comment, Expr, HtmlAttr, HtmlAttrKind, HtmlEndTag, HtmlStartTag, Node, StaticNamedSlot,
    TagRules, Template, TemplateElement, Text, Token,
};

use crate::html_transform::{mark_html, transform_html};
use crate::template_parser::{compile_template, parse_template};

/// Singular Python API that brings together all the other Rust crates.
/// Each crate is exposed as a submodule.
///
/// NOTE: The name of this function will be the name of the Python module.
///       It MUST match the `module-name` setting in `pyproject.toml` in `packages/py/citry_core/`.
#[pymodule]
fn _rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // HTML transformer
    let html_transform_mod = PyModule::new(m.py(), "html_transform")?;
    m.add_submodule(&html_transform_mod)?;
    html_transform_mod.add_function(wrap_pyfunction!(transform_html, &html_transform_mod)?)?;
    html_transform_mod.add_function(wrap_pyfunction!(mark_html, &html_transform_mod)?)?;

    // Safe eval
    let safe_eval_mod = PyModule::new(m.py(), "safe_eval")?;
    m.add_submodule(&safe_eval_mod)?;
    safe_eval_mod.add_function(wrap_pyfunction!(
        crate::safe_eval::safe_eval,
        &safe_eval_mod
    )?)?;

    // Template parser
    let template_parser_mod = PyModule::new(m.py(), "template_parser")?;
    m.add_submodule(&template_parser_mod)?;
    // Functions
    template_parser_mod.add_function(wrap_pyfunction!(parse_template, &template_parser_mod)?)?;
    template_parser_mod.add_function(wrap_pyfunction!(compile_template, &template_parser_mod)?)?;
    // AST classes
    template_parser_mod.add_class::<Token>()?;
    template_parser_mod.add_class::<Comment>()?;
    template_parser_mod.add_class::<HtmlAttrKind>()?;
    template_parser_mod.add_class::<HtmlAttr>()?;
    template_parser_mod.add_class::<HtmlStartTag>()?;
    template_parser_mod.add_class::<HtmlEndTag>()?;
    template_parser_mod.add_class::<Expr>()?;
    template_parser_mod.add_class::<Text>()?;
    template_parser_mod.add_class::<Node>()?;
    template_parser_mod.add_class::<TemplateElement>()?;
    template_parser_mod.add_class::<StaticNamedSlot>()?;
    template_parser_mod.add_class::<Template>()?;
    // Config
    template_parser_mod.add_class::<TagRules>()?;
    // Constants
    // HTML void elements (elements that cannot have children, e.g. <br/>),
    // single-sourced from the Rust parser so Python never drifts from it.
    template_parser_mod.add(
        "HTML_VOID_ELEMENTS",
        PyFrozenSet::new(m.py(), HTML_VOID_ELEMENTS)?,
    )?;

    Ok(())
}
