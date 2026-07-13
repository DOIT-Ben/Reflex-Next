use std::fmt;

use serde::Serialize;

const CREDENTIAL_SERVICE: &str = "com.reflex-next.provider";
pub const SECRET_STORE_ERROR_MESSAGE: &str = "系统安全存储暂不可用。";
const SECRET_INPUT_INVALID_MESSAGE: &str = "密钥信息无效。";

pub trait CredentialBackend: Send + Sync + 'static {
    fn get(&self, service: &str, account: &str) -> Result<Option<String>, ()>;
    fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), ()>;
    fn delete(&self, service: &str, account: &str) -> Result<(), ()>;
}

pub struct KeyringCredentialBackend;

impl CredentialBackend for KeyringCredentialBackend {
    fn get(&self, service: &str, account: &str) -> Result<Option<String>, ()> {
        let entry = keyring::Entry::new(service, account).map_err(|_| ())?;
        match entry.get_password() {
            Ok(secret) => Ok(Some(secret)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(_) => Err(()),
        }
    }

    fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), ()> {
        keyring::Entry::new(service, account)
            .map_err(|_| ())?
            .set_password(secret)
            .map_err(|_| ())
    }

    fn delete(&self, service: &str, account: &str) -> Result<(), ()> {
        let entry = keyring::Entry::new(service, account).map_err(|_| ())?;
        match entry.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(_) => Err(()),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct SecretStatus {
    pub provider_id: String,
    pub configured: bool,
    pub masked_tail: Option<String>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum SecretStoreError {
    InvalidInput,
    BackendUnavailable,
}

impl fmt::Debug for SecretStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidInput => "SecretStoreError::InvalidInput",
            Self::BackendUnavailable => "SecretStoreError::BackendUnavailable",
        })
    }
}

impl fmt::Display for SecretStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidInput => SECRET_INPUT_INVALID_MESSAGE,
            Self::BackendUnavailable => SECRET_STORE_ERROR_MESSAGE,
        })
    }
}

impl std::error::Error for SecretStoreError {}

pub struct SecretStore<B = KeyringCredentialBackend>
where
    B: CredentialBackend,
{
    backend: B,
}

impl SecretStore<KeyringCredentialBackend> {
    pub fn windows() -> Self {
        Self::new(KeyringCredentialBackend)
    }
}

impl<B> SecretStore<B>
where
    B: CredentialBackend,
{
    pub fn new(backend: B) -> Self {
        Self { backend }
    }

    pub fn status(&self, provider_id: &str) -> Result<SecretStatus, SecretStoreError> {
        let provider_id = normalize_provider_id(provider_id)?;
        let secret = self.read(&provider_id)?;
        Ok(status_from_secret(provider_id, secret.as_deref()))
    }

    pub fn save(&self, provider_id: &str, secret: &str) -> Result<SecretStatus, SecretStoreError> {
        let provider_id = normalize_provider_id(provider_id)?;
        let secret = normalize_secret(secret)?;
        self.backend
            .set(CREDENTIAL_SERVICE, &account_name(&provider_id), secret)
            .map_err(|_| SecretStoreError::BackendUnavailable)?;
        Ok(status_from_secret(provider_id, Some(secret)))
    }

    pub fn delete(&self, provider_id: &str) -> Result<SecretStatus, SecretStoreError> {
        let provider_id = normalize_provider_id(provider_id)?;
        self.backend
            .delete(CREDENTIAL_SERVICE, &account_name(&provider_id))
            .map_err(|_| SecretStoreError::BackendUnavailable)?;
        Ok(status_from_secret(provider_id, None))
    }

    pub(crate) fn read(&self, provider_id: &str) -> Result<Option<String>, SecretStoreError> {
        let provider_id = normalize_provider_id(provider_id)?;
        self.backend
            .get(CREDENTIAL_SERVICE, &account_name(&provider_id))
            .map_err(|_| SecretStoreError::BackendUnavailable)
    }
}

fn normalize_provider_id(provider_id: &str) -> Result<String, SecretStoreError> {
    let provider_id = provider_id.trim();
    if provider_id.is_empty()
        || provider_id.len() > 64
        || !provider_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    {
        Err(SecretStoreError::InvalidInput)
    } else {
        Ok(provider_id.to_ascii_lowercase())
    }
}

fn normalize_secret(secret: &str) -> Result<&str, SecretStoreError> {
    let secret = secret.trim();
    if secret.is_empty() || secret.len() > 16_384 {
        Err(SecretStoreError::InvalidInput)
    } else {
        Ok(secret)
    }
}

fn account_name(provider_id: &str) -> String {
    format!("provider:{provider_id}")
}

fn status_from_secret(provider_id: String, secret: Option<&str>) -> SecretStatus {
    SecretStatus {
        provider_id,
        configured: secret.is_some(),
        masked_tail: secret.map(masked_tail),
    }
}

fn masked_tail(secret: &str) -> String {
    let reversed = secret.chars().rev().take(4).collect::<String>();
    reversed.chars().rev().collect()
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Mutex;

    use super::{CredentialBackend, SecretStore, SECRET_STORE_ERROR_MESSAGE};

    #[derive(Default)]
    struct MemoryCredentialBackend {
        values: Mutex<HashMap<(String, String), String>>,
    }

    impl CredentialBackend for MemoryCredentialBackend {
        fn get(&self, service: &str, account: &str) -> Result<Option<String>, ()> {
            Ok(self
                .values
                .lock()
                .unwrap()
                .get(&(service.to_string(), account.to_string()))
                .cloned())
        }

        fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), ()> {
            self.values.lock().unwrap().insert(
                (service.to_string(), account.to_string()),
                secret.to_string(),
            );
            Ok(())
        }

        fn delete(&self, service: &str, account: &str) -> Result<(), ()> {
            self.values
                .lock()
                .unwrap()
                .remove(&(service.to_string(), account.to_string()));
            Ok(())
        }
    }

    struct FailingCredentialBackend;

    impl CredentialBackend for FailingCredentialBackend {
        fn get(&self, _service: &str, _account: &str) -> Result<Option<String>, ()> {
            Err(())
        }

        fn set(&self, _service: &str, _account: &str, _secret: &str) -> Result<(), ()> {
            Err(())
        }

        fn delete(&self, _service: &str, _account: &str) -> Result<(), ()> {
            Err(())
        }
    }

    #[test]
    fn save_status_and_delete_never_return_the_full_secret() {
        let store = SecretStore::new(MemoryCredentialBackend::default());
        let secret = "fixture-stage-a-secret";

        let saved = store.save("MiniMax", secret).unwrap();
        assert_eq!(saved.provider_id, "minimax");
        assert!(saved.configured);
        assert_eq!(saved.masked_tail.as_deref(), Some("cret"));
        assert!(!serde_json::to_string(&saved).unwrap().contains(secret));
        assert!(!format!("{saved:?}").contains(secret));
        assert_eq!(store.read("minimax").unwrap().as_deref(), Some(secret));

        let deleted = store.delete("minimax").unwrap();
        assert!(!deleted.configured);
        assert!(deleted.masked_tail.is_none());
        assert!(store.read("minimax").unwrap().is_none());
    }

    #[test]
    fn status_reports_only_configuration_and_a_four_character_tail() {
        let store = SecretStore::new(MemoryCredentialBackend::default());
        store.save("minimax", "1234567890").unwrap();

        assert_eq!(
            store.status("minimax").unwrap().masked_tail.as_deref(),
            Some("7890")
        );
    }

    #[test]
    fn rejects_unsafe_provider_ids_and_blank_secrets() {
        let store = SecretStore::new(MemoryCredentialBackend::default());

        assert!(store.save("../minimax", "fixture-secret").is_err());
        assert!(store.save("minimax", "   ").is_err());
        assert!(store.status("provider/name").is_err());
    }

    #[test]
    fn delete_is_idempotent_when_no_credential_exists() {
        let store = SecretStore::new(MemoryCredentialBackend::default());

        let status = store.delete("minimax").unwrap();

        assert!(!status.configured);
    }

    #[test]
    fn backend_failures_use_one_fixed_message_without_backend_details() {
        let store = SecretStore::new(FailingCredentialBackend);

        let error = store.status("minimax").unwrap_err();

        assert_eq!(error.to_string(), SECRET_STORE_ERROR_MESSAGE);
        assert!(!format!("{error:?}").contains("minimax"));
    }

    #[test]
    #[ignore = "requires the Windows Credential Manager"]
    fn windows_backend_treats_a_missing_probe_entry_as_unconfigured() {
        let store = SecretStore::windows();

        let status = store.status("reflex-stage-a-readonly-probe").unwrap();

        assert!(!status.configured);
        assert!(status.masked_tail.is_none());
    }

    #[test]
    #[ignore = "requires the Windows Credential Manager"]
    fn windows_backend_reads_minimax_status_without_exposing_the_secret() {
        let store = SecretStore::windows();

        let status = store.status("minimax").unwrap();

        assert_eq!(status.provider_id, "minimax");
    }

    #[test]
    #[ignore = "requires the Windows Credential Manager"]
    fn windows_backend_round_trips_an_isolated_probe_credential() {
        const PROVIDER_ID: &str = "reflex-production-credential-probe";
        const SECRET: &str = "fixture-windows-credential-probe-9a8b7c6d";

        struct ProbeCleanup;

        impl Drop for ProbeCleanup {
            fn drop(&mut self) {
                let _ = SecretStore::windows().delete(PROVIDER_ID);
            }
        }

        let store = SecretStore::windows();
        let _cleanup = ProbeCleanup;
        store.delete(PROVIDER_ID).unwrap();

        let saved = store.save(PROVIDER_ID, SECRET).unwrap();
        assert!(saved.configured);
        assert_eq!(saved.masked_tail.as_deref(), Some("7c6d"));
        assert_eq!(store.read(PROVIDER_ID).unwrap().as_deref(), Some(SECRET));

        let deleted = store.delete(PROVIDER_ID).unwrap();
        assert!(!deleted.configured);
        assert!(store.read(PROVIDER_ID).unwrap().is_none());
    }
}
