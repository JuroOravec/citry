use quick_xml::events::{BytesStart, Event};
use quick_xml::reader::Reader;
use quick_xml::writer::Writer;
use std::collections::HashSet;
use std::io::Cursor;

// List of HTML5 void elements. These can be written as `<tag>` or `<tag />`,
//e.g. `<br />`, `<link />`, `<img />`, etc.
const VOID_ELEMENTS: [&str; 14] = [
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
    "track", "wbr",
];

/// Configuration for HTML transformation
pub struct HtmlTransformerConfig {
    /// Attributes to add to root elements only
    root_attributes: Vec<String>,
    /// Attributes to add to all elements
    all_attributes: Vec<String>,
    /// Known void elements. These will NOT be expanded to start and end tags.
    void_elements: HashSet<String>,
    /// Whether mismatched closing tag names should be detected. If enabled, in
    /// case of mismatch the [`quick_xml::reader::Config::check_end_names`] is returned from
    /// read methods.
    check_end_names: bool,
    /// Attribute to watch for. If set, when an element with this attribute is encountered,
    /// the attributes that were added to the element will be captured and returned.
    track_added_attributes_for_tags_with_this_attribute: Option<String>,
}

impl HtmlTransformerConfig {
    pub fn new(
        root_attributes: Vec<String>,
        all_attributes: Vec<String>,
        check_end_names: bool,
        track_added_attributes_for_tags_with_this_attribute: Option<String>,
    ) -> Self {
        let void_elements = VOID_ELEMENTS.iter().map(|&s| s.to_string()).collect();

        HtmlTransformerConfig {
            root_attributes,
            all_attributes,
            void_elements,
            check_end_names,
            track_added_attributes_for_tags_with_this_attribute,
        }
    }
}

/// Transform given HTML string.
///
/// This function performs the following transformations:
///
/// 1. **Add root attributes**: Attributes specified in [`HtmlTransformerConfig::root_attributes`] are added
///    only to root-level elements (elements at depth 0).
///
/// 2. **Add attributes to all elements**: Attributes specified in [`HtmlTransformerConfig::all_attributes`]
///    are added to every element in the HTML.
///
/// In addition, this transformer also:
///
/// 1. **Tracks added attributes**: If [`HtmlTransformerConfig::track_added_attributes_for_tags_with_this_attribute`]
///    is set, captures which attributes were added to elements that have the specified
///    attribute, returning a list of tuples (attribute value, list of attributes added to tag).
///
/// 2. **Validates end tags**: If [`HtmlTransformerConfig::check_end_names`] is enabled, validates that
///    closing tags match their corresponding opening tags.
///
/// **Arguments**
///
/// * `config` - Configuration object specifying which attributes to add and how to transform
/// * `html` - The HTML string to transform. Can be a fragment or full document.
///
/// **Returns**
///
/// Returns a `Result` containing:
/// - `Ok((html, captured))`: A tuple with the transformed HTML string and a vector of
///   captured attribute mappings (the latter only populated if tracking is enabled).
/// - `Err(error)`: An error if the HTML is malformed or cannot be parsed.
pub fn transform_html(
    config: &HtmlTransformerConfig,
    html: &str,
) -> Result<(String, Vec<(String, Vec<String>)>), Box<dyn std::error::Error>> {
    let mut reader = Reader::from_str(html);
    let reader_config = reader.config_mut();
    reader_config.check_end_names = config.check_end_names;
    // Allow bare `&` in HTML content (e.g. "Hello & Welcome" instead of requiring "Hello &amp; Welcome")
    // This is needed for compatibility with HTML5 which is more lenient than strict XML
    reader_config.allow_dangling_amp = true;

    // We transform the HTML by reading it and writing it simultaneously
    let mut writer = Writer::new(Cursor::new(Vec::new()));
    let mut captured_attributes = Vec::new();

    // Track the nesting depth of elements to identify root elements (depth == 0)
    let mut depth: i32 = 0;

    // Read the HTML, event by event
    loop {
        match reader.read_event() {
            // Start tag
            Ok(Event::Start(e)) => {
                let tag_name = String::from_utf8_lossy(e.name().as_ref())
                    .to_string()
                    .to_lowercase();
                let mut elem = e.into_owned();
                _add_attributes(config, &mut elem, depth == 0, &mut captured_attributes);

                // For void elements, write as Empty event
                if config.void_elements.contains(&tag_name) {
                    writer.write_event(Event::Empty(elem))?;
                } else {
                    writer.write_event(Event::Start(elem))?;
                    depth += 1;
                }
            }

            // End tag
            Ok(Event::End(e)) => {
                let tag_name = String::from_utf8_lossy(e.name().as_ref())
                    .to_string()
                    .to_lowercase();

                // Skip end tags for void elements
                if !config.void_elements.contains(&tag_name) {
                    writer.write_event(Event::End(e))?;
                    depth -= 1;
                }
            }

            // Empty element (AKA void or self-closing tag, e.g. `<br />`)
            Ok(Event::Empty(e)) => {
                let mut elem = e.into_owned();
                _add_attributes(config, &mut elem, depth == 0, &mut captured_attributes);
                writer.write_event(Event::Empty(elem))?;
            }

            // End of file
            Ok(Event::Eof) => break,
            // Other events (e.g. comments, processing instructions, etc.)
            Ok(e) => writer.write_event(e)?,
            Err(e) => return Err(Box::new(e)),
        }
    }

    // Convert the transformed HTML to a string
    let result = String::from_utf8(writer.into_inner().into_inner())?;
    Ok((result, captured_attributes))
}

/// Add attributes to a HTML start tag (e.g. `<div>`) based on the configuration
fn _add_attributes(
    config: &HtmlTransformerConfig,
    element: &mut BytesStart,
    is_root: bool,
    captured_attributes: &mut Vec<(String, Vec<String>)>,
) {
    let mut added_attrs = Vec::new();

    // Add root attributes if this is a root element
    if is_root {
        for attr in &config.root_attributes {
            element.push_attribute((attr.as_str(), ""));
            added_attrs.push(attr.clone());
        }
    }

    // Add attributes that should be applied to all elements
    for attr in &config.all_attributes {
        element.push_attribute((attr.as_str(), ""));
        added_attrs.push(attr.clone());
    }

    // If we're watching for a specific attribute, check if this element has it
    if let Some(watch_attr) = &config.track_added_attributes_for_tags_with_this_attribute {
        if let Some(attr_value) = element
            .attributes()
            .find(|a| {
                if let Ok(attr) = a {
                    String::from_utf8_lossy(attr.key.as_ref()) == *watch_attr
                } else {
                    false
                }
            })
            .and_then(|a| a.ok())
            .map(|a| String::from_utf8_lossy(a.value.as_ref()).into_owned())
        {
            captured_attributes.push((attr_value, added_attrs));
        }
    }
}
