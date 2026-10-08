import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:just_audio/just_audio.dart';

import '../models/voice_part.dart';

/// The audio for one score could not be loaded or decoded.
class PlaybackLoadException implements Exception {
  const PlaybackLoadException([this.cause]);

  final Object? cause;

  @override
  String toString() => 'PlaybackLoadException($cause)';
}

/// Plays the per-voice tracks of one score in step (FR-4/FR-5).
///
/// An interface so widget tests can swap in a fake clock-driven engine.
abstract interface class PlaybackEngine {
  /// Loads every track; throws [PlaybackLoadException] if any fails.
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

  /// Starts playing. Returns once playback has been started, not when it
  /// finishes.
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
/// The first loaded voice (in S/A/T/B order) is the master clock: the
/// others are started from its position and re-seeked to it whenever they
/// drift past [maxDrift]. Muting is volume 0 rather than pausing, so a
/// re-selected voice comes back exactly in time.
///
/// Speed (PIYA-210, FR-9): just_audio's `setSpeed` on Android goes to
/// ExoPlayer's `PlaybackParameters` with pitch 1.0, which time-stretches
/// through Sonic (WSOLA-style) rather than resampling, so pitch is kept.
/// PIYA-210 must still verify that on device, by ear and with a tuner, at
/// 0.5x and 1.5x.
class JustAudioPlaybackEngine implements PlaybackEngine {
  JustAudioPlaybackEngine({AudioPlayer Function()? playerFactory})
    : _playerFactory = playerFactory ?? AudioPlayer.new;

  /// Beyond this a voice is audibly out of step with the master
  /// (~1/25 s, about a 32nd note at 90 bpm).
  static const Duration maxDrift = Duration(milliseconds: 40);
  static const Duration driftCheckInterval = Duration(seconds: 1);

  final AudioPlayer Function() _playerFactory;
  final Map<VoicePart, AudioPlayer> _players = {};
  final StreamController<bool> _playing = StreamController.broadcast();
  final List<StreamSubscription<Object?>> _subscriptions = [];
  Timer? _driftTimer;
  bool _disposed = false;

  AudioPlayer? get _master => _players.values.firstOrNull;

  @override
  Future<void> load(Map<VoicePart, Uri> tracks) async {
    for (final voice in VoicePart.values) {
      final uri = tracks[voice];
      if (uri != null) _players[voice] = _playerFactory();
    }
    final master = _master;
    if (master == null) throw const PlaybackLoadException('no tracks');
    try {
      await Future.wait([
        for (final entry in _players.entries)
          entry.value.setAudioSource(AudioSource.uri(tracks[entry.key]!)),
      ]);
    } on PlayerException catch (e) {
      throw PlaybackLoadException(e);
    } on PlayerInterruptedException catch (e) {
      throw PlaybackLoadException(e);
    } on PlatformException catch (e) {
      throw PlaybackLoadException(e);
    }
    _subscriptions
      ..add(master.playingStream.listen(_onPlayingChanged))
      ..add(
        master.processingStateStream.listen((state) {
          if (state == ProcessingState.completed) unawaited(_onCompleted());
        }),
      );
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
  Future<void> play() async {
    final master = _master;
    if (master == null || master.playing) return;
    if (position >= duration && duration > Duration.zero) {
      await seek(Duration.zero);
    }
    await _alignToMaster();
    // just_audio's play() completes only when playback stops again, so it
    // must not be awaited.
    for (final player in _players.values) {
      unawaited(player.play());
    }
  }

  @override
  Future<void> pause() async {
    await Future.wait([for (final player in _players.values) player.pause()]);
  }

  @override
  Future<void> seek(Duration position) async {
    await Future.wait([
      for (final player in _players.values) player.seek(position),
    ]);
  }

  @override
  Future<void> setVolume(VoicePart voice, double volume) async {
    await _players[voice]?.setVolume(volume.clamp(0.0, 1.0));
  }

  @override
  Future<void> setSpeed(double speed) async {
    await Future.wait([
      for (final player in _players.values) player.setSpeed(speed),
    ]);
  }

  @override
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _driftTimer?.cancel();
    for (final subscription in _subscriptions) {
      await subscription.cancel();
    }
    await Future.wait([for (final player in _players.values) player.dispose()]);
    await _playing.close();
  }

  void _onPlayingChanged(bool playing) {
    if (_disposed) return;
    _driftTimer?.cancel();
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

  Future<void> _alignToMaster() async {
    final master = _master!;
    final target = master.position;
    await Future.wait([
      for (final player in _players.values)
        if (!identical(player, master)) player.seek(target),
    ]);
  }

  void _resync() {
    final master = _master;
    if (master == null || !master.playing) return;
    final target = master.position;
    for (final player in _players.values) {
      if (identical(player, master)) continue;
      if ((player.position - target).abs() > maxDrift) {
        if (kDebugMode) debugPrint('Playback: resyncing a drifted voice');
        unawaited(player.seek(target));
      }
    }
  }
}
