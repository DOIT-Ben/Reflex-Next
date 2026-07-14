use std::ffi::OsStr;
use std::fmt;
use std::path::{Path, PathBuf};

pub const LIFECYCLE_DATA_ROOT_ENV: &str = "REFLEX_LIFECYCLE_DATA_ROOT";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AppPaths {
    config_dir: PathBuf,
    data_dir: PathBuf,
}

impl AppPaths {
    pub fn resolve(
        default_config_dir: PathBuf,
        default_data_dir: PathBuf,
    ) -> Result<Self, AppPathsError> {
        Self::from_override(
            default_config_dir,
            default_data_dir,
            std::env::var_os(LIFECYCLE_DATA_ROOT_ENV).as_deref(),
            &std::env::temp_dir(),
        )
    }

    pub fn config_dir(&self) -> &Path {
        &self.config_dir
    }

    pub fn data_dir(&self) -> &Path {
        &self.data_dir
    }

    fn from_override(
        default_config_dir: PathBuf,
        default_data_dir: PathBuf,
        override_root: Option<&OsStr>,
        temporary_root: &Path,
    ) -> Result<Self, AppPathsError> {
        let Some(override_root) = override_root else {
            return Ok(Self {
                config_dir: default_config_dir,
                data_dir: default_data_dir,
            });
        };
        let root = validated_lifecycle_root(Path::new(override_root), temporary_root)?;
        Ok(Self {
            config_dir: root.join("config"),
            data_dir: root.join("data"),
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AppPathsError;

impl fmt::Display for AppPathsError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("应用数据目录不可用。")
    }
}

impl std::error::Error for AppPathsError {}

fn validated_lifecycle_root(root: &Path, temporary_root: &Path) -> Result<PathBuf, AppPathsError> {
    if !root.is_absolute() || !root.is_dir() || !temporary_root.is_dir() {
        return Err(AppPathsError);
    }
    let root = root.canonicalize().map_err(|_| AppPathsError)?;
    let temporary_root = temporary_root.canonicalize().map_err(|_| AppPathsError)?;
    if root == temporary_root || !root.starts_with(&temporary_root) {
        return Err(AppPathsError);
    }
    Ok(root)
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::sync::atomic::{AtomicU64, Ordering};

    use super::{AppPaths, AppPathsError};

    static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(0);

    struct TestDirectory {
        path: std::path::PathBuf,
    }

    impl TestDirectory {
        fn new() -> Self {
            let sequence = NEXT_DIRECTORY.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "reflex-app-paths-test-{}-{sequence}",
                std::process::id()
            ));
            let _ = fs::remove_dir_all(&path);
            fs::create_dir_all(&path).unwrap();
            Self { path }
        }
    }

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.path);
        }
    }

    #[test]
    fn defaults_are_preserved_without_a_lifecycle_override() {
        let paths = AppPaths::from_override(
            "default-config".into(),
            "default-data".into(),
            None,
            &std::env::temp_dir(),
        )
        .unwrap();

        assert_eq!(paths.config_dir(), std::path::Path::new("default-config"));
        assert_eq!(paths.data_dir(), std::path::Path::new("default-data"));
    }

    #[test]
    fn lifecycle_override_separates_config_and_data_under_temp() {
        let temporary_root = TestDirectory::new();
        let override_root = temporary_root.path.join("profile");
        fs::create_dir_all(&override_root).unwrap();

        let paths = AppPaths::from_override(
            "ignored-config".into(),
            "ignored-data".into(),
            Some(override_root.as_os_str()),
            &temporary_root.path,
        )
        .unwrap();

        let canonical_root = override_root.canonicalize().unwrap();
        assert_eq!(paths.config_dir(), canonical_root.join("config"));
        assert_eq!(paths.data_dir(), canonical_root.join("data"));
    }

    #[test]
    fn lifecycle_override_rejects_temp_root_and_paths_outside_it() {
        let temporary_root = TestDirectory::new();
        let outside_root = TestDirectory::new();

        for root in [&temporary_root.path, &outside_root.path] {
            assert_eq!(
                AppPaths::from_override(
                    "ignored-config".into(),
                    "ignored-data".into(),
                    Some(root.as_os_str()),
                    &temporary_root.path,
                ),
                Err(AppPathsError)
            );
        }
    }
}
