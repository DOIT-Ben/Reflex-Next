#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::{Arc, Mutex};

    use crate::secret_store::CredentialBackend;

    use super::{HistoryKeyStore, HISTORY_KEY_STORE_ERROR_MESSAGE, HISTORY_SERVICE, STATE_ACCOUNT};

    #[derive(Clone, Default)]
    struct MemoryCredentialBackend {
        values: Arc<Mutex<HashMap<(String, String), String>>>,
        fail: Arc<Mutex<bool>>,
    }

    impl MemoryCredentialBackend {
        fn value(&self, service: &str, account: &str) -> Option<String> {
            self.values
                .lock()
                .unwrap()
                .get(&(service.to_string(), account.to_string()))
                .cloned()
        }

        fn insert(&self, service: &str, account: &str, value: &str) {
            self.values.lock().unwrap().insert(
                (service.to_string(), account.to_string()),
                value.to_string(),
            );
        }
    }

    impl CredentialBackend for MemoryCredentialBackend {
        fn get(&self, service: &str, account: &str) -> Result<Option<String>, ()> {
            if *self.fail.lock().unwrap() {
                return Err(());
            }
            Ok(self.value(service, account))
        }

        fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), ()> {
            if *self.fail.lock().unwrap() {
                return Err(());
            }
            self.insert(service, account, secret);
            Ok(())
        }

        fn delete(&self, service: &str, account: &str) -> Result<(), ()> {
            if *self.fail.lock().unwrap() {
                return Err(());
            }
            self.values
                .lock()
                .unwrap()
                .remove(&(service.to_string(), account.to_string()));
            Ok(())
        }
    }

    #[test]
    fn ensure_active_creates_one_versioned_32_byte_key_and_is_idempotent() {
        let backend = MemoryCredentialBackend::default();
        let store = HistoryKeyStore::new(backend.clone());

        let first = store.ensure_active().unwrap();
        let second = store.ensure_active().unwrap();
        let encoded = backend.value(HISTORY_SERVICE, "key:v1").unwrap();

        assert_eq!(first, second);
        assert!(first.configured);
        assert_eq!(first.active_version, Some(1));
        assert_eq!(first.pending_version, None);
        assert!(!first.rotation_pending);
        assert_eq!(encoded.len(), 64);
        assert!(encoded.bytes().all(|byte| byte.is_ascii_hexdigit()));
        let state = backend.value(HISTORY_SERVICE, STATE_ACCOUNT).unwrap();
        assert!(!state.contains(&encoded));
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(&state).unwrap(),
            serde_json::json!({
                "active_version": 1,
                "pending_version": null
            })
        );
        assert_eq!(store.active_keys().unwrap().get("v1"), Some(&encoded));
    }

    #[test]
    fn rotation_versions_have_distinct_values_and_promote_keeps_old_keys() {
        let backend = MemoryCredentialBackend::default();
        let store = HistoryKeyStore::new(backend.clone());
        store.ensure_active().unwrap();

        let pending = store.begin_rotation().unwrap();
        assert_eq!(pending.active_version, Some(1));
        assert_eq!(pending.pending_version, Some(2));
        assert!(pending.rotation_pending);
        assert_eq!(store.active_keys().unwrap().len(), 1);

        let promoted = store.promote().unwrap();
        let keys = store.active_keys().unwrap();
        assert_eq!(promoted.active_version, Some(2));
        assert_eq!(promoted.pending_version, None);
        assert!(!promoted.rotation_pending);
        assert_eq!(keys.len(), 2);
        assert_ne!(keys["v1"], keys["v2"]);
        assert!(backend.value(HISTORY_SERVICE, "key:v1").is_some());
    }

    #[test]
    fn rollback_clears_pending_state_but_preserves_and_never_overwrites_the_key() {
        let backend = MemoryCredentialBackend::default();
        let store = HistoryKeyStore::new(backend.clone());
        store.ensure_active().unwrap();
        store.begin_rotation().unwrap();
        let rolled_back_value = backend.value(HISTORY_SERVICE, "key:v2").unwrap();

        let rolled_back = store.rollback().unwrap();
        assert_eq!(rolled_back.active_version, Some(1));
        assert_eq!(rolled_back.pending_version, None);
        assert_eq!(
            backend.value(HISTORY_SERVICE, "key:v2"),
            Some(rolled_back_value.clone())
        );

        let next = store.begin_rotation().unwrap();
        assert_eq!(next.pending_version, Some(3));
        assert_eq!(
            backend.value(HISTORY_SERVICE, "key:v2"),
            Some(rolled_back_value)
        );
    }

    #[test]
    fn status_and_debug_never_expose_key_material() {
        let backend = MemoryCredentialBackend::default();
        let store = HistoryKeyStore::new(backend.clone());
        let status = store.ensure_active().unwrap();
        let encoded = backend.value(HISTORY_SERVICE, "key:v1").unwrap();

        let serialized = serde_json::to_string(&status).unwrap();
        let debug = format!("{status:?} {store:?}");
        assert!(!serialized.contains(&encoded));
        assert!(!debug.contains(&encoded));
        assert!(!serialized.contains("key:"));
    }

    #[test]
    fn invalid_state_or_key_material_is_rejected() {
        for (state, key) in [
            ("not-json", None),
            (r#"{"active_version":0,"pending_version":null}"#, None),
            (
                r#"{"active_version":1,"pending_version":1}"#,
                Some("00".repeat(32)),
            ),
            (
                r#"{"active_version":1,"pending_version":null}"#,
                Some("g".repeat(64)),
            ),
            (
                r#"{"active_version":1,"pending_version":null}"#,
                Some("AA".repeat(32)),
            ),
        ] {
            let backend = MemoryCredentialBackend::default();
            backend.insert(HISTORY_SERVICE, STATE_ACCOUNT, state);
            if let Some(key) = key {
                backend.insert(HISTORY_SERVICE, "key:v1", &key);
            }
            let store = HistoryKeyStore::new(backend);

            assert!(store.status().is_err());
        }
    }

    #[test]
    fn backend_failures_return_one_fixed_safe_error() {
        let backend = MemoryCredentialBackend::default();
        *backend.fail.lock().unwrap() = true;
        let store = HistoryKeyStore::new(backend);

        let error = store.ensure_active().unwrap_err();
        assert_eq!(error.to_string(), HISTORY_KEY_STORE_ERROR_MESSAGE);
        assert!(!format!("{error:?}").contains("credential"));
    }
}
use std::collections::BTreeMap;
use std::fmt;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

use crate::secret_store::{CredentialBackend, KeyringCredentialBackend};

const HISTORY_SERVICE: &str = "com.reflex-next.history";
const STATE_ACCOUNT: &str = "state";
const MAX_KEY_VERSION: u32 = 1_000_000;
pub const HISTORY_KEY_STORE_ERROR_MESSAGE: &str = "历史密钥存储暂不可用。";

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct HistoryKeyStatus {
    pub configured: bool,
    pub active_version: Option<u32>,
    pub pending_version: Option<u32>,
    pub rotation_pending: bool,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum HistoryKeyStoreError {
    InvalidData,
    BackendUnavailable,
    EntropyUnavailable,
}

impl fmt::Debug for HistoryKeyStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidData => "HistoryKeyStoreError::InvalidData",
            Self::BackendUnavailable => "HistoryKeyStoreError::BackendUnavailable",
            Self::EntropyUnavailable => "HistoryKeyStoreError::EntropyUnavailable",
        })
    }
}

impl fmt::Display for HistoryKeyStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(HISTORY_KEY_STORE_ERROR_MESSAGE)
    }
}

impl std::error::Error for HistoryKeyStoreError {}

#[derive(Debug, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct HistoryKeyState {
    active_version: Option<u32>,
    pending_version: Option<u32>,
}

pub struct HistoryKeyStore<B = KeyringCredentialBackend>
where
    B: CredentialBackend,
{
    backend: B,
    operation_lock: Mutex<()>,
}

impl<B> fmt::Debug for HistoryKeyStore<B>
where
    B: CredentialBackend,
{
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("HistoryKeyStore")
            .field("backend", &"[PRIVATE]")
            .finish_non_exhaustive()
    }
}

impl HistoryKeyStore<KeyringCredentialBackend> {
    pub fn windows() -> Self {
        Self::new(KeyringCredentialBackend)
    }
}

impl<B> HistoryKeyStore<B>
where
    B: CredentialBackend,
{
    pub fn new(backend: B) -> Self {
        Self {
            backend,
            operation_lock: Mutex::new(()),
        }
    }

    // Rotation controls stay host-private until the history management UI is introduced.
    #[allow(dead_code)]
    pub fn status(&self) -> Result<HistoryKeyStatus, HistoryKeyStoreError> {
        let _guard = self.lock()?;
        let state = self.load_state()?;
        self.validate_referenced_keys(&state)?;
        Ok(status_from_state(&state))
    }

    pub fn ensure_active(&self) -> Result<HistoryKeyStatus, HistoryKeyStoreError> {
        let _guard = self.lock()?;
        let mut state = self.load_state()?;
        if state.active_version.is_none() {
            let account = key_account(1);
            match self.backend_get(&account)? {
                Some(encoded) => validate_encoded_key(&encoded)?,
                None => self.backend_set(&account, &generate_encoded_key()?)?,
            }
            state.active_version = Some(1);
            self.save_state(&state)?;
        }
        self.validate_referenced_keys(&state)?;
        Ok(status_from_state(&state))
    }

    #[allow(dead_code)]
    pub fn begin_rotation(&self) -> Result<HistoryKeyStatus, HistoryKeyStoreError> {
        let _guard = self.lock()?;
        let mut state = self.load_state()?;
        let active = state
            .active_version
            .ok_or(HistoryKeyStoreError::InvalidData)?;
        self.validate_referenced_keys(&state)?;
        if state.pending_version.is_none() {
            let version = self.first_unused_version(active)?;
            self.backend_set(&key_account(version), &generate_encoded_key()?)?;
            state.pending_version = Some(version);
            self.save_state(&state)?;
        }
        Ok(status_from_state(&state))
    }

    #[allow(dead_code)]
    pub fn promote(&self) -> Result<HistoryKeyStatus, HistoryKeyStoreError> {
        let _guard = self.lock()?;
        let mut state = self.load_state()?;
        self.validate_referenced_keys(&state)?;
        let pending = state
            .pending_version
            .ok_or(HistoryKeyStoreError::InvalidData)?;
        state.active_version = Some(pending);
        state.pending_version = None;
        self.save_state(&state)?;
        Ok(status_from_state(&state))
    }

    #[allow(dead_code)]
    pub fn rollback(&self) -> Result<HistoryKeyStatus, HistoryKeyStoreError> {
        let _guard = self.lock()?;
        let mut state = self.load_state()?;
        self.validate_referenced_keys(&state)?;
        if state.pending_version.take().is_some() {
            self.save_state(&state)?;
        }
        Ok(status_from_state(&state))
    }

    pub(crate) fn active_keys(&self) -> Result<BTreeMap<String, String>, HistoryKeyStoreError> {
        let _guard = self.lock()?;
        let state = self.load_state()?;
        self.validate_referenced_keys(&state)?;
        let Some(active) = state.active_version else {
            return Ok(BTreeMap::new());
        };
        let mut keys = BTreeMap::new();
        for version in 1..=active {
            let encoded = self
                .backend_get(&key_account(version))?
                .ok_or(HistoryKeyStoreError::InvalidData)?;
            validate_encoded_key(&encoded)?;
            keys.insert(format!("v{version}"), encoded);
        }
        Ok(keys)
    }

    fn lock(&self) -> Result<std::sync::MutexGuard<'_, ()>, HistoryKeyStoreError> {
        self.operation_lock
            .lock()
            .map_err(|_| HistoryKeyStoreError::BackendUnavailable)
    }

    fn load_state(&self) -> Result<HistoryKeyState, HistoryKeyStoreError> {
        let Some(raw) = self.backend_get(STATE_ACCOUNT)? else {
            return Ok(HistoryKeyState::default());
        };
        let state: HistoryKeyState =
            serde_json::from_str(&raw).map_err(|_| HistoryKeyStoreError::InvalidData)?;
        validate_state(&state)?;
        Ok(state)
    }

    fn save_state(&self, state: &HistoryKeyState) -> Result<(), HistoryKeyStoreError> {
        validate_state(state)?;
        let encoded =
            serde_json::to_string(state).map_err(|_| HistoryKeyStoreError::InvalidData)?;
        self.backend_set(STATE_ACCOUNT, &encoded)
    }

    fn validate_referenced_keys(
        &self,
        state: &HistoryKeyState,
    ) -> Result<(), HistoryKeyStoreError> {
        for version in [state.active_version, state.pending_version]
            .into_iter()
            .flatten()
        {
            let encoded = self
                .backend_get(&key_account(version))?
                .ok_or(HistoryKeyStoreError::InvalidData)?;
            validate_encoded_key(&encoded)?;
        }
        Ok(())
    }

    fn first_unused_version(&self, active: u32) -> Result<u32, HistoryKeyStoreError> {
        for version in active.saturating_add(1)..=MAX_KEY_VERSION {
            if self.backend_get(&key_account(version))?.is_none() {
                return Ok(version);
            }
        }
        Err(HistoryKeyStoreError::InvalidData)
    }

    fn backend_get(&self, account: &str) -> Result<Option<String>, HistoryKeyStoreError> {
        self.backend
            .get(HISTORY_SERVICE, account)
            .map_err(|_| HistoryKeyStoreError::BackendUnavailable)
    }

    fn backend_set(&self, account: &str, value: &str) -> Result<(), HistoryKeyStoreError> {
        self.backend
            .set(HISTORY_SERVICE, account, value)
            .map_err(|_| HistoryKeyStoreError::BackendUnavailable)
    }
}

fn status_from_state(state: &HistoryKeyState) -> HistoryKeyStatus {
    HistoryKeyStatus {
        configured: state.active_version.is_some(),
        active_version: state.active_version,
        pending_version: state.pending_version,
        rotation_pending: state.pending_version.is_some(),
    }
}

fn validate_state(state: &HistoryKeyState) -> Result<(), HistoryKeyStoreError> {
    let valid_active = state
        .active_version
        .is_none_or(|version| (1..=MAX_KEY_VERSION).contains(&version));
    let valid_pending = match (state.active_version, state.pending_version) {
        (_, None) => true,
        (Some(active), Some(pending)) => pending > active && pending <= MAX_KEY_VERSION,
        (None, Some(_)) => false,
    };
    if valid_active && valid_pending {
        Ok(())
    } else {
        Err(HistoryKeyStoreError::InvalidData)
    }
}

fn validate_encoded_key(encoded: &str) -> Result<(), HistoryKeyStoreError> {
    if encoded.len() == 64
        && encoded
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    {
        Ok(())
    } else {
        Err(HistoryKeyStoreError::InvalidData)
    }
}

fn generate_encoded_key() -> Result<String, HistoryKeyStoreError> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| HistoryKeyStoreError::EntropyUnavailable)?;
    let mut encoded = String::with_capacity(64);
    for byte in bytes {
        use std::fmt::Write;
        write!(&mut encoded, "{byte:02x}").map_err(|_| HistoryKeyStoreError::InvalidData)?;
    }
    Ok(encoded)
}

fn key_account(version: u32) -> String {
    format!("key:v{version}")
}
