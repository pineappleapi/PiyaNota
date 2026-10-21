import 'dart:async';

import 'package:clock/clock.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_platform_interface.dart';

import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_failure.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/playback/playback_screen.dart';
import 'package:piyanota_application/services/export_service.dart';
import 'package:piyanota_application/services/metronome_click.dart';
import 'package:piyanota_application/services/playback_engine.dart';
import 'package:piyanota_application/services/score_result_api.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/export_providers.dart';
import 'package:piyanota_application/state/playback_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart';

import '../export/export_fakes.dart' show FakeNotificationPermission;
import '../auth/auth_test_harness.dart';
import '../processing/processing_fakes.dart' show ScriptedProcessingApi;

/// [PlaybackEngine] whose position runs on the test clock (`clock.now`,
/// which `testWidgets` advances with `pump`), at the set speed. Like the
/// real engine it stops at the end of the track (noticed the next time the
/// position is read, which the screen's ticker does every frame), and a
/// play from the end starts again at 0.
class FakePlaybackEngine implements PlaybackEngine {
  FakePlaybackEngine({
    this.trackDuration = const Duration(seconds: 10),
    this.loadError,
    this.failAtLoad = const {},
    this.clickAttachFails = false,
    this.clickAttachGate,
  });

  final Duration trackDuration;

  /// When set, [attachClick] waits for it, holding the click in
  /// "preparing"; completing it with false fails the attach.
  final Completer<bool>? clickAttachGate;
  final Object? loadError;

  /// Voices whose track "fails to load"; the rest load, like the real
  /// engine (unless that is every track, which is a load error).
  final Set<VoicePart> failAtLoad;
  final Set<VoicePart> _unavailable = {};
  final StreamController<bool> _changes = StreamController.broadcast();
  final StreamController<PlaybackFailure> _failures =
      StreamController.broadcast();
  final StreamController<Object> _clickFailures = StreamController.broadcast();

  /// [attachClick] returns false, as if the click track would not load.
  final bool clickAttachFails;

  /// The click track attached, if any, and its last volume.
  Uri? click;
  double clickVolume = 1;
  final List<double> clickVolumes = [];

  /// When set, the next seek is recorded at once but completes only when
  /// this does (to see what the screen shows while a seek is in flight).
  Completer<void>? seekGate;

  /// When set, every seek throws it (after recording).
  Object? seekError;

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
    final failed = failAtLoad.intersection(tracks.keys.toSet());
    if (failed.length == tracks.length) {
      throw const PlaybackLoadException('every track failed');
    }
    _unavailable.addAll(failed);
    loaded = tracks;
  }

  @override
  Set<VoicePart> get unavailableVoices => Set.unmodifiable(_unavailable);

  @override
  Duration get position {
    final started = _startedAt;
    if (started == null) return _anchor;
    final elapsed = clock.now().difference(started) * speed;
    final now = _anchor + elapsed;
    if (now < trackDuration) return now;
    _anchor = trackDuration;
    _startedAt = null;
    _changes.add(false);
    return trackDuration;
  }

  /// A runtime failure of [voice]'s player, as the real engine reports it:
  /// [fatal] when no other voice is left to play, which also stops it.
  void fail(VoicePart voice, {bool fatal = false}) {
    _unavailable.add(voice);
    if (fatal && playing) {
      _anchor = position;
      _startedAt = null;
      _changes.add(false);
    }
    _failures.add(PlaybackFailure(voice, 'test failure', fatal: fatal));
  }

  @override
  Stream<PlaybackFailure> get failures => _failures.stream;

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
    if (position >= trackDuration) _anchor = Duration.zero;
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
    final gate = seekGate;
    seekGate = null;
    if (gate != null) await gate.future;
    if (seekError case final error?) throw error;
    _anchor = position;
    if (playing) _startedAt = clock.now();
  }

  @override
  Future<void> setVolume(VoicePart voice, double volume) async {
    volumes[voice] = volume;
  }

  @override
  Future<void> setSpeed(double speed) async {
    // Keep the position reached so far, like a real speed change.
    if (playing) {
      _anchor = position;
      _startedAt = clock.now();
    }
    this.speed = speed;
  }

  /// Like [JustAudioPlaybackEngine.attachClick]: one click slot, taken
  /// at the start of an attach and freed only by [detachClick] (a failed
  /// attach keeps it, holding the dead player); a failure is also
  /// reported on [clickFailures], unless a detach (or dispose) came first.
  @override
  Future<bool> attachClick(Uri track) async {
    final call = attachCalls.length;
    attachCalls.add(track);
    if (disposed || clickSlotTaken) return false;
    clickSlotTaken = true;
    final key = _clickKey;
    bool gone() => key != _clickKey || disposed;
    bool fail() {
      if (!gone()) _clickFailures.add('test click not attached');
      return false;
    }

    if (clickAttachFails) return fail();
    if (attachGateAt[call] case final gate?) {
      if (!await gate.future) return fail();
    } else if (clickAttachGate case final gate?) {
      if (!await gate.future) return fail();
    }
    if (attachOutcomeAt[call] == false) return fail();
    if (gone()) return false;
    click = track;
    attachedClicks.add(track);
    return true;
  }

  /// A click is attached, being attached, or failed and not yet detached.
  bool clickSlotTaken = false;

  /// Every attachClick call, attached or not.
  final List<Uri> attachCalls = [];

  /// The result of the attachClick call at this index (0 = the first);
  /// a call not listed attaches normally. False fails it like a load
  /// error: reported on [clickFailures], slot kept until a detach.
  final Map<int, bool> attachOutcomeAt = {};

  /// Holds the attachClick call at this index until completed (instead
  /// of [clickAttachGate]).
  final Map<int, Completer<bool>> attachGateAt = {};
  int _clickKey = 0;

  /// Every click track attached, in order (a re-plan attaches another).
  final List<Uri> attachedClicks = [];
  int detachCalls = 0;

  @override
  Future<void> detachClick() async {
    detachCalls++;
    _clickKey++;
    clickSlotTaken = false;
    click = null;
  }

  @override
  Future<void> setClickVolume(double volume) async {
    clickVolume = volume;
    clickVolumes.add(volume);
  }

  @override
  Stream<Object> get clickFailures => _clickFailures.stream;

  /// The click player failed after attaching.
  void failClick() => _clickFailures.add('test click failure');

  @override
  Future<void> dispose() async {
    disposed = true;
    _startedAt = null;
    await _changes.close();
    await _failures.close();
    await _clickFailures.close();
  }
}

/// Answers result fetches from a script: each entry is a [ScoreResult] or
/// a [ScoreResultException] to throw; the last entry repeats.
class ScriptedScoreResultApi implements ScoreResultApi {
  ScriptedScoreResultApi(List<Object> script, {this.timing, this.bars})
    : script = [...script];

  final List<Object> script;
  List<TimingEvent>? timing;

  /// The timing file's measure table (PIYA-117 AC9); none when null.
  List<BarInfo>? bars;
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
  Future<TimingFile> fetchTiming(Uri url) async {
    final events = timing;
    if (events == null) throw const ScoreResultNotFoundException();
    return TimingFile(events: events, bars: bars ?? const []);
  }
}

const kScoreId = 42;
const kTitle = 'Bituin Walang Ningning';
const kArranger = 'Robert Delgado';
const kLibrary = 'ROUTE:library';
const kLogin = 'ROUTE:login';

/// PIYA-207 AC12: Capture opened for a whole-score retake.
String wholeRetakeMarker(WholeRetakeArguments args) =>
    'ROUTE:whole-retake ${args.replacesJobId} ${args.details.title} '
    '${args.details.tempoBpm} ${args.retakeOfScoreId}';

/// The PIYA-102 details a whole-score retake pre-fills from.
const kRetakeDetails = ScoreDetails(title: kTitle, tempoBpm: 90);

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

/// The job [testResult] comes from by default.
const String kJobId = 'job-1';

ScoreResult testResult({
  Set<VoicePart> voices = const {...VoicePart.values},
  bool reviewNeeded = true,
  String? arranger = kArranger,
  int tempoBpm = 90,
  bool tempoKnown = true,
  Set<VoicePart> failedVoices = const {},
  List<MutedMeasure> mutedMeasures = const [],
  String jobId = kJobId,
  Map<VoicePart, VoiceFailureCause> failedVoiceCauses = const {},
}) => ScoreResult(
  scoreId: kScoreId,
  jobId: jobId,
  failedVoiceCauses: failedVoiceCauses,
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
  arranger: arranger,
  tempoBpm: tempoBpm,
  tempoKnown: tempoKnown,
  declaredFailedVoices: failedVoices,
  mutedMeasures: mutedMeasures,
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
    this.engineCreateError,
    this.engineFailAtLoad = const {},
    this.clickAttachFails = false,
    this.clickWriteError,
    this.clickAttachGate,
    this.clickWriter,
    this.exportService,
  });

  /// Replaces the device export channel (PIYA-211).
  final ExportService? exportService;

  /// Replaces the default click writer (which writes nothing).
  final Future<Uri> Function(ClickPlan plan)? clickWriter;

  /// Holds every engine's click in "preparing" until completed (see
  /// [FakePlaybackEngine.clickAttachGate]).
  final Completer<bool>? clickAttachGate;

  final ScriptedScoreResultApi api;
  final Duration engineDuration;
  final Object? engineLoadError;

  /// Voices whose track fails to load (see [FakePlaybackEngine.failAtLoad]).
  final Set<VoicePart> engineFailAtLoad;

  /// Thrown by the engine factory itself (e.g. a missing audio plugin).
  final Object? engineCreateError;
  final bool clickAttachFails;

  /// Thrown by the click track writer.
  final Object? clickWriteError;

  /// Click plans the writer was asked for.
  final List<ClickPlan> clickPlans = [];
  final notifications = FakeNotificationPermission();
  final List<FakePlaybackEngine> engines = [];
  final secureStorage = FaultySecureStorage({'session_token': 'sess_t'});

  FakePlaybackEngine get engine => engines.last;

  List<Override> get overrides => [
    if (exportService case final service?)
      exportServiceProvider.overrideWithValue(service),
    notificationPermissionProvider.overrideWithValue(notifications),
    scoreResultApiProvider.overrideWithValue(api),
    playbackEngineFactoryProvider.overrideWithValue(() {
      if (engineCreateError case final error?) throw error;
      final engine = FakePlaybackEngine(
        trackDuration: engineDuration,
        loadError: engineLoadError,
        failAtLoad: engineFailAtLoad,
        clickAttachFails: clickAttachFails,
        clickAttachGate: clickAttachGate,
      );
      engines.add(engine);
      return engine;
    }),
    clickTrackWriterProvider.overrideWithValue((plan) async {
      clickPlans.add(plan);
      if (clickWriteError case final error?) throw error;
      if (clickWriter case final write?) return write(plan);
      // Not a file, so nothing is written or deleted.
      return Uri.parse('test://click.wav');
    }),
    sessionStorageProvider.overrideWithValue(SessionStorage(secureStorage)),
    // A whole-score retake (PIYA-207 AC12) reads the job's details.
    processingApiProvider.overrideWithValue(
      ScriptedProcessingApi([
        const ProcessingStatus(
          stage: ProcessingStage.complete,
          percentComplete: 100,
          scoreId: kScoreId,
          details: kRetakeDetails,
        ),
      ]),
    ),
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
  Map<String, Object> prefs = const {},
  SharedPreferencesStorePlatform Function(Map<String, Object> values)?
  prefsStore,
}) async {
  final values = <String, Object>{
    'onboarding_completed': true,
    'onboarding_default_voice': ?defaultVoice?.name,
    ...prefs,
  };
  SharedPreferences.setMockInitialValues(values);
  if (prefsStore != null) {
    // After setMockInitialValues, which resets the cached instance.
    SharedPreferencesStorePlatform.instance = prefsStore({
      for (final MapEntry(:key, :value) in values.entries)
        'flutter.$key': value,
    });
  }
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
          AppRoutes.capture: (context) {
            final args =
                ModalRoute.of(context)!.settings.arguments!
                    as WholeRetakeArguments;
            return Scaffold(body: Text(wholeRetakeMarker(args)));
          },
        },
      ),
    ),
  );
  await reopenPlayback(tester);
}

/// Pushes Playback for the test score (again) over the library.
Future<void> reopenPlayback(WidgetTester tester) async {
  unawaited(
    tester
        .state<NavigatorState>(find.byType(Navigator).first)
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
