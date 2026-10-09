import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/api_config.dart';
import '../models/score_result.dart';
import '../models/score_timeline.dart';
import '../models/voice_part.dart';
import '../services/fake_score_library_api.dart';
import '../services/fake_score_result_api.dart';
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

enum PlaybackPhase { loading, ready, failed }

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
    this.composer,
    this.selected = const {},
    this.volumes = const {},
    this.playing = false,
    this.duration = Duration.zero,
    this.speed = 1,
    this.reviewDismissed = false,
    this.timingUnavailable = false,
    this.failedVoices = const {},
  });

  final PlaybackPhase phase;
  final PlaybackError? error;
  final ScoreResult? result;
  final ScoreTimeline? timeline;
  final String? composer;

  /// Voices the user hears (AC2). Never empty once ready.
  final Set<VoicePart> selected;

  /// Per-voice level for the Voice Mixer (PIYA-209); an unselected voice
  /// is silent whatever its level here.
  final Map<VoicePart, double> volumes;
  final bool playing;
  final Duration duration;
  final double speed;

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
    String? composer,
    Set<VoicePart>? selected,
    Map<VoicePart, double>? volumes,
    bool? playing,
    Duration? duration,
    double? speed,
    bool? reviewDismissed,
    Set<VoicePart>? failedVoices,
  }) => PlaybackState(
    phase: phase ?? this.phase,
    error: clearError ? null : error ?? this.error,
    result: result ?? this.result,
    timeline: timeline ?? this.timeline,
    composer: composer ?? this.composer,
    selected: selected ?? this.selected,
    volumes: volumes ?? this.volumes,
    playing: playing ?? this.playing,
    duration: duration ?? this.duration,
    speed: speed ?? this.speed,
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
    final volumes = {
      for (final voice in result.audioTracks.keys) voice: fullVolume,
    };
    state = PlaybackState(
      phase: PlaybackPhase.ready,
      result: result,
      timeline: timeline,
      composer: result.composer ?? _libraryComposer(),
      selected: selected,
      volumes: volumes,
      duration: engine.duration,
      timingUnavailable: timingFailed,
      failedVoices: failedVoices,
    );
    await _applyVolumes();
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
      return (
        ScoreTimeline(onExistingPages(events, result.scoreImages.length)),
        false,
      );
    } on Object catch (e, stack) {
      debugPrint('Playback: timing unavailable: $e\n$stack');
      return (ScoreTimeline.empty, true);
    }
  }

  /// Events pointing at a page the result has no image for can't be drawn;
  /// placing them would mean inventing heights for pages that don't exist.
  @visibleForTesting
  static List<TimingEvent> onExistingPages(
    List<TimingEvent> events,
    int pageCount,
  ) {
    final kept = [
      for (final event in events)
        if (event.pageIndex >= 0 && event.pageIndex < pageCount) event,
    ];
    if (kept.length != events.length) {
      debugPrint(
        'Playback: dropped ${events.length - kept.length} timing events '
        'outside the $pageCount score page(s)',
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
      // The new master may be a shorter track.
      duration: _engine?.duration,
    );
    unawaited(_applyVolumes());
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

  /// PIYA-103 has no composer; reuse the library row the user tapped, if
  /// the library is still loaded underneath (never fetch it just for this).
  String? _libraryComposer() {
    if (!ref.exists(scoreLibraryProvider)) return null;
    final scores = ref.read(scoreLibraryProvider).value;
    return scores
        ?.where((score) => score.scoreId == scoreId)
        .firstOrNull
        ?.composer;
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
    unawaited(_applyVolumes());
    return true;
  }

  /// PIYA-209's entry point; also kept for the mixer sheet.
  Future<void> setVoiceVolume(VoicePart voice, double volume) async {
    state = state.copyWith(volumes: {...state.volumes, voice: volume});
    await _applyVolumes();
  }

  /// PIYA-210's entry point. The indicator reads the engine's audio
  /// position, so it needs no change when the speed does.
  Future<void> setSpeed(double speed) async {
    state = state.copyWith(speed: speed);
    await _engine?.setSpeed(speed);
  }

  void dismissReview() => state = state.copyWith(reviewDismissed: true);

  Future<void> _applyVolumes() async {
    final engine = _engine;
    if (engine == null) return;
    for (final voice in state.available) {
      final level = state.selected.contains(voice)
          ? state.volumes[voice] ?? fullVolume
          : 0.0;
      await engine.setVolume(voice, level);
    }
  }

  void _releaseEngine() {
    unawaited(_playingSub?.cancel());
    unawaited(_failureSub?.cancel());
    _playingSub = null;
    _failureSub = null;
    final engine = _engine;
    _engine = null;
    unawaited(_disposeQuietly(engine));
  }
}
