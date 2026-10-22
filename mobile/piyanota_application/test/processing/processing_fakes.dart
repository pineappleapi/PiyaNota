import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/processing/processing_screen.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/services/scan_tracking_service.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/export_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/scan_job_store.dart';
import 'package:piyanota_application/state/work_owner.dart';

import '../auth/auth_test_harness.dart';
import '../export/export_fakes.dart' show FakeNotificationPermission;

/// [ProcessingApi] that answers polls from a script: each entry is a
/// [ProcessingStatus] or a [ProcessingException] to throw. Once the script
/// runs out the last entry repeats, like a server that stopped changing.
class ScriptedProcessingApi implements ProcessingApi {
  ScriptedProcessingApi([List<Object>? script]) : script = [...?script];

  final List<Object> script;
  Object? _last;
  int fetches = 0;

  /// What cancel does: null succeeds, an exception is thrown.
  ProcessingException? cancelError;

  /// Holds the cancel answer until completed, to see the in-flight state.
  Completer<void>? cancelGate;
  int cancels = 0;

  /// Holds every poll started while set until it completes, to have polls
  /// in flight across a forget/track.
  Completer<void>? fetchGate;

  /// How long each poll takes to answer, e.g. a server that only fails
  /// at the connect timeout.
  Duration fetchDelay = Duration.zero;

  /// Appends entries (e.g. the next state, after a test checks this one).
  void then(List<Object> more) => script.addAll(more);

  @override
  Future<ProcessingStatus> fetchStatus(String jobId) async {
    fetches++;
    if (fetchGate case final gate?) await gate.future;
    if (fetchDelay > Duration.zero) await Future<void>.delayed(fetchDelay);
    final next = script.isNotEmpty ? script.removeAt(0) : _last;
    _last = next;
    if (next is ProcessingException) throw next;
    if (next is ProcessingStatus) return next;
    throw StateError('Nothing scripted for $jobId');
  }

  @override
  Future<void> cancelJob(String jobId) async {
    cancels++;
    await cancelGate?.future;
    if (cancelError case final error?) throw error;
  }
}

ProcessingStatus running(
  int percent, {
  ProcessingStage stage = ProcessingStage.transcribing,
  int? page = 2,
  int? total = 3,
  int? seconds = 120,
}) => ProcessingStatus(
  stage: stage,
  currentPage: page,
  totalPages: total,
  percentComplete: percent,
  estimatedRemainingSeconds: seconds,
);

ProcessingStatus done({int? scoreId = 7}) => ProcessingStatus(
  stage: ProcessingStage.complete,
  currentPage: 3,
  totalPages: 3,
  percentComplete: 100,
  estimatedRemainingSeconds: 0,
  scoreId: scoreId,
);

ProcessingStatus failed(FailureReason reason, {int? pageIndex}) =>
    ProcessingStatus(
      stage: ProcessingStage.failed,
      percentComplete: 30,
      failureReason: reason,
      failedPageIndex: pageIndex,
    );

/// [ScanJobStore] in memory: what the tracker saved, and what a "restart"
/// restores ([stored]).
class MemoryScanJobStore implements ScanJobStore {
  MemoryScanJobStore([this.stored]);

  /// The encoded jobs, as SharedPreferences would hold them.
  String? stored;
  int saves = 0;

  /// Holds [load] until completed, to race a restore against the tracker.
  Completer<void>? loadGate;

  List<TrackedJob> get storedJobs =>
      stored == null ? const [] : ScanJobStore.decodeJobs(stored!);

  @override
  Future<List<TrackedJob>> load() async {
    if (loadGate case final gate?) await gate.future;
    return storedJobs;
  }

  @override
  Future<void> save(String encoded) async {
    saves++;
    stored = encoded;
  }

  @override
  Future<void> clear() async => stored = null;
}

/// Someone is already logged in, so the tracker restores the stored jobs
/// and the scans' service may run (both wait for a login, review M1).
class SignedInAlready extends SignedIn {
  @override
  bool build() => true;
}

/// [WorkOwnerStore] in memory: SharedPreferences has no plugin under
/// widget tests, and its channel call never settles in fake time.
class MemoryWorkOwnerStore implements WorkOwnerStore {
  MemoryWorkOwnerStore([this.owner]);

  int? owner;

  @override
  Future<int?> load() async => owner;

  @override
  Future<void> save(int userId) async => owner = userId;

  @override
  Future<void> clear() async => owner = null;
}

Override signedInOverride() =>
    signedInProvider.overrideWith(SignedInAlready.new);

/// Lets a test switch the phone's network off and on (PIYA-218 AC10).
class FakeNetwork {
  final controller = StreamController<bool>.broadcast();
  int get listeners => controller.hasListener ? 1 : 0;
  void set(bool online) => controller.add(online);

  /// What a one-off connectivity check reports; null means unknown.
  bool? initial;
  Future<bool?> check() async => initial;
}

const kJob = 'job-9';
const kTitle = 'Ave Maria';
const kLibrary = 'ROUTE:library';
const kLogin = 'ROUTE:login';

/// A job left in the tracker by whoever was signed in before.
const kOldJob = 'job-old';

/// The app's container in any test tree with a ProviderScope over a
/// MaterialApp.
ProviderContainer appContainer(WidgetTester tester) =>
    ProviderScope.containerOf(
      tester.element(find.byType(MaterialApp)),
      listen: false,
    );

/// Starts the tracker following [kOldJob] on [api], as if the previous
/// account had a scan running.
Future<void> seedOldJob(WidgetTester tester, ScriptedProcessingApi api) async {
  appContainer(tester).read(processingJobsProvider.notifier).track(kOldJob);
  await tester.pump();
  expect(appContainer(tester).read(processingJobsProvider), contains(kOldJob));
  expect(api.fetches, 1);
}

/// The tracker is empty and nothing polls any more.
Future<void> expectTrackerCleared(
  WidgetTester tester,
  ScriptedProcessingApi api,
) async {
  expect(appContainer(tester).read(processingJobsProvider), isEmpty);
  final fetches = api.fetches;
  await tester.pump(ProcessingTiming.pollInterval * 3);
  expect(api.fetches, fetches, reason: 'old jobs must stop polling');
}

String playbackMarker(int scoreId) => 'ROUTE:playback $scoreId $kTitle';

/// PIYA-207 AC12: Capture opened for a whole-score retake.
String wholeRetakeMarker(WholeRetakeArguments args) =>
    'ROUTE:whole-retake ${args.replacesJobId} ${args.details.title} '
    '${args.details.tempoBpm} ${args.retakeOfScoreId}';

String retakeMarker(String jobId, int pageIndex) =>
    'ROUTE:retake $jobId $pageIndex';

class ProcessingHarness {
  ProcessingHarness(this.api);

  final ScriptedProcessingApi api;
  final store = MemoryScanJobStore();
  final network = FakeNetwork();
  final secureStorage = FaultySecureStorage({'session_token': 'sess_t'});
  final scans = FakeScanTrackingService();
  final notifications = FakeNotificationPermission();
  final owners = MemoryWorkOwnerStore();
  late WidgetTester _tester;

  /// Owned by the ProviderScope, so unmounting the tree disposes it (and
  /// the poll timers) before the pending-timer check.
  ProviderContainer get container => appContainer(_tester);

  List<Override> get overrides => [
    processingApiProvider.overrideWithValue(api),
    sessionStorageProvider.overrideWithValue(SessionStorage(secureStorage)),
    scanJobStoreProvider.overrideWithValue(store),
    networkAvailabilityProvider.overrideWithValue(network.controller.stream),
    networkCheckProvider.overrideWithValue(network.check),
    scanTrackingServiceProvider.overrideWithValue(scans),
    notificationPermissionProvider.overrideWithValue(notifications),
    signedInOverride(),
    workOwnerStoreProvider.overrideWithValue(owners),
  ];

  TrackedJob? get job => container.read(processingJobsProvider)[kJob];
}

/// A library stand-in with Processing pushed on top, so leaving can be
/// checked against a real stack.
Future<void> pumpProcessing(
  WidgetTester tester,
  ProcessingHarness harness, {
  Size size = const Size(412, 917),
  double textScale = 1,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  harness._tester = tester;
  await tester.pumpWidget(
    ProviderScope(
      overrides: harness.overrides,
      child: MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: TextScaler.linear(textScale)),
          child: child!,
        ),
        initialRoute: AppRoutes.scoreLibrary,
        routes: {
          AppRoutes.scoreLibrary: (_) => const Scaffold(body: Text(kLibrary)),
          AppRoutes.login: (_) => const Scaffold(body: Text(kLogin)),
          AppRoutes.playback: (context) {
            final args =
                ModalRoute.of(context)!.settings.arguments!
                    as PlaybackArguments;
            return Scaffold(
              body: Text('ROUTE:playback ${args.scoreId} ${args.title}'),
            );
          },
          AppRoutes.captureRetake: (context) {
            final args =
                ModalRoute.of(context)!.settings.arguments!
                    as CaptureRetakeArguments;
            return Scaffold(
              body: Text(retakeMarker(args.jobId, args.pageIndex)),
            );
          },
          AppRoutes.capture: (context) {
            final args =
                ModalRoute.of(context)!.settings.arguments!
                    as WholeRetakeArguments;
            return Scaffold(body: Text(wholeRetakeMarker(args)));
          },
          AppRoutes.processing: (context) {
            final args =
                ModalRoute.of(context)!.settings.arguments!
                    as ProcessingArguments;
            return ProcessingScreen(jobId: args.jobId, title: args.title);
          },
        },
      ),
    ),
  );
  tester
      .state<NavigatorState>(find.byType(Navigator))
      .pushNamed(
        AppRoutes.processing,
        arguments: const ProcessingArguments(jobId: kJob, title: kTitle),
      );
  // Push transition, the first poll, and the percent tween.
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
  await tester.pump(const Duration(milliseconds: 700));
}

/// Records what the tracker asked of the device (PIYA-218 background
/// following); [tap] plays a tapped result notification.
class FakeScanTrackingService implements ScanTrackingService {
  final List<String> shown = [];
  int stops = 0;
  int stopAllCalls = 0;
  final List<({String jobId, String title, String text, bool ok})> results = [];
  final List<String> cleared = [];
  final StreamController<String> _opened = StreamController.broadcast();
  final StreamController<void> _stopped = StreamController.broadcast();

  void tap(String jobId) => _opened.add(jobId);

  /// The native side's own stop (timeout, refused start).
  void stopByItself() => _stopped.add(null);

  @override
  Stream<String> get opened => _opened.stream;

  @override
  Stream<void> get stopped => _stopped.stream;

  @override
  Future<void> show(String text) async => shown.add(text);

  @override
  Future<void> stop() async => stops++;

  @override
  Future<void> notifyResult({
    required String jobId,
    required String title,
    required String text,
    required bool ok,
  }) async => results.add((jobId: jobId, title: title, text: text, ok: ok));

  @override
  Future<void> clearResult(String jobId) async => cleared.add(jobId);

  @override
  Future<void> stopAll() async => stopAllCalls++;
}
