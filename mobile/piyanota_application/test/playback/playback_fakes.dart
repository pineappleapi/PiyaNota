import 'dart:async';

import 'package:clock/clock.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/playback/playback_screen.dart';
import 'package:piyanota_application/services/playback_engine.dart';
import 'package:piyanota_application/services/score_result_api.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/playback_providers.dart';

import '../auth/auth_test_harness.dart';

/// [PlaybackEngine] whose position runs on the test clock (`clock.now`,
/// which `testWidgets` advances with `pump`), at the set speed.
class FakePlaybackEngine implements PlaybackEngine {
  FakePlaybackEngine({
    this.trackDuration = const Duration(seconds: 10),
    this.loadError,
  });

  final Duration trackDuration;
  final Object? loadError;
  final StreamController<bool> _changes = StreamController.broadcast();

  Map<VoicePart, Uri>? loaded;
  final Map<VoicePart, double> volumes = {};
  final List<Duration> seeks = [];
  int playCalls = 0;
  int pauseCalls = 0;
  double speed = 1;
  bool disposed = false;

  Duration _anchor = Duration.zero;
  DateTime? _startedAt;

  @override
  Future<void> load(Map<VoicePart, Uri> tracks) async {
    if (loadError case final error?) throw PlaybackLoadException(error);
    loaded = tracks;
  }

  @override
  Duration get position {
    final started = _startedAt;
    if (started == null) return _anchor;
    final elapsed = clock.now().difference(started) * speed;
    final now = _anchor + elapsed;
    return now > trackDuration ? trackDuration : now;
  }

  @override
  Duration get duration => trackDuration;

  @override
  bool get playing => _startedAt != null;

  @override
  Stream<bool> get playingChanges => _changes.stream;

  @override
  Future<void> play() async {
    playCalls++;
    if (playing) return;
    _startedAt = clock.now();
    _changes.add(true);
  }

  @override
  Future<void> pause() async {
    pauseCalls++;
    if (!playing) return;
    _anchor = position;
    _startedAt = null;
    _changes.add(false);
  }

  @override
  Future<void> seek(Duration position) async {
    seeks.add(position);
    _anchor = position;
    if (playing) _startedAt = clock.now();
  }

  @override
  Future<void> setVolume(VoicePart voice, double volume) async {
    volumes[voice] = volume;
  }

  @override
  Future<void> setSpeed(double speed) async => this.speed = speed;

  @override
  Future<void> dispose() async {
    disposed = true;
    _startedAt = null;
    await _changes.close();
  }
}

/// Answers result fetches from a script: each entry is a [ScoreResult] or
/// a [ScoreResultException] to throw; the last entry repeats.
class ScriptedScoreResultApi implements ScoreResultApi {
  ScriptedScoreResultApi(List<Object> script, {this.timing})
    : script = [...script];

  final List<Object> script;
  List<TimingEvent>? timing;
  Object? _last;
  int fetches = 0;

  /// When set, the next fetch waits for it (to see the loading state).
  Completer<void>? gate;

  @override
  Future<ScoreResult> fetchResult(int scoreId) async {
    fetches++;
    final wait = gate;
    gate = null;
    if (wait != null) await wait.future;
    final next = script.isNotEmpty ? script.removeAt(0) : _last;
    _last = next;
    if (next is ScoreResultException) throw next;
    if (next is ScoreResult) return next;
    throw StateError('Nothing scripted for $scoreId');
  }

  @override
  Future<List<TimingEvent>> fetchTiming(Uri url) async {
    final events = timing;
    if (events == null) throw const ScoreResultNotFoundException();
    return events;
  }
}

const kScoreId = 42;
const kTitle = 'Bituin Walang Ningning';
const kComposer = 'Robert Delgado';
const kLibrary = 'ROUTE:library';
const kLogin = 'ROUTE:login';

/// Natural size of the test page; the timing x/y are in these pixels.
const kPageWidth = 1000;
const kPageHeight = 1400;

TimingEvent ev(
  int ms,
  double x,
  double y, {
  int? bar,
  VoicePart? voice,
  int? systemIndex,
  double? top,
  double? bottom,
  int page = 0,
}) => TimingEvent(
  timestampMs: ms,
  pageIndex: page,
  x: x,
  y: y,
  voice: voice,
  bar: bar,
  systemIndex: systemIndex,
  systemTopY: top,
  systemBottomY: bottom,
);

/// Two systems on one page, all four voices per onset. Bar 1 starts at
/// 0.5 s (no pickup), the last bar (3) at 3.5 s.
List<TimingEvent> testTiming() {
  final events = <TimingEvent>[];
  void chord(int ms, double x, int bar, int system) {
    final base = system == 0 ? 100.0 : 800.0;
    for (final voice in VoicePart.values) {
      events.add(
        ev(
          ms,
          x,
          base + voice.index * 120,
          bar: bar,
          voice: voice,
          systemIndex: system,
          top: base - 40,
          bottom: base + 3 * 120 + 40,
        ),
      );
    }
  }

  chord(500, 100, 1, 0);
  chord(1500, 300, 1, 0);
  chord(2500, 600, 2, 0);
  chord(3500, 100, 3, 1);
  chord(4500, 400, 3, 1);
  return events;
}

ScoreResult testResult({
  Set<VoicePart> voices = const {...VoicePart.values},
  bool reviewNeeded = true,
  String? composer = kComposer,
}) => ScoreResult(
  scoreId: kScoreId,
  jobId: 'job-1',
  audioTracks: {
    for (final voice in voices)
      voice: Uri.parse('https://cdn.test/${voice.name}.mp3'),
  },
  // No image provider for this scheme: the page lays out from pageSizes
  // without decoding anything in the test.
  scoreImages: [Uri.parse('test://page1.png')],
  timingMetadataUrl: Uri.parse('https://cdn.test/timing.json'),
  review: ReviewSummary(reviewNeeded: reviewNeeded),
  pageSizes: const [Size(1000, 1400)],
  composer: composer,
);

ProviderContainer appContainer(WidgetTester tester) =>
    ProviderScope.containerOf(
      tester.element(find.byType(MaterialApp)),
      listen: false,
    );

class PlaybackHarness {
  PlaybackHarness(
    this.api, {
    this.engineDuration = const Duration(seconds: 10),
    this.engineLoadError,
  });

  final ScriptedScoreResultApi api;
  final Duration engineDuration;
  final Object? engineLoadError;
  final List<FakePlaybackEngine> engines = [];
  final secureStorage = FaultySecureStorage({'session_token': 'sess_t'});

  FakePlaybackEngine get engine => engines.last;

  List<Override> get overrides => [
    scoreResultApiProvider.overrideWithValue(api),
    playbackEngineFactoryProvider.overrideWithValue(() {
      final engine = FakePlaybackEngine(
        trackDuration: engineDuration,
        loadError: engineLoadError,
      );
      engines.add(engine);
      return engine;
    }),
    sessionStorageProvider.overrideWithValue(SessionStorage(secureStorage)),
  ];
}

/// A library stand-in with Playback pushed on top, so leaving can be
/// checked against a real stack. [defaultVoice] is the PIYA-201 choice.
Future<void> pumpPlayback(
  WidgetTester tester,
  PlaybackHarness harness, {
  VoicePart? defaultVoice,
  Size size = const Size(412, 917),
  double textScale = 1,
}) async {
  SharedPreferences.setMockInitialValues({
    'onboarding_completed': true,
    'onboarding_default_voice': ?defaultVoice?.name,
  });
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
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
            return PlaybackScreen(scoreId: args.scoreId, title: args.title);
          },
        },
      ),
    ),
  );
  unawaited(
    tester
        .state<NavigatorState>(find.byType(Navigator))
        .pushNamed(
          AppRoutes.playback,
          arguments: const PlaybackArguments(scoreId: kScoreId, title: kTitle),
        ),
  );
  await settle(tester);
}

/// Lets the load's microtasks and the push transition finish. Not
/// pumpAndSettle: the ticker runs for as long as audio plays.
Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 4; i++) {
    await tester.pump(const Duration(milliseconds: 150));
  }
}
