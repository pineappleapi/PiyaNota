import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:audio_session/audio_session.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../config/api_config.dart';
import '../models/measure_table.dart';
import '../models/score_details.dart';
import '../models/score_result.dart';
import '../models/score_timeline.dart';
import '../models/voice_part.dart';
import '../services/fake_score_library_api.dart';
import '../services/fake_score_result_api.dart';
import '../services/local_results_store.dart';
import '../services/metronome_click.dart';
import '../services/midi_render_cache.dart';
import '../services/live_synth_engine.dart';
import '../services/midi_synth.dart' show ensureSoundfont;
import '../services/playback_engine.dart';
import '../services/score_result_api.dart';
import 'auth_providers.dart';
import 'onboarding_providers.dart';
import 'processing_providers.dart';
import 'score_library_providers.dart';

/// F10: where converted results are kept. Application support, not the temp
/// folder, which the system may clear; excluded from backup by
/// data_extraction_rules.xml (domain `file`) and allowBackup=false.
final localResultsStoreProvider = Provider<LocalResultsStore>(
  (ref) => LocalResultsStore(
    rootProvider: () async {
      final support = await getApplicationSupportDirectory();
      return Directory('${support.path}${Platform.pathSeparator}results');
    },
    downloader: DioFileDownloader(ref.watch(dioProvider)),
  ),
);

/// PIYA-103. Fake until Module 3 is deployed, under the same flag as the
/// other fakes.
final scoreResultApiProvider = Provider<ScoreResultApi>((ref) {
  final sessionStorage = ref.watch(sessionStorageProvider);
  if (ApiConfig.useFakeAuth) {
    final library = ref.watch(scoreLibraryApiProvider);
    return FakeScoreResultApi(
      sessionStorage: sessionStorage,
      accountForToken: ref.watch(fakeAuthApiProvider).accountForToken,
      library: library is FakeScoreLibraryApi
          ? library
          : throw StateError('Fake result needs the fake library'),
      processing: ref.watch(fakeProcessingApiProvider),
    );
  }
  final configError = ApiConfig.configurationError();
  if (configError != null) throw StateError(configError);
  return LocalFirstScoreResultApi(
    HttpScoreResultApi(ref.watch(dioProvider), sessionStorage),
    ref.watch(localResultsStoreProvider),
  );
});

/// Makes a fresh engine per opened score; tests override it with a fake.
final playbackEngineFactoryProvider = Provider<PlaybackEngine Function()>(
  (ref) =>
      () => JustAudioPlaybackEngine(audioSession: AudioSession.instance),
);

/// Writes the metronome click track; tests override it with a fake (or a
/// failure).
final clickTrackWriterProvider = Provider<ClickTrackWriter>(
  (ref) => writeClickTrack,
);

/// Builds the one-clock live-synth file for the combined MIDI at [bpm]; null
/// means the live path is unusable and the caller renders WAVs instead.
/// Tests override it (the default needs the Android native library).
typedef LiveFileMaker = Future<LiveRender?> Function(
  ScoreResult result,
  List<BarInfo> bars,
  int bpm,
);

final liveFileMakerProvider = Provider<LiveFileMaker>((ref) {
  if (!Platform.isAndroid) return (_, _, _) async => null;
  final cache = MidiRenderCache(
    rootDir: () async {
      final support = await getApplicationSupportDirectory();
      return Directory('${support.path}/render_cache')
        ..createSync(recursive: true);
    },
    tempDir: getTemporaryDirectory,
    soundfont: ensureSoundfont,
  );
  final downloader = DioFileDownloader(ref.watch(dioProvider));
  return (result, bars, bpm) async {
    String? downloaded;
    try {
      return await cache.liveFile(
        result,
        bars: bars,
        bpm: bpm,
        midiPath: () async {
          final url = result.midiCombined!.url;
          if (url.scheme == 'file') return url.toFilePath();
          final temp = await getTemporaryDirectory();
          final path = '${temp.path}/combined_live_${result.scoreId}.mid';
          downloaded = path;
          await downloader.download(url, path);
          return path;
        },
      );
    } finally {
      final d = downloaded;
      if (d != null && File(d).existsSync()) File(d).deleteSync();
    }
  };
});

/// The engine that plays a [LiveRender] through one synth; tests override it.
final liveEngineFactoryProvider = Provider<PlaybackEngine Function(LiveRender)>(
  (ref) =>
      (live) => LiveSynthPlaybackEngine(
        sf2Path: live.sf2,
        midPath: live.midi.toFilePath(),
        bpm: live.bpm,
        audioSession: AudioSession.instance,
      ),
);

enum PlaybackPhase { loading, ready, failed }

/// What the voice tracks were made from: WAVs rendered on the phone from the
/// combined MIDI, or the server's MP3s (also the fallback for any render
/// problem).
enum PlaybackSource { midi, mp3 }

/// Renders the four voices from the result's combined MIDI; null means play
/// the MP3s. Tests override it.
typedef MidiVoiceRenderer = Future<MidiRender?> Function(
  ScoreResult result,
  List<BarInfo> bars,
  int bpm,
);

final midiVoiceRendererProvider = Provider<MidiVoiceRenderer>((ref) {
  final cache = MidiRenderCache(
    rootDir: () async {
      final support = await getApplicationSupportDirectory();
      return Directory('${support.path}/render_cache')
        ..createSync(recursive: true);
    },
    tempDir: getTemporaryDirectory,
    soundfont: ensureSoundfont,
  );
  final downloader = DioFileDownloader(ref.watch(dioProvider));
  return (result, bars, bpm) async {
    String? downloaded;
    try {
      return await cache.renderVoices(
        result,
        bars: bars,
        bpm: bpm,
        midiPath: () async {
          final url = result.midiCombined!.url;
          if (url.scheme == 'file') return url.toFilePath();
          final temp = await getTemporaryDirectory();
          final path = '${temp.path}/combined_${result.scoreId}.mid';
          downloaded = path;
          await downloader.download(url, path);
          return path;
        },
      );
    } finally {
      final d = downloaded;
      if (d != null && File(d).existsSync()) File(d).deleteSync();
    }
  };
});

/// The app-made metronome click track (PIYA-209/210).
enum ClickStatus {
  /// Being generated and loaded after the voices. The controls already
  /// work; their settings apply once it is ready.
  preparing,
  ready,

  /// Could not be generated or played. Playback carries on without it and
  /// the metronome controls are disabled with a short note.
  unavailable,
}

/// Why Playback couldn't open the score. Each has its own wording and
/// action (FR-14), so none of them reads as a generic failure.
enum PlaybackError {
  /// 409: still being converted. Retry later.
  notReady,

  /// 404: gone, or not this account's.
  notFound,

  /// No connection. Retry once back online.
  network,

  /// Server error or an unusable response.
  server,

  /// The result loaded but the audio wouldn't.
  audio,

  /// 401: the screen sends the user to Login.
  sessionExpired,
}

@immutable
class PlaybackState {
  const PlaybackState({
    this.phase = PlaybackPhase.loading,
    this.error,
    this.result,
    this.timeline,
    this.arranger,
    this.selected = const {},
    this.volumes = const {},
    this.muted = const {},
    this.clickVolume = PlaybackController.defaultClickVolume,
    this.clickMuted = false,
    this.metronomeOn = false,
    this.clickStatus = ClickStatus.preparing,
    this.bpm,
    this.playing = false,
    this.duration = Duration.zero,
    this.reviewDismissed = false,
    this.timingUnavailable = false,
    this.failedVoices = const {},
    this.source = PlaybackSource.mp3,
  });

  final PlaybackPhase phase;

  /// Where the loaded voice audio came from.
  final PlaybackSource source;
  final PlaybackError? error;
  final ScoreResult? result;
  final ScoreTimeline? timeline;
  final String? arranger;

  /// Voices the user hears (AC2). Never empty once ready.
  final Set<VoicePart> selected;

  /// Per-voice slider level in the Voice Mixer (PIYA-209), 0 to 1. Kept
  /// as set while muted, so unmuting restores it (AC4). What is heard is
  /// [voiceGain].
  final Map<VoicePart, double> volumes;

  /// Mixer Mute per voice; independent of the slider (AC2).
  final Set<VoicePart> muted;

  /// The Mixer's Metronome Click row: level and Mute. Whether the click
  /// plays at all is [metronomeOn], the Speed modal's toggle, which the
  /// row's checkbox also drives.
  final double clickVolume;
  final bool clickMuted;

  /// The Speed modal's Metronome Click checkbox (PIYA-210 AC3); off by
  /// default.
  final bool metronomeOn;
  final ClickStatus clickStatus;

  /// The Speed modal's BPM (PIYA-210), 30 to 180; null until loaded. Read
  /// it through [chosenBpm].
  final int? bpm;
  final bool playing;
  final Duration duration;

  /// The review banner was closed; lasts as long as this screen.
  final bool reviewDismissed;

  /// The timing file failed to load: the audio plays, but there is no
  /// position indicator. The screen says so once, quietly.
  final bool timingUnavailable;

  /// Voices that can't play: failed on the server (PIYA-103 AC10
  /// `failedVoices`, or missing from `audioTracks`, PIYA-216 AC5), failed
  /// to load on the device, or dropped out mid-play. The others keep
  /// playing (user decision 2026-10-09); these chips and Mixer rows are
  /// disabled and the screen names them in the failed-voice alert.
  final Set<VoicePart> failedVoices;

  /// Voices that can be heard: in the result, and not failed.
  Set<VoicePart> get available =>
      {...?result?.playableVoices}.difference(failedVoices);

  /// The score's own tempo (PIYA-103 AC8), 90 until loaded.
  int get tempoBpm => result?.tempoBpm ?? ScoreDetails.defaultTempo;

  /// The Speed slider's value; opens at [tempoBpm].
  int get chosenBpm => bpm ?? tempoBpm;

  /// Playback rate: chosen BPM / the tempo the tracks were rendered at.
  double get speed => chosenBpm / tempoBpm;

  /// The metronome is off for good because the server gave no tempo (see
  /// ScoreResult.tempoKnown); the sheets say so instead of the generic note.
  bool get clickNeedsTempo => !(result?.tempoKnown ?? true);

  /// The click can sound: the Speed toggle is on and the track is loaded.
  bool get clickLive => metronomeOn && clickStatus == ClickStatus.ready;

  /// What [voice] is played at: silent if it can't play, its chip is off
  /// (the Mixer checkbox is the same state), or it is muted; else its slider
  /// level.
  double voiceGain(VoicePart voice) {
    if (!available.contains(voice) ||
        !selected.contains(voice) ||
        muted.contains(voice)) {
      return 0;
    }
    return volumes[voice] ?? PlaybackController.defaultVoiceVolume;
  }

  /// The click: only while it is live (Speed toggle on, track loaded) and
  /// not muted; then the Metronome row's level.
  double get clickGain {
    if (!clickLive || clickMuted) {
      return 0;
    }
    return clickVolume;
  }

  bool get showReviewBanner =>
      phase == PlaybackPhase.ready &&
      !reviewDismissed &&
      (result?.review.reviewNeeded ?? false);

  PlaybackState copyWith({
    PlaybackPhase? phase,
    PlaybackError? error,
    bool clearError = false,
    ScoreResult? result,
    ScoreTimeline? timeline,
    String? arranger,
    Set<VoicePart>? selected,
    Map<VoicePart, double>? volumes,
    Set<VoicePart>? muted,
    double? clickVolume,
    bool? clickMuted,
    bool? metronomeOn,
    ClickStatus? clickStatus,
    int? bpm,
    bool? playing,
    Duration? duration,
    bool? reviewDismissed,
    Set<VoicePart>? failedVoices,
    PlaybackSource? source,
  }) => PlaybackState(
    phase: phase ?? this.phase,
    error: clearError ? null : error ?? this.error,
    result: result ?? this.result,
    timeline: timeline ?? this.timeline,
    arranger: arranger ?? this.arranger,
    selected: selected ?? this.selected,
    volumes: volumes ?? this.volumes,
    muted: muted ?? this.muted,
    clickVolume: clickVolume ?? this.clickVolume,
    clickMuted: clickMuted ?? this.clickMuted,
    metronomeOn: metronomeOn ?? this.metronomeOn,
    clickStatus: clickStatus ?? this.clickStatus,
    bpm: bpm ?? this.bpm,
    playing: playing ?? this.playing,
    duration: duration ?? this.duration,
    reviewDismissed: reviewDismissed ?? this.reviewDismissed,
    timingUnavailable: timingUnavailable,
    failedVoices: failedVoices ?? this.failedVoices,
    source: source ?? this.source,
  );
}

/// One opened score's playback, keyed by `scoreId`. autoDispose, so
/// leaving Playback disposes the engine and the audio stops with it.
final playbackControllerProvider = NotifierProvider.autoDispose
    .family<PlaybackController, PlaybackState, int>(PlaybackController.new);

/// Per-score Playback memory kept on the device, keyed by score id: the
/// disclaimer-seen flag and the last mixer / speed. A storage failure reads
/// as "nothing saved" and a failed save is only logged.
class PlaybackPrefs {
  const PlaybackPrefs._();

  static const String disclaimerPrefix = 'playback_disclaimer_seen_';
  static const String mixPrefix = 'playback_mix_';

  @visibleForTesting
  static String disclaimerKey(int scoreId) => '$disclaimerPrefix$scoreId';
  @visibleForTesting
  static String mixKey(int scoreId) => '$mixPrefix$scoreId';

  static Future<bool> disclaimerSeen(int scoreId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool(disclaimerKey(scoreId)) ?? false;
    } on Object catch (e) {
      debugPrint('Playback: disclaimer flag unread: $e');
      return false;
    }
  }

  static Future<void> markDisclaimerSeen(int scoreId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(disclaimerKey(scoreId), true);
    } on Object catch (e) {
      debugPrint('Playback: disclaimer flag not saved: $e');
    }
  }

  static Future<Map<String, dynamic>?> loadMix(int scoreId) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final text = prefs.getString(mixKey(scoreId));
      if (text == null) return null;
      final data = jsonDecode(text);
      return data is Map<String, dynamic> ? data : null;
    } on Object catch (e) {
      debugPrint('Playback: saved mix unread: $e');
      return null;
    }
  }

  static Future<void> saveMix(int scoreId, Map<String, dynamic> mix) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(mixKey(scoreId), jsonEncode(mix));
    } on Object catch (e) {
      debugPrint('Playback: mix not saved: $e');
    }
  }
}

class PlaybackController extends Notifier<PlaybackState> {
  PlaybackController(this.scoreId);

  final int scoreId;

  /// ⟲5 / ⟳5 (user decision 2026-10-09).
  static const Duration skipStep = Duration(seconds: 5);
  static const double fullVolume = 1;

  /// Slider defaults (F8c): voices leave headroom, the click starts at half.
  static const double defaultVoiceVolume = 0.8;
  static const double defaultClickVolume = 0.5;

  PlaybackEngine? _engine;
  StreamSubscription<bool>? _playingSub;
  StreamSubscription<PlaybackFailure>? _failureSub;
  StreamSubscription<Object>? _clickFailureSub;

  /// The generated click file of the current engine; deleted with it.
  Uri? _clickFile;

  /// The timing file's measure table (PIYA-117 AC9); empty without one.
  List<BarInfo> _bars = const [];

  /// [subdividedBars] the current click was planned for. A speed change
  /// that leaves it the same only rescales the click (the engine's speed
  /// does that); one that changes it re-plans (PIYA-210 "Speed changes").
  Set<int>? _plannedSubdivisions;

  /// Voices muted only by the default mix (V2.2); a hand-set mute leaves it.
  Set<VoicePart> _mixMuted = {};

  /// A click plan is being written or attached (see [_prepareClick]).
  bool _clickBusy = false;

  /// A slider release arrived while [_clickBusy]; re-checked after.
  bool _replanPending = false;

  /// A re-plan is swapping the engine's click (see [_onClickFailure]).
  bool _clickSwapping = false;

  /// Gains last sent to the current engine, by voice or [_clickGainKey],
  /// so a slider drag only sends what changed.
  final Map<Object, double> _sentGains = {};
  static const Object _clickGainKey = #click;

  /// Bumped by every load, so a slow earlier load can't overwrite a newer
  /// one (Retry pressed twice, or the screen left mid-load).
  int _generation = 0;

  @override
  PlaybackState build() {
    ref.onDispose(() {
      _generation++;
      _releaseEngine();
    });
    Future.microtask(_load);
    return const PlaybackState();
  }

  /// The audio position, read every frame by the screen's ticker. Zero
  /// until loaded.
  Duration get position => _engine?.position ?? Duration.zero;

  /// After an error. Back to the loading state, never stale error + spinner.
  Future<void> retry() async {
    if (state.phase == PlaybackPhase.loading) return;
    state = const PlaybackState();
    await _load();
  }

  Future<void> _load() async {
    final generation = ++_generation;
    bool current() => ref.mounted && generation == _generation;
    _releaseEngine();
    final ScoreResultApi api;
    final ScoreResult result;
    try {
      api = ref.read(scoreResultApiProvider);
      result = await api.fetchResult(scoreId);
    } on ScoreResultException catch (e) {
      if (current()) _fail(_errorFor(e));
      return;
    } on Object catch (e, stack) {
      // Not a typed API failure: a misconfigured build (StateError from
      // the provider), an unreadable token (PlatformException), a bug.
      // Shown as the server error, never an endless spinner.
      debugPrint('Playback: result load failed: $e\n$stack');
      if (current()) _fail(PlaybackError.server);
      return;
    }
    if (!current()) return;

    final (timeline, bars, timingFailed) = await _loadTimeline(api, result);
    if (!current()) return;

    PlaybackEngine? engine;
    var source = PlaybackSource.mp3;
    var clickAttached = false;
    try {
      MidiRender? rendered;
      if (result.midiCombined != null) {
        // One synth, one clock: tried first; any failure renders WAVs.
        engine = await _openLiveEngine(result, bars, result.tempoBpm);
        if (!current()) {
          await _disposeQuietly(engine);
          return;
        }
        if (engine != null) {
          source = PlaybackSource.midi;
          clickAttached = bars.isNotEmpty;
        }
      }
      if (engine == null && result.midiCombined != null) {
        try {
          rendered = await ref.read(midiVoiceRendererProvider)(
            result,
            bars,
            result.tempoBpm,
          );
        } on Object catch (e) {
          debugPrint('Playback: MIDI render failed, using MP3: $e');
        }
        if (!current()) return;
      }
      if (rendered != null) {
        // Only the voices the result has audio for, so the mixer keys match.
        final wavs = {
          for (final v in result.playableVoices)
            if (rendered.voices[v] != null) v: rendered.voices[v]!,
        };
        try {
          engine = ref.read(playbackEngineFactoryProvider)();
          await engine.load(wavs);
          source = PlaybackSource.midi;
          final renderedClick = rendered.click;
          clickAttached =
              renderedClick != null && await engine.attachClick(renderedClick);
        } on Object catch (e) {
          debugPrint('Playback: rendered WAVs failed, using MP3: $e');
          await _disposeQuietly(engine);
          engine = null;
        }
      }
      if (engine == null) {
        engine = ref.read(playbackEngineFactoryProvider)();
        // Throws only if no voice at all loads; a voice that didn't is in
        // unavailableVoices and the rest still play.
        await engine.load(result.audioTracks);
      }
    } on Object catch (e, stack) {
      debugPrint('Playback: audio failed to load: $e\n$stack');
      await _disposeQuietly(engine);
      if (current()) _fail(PlaybackError.audio);
      return;
    }
    if (!current()) {
      await _disposeQuietly(engine);
      return;
    }

    final failedVoices = {...result.failedVoices, ...engine.unavailableVoices};
    final playable = result.playableVoices.difference(failedVoices);
    final selected = await _defaultSelection(playable);
    if (!current()) {
      await _disposeQuietly(engine);
      return;
    }
    _bars = bars;
    _renderedBpm = result.tempoBpm;
    timeline.audioToScore = 1; // rendered at the score tempo (or MP3)
    _wireEngine(engine);
    // PIYA-209-V2.2 replaces 209 AC5: voice sliders at 0.8, click at 0.5,
    // metronome off, speed at the score's tempo; the voices the
    // default selection left out start muted so the Mixer shows what is
    // heard. A fresh controller (autoDispose) means a reopened score starts
    // here until a saved mix is restored (mix/speed persist per score, user
    // decision 2026-11-09, supersedes 209 AC6).
    _mixMuted = playable.difference(selected);
    final volumes = {
      for (final voice in result.playableVoices) voice: defaultVoiceVolume,
    };
    state = PlaybackState(
      phase: PlaybackPhase.ready,
      result: result,
      timeline: timeline,
      arranger: result.arranger ?? _libraryArranger(),
      selected: selected,
      volumes: volumes,
      muted: {..._mixMuted},
      duration: engine.duration,
      timingUnavailable: timingFailed,
      failedVoices: failedVoices,
      source: source,
      bpm: result.tempoBpm,
      // No tempo, no grid to lay the click on (coordinator decision
      // 2026-10-09); the slider still runs relative to the assumed 90.
      clickStatus: !result.tempoKnown
          ? ClickStatus.unavailable
          : source == PlaybackSource.midi
          ? (clickAttached ? ClickStatus.ready : ClickStatus.unavailable)
          : ClickStatus.preparing,
    );
    final savedMix = await PlaybackPrefs.loadMix(scoreId);
    if (!current()) {
      await _disposeQuietly(engine);
      return;
    }
    _restoreMix(savedMix, playable);

    /// Sends every gain that changed, all started at once (never one
    /// awaited after another), so a slider change reaches the engine in the
    /// same frame.
    _applyGains();
    // Speed must reach the engine too, not only the slider (MIDI re-renders).
    if (state.chosenBpm != result.tempoBpm) commitBpm();
    // The MIDI path's click is a rendered WAV, already attached; the
    // generated click only serves the time-stretched MP3 path.
    if (result.tempoKnown && source == PlaybackSource.mp3) {
      unawaited(_prepareClick(engine, generation));
    }
  }

  void _wireEngine(PlaybackEngine engine) {
    _engine = engine;
    _plannedSubdivisions = null;
    _playingSub = engine.playingChanges.listen((playing) {
      if (ref.mounted) state = state.copyWith(playing: playing);
    });
    _failureSub = engine.failures.listen(_onFailure);
    _clickFailureSub = engine.clickFailures.listen(_onClickFailure);
  }

  /// The live-synth engine for [result] at [bpm], loaded and with its click
  /// attached, or null when it cannot be used (not Android, native library
  /// or audio output failing): the caller then renders WAVs.
  Future<PlaybackEngine?> _openLiveEngine(
    ScoreResult result,
    List<BarInfo> bars,
    int bpm,
  ) async {
    PlaybackEngine? engine;
    try {
      final live = await ref.read(liveFileMakerProvider)(result, bars, bpm);
      if (live == null) return null;
      engine = ref.read(liveEngineFactoryProvider)(live);
      await engine.load({for (final v in result.playableVoices) v: live.midi});
      if (bars.isNotEmpty) await engine.attachClick(live.midi);
      return engine;
    } on Object catch (e) {
      debugPrint('Playback: live synth unavailable, rendering WAVs: $e');
      await _disposeQuietly(engine);
      return null;
    }
  }

  /// The bpm the current MIDI-rendered audio was made at.
  int _renderedBpm = 0;
  bool _rerendering = false;
  bool _rerenderPending = false;

  /// MIDI path: re-renders every voice and the click at the chosen bpm and
  /// swaps them in, keeping the musical position. Never time-stretches
  /// (chops at extreme speeds). Any failure falls back to the stretched MP3
  /// path, which is what old scores use.
  Future<void> _rerender() async {
    if (_rerendering) {
      _rerenderPending = true;
      return;
    }
    final result = state.result;
    final old = _engine;
    final bpm = state.chosenBpm;
    if (result == null || old == null || bpm == _renderedBpm) return;
    _rerendering = true;
    final generation = _generation;
    bool current() => ref.mounted && generation == _generation;
    // Paused for the render (about a second or two): playing on while the
    // new voices render left the old ones running, and the swap then
    // started the new ones from a position read after that drift.
    final wasPlaying = state.playing;
    if (wasPlaying) await old.pause();
    var swappedOk = false;
    try {
      final liveFile = await _liveFileOrNull(result, bpm);
      if (!current()) return;
      if (liveFile != null &&
          await _swapEngine(
            {for (final v in result.playableVoices) v: liveFile.midi},
            click: _bars.isEmpty ? null : liveFile.midi,
            live: liveFile,
            position: Duration(
              microseconds: (old.position.inMicroseconds * _renderedBpm / bpm)
                  .round(),
            ),
            speed: 1,
            source: PlaybackSource.midi,
            renderedBpm: bpm,
            resume: wasPlaying,
          )) {
        swappedOk = true;
        return;
      }
      if (!current()) return;
      MidiRender? rendered;
      try {
        rendered = await ref.read(midiVoiceRendererProvider)(
          result,
          _bars,
          bpm,
        );
      } on Object catch (e) {
        debugPrint('Playback: MIDI re-render failed: $e');
      }
      if (!current()) return;
      final voices = rendered == null
          ? null
          : {
              for (final v in result.playableVoices)
                if (rendered.voices[v] != null) v: rendered.voices[v]!,
            };
      final position = Duration(
        microseconds: (old.position.inMicroseconds * _renderedBpm / bpm)
            .round(),
      );
      final swapped =
          voices != null &&
          await _swapEngine(
            voices,
            click: rendered!.click,
            position: position,
            speed: 1,
            source: PlaybackSource.midi,
            renderedBpm: bpm,
            resume: wasPlaying,
          );
      if (!current()) return;
      if (swapped) {
        swappedOk = true;
        return;
      }
      // Fallback keeps the old engine's musical position: it is still at
      // the old tempo, so [position] (new tempo) is not used for MP3.
      final mp3Position = Duration(
        microseconds:
            (old.position.inMicroseconds * _renderedBpm / result.tempoBpm)
                .round(),
      );
      final fell = await _swapEngine(
        result.audioTracks,
        position: mp3Position,
        speed: state.speed,
        source: PlaybackSource.mp3,
        resume: wasPlaying,
      );
      swappedOk = fell;
      final engine = _engine;
      if (fell && current() && result.tempoKnown && engine != null) {
        state = state.copyWith(clickStatus: ClickStatus.preparing);
        unawaited(_prepareClick(engine, _generation));
      }
    } finally {
      // Neither swap took: the old engine is still the one in use.
      if (!swappedOk && wasPlaying && current()) unawaited(old.play());
      _rerendering = false;
      if (_rerenderPending) {
        _rerenderPending = false;
        if (ref.mounted) unawaited(_rerender());
      }
    }
  }

  Future<LiveRender?> _liveFileOrNull(ScoreResult result, int bpm) async {
    try {
      return await ref.read(liveFileMakerProvider)(result, _bars, bpm);
    } on Object catch (e) {
      debugPrint('Playback: live file failed: $e');
      return null;
    }
  }

  /// Loads [tracks] into a new engine, brings it to [position] (and playing
  /// if the old one was), then replaces the old engine. The old engine is
  /// untouched when anything fails, so false leaves playback as it was.
  Future<bool> _swapEngine(
    Map<VoicePart, Uri> tracks, {
    Uri? click,
    required Duration position,
    required double speed,
    required PlaybackSource source,
    int? renderedBpm,
    bool? resume,
    LiveRender? live,
  }) async {
    final old = _engine;
    if (old == null) return false;
    final generation = _generation;
    final wasPlaying = resume ?? state.playing;
    PlaybackEngine? fresh;
    try {
      fresh = live != null
          ? ref.read(liveEngineFactoryProvider)(live)
          : ref.read(playbackEngineFactoryProvider)();
      await fresh.load(tracks);
      var clickOk = false;
      if (click != null) clickOk = await fresh.attachClick(click);
      if (speed != 1) await fresh.setSpeed(speed);
      await fresh.seek(position);
      if (!ref.mounted || generation != _generation) {
        await _disposeQuietly(fresh);
        return false;
      }
      if (wasPlaying) await old.pause();
      unawaited(_playingSub?.cancel());
      unawaited(_failureSub?.cancel());
      unawaited(_clickFailureSub?.cancel());
      final oldClickFile = _clickFile;
      _clickFile = null;
      _clickBusy = false;
      _clickSwapping = false;
      _replanPending = false;
      _sentGains.clear();
      _wireEngine(fresh);
      if (renderedBpm != null) _renderedBpm = renderedBpm;
      state = state.copyWith(
        source: source,
        duration: fresh.duration,
        clickStatus: source == PlaybackSource.midi
            ? (clickOk ? ClickStatus.ready : ClickStatus.unavailable)
            : null,
      );
      _syncTimeScale();
      _applyGains();
      if (wasPlaying) await fresh.play();
      unawaited(_disposeQuietly(old).then((_) => _deleteQuietly(oldClickFile)));
      return true;
    } on Object catch (e) {
      debugPrint('Playback: engine swap failed: $e');
      await _disposeQuietly(fresh);
      return false;
    }
  }

  /// Generates the click for this score at the current speed and adds it
  /// to [engine] as a follower track. Done after the voices are ready so
  /// it never delays them; a failure only disables the metronome controls.
  ///
  /// One plan at a time: a slider release while one is being written or
  /// attached is held in [_replanPending] and re-checked when it ends, so
  /// two plans never compete for the engine's single click slot.
  ///
  /// [replace]: a re-plan after a speed change (see [commitBpm]); only
  /// started once a click is attached and ready. The old click keeps
  /// playing until the new file is written, then is swapped out; the
  /// status stays ready throughout, so the click does not drop out for the
  /// moment of the swap. A re-plan that fails (not
  /// written, or not attached) keeps the old click: it is still in time,
  /// only its subdivision is out of date, and the next release of the
  /// slider tries again. The click is marked unavailable only when there
  /// is no click left to fall back to.
  ///
  /// File ownership: [_clickFile] is the file the engine holds, and is
  /// set only once an attach succeeded. Whoever replaces it deletes it;
  /// a file that never got attached is deleted by the call that wrote it;
  /// leaving the screen deletes whatever [_clickFile] is then. So no file
  /// is deleted twice, or left behind.
  Future<void> _prepareClick(
    PlaybackEngine engine,
    int generation, {
    bool replace = false,
  }) async {
    bool live() =>
        ref.mounted && generation == _generation && identical(_engine, engine);
    _clickBusy = true;
    try {
      await _planAndAttachClick(engine, live, replace: replace);
    } finally {
      // Leaving the screen already reset both (see [_releaseEngine]).
      if (live()) {
        _clickBusy = false;
        _clickSwapping = false;
        if (_replanPending) {
          _replanPending = false;
          commitBpm();
        }
      }
    }
  }

  Future<void> _planAndAttachClick(
    PlaybackEngine engine,
    bool Function() live, {
    required bool replace,
  }) async {
    // A plan for a zero length is an empty file: "ready" yet silent. So
    // wait for the length if just_audio doesn't know it yet.
    final length = await engine.durationKnown();
    if (!live()) return;
    if (length <= Duration.zero) {
      debugPrint('Playback: track length unknown; no metronome click');
      if (!replace) _clickFailed();
      return;
    }
    // The seek bar read the same unknown length at load.
    if (state.duration != length) state = state.copyWith(duration: length);
    final chosenBpm = state.chosenBpm;
    final plannedSubdivisions = subdividedBars(_bars, chosenBpm);
    final Uri file;
    try {
      final plan = planClicks(
        bars: _bars,
        events: _eventsOf(state.timeline),
        tempoBpm: state.tempoBpm,
        chosenBpm: chosenBpm,
        length: length,
      );
      file = await ref.read(clickTrackWriterProvider)(plan);
    } on Object catch (e, stack) {
      debugPrint('Playback: metronome click not generated: $e\n$stack');
      // A failed re-plan keeps the old click (and its plan).
      if (live() && !replace) _clickFailed();
      return;
    }
    if (!live()) {
      unawaited(_deleteQuietly(file));
      return;
    }
    final old = _clickFile;
    // From the detach on, the engine reports this swap's own failed
    // attempts on clickFailures too; they are handled here, from the
    // attach results, not as the click failing (see [_onClickFailure]).
    _clickSwapping = replace;
    if (replace) await engine.detachClick();
    if (!live()) {
      // Left the screen: [_releaseEngine] deletes [old].
      unawaited(_deleteQuietly(file));
      return;
    }
    if (await engine.attachClick(file)) {
      if (!live()) {
        unawaited(_deleteQuietly(file));
        return;
      }
      _clickFile = file;
      _plannedSubdivisions = plannedSubdivisions;
      if (old != null && replace) unawaited(_deleteQuietly(old));
      state = state.copyWith(clickStatus: ClickStatus.ready);
      _applyGains();
      return;
    }
    unawaited(_deleteQuietly(file));
    if (!live()) return;
    if (!replace || old == null) {
      _clickFailed();
      return;
    }
    debugPrint('Playback: re-planned click not attached; keeping the old');
    // The failed attempt still holds the engine's one click slot.
    await engine.detachClick();
    if (!live()) return;
    // A fresh load of the old file, then a seek to the voices: the click
    // is silent for that moment (a few hundred ms at most), then resumes
    // in time. The plan stays the old one, so the next release re-plans.
    if (await engine.attachClick(old)) return;
    if (!live()) return;
    _clickFile = null;
    unawaited(_deleteQuietly(old));
    _clickFailed();
  }

  /// The Speed slider was let go (or stepped by a screen reader). Re-plans
  /// the click only when a compound measure's beat tempo crossed 60 a
  /// minute (PIYA-210 "Speed changes"): that is the only time the click
  /// pattern changes, and re-planning on every drag tick would swap the
  /// click track dozens of times a second.
  ///
  /// The speed reaches the engine only here (F8a): each speed change is a
  /// pause, re-align and restart of every player, which mid-drag would
  /// stutter dozens of times a second.
  void commitBpm() {
    final engine = _engine;
    if (engine == null || state.phase != PlaybackPhase.ready) return;
    _saveMix();
    if (state.source == PlaybackSource.midi) {
      unawaited(_rerender());
      return;
    }
    unawaited(engine.setSpeed(state.speed));
    if (state.clickStatus == ClickStatus.unavailable) return;
    if (_clickBusy) {
      // Re-checked once the plan in progress ends.
      _replanPending = true;
      return;
    }
    final planned = _plannedSubdivisions;
    if (planned == null) return;
    if (setEquals(planned, subdividedBars(_bars, state.chosenBpm))) return;
    unawaited(_prepareClick(engine, _generation, replace: true));
  }

  /// A swap's own failed attempts are handled by [_planAndAttachClick];
  /// the old click it detached can no longer report anything.
  void _onClickFailure(Object _) {
    if (!_clickSwapping) _clickFailed();
  }

  void _clickFailed() {
    if (!ref.mounted || state.phase != PlaybackPhase.ready) return;
    if (state.clickStatus == ClickStatus.unavailable) return;
    state = state.copyWith(clickStatus: ClickStatus.unavailable);
    _applyGains();
  }

  static Future<void> _deleteQuietly(Uri? file) async {
    if (file == null || file.scheme != 'file') return;
    try {
      await File.fromUri(file).delete();
    } on Object catch (e) {
      if (kDebugMode) debugPrint('Playback: click file not deleted: $e');
    }
  }

  /// A timing file that fails to load costs only the indicator (and
  /// bar-based skipping), not the audio, so it doesn't fail the screen;
  /// the flag lets the screen say so once. No timing URL at all is not a
  /// failure (nothing to show).
  ///
  /// The measure table is kept whole even for pages without an image: it
  /// times the click, which doesn't depend on drawing anything.
  Future<(ScoreTimeline, List<BarInfo>, bool)> _loadTimeline(
    ScoreResultApi api,
    ScoreResult result,
  ) async {
    final url = result.timingMetadataUrl;
    if (url == null) return (ScoreTimeline.empty, const <BarInfo>[], false);
    try {
      final file = await api.fetchTiming(url);
      return (
        ScoreTimeline(
          onExistingPages(file.events, result.hasPage),
          // A bar on a page with no image can't be drawn (as for events).
          bars: [
            for (final bar in file.bars)
              if (bar.pageIndex == null || result.hasPage(bar.pageIndex!)) bar,
          ],
        ),
        file.bars,
        false,
      );
    } on Object catch (e, stack) {
      debugPrint('Playback: timing unavailable: $e\n$stack');
      return (ScoreTimeline.empty, const <BarInfo>[], true);
    }
  }

  /// Events pointing at a page the result has no image for can't be drawn;
  /// placing them would mean inventing heights for pages that don't exist
  /// (or a band over a blank page).
  @visibleForTesting
  static List<TimingEvent> onExistingPages(
    List<TimingEvent> events,
    bool Function(int pageIndex) hasPage,
  ) {
    final kept = [
      for (final event in events)
        if (hasPage(event.pageIndex)) event,
    ];
    if (kept.length != events.length) {
      debugPrint(
        'Playback: dropped ${events.length - kept.length} timing events '
        'on pages without an image',
      );
    }
    return kept;
  }

  /// A voice's audio dropped out mid-play. The rest keep playing and its
  /// chip turns unavailable (user decision 2026-10-09); only when no voice
  /// is left does the screen show the audio error (FR-14). If it was the
  /// only voice selected, every remaining voice is selected instead, so
  /// something is still heard and "at least one selected" still holds.
  void _onFailure(PlaybackFailure failure) {
    if (!ref.mounted || state.phase != PlaybackPhase.ready) return;
    final remaining = state.available.difference({failure.voice});
    if (failure.fatal || remaining.isEmpty) {
      _failPlaying();
      return;
    }
    var selected = state.selected.difference({failure.voice});
    var muted = state.muted;
    // Nothing audible (a hand-muted lone chip counts) must fall back too.
    if (selected.difference(muted).isEmpty) {
      // V2.2 AC3: the fallback turns the rest on and unmutes them.
      selected = remaining;
      muted = muted.difference(_mixMuted);
      _mixMuted = {};
    }
    state = state.copyWith(
      muted: muted,
      failedVoices: {...state.failedVoices, failure.voice},
      selected: selected,
      // The new master may be a shorter track.
      duration: _engine?.duration,
    );
    _applyGains();
  }

  void _failPlaying() {
    final engine = _engine;
    if (engine != null) unawaited(_quietly(engine.pause()));
    _releaseEngine();
    _fail(PlaybackError.audio);
  }

  static Future<void> _disposeQuietly(PlaybackEngine? engine) async {
    if (engine != null) await _quietly(engine.dispose());
  }

  static Future<void> _quietly(Future<void> call) async {
    try {
      await call;
    } on Object catch (e) {
      debugPrint('Playback: engine cleanup failed: $e');
    }
  }

  /// AC3: the onboarding voice if this score has it, else every voice.
  Future<Set<VoicePart>> _defaultSelection(Set<VoicePart> available) async {
    VoicePart? preferred;
    try {
      preferred = await ref
          .read(onboardingPrefsServiceProvider)
          .getDefaultVoicePart();
    } on Object catch (e) {
      if (kDebugMode) debugPrint('Playback: voice preference unread: $e');
    }
    if (preferred != null && available.contains(preferred)) {
      return {preferred};
    }
    return available;
  }

  /// For a result without `arranger` (PIYA-103 AC7 omits it when absent, and
  /// older servers lack it): reuse the library row the user tapped, if
  /// the library is still loaded underneath (never fetch it just for this).
  String? _libraryArranger() {
    if (!ref.exists(scoreLibraryProvider)) return null;
    final scores = ref.read(scoreLibraryProvider).value;
    return scores
        ?.where((score) => score.scoreId == scoreId)
        .firstOrNull
        ?.arranger;
  }

  void _fail(PlaybackError error) {
    state = PlaybackState(phase: PlaybackPhase.failed, error: error);
  }

  static PlaybackError _errorFor(ScoreResultException e) => switch (e) {
    ScoreResultNotReadyException() => PlaybackError.notReady,
    ScoreResultNotFoundException() => PlaybackError.notFound,
    ScoreResultNetworkException() => PlaybackError.network,
    ScoreResultServerException() => PlaybackError.server,
    ScoreResultSessionExpiredException() => PlaybackError.sessionExpired,
  };

  Future<void> togglePlay() => state.playing ? pause() : play();

  Future<void> play() async => _engine?.play();

  Future<void> pause() async => _engine?.pause();

  /// Clamped to the track (AC5).
  Future<void> seek(Duration target) async {
    final engine = _engine;
    if (engine == null) return;
    await engine.seek(_clamp(target));
  }

  /// ⟲5 / ⟳5, clamped to 0 and the end.
  Future<void> skipBy(Duration delta) => seek(position + delta);

  /// ⏮ / ⏭: see [skipTargets].
  Future<void> skipToStart() => seek(_toAudio(_targets().back));

  Future<void> skipToEnd() {
    final forward = _targets().forward;
    return seek(forward == null ? state.duration : _toAudio(forward));
  }

  /// Timeline targets are score time; MIDI audio runs at the rendered bpm.
  Duration _toAudio(Duration score) => Duration(
    microseconds: (score.inMicroseconds / (state.timeline?.audioToScore ?? 1))
        .round(),
  );

  /// Keeps the timeline's score-time/audio-time ratio in step with what the
  /// engine is playing (see [ScoreTimeline.audioToScore]).
  void _syncTimeScale() => state.timeline?.audioToScore =
      state.source == PlaybackSource.midi && state.tempoBpm > 0
      ? _renderedBpm / state.tempoBpm
      : 1;

  ({Duration back, Duration? forward}) _targets() =>
      skipTargets(_eventsOf(state.timeline));

  /// A fresh click track for Export (PIYA-211 AC7), planned exactly as
  /// Playback's is for the current BPM, in track time (the export
  /// time-stretches it on its own, like each voice, as Playback's click
  /// player does). A separate file, so the caller may
  /// delete it without touching the one Playback is playing.
  Future<Uri> writeExportClick() => exportClickWriter()();

  /// [writeExportClick], with everything it needs from this controller
  /// read now. An export runs in the background (user decision
  /// 2026-10-21) and this controller is disposed when Playback closes, so
  /// the export must not reach back into it.
  Future<Uri> Function() exportClickWriter() {
    final writer = ref.read(clickTrackWriterProvider);
    final bars = _bars;
    final events = _eventsOf(state.timeline);
    final tempoBpm = state.tempoBpm;
    final chosenBpm = state.chosenBpm;
    final length = _engine?.duration ?? state.duration;
    // Planned when called, inside the export's error handling, as before.
    return () async => writer(
      planClicks(
        bars: bars,
        events: events,
        tempoBpm: tempoBpm,
        chosenBpm: chosenBpm,
        length: length,
      ),
    );
  }

  /// For Export: renders (or fetches from the cache) the voices and click
  /// at the chosen BPM. Null for MP3-source scores, which export as before.
  /// Read now, like [exportClickWriter], so it outlives this controller.
  Future<MidiRender?> Function()? exportMidiRenderer() {
    final result = state.result;
    if (state.source != PlaybackSource.midi || result == null) return null;
    final render = ref.read(midiVoiceRendererProvider);
    final bars = _bars;
    final bpm = state.chosenBpm;
    return () => render(result, bars, bpm);
  }

  List<TimingEvent> _eventsOf(ScoreTimeline? timeline) =>
      timeline?.events ?? const [];

  Duration _clamp(Duration target) {
    if (target < Duration.zero) return Duration.zero;
    final end = state.duration;
    return end > Duration.zero && target > end ? end : target;
  }

  /// AC2. Returns false, changing nothing, when [voice] is the last one
  /// selected: at least one voice always plays.
  bool toggleVoice(VoicePart voice) {
    if (!state.available.contains(voice)) return false;
    final selected = {...state.selected};
    if (selected.contains(voice)) {
      if (selected.length == 1) return false;
      selected.remove(voice);
    } else {
      selected.add(voice);
      // Chip on must be heard: lift only the default mix's own mute, never
      // one the user set.
      if (_mixMuted.contains(voice)) {
        _mixMuted = _mixMuted.difference({voice});
        state = state.copyWith(muted: state.muted.difference({voice}));
      }
    }
    state = state.copyWith(selected: selected);
    _applyGains();
    _saveMix();
    return true;
  }

  /// PIYA-209 AC3: sent to the engine at once, on every slider change (not
  /// at the end of a drag), so it is heard within the 100 ms budget.
  /// Mute and level are independent (user decision 2026-10-22): a slider
  /// at 0 is not a mute, and moving a muted row's slider leaves it muted
  /// (PIYA-209 AC4).
  void setVoiceVolume(VoicePart voice, double volume) {
    if (!state.available.contains(voice)) return;
    final level = volume.clamp(0.0, fullVolume).toDouble();
    state = state.copyWith(volumes: {...state.volumes, voice: level});
    _applyGains();
    _saveMix();
  }

  /// PIYA-209 AC2/AC4: muting leaves the slider exactly where it is, and
  /// unmuting plays at that level, 0% included (user decision 2026-10-22).
  void setVoiceMuted(VoicePart voice, {required bool muted}) {
    if (!state.available.contains(voice)) return;
    // Unmuting a default-mix mute must also turn the chip on: voiceGain is 0
    // for a chip-off voice, so the Mixer would show it live but silent.
    final liftChip =
        !muted && _mixMuted.contains(voice) && !state.selected.contains(voice);
    _mixMuted = _mixMuted.difference({voice});
    state = state.copyWith(
      muted: muted ? {...state.muted, voice} : state.muted.difference({voice}),
      selected: liftChip ? {...state.selected, voice} : state.selected,
    );
    _applyGains();
    _saveMix();
  }

  /// The click row follows the voices' rule: level and Mute independent.
  void setClickVolume(double volume) {
    if (state.clickStatus == ClickStatus.unavailable) return;
    final level = volume.clamp(0.0, fullVolume).toDouble();
    state = state.copyWith(clickVolume: level);
    _applyGains();
    _saveMix();
  }

  void setClickMuted({required bool muted}) {
    if (state.clickStatus == ClickStatus.unavailable) return;
    state = state.copyWith(clickMuted: muted);
    _applyGains();
    _saveMix();
  }

  /// PIYA-210 AC3: the Speed modal's Metronome Click checkbox.
  void setMetronomeOn({required bool on}) {
    if (state.clickStatus == ClickStatus.unavailable) return;
    state = state.copyWith(metronomeOn: on);
    _applyGains();
    _saveMix();
  }

  /// PIYA-210: the Speed slider, in whole BPM from 30 to 180. Moves the
  /// shown value only; the engine gets the speed when the drag ends, in
  /// [commitBpm] (F8a). The engine keeps pitch (FR-9). The indicator reads
  /// the engine's audio position, so it needs no change when the speed
  /// does.
  void setBpm(int bpm) {
    if (state.phase != PlaybackPhase.ready) return;
    final clamped = bpm.clamp(ScoreDetails.minTempo, ScoreDetails.maxTempo);
    if (clamped == state.chosenBpm) return;
    state = state.copyWith(bpm: clamped);
  }

  void dismissReview() => state = state.copyWith(reviewDismissed: true);

  /// Applies the last saved mixer and speed over the defaults; anything
  /// unusable (voice gone, bad type) keeps its default.
  void _restoreMix(Map<String, dynamic>? saved, Set<VoicePart> playable) {
    if (saved == null) return;
    Set<VoicePart> voices(Object? raw) => {
      if (raw is List)
        for (final name in raw)
          if (parseVoicePart(name) case final v? when playable.contains(v)) v,
    };
    double? level(Object? v) => v is num ? v.toDouble().clamp(0.0, 1.0) : null;
    final selected = voices(saved['selected']);
    final volumes = {...state.volumes};
    final rawVolumes = saved['volumes'];
    if (rawVolumes is Map) {
      rawVolumes.forEach((name, v) {
        final voice = parseVoicePart(name);
        final l = level(v);
        if (voice != null && l != null && volumes.containsKey(voice)) {
          volumes[voice] = l;
        }
      });
    }
    final bpm = saved['bpm'];
    final clickOk = state.clickStatus != ClickStatus.unavailable;
    // Mutes only apply with the selection they were saved against, else a
    // fallback selection could end up fully muted.
    final muted = selected.isNotEmpty && saved['muted'] is List
        ? voices(saved['muted'])
        : state.muted;
    // Restored mutes stay liftable by the chip (the Mute pill may be gone).
    _mixMuted = {...muted};
    state = state.copyWith(
      selected: selected.isEmpty ? state.selected : selected,
      muted: muted,
      volumes: volumes,
      clickVolume: clickOk ? level(saved['clickVolume']) : null,
      clickMuted: clickOk && saved['clickMuted'] == true,
      metronomeOn: clickOk && saved['metronomeOn'] == true,
      bpm: bpm is int
          ? bpm.clamp(ScoreDetails.minTempo, ScoreDetails.maxTempo)
          : null,
    );
  }

  /// Fire-and-forget; slider drags write every change (a small JSON string,
  /// shortcut: debounce if this ever shows in profiling).
  void _saveMix() {
    if (state.phase != PlaybackPhase.ready) return;
    unawaited(
      PlaybackPrefs.saveMix(scoreId, {
        'selected': [for (final v in state.selected) v.name],
        'muted': [for (final v in state.muted) v.name],
        'volumes': {for (final e in state.volumes.entries) e.key.name: e.value},
        'clickVolume': state.clickVolume,
        'clickMuted': state.clickMuted,
        'metronomeOn': state.metronomeOn,
        'bpm': state.chosenBpm,
      }),
    );
  }

  void _applyGains() {
    final engine = _engine;
    if (engine == null) return;
    for (final voice in state.available) {
      final gain = state.voiceGain(voice);
      if (_sentGains[voice] == gain) continue;
      _sentGains[voice] = gain;
      unawaited(engine.setVolume(voice, gain));
    }
    final click = state.clickGain;
    if (_sentGains[_clickGainKey] != click) {
      _sentGains[_clickGainKey] = click;
      unawaited(engine.setClickVolume(click));
    }
  }

  void _releaseEngine() {
    _clickBusy = false;
    _replanPending = false;
    _clickSwapping = false;
    _rerenderPending = false;
    _bars = const [];
    _plannedSubdivisions = null;
    unawaited(_playingSub?.cancel());
    unawaited(_failureSub?.cancel());
    unawaited(_clickFailureSub?.cancel());
    _playingSub = null;
    _failureSub = null;
    _clickFailureSub = null;
    _sentGains.clear();
    final engine = _engine;
    final clickFile = _clickFile;
    _engine = null;
    _clickFile = null;
    // The file goes once the player holding it is released.
    unawaited(_disposeQuietly(engine).then((_) => _deleteQuietly(clickFile)));
  }
}
