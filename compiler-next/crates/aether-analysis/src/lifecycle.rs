//! Serial per-workspace scheduling and cooperative analysis request lifecycle.
#![allow(missing_docs)]

use std::collections::{BTreeMap, VecDeque};
use std::fmt;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex, mpsc};
use std::thread::{self, JoinHandle};
use std::time::Instant;

use crate::{
    AnalysisFailure, AnalysisRequest, AnalysisResult, AnalysisTarget, CanonicalAnalyzer,
    EditorWorkspace, PublishDecision, RequestId,
};

/// Shared cooperative cancellation state. Requesting and observing cancellation are distinct.
#[derive(Clone)]
pub struct CancellationToken {
    inner: Arc<CancellationState>,
}

struct CancellationState {
    requested: AtomicBool,
    observed: AtomicBool,
    requested_at: Mutex<Option<Instant>>,
    observed_after_ns: AtomicU64,
}

impl fmt::Debug for CancellationToken {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CancellationToken")
            .field("requested", &self.is_cancellation_requested())
            .field("observed", &self.is_cancellation_observed())
            .finish()
    }
}

impl Default for CancellationToken {
    fn default() -> Self {
        Self::new()
    }
}

impl CancellationToken {
    #[must_use]
    pub fn new() -> Self {
        Self {
            inner: Arc::new(CancellationState {
                requested: AtomicBool::new(false),
                observed: AtomicBool::new(false),
                requested_at: Mutex::new(None),
                observed_after_ns: AtomicU64::new(0),
            }),
        }
    }

    pub fn cancel(&self) {
        if !self.inner.requested.swap(true, Ordering::AcqRel) {
            *self
                .inner
                .requested_at
                .lock()
                .expect("cancellation timestamp poisoned") = Some(Instant::now());
        }
    }

    #[must_use]
    pub fn is_cancellation_requested(&self) -> bool {
        self.inner.requested.load(Ordering::Acquire)
    }

    #[must_use]
    pub fn is_cancellation_observed(&self) -> bool {
        self.inner.observed.load(Ordering::Acquire)
    }

    pub fn checkpoint(&self) -> Result<(), AnalysisFailure> {
        if self.is_cancellation_requested() {
            self.observe();
            Err(AnalysisFailure::Cancelled)
        } else {
            Ok(())
        }
    }

    pub(crate) fn provider_checkpoint(&self) -> Result<(), crate::SourceProviderError> {
        if self.is_cancellation_requested() {
            self.observe();
            Err(crate::SourceProviderError {
                message: "analysis request cancelled".into(),
            })
        } else {
            Ok(())
        }
    }

    fn observe(&self) {
        if !self.inner.observed.swap(true, Ordering::AcqRel) {
            let elapsed = self
                .inner
                .requested_at
                .lock()
                .expect("cancellation timestamp poisoned")
                .as_ref()
                .map_or(std::time::Duration::ZERO, Instant::elapsed)
                .as_nanos();
            self.inner.observed_after_ns.store(
                u64::try_from(elapsed).unwrap_or(u64::MAX),
                Ordering::Release,
            );
        }
    }

    #[must_use]
    pub fn observation_ns(&self) -> Option<u128> {
        self.is_cancellation_observed()
            .then(|| u128::from(self.inner.observed_after_ns.load(Ordering::Acquire)))
    }
}

/// Valid lifecycle states. All states after `Running` are terminal.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RequestState {
    Queued,
    Running,
    Published,
    Stale,
    Cancelled,
    TargetClosed,
    SourceChanged,
    InternalFailure,
}

impl RequestState {
    pub fn transition(&mut self, next: Self) -> Result<(), InvalidRequestTransition> {
        let valid = matches!(
            (*self, next),
            (
                Self::Queued,
                Self::Running | Self::Cancelled | Self::InternalFailure
            ) | (
                Self::Running,
                Self::Published
                    | Self::Stale
                    | Self::Cancelled
                    | Self::TargetClosed
                    | Self::SourceChanged
                    | Self::InternalFailure
            )
        );
        if !valid {
            return Err(InvalidRequestTransition {
                from: *self,
                to: next,
            });
        }
        *self = next;
        Ok(())
    }

    #[must_use]
    pub const fn is_terminal(self) -> bool {
        !matches!(self, Self::Queued | Self::Running)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct InvalidRequestTransition {
    pub from: RequestState,
    pub to: RequestState,
}

/// Final owned outcome delivered exactly once for a request.
#[derive(Debug)]
pub struct RequestCompletion {
    pub request: RequestId,
    pub state: RequestState,
    pub result: Option<AnalysisResult>,
    pub failure: Option<AnalysisFailure>,
}

/// Aggregate measurements for one workspace worker.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct SchedulerMeasurements {
    pub max_pending_requests: usize,
    pub retained_snapshot_bytes: usize,
    pub stale_work_ns: u128,
    pub cancelled_work_ns: u128,
    pub completed_requests: u64,
}

/// Client side of a scheduled request.
pub struct RequestHandle {
    id: RequestId,
    state: Arc<Mutex<RequestState>>,
    cancellation: CancellationToken,
    receiver: mpsc::Receiver<RequestCompletion>,
}

impl RequestHandle {
    #[must_use]
    pub const fn id(&self) -> RequestId {
        self.id
    }

    #[must_use]
    pub fn state(&self) -> RequestState {
        *self.state.lock().expect("request state poisoned")
    }

    #[must_use]
    pub fn cancellation(&self) -> CancellationToken {
        self.cancellation.clone()
    }

    pub fn wait(self) -> Result<RequestCompletion, AnalysisFailure> {
        self.receiver
            .recv()
            .map_err(|_| AnalysisFailure::Internal("analysis worker stopped unexpectedly".into()))
    }
}

struct PendingRequest {
    request: AnalysisRequest,
    state: Arc<Mutex<RequestState>>,
    sender: mpsc::Sender<RequestCompletion>,
    queued_at: Instant,
    snapshot_bytes: usize,
}

struct WorkerState {
    queue: VecDeque<PendingRequest>,
    latest: BTreeMap<AnalysisTarget, RequestId>,
    running: Option<(AnalysisTarget, RequestId, CancellationToken)>,
    closing: bool,
    measurements: SchedulerMeasurements,
}

struct SharedWorker {
    state: Mutex<WorkerState>,
    ready: Condvar,
    observer: Option<LifecycleObserver>,
}

type LifecycleObserver = Arc<dyn Fn(RequestId, LifecyclePoint) + Send + Sync>;

#[derive(Clone, Copy)]
enum LifecyclePoint {
    BeforeAnalysis,
    BeforePublication,
}

/// A deterministic serial worker. At most one obsolete queued request is retained per target.
pub struct AnalysisScheduler {
    workspace: Arc<EditorWorkspace>,
    next_request: AtomicU64,
    shared: Arc<SharedWorker>,
    worker: Option<JoinHandle<()>>,
}

impl AnalysisScheduler {
    #[must_use]
    pub fn new(workspace: Arc<EditorWorkspace>) -> Self {
        let shared = Arc::new(SharedWorker {
            state: Mutex::new(WorkerState {
                queue: VecDeque::new(),
                latest: BTreeMap::new(),
                running: None,
                closing: false,
                measurements: SchedulerMeasurements::default(),
            }),
            ready: Condvar::new(),
            observer: None,
        });
        let worker_shared = Arc::clone(&shared);
        let worker_workspace = Arc::clone(&workspace);
        let worker = thread::Builder::new()
            .name(format!("aether-analysis-{}", workspace.id().0))
            .spawn(move || worker_loop(&worker_workspace, &worker_shared))
            .expect("failed to start analysis worker");
        Self {
            workspace,
            next_request: AtomicU64::new(1),
            shared,
            worker: Some(worker),
        }
    }

    #[cfg(test)]
    fn new_with_observer(workspace: Arc<EditorWorkspace>, observer: LifecycleObserver) -> Self {
        let shared = Arc::new(SharedWorker {
            state: Mutex::new(WorkerState {
                queue: VecDeque::new(),
                latest: BTreeMap::new(),
                running: None,
                closing: false,
                measurements: SchedulerMeasurements::default(),
            }),
            ready: Condvar::new(),
            observer: Some(observer),
        });
        let worker_shared = Arc::clone(&shared);
        let worker_workspace = Arc::clone(&workspace);
        let worker = thread::Builder::new()
            .name(format!("aether-analysis-test-{}", workspace.id().0))
            .spawn(move || worker_loop(&worker_workspace, &worker_shared))
            .expect("failed to start analysis worker");
        Self {
            workspace,
            next_request: AtomicU64::new(1),
            shared,
            worker: Some(worker),
        }
    }

    pub fn request(&self, target: AnalysisTarget) -> Result<RequestHandle, AnalysisFailure> {
        let id = RequestId(self.next_request.fetch_add(1, Ordering::Relaxed));
        let cancellation = CancellationToken::new();
        cancellation.checkpoint()?;
        let snapshot = self.workspace.snapshot();
        cancellation.checkpoint()?;
        let snapshot_bytes = snapshot.retained_text_bytes();
        let request = AnalysisRequest {
            id,
            target: target.clone(),
            snapshot,
            cancellation: cancellation.clone(),
        };
        let state = Arc::new(Mutex::new(RequestState::Queued));
        let (sender, receiver) = mpsc::channel();
        let mut worker = self.shared.state.lock().expect("analysis queue poisoned");
        if worker.closing {
            return Err(AnalysisFailure::Internal(
                "workspace worker is closed".into(),
            ));
        }
        if let Some((_, _, token)) = worker
            .running
            .as_ref()
            .filter(|(running_target, _, _)| running_target == &target)
        {
            token.cancel();
        }
        let mut index = 0;
        while index < worker.queue.len() {
            if worker.queue[index].request.target == target {
                let obsolete = worker.queue.remove(index).expect("queue index exists");
                obsolete.request.cancellation.cancel();
                obsolete.request.cancellation.observe();
                finish(
                    obsolete,
                    RequestState::Cancelled,
                    None,
                    Some(AnalysisFailure::Cancelled),
                );
            } else {
                index += 1;
            }
        }
        worker.latest.insert(target, id);
        worker.queue.push_back(PendingRequest {
            request,
            state: Arc::clone(&state),
            sender,
            queued_at: Instant::now(),
            snapshot_bytes,
        });
        worker.measurements.max_pending_requests = worker
            .measurements
            .max_pending_requests
            .max(worker.queue.len());
        worker.measurements.retained_snapshot_bytes = worker
            .queue
            .iter()
            .map(|pending| pending.snapshot_bytes)
            .sum();
        drop(worker);
        self.shared.ready.notify_one();
        Ok(RequestHandle {
            id,
            state,
            cancellation,
            receiver,
        })
    }

    #[must_use]
    pub fn measurements(&self) -> SchedulerMeasurements {
        self.shared
            .state
            .lock()
            .expect("analysis queue poisoned")
            .measurements
            .clone()
    }

    pub fn shutdown(&mut self) {
        {
            let mut worker = self.shared.state.lock().expect("analysis queue poisoned");
            if !worker.closing {
                worker.closing = true;
                for pending in worker.queue.drain(..) {
                    pending.request.cancellation.cancel();
                    finish(
                        pending,
                        RequestState::Cancelled,
                        None,
                        Some(AnalysisFailure::Cancelled),
                    );
                }
                if let Some((_, _, token)) = &worker.running {
                    token.cancel();
                }
                worker.measurements.retained_snapshot_bytes = 0;
            }
        }
        self.shared.ready.notify_all();
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

impl Drop for AnalysisScheduler {
    fn drop(&mut self) {
        self.shutdown();
    }
}

#[allow(clippy::too_many_lines)]
fn worker_loop(workspace: &EditorWorkspace, shared: &SharedWorker) {
    loop {
        let pending = {
            let mut state = shared.state.lock().expect("analysis queue poisoned");
            while state.queue.is_empty() && !state.closing {
                state = shared.ready.wait(state).expect("analysis queue poisoned");
            }
            if state.queue.is_empty() && state.closing {
                return;
            }
            let pending = state.queue.pop_front().expect("checked non-empty");
            state.measurements.retained_snapshot_bytes =
                state.queue.iter().map(|queued| queued.snapshot_bytes).sum();
            state.running = Some((
                pending.request.target.clone(),
                pending.request.id,
                pending.request.cancellation.clone(),
            ));
            pending
        };
        transition(&pending.state, RequestState::Running);
        let analysis_started = Instant::now();
        let queue_ns = pending.queued_at.elapsed().as_nanos();
        let request_copy = pending.request.clone();
        let analyzed = catch_unwind(AssertUnwindSafe(|| {
            if let Some(observer) = &shared.observer {
                observer(request_copy.id, LifecyclePoint::BeforeAnalysis);
            }
            CanonicalAnalyzer.analyze(pending.request.clone())
        }))
        .map_err(|payload| {
            let detail = payload
                .downcast_ref::<&str>()
                .copied()
                .or_else(|| payload.downcast_ref::<String>().map(String::as_str))
                .unwrap_or("unknown panic");
            AnalysisFailure::Internal(format!("frontend panic: {detail}"))
        })
        .and_then(|result| result);
        let analysis_ns = analysis_started.elapsed().as_nanos();
        let (terminal, result, failure) = match analyzed {
            Err(AnalysisFailure::Cancelled) => (
                RequestState::Cancelled,
                None,
                Some(AnalysisFailure::Cancelled),
            ),
            Err(AnalysisFailure::ClosedDocument(document)) => (
                RequestState::TargetClosed,
                None,
                Some(AnalysisFailure::ClosedDocument(document)),
            ),
            Err(error) => (RequestState::InternalFailure, None, Some(error)),
            Ok(mut result) => {
                result.measurements.queue_ns = queue_ns;
                result.measurements.analysis_ns = analysis_ns;
                result.measurements.cancellation_observation_ns =
                    request_copy.cancellation.observation_ns();
                if let Some(observer) = &shared.observer {
                    observer(request_copy.id, LifecyclePoint::BeforePublication);
                }
                if let Err(error) = request_copy.cancellation.checkpoint() {
                    (RequestState::Cancelled, None, Some(error))
                } else {
                    let state = shared.state.lock().expect("analysis queue poisoned");
                    let latest =
                        state.latest.get(&request_copy.target).copied() == Some(request_copy.id);
                    let decision = workspace.may_publish_analysis(
                        &request_copy.target,
                        &result,
                        &request_copy.cancellation,
                        latest,
                    );
                    drop(state);
                    match decision {
                        PublishDecision::Current => (RequestState::Published, Some(result), None),
                        PublishDecision::Stale => (RequestState::Stale, None, None),
                        PublishDecision::DocumentClosed => (RequestState::TargetClosed, None, None),
                        PublishDecision::SourceChanged => (RequestState::SourceChanged, None, None),
                        PublishDecision::ProviderError(message) => (
                            RequestState::InternalFailure,
                            None,
                            Some(AnalysisFailure::Internal(message)),
                        ),
                        PublishDecision::Cancelled => (
                            RequestState::Cancelled,
                            None,
                            Some(AnalysisFailure::Cancelled),
                        ),
                    }
                }
            }
        };
        {
            let mut state = shared.state.lock().expect("analysis queue poisoned");
            state.running = None;
            state.measurements.completed_requests += 1;
            match terminal {
                RequestState::Stale => state.measurements.stale_work_ns += analysis_ns,
                RequestState::Cancelled => state.measurements.cancelled_work_ns += analysis_ns,
                _ => {}
            }
        }
        finish(pending, terminal, result, failure);
    }
}

fn transition(state: &Mutex<RequestState>, next: RequestState) {
    state
        .lock()
        .expect("request state poisoned")
        .transition(next)
        .expect("worker attempted an invalid request transition");
}

#[allow(clippy::needless_pass_by_value)]
fn finish(
    pending: PendingRequest,
    terminal: RequestState,
    result: Option<AnalysisResult>,
    failure: Option<AnalysisFailure>,
) {
    transition(&pending.state, terminal);
    let _ = pending.sender.send(RequestCompletion {
        request: pending.request.id,
        state: terminal,
        result,
        failure,
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    use crate::{DocumentLocator, OpenDocument};

    static NEXT_TEST: AtomicU64 = AtomicU64::new(1);

    struct TestWorkspace {
        path: PathBuf,
        workspace: Arc<EditorWorkspace>,
        first: crate::DocumentId,
    }

    impl TestWorkspace {
        fn new(text: &str) -> Self {
            let path = std::env::temp_dir().join(format!(
                "aether-lifecycle-{}-{}",
                std::process::id(),
                NEXT_TEST.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&path).unwrap();
            let first_path = path.join("main.ae");
            fs::write(&first_path, "int main(){return 0;}").unwrap();
            let workspace = Arc::new(EditorWorkspace::new(&path).unwrap());
            let first = workspace
                .open(OpenDocument {
                    locator: DocumentLocator::file(&first_path).unwrap(),
                    text: Arc::from(text),
                    client_version: Some(1),
                    project: None,
                })
                .unwrap();
            Self {
                path,
                workspace,
                first,
            }
        }

        fn second(&self) -> crate::DocumentId {
            let path = self.path.join("other.ae");
            fs::write(&path, "int other(){return 1;}").unwrap();
            self.workspace
                .open(OpenDocument {
                    locator: DocumentLocator::file(path).unwrap(),
                    text: Arc::from("int other(){return 1;}"),
                    client_version: Some(1),
                    project: None,
                })
                .unwrap()
        }
    }

    impl Drop for TestWorkspace {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.path);
        }
    }

    fn blocking_observer(
        point: LifecyclePoint,
    ) -> (LifecycleObserver, mpsc::Receiver<()>, mpsc::Sender<()>) {
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let release_rx = Mutex::new(release_rx);
        let observer = Arc::new(move |request: RequestId, seen: LifecyclePoint| {
            if request == RequestId(1)
                && std::mem::discriminant(&seen) == std::mem::discriminant(&point)
            {
                entered_tx.send(()).unwrap();
                release_rx.lock().unwrap().recv().unwrap();
            }
        });
        (observer, entered_rx, release_tx)
    }

    #[test]
    fn request_transitions_reject_double_and_impossible_moves() {
        let mut state = RequestState::Queued;
        state.transition(RequestState::Running).unwrap();
        state.transition(RequestState::Published).unwrap();
        assert!(state.transition(RequestState::Stale).is_err());
        let mut queued = RequestState::Queued;
        assert!(queued.transition(RequestState::Published).is_err());
    }

    #[test]
    fn cancellation_distinguishes_request_from_observation() {
        let token = CancellationToken::new();
        token.cancel();
        assert!(token.is_cancellation_requested());
        assert!(!token.is_cancellation_observed());
        assert_eq!(token.checkpoint(), Err(AnalysisFailure::Cancelled));
        assert!(token.is_cancellation_observed());
    }

    #[test]
    fn request_ids_are_unique_and_different_targets_run_fifo() {
        let test = TestWorkspace::new("int main(){return 0;}");
        let second = test.second();
        let scheduler = AnalysisScheduler::new(Arc::clone(&test.workspace));
        let first = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap();
        let second = scheduler.request(AnalysisTarget::Document(second)).unwrap();
        assert_ne!(first.id(), second.id());
        assert!(first.id() < second.id());
        assert_eq!(first.wait().unwrap().state, RequestState::Published);
        assert_eq!(second.wait().unwrap().state, RequestState::Published);
    }

    #[test]
    fn successive_same_target_cancels_running_request_without_queue_growth() {
        let test = TestWorkspace::new("int main(){return 0;}");
        let (observer, entered, release) = blocking_observer(LifecyclePoint::BeforeAnalysis);
        let scheduler = AnalysisScheduler::new_with_observer(Arc::clone(&test.workspace), observer);
        let first = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap();
        entered.recv().unwrap();
        let second = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap();
        release.send(()).unwrap();
        assert_eq!(first.wait().unwrap().state, RequestState::Cancelled);
        assert_eq!(second.wait().unwrap().state, RequestState::Published);
        assert!(scheduler.measurements().max_pending_requests <= 1);
    }

    #[test]
    fn obsolete_queued_request_is_cancelled_before_it_starts() {
        let test = TestWorkspace::new("int main(){return 0;}");
        let second = test.second();
        let (observer, entered, release) = blocking_observer(LifecyclePoint::BeforeAnalysis);
        let scheduler = AnalysisScheduler::new_with_observer(Arc::clone(&test.workspace), observer);
        let running = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap();
        entered.recv().unwrap();
        let obsolete = scheduler.request(AnalysisTarget::Document(second)).unwrap();
        let current = scheduler.request(AnalysisTarget::Document(second)).unwrap();
        assert_eq!(obsolete.wait().unwrap().state, RequestState::Cancelled);
        release.send(()).unwrap();
        assert_eq!(running.wait().unwrap().state, RequestState::Published);
        assert_eq!(current.wait().unwrap().state, RequestState::Published);
    }

    #[test]
    fn cancellation_after_non_preemptible_work_discards_the_result() {
        let test = TestWorkspace::new("int main(){return 0;}");
        let (observer, entered, release) = blocking_observer(LifecyclePoint::BeforePublication);
        let scheduler = AnalysisScheduler::new_with_observer(Arc::clone(&test.workspace), observer);
        let handle = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap();
        let token = handle.cancellation();
        entered.recv().unwrap();
        token.cancel();
        assert!(token.is_cancellation_requested());
        assert!(!token.is_cancellation_observed());
        release.send(()).unwrap();
        assert_eq!(handle.wait().unwrap().state, RequestState::Cancelled);
        assert!(token.is_cancellation_observed());
    }

    #[test]
    fn edit_and_close_during_analysis_suppress_old_results() {
        let test = TestWorkspace::new("int main(){return 0;}");
        let (observer, entered, release) = blocking_observer(LifecyclePoint::BeforePublication);
        let scheduler = AnalysisScheduler::new_with_observer(Arc::clone(&test.workspace), observer);
        let handle = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap();
        entered.recv().unwrap();
        test.workspace
            .change(crate::ChangeDocument {
                document: test.first,
                text: Arc::from("int main(){return 1;}"),
                client_version: Some(2),
            })
            .unwrap();
        release.send(()).unwrap();
        assert_eq!(handle.wait().unwrap().state, RequestState::Stale);

        let (observer, entered, release) = blocking_observer(LifecyclePoint::BeforePublication);
        let scheduler = AnalysisScheduler::new_with_observer(Arc::clone(&test.workspace), observer);
        let handle = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap();
        entered.recv().unwrap();
        test.workspace.close(test.first).unwrap();
        release.send(()).unwrap();
        assert_eq!(handle.wait().unwrap().state, RequestState::TargetClosed);
    }

    #[test]
    fn external_source_change_is_distinct_from_workspace_staleness() {
        let test = TestWorkspace::new("int main(){return 0;}");
        let imported = test.path.join("alpha.ae");
        fs::write(&imported, "package Alpha; public int value(){return 1;}").unwrap();
        test.workspace
            .change(crate::ChangeDocument {
                document: test.first,
                text: Arc::from("import Alpha; int main(){return Alpha.value();}"),
                client_version: Some(2),
            })
            .unwrap();
        let (observer, entered, release) = blocking_observer(LifecyclePoint::BeforePublication);
        let scheduler = AnalysisScheduler::new_with_observer(Arc::clone(&test.workspace), observer);
        let handle = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap();
        entered.recv().unwrap();
        // This direct write deliberately has no workspace notification.
        fs::write(&imported, "package Alpha; public int value(){return 7;}").unwrap();
        release.send(()).unwrap();
        assert_eq!(handle.wait().unwrap().state, RequestState::SourceChanged);
    }

    #[test]
    fn current_partial_invalid_diagnostics_are_publishable() {
        let test = TestWorkspace::new("int main( { return 0; }");
        let scheduler = AnalysisScheduler::new(Arc::clone(&test.workspace));
        let completion = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap()
            .wait()
            .unwrap();
        assert_eq!(completion.state, RequestState::Published);
        let result = completion.result.unwrap();
        assert_eq!(result.state.validity, crate::AnalysisValidity::Invalid);
        assert!(!result.diagnostics.is_empty());
    }

    #[test]
    fn recovered_panic_does_not_stop_the_next_request() {
        let test = TestWorkspace::new("int main(){return 0;}");
        let observer = Arc::new(|request: RequestId, point: LifecyclePoint| {
            assert!(
                request != RequestId(1) || !matches!(point, LifecyclePoint::BeforeAnalysis),
                "injected recoverable frontend panic"
            );
        });
        let scheduler = AnalysisScheduler::new_with_observer(Arc::clone(&test.workspace), observer);
        let failed = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap()
            .wait()
            .unwrap();
        assert_eq!(failed.state, RequestState::InternalFailure);
        let recovered = scheduler
            .request(AnalysisTarget::Document(test.first))
            .unwrap()
            .wait()
            .unwrap();
        assert_eq!(recovered.state, RequestState::Published);
    }

    #[test]
    fn worker_shutdown_is_orderly_and_rejects_new_work() {
        let test = TestWorkspace::new("int main(){return 0;}");
        let mut scheduler = AnalysisScheduler::new(Arc::clone(&test.workspace));
        assert_eq!(
            scheduler
                .request(AnalysisTarget::Document(test.first))
                .unwrap()
                .wait()
                .unwrap()
                .state,
            RequestState::Published
        );
        scheduler.shutdown();
        assert!(
            scheduler
                .request(AnalysisTarget::Document(test.first))
                .is_err()
        );
    }
}
