use std::fmt;

use crate::secret_store::{CredentialBackend, KeyringCredentialBackend};

const CLOUD_CREDENTIAL_SERVICE: &str = "com.reflex-next.cloud";
const INSTALLATION_ACCOUNT: &str = "installation";
pub const CLOUD_TOKEN_STORE_ERROR_MESSAGE: &str = "云端身份暂不可用。";

pub struct CloudTokenStore<B = KeyringCredentialBackend>
where
    B: CredentialBackend,
{
    backend: B,
}

impl CloudTokenStore<KeyringCredentialBackend> {
    pub fn windows() -> Self {
        Self::new(KeyringCredentialBackend)
    }
}

impl<B> CloudTokenStore<B>
where
    B: CredentialBackend,
{
    pub fn new(backend: B) -> Self {
        Self { backend }
    }

    pub fn read(&self) -> Result<Option<String>, CloudTokenStoreError> {
        self.backend
            .get(CLOUD_CREDENTIAL_SERVICE, INSTALLATION_ACCOUNT)
            .map_err(|_| CloudTokenStoreError)
    }

    pub fn save(&self, token: &str) -> Result<(), CloudTokenStoreError> {
        let token = validated_token(token)?;
        self.backend
            .set(CLOUD_CREDENTIAL_SERVICE, INSTALLATION_ACCOUNT, token)
            .map_err(|_| CloudTokenStoreError)
    }

    pub fn delete(&self) -> Result<(), CloudTokenStoreError> {
        self.backend
            .delete(CLOUD_CREDENTIAL_SERVICE, INSTALLATION_ACCOUNT)
            .map_err(|_| CloudTokenStoreError)
    }
}

#[derive(Clone, Copy)]
pub struct CloudTokenStoreError;

impl fmt::Debug for CloudTokenStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CloudTokenStoreError")
    }
}

impl fmt::Display for CloudTokenStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(CLOUD_TOKEN_STORE_ERROR_MESSAGE)
    }
}

impl std::error::Error for CloudTokenStoreError {}

fn validated_token(token: &str) -> Result<&str, CloudTokenStoreError> {
    let token = token.trim();
    if !(32..=256).contains(&token.len())
        || !token
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
    {
        return Err(CloudTokenStoreError);
    }
    Ok(token)
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Mutex;

    use crate::secret_store::CredentialBackend;

    use super::CloudTokenStore;

    #[derive(Default)]
    struct MemoryBackend {
        values: Mutex<HashMap<(String, String), String>>,
    }

    impl CredentialBackend for MemoryBackend {
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

    #[test]
    fn stores_only_valid_opaque_installation_tokens() {
        let store = CloudTokenStore::new(MemoryBackend::default());
        let token = "fixture_installation_token_1234567890";

        store.save(token).unwrap();

        assert_eq!(store.read().unwrap().as_deref(), Some(token));
        store.delete().unwrap();
        assert!(store.read().unwrap().is_none());
        assert!(store.save("short").is_err());
        assert!(store.save("unsafe/token/fixture________________").is_err());
    }
}
