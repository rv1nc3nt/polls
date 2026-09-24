// SPDX-License-Identifier: 0BSD
//! A strict JSON reader (RFC 8259) for the publication document
//! (`docs/publication-format.md`), with no dependency, like the rest of this
//! crate.
//!
//! Strict on purpose. A duplicate object key is an error rather than "last one
//! wins": two readers of one file must not be able to see two different
//! winners in it. Nesting is capped so a hostile file cannot exhaust the
//! stack. Numbers are kept as their text; the caller reads the few it needs
//! as unsigned integers.

/// A parsed JSON value. Objects keep their keys in document order.
#[derive(Debug, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Number(String),
    String(String),
    Array(Vec<Value>),
    Object(Vec<(String, Value)>),
}

impl Value {
    /// The member `key` of an object; `None` if absent or not an object.
    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Object(members) => members.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::String(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_array(&self) -> Option<&[Value]> {
        match self {
            Value::Array(items) => Some(items),
            _ => None,
        }
    }

    pub fn as_object(&self) -> Option<&[(String, Value)]> {
        match self {
            Value::Object(members) => Some(members),
            _ => None,
        }
    }

    /// A non-negative integer with no fraction or exponent.
    pub fn as_u64(&self) -> Option<u64> {
        match self {
            Value::Number(text) if text.bytes().all(|b| b.is_ascii_digit()) => text.parse().ok(),
            _ => None,
        }
    }
}

const MAX_DEPTH: usize = 64;

/// Parse one JSON document; anything but whitespace after it is an error.
/// The message gives the byte offset of the problem.
pub fn parse(text: &str) -> Result<Value, String> {
    let mut reader = Reader { bytes: text.as_bytes(), pos: 0 };
    reader.skip_whitespace();
    let value = reader.value(0)?;
    reader.skip_whitespace();
    if reader.pos != reader.bytes.len() {
        return Err(reader.error("unexpected content after the document"));
    }
    Ok(value)
}

struct Reader<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl Reader<'_> {
    fn error(&self, what: &str) -> String {
        format!("JSON: {what} at byte {}", self.pos)
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.pos += 1;
        }
    }

    fn expect(&mut self, byte: u8) -> Result<(), String> {
        if self.peek() == Some(byte) {
            self.pos += 1;
            Ok(())
        } else {
            Err(self.error(&format!("expected '{}'", byte as char)))
        }
    }

    fn literal(&mut self, word: &str, value: Value) -> Result<Value, String> {
        if self.bytes[self.pos..].starts_with(word.as_bytes()) {
            self.pos += word.len();
            Ok(value)
        } else {
            Err(self.error("invalid literal"))
        }
    }

    fn value(&mut self, depth: usize) -> Result<Value, String> {
        if depth > MAX_DEPTH {
            return Err(self.error("nesting too deep"));
        }
        match self.peek() {
            Some(b'{') => self.object(depth),
            Some(b'[') => self.array(depth),
            Some(b'"') => Ok(Value::String(self.string()?)),
            Some(b't') => self.literal("true", Value::Bool(true)),
            Some(b'f') => self.literal("false", Value::Bool(false)),
            Some(b'n') => self.literal("null", Value::Null),
            Some(b'-' | b'0'..=b'9') => self.number(),
            Some(_) => Err(self.error("unexpected character")),
            None => Err(self.error("unexpected end")),
        }
    }

    fn object(&mut self, depth: usize) -> Result<Value, String> {
        self.expect(b'{')?;
        let mut members: Vec<(String, Value)> = Vec::new();
        self.skip_whitespace();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Ok(Value::Object(members));
        }
        loop {
            self.skip_whitespace();
            if self.peek() != Some(b'"') {
                return Err(self.error("expected a string key"));
            }
            let key = self.string()?;
            if members.iter().any(|(k, _)| *k == key) {
                return Err(self.error(&format!("duplicate key \"{key}\"")));
            }
            self.skip_whitespace();
            self.expect(b':')?;
            self.skip_whitespace();
            let value = self.value(depth + 1)?;
            members.push((key, value));
            self.skip_whitespace();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(Value::Object(members));
                }
                _ => return Err(self.error("expected ',' or '}'")),
            }
        }
    }

    fn array(&mut self, depth: usize) -> Result<Value, String> {
        self.expect(b'[')?;
        let mut items = Vec::new();
        self.skip_whitespace();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Ok(Value::Array(items));
        }
        loop {
            self.skip_whitespace();
            items.push(self.value(depth + 1)?);
            self.skip_whitespace();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b']') => {
                    self.pos += 1;
                    return Ok(Value::Array(items));
                }
                _ => return Err(self.error("expected ',' or ']'")),
            }
        }
    }

    fn number(&mut self) -> Result<Value, String> {
        let start = self.pos;
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        match self.peek() {
            Some(b'0') => self.pos += 1,
            Some(b'1'..=b'9') => self.digits(),
            _ => return Err(self.error("invalid number")),
        }
        if self.peek() == Some(b'.') {
            self.pos += 1;
            if !matches!(self.peek(), Some(b'0'..=b'9')) {
                return Err(self.error("invalid number"));
            }
            self.digits();
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            if !matches!(self.peek(), Some(b'0'..=b'9')) {
                return Err(self.error("invalid number"));
            }
            self.digits();
        }
        // Only ASCII bytes were consumed, so this slice is valid UTF-8.
        Ok(Value::Number(String::from_utf8_lossy(&self.bytes[start..self.pos]).into_owned()))
    }

    fn digits(&mut self) {
        while matches!(self.peek(), Some(b'0'..=b'9')) {
            self.pos += 1;
        }
    }

    fn hex4(&mut self) -> Result<u32, String> {
        let mut code = 0u32;
        for _ in 0..4 {
            let digit = self
                .peek()
                .and_then(|b| (b as char).to_digit(16))
                .ok_or_else(|| self.error("invalid \\u escape"))?;
            code = code * 16 + digit;
            self.pos += 1;
        }
        Ok(code)
    }

    fn string(&mut self) -> Result<String, String> {
        self.expect(b'"')?;
        let mut out = String::new();
        loop {
            let start = self.pos;
            while !matches!(self.peek(), None | Some(b'"' | b'\\' | 0x00..=0x1f)) {
                self.pos += 1;
            }
            // The input is a &str and the run stops only at ASCII bytes, so it
            // ends on a character boundary.
            out.push_str(std::str::from_utf8(&self.bytes[start..self.pos]).map_err(|_| {
                self.error("invalid UTF-8")
            })?);
            match self.peek() {
                Some(b'"') => {
                    self.pos += 1;
                    return Ok(out);
                }
                Some(b'\\') => {
                    self.pos += 1;
                    let escape = self.peek().ok_or_else(|| self.error("unexpected end"))?;
                    self.pos += 1;
                    match escape {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{8}'),
                        b'f' => out.push('\u{c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => out.push(self.unicode_escape()?),
                        _ => return Err(self.error("invalid escape")),
                    }
                }
                Some(_) => return Err(self.error("control character in string")),
                None => return Err(self.error("unterminated string")),
            }
        }
    }

    /// After `\u`: one code point, joining a surrogate pair; a lone surrogate
    /// is an error rather than a replacement character.
    fn unicode_escape(&mut self) -> Result<char, String> {
        let first = self.hex4()?;
        let code = match first {
            0xD800..=0xDBFF => {
                if !self.bytes[self.pos..].starts_with(b"\\u") {
                    return Err(self.error("unpaired surrogate"));
                }
                self.pos += 2;
                let second = self.hex4()?;
                if !(0xDC00..=0xDFFF).contains(&second) {
                    return Err(self.error("unpaired surrogate"));
                }
                0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00)
            }
            0xDC00..=0xDFFF => return Err(self.error("unpaired surrogate")),
            _ => first,
        };
        char::from_u32(code).ok_or_else(|| self.error("invalid code point"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_every_kind_of_value_keeping_key_order() {
        let value = parse(r#" {"b": [1, -2.5e3, true, false, null], "a": {"x": "y"}} "#).unwrap();
        let members = value.as_object().unwrap();
        assert_eq!(members[0].0, "b");
        assert_eq!(members[1].0, "a");
        let list = value.get("b").unwrap().as_array().unwrap();
        assert_eq!(list[0].as_u64(), Some(1));
        assert_eq!(list[1], Value::Number("-2.5e3".into()));
        assert_eq!(list[1].as_u64(), None);
        assert_eq!(list[2], Value::Bool(true));
        assert_eq!(list[4], Value::Null);
        assert_eq!(value.get("a").unwrap().get("x").unwrap().as_str(), Some("y"));
    }

    #[test]
    fn decodes_escapes_and_raw_utf8() {
        let value = parse(r#""a\"\\\/\n\u00e9\ud83d\ude00 é""#).unwrap();
        assert_eq!(value.as_str(), Some("a\"\\/\né😀 é"));
    }

    #[test]
    fn refuses_what_rfc_8259_refuses() {
        for bad in [
            "",
            "{",
            "[1,]",
            "{\"a\":1,}",
            "01",
            "1.",
            "+1",
            "'a'",
            "\"a\nb\"",
            "\"\\x\"",
            "\"\\ud800\"",
            "\"\\udc00\"",
            "tru",
            "{} {}",
            "{a:1}",
        ] {
            assert!(parse(bad).is_err(), "accepted {bad:?}");
        }
    }

    #[test]
    fn refuses_a_duplicate_key() {
        // Two readers must not see two different values in one file.
        let err = parse(r#"{"winner": "a", "winner": "b"}"#).unwrap_err();
        assert!(err.contains("duplicate key"), "{err}");
    }

    #[test]
    fn refuses_nesting_past_the_cap_instead_of_overflowing() {
        let deep = "[".repeat(MAX_DEPTH + 2) + &"]".repeat(MAX_DEPTH + 2);
        assert!(parse(&deep).is_err());
        let fine = "[".repeat(MAX_DEPTH) + &"]".repeat(MAX_DEPTH);
        assert!(parse(&fine).is_ok());
    }
}
