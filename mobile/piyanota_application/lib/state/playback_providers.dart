import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/api_config.dart';
import '../models/score_details.dart';
import '../models/score_result.dart';
import '../models/score_timeline.dart';
import '../models/voice_part.dart';
import '../services/fake_score_library_api.dart';
import '../services/fake_score_result_api.dart';
import '../services/metronome_click.dart';
import '../services/playback_engine.dart';
import '../services/score_result_api.dart';
import 'auth_providers.dart';
import 'onboarding_providers.dart';
import 'processing_providers.dart';
import 'score_library_providers.dart';

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
  return HttpScoreResultApi(ref.watch(dioProvider), sessionStorage);
});

/// Makes a fresh engine per opened score; tests override it with a fake.
final playbackEngineFactoryProvider = Provider<PlaybackEngine Function()>(
  (ref) => JustAudioPlaybackEngine.new,
);

/// Writes the metronome click track; tests override it with a fake (or a
/// failure).
final clickTrackWriterProvider = Provider<ClickTrackWriter>(
  (ref) => writeClickTrack,
);

enum PlaybackPhase { loading, ready, failed }

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
    this.soloed = const {},
    this.clickVolume = PlaybackController.fullVolume,
    this.clickMuted = false,
    this.clickSoloed = false,
    this.metronomeOn = false,
    this.clickStatus = ClickStatus.preparing,
    this.bpm,
    this.playing = false,
    this.duration = Duration.zero,
    this.reviewDismissed = false,
    this.timingUnavailable = false,
    this.failedVoices = const {},
  });

  final PlaybackPhase phase;
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

  /// Mixer Solo per voice. While any row (voice or click) is soloed, only
  /// soloed rows are heard; Mute still wins (design decision 2026-10-09).
  final Set<VoicePart> soloed;

  /// The Mixer's Metronome Click row: level, Mute and Solo. Whether the
  /// click plays at all is [metronomeOn], the Speed modal's toggle.
  final double clickVolume;
  final bool clickMuted;
  final bool clickSoloed;

  /// The Speed modal's Metronome Click checkbox (PIYA-210 AC3); off by
  /// default.
  final bool metronomeOn;
  final ClickStatus clickStatus;

  /// The Speed modal's BPM (PIYA-210), 30 to 240; null until loaded. Read
  /// it through [chosenBpm].
  final int? bpm;
  final bool playing;
  final Duration duration;

  /// The review banner was closed; lasts as long as this screen.
  final bool reviewDismissed;

  /// The timing file failed to load: the audio plays, but there is no
  /// position indicator. The screen says so once, quietly.
  final bool timingUnavailable;

  /// Voices whose audio failed to load or dropped out mid-play. The others
  /// keep playing (user decision 2026-10-09); these chips show as
  /// unavailable, like a missing track.
  final Set<VoicePart> failedVoices;

  /// Voices that can be heard: in the result, and not failed.
  Set<VoicePart> get available =>
      {...?result?.audioTracks.keys}.difference(failedVoices);

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

  /// A soloed metronome row counts only while the click can sound, so
  /// soloing it with the Speed toggle off never silences the voices
  /// (coordinator decision 2026-10-09).
  bool get anySoloed => soloed.isNotEmpty || (clickSoloed && clickLive);

  /// What [voice] is played at: silent if it can't play, its chip is off
  /// (PIYA-208 chips stack with the mixer), it is muted, or another row is
  /// soloed; else its slider level.
  double voiceGain(VoicePart voice) {
    if (!available.contains(voice) ||
        !selected.contains(voice) ||
        muted.contains(voice) ||
        (anySoloed && !soloed.contains(voice))) {
      return 0;
    }
    return volumes[voice] ?? PlaybackController.fullVolume;
  }

  /// The click: only while it is live (Speed toggle on, track loaded), not
  /// muted, and not left out by a solo; then the Metronome row's level.
  double get clickGain {
    if (!clickLive || clickMuted || (anySoloed && !clickSoloed)) {
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
    Set<VoicePart>? soloed,
    double? clickVolume,
    bool? clickMuted,
    bool? clickSoloed,
    bool? metronomeOn,
    ClickStatus? clickStatus,
    int? bpm,
    bool? playing,
    Duration? duration,
    bool? reviewDismissed,
    Set<VoicePart>? failedVoices,
  }) => PlaybackState(
    phase: phase ?? this.phase,
    error: clearError ? null : error ?? this.error,
    result: result ?? this.result,
    timeline: timeline ?? this.timeline,
    arranger: arranger ?? this.arranger,
    selected: selected ?? this.selected,
    volumes: volumes ?? this.volumes,
    muted: muted ?? this.muted,
    soloed: soloed ?? this.soloed,
    clickVolume: clickVolume ?? this.clickVolume,
    clickMuted: clickMuted ?? this.clickMuted,
    clickSoloed: clickSoloed ?? this.clickSoloed,
    metronomeOn: metronomeOn ?? this.metronomeOn,
    clickStatus: clickStatus ?? this.clickStatus,
    bpm: bpm ?? this.bpm,
    playing: playing ?? this.playing,
    duration: duration ?? this.duration,
    reviewDismissed: reviewDismissed ?? this.reviewDismissed,
    timingUnavailable: timingUnavailable,
    failedVoices: failedVoices ?? this.failedVoices,
  );
}

/// One opened score's playback, keyed by `scoreId`. autoDispose, so
/// leaving Playback disposes the engine and the audio stops with it.
final playbackControllerProvider = NotifierProvider.autoDispose
    .family<PlaybackController, PlaybackState, int>(PlaybackController.new);

class PlaybackController extends Notifier<PlaybackState> {
  PlaybackController(this.scoreId);

  final int scoreId;

  /// ⟲5 / ⟳5 (user decision 2026-10-09).
  static const Duration skipStep = Duration(seconds: 5);
  static const double fullVolume = 1;

  PlaybackEngine? _engine;
  StreamSubscription<bool>? _playingSub;
  StreamSubscription<PlaybackFailure>? _failureSub;
  StreamSubscription<Object>? _clickFailureSub;

  /// The generated click file of the current engine; deleted with it.
  Uri? _clickFile;

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

    final (timeline, timingFailed) = await _loadTimeline(api, result);
    if (!current()) return;

    PlaybackEngine? engine;
    try {
      engine = ref.read(playbackEngineFactoryProvider)();
      // Throws only if no voice at all loads; a voice that didn't is in
      // unavailableVoices and the rest still play.
      await engine.load(result.audioTracks);
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

    final failedVoices = {...engine.unavailableVoices};
    final playable = result.audioTracks.keys.toSet().difference(failedVoices);
    final selected = await _defaultSelection(playable);
    if (!current()) {
      await _disposeQuietly(engine);
      return;
    }
    _engine = engine;
    _playingSub = engine.playingChanges.listen((playing) {
      if (ref.mounted) state = state.copyWith(playing: playing);
    });
    _failureSub = engine.failures.listen(_onFailure);
    _clickFailureSub = engine.clickFailures.listen((_) => _clickFailed());
    // 209 AC5: every voice unmuted at full volume, nothing soloed,
    // metronome off, speed at the score's tempo. A fresh controller
    // (autoDispose) means a reopened score starts here again (209 AC6).
    final volumes = {
      for (final voice in result.audioTracks.keys) voice: fullVolume,
    };
    state = PlaybackState(
      phase: PlaybackPhase.ready,
      result: result,
      timeline: timeline,
      arranger: result.arranger ?? _libraryArranger(),
      selected: selected,
      volumes: volumes,
      duration: engine.duration,
      timingUnavailable: timingFailed,
      failedVoices: failedVoices,
      bpm: result.tempoBpm,
      // No tempo, no grid to lay the click on (coordinator decision
      // 2026-10-09); the slider still runs relative to the assumed 90.
      clickStatus: result.tempoKnown
          ? ClickStatus.preparing
          : ClickStatus.unavailable,
    );
    _applyGains();
    if (result.tempoKnown) unawaited(_prepareClick(engine, generation));
  }

  /// Generates the click for this score and adds it to [engine] as a
  /// follower track. Done after the voices are ready so it never delays
  /// them; a failure only disables the metronome controls.
  Future<void> _prepareClick(PlaybackEngine engine, int generation) async {
    bool current() =>
        ref.mounted && generation == _generation && identical(_engine, engine);
    final Uri file;
    try {
      final plan = planClicks(
        events: _eventsOf(state.timeline),
        tempoBpm: state.tempoBpm,
        length: engine.duration,
      );
      file = await ref.read(clickTrackWriterProvider)(plan);
    } on Object catch (e, stack) {
      debugPrint('Playback: metronome click not generated: $e\n$stack');
      if (current()) _clickFailed();
      return;
    }
    if (!current()) {
      unawaited(_deleteQuietly(file));
      return;
    }
    _clickFile = file;
    final attached = await engine.attachClick(file);
    if (!current()) return;
    if (!attached) {
      _clickFailed();
      return;
    }
    state = state.copyWith(clickStatus: ClickStatus.ready);
    _applyGains();
  }

  void _clickFailed() {
    if (!ref.mounted || state.phase != PlaybackPhase.ready) return;
    if (state.clickStatus == ClickStatus.unavailable) return;
    state = state.copyWith(
      clickStatus: ClickStatus.unavailable,
      // A solo on a click that can't play would silence every voice.
      clickSoloed: false,
    );
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
  Future<(ScoreTimeline, bool)> _loadTimeline(
    ScoreResultApi api,
    ScoreResult result,
  ) async {
    final url = result.timingMetadataUrl;
    if (url == null) return (ScoreTimeline.empty, false);
    try {
      final events = await api.fetchTiming(url);
      return (ScoreTimeline(onExistingPages(events, result.hasPage)), false);
    } on Object catch (e, stack) {
      debugPrint('Playback: timing unavailable: $e\n$stack');
      return (ScoreTimeline.empty, true);
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
    if (selected.isEmpty) selected = remaining;
    state = state.copyWith(
      failedVoices: {...state.failedVoices, failure.voice},
      selected: selected,
      // A solo on a voice that can't play would silence the rest.
      soloed: state.soloed.difference({failure.voice}),
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
  Future<void> skipToStart() => seek(_targets().back);

  Future<void> skipToEnd() => seek(_targets().forward ?? state.duration);

  ({Duration back, Duration? forward}) _targets() =>
      skipTargets(_eventsOf(state.timeline));

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
    }
    state = state.copyWith(selected: selected);
    _applyGains();
    return true;
  }

  /// PIYA-209 AC3: sent to the engine at once, on every slider change (not
  /// at the end of a drag), so it is heard within the 100 ms budget.
  void setVoiceVolume(VoicePart voice, double volume) {
    if (!state.available.contains(voice)) return;
    state = state.copyWith(
      volumes: {...state.volumes, voice: volume.clamp(0.0, fullVolume)},
    );
    _applyGains();
  }

  /// PIYA-209 AC2/AC4: the slider keeps its place while muted.
  void setVoiceMuted(VoicePart voice, {required bool muted}) {
    if (!state.available.contains(voice)) return;
    state = state.copyWith(
      muted: muted ? {...state.muted, voice} : state.muted.difference({voice}),
    );
    _applyGains();
  }

  void setVoiceSoloed(VoicePart voice, {required bool soloed}) {
    if (!state.available.contains(voice)) return;
    state = state.copyWith(
      soloed: soloed
          ? {...state.soloed, voice}
          : state.soloed.difference({voice}),
    );
    _applyGains();
  }

  void setClickVolume(double volume) {
    if (state.clickStatus == ClickStatus.unavailable) return;
    state = state.copyWith(clickVolume: volume.clamp(0.0, fullVolume));
    _applyGains();
  }

  void setClickMuted({required bool muted}) {
    if (state.clickStatus == ClickStatus.unavailable) return;
    state = state.copyWith(clickMuted: muted);
    _applyGains();
  }

  void setClickSoloed({required bool soloed}) {
    if (state.clickStatus == ClickStatus.unavailable) return;
    state = state.copyWith(clickSoloed: soloed);
    _applyGains();
  }

  /// PIYA-210 AC3: the Speed modal's Metronome Click checkbox.
  void setMetronomeOn({required bool on}) {
    if (state.clickStatus == ClickStatus.unavailable) return;
    state = state.copyWith(metronomeOn: on);
    _applyGains();
  }

  /// PIYA-210: the Speed slider, in whole BPM from 30 to 240. Applied to
  /// the engine at once, also while playing (AC4); the engine keeps pitch
  /// (FR-9). The indicator reads the engine's audio position, so it needs
  /// no change when the speed does.
  void setBpm(int bpm) {
    if (state.phase != PlaybackPhase.ready) return;
    final clamped = bpm.clamp(ScoreDetails.minTempo, ScoreDetails.maxTempo);
    if (clamped == state.chosenBpm) return;
    state = state.copyWith(bpm: clamped);
    final engine = _engine;
    if (engine != null) unawaited(engine.setSpeed(state.speed));
  }

  void dismissReview() => state = state.copyWith(reviewDismissed: true);

  /// Sends every gain that changed, all started at once (never one
  /// awaited after another), so a slider change reaches the engine in the
  /// same frame.
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
