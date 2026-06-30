use ruff_source_file::LineIndex;

use crate::transformer::{Comment, Token};

/// Preprocess the source string to extract comments.
///
/// Ignores comments in strings (both single and triple quotes),
/// and collects comments only until the end of the line.
///
/// We have to do this, because Ruff's Python parser ignores comments.
///
/// Since we use `exec()` instead of `eval()`, Python naturally handles:
/// - Comments (they're ignored by the parser)
/// - Newlines (they're part of normal Python syntax)
pub fn extract_comments(source: &str) -> Result<Vec<Comment>, String> {
    let mut comments = Vec::new();
    let line_index = LineIndex::from_source_text(source);

    // Convert to bytes for easier indexing
    let bytes = source.as_bytes();
    let mut i = 0;
    let mut in_string = false;
    let mut string_quote: Option<u8> = None;
    let mut string_delimiter_count = 0;

    let check_for_string_start = |ch: char, i: usize| -> (bool, Option<u8>, i32, usize) {
        if !(ch == '"' || ch == '\'') {
            // Curr char NOT a quote
            return (false, None, 0, i);
        }
        let quote_byte = ch as u8;

        // is_raw_string is already set if we saw a prefix
        let in_string = true;
        let string_quote = Some(quote_byte);
        // A triple-quoted string (""" or ''') opens with three quote bytes;
        // otherwise a single quote opens a normal string.
        let (string_delimiter_count, new_i) =
            if i + 2 < bytes.len() && bytes[i + 1] == quote_byte && bytes[i + 2] == quote_byte {
                (3, i + 3)
            } else {
                (1, i + 1)
            };
        (in_string, string_quote, string_delimiter_count, new_i)
    };

    let check_for_comment = |ch: char, i: usize, comments: &mut Vec<Comment>| -> (bool, usize) {
        if ch != '#' {
            return (false, i);
        }

        // Found a comment - extract it
        let comment_start = i;
        let mut comment_end = i + 1;

        // Collect comment text until newline or end of input
        while comment_end < bytes.len() {
            let next_byte = bytes[comment_end];
            if next_byte == b'\n' || next_byte == b'\r' {
                break;
            }
            comment_end += 1;
        }

        let comment_text =
            String::from_utf8_lossy(&bytes[comment_start + 1..comment_end]).to_string();

        // Create tokens for the comment
        let start_pos =
            line_index.line_column(ruff_text_size::TextSize::from(comment_start as u32), source);

        let comment_token = Token {
            content: format!("#{}", comment_text),
            start_index: comment_start,
            end_index: comment_end,
            line_col: (
                start_pos.line.to_zero_indexed() + 1,
                start_pos.column.to_zero_indexed() + 1,
            ),
        };

        // Calculate position for value token (starts one character after #)
        let value_start_pos = line_index.line_column(
            ruff_text_size::TextSize::from((comment_start + 1) as u32),
            source,
        );

        let value_token = Token {
            content: comment_text.clone(),
            start_index: comment_start + 1,
            end_index: comment_end,
            line_col: (
                value_start_pos.line.to_zero_indexed() + 1,
                value_start_pos.column.to_zero_indexed() + 1,
            ),
        };

        comments.push(Comment {
            token: comment_token,
            value: value_token,
        });

        (true, comment_end)
    };

    while i < bytes.len() {
        let ch = bytes[i] as char;

        if !in_string {
            // Check for string start quote(s)
            // If so, advance past the string start quotes
            let (new_in_string, new_string_quote, new_string_delimiter_count, new_i) =
                check_for_string_start(ch, i);
            if new_in_string {
                in_string = new_in_string;
                string_quote = new_string_quote;
                string_delimiter_count = new_string_delimiter_count;
                i = new_i;
                continue;
            }

            // Check for comment
            // If found, advance past the comment
            let (found_comment, new_i) = check_for_comment(ch, i, &mut comments);
            if found_comment {
                i = new_i;
                continue;
            }

            // Regular character outside string
            i += 1;
        } else {
            // Inside a string
            let quote_byte = string_quote.unwrap();

            // Before checking for closing quotes or anything else,
            // first handle escape sequences like `\"` or `\\`.
            //
            // Whether it's a raw string or not, Python allows nested quotes if they follow
            // a backslash. The difference is that in raw string, the backslash is included
            // in the final string too. While in regular string the backslash and character
            // after it create a new single character, e.g. `\n` for newline.
            // Compare `r"abc \" def"` vs `"abc \" def"`
            //
            // So check if we're escaping the next char, and if so push and skip both characters.
            if bytes[i] == b'\\' && i + 1 < bytes.len() {
                i += 2;
                continue;
            }

            // Check for closing quote(s)
            // We already handled escape sequences above, so any quote here is a closing quote
            if bytes[i] == quote_byte {
                let mut quote_count = 1;
                let mut j = i + 1;
                while j < bytes.len()
                    && quote_count < string_delimiter_count
                    && bytes[j] == quote_byte
                {
                    quote_count += 1;
                    j += 1;
                }

                if quote_count == string_delimiter_count {
                    // Closing quote(s)
                    i = j;
                    in_string = false;
                    string_quote = None;
                    string_delimiter_count = 0;
                    continue;
                }
            }

            // Regular character inside string
            i += 1;
        }
    }

    Ok(comments)
}
