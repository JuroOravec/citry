use citry_html_transform::{transform_html, HtmlTransformerConfig};

#[test]
fn test_basic_transformation() {
    let config = HtmlTransformerConfig::new(
        vec!["data-root".to_string()],
        vec!["data-all".to_string()],
        false,
        None,
    );

    let input = "<div><p>Hello</p></div>";
    let (result, _) = transform_html(&config, input).unwrap();

    assert!(result.contains("data-root"));
    assert!(result.contains("data-all"));
}

#[test]
fn test_multiple_roots() {
    let config = HtmlTransformerConfig::new(
        vec!["data-root".to_string()],
        vec!["data-all".to_string()],
        false,
        None,
    );

    let input = "<div>First</div><span>Second</span>";
    let (result, _) = transform_html(&config, input).unwrap();

    // Both root elements should have data-root
    assert_eq!(result.matches("data-root").count(), 2);
    // All elements should have data-all
    assert_eq!(result.matches("data-all").count(), 2);
}

#[test]
fn test_complex_html() {
    let config = HtmlTransformerConfig::new(
        vec!["data-root".to_string()],
        vec!["data-all".to_string(), "data-v-123".to_string()],
        false,
        None,
    );

    let input = r#"
        <div class="container" id="main">
            <header class="flex">
                <h1 title="Main Title">Hello & Welcome</h1>
                <nav data-existing="true">
                    <a href="/home">Home</a>
                    <a href="/about" class="active">About</a>
                </nav>
            </header>
            <main>
                <article data-existing="true">
                    <h2>Article 1</h2>
                    <p>Some text with <strong>bold</strong> and <em>emphasis</em></p>
                    <img src="test.jpg" alt="Test Image"/>
                </article>
            </main>
        </div>
        <footer id="footer">
            <p>&copy; 2024</p>
        </footer>
    "#;

    let (result, _) = transform_html(&config, input).unwrap();

    // Check root elements have root attributes
    assert!(result
        .contains(r#"<div class="container" id="main" data-root="" data-all="" data-v-123="">"#));
    assert!(result.contains(r#"<footer id="footer" data-root="" data-all="" data-v-123="">"#));

    // Check nested elements have all_attributes but not root_attributes
    assert!(result.contains(r#"<h1 title="Main Title" data-all="" data-v-123="">"#));
    assert!(result.contains(r#"<nav data-existing="true" data-all="" data-v-123="">"#));
    assert!(result.contains(r#"<img src="test.jpg" alt="Test Image" data-all="" data-v-123=""/>"#));

    // Verify we didn't mess up the content or structure
    assert!(result.contains("Hello & Welcome"));
    assert!(result.contains("&copy; 2024"));
    assert!(result.contains(r#"<strong data-all="" data-v-123="">bold</strong>"#));
}

#[test]
fn test_void_elements() {
    let config = HtmlTransformerConfig::new(
        vec!["data-root".to_string()],
        vec!["data-v-123".to_string()],
        false,
        None,
    );

    // Test various formats of void elements
    let test_cases = [
        (
            "<meta charset=\"utf-8\">",
            "<meta charset=\"utf-8\" data-root=\"\" data-v-123=\"\"/>",
        ),
        (
            "<meta charset=\"utf-8\"/>",
            "<meta charset=\"utf-8\" data-root=\"\" data-v-123=\"\"/>",
        ),
        (
            "<div><br><hr></div>",
            "<div data-root=\"\" data-v-123=\"\"><br data-v-123=\"\"/><hr data-v-123=\"\"/></div>",
        ),
        (
            "<img src=\"test.jpg\" alt=\"Test\">",
            "<img src=\"test.jpg\" alt=\"Test\" data-root=\"\" data-v-123=\"\"/>",
        ),
    ];

    for (input, expected) in test_cases {
        let (result, _) = transform_html(&config, input).unwrap();
        assert_eq!(result, expected);
    }

    // Test multiple void elements in a complex structure
    let input = r#"<div>
        <link rel="stylesheet" href="style.css">
        <img src="test.jpg">
        <p>Text with<br>break</p>
    </div>"#;

    let (result, _) = transform_html(&config, input).unwrap();

    // Verify void elements have attributes but no closing tags
    assert!(result.contains(r#"<link rel="stylesheet" href="style.css" data-v-123=""/>"#));
    assert!(result.contains(r#"<img src="test.jpg" data-v-123=""/>"#));
    assert!(result.contains(r#"<br data-v-123=""/>"#));

    // Verify non-void elements still have proper closing tags
    assert!(result.contains("</p>"));
    assert!(result.contains("</div>"));
}

#[test]
fn test_html_head_with_meta() {
    let config = HtmlTransformerConfig::new(
        vec!["data-root".to_string()],
        vec!["data-v-123".to_string()],
        false,
        None,
    );

    let input = r#"
        <head>
            <meta charset="utf-8">
            <title>Test Page</title>
            <link rel="stylesheet" href="style.css">
            <meta name="description" content="Test">
        </head>"#;

    let (result, _) = transform_html(&config, input).unwrap();

    // Check that it parsed successfully
    assert!(result.contains(r#"<meta charset="utf-8""#));
    assert!(result.contains(r#"<title data-v-123="">Test Page</title>"#));
    assert!(result.contains(r#"<link rel="stylesheet" href="style.css""#));

    // Verify void elements are properly handled
    assert!(!result.contains("</meta>"));
    assert!(!result.contains("</link>"));
    assert!(result.contains("/>"));
}

#[test]
fn test_config_check_end_names() {
    // Test with check_end_names = false (lenient mode)
    let config = HtmlTransformerConfig::new(
        vec!["data-root".to_string()],
        vec!["data-v-123".to_string()],
        false, // Don't check end names
        None,
    );

    // These should parse successfully with check_end_names = false
    let lenient_cases = [
        "<div><p>Hello</div></p>", // Mismatched nesting
        "<div>Text</span>",        // Wrong closing tag
        "<p>Text</wrong>",         // Non-matching end tag
    ];

    for input in lenient_cases {
        assert!(transform_html(&config, input).is_ok());
    }

    // Test with check_end_names = true (strict mode)
    let config = HtmlTransformerConfig::new(
        vec!["data-root".to_string()],
        vec!["data-v-123".to_string()],
        true, // Check end names
        None,
    );

    // These should fail with check_end_names = true
    for input in lenient_cases {
        assert!(transform_html(&config, input).is_err());
    }

    // But well-formed HTML should still work
    let valid_input = "<div><p>Hello</p></div>";
    assert!(transform_html(&config, valid_input).is_ok());
}

#[test]
fn test_watch_attribute() {
    let config = HtmlTransformerConfig::new(
        vec!["data-root".to_string()],
        vec!["data-v-123".to_string()],
        false,
        Some("data-id".to_string()),
    );

    let input = r#"
        <div data-id="123">
            <p>Regular element</p>
            <span data-id="456">Nested element</span>
            <img data-id="789" src="test.jpg"/>
        </div>"#;

    let (result, captured) = transform_html(&config, input).unwrap();

    println!("result: {}", result);
    println!("captured: {:?}", captured);

    // Verify HTML transformation worked
    assert!(result.contains(r#"<div data-id="123" data-root="" data-v-123="">"#));
    assert!(result.contains(r#"<span data-id="456" data-v-123="">"#));
    assert!(result.contains(r#"<img data-id="789" src="test.jpg" data-v-123=""/>"#));

    // Verify attribute capturing
    assert_eq!(captured.len(), 3);
    assert!(captured.iter().any(|(id, attrs)| id == "123"
        && attrs.contains(&"data-root".to_string())
        && attrs.contains(&"data-v-123".to_string())));
    assert!(captured
        .iter()
        .any(|(id, attrs)| id == "456" && attrs.contains(&"data-v-123".to_string())));
    assert!(captured
        .iter()
        .any(|(id, attrs)| id == "789" && attrs.contains(&"data-v-123".to_string())));
}
