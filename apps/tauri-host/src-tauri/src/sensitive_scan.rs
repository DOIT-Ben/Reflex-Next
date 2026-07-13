use std::collections::HashMap;

const MIN_ASSIGNMENT_VALUE_LEN: usize = 4;
const MIN_HIGH_ENTROPY_LEN: usize = 32;
const MAX_HIGH_ENTROPY_LEN: usize = 256;
const MIN_HIGH_ENTROPY_BITS: f64 = 4.35;

/// Returns `true` when an exported diagnostic payload may contain a credential.
///
/// The caller owns the input-size limit. Invalid UTF-8 is rejected because it
/// cannot be inspected reliably by this text scanner.
pub fn contains_sensitive_content(bytes: &[u8]) -> bool {
    let Ok(text) = std::str::from_utf8(bytes) else {
        return true;
    };

    contains_private_key_header(text)
        || contains_bearer_token(text)
        || contains_jwt(text)
        || contains_slack_webhook(text)
        || contains_known_credential(text)
        || contains_credential_assignment(text)
        || contains_credential_url(text)
        || contains_high_entropy_token(text)
}

fn contains_private_key_header(text: &str) -> bool {
    text.lines().any(|line| {
        let upper = line.trim().to_ascii_uppercase();
        upper.starts_with("-----BEGIN ")
            && upper.ends_with("-----")
            && (upper.contains("PRIVATE KEY") || upper.contains("PGP PRIVATE KEY BLOCK"))
    })
}

fn contains_bearer_token(text: &str) -> bool {
    let lower = text.to_ascii_lowercase();
    let bytes = text.as_bytes();
    let mut offset = 0;

    while let Some(relative) = lower[offset..].find("bearer") {
        let start = offset + relative;
        let before_is_boundary = start == 0 || !bytes[start - 1].is_ascii_alphanumeric();
        let mut value_start = start + "bearer".len();
        if before_is_boundary
            && value_start < bytes.len()
            && bytes[value_start].is_ascii_whitespace()
        {
            while value_start < bytes.len() && bytes[value_start].is_ascii_whitespace() {
                value_start += 1;
            }
            let value = take_credential_value(&text[value_start..]);
            if value.len() >= 8 && is_substantive_value(value) {
                return true;
            }
        }
        offset = start + "bearer".len();
    }
    false
}

fn contains_jwt(text: &str) -> bool {
    credential_tokens(text).any(is_jwt)
}

fn contains_slack_webhook(text: &str) -> bool {
    const PREFIX: &str = "https://hooks.slack.com/services/";
    let mut offset = 0;
    while let Some(relative) = text[offset..].find(PREFIX) {
        let start = offset + relative + PREFIX.len();
        let path = text[start..]
            .split(|ch: char| ch.is_whitespace() || matches!(ch, '"' | '\'' | '?' | '#'))
            .next()
            .unwrap_or_default();
        let segments = path.split('/').collect::<Vec<_>>();
        if segments.len() >= 3
            && segments
                .iter()
                .take(3)
                .all(|segment| segment.len() >= 8 && segment.bytes().all(is_key_byte))
        {
            return true;
        }
        offset = start;
    }
    false
}

fn is_jwt(token: &str) -> bool {
    let token = trim_token_edges(token);
    let mut segments = token.split('.');
    let Some(header) = segments.next() else {
        return false;
    };
    let Some(payload) = segments.next() else {
        return false;
    };
    let Some(signature) = segments.next() else {
        return false;
    };

    segments.next().is_none()
        && header.starts_with("eyJ")
        && header.len() >= 8
        && payload.len() >= 8
        && signature.len() >= 8
        && [header, payload, signature]
            .iter()
            .all(|segment| segment.bytes().all(is_base64_url_byte))
}

fn contains_known_credential(text: &str) -> bool {
    credential_tokens(text).any(|raw| {
        let token = trim_token_edges(raw);
        is_prefixed_token(token, &["sk-cp-", "sk-proj-", "sk-ant-"], 8, is_key_byte)
            || is_prefixed_token(token, &["sk-"], 16, is_key_byte)
            || is_prefixed_token(
                token,
                &["ghp_", "gho_", "ghu_", "ghs_", "ghr_"],
                20,
                |byte| byte.is_ascii_alphanumeric(),
            )
            || is_prefixed_token(token, &["github_pat_"], 20, is_key_byte)
            || is_prefixed_token(
                token,
                &["xoxb-", "xoxp-", "xoxa-", "xoxr-", "xoxs-"],
                10,
                is_key_byte,
            )
            || is_aws_access_key(token)
            || is_prefixed_token(token, &["AIza"], 30, |byte| {
                byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-')
            })
            || is_prefixed_token(token, &["GOCSPX-"], 20, is_key_byte)
            || is_prefixed_token(
                token,
                &[
                    "sk_live_", "rk_live_", "pk_live_", "sk_test_", "rk_test_", "pk_test_",
                    "whsec_",
                ],
                16,
                is_key_byte,
            )
    })
}

fn is_prefixed_token(
    token: &str,
    prefixes: &[&str],
    minimum_tail: usize,
    allowed: fn(u8) -> bool,
) -> bool {
    prefixes.iter().any(|prefix| {
        token
            .strip_prefix(prefix)
            .is_some_and(|tail| tail.len() >= minimum_tail && tail.bytes().all(allowed))
    })
}

fn is_aws_access_key(token: &str) -> bool {
    token.len() == 20
        && (token.starts_with("AKIA") || token.starts_with("ASIA"))
        && token
            .bytes()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit())
}

fn contains_credential_assignment(text: &str) -> bool {
    let bytes = text.as_bytes();
    let mut index = 0;

    while index < bytes.len() {
        if !is_identifier_byte(bytes[index]) {
            index += 1;
            continue;
        }
        let name_start = index;
        while index < bytes.len() && is_identifier_byte(bytes[index]) {
            index += 1;
        }
        let name = &text[name_start..index];
        if !is_sensitive_field_name(name) {
            continue;
        }

        let mut separator = index;
        if separator < bytes.len() && matches!(bytes[separator], b'"' | b'\'') {
            separator += 1;
        }
        while separator < bytes.len() && bytes[separator].is_ascii_whitespace() {
            separator += 1;
        }
        if separator >= bytes.len() || !matches!(bytes[separator], b'=' | b':') {
            continue;
        }
        separator += 1;
        while separator < bytes.len() && bytes[separator].is_ascii_whitespace() {
            separator += 1;
        }
        let value = take_credential_value(&text[separator..]);
        if is_substantive_value(value) {
            return true;
        }
    }
    false
}

fn contains_credential_url(text: &str) -> bool {
    for scheme in ["http://", "https://"] {
        let lower = text.to_ascii_lowercase();
        let mut offset = 0;
        while let Some(relative) = lower[offset..].find(scheme) {
            let start = offset + relative;
            let url = text[start..]
                .split(|ch: char| ch.is_whitespace() || matches!(ch, '"' | '\'' | '<' | '>'))
                .next()
                .unwrap_or_default();
            let authority = url[scheme.len()..]
                .split(['/', '?', '#'])
                .next()
                .unwrap_or_default();
            if let Some(user_info) = authority.rsplit_once('@').map(|(value, _)| value) {
                if let Some((user, password)) = user_info.split_once(':') {
                    if !user.is_empty() && is_substantive_value(password) {
                        return true;
                    }
                }
            }
            offset = start + scheme.len();
        }
    }
    false
}

fn contains_high_entropy_token(text: &str) -> bool {
    credential_tokens(text).any(|raw| {
        let token = trim_token_edges(raw);
        token.len() >= MIN_HIGH_ENTROPY_LEN
            && token.len() <= MAX_HIGH_ENTROPY_LEN
            && token.is_ascii()
            && !looks_like_diagnostic_identifier(token)
            && !looks_like_path_or_url(token)
            && !looks_like_version(token)
            && !looks_like_uuid(token)
            && !is_hex_string(token)
            && character_class_count(token) >= 3
            && shannon_entropy(token) >= MIN_HIGH_ENTROPY_BITS
    })
}

fn credential_tokens(text: &str) -> impl Iterator<Item = &str> {
    text.split(|ch: char| {
        ch.is_whitespace()
            || matches!(
                ch,
                '"' | '\''
                    | '`'
                    | '<'
                    | '>'
                    | '('
                    | ')'
                    | '['
                    | ']'
                    | '{'
                    | '}'
                    | ','
                    | ';'
                    | ':'
                    | '='
                    | '?'
                    | '&'
            )
    })
    .filter(|token| !token.is_empty())
}

fn trim_token_edges(token: &str) -> &str {
    token.trim_matches(|ch: char| matches!(ch, ':' | '=' | '?' | '&' | '#' | '!' | ',' | ';'))
}

fn take_credential_value(input: &str) -> &str {
    let input = input.trim_start_matches(['"', '\'']);
    input
        .split(|ch: char| ch.is_whitespace() || matches!(ch, '"' | '\'' | ',' | ';' | '&' | '#'))
        .next()
        .unwrap_or_default()
}

fn is_substantive_value(value: &str) -> bool {
    let value = value.trim();
    value.len() >= MIN_ASSIGNMENT_VALUE_LEN
        && !matches!(
            value.to_ascii_lowercase().as_str(),
            "none"
                | "null"
                | "true"
                | "false"
                | "redacted"
                | "[redacted]"
                | "<redacted>"
                | "placeholder"
                | "changeme"
                | "configured"
                | "disabled"
                | "enabled"
                | "missing"
                | "not_configured"
                | "required"
                | "unavailable"
                | "unset"
        )
        && !value.starts_with("${")
        && !value.starts_with('%')
}

fn is_sensitive_field_name(name: &str) -> bool {
    let normalized = name.to_ascii_lowercase().replace('-', "_");
    matches!(
        normalized.as_str(),
        "api_key"
            | "apikey"
            | "access_key"
            | "access_token"
            | "aws_access_key_id"
            | "aws_secret_access_key"
            | "aws_session_token"
            | "auth_token"
            | "authorization"
            | "bearer_token"
            | "client_secret"
            | "credential"
            | "credentials"
            | "github_token"
            | "google_api_key"
            | "passwd"
            | "password"
            | "private_key"
            | "secret"
            | "secret_key"
            | "slack_token"
            | "stripe_secret_key"
            | "token"
    )
}

fn looks_like_diagnostic_identifier(token: &str) -> bool {
    let lower = token.to_ascii_lowercase();
    [
        "diag-",
        "diagnostic-",
        "request-",
        "request_id-",
        "trace-",
        "correlation-",
        "event-",
        "job-",
        "operation-",
        "plugin-",
        "run-",
        "span-",
        "task-",
        "build-",
    ]
    .iter()
    .any(|prefix| lower.starts_with(prefix))
}

fn looks_like_path_or_url(token: &str) -> bool {
    token.contains('\\') || token.starts_with('/') || token.contains("://")
}

fn looks_like_version(token: &str) -> bool {
    let value = token.rsplit_once('/').map_or(token, |(_, value)| value);
    let value = value.strip_prefix(['v', 'V']).unwrap_or(value);
    let mut components = 0;
    for component in value.split(['.', '-', '+']) {
        if component.is_empty() {
            continue;
        }
        components += 1;
        if !component.bytes().all(|byte| byte.is_ascii_alphanumeric()) {
            return false;
        }
    }
    components >= 2 && value.bytes().filter(|byte| *byte == b'.').count() >= 1
}

fn looks_like_uuid(token: &str) -> bool {
    let bytes = token.as_bytes();
    bytes.len() == 36
        && [8, 13, 18, 23].iter().all(|index| bytes[*index] == b'-')
        && bytes
            .iter()
            .enumerate()
            .all(|(index, byte)| [8, 13, 18, 23].contains(&index) || byte.is_ascii_hexdigit())
}

fn is_hex_string(token: &str) -> bool {
    token.len() >= MIN_HIGH_ENTROPY_LEN && token.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn character_class_count(token: &str) -> usize {
    let mut lower = false;
    let mut upper = false;
    let mut digit = false;
    let mut symbol = false;
    for byte in token.bytes() {
        lower |= byte.is_ascii_lowercase();
        upper |= byte.is_ascii_uppercase();
        digit |= byte.is_ascii_digit();
        symbol |= !byte.is_ascii_alphanumeric();
    }
    [lower, upper, digit, symbol]
        .iter()
        .filter(|present| **present)
        .count()
}

fn shannon_entropy(token: &str) -> f64 {
    let mut counts = HashMap::new();
    for byte in token.bytes() {
        *counts.entry(byte).or_insert(0usize) += 1;
    }
    let length = token.len() as f64;
    counts
        .values()
        .map(|count| {
            let probability = *count as f64 / length;
            -probability * probability.log2()
        })
        .sum()
}

fn is_identifier_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-')
}

fn is_key_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-')
}

fn is_base64_url_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b'=')
}

#[cfg(test)]
mod tests {
    use super::contains_sensitive_content;

    fn sensitive(text: &str) -> bool {
        contains_sensitive_content(text.as_bytes())
    }

    #[test]
    fn rejects_invalid_utf8() {
        assert!(contains_sensitive_content(b"diagnostic\xfffixture"));
    }

    #[test]
    fn finds_api_key_fixtures() {
        for fixture in [
            "provider=alpha key=sk-cp-fixtureKey123456",
            "sk-proj-fixtureKey1234567890",
            "sk-ant-fixtureKey1234567890",
            "sk-fixtureGenericKey1234567890",
        ] {
            assert!(sensitive(fixture), "missed fixture: {fixture}");
        }
    }

    #[test]
    fn finds_private_key_headers() {
        for key_type in [
            "PRIVATE KEY",
            "RSA PRIVATE KEY",
            "OPENSSH PRIVATE KEY",
            "PGP PRIVATE KEY BLOCK",
        ] {
            let fixture = format!("{}{}{}\nfixture-only", "-----BEGIN ", key_type, "-----");
            assert!(sensitive(&fixture), "missed fixture header");
        }
    }

    #[test]
    fn finds_bearer_and_jwt_fixtures() {
        assert!(sensitive("Authorization: Bearer fixture-access-token"));
        assert!(sensitive(
            "eyJmaXh0dXJlIjoiaGVhZGVyIn0.eyJmaXh0dXJlIjoicGF5bG9hZCJ9.fixtureSignature123"
        ));
    }

    #[test]
    fn finds_github_slack_aws_google_and_stripe_fixtures() {
        for fixture in [
            "ghp_FixtureToken0123456789ABCDE",
            "github_pat_fixtureToken0123456789ABCDE",
            "xoxb-fixture-token-0123456789",
            "https://hooks.slack.com/services/Tfixture1/Bfixture2/fixtureWebhook3",
            "AKIAFIXTURE012345678",
            "AIzaFixtureGoogleCredential0123456789ABCDE",
            "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45",
            "sk_live_fixtureStripeCredential012345",
            "rk_live_fixtureStripeCredential012345",
            "whsec_fixtureStripeCredential01234567",
        ] {
            assert!(sensitive(fixture), "missed fixture: {fixture}");
        }
    }

    #[test]
    fn finds_credential_assignments_and_urls() {
        for fixture in [
            "client_secret = fixture-client-secret",
            "aws_secret_access_key=fixture-aws-secret-value",
            "aws_session_token=fixture-aws-session-value",
            r#"{"api_key":"fixture-api-value"}"#,
            "https://example.test/callback?access_token=fixture-query-value",
            "https://fixture-user:fixture-password@example.test/v1",
        ] {
            assert!(sensitive(fixture), "missed fixture: {fixture}");
        }
    }

    #[test]
    fn high_entropy_fallback_finds_unlabelled_fixture() {
        assert!(sensitive(
            "opaque Z9vK2mQ7xR4pL8sN1dF6hJ3wC0bT5yUeA+fixture/42"
        ));
    }

    #[test]
    fn allows_normal_diagnostics_versions_and_placeholders() {
        for fixture in [
            "host_started status=ready elapsed_ms=42",
            "authorization=disabled credential=not_configured",
            "diagnostic_id=diag-123",
            "diag-aB3dE5fG7hJ9kL1mN3pQ5rS7tV9xY2zA",
            "plugin-aB3dE5fG7hJ9kL1mN3pQ5rS7tV9xY2zA",
            "request-9f4c2a10-b8d7-4c3a-9e61-123456789abc",
            "9f4c2a10-b8d7-4c3a-9e61-123456789abc",
            "0123456789abcdef0123456789abcdef01234567",
            "Reflex/1.12.3-beta+build20260714",
            r"C:\Users\fixture\AppData\Local\Reflex\diagnostics\host-diagnostics.jsonl",
            "api_key=[REDACTED] token=${REFLEX_TOKEN} password=null",
            "https://example.test/v1/status?request_id=diag-123",
        ] {
            assert!(!sensitive(fixture), "false positive: {fixture}");
        }
    }

    #[test]
    fn does_not_treat_bearer_prose_as_a_token() {
        assert!(!sensitive("the bearer token field was redacted"));
        assert!(!sensitive("authentication scheme: Bearer"));
    }
}
