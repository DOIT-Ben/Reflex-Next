use std::collections::{HashMap, HashSet, VecDeque};
use std::fmt;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::Value;

use crate::runtime_commands::ValidatedCommand;

pub const RUNTIME_UNAVAILABLE_MESSAGE: &str = "运行服务暂不可用，请稍后重试。";
pub const DUPLICATE_REQUEST_MESSAGE: &str = "运行请求重复。";
pub const REQUEST_NOT_FOUND_MESSAGE: &str = "目标请求不存在。";
pub const REQUEST_SESSION_FULL_MESSAGE: &str = "运行会话已满，请重启应用。";
const MAX_SEEN_REQUEST_IDS: usize = 100_000;
const PRIVATE_CONFIGURATION_TIMEOUT: Duration = Duration::from_secs(2);
pub const CORE_EVENT_NAME: &str = "reflex://core-event";
pub const PLUGIN_EVENT_NAME: &str = "reflex://plugin-event";
pub const CAPABILITY_LIST_EVENT_NAME: &str = "reflex://capability-list";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimePaths {
    pub root: PathBuf,
    pub runtime_dir: PathBuf,
    pub runtime_src: PathBuf,
    pub core_src: PathBuf,
    pub provider_plugin_src: PathBuf,
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
    pub runtime_development: bool,
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
        let child = build_process_command(&self.launch)?
            .spawn()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        Ok(Box::new(OsChildProcess::new(child)))
    }
}

fn build_process_command(launch: &LaunchSpec) -> Result<Command, &'static str> {
    let python_path =
        std::env::join_paths(&launch.python_path).map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
    let mut command = Command::new(&launch.program);
    command
        .args(&launch.arguments)
        .current_dir(&launch.current_dir)
        .env("PYTHONPATH", python_path)
        .env("PYTHONUTF8", "1");
    if launch.runtime_development {
        command.env("REFLEX_RUNTIME_DEVELOPMENT", "1");
    } else {
        command.env_remove("REFLEX_RUNTIME_DEVELOPMENT");
    }
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    Ok(command)
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
    fn emit(&self, event_name: &str, payload: Value);

    fn emit_to(&self, _target: &str, event_name: &str, payload: Value) {
        self.emit(event_name, payload);
    }
}

struct HostRequestRegistry {
    history: Mutex<RequestHistory>,
    internal_sequence: AtomicU64,
    max_seen_request_ids: usize,
}

#[derive(Default)]
struct RequestHistory {
    ids: HashSet<String>,
    order: VecDeque<String>,
}

impl Default for HostRequestRegistry {
    fn default() -> Self {
        Self {
            history: Mutex::new(RequestHistory::default()),
            internal_sequence: AtomicU64::new(0),
            max_seen_request_ids: MAX_SEEN_REQUEST_IDS,
        }
    }
}

impl HostRequestRegistry {
    #[cfg(test)]
    fn with_limit(max_seen_request_ids: usize) -> Self {
        Self {
            max_seen_request_ids,
            ..Self::default()
        }
    }

    fn claim(&self, request_id: &str) -> Result<(), &'static str> {
        self.claim_many(std::iter::once(request_id))
    }

    fn claim_many<'a>(
        &self,
        request_ids: impl IntoIterator<Item = &'a str>,
    ) -> Result<(), &'static str> {
        let request_ids = request_ids.into_iter().collect::<Vec<_>>();
        if request_ids
            .iter()
            .any(|request_id| !crate::runtime_commands::is_safe_request_id(request_id))
        {
            return Err(crate::runtime_commands::COMMAND_INVALID_MESSAGE);
        }
        let mut batch_ids = HashSet::new();
        let unique = request_ids
            .iter()
            .map(|request_id| (*request_id).to_string())
            .collect::<Vec<_>>();
        if unique
            .iter()
            .any(|request_id| !batch_ids.insert(request_id.clone()))
        {
            return Err(DUPLICATE_REQUEST_MESSAGE);
        }
        if unique.len() > self.max_seen_request_ids {
            return Err(REQUEST_SESSION_FULL_MESSAGE);
        }

        let mut history = self
            .history
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        if unique
            .iter()
            .any(|request_id| history.ids.contains(request_id))
        {
            return Err(DUPLICATE_REQUEST_MESSAGE);
        }
        while history.ids.len() + unique.len() > self.max_seen_request_ids {
            let Some(expired) = history.order.pop_front() else {
                return Err(RUNTIME_UNAVAILABLE_MESSAGE);
            };
            history.ids.remove(&expired);
        }
        for request_id in unique {
            history.ids.insert(request_id.clone());
            history.order.push_back(request_id);
        }
        Ok(())
    }

    fn claim_internal(&self, prefix: &str) -> Result<String, &'static str> {
        loop {
            let sequence = self
                .internal_sequence
                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                    value.checked_add(1)
                })
                .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?
                + 1;
            let request_id = format!("{prefix}-{sequence}");
            match self.claim(&request_id) {
                Ok(()) => return Ok(request_id),
                Err(DUPLICATE_REQUEST_MESSAGE) => continue,
                Err(error) => return Err(error),
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ResponseContract {
    Core,
    CapabilityList,
    Plugin {
        plugin_id: String,
        operation: String,
    },
}

impl ResponseContract {
    fn for_command(command: &ValidatedCommand) -> Option<Self> {
        use crate::runtime_commands::CommandKind;

        match command.kind {
            CommandKind::Cancel => None,
            CommandKind::ListPlugins => Some(Self::CapabilityList),
            CommandKind::PluginCall | CommandKind::PluginAdminCall => Some(Self::Plugin {
                plugin_id: command.payload["plugin_id"].as_str()?.to_string(),
                operation: command.payload["operation"].as_str()?.to_string(),
            }),
            CommandKind::Optimize
            | CommandKind::Ping
            | CommandKind::Shutdown
            | CommandKind::ConfigureProvider
            | CommandKind::ConfigurePlugin
            | CommandKind::ConfigureHistoryKeys
            | CommandKind::ConfigureHistoryPolicy
            | CommandKind::ConfigureHistoryPath => Some(Self::Core),
        }
    }

    fn event_name(&self) -> &'static str {
        match self {
            Self::Core => CORE_EVENT_NAME,
            Self::CapabilityList => CAPABILITY_LIST_EVENT_NAME,
            Self::Plugin { .. } => PLUGIN_EVENT_NAME,
        }
    }

    fn matches(&self, parsed: &ParsedSidecarEvent) -> bool {
        if self.event_name() != parsed.event_name {
            return false;
        }
        match self {
            Self::Plugin {
                plugin_id,
                operation,
            } => {
                parsed.payload["plugin_id"].as_str() == Some(plugin_id)
                    && parsed.payload["operation"].as_str() == Some(operation)
            }
            _ => true,
        }
    }
}

#[derive(Clone)]
enum RequestRoute {
    #[cfg(test)]
    Public,
    PublicTo(String),
    Private(mpsc::Sender<Value>),
}

impl RequestRoute {
    fn public_target(&self) -> Option<&str> {
        match self {
            #[cfg(test)]
            Self::Public => Some("main"),
            Self::PublicTo(target) => Some(target),
            Self::Private(_) => None,
        }
    }

    fn owned_by_same_public_window(&self, other: &Self) -> bool {
        self.public_target().is_some() && self.public_target() == other.public_target()
    }
}

struct ActiveRequest {
    contract: ResponseContract,
    route: RequestRoute,
    lifecycle: Mutex<RequestLifecycle>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum RequestLifecycle {
    Active,
    Terminal,
}

impl ActiveRequest {
    fn new(contract: ResponseContract, route: RequestRoute) -> Self {
        Self {
            contract,
            route,
            lifecycle: Mutex::new(RequestLifecycle::Active),
        }
    }

    fn dispatch(&self, emitter: &Arc<dyn EventEmitter>, payload: Value, terminal: bool) -> bool {
        let Ok(mut lifecycle) = self.lifecycle.lock() else {
            return false;
        };
        if *lifecycle == RequestLifecycle::Terminal {
            return false;
        }
        if terminal {
            *lifecycle = RequestLifecycle::Terminal;
        }
        match &self.route {
            #[cfg(test)]
            RequestRoute::Public => emitter.emit_to("main", self.contract.event_name(), payload),
            RequestRoute::PublicTo(target) => {
                emitter.emit_to(target, self.contract.event_name(), payload)
            }
            RequestRoute::Private(sender) => {
                let _ = sender.send(payload);
            }
        }
        true
    }

    fn cancel_without_dispatch(&self) -> bool {
        let Ok(mut lifecycle) = self.lifecycle.lock() else {
            return false;
        };
        if *lifecycle == RequestLifecycle::Terminal {
            return false;
        }
        *lifecycle = RequestLifecycle::Terminal;
        true
    }
}

type ActiveRequests = Arc<Mutex<HashMap<String, Arc<ActiveRequest>>>>;

#[derive(Clone)]
pub(crate) struct PrivateRuntimeGeneration(ActiveRequests);

#[allow(dead_code)]
pub struct PrivateEventStream {
    request_id: String,
    receiver: mpsc::Receiver<Value>,
    active_requests: ActiveRequests,
    running: Arc<Mutex<Option<RunningProcess>>>,
    emitter: Arc<dyn EventEmitter>,
}

#[allow(dead_code)]
impl PrivateEventStream {
    pub(crate) fn generation(&self) -> PrivateRuntimeGeneration {
        PrivateRuntimeGeneration(self.active_requests.clone())
    }

    pub fn recv_timeout(&mut self, timeout: Duration) -> Result<Value, &'static str> {
        match self.receiver.recv_timeout(timeout) {
            Ok(payload) => Ok(payload),
            Err(_) => {
                self.cleanup();
                Err(RUNTIME_UNAVAILABLE_MESSAGE)
            }
        }
    }

    pub fn poll_timeout(&mut self, timeout: Duration) -> Result<Option<Value>, &'static str> {
        match self.receiver.recv_timeout(timeout) {
            Ok(payload) => Ok(Some(payload)),
            Err(mpsc::RecvTimeoutError::Timeout) => Ok(None),
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                self.cleanup();
                Err(RUNTIME_UNAVAILABLE_MESSAGE)
            }
        }
    }

    pub fn cancel(&mut self) {
        self.cleanup();
    }

    fn cleanup(&mut self) {
        let request = self
            .active_requests
            .lock()
            .ok()
            .and_then(|active| active.get(&self.request_id).cloned());
        let Some(request) = request else {
            return;
        };
        if request.cancel_without_dispatch() {
            remove_active_request(&self.active_requests, &self.request_id, &request);
            send_private_cancel(
                &self.running,
                &self.active_requests,
                &self.emitter,
                &self.request_id,
            );
        }
    }
}

impl Drop for PrivateEventStream {
    fn drop(&mut self) {
        self.cleanup();
    }
}

struct RunningProcess {
    process: Box<dyn ChildProcess>,
    active_requests: ActiveRequests,
    stopping: Arc<AtomicBool>,
    unhealthy: Arc<AtomicBool>,
}

pub struct RuntimeSidecar<F>
where
    F: ProcessFactory,
{
    factory: F,
    emitter: Arc<dyn EventEmitter>,
    request_registry: Arc<HostRequestRegistry>,
    running: Arc<Mutex<Option<RunningProcess>>>,
    sequence: Mutex<()>,
}

impl<F> RuntimeSidecar<F>
where
    F: ProcessFactory,
{
    #[cfg(test)]
    pub fn new(factory: F, emitter: Arc<dyn EventEmitter>) -> Self {
        Self::new_with_registry(factory, emitter, Arc::new(HostRequestRegistry::default()))
    }

    fn new_with_registry(
        factory: F,
        emitter: Arc<dyn EventEmitter>,
        request_registry: Arc<HostRequestRegistry>,
    ) -> Self {
        Self {
            factory,
            emitter,
            request_registry,
            running: Arc::new(Mutex::new(None)),
            sequence: Mutex::new(()),
        }
    }

    #[cfg(test)]
    pub fn send(&self, command: ValidatedCommand) -> Result<(), &'static str> {
        self.send_to(command, "main")
    }

    pub fn send_to(&self, command: ValidatedCommand, target: &str) -> Result<(), &'static str> {
        if is_private_command(command.kind) {
            return Err(RUNTIME_UNAVAILABLE_MESSAGE);
        }
        self.send_routed(vec![(command, public_route(target)?)])
    }

    #[allow(dead_code)]
    pub fn send_sequence(&self, commands: Vec<ValidatedCommand>) -> Result<(), &'static str> {
        self.send_sequence_to(commands, "main")
    }

    pub fn send_sequence_to(
        &self,
        commands: Vec<ValidatedCommand>,
        target: &str,
    ) -> Result<(), &'static str> {
        let public_route = public_route(target)?;
        let _sequence = self
            .sequence
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        let mut generation = None;
        for command in commands {
            if let Some(expected_message) = expected_private_status(command.kind) {
                let (mut stream, active_requests) =
                    self.send_private_for_generation(command, generation.as_ref())?;
                if generation.is_none() {
                    generation = Some(active_requests);
                }
                let payload = stream.recv_timeout(PRIVATE_CONFIGURATION_TIMEOUT)?;
                if !is_expected_private_success(&payload, expected_message) {
                    return Err(RUNTIME_UNAVAILABLE_MESSAGE);
                }
            } else if is_private_command(command.kind) {
                self.send_detached_private(command, generation.as_ref())?;
            } else if let Some(expected) = generation.as_ref() {
                self.send_routed_with_generation(
                    vec![(command, public_route.clone())],
                    Some(expected),
                )?;
            } else {
                self.send_routed(vec![(command, public_route.clone())])?;
            }
        }
        Ok(())
    }

    #[allow(dead_code)]
    pub fn send_private(
        &self,
        command: ValidatedCommand,
    ) -> Result<PrivateEventStream, &'static str> {
        self.send_private_for_generation(command, None)
            .map(|(stream, _)| stream)
    }

    pub fn send_private_sequence(
        &self,
        commands: Vec<ValidatedCommand>,
    ) -> Result<PrivateEventStream, &'static str> {
        self.send_private_sequence_for_generation(commands, None)
    }

    fn send_private_sequence_for_generation(
        &self,
        commands: Vec<ValidatedCommand>,
        expected_generation: Option<&ActiveRequests>,
    ) -> Result<PrivateEventStream, &'static str> {
        let _sequence = self
            .sequence
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        let command_count = commands.len();
        let mut generation = expected_generation.cloned();
        for (index, command) in commands.into_iter().enumerate() {
            if matches!(
                command.kind,
                crate::runtime_commands::CommandKind::PluginAdminCall
                    | crate::runtime_commands::CommandKind::PluginCall
            ) {
                if index + 1 != command_count {
                    return Err(RUNTIME_UNAVAILABLE_MESSAGE);
                }
                return self
                    .send_private_routed(command, generation.as_ref())
                    .map(|(stream, _)| stream);
            }
            if let Some(expected_message) = expected_private_status(command.kind) {
                let (mut stream, active_requests) =
                    self.send_private_for_generation(command, generation.as_ref())?;
                if generation.is_none() {
                    generation = Some(active_requests);
                }
                let payload = stream.recv_timeout(PRIVATE_CONFIGURATION_TIMEOUT)?;
                if !is_expected_private_success(&payload, expected_message) {
                    return Err(RUNTIME_UNAVAILABLE_MESSAGE);
                }
            } else if is_private_command(command.kind) {
                self.send_detached_private(command, generation.as_ref())?;
            } else {
                return Err(RUNTIME_UNAVAILABLE_MESSAGE);
            }
        }
        Err(RUNTIME_UNAVAILABLE_MESSAGE)
    }

    fn send_private_for_generation(
        &self,
        command: ValidatedCommand,
        expected_generation: Option<&ActiveRequests>,
    ) -> Result<(PrivateEventStream, ActiveRequests), &'static str> {
        if !is_private_command(command.kind)
            || command.kind == crate::runtime_commands::CommandKind::Cancel
        {
            return Err(RUNTIME_UNAVAILABLE_MESSAGE);
        }
        self.send_private_routed(command, expected_generation)
    }

    fn send_private_routed(
        &self,
        command: ValidatedCommand,
        expected_generation: Option<&ActiveRequests>,
    ) -> Result<(PrivateEventStream, ActiveRequests), &'static str> {
        let request_id = command.request_id.clone();
        let (sender, receiver) = mpsc::channel();
        let active_requests = self.send_routed_with_generation(
            vec![(command, RequestRoute::Private(sender))],
            expected_generation,
        )?;
        Ok((
            PrivateEventStream {
                request_id,
                receiver,
                active_requests: active_requests.clone(),
                running: self.running.clone(),
                emitter: self.emitter.clone(),
            },
            active_requests,
        ))
    }

    fn send_detached_private(
        &self,
        command: ValidatedCommand,
        expected_generation: Option<&ActiveRequests>,
    ) -> Result<(), &'static str> {
        if !is_private_command(command.kind)
            || command.kind == crate::runtime_commands::CommandKind::Cancel
        {
            return Err(RUNTIME_UNAVAILABLE_MESSAGE);
        }
        let (sender, _receiver) = mpsc::channel();
        self.send_routed_with_generation(
            vec![(command, RequestRoute::Private(sender))],
            expected_generation,
        )
        .map(|_| ())
    }

    fn send_routed(
        &self,
        commands: Vec<(ValidatedCommand, RequestRoute)>,
    ) -> Result<(), &'static str> {
        self.send_routed_with_generation(commands, None).map(|_| ())
    }

    fn send_routed_with_generation(
        &self,
        commands: Vec<(ValidatedCommand, RequestRoute)>,
        expected_generation: Option<&ActiveRequests>,
    ) -> Result<ActiveRequests, &'static str> {
        if commands.is_empty() {
            return Err(RUNTIME_UNAVAILABLE_MESSAGE);
        }
        let serialized = commands
            .iter()
            .map(|(command, _)| serialize_command(command))
            .collect::<Result<Vec<_>, _>>()?;
        let mut running = self
            .running
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        if commands
            .iter()
            .any(|(command, _)| command.kind == crate::runtime_commands::CommandKind::Cancel)
        {
            let Some(existing) = running.as_ref() else {
                return Err(REQUEST_NOT_FOUND_MESSAGE);
            };
            let active_requests = existing
                .active_requests
                .lock()
                .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
            for (command, route) in &commands {
                if command.kind == crate::runtime_commands::CommandKind::Cancel
                    && !active_requests
                        .get(&command.request_id)
                        .is_some_and(|active| active.route.owned_by_same_public_window(route))
                {
                    return Err(REQUEST_NOT_FOUND_MESSAGE);
                }
            }
        }
        let allow_restart = expected_generation.is_none();
        if let Some(expected_generation) = expected_generation {
            let Some(child) = running.as_mut() else {
                return Err(RUNTIME_UNAVAILABLE_MESSAGE);
            };
            if !Arc::ptr_eq(&child.active_requests, expected_generation)
                || child.unhealthy.load(Ordering::Acquire)
                || child.process.has_exited().unwrap_or(true)
            {
                return Err(RUNTIME_UNAVAILABLE_MESSAGE);
            }
        }
        if let Some(child) = running.as_ref() {
            let active_requests = child
                .active_requests
                .lock()
                .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
            if commands.iter().any(|(command, _)| {
                command.kind != crate::runtime_commands::CommandKind::Cancel
                    && active_requests.contains_key(&command.request_id)
            }) {
                return Err(DUPLICATE_REQUEST_MESSAGE);
            }
        }
        self.request_registry
            .claim_many(commands.iter().filter_map(|(command, _)| {
                (command.kind != crate::runtime_commands::CommandKind::Cancel)
                    .then_some(command.request_id.as_str())
            }))?;
        let needs_restart = running
            .as_mut()
            .map(|child| {
                child.unhealthy.load(Ordering::Acquire)
                    || child.process.has_exited().unwrap_or(true)
            })
            .unwrap_or(true);
        if needs_restart {
            if !allow_restart {
                return Err(RUNTIME_UNAVAILABLE_MESSAGE);
            }
            if let Some(mut previous) = running.take() {
                previous.stopping.store(true, Ordering::Release);
                fail_all_requests(&self.emitter, &previous.active_requests);
                let _ = previous.process.terminate();
            }
            *running = Some(self.start_process()?);
        }

        let child = running.as_mut().ok_or(RUNTIME_UNAVAILABLE_MESSAGE)?;
        {
            let active_requests = child
                .active_requests
                .lock()
                .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
            for (command, route) in &commands {
                if command.kind == crate::runtime_commands::CommandKind::Cancel {
                    if !active_requests
                        .get(&command.request_id)
                        .is_some_and(|active| active.route.owned_by_same_public_window(route))
                    {
                        return Err(REQUEST_NOT_FOUND_MESSAGE);
                    }
                }
            }
        }

        {
            let mut active_requests = child
                .active_requests
                .lock()
                .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
            for (command, route) in &commands {
                if let Some(contract) = ResponseContract::for_command(command) {
                    active_requests.insert(
                        command.request_id.clone(),
                        Arc::new(ActiveRequest::new(contract, route.clone())),
                    );
                }
            }
        }

        for ((_, _), bytes) in commands.iter().zip(serialized) {
            let write_result = child
                .process
                .write_stdin(bytes.as_bytes())
                .and_then(|_| child.process.flush_stdin())
                .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE);
            if write_result.is_err() {
                child.unhealthy.store(true, Ordering::Release);
                fail_all_requests(&self.emitter, &child.active_requests);
                return Err(RUNTIME_UNAVAILABLE_MESSAGE);
            }
        }
        Ok(child.active_requests.clone())
    }

    pub fn shutdown(&self) {
        let Ok(mut running) = self.running.lock() else {
            return;
        };
        let Some(mut child) = running.take() else {
            return;
        };
        fail_all_requests(&self.emitter, &child.active_requests);
        let shutdown = self
            .request_registry
            .claim_internal("host-shutdown")
            .ok()
            .map(|request_id| ValidatedCommand {
                request_id,
                kind: crate::runtime_commands::CommandKind::Shutdown,
                payload: serde_json::json!({}),
            });
        let mut shutdown_bytes = shutdown
            .as_ref()
            .and_then(|command| serialize_command(command).ok());
        let mut shutdown_receiver = None;
        if let Some(shutdown) = shutdown.as_ref().filter(|_| shutdown_bytes.is_some()) {
            let (sender, receiver) = mpsc::channel();
            shutdown_receiver = Some(receiver);
            if let Ok(mut active_requests) = child.active_requests.lock() {
                active_requests.insert(
                    shutdown.request_id.clone(),
                    Arc::new(ActiveRequest::new(
                        ResponseContract::Core,
                        RequestRoute::Private(sender),
                    )),
                );
            }
        }
        child.stopping.store(true, Ordering::Release);
        if let Some(shutdown_bytes) = shutdown_bytes.take() {
            if child
                .process
                .write_stdin(shutdown_bytes.as_bytes())
                .and_then(|_| child.process.flush_stdin())
                .is_err()
            {
                fail_all_requests(&self.emitter, &child.active_requests);
            }
        }
        child.process.close_stdin();
        let exited = child
            .process
            .wait_for(Duration::from_millis(600))
            .unwrap_or(false);
        if !exited {
            let _ = child.process.terminate();
            let _ = child.process.wait_for(Duration::from_millis(300));
        }
        fail_all_requests(&self.emitter, &child.active_requests);
        drop(shutdown_receiver);
    }

    fn start_process(&self) -> Result<RunningProcess, &'static str> {
        let mut process = self.factory.spawn()?;
        let active_requests = Arc::new(Mutex::new(HashMap::new()));
        let stopping = Arc::new(AtomicBool::new(false));
        let unhealthy = Arc::new(AtomicBool::new(false));

        if let Some(stdout) = process.take_stdout() {
            spawn_stdout_reader(
                stdout,
                self.emitter.clone(),
                active_requests.clone(),
                stopping.clone(),
                unhealthy.clone(),
            );
        }
        if let Some(stderr) = process.take_stderr() {
            spawn_stderr_drainer(stderr);
        }

        Ok(RunningProcess {
            process,
            active_requests,
            stopping,
            unhealthy,
        })
    }
}

fn send_private_cancel(
    running: &Arc<Mutex<Option<RunningProcess>>>,
    expected_active_requests: &ActiveRequests,
    emitter: &Arc<dyn EventEmitter>,
    request_id: &str,
) {
    let Ok(mut running) = running.lock() else {
        return;
    };
    let Some(child) = running.as_mut() else {
        return;
    };
    if !Arc::ptr_eq(&child.active_requests, expected_active_requests) {
        return;
    }
    let command = ValidatedCommand {
        request_id: request_id.to_string(),
        kind: crate::runtime_commands::CommandKind::Cancel,
        payload: serde_json::json!({}),
    };
    let write_result = serialize_command(&command).and_then(|bytes| {
        child
            .process
            .write_stdin(bytes.as_bytes())
            .and_then(|_| child.process.flush_stdin())
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)
    });
    if write_result.is_err() {
        child.unhealthy.store(true, Ordering::Release);
        fail_all_requests(emitter, &child.active_requests);
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
    request_registry: Arc<HostRequestRegistry>,
    lifecycle: Mutex<RuntimeLifecycle>,
    sidecar: Mutex<Option<Arc<RuntimeSidecar<OsProcessFactory>>>>,
}

#[derive(Default)]
struct RuntimeLifecycle {
    generation: u64,
}

impl RuntimeController {
    pub fn new(emitter: Arc<dyn EventEmitter>) -> Self {
        Self {
            emitter,
            request_registry: Arc::new(HostRequestRegistry::default()),
            lifecycle: Mutex::new(RuntimeLifecycle::default()),
            sidecar: Mutex::new(None),
        }
    }

    pub fn send_to(&self, command: ValidatedCommand, target: &str) -> Result<(), &'static str> {
        let _lifecycle = self
            .lifecycle
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        self.send_unlocked_to(command, target)
    }

    pub(crate) fn send_unlocked_to(
        &self,
        command: ValidatedCommand,
        target: &str,
    ) -> Result<(), &'static str> {
        self.get_or_start_sidecar()?.send_to(command, target)
    }

    pub(crate) fn send_sequence_unlocked_to(
        &self,
        commands: Vec<ValidatedCommand>,
        target: &str,
    ) -> Result<(), &'static str> {
        self.get_or_start_sidecar()?
            .send_sequence_to(commands, target)
    }

    pub(crate) fn send_private_sequence(
        &self,
        commands: Vec<ValidatedCommand>,
    ) -> Result<PrivateEventStream, &'static str> {
        let _lifecycle = self
            .lifecycle
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        self.get_or_start_sidecar()?.send_private_sequence(commands)
    }

    pub(crate) fn send_private_sequence_unlocked(
        &self,
        commands: Vec<ValidatedCommand>,
    ) -> Result<PrivateEventStream, &'static str> {
        self.get_or_start_sidecar()?.send_private_sequence(commands)
    }

    pub(crate) fn send_private_sequence_for_generation(
        &self,
        commands: Vec<ValidatedCommand>,
        generation: &PrivateRuntimeGeneration,
    ) -> Result<PrivateEventStream, &'static str> {
        let _lifecycle = self
            .lifecycle
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        self.get_or_start_sidecar()?
            .send_private_sequence_for_generation(commands, Some(&generation.0))
    }

    fn get_or_start_sidecar(&self) -> Result<Arc<RuntimeSidecar<OsProcessFactory>>, &'static str> {
        let mut sidecar = self
            .sidecar
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        if sidecar.is_none() {
            let launch = match bundled_launch_spec()? {
                Some(launch) => launch,
                None => {
                    let paths = resolve_runtime_paths()?;
                    build_launch_spec(resolve_python_launcher()?, &paths)?
                }
            };
            *sidecar = Some(Arc::new(RuntimeSidecar::new_with_registry(
                OsProcessFactory::new(launch),
                self.emitter.clone(),
                self.request_registry.clone(),
            )));
        }
        sidecar.as_ref().cloned().ok_or(RUNTIME_UNAVAILABLE_MESSAGE)
    }

    #[allow(dead_code)]
    pub fn emit_provider_unconfigured(&self, request_id: &str) -> Result<(), &'static str> {
        let _lifecycle = self
            .lifecycle
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
        self.emit_provider_unconfigured_unlocked(request_id)
    }

    pub(crate) fn emit_provider_unconfigured_unlocked(
        &self,
        request_id: &str,
    ) -> Result<(), &'static str> {
        self.emit_provider_unconfigured_unlocked_to(request_id, "main")
    }

    pub(crate) fn emit_provider_unconfigured_unlocked_to(
        &self,
        request_id: &str,
        target: &str,
    ) -> Result<(), &'static str> {
        let target = public_route(target)?
            .public_target()
            .ok_or(RUNTIME_UNAVAILABLE_MESSAGE)?
            .to_string();
        self.request_registry.claim(request_id)?;
        self.emitter.emit_to(
            &target,
            CORE_EVENT_NAME,
            serde_json::json!({
                "version": 1,
                "request_id": request_id,
                "event": {
                    "type": "error",
                    "data": {
                        "code": "provider_unconfigured",
                        "message": "请先在设置中保存 Provider 密钥。",
                        "recoverable": true,
                        "action": "settings"
                    }
                }
            }),
        );
        Ok(())
    }

    pub(crate) fn with_lifecycle<T>(
        &self,
        operation: impl FnOnce(&Self, u64) -> Result<T, String>,
    ) -> Result<T, String> {
        let lifecycle = self
            .lifecycle
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE.to_string())?;
        operation(self, lifecycle.generation)
    }

    pub(crate) fn replace_provider_credentials<T>(
        &self,
        update: impl FnOnce() -> Result<T, String>,
    ) -> Result<T, String> {
        let mut lifecycle = self
            .lifecycle
            .lock()
            .map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE.to_string())?;
        let result = update()?;
        lifecycle.generation = lifecycle
            .generation
            .checked_add(1)
            .ok_or_else(|| RUNTIME_UNAVAILABLE_MESSAGE.to_string())?;
        self.shutdown_sidecar();
        Ok(result)
    }

    pub fn shutdown(&self) {
        let Ok(mut lifecycle) = self.lifecycle.lock() else {
            return;
        };
        let Some(next_generation) = lifecycle.generation.checked_add(1) else {
            return;
        };
        lifecycle.generation = next_generation;
        self.shutdown_sidecar();
    }

    fn shutdown_sidecar(&self) {
        let sidecar = self
            .sidecar
            .lock()
            .ok()
            .and_then(|mut sidecar| sidecar.take());
        if let Some(sidecar) = sidecar {
            sidecar.shutdown();
        }
    }
}

fn spawn_stdout_reader(
    stdout: Box<dyn Read + Send>,
    emitter: Arc<dyn EventEmitter>,
    active_requests: ActiveRequests,
    stopping: Arc<AtomicBool>,
    unhealthy: Arc<AtomicBool>,
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
            match parse_sidecar_event(&line) {
                Ok(parsed) => {
                    route_parsed_event(&emitter, &active_requests, parsed);
                }
                Err(_) => {
                    if let Some(request_id) = request_id {
                        fail_request(&emitter, &active_requests, &request_id);
                    } else {
                        unhealthy.store(true, Ordering::Release);
                        fail_all_requests(&emitter, &active_requests);
                        break;
                    }
                }
            }
        }
        if !stopping.load(Ordering::Acquire) {
            unhealthy.store(true, Ordering::Release);
            fail_all_requests(&emitter, &active_requests);
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
        .filter(|request_id| is_safe_request_id(request_id))
        .map(str::to_string)
}

fn public_route(target: &str) -> Result<RequestRoute, &'static str> {
    if matches!(target, "main" | "history") {
        Ok(RequestRoute::PublicTo(target.to_string()))
    } else {
        Err(RUNTIME_UNAVAILABLE_MESSAGE)
    }
}

fn is_private_command(kind: crate::runtime_commands::CommandKind) -> bool {
    use crate::runtime_commands::CommandKind;

    matches!(
        kind,
        CommandKind::Ping
            | CommandKind::Shutdown
            | CommandKind::ConfigureProvider
            | CommandKind::ConfigurePlugin
            | CommandKind::ConfigureHistoryKeys
            | CommandKind::ConfigureHistoryPolicy
            | CommandKind::ConfigureHistoryPath
            | CommandKind::PluginAdminCall
    )
}

fn expected_private_status(kind: crate::runtime_commands::CommandKind) -> Option<&'static str> {
    use crate::runtime_commands::CommandKind;

    match kind {
        CommandKind::ConfigureProvider => Some("provider_configured"),
        CommandKind::ConfigurePlugin => Some("plugin_configured"),
        CommandKind::ConfigureHistoryKeys => Some("history_keys_configured"),
        CommandKind::ConfigureHistoryPolicy => Some("history_policy_configured"),
        CommandKind::ConfigureHistoryPath => Some("history_path_configured"),
        _ => None,
    }
}

fn is_expected_private_success(payload: &Value, expected_message: &str) -> bool {
    payload["event"]["type"] == "status"
        && payload["event"]["data"]["phase"] == "completed"
        && payload["event"]["data"]["message"] == expected_message
}

fn route_parsed_event(
    emitter: &Arc<dyn EventEmitter>,
    active_requests: &ActiveRequests,
    parsed: ParsedSidecarEvent,
) {
    let request = active_requests
        .lock()
        .ok()
        .and_then(|active| active.get(&parsed.request_id).cloned());
    let Some(request) = request else {
        return;
    };
    if !request.contract.matches(&parsed) {
        remove_active_request(active_requests, &parsed.request_id, &request);
        dispatch_failure(emitter, &request, &parsed.request_id);
        return;
    }
    let terminal = parsed.terminal;
    if terminal {
        remove_active_request(active_requests, &parsed.request_id, &request);
    }
    request.dispatch(emitter, parsed.payload, terminal);
}

fn remove_active_request(
    active_requests: &ActiveRequests,
    request_id: &str,
    request: &Arc<ActiveRequest>,
) {
    if let Ok(mut active) = active_requests.lock() {
        if active
            .get(request_id)
            .is_some_and(|candidate| Arc::ptr_eq(candidate, request))
        {
            active.remove(request_id);
        }
    }
}

fn dispatch_failure(
    emitter: &Arc<dyn EventEmitter>,
    request: &Arc<ActiveRequest>,
    request_id: &str,
) {
    request.dispatch(
        emitter,
        safe_failure_payload(request_id, &request.contract),
        true,
    );
}

fn fail_request(
    emitter: &Arc<dyn EventEmitter>,
    active_requests: &ActiveRequests,
    request_id: &str,
) {
    let request = active_requests
        .lock()
        .ok()
        .and_then(|active| active.get(request_id).cloned());
    if let Some(request) = request {
        dispatch_failure(emitter, &request, request_id);
        remove_active_request(active_requests, request_id, &request);
    }
}

fn fail_all_requests(emitter: &Arc<dyn EventEmitter>, active_requests: &ActiveRequests) {
    let requests = active_requests
        .lock()
        .map(|mut active| active.drain().collect::<Vec<_>>())
        .unwrap_or_default();
    for (request_id, request) in requests {
        dispatch_failure(emitter, &request, &request_id);
    }
}

fn safe_failure_payload(request_id: &str, contract: &ResponseContract) -> Value {
    match contract {
        ResponseContract::Core => serde_json::json!({
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
        }),
        ResponseContract::CapabilityList => serde_json::json!({
            "version": 1,
            "request_id": request_id,
            "type": "capability_list",
            "plugins": []
        }),
        ResponseContract::Plugin {
            plugin_id,
            operation,
        } => serde_json::json!({
            "version": 1,
            "request_id": request_id,
            "type": "plugin_event",
            "plugin_id": plugin_id,
            "operation": operation,
            "status": "error",
            "data": {},
            "code": "runtime_unavailable"
        }),
    }
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
    let provider_plugin_src = root.join("plugins").join("provider-minimax").join("src");

    if runtime_dir.is_dir()
        && runtime_src.join("reflex_runtime").join("cli.py").is_file()
        && core_src.join("reflex_core").is_dir()
        && provider_plugin_src.join("reflex_provider_minimax").is_dir()
    {
        Ok(RuntimePaths {
            root,
            runtime_dir,
            runtime_src,
            core_src,
            provider_plugin_src,
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

pub fn bundled_launch_spec() -> Result<Option<LaunchSpec>, &'static str> {
    match std::env::var_os("REFLEX_RUNTIME_EXECUTABLE") {
        Some(path) if !path.is_empty() => build_bundled_launch_spec(Path::new(&path)).map(Some),
        Some(_) => Err(RUNTIME_UNAVAILABLE_MESSAGE),
        None => Ok(None),
    }
}

pub fn build_bundled_launch_spec(executable: &Path) -> Result<LaunchSpec, &'static str> {
    if !executable.is_file() {
        return Err(RUNTIME_UNAVAILABLE_MESSAGE);
    }
    let current_dir = executable
        .parent()
        .map(Path::to_path_buf)
        .ok_or(RUNTIME_UNAVAILABLE_MESSAGE)?;
    Ok(LaunchSpec {
        program: executable.to_path_buf(),
        arguments: vec![],
        current_dir,
        python_path: vec![],
        runtime_development: false,
    })
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
                "--extra".to_string(),
                "builtins".to_string(),
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
        python_path: vec![
            paths.runtime_src.clone(),
            paths.core_src.clone(),
            paths.provider_plugin_src.clone(),
        ],
        runtime_development: cfg!(debug_assertions),
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

#[derive(Clone, PartialEq)]
pub struct ParsedSidecarEvent {
    pub event_name: &'static str,
    pub request_id: String,
    pub terminal: bool,
    pub payload: Value,
}

impl fmt::Debug for ParsedSidecarEvent {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ParsedSidecarEvent")
            .field("event_name", &self.event_name)
            .field("request_id", &self.request_id)
            .field("terminal", &self.terminal)
            .field("payload", &"[REDACTED]")
            .finish()
    }
}

pub fn parse_sidecar_event(raw: &str) -> Result<ParsedSidecarEvent, &'static str> {
    let value: Value = serde_json::from_str(raw).map_err(|_| RUNTIME_UNAVAILABLE_MESSAGE)?;
    let Value::Object(object) = &value else {
        return Err(RUNTIME_UNAVAILABLE_MESSAGE);
    };
    let valid_version = object.get("version").and_then(Value::as_u64) == Some(1);
    let request_id = object
        .get("request_id")
        .and_then(Value::as_str)
        .filter(|request_id| is_safe_request_id(request_id))
        .ok_or(RUNTIME_UNAVAILABLE_MESSAGE)?;
    if !valid_version {
        return Err(RUNTIME_UNAVAILABLE_MESSAGE);
    }

    if object.contains_key("event") {
        if !has_exact_keys(object, &["version", "request_id", "event"]) {
            return Err(RUNTIME_UNAVAILABLE_MESSAGE);
        }
        let event = object
            .get("event")
            .and_then(Value::as_object)
            .filter(|event| has_exact_keys(event, &["type", "data"]))
            .ok_or(RUNTIME_UNAVAILABLE_MESSAGE)?;
        let event_type = event
            .get("type")
            .and_then(Value::as_str)
            .filter(|event_type| {
                matches!(
                    *event_type,
                    "status" | "scene" | "request" | "chunk" | "done" | "error" | "metric"
                )
            })
            .ok_or(RUNTIME_UNAVAILABLE_MESSAGE)?;
        if !event.get("data").is_some_and(Value::is_object) {
            return Err(RUNTIME_UNAVAILABLE_MESSAGE);
        }
        let terminal = matches!(event_type, "metric" | "error")
            || (event_type == "status"
                && matches!(
                    event["data"].get("phase").and_then(Value::as_str),
                    Some("completed" | "cancelled" | "error")
                ));
        return Ok(ParsedSidecarEvent {
            event_name: CORE_EVENT_NAME,
            request_id: request_id.to_string(),
            terminal,
            payload: value,
        });
    }

    match object.get("type").and_then(Value::as_str) {
        Some("plugin_event") => parse_plugin_event(value.clone(), object, request_id),
        Some("capability_list") => parse_capability_list(value.clone(), object, request_id),
        _ => Err(RUNTIME_UNAVAILABLE_MESSAGE),
    }
}

#[cfg(test)]
pub fn parse_event_envelope(raw: &str) -> Result<Value, &'static str> {
    let parsed = parse_sidecar_event(raw)?;
    if parsed.event_name == CORE_EVENT_NAME {
        Ok(parsed.payload)
    } else {
        Err(RUNTIME_UNAVAILABLE_MESSAGE)
    }
}

fn parse_plugin_event(
    value: Value,
    object: &serde_json::Map<String, Value>,
    request_id: &str,
) -> Result<ParsedSidecarEvent, &'static str> {
    let status = object
        .get("status")
        .and_then(Value::as_str)
        .filter(|status| {
            matches!(
                *status,
                "started" | "chunk" | "progress" | "result" | "cancelled" | "error"
            )
        })
        .ok_or(RUNTIME_UNAVAILABLE_MESSAGE)?;
    let expected_fields = if status == "error" {
        &[
            "version",
            "request_id",
            "type",
            "plugin_id",
            "operation",
            "status",
            "data",
            "code",
        ][..]
    } else {
        &[
            "version",
            "request_id",
            "type",
            "plugin_id",
            "operation",
            "status",
            "data",
        ][..]
    };
    if !has_exact_keys(object, expected_fields)
        || !object
            .get("plugin_id")
            .and_then(Value::as_str)
            .is_some_and(crate::runtime_commands::is_safe_id)
        || !object
            .get("operation")
            .and_then(Value::as_str)
            .is_some_and(crate::runtime_commands::is_safe_id)
        || !object
            .get("data")
            .is_some_and(|data| data.is_object() && validate_plugin_event_data(data))
    {
        return Err(RUNTIME_UNAVAILABLE_MESSAGE);
    }
    if status == "error" {
        if !object["data"]
            .as_object()
            .is_some_and(|data| data.is_empty())
            || !object
                .get("code")
                .and_then(Value::as_str)
                .is_some_and(crate::runtime_commands::is_safe_id)
        {
            return Err(RUNTIME_UNAVAILABLE_MESSAGE);
        }
    }
    Ok(ParsedSidecarEvent {
        event_name: PLUGIN_EVENT_NAME,
        request_id: request_id.to_string(),
        terminal: matches!(status, "result" | "cancelled" | "error"),
        payload: value,
    })
}

fn validate_plugin_event_data(value: &Value) -> bool {
    match value {
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => true,
        Value::Array(values) => values.iter().all(validate_plugin_event_data),
        Value::Object(values) => values.iter().all(|(key, value)| {
            !key.is_empty()
                && key.len() <= 128
                && !key.chars().any(|character| character < ' ')
                && validate_plugin_event_data(value)
        }),
    }
}

fn parse_capability_list(
    value: Value,
    object: &serde_json::Map<String, Value>,
    request_id: &str,
) -> Result<ParsedSidecarEvent, &'static str> {
    if !has_exact_keys(object, &["version", "request_id", "type", "plugins"])
        || !object
            .get("plugins")
            .and_then(Value::as_array)
            .is_some_and(|plugins| plugins.iter().all(validate_plugin_descriptor))
    {
        return Err(RUNTIME_UNAVAILABLE_MESSAGE);
    }
    Ok(ParsedSidecarEvent {
        event_name: CAPABILITY_LIST_EVENT_NAME,
        request_id: request_id.to_string(),
        terminal: true,
        payload: value,
    })
}

fn validate_plugin_descriptor(value: &Value) -> bool {
    let Some(descriptor) = value.as_object() else {
        return false;
    };
    let state = descriptor.get("state").and_then(Value::as_str);
    let expected_fields = if state == Some("unavailable") {
        &[
            "id",
            "name",
            "version",
            "kind",
            "permissions",
            "public_operations",
            "enabled",
            "state",
            "error_code",
        ][..]
    } else {
        &[
            "id",
            "name",
            "version",
            "kind",
            "permissions",
            "public_operations",
            "enabled",
            "state",
        ][..]
    };
    has_exact_keys(descriptor, expected_fields)
        && descriptor
            .get("id")
            .and_then(Value::as_str)
            .is_some_and(crate::runtime_commands::is_safe_id)
        && descriptor
            .get("name")
            .and_then(Value::as_str)
            .is_some_and(|name| !name.trim().is_empty())
        && descriptor
            .get("version")
            .and_then(Value::as_str)
            .is_some_and(|version| !version.trim().is_empty())
        && matches!(
            descriptor.get("kind").and_then(Value::as_str),
            Some("storage" | "transformer" | "command")
        )
        && validate_unique_ids(descriptor.get("permissions"))
        && validate_unique_ids(descriptor.get("public_operations"))
        && descriptor.get("enabled").is_some_and(Value::is_boolean)
        && matches!(
            state,
            Some(
                "available"
                    | "disabled"
                    | "absent"
                    | "read_only"
                    | "writable"
                    | "private"
                    | "unavailable"
            )
        )
        && if state == Some("unavailable") {
            descriptor
                .get("error_code")
                .and_then(Value::as_str)
                .is_some_and(crate::runtime_commands::is_safe_id)
        } else {
            !descriptor.contains_key("error_code")
        }
}

fn validate_unique_ids(value: Option<&Value>) -> bool {
    let Some(values) = value.and_then(Value::as_array) else {
        return false;
    };
    let mut unique = HashSet::new();
    values.iter().all(|value| {
        value
            .as_str()
            .filter(|value| crate::runtime_commands::is_safe_id(value))
            .is_some_and(|value| unique.insert(value))
    })
}

fn has_exact_keys(object: &serde_json::Map<String, Value>, fields: &[&str]) -> bool {
    object.len() == fields.len() && fields.iter().all(|field| object.contains_key(*field))
}

fn is_safe_request_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':'))
}

#[cfg(test)]
mod tests {
    use std::collections::{HashMap, VecDeque};
    use std::io::{self, Cursor, Read};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::{Arc, Barrier, Mutex};

    use serde_json::{json, Value};

    use crate::runtime_commands::{
        configure_history_keys_command, configure_history_path_command,
        configure_history_policy_command, configure_provider_command, CommandKind,
        ValidatedCommand,
    };

    use super::{
        build_bundled_launch_spec, build_launch_spec, build_process_command, parse_event_envelope,
        parse_sidecar_event, resolve_runtime_paths_from, route_parsed_event, serialize_command,
        spawn_stdout_reader, ChildProcess, EventEmitter, HostRequestRegistry, OsProcessFactory,
        ParsedSidecarEvent, ProcessFactory, PythonLauncher, RuntimeController, RuntimeSidecar,
        CAPABILITY_LIST_EVENT_NAME, CORE_EVENT_NAME, PLUGIN_EVENT_NAME,
        RUNTIME_UNAVAILABLE_MESSAGE,
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
    fn serializes_shutdown_from_the_validated_command_model() {
        let command = ValidatedCommand {
            request_id: "host-shutdown-1".to_string(),
            kind: CommandKind::Shutdown,
            payload: json!({}),
        };

        assert_eq!(
            serialize_command(&command).unwrap(),
            "{\"version\":1,\"request_id\":\"host-shutdown-1\",\"type\":\"shutdown\",\"payload\":{}}\n"
        );
    }

    #[test]
    fn controller_shutdown_preserves_seen_ids_for_a_rebuilt_sidecar() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let controller = RuntimeController::new(Arc::new(RecordingEmitter(events)));
        controller
            .emit_provider_unconfigured("controller-persisted")
            .unwrap();
        controller.shutdown();
        let writes = Arc::new(Mutex::new(Vec::new()));
        let sidecar = RuntimeSidecar::new_with_registry(
            FakeProcessFactory::new(vec![FakeProcess::running(writes.clone())]),
            Arc::new(FakeEmitter),
            controller.request_registry.clone(),
        );

        assert_eq!(
            sidecar.send(ValidatedCommand {
                request_id: "controller-persisted".to_string(),
                kind: CommandKind::ListPlugins,
                payload: json!({}),
            }),
            Err(super::DUPLICATE_REQUEST_MESSAGE)
        );
        assert!(writes.lock().unwrap().is_empty());
    }

    #[test]
    fn provider_save_and_delete_serialize_optimize_across_generation_change() {
        for updated_secret in [Some("new-secret".to_string()), None] {
            let controller = Arc::new(RuntimeController::new(Arc::new(FakeEmitter)));
            let secret = Arc::new(Mutex::new(Some("old-secret".to_string())));
            let update_entered = Arc::new(Barrier::new(2));
            let release_update = Arc::new(Barrier::new(2));
            let update_thread = {
                let controller = controller.clone();
                let secret = secret.clone();
                let update_entered = update_entered.clone();
                let release_update = release_update.clone();
                let updated_secret = updated_secret.clone();
                std::thread::spawn(move || {
                    controller
                        .replace_provider_credentials(|| {
                            *secret.lock().unwrap() = updated_secret;
                            update_entered.wait();
                            release_update.wait();
                            Ok(())
                        })
                        .unwrap();
                })
            };
            update_entered.wait();

            let observed = Arc::new(Mutex::new(None));
            let optimize_thread = {
                let controller = controller.clone();
                let secret = secret.clone();
                let observed = observed.clone();
                std::thread::spawn(move || {
                    controller
                        .with_lifecycle(|_, generation| {
                            *observed.lock().unwrap() =
                                Some((generation, secret.lock().unwrap().clone()));
                            Ok(())
                        })
                        .unwrap();
                })
            };
            std::thread::sleep(std::time::Duration::from_millis(20));
            assert!(observed.lock().unwrap().is_none());
            release_update.wait();
            update_thread.join().unwrap();
            optimize_thread.join().unwrap();

            assert_eq!(*observed.lock().unwrap(), Some((1, updated_secret.clone())));
            assert_ne!(
                observed.lock().unwrap().as_ref().unwrap().1.as_deref(),
                Some("old-secret")
            );
        }
    }

    #[test]
    fn provider_unconfigured_claims_once_and_duplicate_does_not_emit() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let controller = RuntimeController::new(Arc::new(RecordingEmitter(events.clone())));

        assert!(controller
            .emit_provider_unconfigured("provider-direct")
            .is_ok());
        assert_eq!(events.lock().unwrap().len(), 1);
        assert_eq!(
            controller.emit_provider_unconfigured("provider-direct"),
            Err(super::DUPLICATE_REQUEST_MESSAGE)
        );
        assert_eq!(events.lock().unwrap().len(), 1);
    }

    #[test]
    fn seen_registry_rotates_the_oldest_id_without_losing_recent_replay_protection() {
        let registry = HostRequestRegistry::with_limit(2);
        registry.claim("seen-a").unwrap();
        registry.claim("seen-b").unwrap();
        registry.claim("seen-c").unwrap();

        assert_eq!(
            registry.claim("seen-c"),
            Err(super::DUPLICATE_REQUEST_MESSAGE)
        );
        assert_eq!(registry.claim("seen-a"), Ok(()));
    }

    #[test]
    fn seen_registry_rotation_is_atomic_at_the_concurrent_boundary() {
        let registry = Arc::new(HostRequestRegistry::with_limit(1));
        let barrier = Arc::new(Barrier::new(3));
        let results = Arc::new(Mutex::new(Vec::new()));
        let mut threads = Vec::new();
        for request_id in ["boundary-a", "boundary-b"] {
            let registry = registry.clone();
            let barrier = barrier.clone();
            let results = results.clone();
            threads.push(std::thread::spawn(move || {
                barrier.wait();
                results.lock().unwrap().push(registry.claim(request_id));
            }));
        }
        barrier.wait();
        for thread in threads {
            thread.join().unwrap();
        }

        let results = results.lock().unwrap();
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 2);
    }

    #[test]
    fn active_request_id_cannot_be_reused_after_replay_history_rotation() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let registry = Arc::new(HostRequestRegistry::with_limit(1));
        let sidecar = RuntimeSidecar::new_with_registry(
            FakeProcessFactory::new(vec![FakeProcess::running(writes)]),
            Arc::new(FakeEmitter),
            registry,
        );

        sidecar.send(optimize_command("active-a")).unwrap();
        sidecar.send(optimize_command("active-b")).unwrap();

        assert_eq!(
            sidecar.send(optimize_command("active-a")),
            Err(super::DUPLICATE_REQUEST_MESSAGE)
        );
    }

    #[test]
    fn consecutive_shutdowns_use_distinct_claimed_internal_request_ids() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let factory = FakeProcessFactory::new(vec![
            FakeProcess::running(writes.clone()),
            FakeProcess::running(writes.clone()),
        ]);
        let sidecar = RuntimeSidecar::new(factory, Arc::new(FakeEmitter));

        for request_id in ["before-shutdown-1", "before-shutdown-2"] {
            sidecar
                .send(ValidatedCommand {
                    request_id: request_id.to_string(),
                    kind: CommandKind::ListPlugins,
                    payload: json!({}),
                })
                .unwrap();
            sidecar.shutdown();
        }

        let shutdown_ids = writes
            .lock()
            .unwrap()
            .iter()
            .filter_map(|bytes| serde_json::from_slice::<Value>(bytes).ok())
            .filter(|command| command["type"] == "shutdown")
            .filter_map(|command| command["request_id"].as_str().map(str::to_string))
            .collect::<Vec<_>>();
        assert_eq!(shutdown_ids, ["host-shutdown-1", "host-shutdown-2"]);
    }

    #[test]
    fn seen_registry_claim_is_atomic_under_concurrency() {
        let registry = Arc::new(HostRequestRegistry::default());
        let barrier = Arc::new(Barrier::new(9));
        let mut threads = Vec::new();
        for _ in 0..8 {
            let registry = registry.clone();
            let barrier = barrier.clone();
            threads.push(std::thread::spawn(move || {
                barrier.wait();
                registry.claim("concurrent-claim")
            }));
        }
        barrier.wait();
        let results = threads
            .into_iter()
            .map(|thread| thread.join().unwrap())
            .collect::<Vec<_>>();

        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(
            results
                .iter()
                .filter(|result| **result == Err(super::DUPLICATE_REQUEST_MESSAGE))
                .count(),
            7
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
    fn keeps_core_route_open_for_history_save_metric_after_done() {
        let done = parse_sidecar_event(
            r#"{"version":1,"request_id":"req-1","event":{"type":"done","data":{}}}"#,
        )
        .unwrap();
        let metric = parse_sidecar_event(
            r#"{"version":1,"request_id":"req-1","event":{"type":"metric","data":{"save_status":"saved"}}}"#,
        )
        .unwrap();

        assert!(!done.terminal);
        assert!(metric.terminal);
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
    fn strictly_routes_core_plugin_and_capability_runtime_envelopes() {
        let cases = [
            (
                r#"{"version":1,"request_id":"core-1","event":{"type":"chunk","data":{"text":"片段"}}}"#,
                CORE_EVENT_NAME,
            ),
            (
                r#"{"version":1,"request_id":"plugin-1","type":"plugin_event","plugin_id":"translator","operation":"translate","status":"result","data":{"text":"完成"}}"#,
                PLUGIN_EVENT_NAME,
            ),
            (
                r#"{"version":1,"request_id":"list-1","type":"capability_list","plugins":[]}"#,
                CAPABILITY_LIST_EVENT_NAME,
            ),
        ];

        for (raw, event_name) in cases {
            let parsed = parse_sidecar_event(raw).unwrap();
            assert_eq!(parsed.event_name, event_name);
        }
    }

    #[test]
    fn rejects_unknown_fields_and_invalid_plugin_contract_values() {
        let invalid = [
            r#"{"version":1,"request_id":"plugin-1","type":"plugin_event","plugin_id":"translator","operation":"translate","status":"result","data":{},"debug":true}"#,
            r#"{"version":1,"request_id":"plugin-1","type":"plugin_event","plugin_id":"translator","operation":"translate","status":"unknown","data":{}}"#,
            r#"{"version":1,"request_id":"plugin-1","type":"plugin_event","plugin_id":"translator","operation":"translate","status":"result","data":{"":true}}"#,
            r#"{"version":1,"request_id":"plugin-1","type":"plugin_event","plugin_id":"translator","operation":"translate","status":"result","data":{"nested":{"\u0001":true}}}"#,
            r#"{"version":1,"request_id":"list-1","type":"capability_list","plugins":[{"id":"translator","name":"Translator","version":"1","kind":"transformer","permissions":[],"public_operations":["translate"],"enabled":true,"state":"available","module":"secret-path"}]}"#,
            r#"{"version":1,"request_id":"core-1","event":{"type":"chunk","data":{},"debug":true}}"#,
        ];

        for raw in invalid {
            assert_eq!(parse_sidecar_event(raw), Err(RUNTIME_UNAVAILABLE_MESSAGE));
        }
    }

    #[test]
    fn duplicate_request_ids_are_rejected_before_any_second_write_and_cancel_never_registers() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let factory = FakeProcessFactory::new(vec![FakeProcess::running(writes.clone())]);
        let sidecar = RuntimeSidecar::new(factory, Arc::new(FakeEmitter));
        let list = |request_id: &str| ValidatedCommand {
            request_id: request_id.to_string(),
            kind: CommandKind::ListPlugins,
            payload: json!({}),
        };

        sidecar.send(list("duplicate")).unwrap();
        assert_eq!(sidecar.send(list("duplicate")), Err("运行请求重复。"));
        assert_eq!(
            sidecar.send(ValidatedCommand {
                request_id: "missing".to_string(),
                kind: CommandKind::Cancel,
                payload: json!({}),
            }),
            Err("目标请求不存在。")
        );
        assert_eq!(writes.lock().unwrap().len(), 1);
    }

    #[test]
    fn terminal_request_id_remains_seen_and_cannot_be_sent_again() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let events = Arc::new(Mutex::new(Vec::new()));
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![FakeProcess::running(writes.clone())]),
            Arc::new(RecordingEmitter(events.clone())),
        );
        let command = ValidatedCommand {
            request_id: "terminal-seen".to_string(),
            kind: CommandKind::ListPlugins,
            payload: json!({}),
        };

        sidecar.send(command.clone()).unwrap();
        let active_requests = sidecar
            .running
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .active_requests
            .clone();
        route_parsed_event(
            &sidecar.emitter,
            &active_requests,
            ParsedSidecarEvent {
                event_name: CAPABILITY_LIST_EVENT_NAME,
                request_id: "terminal-seen".to_string(),
                terminal: true,
                payload: json!({
                    "version": 1,
                    "request_id": "terminal-seen",
                    "type": "capability_list",
                    "plugins": []
                }),
            },
        );

        assert!(active_requests.lock().unwrap().is_empty());
        assert_eq!(sidecar.send(command), Err(super::DUPLICATE_REQUEST_MESSAGE));
        assert_eq!(writes.lock().unwrap().len(), 1);
        assert_eq!(events.lock().unwrap().len(), 1);
    }

    #[test]
    fn child_restart_does_not_allow_a_seen_request_id_to_be_reused() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let factory = FakeProcessFactory::new(vec![
            FakeProcess::exits_after_write(writes.clone()),
            FakeProcess::running(writes.clone()),
        ]);
        let sidecar = RuntimeSidecar::new(factory.clone(), Arc::new(FakeEmitter));
        let command = ValidatedCommand {
            request_id: "restart-seen".to_string(),
            kind: CommandKind::ListPlugins,
            payload: json!({}),
        };

        sidecar.send(command.clone()).unwrap();
        assert_eq!(sidecar.send(command), Err(super::DUPLICATE_REQUEST_MESSAGE));
        assert_eq!(factory.launch_count(), 1);
        assert_eq!(writes.lock().unwrap().len(), 1);
    }

    #[test]
    fn late_terminal_and_chunk_events_are_dropped_after_active_cleanup() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let events = Arc::new(Mutex::new(Vec::new()));
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![FakeProcess::running(writes)]),
            Arc::new(RecordingEmitter(events.clone())),
        );
        sidecar
            .send(ValidatedCommand {
                request_id: "late-events".to_string(),
                kind: CommandKind::Optimize,
                payload: json!({ "text": "fixture" }),
            })
            .unwrap();
        let active_requests = sidecar
            .running
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .active_requests
            .clone();
        let done = |payload| ParsedSidecarEvent {
            event_name: CORE_EVENT_NAME,
            request_id: "late-events".to_string(),
            terminal: true,
            payload,
        };
        route_parsed_event(
            &sidecar.emitter,
            &active_requests,
            done(json!({
                "version": 1,
                "request_id": "late-events",
                "event": { "type": "done", "data": { "text": "done" } }
            })),
        );
        route_parsed_event(
            &sidecar.emitter,
            &active_requests,
            done(json!({
                "version": 1,
                "request_id": "late-events",
                "event": { "type": "done", "data": { "text": "late-done" } }
            })),
        );
        route_parsed_event(
            &sidecar.emitter,
            &active_requests,
            ParsedSidecarEvent {
                event_name: CORE_EVENT_NAME,
                request_id: "late-events".to_string(),
                terminal: false,
                payload: json!({
                    "version": 1,
                    "request_id": "late-events",
                    "event": { "type": "chunk", "data": { "text": "late-chunk" } }
                }),
            },
        );

        assert!(active_requests.lock().unwrap().is_empty());
        assert_eq!(events.lock().unwrap().len(), 1);
    }

    #[test]
    fn cancel_targets_active_request_without_adding_to_seen_ids() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![FakeProcess::running(writes.clone())]),
            Arc::new(FakeEmitter),
        );
        sidecar
            .send(ValidatedCommand {
                request_id: "cancel-active".to_string(),
                kind: CommandKind::ListPlugins,
                payload: json!({}),
            })
            .unwrap();
        let seen_before = sidecar.request_registry.history.lock().unwrap().ids.len();

        sidecar
            .send(ValidatedCommand {
                request_id: "cancel-active".to_string(),
                kind: CommandKind::Cancel,
                payload: json!({}),
            })
            .unwrap();

        assert_eq!(seen_before, 1);
        assert_eq!(
            sidecar.request_registry.history.lock().unwrap().ids.len(),
            seen_before
        );
        assert_eq!(writes.lock().unwrap().len(), 2);
    }

    #[test]
    fn cancel_requires_the_same_public_window_owner() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![FakeProcess::running(writes.clone())]),
            Arc::new(FakeEmitter),
        );
        sidecar
            .send_to(
                ValidatedCommand {
                    request_id: "owned-request".to_string(),
                    kind: CommandKind::ListPlugins,
                    payload: json!({}),
                },
                "main",
            )
            .unwrap();

        assert_eq!(
            sidecar.send_to(
                ValidatedCommand {
                    request_id: "owned-request".to_string(),
                    kind: CommandKind::Cancel,
                    payload: json!({}),
                },
                "history",
            ),
            Err(super::REQUEST_NOT_FOUND_MESSAGE)
        );
        sidecar
            .send_to(
                ValidatedCommand {
                    request_id: "owned-request".to_string(),
                    kind: CommandKind::Cancel,
                    payload: json!({}),
                },
                "main",
            )
            .unwrap();
    }

    #[test]
    fn private_events_are_delivered_to_a_waiter_and_never_emitted_to_webview() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let events = Arc::new(Mutex::new(Vec::new()));
        let process = FakeProcess::with_stdout(
            writes.clone(),
            br#"{"version":1,"request_id":"private-1","event":{"type":"status","data":{"phase":"completed","message":"ok"}}}
            "#
            .to_vec(),
        );
        let factory = FakeProcessFactory::new(vec![process]);
        let sidecar = RuntimeSidecar::new(factory, Arc::new(NamedRecordingEmitter(events.clone())));
        let mut waiter = sidecar
            .send_private(ValidatedCommand {
                request_id: "private-1".to_string(),
                kind: CommandKind::ConfigureProvider,
                payload: json!({
                    "provider_id": "minimax",
                    "secret": "fixture-private",
                    "config": {}
                }),
            })
            .unwrap();

        let payload = waiter
            .recv_timeout(std::time::Duration::from_secs(1))
            .unwrap();
        assert_eq!(payload["request_id"], "private-1");
        assert!(events.lock().unwrap().is_empty());
        assert!(waiter.active_requests.lock().unwrap().is_empty());
        assert_eq!(writes.lock().unwrap().len(), 1);
    }

    #[test]
    fn first_plugin_configuration_failure_stops_before_later_configuration_and_optimize() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let events = Arc::new(Mutex::new(Vec::new()));
        let release = Arc::new(AtomicBool::new(false));
        let process = FakeProcess::with_stdout_reader(
            writes.clone(),
            Box::new(WriteGatedReader::new(
                writes.clone(),
                release.clone(),
                vec![
                    (1, core_status("provider-1", "provider_configured")),
                    (2, core_error("plugin-1", "plugin_configuration_denied")),
                ],
            )),
        );
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![process]),
            Arc::new(NamedRecordingEmitter(events.clone())),
        );
        let provider = configure_provider_command(
            "minimax",
            "history-fixture-provider-key",
            json!({ "model": "fixture-model" }),
        )
        .unwrap();
        let provider = ValidatedCommand {
            request_id: "provider-1".to_string(),
            ..provider
        };

        let result = sidecar.send_sequence(vec![
            provider.clone(),
            plugin_configuration("plugin-1", "translator", true),
            plugin_configuration("plugin-2", "markdown-preview", true),
            optimize_command("optimize-1"),
        ]);

        release.store(true, Ordering::Release);
        assert_eq!(result, Err(RUNTIME_UNAVAILABLE_MESSAGE));
        assert_eq!(
            written_command_types(&writes),
            ["configure_provider", "configure_plugin"]
        );
        assert!(events.lock().unwrap().is_empty());
        assert!(!format!("{provider:?} {result:?}").contains("history-fixture-provider-key"));
    }

    #[test]
    fn second_plugin_configuration_failure_stops_before_optimize() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let release = Arc::new(AtomicBool::new(false));
        let process = FakeProcess::with_stdout_reader(
            writes.clone(),
            Box::new(WriteGatedReader::new(
                writes.clone(),
                release.clone(),
                vec![
                    (1, core_status("provider-2", "provider_configured")),
                    (2, core_status("plugin-3", "plugin_configured")),
                    (3, core_error("plugin-4", "plugin_configuration_denied")),
                ],
            )),
        );
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![process]),
            Arc::new(FakeEmitter),
        );
        let provider = configure_provider_command(
            "minimax",
            "history-fixture-provider-key",
            json!({ "model": "fixture-model" }),
        )
        .unwrap();

        let result = sidecar.send_sequence(vec![
            ValidatedCommand {
                request_id: "provider-2".to_string(),
                ..provider
            },
            plugin_configuration("plugin-3", "translator", true),
            plugin_configuration("plugin-4", "markdown-preview", true),
            optimize_command("optimize-2"),
        ]);

        release.store(true, Ordering::Release);
        assert_eq!(result, Err(RUNTIME_UNAVAILABLE_MESSAGE));
        assert_eq!(
            written_command_types(&writes),
            ["configure_provider", "configure_plugin", "configure_plugin"]
        );
    }

    #[test]
    fn optimize_is_sent_only_after_every_private_configuration_succeeds() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let release = Arc::new(AtomicBool::new(false));
        let process = FakeProcess::with_stdout_reader(
            writes.clone(),
            Box::new(WriteGatedReader::new(
                writes.clone(),
                release.clone(),
                vec![
                    (1, core_status("provider-3", "provider_configured")),
                    (2, core_status("plugin-5", "plugin_configured")),
                    (3, core_status("plugin-6", "plugin_configured")),
                ],
            )),
        );
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![process]),
            Arc::new(FakeEmitter),
        );
        let provider = configure_provider_command(
            "minimax",
            "history-fixture-provider-key",
            json!({ "model": "fixture-model" }),
        )
        .unwrap();

        let result = sidecar.send_sequence(vec![
            ValidatedCommand {
                request_id: "provider-3".to_string(),
                ..provider
            },
            plugin_configuration("plugin-5", "translator", true),
            plugin_configuration("plugin-6", "markdown-preview", true),
            optimize_command("optimize-3"),
        ]);

        assert_eq!(result, Ok(()));
        assert_eq!(
            written_command_types(&writes),
            [
                "configure_provider",
                "configure_plugin",
                "configure_plugin",
                "optimize"
            ]
        );
        release.store(true, Ordering::Release);
    }

    #[test]
    fn empty_history_keys_complete_private_handshakes_and_do_not_block_optimize() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let events = Arc::new(Mutex::new(Vec::new()));
        let release = Arc::new(AtomicBool::new(false));
        let process = FakeProcess::with_stdout_reader(
            writes.clone(),
            Box::new(WriteGatedReader::new(
                writes.clone(),
                release.clone(),
                vec![
                    (
                        1,
                        core_status("history-path-empty", "history_path_configured"),
                    ),
                    (
                        2,
                        core_status("history-keys-empty", "history_keys_configured"),
                    ),
                    (
                        3,
                        core_status("history-policy-empty", "history_policy_configured"),
                    ),
                ],
            )),
        );
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![process]),
            Arc::new(NamedRecordingEmitter(events.clone())),
        );
        let history_path = std::env::temp_dir().join("history").join("history.sqlite3");
        let path = ValidatedCommand {
            request_id: "history-path-empty".to_string(),
            ..configure_history_path_command(&history_path).unwrap()
        };
        let keys = ValidatedCommand {
            request_id: "history-keys-empty".to_string(),
            ..configure_history_keys_command(Default::default()).unwrap()
        };
        let policy = ValidatedCommand {
            request_id: "history-policy-empty".to_string(),
            ..configure_history_policy_command(true, false, "secrets").unwrap()
        };

        let result = sidecar.send_sequence(vec![
            path,
            keys,
            policy,
            optimize_command("optimize-empty-history-keys"),
        ]);

        assert_eq!(result, Ok(()));
        assert_eq!(
            written_command_types(&writes),
            [
                "configure_history_path",
                "configure_history_keys",
                "configure_history_policy",
                "optimize",
            ]
        );
        assert!(events.lock().unwrap().is_empty());
        release.store(true, Ordering::Release);
    }

    #[test]
    fn private_configuration_timeout_cleans_the_route_and_never_sends_optimize() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![FakeProcess::running(writes.clone())]),
            Arc::new(FakeEmitter),
        );
        let provider = configure_provider_command(
            "minimax",
            "history-fixture-provider-key",
            json!({ "model": "fixture-model" }),
        )
        .unwrap();

        let result = sidecar.send_sequence(vec![provider, optimize_command("optimize-timeout")]);

        assert_eq!(result, Err(RUNTIME_UNAVAILABLE_MESSAGE));
        assert_eq!(
            written_command_types(&writes),
            ["configure_provider", "cancel"]
        );
        assert!(sidecar
            .running
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .active_requests
            .lock()
            .unwrap()
            .is_empty());
    }

    #[test]
    fn generic_private_sequence_uses_private_routes_without_webview_or_cancel() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let events = Arc::new(Mutex::new(Vec::new()));
        let release = Arc::new(AtomicBool::new(false));
        let process = FakeProcess::with_stdout_reader(
            writes.clone(),
            Box::new(WriteGatedReader::new(
                writes.clone(),
                release.clone(),
                vec![
                    (1, core_status("ping-private", "pong")),
                    (
                        2,
                        plugin_result("admin-private", "history-sqlite", "delete"),
                    ),
                    (3, core_status("shutdown-private", "shutdown")),
                ],
            )),
        );
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![process]),
            Arc::new(NamedRecordingEmitter(events.clone())),
        );

        let result = sidecar.send_sequence(vec![
            ValidatedCommand {
                request_id: "ping-private".to_string(),
                kind: CommandKind::Ping,
                payload: json!({}),
            },
            ValidatedCommand {
                request_id: "admin-private".to_string(),
                kind: CommandKind::PluginAdminCall,
                payload: json!({
                    "plugin_id": "history-sqlite",
                    "operation": "delete",
                    "input": {}
                }),
            },
            ValidatedCommand {
                request_id: "shutdown-private".to_string(),
                kind: CommandKind::Shutdown,
                payload: json!({}),
            },
        ]);

        assert_eq!(result, Ok(()));
        wait_for_active_requests_empty(&sidecar);
        release.store(true, Ordering::Release);
        assert_eq!(
            written_command_types(&writes),
            ["ping", "plugin_admin_call", "shutdown"]
        );
        assert!(events.lock().unwrap().is_empty());
    }

    #[test]
    fn private_admin_sequence_delivers_chunks_only_to_waiter() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let events = Arc::new(Mutex::new(Vec::new()));
        let release = Arc::new(AtomicBool::new(false));
        let process = FakeProcess::with_stdout_reader(
            writes.clone(),
            Box::new(WriteGatedReader::new(
                writes.clone(),
                release.clone(),
                vec![
                    (
                        1,
                        core_status("policy-private", "history_policy_configured"),
                    ),
                    (
                        2,
                        plugin_status("export-private", "export", "started", json!({})),
                    ),
                    (
                        2,
                        plugin_status(
                            "export-private",
                            "export",
                            "chunk",
                            json!({"bytes": "5Lit5paH"}),
                        ),
                    ),
                    (
                        2,
                        plugin_status(
                            "export-private",
                            "export",
                            "result",
                            json!({"record_count": 1}),
                        ),
                    ),
                ],
            )),
        );
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![process]),
            Arc::new(NamedRecordingEmitter(events.clone())),
        );
        let policy = ValidatedCommand {
            request_id: "policy-private".to_string(),
            ..configure_history_policy_command(true, false, "secrets").unwrap()
        };
        let admin = ValidatedCommand {
            request_id: "export-private".to_string(),
            kind: CommandKind::PluginAdminCall,
            payload: json!({
                "plugin_id": "history-sqlite",
                "operation": "export",
                "input": {"format": "json", "filters": {}}
            }),
        };

        let mut stream = sidecar.send_private_sequence(vec![policy, admin]).unwrap();
        let started = stream
            .recv_timeout(std::time::Duration::from_secs(1))
            .unwrap();
        let chunk = stream
            .recv_timeout(std::time::Duration::from_secs(1))
            .unwrap();
        let result = stream
            .recv_timeout(std::time::Duration::from_secs(1))
            .unwrap();

        assert_eq!(started["status"], "started");
        assert_eq!(chunk["data"]["bytes"], "5Lit5paH");
        assert_eq!(result["status"], "result");
        assert!(events.lock().unwrap().is_empty());
        release.store(true, Ordering::Release);
    }

    #[test]
    fn configuration_sequence_fails_instead_of_restarting_after_child_exit() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let first_release = Arc::new(AtomicBool::new(false));
        let second_release = Arc::new(AtomicBool::new(false));
        let first = FakeProcess::with_stdout_reader_and_exit_after_write(
            writes.clone(),
            Box::new(WriteGatedReader::new(
                writes.clone(),
                first_release.clone(),
                vec![(1, core_status("provider-generation", "provider_configured"))],
            )),
        );
        let second = FakeProcess::with_stdout_reader(
            writes.clone(),
            Box::new(WriteGatedReader::new(
                writes.clone(),
                second_release.clone(),
                vec![(2, core_status("plugin-generation", "plugin_configured"))],
            )),
        );
        let factory = FakeProcessFactory::new(vec![first, second]);
        let sidecar = RuntimeSidecar::new(factory.clone(), Arc::new(FakeEmitter));
        let provider = configure_provider_command(
            "minimax",
            "history-fixture-provider-key",
            json!({ "model": "fixture-model" }),
        )
        .unwrap();

        let result = sidecar.send_sequence(vec![
            ValidatedCommand {
                request_id: "provider-generation".to_string(),
                ..provider
            },
            plugin_configuration("plugin-generation", "translator", true),
            optimize_command("optimize-generation"),
        ]);

        first_release.store(true, Ordering::Release);
        second_release.store(true, Ordering::Release);
        assert_eq!(result, Err(RUNTIME_UNAVAILABLE_MESSAGE));
        assert_eq!(factory.launch_count(), 1);
        assert_eq!(written_command_types(&writes), ["configure_provider"]);
    }

    #[test]
    fn expected_generation_does_not_restart_after_a_second_liveness_change() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let release = Arc::new(AtomicBool::new(false));
        let first = FakeProcess::with_stdout_reader_and_has_exited_script(
            writes.clone(),
            Box::new(WriteGatedReader::new(
                writes.clone(),
                release.clone(),
                vec![(1, core_status("provider-liveness", "provider_configured"))],
            )),
            vec![false, true],
        );
        let factory = FakeProcessFactory::new(vec![first, FakeProcess::running(writes.clone())]);
        let sidecar = RuntimeSidecar::new(factory.clone(), Arc::new(FakeEmitter));
        let provider = configure_provider_command(
            "minimax",
            "history-fixture-provider-key",
            json!({ "model": "fixture-model" }),
        )
        .unwrap();

        let result = sidecar.send_sequence(vec![
            ValidatedCommand {
                request_id: "provider-liveness".to_string(),
                ..provider
            },
            optimize_command("optimize-liveness"),
        ]);

        release.store(true, Ordering::Release);
        assert_eq!(
            (
                result,
                factory.launch_count(),
                written_command_types(&writes)
            ),
            (
                Err(RUNTIME_UNAVAILABLE_MESSAGE),
                1,
                vec!["configure_provider".to_string()]
            )
        );
    }

    #[test]
    fn private_timeout_cancel_and_shutdown_remove_waiter_registrations() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let factory = FakeProcessFactory::new(vec![FakeProcess::running(writes.clone())]);
        let sidecar = RuntimeSidecar::new(factory, Arc::new(FakeEmitter));
        let mut timed_out = sidecar
            .send_private(ValidatedCommand {
                request_id: "private-timeout".to_string(),
                kind: CommandKind::ConfigureProvider,
                payload: json!({
                    "provider_id": "minimax",
                    "secret": "fixture-private",
                    "config": {}
                }),
            })
            .unwrap();
        assert_eq!(
            timed_out.recv_timeout(std::time::Duration::from_millis(1)),
            Err(RUNTIME_UNAVAILABLE_MESSAGE)
        );
        assert!(timed_out.active_requests.lock().unwrap().is_empty());
        assert!(writes.lock().unwrap().iter().any(|write| {
            String::from_utf8_lossy(write).contains(r#""type":"cancel""#)
                && String::from_utf8_lossy(write).contains("private-timeout")
        }));

        let mut cancelled = sidecar
            .send_private(ValidatedCommand {
                request_id: "private-cancel".to_string(),
                kind: CommandKind::ConfigureProvider,
                payload: json!({
                    "provider_id": "minimax",
                    "secret": "fixture-private",
                    "config": {}
                }),
            })
            .unwrap();
        cancelled.cancel();
        assert!(cancelled.active_requests.lock().unwrap().is_empty());
        assert!(writes.lock().unwrap().iter().any(|write| {
            String::from_utf8_lossy(write).contains(r#""type":"cancel""#)
                && String::from_utf8_lossy(write).contains("private-cancel")
        }));
        drop(cancelled);

        let mut shutdown_waiter = sidecar
            .send_private(ValidatedCommand {
                request_id: "private-shutdown".to_string(),
                kind: CommandKind::ConfigureProvider,
                payload: json!({
                    "provider_id": "minimax",
                    "secret": "fixture-private",
                    "config": {}
                }),
            })
            .unwrap();
        sidecar.shutdown();
        assert!(shutdown_waiter.active_requests.lock().unwrap().is_empty());
        shutdown_waiter.cancel();
    }

    #[test]
    fn dropping_an_incomplete_private_waiter_sends_cancel_and_cleans_route() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![FakeProcess::running(writes.clone())]),
            Arc::new(FakeEmitter),
        );
        let waiter = sidecar
            .send_private(ValidatedCommand {
                request_id: "private-drop".to_string(),
                kind: CommandKind::ConfigureProvider,
                payload: json!({
                    "provider_id": "minimax",
                    "secret": "fixture-private",
                    "config": {}
                }),
            })
            .unwrap();
        let active_requests = waiter.active_requests.clone();
        drop(waiter);

        assert!(active_requests.lock().unwrap().is_empty());
        assert!(writes.lock().unwrap().iter().any(|write| {
            String::from_utf8_lossy(write).contains(r#""type":"cancel""#)
                && String::from_utf8_lossy(write).contains("private-drop")
        }));
    }

    #[test]
    fn private_cancel_write_failure_still_cleans_the_waiter_route() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let sidecar = RuntimeSidecar::new(
            FakeProcessFactory::new(vec![FakeProcess::fails_after_writes(writes, 1)]),
            Arc::new(FakeEmitter),
        );
        let waiter = sidecar
            .send_private(ValidatedCommand {
                request_id: "private-cancel-failure".to_string(),
                kind: CommandKind::ConfigureProvider,
                payload: json!({
                    "provider_id": "minimax",
                    "secret": "fixture-private",
                    "config": {}
                }),
            })
            .unwrap();
        let active_requests = waiter.active_requests.clone();
        drop(waiter);

        assert!(active_requests.lock().unwrap().is_empty());
    }

    #[test]
    fn stdout_without_a_trusted_request_id_fails_all_and_next_send_restarts_the_child() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let factory = FakeProcessFactory::new(vec![
            FakeProcess::with_stdout(writes.clone(), b"Traceback secret=value\n".to_vec()),
            FakeProcess::running(writes.clone()),
        ]);
        let events = Arc::new(Mutex::new(Vec::new()));
        let sidecar = RuntimeSidecar::new(
            factory.clone(),
            Arc::new(NamedRecordingEmitter(events.clone())),
        );

        sidecar
            .send(ValidatedCommand {
                request_id: "public-1".to_string(),
                kind: CommandKind::ListPlugins,
                payload: json!({}),
            })
            .unwrap();
        std::thread::sleep(std::time::Duration::from_millis(80));
        assert!(events.lock().unwrap().iter().any(|(name, payload)| {
            name == CAPABILITY_LIST_EVENT_NAME && payload["request_id"] == "public-1"
        }));

        sidecar
            .send(ValidatedCommand {
                request_id: "public-2".to_string(),
                kind: CommandKind::ListPlugins,
                payload: json!({}),
            })
            .unwrap();
        assert_eq!(factory.launch_count(), 2);
    }

    #[test]
    fn turns_invalid_stdout_into_a_fixed_safe_error_without_raw_content() {
        let error = parse_event_envelope("Traceback: token=secret-value").unwrap_err();

        assert_eq!(error, RUNTIME_UNAVAILABLE_MESSAGE);
        assert!(!error.contains("secret-value"));
    }

    #[test]
    fn parsed_sidecar_event_debug_never_contains_payload_data() {
        let event = parse_sidecar_event(
            r#"{"version":1,"request_id":"debug-safe","event":{"type":"chunk","data":{"text":"fixture-sensitive-payload"}}}"#,
        )
        .unwrap();

        let debug = format!("{event:?}");
        assert!(debug.contains("debug-safe"));
        assert!(debug.contains(CORE_EVENT_NAME));
        assert!(debug.contains("[REDACTED]"));
        assert!(!debug.contains("fixture-sensitive-payload"));
    }

    #[test]
    fn active_route_linearizes_stdout_terminal_and_drain_dispatch() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let emitter: Arc<dyn EventEmitter> = Arc::new(RecordingEmitter(events.clone()));
        let route = Arc::new(super::ActiveRequest::new(
            super::ResponseContract::Core,
            super::RequestRoute::Public,
        ));
        let active_requests = Arc::new(Mutex::new(HashMap::from([(
            "linearized".to_string(),
            route,
        )])));
        let barrier = Arc::new(Barrier::new(3));

        let event_thread = {
            let emitter = emitter.clone();
            let active_requests = active_requests.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                route_parsed_event(
                    &emitter,
                    &active_requests,
                    ParsedSidecarEvent {
                        event_name: CORE_EVENT_NAME,
                        request_id: "linearized".to_string(),
                        terminal: true,
                        payload: json!({
                            "version": 1,
                            "request_id": "linearized",
                            "event": { "type": "done", "data": { "text": "terminal" } }
                        }),
                    },
                );
                route_parsed_event(
                    &emitter,
                    &active_requests,
                    ParsedSidecarEvent {
                        event_name: CORE_EVENT_NAME,
                        request_id: "linearized".to_string(),
                        terminal: false,
                        payload: json!({
                            "version": 1,
                            "request_id": "linearized",
                            "event": { "type": "chunk", "data": { "text": "late" } }
                        }),
                    },
                );
            })
        };
        let drain_thread = {
            let emitter = emitter.clone();
            let active_requests = active_requests.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                super::fail_all_requests(&emitter, &active_requests);
            })
        };
        barrier.wait();
        event_thread.join().unwrap();
        drain_thread.join().unwrap();

        let events = events.lock().unwrap();
        let terminal_count = events
            .iter()
            .filter(|payload| matches!(payload["event"]["type"].as_str(), Some("done" | "error")))
            .count();
        assert_eq!(terminal_count, 1);
        let terminal_index = events
            .iter()
            .position(|payload| matches!(payload["event"]["type"].as_str(), Some("done" | "error")))
            .unwrap();
        assert!(events[terminal_index + 1..]
            .iter()
            .all(|payload| payload["event"]["type"] != "chunk"));
    }

    #[test]
    fn public_route_emits_only_to_its_window_owner() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let emitter: Arc<dyn EventEmitter> = Arc::new(TargetRecordingEmitter(events.clone()));
        let route = super::ActiveRequest::new(
            super::ResponseContract::Core,
            super::RequestRoute::PublicTo("history".to_string()),
        );

        assert!(route.dispatch(
            &emitter,
            json!({"version":1,"request_id":"owned","event":{"type":"done","data":{}}}),
            true,
        ));
        assert_eq!(events.lock().unwrap()[0].0, "history");
        assert_eq!(events.lock().unwrap()[0].1, CORE_EVENT_NAME);
    }

    #[test]
    fn fails_all_active_requests_when_invalid_stdout_has_no_request_id() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let active_requests = Arc::new(Mutex::new(HashMap::from([(
            "req-active".to_string(),
            Arc::new(super::ActiveRequest::new(
                super::ResponseContract::Core,
                super::RequestRoute::Public,
            )),
        )])));
        let release = Arc::new(AtomicBool::new(false));

        spawn_stdout_reader(
            Box::new(HoldOpenReader {
                bytes: Cursor::new(b"Traceback: token=secret-value\n".to_vec()),
                release: release.clone(),
            }),
            Arc::new(RecordingEmitter(events.clone())),
            active_requests.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(AtomicBool::new(false)),
        );

        std::thread::sleep(std::time::Duration::from_millis(80));
        let events_before_eof = events.lock().unwrap().clone();
        let active_requests_cleared_before_eof = active_requests.lock().unwrap().is_empty();
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
                "--extra",
                "builtins",
                "python",
                "-m",
                "reflex_runtime.cli",
            ]
        );
        assert_eq!(launch.current_dir, paths.runtime_dir);
        assert_eq!(
            launch.python_path,
            vec![paths.runtime_src, paths.core_src, paths.provider_plugin_src]
        );
        assert!(launch.runtime_development);
        let command = build_process_command(&launch).unwrap();
        assert_eq!(
            command
                .get_envs()
                .find(|(key, _)| *key == "REFLEX_RUNTIME_DEVELOPMENT")
                .and_then(|(_, value)| value),
            Some(std::ffi::OsStr::new("1"))
        );
    }

    #[test]
    fn builds_a_resource_sidecar_launch_without_python_paths() {
        let executable = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml");
        let launch = build_bundled_launch_spec(&executable).unwrap();

        assert_eq!(launch.program, executable);
        assert!(launch.arguments.is_empty());
        assert!(launch.python_path.is_empty());
        assert!(!launch.runtime_development);
        let command = build_process_command(&launch).unwrap();
        assert_eq!(
            command
                .get_envs()
                .find(|(key, _)| *key == "REFLEX_RUNTIME_DEVELOPMENT")
                .map(|(_, value)| value),
            Some(None)
        );
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
                b"{\"version\":1,\"request_id\":\"host-shutdown-1\",\"type\":\"shutdown\",\"payload\":{}}\n".to_vec(),
            ]
        );
    }

    #[test]
    fn concurrent_configuration_and_optimize_sequences_never_interleave() {
        let writes = Arc::new(Mutex::new(Vec::new()));
        let release = Arc::new(AtomicBool::new(false));
        let factory = FakeProcessFactory::new(vec![FakeProcess::with_stdout_reader(
            writes.clone(),
            Box::new(CommandResponseReader::new(writes.clone(), release.clone())),
        )]);
        let sidecar = Arc::new(RuntimeSidecar::new(factory, Arc::new(FakeEmitter)));
        let barrier = Arc::new(Barrier::new(3));
        let mut threads = Vec::new();

        for (request_id, model) in [("req-a", "model-a"), ("req-b", "model-b")] {
            let sidecar = sidecar.clone();
            let barrier = barrier.clone();
            threads.push(std::thread::spawn(move || {
                let configure = configure_provider_command(
                    "minimax",
                    "fixture-private-credential",
                    json!({ "model": model, "tls_verify": true }),
                )
                .unwrap();
                let optimize = ValidatedCommand {
                    request_id: request_id.to_string(),
                    kind: CommandKind::Optimize,
                    payload: json!({ "text": request_id, "provider": "minimax", "model": model }),
                };
                barrier.wait();
                sidecar.send_sequence(vec![configure, optimize]).unwrap();
            }));
        }
        barrier.wait();
        for thread in threads {
            thread.join().unwrap();
        }
        release.store(true, Ordering::Release);

        let lines = writes
            .lock()
            .unwrap()
            .iter()
            .map(|bytes| String::from_utf8(bytes.clone()).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(lines.len(), 4);
        for pair in lines.chunks_exact(2) {
            assert!(pair[0].contains(r#""type":"configure_provider""#));
            assert!(pair[1].contains(r#""type":"optimize""#));
        }
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
                    "provider": "mock",
                    "model": "mock-stream",
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
        has_exited_script: VecDeque<bool>,
        fail_after_writes: Option<usize>,
        writes: Arc<Mutex<Vec<Vec<u8>>>>,
        stdout: Option<Box<dyn Read + Send>>,
    }

    struct HoldOpenReader {
        bytes: Cursor<Vec<u8>>,
        release: Arc<AtomicBool>,
    }

    struct WriteGatedReader {
        writes: Arc<Mutex<Vec<Vec<u8>>>>,
        release: Arc<AtomicBool>,
        responses: VecDeque<(usize, Cursor<Vec<u8>>)>,
    }

    struct CommandResponseReader {
        writes: Arc<Mutex<Vec<Vec<u8>>>>,
        release: Arc<AtomicBool>,
        processed: usize,
        response: Cursor<Vec<u8>>,
    }

    impl WriteGatedReader {
        fn new(
            writes: Arc<Mutex<Vec<Vec<u8>>>>,
            release: Arc<AtomicBool>,
            responses: Vec<(usize, Vec<u8>)>,
        ) -> Self {
            Self {
                writes,
                release,
                responses: responses
                    .into_iter()
                    .map(|(required_writes, response)| (required_writes, Cursor::new(response)))
                    .collect(),
            }
        }
    }

    impl Read for WriteGatedReader {
        fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
            loop {
                if let Some((required_writes, response)) = self.responses.front_mut() {
                    if self.writes.lock().unwrap().len() < *required_writes {
                        std::thread::sleep(std::time::Duration::from_millis(2));
                        continue;
                    }
                    if response.position() < response.get_ref().len() as u64 {
                        return response.read(buffer);
                    }
                    self.responses.pop_front();
                    continue;
                } else if self.release.load(Ordering::Acquire) {
                    return Ok(0);
                }
                std::thread::sleep(std::time::Duration::from_millis(2));
            }
        }
    }

    impl CommandResponseReader {
        fn new(writes: Arc<Mutex<Vec<Vec<u8>>>>, release: Arc<AtomicBool>) -> Self {
            Self {
                writes,
                release,
                processed: 0,
                response: Cursor::new(Vec::new()),
            }
        }
    }

    impl Read for CommandResponseReader {
        fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
            loop {
                if self.response.position() < self.response.get_ref().len() as u64 {
                    return self.response.read(buffer);
                }
                let command = self.writes.lock().unwrap().get(self.processed).cloned();
                if let Some(command) = command {
                    self.processed += 1;
                    let command: Value = serde_json::from_slice(&command).unwrap();
                    if command["type"] == "configure_provider" {
                        self.response = Cursor::new(core_status(
                            command["request_id"].as_str().unwrap(),
                            "provider_configured",
                        ));
                    }
                    continue;
                }
                if self.release.load(Ordering::Acquire) {
                    return Ok(0);
                }
                std::thread::sleep(std::time::Duration::from_millis(2));
            }
        }
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
                has_exited_script: VecDeque::new(),
                fail_after_writes: None,
                writes,
                stdout: None,
            }
        }

        fn running(writes: Arc<Mutex<Vec<Vec<u8>>>>) -> Self {
            Self {
                exited: false,
                exits_after_write: false,
                has_exited_script: VecDeque::new(),
                fail_after_writes: None,
                writes,
                stdout: None,
            }
        }

        fn fails_after_writes(writes: Arc<Mutex<Vec<Vec<u8>>>>, count: usize) -> Self {
            Self {
                exited: false,
                exits_after_write: false,
                has_exited_script: VecDeque::new(),
                fail_after_writes: Some(count),
                writes,
                stdout: None,
            }
        }

        fn with_stdout(writes: Arc<Mutex<Vec<Vec<u8>>>>, stdout: Vec<u8>) -> Self {
            Self {
                exited: false,
                exits_after_write: false,
                has_exited_script: VecDeque::new(),
                fail_after_writes: None,
                writes,
                stdout: Some(Box::new(Cursor::new(stdout))),
            }
        }

        fn with_stdout_reader(
            writes: Arc<Mutex<Vec<Vec<u8>>>>,
            stdout: Box<dyn Read + Send>,
        ) -> Self {
            Self {
                exited: false,
                exits_after_write: false,
                has_exited_script: VecDeque::new(),
                fail_after_writes: None,
                writes,
                stdout: Some(stdout),
            }
        }

        fn with_stdout_reader_and_exit_after_write(
            writes: Arc<Mutex<Vec<Vec<u8>>>>,
            stdout: Box<dyn Read + Send>,
        ) -> Self {
            Self {
                exited: false,
                exits_after_write: true,
                has_exited_script: VecDeque::new(),
                fail_after_writes: None,
                writes,
                stdout: Some(stdout),
            }
        }

        fn with_stdout_reader_and_has_exited_script(
            writes: Arc<Mutex<Vec<Vec<u8>>>>,
            stdout: Box<dyn Read + Send>,
            has_exited_script: Vec<bool>,
        ) -> Self {
            Self {
                exited: false,
                exits_after_write: false,
                has_exited_script: has_exited_script.into(),
                fail_after_writes: None,
                writes,
                stdout: Some(stdout),
            }
        }
    }

    impl ChildProcess for FakeProcess {
        fn has_exited(&mut self) -> io::Result<bool> {
            Ok(self.has_exited_script.pop_front().unwrap_or(self.exited))
        }

        fn write_stdin(&mut self, bytes: &[u8]) -> io::Result<()> {
            if self
                .fail_after_writes
                .is_some_and(|limit| self.writes.lock().unwrap().len() >= limit)
            {
                return Err(io::Error::new(
                    io::ErrorKind::BrokenPipe,
                    "fixture write failure",
                ));
            }
            self.writes.lock().unwrap().push(bytes.to_vec());
            self.exited = self.exits_after_write;
            Ok(())
        }

        fn flush_stdin(&mut self) -> io::Result<()> {
            Ok(())
        }

        fn take_stdout(&mut self) -> Option<Box<dyn Read + Send>> {
            self.stdout.take()
        }
    }

    fn core_status(request_id: &str, message: &str) -> Vec<u8> {
        format!(
            "{{\"version\":1,\"request_id\":\"{request_id}\",\"event\":{{\"type\":\"status\",\"data\":{{\"phase\":\"completed\",\"message\":\"{message}\"}}}}}}\n"
        )
        .into_bytes()
    }

    fn core_error(request_id: &str, code: &str) -> Vec<u8> {
        format!(
            "{{\"version\":1,\"request_id\":\"{request_id}\",\"event\":{{\"type\":\"error\",\"data\":{{\"code\":\"{code}\",\"message\":\"fixture failure\"}}}}}}\n"
        )
        .into_bytes()
    }

    fn plugin_result(request_id: &str, plugin_id: &str, operation: &str) -> Vec<u8> {
        format!(
            "{{\"version\":1,\"request_id\":\"{request_id}\",\"type\":\"plugin_event\",\"plugin_id\":\"{plugin_id}\",\"operation\":\"{operation}\",\"status\":\"result\",\"data\":{{}}}}\n"
        )
        .into_bytes()
    }

    fn plugin_status(request_id: &str, operation: &str, status: &str, data: Value) -> Vec<u8> {
        serde_json::to_vec(&json!({
            "version": 1,
            "request_id": request_id,
            "type": "plugin_event",
            "plugin_id": "history-sqlite",
            "operation": operation,
            "status": status,
            "data": data,
        }))
        .map(|mut value| {
            value.push(b'\n');
            value
        })
        .unwrap()
    }

    fn plugin_configuration(request_id: &str, plugin_id: &str, enabled: bool) -> ValidatedCommand {
        ValidatedCommand {
            request_id: request_id.to_string(),
            kind: CommandKind::ConfigurePlugin,
            payload: json!({ "plugin_id": plugin_id, "enabled": enabled }),
        }
    }

    fn optimize_command(request_id: &str) -> ValidatedCommand {
        ValidatedCommand {
            request_id: request_id.to_string(),
            kind: CommandKind::Optimize,
            payload: json!({ "text": "fixture input", "provider": "minimax" }),
        }
    }

    fn written_command_types(writes: &Arc<Mutex<Vec<Vec<u8>>>>) -> Vec<String> {
        writes
            .lock()
            .unwrap()
            .iter()
            .map(|write| {
                serde_json::from_slice::<Value>(write).unwrap()["type"]
                    .as_str()
                    .unwrap()
                    .to_string()
            })
            .collect()
    }

    fn wait_for_active_requests_empty(sidecar: &RuntimeSidecar<FakeProcessFactory>) {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(1);
        while std::time::Instant::now() < deadline {
            let empty = sidecar
                .running
                .lock()
                .unwrap()
                .as_ref()
                .is_some_and(|running| running.active_requests.lock().unwrap().is_empty());
            if empty {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(2));
        }
        panic!("timed out waiting for private routes to close");
    }

    struct FakeEmitter;

    impl EventEmitter for FakeEmitter {
        fn emit(&self, _event_name: &str, _payload: serde_json::Value) {}
    }

    struct RecordingEmitter(Arc<Mutex<Vec<serde_json::Value>>>);

    impl EventEmitter for RecordingEmitter {
        fn emit(&self, event_name: &str, payload: serde_json::Value) {
            let _ = event_name;
            self.0.lock().unwrap().push(payload);
        }
    }

    struct NamedRecordingEmitter(Arc<Mutex<Vec<(String, serde_json::Value)>>>);

    impl EventEmitter for NamedRecordingEmitter {
        fn emit(&self, event_name: &str, payload: serde_json::Value) {
            self.0
                .lock()
                .unwrap()
                .push((event_name.to_string(), payload));
        }
    }

    struct TargetRecordingEmitter(Arc<Mutex<Vec<(String, String, serde_json::Value)>>>);

    impl EventEmitter for TargetRecordingEmitter {
        fn emit(&self, event_name: &str, payload: serde_json::Value) {
            self.emit_to("main", event_name, payload);
        }

        fn emit_to(&self, target: &str, event_name: &str, payload: serde_json::Value) {
            self.0
                .lock()
                .unwrap()
                .push((target.to_string(), event_name.to_string(), payload));
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
