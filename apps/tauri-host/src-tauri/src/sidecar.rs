use std::collections::HashSet;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::Value;

use crate::runtime_commands::ValidatedCommand;

pub const RUNTIME_UNAVAILABLE_MESSAGE: &str = "运行服务暂不可用，请稍后重试。";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimePaths {
    pub root: PathBuf,
    pub runtime_dir: PathBuf,
    pub runtime_src: PathBuf,
    pub core_src: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PythonLauncher {
    Override(PathBuf),
    UvManaged312,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LaunchSpec {
    pub program: PathBuf,
    pub arguments: Vec<String>,
    pub current_dir: PathBuf,
    pub python_path: Vec<PathBuf>,
}

pub trait ChildProcess: Send {
    fn has_exited(&mut self) -> io::Result<bool>;
    fn write_stdin(&mut self, bytes: &[u8]) -> io::Result<()>;
    fn flush_stdin(&mut self) -> io::Result<()>;
    fn close_stdin(&mut self) {}
    fn take_stdout(&mut self) -> Option<Box<dyn Read + Send>> {
        None
    }
    fn take_stderr(&mut self) -> Option<Box<dyn Read + Send>> {
        None
    }
    fn wait_for(&mut self, timeout: Duration) -> io::Result<bool> {
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            if self.has_exited()? {
                return Ok(true);
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        self.has_exited()
    }
    fn terminate(&mut self) -> io::Result<()> {
        Ok(())
    }
}

pub trait ProcessFactory: Clone + Send + Sync {
    fn spawn(&self) -> Result<Box<dyn ChildProcess>, &'static str>;
}

#[derive(Clone)]
pub struct OsProcessFactory {
    launch: LaunchSpec,
}

impl OsProcessFactory {
    pub fn new(launch: LaunchSpec) -> Self {
        Self { launch }
    }
}

impl ProcessFactory for OsProcessFactory {
    fn spawn(&self) -> Result<Box<dyn ChildProcess>, &'static str> {
        let python_path = std::env::join_paths(&self.launch.python_path)
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        let child = Command::new(&self.launch.program)
            .args(&self.launch.arguments)
            .current_dir(&self.launch.current_dir)
            .env("PYTHONPATH", python_path)
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        Ok(Box::new(OsChildProcess::new(child)))
    }
}

struct OsChildProcess {
    child: Child,
    stdin: Option<ChildStdin>,
    stdout: Option<ChildStdout>,
    stderr: Option<ChildStderr>,
}

impl OsChildProcess {
    fn new(mut child: Child) -> Self {
        Self {
            stdin: child.stdin.take(),
            stdout: child.stdout.take(),
            stderr: child.stderr.take(),
            child,
        }
    }
}

impl ChildProcess for OsChildProcess {
    fn has_exited(&mut self) -> io::Result<bool> {
        self.child.try_wait().map(|status| status.is_some())
    }

    fn write_stdin(&mut self, bytes: &[u8]) -> io::Result<()> {
        self.stdin
            .as_mut()
            .ok_or_else(|| io::Error::new(io::ErrorKind::BrokenPipe, "stdin closed"))?
            .write_all(bytes)
    }

    fn flush_stdin(&mut self) -> io::Result<()> {
        self.stdin
            .as_mut()
            .ok_or_else(|| io::Error::new(io::ErrorKind::BrokenPipe, "stdin closed"))?
            .flush()
    }

    fn close_stdin(&mut self) {
        self.stdin.take();
    }

    fn take_stdout(&mut self) -> Option<Box<dyn Read + Send>> {
        self.stdout
            .take()
            .map(|stream| Box::new(stream) as Box<dyn Read + Send>)
    }

    fn take_stderr(&mut self) -> Option<Box<dyn Read + Send>> {
        self.stderr
            .take()
            .map(|stream| Box::new(stream) as Box<dyn Read + Send>)
    }

    fn terminate(&mut self) -> io::Result<()> {
        match self.child.kill() {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == io::ErrorKind::InvalidInput => Ok(()),
            Err(error) => Err(error),
        }
    }
}

pub trait EventEmitter: Send + Sync {
    fn emit(&self, payload: Value);
}

struct RunningProcess {
    process: Box<dyn ChildProcess>,
    active_request_ids: Arc<Mutex<HashSet<String>>>,
    stopping: Arc<AtomicBool>,
}

pub struct RuntimeSidecar<F>
where
    F: ProcessFactory,
{
    factory: F,
    emitter: Arc<dyn EventEmitter>,
    running: Mutex<Option<RunningProcess>>,
}

impl<F> RuntimeSidecar<F>
where
    F: ProcessFactory,
{
    pub fn new(factory: F, emitter: Arc<dyn EventEmitter>) -> Self {
        Self {
            factory,
            emitter,
            running: std::sync::Mutex::new(None),
        }
    }

    pub fn send(&self, command: ValidatedCommand) -> Result<(), &'static str> {
        let bytes = serialize_command(&command)?;
        let mut running = self
            .running
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        let needs_restart = running
            .as_mut()
            .map(|child| child.process.has_exited().unwrap_or(true))
            .unwrap_or(true);

        if needs_restart {
            if let Some(previous) = running.take() {
                emit_remaining_request_errors(&self.emitter, &previous.active_request_ids);
            }
            *running = Some(self.start_process()?);
        }

        let child = running.as_mut().ok_or(RUNTIME_UNAVAILABLE_MESSAGE)?;
        if command.kind == crate::runtime_commands::CommandKind::Optimize {
            child
                .active_request_ids
                .lock()
                .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?
                .insert(command.request_id.clone());
        }
        let write_result = child
            .process
            .write_stdin(bytes.as_bytes())
            .and_then(|_| child.process.flush_stdin())
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE);
        if write_result.is_err() {
            emit_safe_error(&self.emitter, &command.request_id);
        }
        write_result
    }

    pub fn shutdown(&self) {
        let Ok(mut running) = self.running.lock() else {
            return;
        };
        let Some(mut child) = running.take() else {
            return;
        };
        child.stopping.store(true, Ordering::Release);
        let _ = child.process.write_stdin(
            b"{\"version\":1,\"request_id\":\"host-shutdown\",\"type\":\"shutdown\",\"payload\":{}}\n",
        );
        let _ = child.process.flush_stdin();
        child.process.close_stdin();
        if child
            .process
            .wait_for(Duration::from_millis(600))
            .unwrap_or(false)
        {
            return;
        }
        let _ = child.process.terminate();
        let _ = child.process.wait_for(Duration::from_millis(300));
    }

    fn start_process(&self) -> Result<RunningProcess, &'static str> {
        let mut process = self.factory.spawn()?;
        let active_request_ids = Arc::new(Mutex::new(HashSet::new()));
        let stopping = Arc::new(AtomicBool::new(false));

        if let Some(stdout) = process.take_stdout() {
            spawn_stdout_reader(
                stdout,
                self.emitter.clone(),
                active_request_ids.clone(),
                stopping.clone(),
            );
        }
        if let Some(stderr) = process.take_stderr() {
            spawn_stderr_drainer(stderr);
        }

        Ok(RunningProcess {
            process,
            active_request_ids,
            stopping,
        })
    }
}

impl<F> Drop for RuntimeSidecar<F>
where
    F: ProcessFactory,
{
    fn drop(&mut self) {
        self.shutdown();
    }
}

pub struct RuntimeController {
    emitter: Arc<dyn EventEmitter>,
    sidecar: Mutex<Option<RuntimeSidecar<OsProcessFactory>>>,
}

impl RuntimeController {
    pub fn new(emitter: Arc<dyn EventEmitter>) -> Self {
        Self {
            emitter,
            sidecar: Mutex::new(None),
        }
    }

    pub fn send(&self, command: ValidatedCommand) -> Result<(), &'static str> {
        let mut sidecar = self
            .sidecar
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        if sidecar.is_none() {
            let paths = resolve_runtime_paths()?;
            let launch = build_launch_spec(resolve_python_launcher()?, &paths)?;
            *sidecar = Some(RuntimeSidecar::new(
                OsProcessFactory::new(launch),
                self.emitter.clone(),
            ));
        }
        sidecar
            .as_ref()
            .ok_or(RUNTIME_UNAVAILABLE_MESSAGE)?
            .send(command)
    }

    pub fn shutdown(&self) {
        if let Ok(mut sidecar) = self.sidecar.lock() {
            if let Some(sidecar) = sidecar.take() {
                sidecar.shutdown();
            }
        }
    }
}

fn spawn_stdout_reader(
    stdout: Box<dyn Read + Send>,
    emitter: Arc<dyn EventEmitter>,
    active_request_ids: Arc<Mutex<HashSet<String>>>,
    stopping: Arc<AtomicBool>,
) {
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else {
                break;
            };
            if line.trim().is_empty() {
                continue;
            }
            let request_id = request_id_from_raw_event(&line);
            match parse_event_envelope(&line) {
                Ok(payload) => {
                    if event_is_terminal(&payload) {
                        remove_active_request(&active_request_ids, payload.get("request_id"));
                    }
                    emitter.emit(payload);
                }
                Err(_) => {
                    if let Some(request_id) = request_id {
                        remove_active_request(
                            &active_request_ids,
                            Some(&Value::String(request_id.clone())),
                        );
                        emit_safe_error(&emitter, &request_id);
                    } else {
                        emit_remaining_request_errors(&emitter, &active_request_ids);
                    }
                }
            }
        }
        if !stopping.load(Ordering::Acquire) {
            emit_remaining_request_errors(&emitter, &active_request_ids);
        }
    });
}

fn spawn_stderr_drainer(stderr: Box<dyn Read + Send>) {
    std::thread::spawn(move || {
        for line in BufReader::new(stderr).lines() {
            if line.is_err() {
                break;
            }
        }
    });
}

fn request_id_from_raw_event(raw: &str) -> Option<String> {
    serde_json::from_str::<Value>(raw)
        .ok()?
        .get("request_id")?
        .as_str()
        .filter(|request_id| !request_id.trim().is_empty())
        .map(str::to_string)
}

fn event_is_terminal(payload: &Value) -> bool {
    let Some(event) = payload.get("event") else {
        return false;
    };
    matches!(
        event.get("type").and_then(Value::as_str),
        Some("done" | "error")
    ) || (event.get("type").and_then(Value::as_str) == Some("status")
        && matches!(
            event
                .get("data")
                .and_then(|data| data.get("phase"))
                .and_then(Value::as_str),
            Some("completed" | "cancelled" | "error")
        ))
}

fn remove_active_request(active_request_ids: &Arc<Mutex<HashSet<String>>>, value: Option<&Value>) {
    let Some(request_id) = value.and_then(Value::as_str) else {
        return;
    };
    if let Ok(mut request_ids) = active_request_ids.lock() {
        request_ids.remove(request_id);
    }
}

fn emit_remaining_request_errors(
    emitter: &Arc<dyn EventEmitter>,
    active_request_ids: &Arc<Mutex<HashSet<String>>>,
) {
    let request_ids = active_request_ids
        .lock()
        .map(|mut request_ids| request_ids.drain().collect::<Vec<_>>())
        .unwrap_or_default();
    for request_id in request_ids {
        emit_safe_error(emitter, &request_id);
    }
}

fn emit_safe_error(emitter: &Arc<dyn EventEmitter>, request_id: &str) {
    emitter.emit(serde_json::json!({
        "version": 1,
        "request_id": request_id,
        "event": {
            "type": "error",
            "data": {
                "code": "runtime_unavailable",
                "message": RUNTIME_UNAVAILABLE_MESSAGE,
                "recoverable": true,
                "action": "retry"
            }
        }
    }));
}

pub fn resolve_runtime_paths_from(
    root_override: Option<&Path>,
    manifest_dir: &Path,
) -> Result<RuntimePaths, &'static str> {
    let root = match root_override {
        Some(path) => path.to_path_buf(),
        None => manifest_dir
            .parent()
            .and_then(Path::parent)
            .and_then(Path::parent)
            .map(Path::to_path_buf)
            .ok_or(RUNTIME_UNAVAILABLE_MESSAGE)?,
    };
    let runtime_dir = root.join("packages").join("reflex-runtime");
    let runtime_src = runtime_dir.join("src");
    let core_src = root.join("packages").join("reflex-core").join("src");

    if runtime_dir.is_dir()
        && runtime_src.join("reflex_runtime").join("cli.py").is_file()
        && core_src.join("reflex_core").is_dir()
    {
        Ok(RuntimePaths {
            root,
            runtime_dir,
            runtime_src,
            core_src,
        })
    } else {
        Err(RUNTIME_UNAVAILABLE_MESSAGE)
    }
}

pub fn resolve_runtime_paths() -> Result<RuntimePaths, &'static str> {
    let root_override = std::env::var_os("REFLEX_RUNTIME_ROOT").map(PathBuf::from);
    resolve_runtime_paths_from(
        root_override.as_deref(),
        Path::new(env!("CARGO_MANIFEST_DIR")),
    )
}

pub fn resolve_python_launcher() -> Result<PythonLauncher, &'static str> {
    match std::env::var_os("REFLEX_RUNTIME_PYTHON") {
        Some(path) if !path.is_empty() => Ok(PythonLauncher::Override(PathBuf::from(path))),
        Some(_) => Err(RUNTIME_UNAVAILABLE_MESSAGE),
        None => Ok(PythonLauncher::UvManaged312),
    }
}

pub fn build_launch_spec(
    launcher: PythonLauncher,
    paths: &RuntimePaths,
) -> Result<LaunchSpec, &'static str> {
    let (program, arguments) = match launcher {
        PythonLauncher::Override(path) => (
            path,
            vec!["-m".to_string(), "reflex_runtime.cli".to_string()],
        ),
        PythonLauncher::UvManaged312 => (
            PathBuf::from("uv"),
            vec![
                "run".to_string(),
                "--python".to_string(),
                "3.12".to_string(),
                "--no-python-downloads".to_string(),
                "--offline".to_string(),
                "python".to_string(),
                "-m".to_string(),
                "reflex_runtime.cli".to_string(),
            ],
        ),
    };

    Ok(LaunchSpec {
        program,
        arguments,
        current_dir: paths.runtime_dir.clone(),
        python_path: vec![paths.runtime_src.clone(), paths.core_src.clone()],
    })
}

#[derive(Serialize)]
struct WireCommand<'a> {
    version: u8,
    request_id: &'a str,
    #[serde(rename = "type")]
    kind: &'a str,
    payload: &'a Value,
}

pub fn serialize_command(command: &ValidatedCommand) -> Result<String, &'static str> {
    let serialized = serde_json::to_string(&WireCommand {
        version: 1,
        request_id: &command.request_id,
        kind: command.kind.as_str(),
        payload: &command.payload,
    })
    .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;

    Ok(format!("{serialized}\n"))
}

pub fn parse_event_envelope(raw: &str) -> Result<Value, &'static str> {
    let value: Value = serde_json::from_str(raw).map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
    let Value::Object(object) = &value else {
        return Err(RUNTIME_UNAVAILABLE_MESSAGE);
    };
    let valid_version = object.get("version").and_then(Value::as_u64) == Some(1);
    let valid_request_id = object
        .get("request_id")
        .and_then(Value::as_str)
        .is_some_and(|request_id| !request_id.trim().is_empty());
    let valid_event = object
        .get("event")
        .and_then(Value::as_object)
        .is_some_and(|event| {
            matches!(
                event.get("type").and_then(Value::as_str),
                Some("status" | "scene" | "request" | "chunk" | "done" | "error" | "metric")
            ) && event.get("data").is_some_and(Value::is_object)
        });

    if valid_version && valid_request_id && valid_event {
        Ok(value)
    } else {
        Err(RUNTIME_UNAVAILABLE_MESSAGE)
    }
}

#[cfg(test)]
mod tests {
    use std::collections::{HashSet, VecDeque};
    use std::io::{self, Cursor, Read};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::{Arc, Mutex};

    use serde_json::json;

    use crate::runtime_commands::{CommandKind, ValidatedCommand};

    use super::{
        build_launch_spec, parse_event_envelope, resolve_runtime_paths_from, serialize_command,
        spawn_stdout_reader, ChildProcess, EventEmitter, OsProcessFactory, ProcessFactory,
        PythonLauncher, RuntimeSidecar, RUNTIME_UNAVAILABLE_MESSAGE,
    };

    #[test]
    fn serializes_one_utf8_ndjson_command_with_exactly_one_trailing_newline() {
        let command = ValidatedCommand {
            request_id: "请求-1".to_string(),
            kind: CommandKind::Optimize,
            payload: json!({ "text": "保留 UTF-8 内容" }),
        };

        assert_eq!(
            serialize_command(&command).unwrap(),
            "{\"version\":1,\"request_id\":\"请求-1\",\"type\":\"optimize\",\"payload\":{\"text\":\"保留 UTF-8 内容\"}}\n"
        );
    }

    #[test]
    fn accepts_valid_event_envelopes_without_changing_their_payload() {
        let raw = "{\"version\":1,\"request_id\":\"req-1\",\"event\":{\"type\":\"chunk\",\"data\":{\"text\":\"片段\"}}}";

        assert_eq!(
            parse_event_envelope(raw).unwrap(),
            json!({
                "version": 1,
                "request_id": "req-1",
                "event": { "type": "chunk", "data": { "text": "片段" } }
            })
        );
    }

    #[test]
    fn rejects_unknown_event_types_and_non_object_event_data() {
        let invalid_events = [
            r#"{"version":1,"request_id":"req-1","event":{"type":"debug","data":{}}}"#,
            r#"{"version":1,"request_id":"req-1","event":{"type":"chunk","data":"raw"}}"#,
        ];

        for raw in invalid_events {
            assert_eq!(parse_event_envelope(raw), Err(RUNTIME_UNAVAILABLE_MESSAGE));
        }
    }

    #[test]
    fn turns_invalid_stdout_into_a_fixed_safe_error_without_raw_content() {
        let error = parse_event_envelope("Traceback: token=secret-value").unwrap_err();

        assert_eq!(error, RUNTIME_UNAVAILABLE_MESSAGE);
        assert!(!error.contains("secret-value"));
    }

    #[test]
    fn fails_all_active_requests_when_invalid_stdout_has_no_request_id() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let active_request_ids = Arc::new(Mutex::new(HashSet::from(["req-active".to_string()])));
        let release = Arc::new(AtomicBool::new(false));

        spawn_stdout_reader(
            Box::new(HoldOpenReader {
                bytes: Cursor::new(b"Traceback: token=secret-value\n".to_vec()),
                release: release.clone(),
            }),
            Arc::new(RecordingEmitter(events.clone())),
            active_request_ids.clone(),
            Arc::new(AtomicBool::new(false)),
        );

        std::thread::sleep(std::time::Duration::from_millis(80));
        let events_before_eof = events.lock().unwrap().clone();
        let active_requests_cleared_before_eof = active_request_ids.lock().unwrap().is_empty();
        release.store(true, Ordering::Release);

        assert!(events_before_eof.iter().any(|payload| {
            payload["request_id"] == "req-active"
                && payload["event"]["data"]["code"] == "runtime_unavailable"
        }));
        assert!(active_requests_cleared_before_eof);
        assert!(!serde_json::to_string(&events_before_eof)
            .unwrap()
            .contains("secret-value"));
    }

    #[test]
    fn builds_the_offline_uv_python_312_development_launch_contract() {
        let manifest_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let paths = resolve_runtime_paths_from(None, manifest_dir).unwrap();

        let launch = build_launch_spec(PythonLauncher::UvManaged312, &paths).unwrap();

        assert_eq!(launch.program, std::path::Path::new("uv"));
        assert_eq!(
            launch.arguments,
            vec![
                "run",
                "--python",
                "3.12",
                "--no-python-downloads",
                "--offline",
                "python",
                "-m",
                "reflex_runtime.cli",
            ]
        );
        assert_eq!(launch.current_dir, paths.runtime_dir);
        assert_eq!(launch.python_path, vec![paths.runtime_src, paths.core_src]);
    }

    #[test]
    fn keeps_an_explicit_python_override_as_one_executable_path() {
        let manifest_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let paths = resolve_runtime_paths_from(None, manifest_dir).unwrap();
        let executable = std::path::PathBuf::from(r"C:\工具\Python 3.12\python.exe");

        let launch =
            build_launch_spec(PythonLauncher::Override(executable.clone()), &paths).unwrap();

        assert_eq!(launch.program, executable);
        assert_eq!(launch.arguments, vec!["-m", "reflex_runtime.cli"]);
    }

    #[test]
    fn restarts_after_an_owned_child_has_exited_before_the_next_write() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let factory = FakeProcessFactory::new(vec![
            FakeProcess::exits_after_write(writes.clone()),
            FakeProcess::running(writes.clone()),
        ]);
        let sidecar = RuntimeSidecar::new(factory.clone(), Arc::new(FakeEmitter));

        sidecar
            .send(ValidatedCommand {
                request_id: "req-1".to_string(),
                kind: CommandKind::Optimize,
                payload: json!({ "text": "first" }),
            })
            .unwrap();
        sidecar
            .send(ValidatedCommand {
                request_id: "req-2".to_string(),
                kind: CommandKind::Optimize,
                payload: json!({ "text": "second" }),
            })
            .unwrap();

        assert_eq!(factory.launch_count(), 2);
        assert_eq!(
            *writes.lock().unwrap(),
            vec![
                b"{\"version\":1,\"request_id\":\"req-1\",\"type\":\"optimize\",\"payload\":{\"text\":\"first\"}}\n".to_vec(),
                b"{\"version\":1,\"request_id\":\"req-2\",\"type\":\"optimize\",\"payload\":{\"text\":\"second\"}}\n".to_vec(),
            ]
        );
    }

    #[test]
    fn sends_commands_serially_then_requests_shutdown_only_for_its_owned_child() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let factory = FakeProcessFactory::new(vec![FakeProcess::running(writes.clone())]);
        let sidecar = RuntimeSidecar::new(factory, Arc::new(FakeEmitter));
        let command = ValidatedCommand {
            request_id: "req-1".to_string(),
            kind: CommandKind::Optimize,
            payload: json!({ "text": "测试" }),
        };

        sidecar.send(command).unwrap();
        sidecar.shutdown();

        assert_eq!(
            *writes.lock().unwrap(),
            vec![
                "{\"version\":1,\"request_id\":\"req-1\",\"type\":\"optimize\",\"payload\":{\"text\":\"测试\"}}\n".as_bytes().to_vec(),
                b"{\"version\":1,\"request_id\":\"host-shutdown\",\"type\":\"shutdown\",\"payload\":{}}\n".to_vec(),
            ]
        );
    }

    #[test]
    fn mock_runtime_streams_then_cancels_without_done_and_shuts_down_cleanly() {
        let manifest_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let paths = resolve_runtime_paths_from(None, manifest_dir).unwrap();
        let launcher = std::env::var_os("REFLEX_RUNTIME_TEST_PYTHON")
            .map(|python| PythonLauncher::Override(python.into()))
            .unwrap_or(PythonLauncher::UvManaged312);
        let launch = build_launch_spec(launcher, &paths).unwrap();
        let events = Arc::new(Mutex::new(Vec::new()));
        let sidecar = RuntimeSidecar::new(
            OsProcessFactory::new(launch),
            Arc::new(RecordingEmitter(events.clone())),
        );

        sidecar
            .send(ValidatedCommand {
                request_id: "req-cancel".to_string(),
                kind: CommandKind::Optimize,
                payload: json!({
                    "text": "写一封邮件",
                    "style": "concise",
                    "metadata": { "delay_ms": 80, "chunks": ["first", "late"] }
                }),
            })
            .unwrap();
        wait_for_event(&events, |payload| {
            payload["request_id"] == "req-cancel" && payload["event"]["type"] == "chunk"
        });

        sidecar
            .send(ValidatedCommand {
                request_id: "req-cancel".to_string(),
                kind: CommandKind::Cancel,
                payload: json!({}),
            })
            .unwrap();
        wait_for_event(&events, |payload| {
            payload["request_id"] == "req-cancel"
                && payload["event"]["type"] == "status"
                && payload["event"]["data"]["phase"] == "cancelled"
        });

        assert!(events
            .lock()
            .unwrap()
            .iter()
            .filter(|payload| payload["request_id"] == "req-cancel")
            .all(|payload| payload["event"]["type"] != "done"));

        sidecar.shutdown();
        assert!(sidecar.running.lock().unwrap().is_none());
    }

    #[derive(Clone)]
    struct FakeProcessFactory {
        processes: Arc<Mutex<VecDeque<FakeProcess>>>,
        launches: Arc<Mutex<usize>>,
    }

    impl FakeProcessFactory {
        fn new(processes: Vec<FakeProcess>) -> Self {
            Self {
                processes: Arc::new(Mutex::new(processes.into())),
                launches: Arc::new(Mutex::new(0)),
            }
        }

        fn launch_count(&self) -> usize {
            *self.launches.lock().unwrap()
        }
    }

    impl ProcessFactory for FakeProcessFactory {
        fn spawn(&self) -> Result<Box<dyn ChildProcess>, &'static str> {
            *self.launches.lock().unwrap() += 1;
            let process = self.processes.lock().unwrap().pop_front().unwrap();
            Ok(Box::new(process))
        }
    }

    struct FakeProcess {
        exited: bool,
        exits_after_write: bool,
        writes: Arc<Mutex<Vec<Vec<u8>>>>,
    }

    struct HoldOpenReader {
        bytes: Cursor<Vec<u8>>,
        release: Arc<AtomicBool>,
    }

    impl Read for HoldOpenReader {
        fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
            if self.bytes.position() < self.bytes.get_ref().len() as u64 {
                return self.bytes.read(buffer);
            }
            while !self.release.load(Ordering::Acquire) {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            Ok(0)
        }
    }

    impl FakeProcess {
        fn exits_after_write(writes: Arc<Mutex<Vec<Vec<u8>>>>) -> Self {
            Self {
                exited: false,
                exits_after_write: true,
                writes,
            }
        }

        fn running(writes: Arc<Mutex<Vec<Vec<u8>>>>) -> Self {
            Self {
                exited: false,
                exits_after_write: false,
                writes,
            }
        }
    }

    impl ChildProcess for FakeProcess {
        fn has_exited(&mut self) -> io::Result<bool> {
            Ok(self.exited)
        }

        fn write_stdin(&mut self, bytes: &[u8]) -> io::Result<()> {
            self.writes.lock().unwrap().push(bytes.to_vec());
            self.exited = self.exits_after_write;
            Ok(())
        }

        fn flush_stdin(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    struct FakeEmitter;

    impl EventEmitter for FakeEmitter {
        fn emit(&self, _payload: serde_json::Value) {}
    }

    struct RecordingEmitter(Arc<Mutex<Vec<serde_json::Value>>>);

    impl EventEmitter for RecordingEmitter {
        fn emit(&self, payload: serde_json::Value) {
            self.0.lock().unwrap().push(payload);
        }
    }

    fn wait_for_event(
        events: &Arc<Mutex<Vec<serde_json::Value>>>,
        predicate: impl Fn(&serde_json::Value) -> bool,
    ) {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(4);
        while std::time::Instant::now() < deadline {
            if events.lock().unwrap().iter().any(&predicate) {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        panic!("timed out waiting for Runtime event");
    }
}
