import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/processing/processing_screen.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart';

import '../auth/auth_test_harness.dart';

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

  /// Appends entries (e.g. the next state, after a test checks this one).
  void then(List<Object> more) => script.addAll(more);

  @override
  Future<ProcessingStatus> fetchStatus(String jobId) async {
    fetches++;
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

const kJob = 'job-9';
const kTitle = 'Ave Maria';
const kLibrary = 'ROUTE:library';
const kLogin = 'ROUTE:login';

String playbackMarker(int scoreId) => 'ROUTE:playback $scoreId $kTitle';
String retakeMarker(String jobId, int pageIndex) =>
    'ROUTE:retake $jobId $pageIndex';

class ProcessingHarness {
  ProcessingHarness(this.api);

  final ScriptedProcessingApi api;
  final secureStorage = FaultySecureStorage({'session_token': 'sess_t'});
  late WidgetTester _tester;

  /// Owned by the ProviderScope, so unmounting the tree disposes it (and
  /// the poll timers) before the pending-timer check.
  ProviderContainer get container => ProviderScope.containerOf(
    _tester.element(find.byType(MaterialApp)),
    listen: false,
  );

  List<Override> get overrides => [
    processingApiProvider.overrideWithValue(api),
    sessionStorageProvider.overrideWithValue(SessionStorage(secureStorage)),
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
