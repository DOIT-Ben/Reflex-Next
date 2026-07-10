use tauri::AppHandle;
use tauri_plugin_clipboard_manager::ClipboardExt;

pub const CLIPBOARD_READ_ERROR_MESSAGE: &str = "无法读取剪贴板，请确认权限后重试。";

pub trait ClipboardTextReader {
    type Error;

    fn read_text(&self) -> Result<String, Self::Error>;
}

impl ClipboardTextReader for AppHandle {
    type Error = String;

    fn read_text(&self) -> Result<String, Self::Error> {
        self.clipboard().read_text().map_err(|error| error.to_string())
    }
}

pub fn sanitize_clipboard_read_error<E>(_error: E) -> &'static str {
    CLIPBOARD_READ_ERROR_MESSAGE
}

pub fn read_clipboard_text<R>(reader: &R) -> Result<String, &'static str>
where
    R: ClipboardTextReader,
{
    reader
        .read_text()
        .map_err(sanitize_clipboard_read_error)
}

#[cfg(test)]
mod tests {
    use super::{
        read_clipboard_text, sanitize_clipboard_read_error, ClipboardTextReader,
        CLIPBOARD_READ_ERROR_MESSAGE,
    };

    #[derive(Debug, Clone, PartialEq, Eq)]
    struct FakeError(&'static str);

    enum FakeClipboard {
        Text(&'static str),
        Error(FakeError),
    }

    impl ClipboardTextReader for FakeClipboard {
        type Error = FakeError;

        fn read_text(&self) -> Result<String, <Self as ClipboardTextReader>::Error> {
            match self {
                Self::Text(text) => Ok((*text).to_string()),
                Self::Error(error) => Err(error.clone()),
            }
        }
    }

    #[test]
    fn passes_through_clipboard_text_unchanged() {
        let clipboard = FakeClipboard::Text("  来自系统剪贴板的原始文本  ");

        let result = read_clipboard_text(&clipboard);

        assert_eq!(
            result,
            Ok("  来自系统剪贴板的原始文本  ".to_string())
        );
    }

    #[test]
    fn sanitizes_backend_failures_without_exposing_raw_error() {
        let clipboard = FakeClipboard::Error(FakeError("NotAllowedError: raw backend failure"));

        let result = read_clipboard_text(&clipboard);

        assert_eq!(result, Err(CLIPBOARD_READ_ERROR_MESSAGE));
        assert_eq!(
            sanitize_clipboard_read_error(FakeError("raw backend failure")),
            CLIPBOARD_READ_ERROR_MESSAGE
        );
    }
}
