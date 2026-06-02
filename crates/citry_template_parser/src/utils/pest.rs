use crate::error::{assert_rule, ParseError};
use crate::grammar::Rule;

pub fn span_from_str<'i>(input: &'i str) -> pest::Span<'i> {
    pest::Span::new(input, 0, input.len()).unwrap()
}

/// Given a Pest's Pair (matched rule), return the inner pair
pub fn unwrap_pair(
    pair: pest::iterators::Pair<Rule>,
    expected_rule: Rule,
) -> Result<pest::iterators::Pair<Rule>, ParseError> {
    let pair_span = pair.as_span();
    let pair_rule = pair.as_rule();
    let inner = pair.into_inner().next().ok_or_else(|| {
        ParseError::from_span(
            pair_span,
            format!(
                "pair {:?} should contain a pair {:?}",
                pair_rule, expected_rule
            ),
        )
    })?;
    assert_rule(&inner, expected_rule)?;
    Ok(inner)
}
