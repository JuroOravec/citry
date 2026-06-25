//! Dependency collection + merge prototype.
//!
//! The dependencies extension collects one `DependencyRecord` per component
//! render into an insertion-ordered set, bubbles them up the tree (a union per
//! merge site), and at serialize time collapses the duplicates with
//! `dict.fromkeys`, keeping first-seen (document) order. A record is a NamedTuple
//! of four strings (class_id, component_id, js_vars_hash, css_vars_hash); the
//! whole choreography is first-seen-order dedup/union over that key.
//!
//! This module reimplements just that choreography in Rust so it can be compared
//! against Python's `dict`-based version. Two entry points:
//!
//! - `dedup_first_seen` dedups records handed in from Python (so it pays the cost
//!   of marshalling the records across the boundary, which the in-process Python
//!   `dict.fromkeys` does not). This is "move only the dedup to Rust".
//! - `bench_native_collect` builds and dedups the records entirely in Rust, with
//!   no per-call marshalling. This is the speed the choreography would have if the
//!   records already lived in Rust (a full render-in-Rust port).

use std::collections::HashSet;

use pyo3::prelude::*;

/// A dependency record's identity: (class_id, component_id, js_vars_hash, css_vars_hash).
type RecordKey = (String, String, Option<String>, Option<String>);

/// First-seen-order dedup of records marshalled in from Python (mirrors
/// `_resolve_records`' `list(dict.fromkeys(records))`).
#[pyfunction]
fn dedup_first_seen(records: Vec<RecordKey>) -> Vec<RecordKey> {
    let mut seen: HashSet<RecordKey> = HashSet::with_capacity(records.len());
    let mut out: Vec<RecordKey> = Vec::new();
    for record in records {
        if seen.insert(record.clone()) {
            out.push(record);
        }
    }
    out
}

/// Build `n_distinct` records and re-emit them across `n_levels` bubble-up
/// levels (modelling a record arriving once per ancestor), deduping on insert
/// like the real insertion-ordered set. Everything happens in Rust, so there is
/// no per-call Python marshalling. Returns the distinct count.
#[pyfunction]
fn bench_native_collect(n_distinct: usize, n_levels: usize) -> usize {
    let mut seen: HashSet<RecordKey> = HashSet::with_capacity(n_distinct);
    let mut out: Vec<RecordKey> = Vec::with_capacity(n_distinct);
    for _level in 0..n_levels {
        for i in 0..n_distinct {
            let record: RecordKey = (format!("Cls{i}"), format!("c{i}"), None, None);
            if seen.insert(record.clone()) {
                out.push(record);
            }
        }
    }
    out.len()
}

/// Register the prototype's functions into the given module.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(dedup_first_seen, m)?)?;
    m.add_function(wrap_pyfunction!(bench_native_collect, m)?)?;
    Ok(())
}
