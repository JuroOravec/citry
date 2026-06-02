use std::collections::HashMap;
use std::rc::Rc;

use crate::ast::{Comment, Token};
use crate::error::ParseError;
use crate::grammar::Rule;
use crate::lang::lang::LangImpl;

/// Attribute validation rules for special tags
///
/// Used to define custom attribute validation rules for user-defined tags.
///
/// # Examples
///
/// ```ignore
/// use std::collections::HashMap;
/// use citry_template_parser::{TagRules, parse_template};
///
/// let mut rules = HashMap::new();
/// rules.insert("my-tag".to_string(), TagRules {
///     allowed_attrs: Some(vec![vec!["id".to_string(), "c-id".to_string()]]),
///     required_attrs: vec![vec!["id".to_string(), "c-id".to_string()]],
///     allowed_slots: Some(vec!["default".to_string()]),
///     required_slots: vec!["default".to_string()],
/// });
///
/// let template = parse_template("<my-tag id=\"test\"></my-tag>", None, Some(&rules))?;
/// ```
#[derive(Debug, Clone)]
pub struct TagRules {
    /// Allowed attributes. List of lists where inner lists mean "one of" (mutually exclusive).
    /// - If `None`, any attributes allowed.
    /// - If `Some(vec![])`, no attributes allowed.
    /// - If `Some([["c-name", "name"]])`, the tag can have either "c-name" OR "name", but not both.
    /// - If `Some([["c-name", "name"], ["data"]])`, the tag can have either "c-name" OR "name", but not both,
    ///   and can have "data" as well.
    pub allowed_attrs: Option<Vec<Vec<String>>>,
    /// Required attributes. List of lists where inner lists mean "one of"
    /// (at least one from each inner list must be present).
    /// - If `[]`, no attributes required.
    /// - If `[["id", "c-id"]]`, at least one of "id" or "c-id" must be present.
    /// - If `[["id", "c-id", "c-bind"], ["data"]]`, at least one of "id" or "c-id" or "c-bind" must be present,
    ///   and "data" can be present as well.
    pub required_attrs: Vec<Vec<String>>,
    /// Allowed slot names (for `<c-fill>` tags).
    /// - If `None`, any slot names allowed.
    /// - If `Some(vec![])`, no slots allowed (component cannot have fills).
    /// - If `Some(vec!["default", "footer"])`, only "default" and "footer" slots are allowed.
    pub allowed_slots: Option<Vec<String>>,
    /// Required slot names.
    /// - If `[]`, no slots required.
    /// - If `vec!["default"]`, the "default" slot must be present (either as explicit `<c-fill name="default">` or as body content).
    /// - If `vec!["default", "footer"]`, both "default" and "footer" slots must be present.
    pub required_slots: Vec<String>,
}

/// Global context for parsing templates and tags
#[derive(Clone)]
pub struct ParserContext {
    /// Line offset to add to all line numbers (0-based internally, but reported as 1-based)
    pub line_offset: usize,
    /// Column offset to add to column numbers on the first line only
    pub col_offset: usize,
    /// Index offset to add to start_index and end_index
    pub index_offset: usize,
    /// User-defined attribute validation rules (tag_name -> rules)
    pub user_rules: Rc<HashMap<String, TagRules>>,
    /// Language-specific implementation for parsing expressions
    pub lang: Rc<dyn LangImpl>,
}

impl ParserContext {
    /// Create a new context with no offsets
    pub fn new(lang: &Rc<dyn LangImpl>, user_rules: &Rc<HashMap<String, TagRules>>) -> Self {
        Self {
            line_offset: 0,
            col_offset: 0,
            index_offset: 0,
            lang: Rc::clone(lang),
            user_rules: Rc::clone(user_rules),
        }
    }

    /// Create a child context with specified offsets
    ///
    /// This is used when creating nested contexts (e.g., for template strings).
    pub fn create_child_context(
        &self,
        line_offset: usize,
        col_offset: usize,
        index_offset: usize,
    ) -> Self {
        Self {
            line_offset,
            col_offset,
            index_offset,
            // User-defined attribute rules are inherited from the parent context via Rc (no cloning).
            user_rules: Rc::clone(&self.user_rules),
            // Language implementation is inherited from the parent context via Rc (no cloning).
            lang: Rc::clone(&self.lang),
        }
    }

    // /////////////////////////////////////////////////////
    // COMMENTS
    // /////////////////////////////////////////////////////

    /// Helper to create a Comment from a COMMENT rule pair
    fn create_comment(&self, pair: &pest::iterators::Pair<Rule>) -> Result<Comment, ParseError> {
        let token = self.create_token(pair);

        // A comment must be at least 4 characters: {# #}
        if token.content.len() < 4 {
            return Err(ParseError::from_span(
                pair.as_span(),
                format!("Invalid comment: too short ({})", token.content.clone()),
            ));
        }

        // Create value token with offsets to skip {# at start and #} at end
        // The content will be automatically sliced and trimmed
        let value_token = Token::from_pair(pair).crop_cols(2, -2);
        let value_token = self.offset_token(value_token);

        Ok(Comment {
            token,
            value: value_token,
        })
    }

    /// Filter wrapper pairs whose single child might be a COMMENT
    ///
    /// This helper is used for cases like `template_element` which wraps a single child
    /// that could be `html_tag | expression | COMMENT | text`.
    ///
    /// For each parent pair:
    /// 1. Peeks at the single child
    /// 2. If child is a COMMENT, extracts it and adds to context
    /// 3. If child is not a COMMENT, keeps the parent pair
    /// 4. Returns a Vec of parent pairs (excluding those with COMMENT children)
    pub fn extract_comments_from_pairs<'i>(
        &self,
        pairs: impl IntoIterator<Item = pest::iterators::Pair<'i, Rule>>,
    ) -> Result<
        (
            impl Iterator<Item = pest::iterators::Pair<'i, Rule>>,
            Vec<Comment>,
        ),
        ParseError,
    > {
        let mut filtered_pairs = Vec::new();
        let mut comments = Vec::new();

        for pair in pairs {
            let pair_rule = pair.as_rule();

            // Handle spacing and spacing_with_whitespace by recursively extracting comments
            if pair_rule == Rule::spacing || pair_rule == Rule::spacing_with_whitespace {
                // Recursively process spacing to extract nested comments
                self._extract_comments_from_pairs(pair.into_inner(), &mut comments)?
                    .for_each(|_| {});
                // Don't add spacing pairs to filtered_pairs
                continue;
            }

            // template_element may have a COMMENT as its child. In which case we drop the parent pair
            if pair_rule == Rule::template_element {
                // Check if this pair's single child is a COMMENT
                let inner = pair.clone().into_inner().next();
                if let Some(inner_rule) = inner {
                    if inner_rule.as_rule() == Rule::template_comment {
                        // Extract and collect the comment
                        let comment = self.create_comment(&inner_rule)?;
                        comments.push(comment);
                        // Don't add this parent pair to filtered_pairs
                        continue;
                    }
                }
            }

            // Keep the parent pair if child is not a comment
            filtered_pairs.push(pair);
        }

        Ok((filtered_pairs.into_iter(), comments))
    }

    /// Filter pairs, extracting and collecting comments and spacing, returning only meaningful pairs
    ///
    /// This helper processes an iterator of pairs and:
    /// 1. Extracts COMMENT pairs and adds them to the context
    /// 2. Recursively processes spacing pairs to extract nested comments
    /// 3. Returns a Vec of non-comment, non-spacing pairs
    fn _extract_comments_from_pairs<'i>(
        &self,
        pairs: impl IntoIterator<Item = pest::iterators::Pair<'i, Rule>>,
        comments: &mut Vec<Comment>,
    ) -> Result<impl Iterator<Item = pest::iterators::Pair<'i, Rule>>, ParseError> {
        let mut filtered_pairs = Vec::new();

        for pair in pairs {
            match pair.as_rule() {
                Rule::template_comment => {
                    // Collect the comment
                    let comment = self.create_comment(&pair)?;
                    comments.push(comment);
                }
                Rule::spacing => {
                    // Recursively process spacing to extract nested comments
                    self._extract_comments_from_pairs(pair.into_inner(), comments)?
                        .for_each(|_| {});
                    // Note: we don't add spacing pairs to filtered_pairs
                }
                _ => {
                    // Keep all other pairs
                    filtered_pairs.push(pair);
                }
            }
        }

        Ok(filtered_pairs.into_iter())
    }

    // /////////////////////////////////////////////////////
    // TOKENS
    // /////////////////////////////////////////////////////

    /// Apply context offsets (line, column, index) to an existing Token
    ///
    /// This modifies the token's positions to account for the context's offsets.
    /// This is useful when you have a token created in a different context (e.g., from safe_eval)
    /// and need to adjust it to match the current context's position.
    pub fn offset_token(&self, token: Token) -> Token {
        token.offset(self.index_offset, self.line_offset, self.col_offset)
    }

    /// Create a Token from a pest Pair, applying line, column, and index offsets
    pub fn create_token(&self, pair: &pest::iterators::Pair<Rule>) -> Token {
        let token = Token::from_pair(pair);
        self.offset_token(token)
    }
}
