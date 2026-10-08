import 'dart:async';

import 'package:clock/clock.dart';
import 'package:flutter/foundation.dart';
import 'package:just_audio/just_audio.dart';

import '../models/voice_part.dart';

/// The audio for one score could not be loaded or decoded.
class PlaybackLoadException implements Exception {
  const PlaybackLoadException([this.cause]);

  final Object? cause;

  @override
  String toString() => 'PlaybackLoadException($cause)';
}

/// One voice's player failed after loading (decoder error, lost stream,
/// a seek or play that threw). The failed voice stays silent from then on.
@immutable
class PlaybackFailure {
  const PlaybackFailure(this.voice, this.cause, {required this.master});

  final VoicePart voice;

  /// The failed voice was the master clock, so position and completion are
  /// gone too; nothing can keep playing.
  final bool master;
  final Object cause;

  @override
  String toString() =>
      'PlaybackFailure(${voice.name}${master ? ', master' : ''}: $cause)';
}

/// Plays the per-voice tracks of one score in step (FR-4/FR-5).
///
/// An interface so widget tests can swap in a fake clock-driven engine.
abstract interface class PlaybackEngine {
  /// Loads every track; throws [PlaybackLoadException] if any fails, for
  /// whatever reason.
  Future<void> load(Map<VoicePart, Uri> tracks);

  /// The audio position of the master track. This drives the seek bar and
  /// the indicator, so both follow the audio at any speed.
  Duration get position;

  /// The master track's length, known after [load].
  Duration get duration;

  bool get playing;

  /// Emits whenever [playing] changes, including when playback stops on
  /// its own at the end.
  Stream<bool> get playingChanges;

  /// Runtime failures after [load]. Transport calls never throw for a
  /// failed player; the failure arrives here instead.
  Stream<PlaybackFailure> get failures;

  /// Starts playing. Returns once playback has been started, not when it
  /// finishes. From the end, starts again at 0.
  Future<void> play();
  Future<void> pause();
  Future<void> seek(Duration position);

  /// 0 (silent) to 1 (full). An unselected chip is 0 (FR-5 mute).
  Future<void> setVolume(VoicePart voice, double volume);

  /// PIYA-210. Must keep pitch (FR-9); see [JustAudioPlaybackEngine].
  Future<void> setSpeed(double speed);
  Future<void> dispose();
}

/// One just_audio player per voice, kept in step by hand.
///
/// The longest loaded track is the master clock (ties go to S/A/T/B
/// order): a shorter master would report completion while the others
/// still had notes left. The others are started from its position and
/// re-seeked to it when they drift (see [resyncTrigger]). Muting is volume
/// 0 rather than pausing, so a re-selected voice comes back exactly in
/// time.
///
/// Speed (PIYA-210, FR-9): just_audio's `setSpeed` on Android goes to
/// ExoPlayer's `PlaybackParameters` with pitch 1.0, which time-stretches
/// through Sonic (WSOLA-style) rather than resampling, so pitch is kept.
/// PIYA-210 must still verify that on device, by ear and with a tuner, at
/// 0.5x and 1.5x.
///
/// just_audio 0.10 reports playback errors only on `errorStream`
/// (maxSkipsOnError is 0), so every player's stream is watched; a failure
/// marks that player dead, stops it, and is passed on as [failures].
class JustAudioPlaybackEngine implements PlaybackEngine {
  JustAudioPlaybackEngine({AudioPlayer Function()? playerFactory})
    : _playerFactory = playerFactory ?? AudioPlayer.new;

  /// A follower this far from the master on [resyncStrikes] checks in a
  /// row is re-seeked. ExoPlayer's position reports jitter by a few tens
  /// of ms, so a lower trigger re-seeks voices that are in fact in step,
  /// and each re-seek is itself an audible glitch.
  static const Duration resyncTrigger = Duration(milliseconds: 100);

  /// Back under this, a follower counts as in step again and its strikes
  /// reset. Between this and [resyncTrigger] the strikes stay as they are
  /// (hysteresis), so a voice hovering near the trigger isn't re-seeked
  /// on every check.
  static const Duration inStepTolerance = Duration(milliseconds: 40);

  /// Consecutive over-trigger checks before a re-seek, so one stale
  /// position report doesn't cause one.
  static const int resyncStrikes = 2;
  static const Duration driftCheckInterval = Duration(milliseconds: 500);

  /// Upper bound on the measured seek latency added to a re-seek target
  /// (the master keeps moving while the follower seeks). Keeps one slow
  /// seek from throwing the next one far ahead.
  static const Duration maxSeekLead = Duration(milliseconds: 250);

  /// Weight of the newest measurement in the seek-latency average.
  static const double seekLatencySmoothing = 0.5;

  final AudioPlayer Function() _playerFactory;
  final Map<VoicePart, AudioPlayer> _players = {};
  final Set<VoicePart> _dead = {};
  final Map<VoicePart, int> _strikes = {};
  final Set<VoicePart> _resyncing = {};
  final StreamController<bool> _playing = StreamController.broadcast();
  final StreamController<PlaybackFailure> _failures =
      StreamController.broadcast();
  final List<StreamSubscription<Object?>> _subscriptions = [];
  VoicePart? _masterVoice;
  Timer? _driftTimer;
  bool _disposed = false;
  double _speed = 1;
  Duration _seekLatency = Duration.zero;

  /// Bumped by every play and pause. A play that is still aligning the
  /// followers when a pause (or a newer play) arrives must not start them.
  int _transport = 0;

  /// Followers re-seeked to the master so far; logged in debug builds and
  /// read by tests.
  @visibleForTesting
  int resyncCount = 0;

  @visibleForTesting
  VoicePart? get masterVoice => _masterVoice;

  AudioPlayer? get _master {
    final voice = _masterVoice;
    if (voice == null || _dead.contains(voice)) return null;
    return _players[voice];
  }

  Iterable<MapEntry<VoicePart, AudioPlayer>> get _live =>
      _players.entries.where((entry) => !_dead.contains(entry.key));

  @override
  Future<void> load(Map<VoicePart, Uri> tracks) async {
    try {
      for (final voice in VoicePart.values) {
        final uri = tracks[voice];
        if (uri != null) _players[voice] = _playerFactory();
      }
      if (_players.isEmpty) throw const PlaybackLoadException('no tracks');
      final lengths = await Future.wait([
        for (final entry in _players.entries)
          entry.value.setAudioSource(AudioSource.uri(tracks[entry.key]!)),
      ]);
      _masterVoice = _longest(lengths);
    } on PlaybackLoadException {
      rethrow;
    } on Object catch (e, stack) {
      // Anything at all (PlayerException, PlatformException, a missing
      // plugin, a bad URI) is a load failure; the caller shows the audio
      // error rather than spinning.
      debugPrint('Playback: audio load failed: $e\n$stack');
      throw PlaybackLoadException(e);
    }
    for (final entry in _players.entries) {
      final voice = entry.key;
      _subscriptions.add(
        entry.value.errorStream.listen(
          (error) => _fail(voice, error),
          onError: (Object error) => _fail(voice, error),
        ),
      );
    }
    final master = _master!;
    _subscriptions
      ..add(master.playingStream.listen(_onPlayingChanged))
      ..add(
        master.processingStateStream.listen((state) {
          if (state == ProcessingState.completed) unawaited(_onCompleted());
        }),
      );
  }

  VoicePart _longest(List<Duration?> lengths) {
    final voices = _players.keys.toList();
    var best = 0;
    for (var i = 1; i < voices.length; i++) {
      final length = lengths[i] ?? _players[voices[i]]!.duration;
      final bestLength = lengths[best] ?? _players[voices[best]]!.duration;
      if ((length ?? Duration.zero) > (bestLength ?? Duration.zero)) best = i;
    }
    return voices[best];
  }

  @override
  Duration get position => _master?.position ?? Duration.zero;

  @override
  Duration get duration => _master?.duration ?? Duration.zero;

  @override
  bool get playing => _master?.playing ?? false;

  @override
  Stream<bool> get playingChanges => _playing.stream;

  @override
  Stream<PlaybackFailure> get failures => _failures.stream;

  @override
  Future<void> play() async {
    final master = _master;
    if (_disposed || master == null || master.playing) return;
    final ticket = ++_transport;
    if (position >= duration && duration > Duration.zero) {
      await seek(Duration.zero);
    }
    await _alignToMaster();
    // A pause (or another play) arrived while the followers were seeking.
    if (_disposed || ticket != _transport) return;
    // just_audio's play() completes only when playback stops again, so it
    // must not be awaited.
    for (final entry in _live) {
      unawaited(_guard(entry.key, entry.value.play()));
    }
  }

  @override
  Future<void> pause() async {
    _transport++;
    await Future.wait([
      for (final entry in _live) _guard(entry.key, entry.value.pause()),
    ]);
  }

  @override
  Future<void> seek(Duration position) async {
    _strikes.clear();
    await Future.wait([
      for (final entry in _live) _guard(entry.key, entry.value.seek(position)),
    ]);
  }

  @override
  Future<void> setVolume(VoicePart voice, double volume) async {
    final player = _players[voice];
    if (player == null || _dead.contains(voice)) return;
    await _guard(voice, player.setVolume(volume.clamp(0.0, 1.0)));
  }

  @override
  Future<void> setSpeed(double speed) async {
    _speed = speed;
    await Future.wait([
      for (final entry in _live) _guard(entry.key, entry.value.setSpeed(speed)),
    ]);
  }

  @override
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _transport++;
    _driftTimer?.cancel();
    // Not awaited: the listeners stop at once, and the players must be
    // released even if a source's cancel is slow to settle.
    for (final subscription in _subscriptions) {
      unawaited(subscription.cancel());
    }
    await Future.wait([
      for (final player in _players.values)
        player.dispose().catchError(
          (Object e) => debugPrint('Playback: dispose failed: $e'),
        ),
    ]);
    await _playing.close();
    await _failures.close();
  }

  /// Runs one player's call; a throw becomes that voice's failure instead
  /// of an unhandled error. An interrupted call (a newer seek or load
  /// replaced it) is not a failure.
  Future<void> _guard(VoicePart voice, Future<Object?> call) async {
    try {
      await call;
    } on PlayerInterruptedException {
      return;
    } on Object catch (e) {
      _fail(voice, e);
    }
  }

  void _fail(VoicePart voice, Object error) {
    if (_disposed || !_dead.add(voice)) return;
    final master = voice == _masterVoice;
    debugPrint(
      'Playback: ${voice.name} failed${master ? ' (master)' : ''}: '
      '$error',
    );
    _strikes.remove(voice);
    // Silence what's left of the failed voice; it may already be gone.
    unawaited(_players[voice]!.pause().catchError((Object _) {}));
    if (master) {
      // No clock any more: stop the rest so nothing plays unsynced.
      _transport++;
      _driftTimer?.cancel();
      for (final entry in _live) {
        unawaited(entry.value.pause().catchError((Object _) {}));
      }
      _playing.add(false);
    }
    _failures.add(PlaybackFailure(voice, error, master: master));
  }

  void _onPlayingChanged(bool playing) {
    if (_disposed) return;
    _driftTimer?.cancel();
    _strikes.clear();
    if (playing) {
      _driftTimer = Timer.periodic(driftCheckInterval, (_) => _resync());
    }
    _playing.add(playing);
  }

  /// The master reached the end: stop everyone there, so the next play
  /// starts again from the top (see [play]).
  Future<void> _onCompleted() async {
    if (_disposed) return;
    await pause();
    if (!_disposed) _playing.add(false);
  }

  /// Before play, while the master is paused, so its position is exact.
  Future<void> _alignToMaster() async {
    final master = _master;
    if (master == null) return;
    final target = master.position;
    await Future.wait([
      for (final entry in _live)
        if (!identical(entry.value, master))
          _guard(entry.key, entry.value.seek(target)),
    ]);
  }

  void _resync() {
    final master = _master;
    if (_disposed || master == null || !master.playing) return;
    final now = master.position;
    for (final entry in _live) {
      final voice = entry.key;
      final player = entry.value;
      if (identical(player, master) || _resyncing.contains(voice)) continue;
      // A shorter track that has finished stays at its end; it isn't
      // drifting, and seeking it past its end would loop the re-seek.
      final end = player.duration;
      if (end != null && now >= end) continue;
      final drift = (player.position - now).abs();
      if (drift <= inStepTolerance) {
        _strikes.remove(voice);
        continue;
      }
      if (drift <= resyncTrigger) continue;
      final strikes = (_strikes[voice] ?? 0) + 1;
      if (strikes < resyncStrikes) {
        _strikes[voice] = strikes;
        continue;
      }
      _strikes.remove(voice);
      unawaited(_resyncOne(voice, player, master));
    }
  }

  /// Seeks [player] to where the master will be once the seek lands: the
  /// position now plus the recent seek latency, at the current speed.
  Future<void> _resyncOne(
    VoicePart voice,
    AudioPlayer player,
    AudioPlayer master,
  ) async {
    _resyncing.add(voice);
    final lead = _seekLatency * _speed;
    final target = master.position + (lead > maxSeekLead ? maxSeekLead : lead);
    resyncCount++;
    if (kDebugMode) {
      debugPrint(
        'Playback: resync #$resyncCount ${voice.name} '
        '(lead ${lead.inMilliseconds} ms)',
      );
    }
    final watch = clock.stopwatch()..start();
    try {
      await _guard(voice, player.seek(target));
      final took = watch.elapsed;
      _seekLatency =
          _seekLatency * (1 - seekLatencySmoothing) +
          took * seekLatencySmoothing;
    } finally {
      _resyncing.remove(voice);
    }
  }
}
