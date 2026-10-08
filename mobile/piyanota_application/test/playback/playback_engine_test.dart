import 'dart:async';

import 'package:clock/clock.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:just_audio/just_audio.dart';

import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/services/playback_engine.dart';

/// Stands in for one just_audio player: position runs on the fake clock at
/// speed x [rate] ([rate] other than 1 simulates a drifting voice), and
/// completion and errors are raised by hand.
class FakeAudioPlayer implements AudioPlayer {
  FakeAudioPlayer({
    this.length = const Duration(seconds: 10),
    this.rate = 1,
    this.loadError,
  });

  final Duration length;
  double rate;

  /// Changes [rate] from now on, keeping the position reached so far.
  void setRate(double value) {
    _anchor = position;
    if (playing) _startedAt = clock.now();
    rate = value;
  }

  final Object? loadError;

  final StreamController<bool> _playingEvents = StreamController.broadcast();
  final StreamController<ProcessingState> _states =
      StreamController.broadcast();
  final StreamController<PlayerException> _errors =
      StreamController.broadcast();

  final List<Duration> seeks = [];

  /// Fake-clock time each seek was issued.
  final List<DateTime> seekTimes = [];
  int playCalls = 0;
  int pauseCalls = 0;
  double volumeSet = 1;
  double speedSet = 1;
  bool disposed = false;
  Uri? loadedUri;

  /// Each seek takes this long to land.
  Duration seekDelay = Duration.zero;
  Object? seekError;

  Duration _anchor = Duration.zero;
  DateTime? _startedAt;

  @override
  Future<Duration?> setAudioSource(
    AudioSource audioSource, {
    bool preload = true,
    int? initialIndex,
    Duration? initialPosition,
  }) async {
    if (loadError case final error?) throw error;
    loadedUri = (audioSource as UriAudioSource).uri;
    return length;
  }

  @override
  Duration? get duration => length;

  @override
  Duration get position {
    final started = _startedAt;
    if (started == null) return _anchor;
    final now = _anchor + clock.now().difference(started) * (speedSet * rate);
    return now > length ? length : now;
  }

  @override
  bool get playing => _startedAt != null;

  @override
  Stream<bool> get playingStream => _playingEvents.stream;

  @override
  Stream<ProcessingState> get processingStateStream => _states.stream;

  @override
  Stream<PlayerException> get errorStream => _errors.stream;

  @override
  Future<void> play() async {
    playCalls++;
    if (playing) return;
    _startedAt = clock.now();
    _playingEvents.add(true);
  }

  @override
  Future<void> pause() async {
    pauseCalls++;
    if (!playing) return;
    _anchor = position;
    _startedAt = null;
    _playingEvents.add(false);
  }

  @override
  Future<void> seek(Duration? position, {int? index}) async {
    seeks.add(position!);
    seekTimes.add(clock.now());
    if (seekDelay > Duration.zero) await Future<void>.delayed(seekDelay);
    if (seekError case final error?) throw error;
    _anchor = position;
    if (playing) _startedAt = clock.now();
  }

  @override
  Future<void> setVolume(double volume) async => volumeSet = volume;

  @override
  Future<void> setSpeed(double speed) async {
    _anchor = position;
    if (playing) _startedAt = clock.now();
    speedSet = speed;
  }

  @override
  Future<void> dispose() async => disposed = true;

  /// Reached the end of the track.
  void complete() {
    _anchor = length;
    _startedAt = null;
    _playingEvents.add(false);
    _states.add(ProcessingState.completed);
  }

  /// A decoder/source error, as just_audio 0.10 reports it.
  void raise() {
    _errors.add(PlayerException(1, 'decoder failed', null));
    if (playing) {
      _anchor = position;
      _startedAt = null;
      _playingEvents.add(false);
    }
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Map<VoicePart, Uri> tracks([
  Set<VoicePart> voices = const {...VoicePart.values},
]) => {
  for (final voice in voices)
    voice: Uri.parse('https://cdn.test/${voice.name}.mp3'),
};

/// An engine over one fake player per voice, in S/A/T/B order.
({
  JustAudioPlaybackEngine engine,
  Map<VoicePart, FakeAudioPlayer> players,
  List<bool> playing,
  List<PlaybackFailure> failures,
})
rig({Map<VoicePart, FakeAudioPlayer> overrides = const {}}) {
  final players = {
    for (final voice in VoicePart.values)
      voice: overrides[voice] ?? FakeAudioPlayer(),
  };
  final queue = [for (final voice in VoicePart.values) players[voice]!];
  final engine = JustAudioPlaybackEngine(playerFactory: queue.removeAt0);
  final playing = <bool>[];
  final failures = <PlaybackFailure>[];
  engine.playingChanges.listen(playing.add);
  engine.failures.listen(failures.add);
  return (
    engine: engine,
    players: players,
    playing: playing,
    failures: failures,
  );
}

extension on List<FakeAudioPlayer> {
  FakeAudioPlayer removeAt0() => removeAt(0);
}

void main() {
  group('load', () {
    test('one player per track, each given its own URI', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        for (final voice in VoicePart.values) {
          expect(r.players[voice]!.loadedUri, tracks()[voice]);
        }
        expect(r.engine.duration, const Duration(seconds: 10));
      });
    });

    test('the longest track is the master clock', () {
      fakeAsync((async) {
        final r = rig(
          overrides: {
            VoicePart.tenor: FakeAudioPlayer(
              length: const Duration(seconds: 12),
            ),
          },
        );
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        expect(r.engine.masterVoice, VoicePart.tenor);
        expect(r.engine.duration, const Duration(seconds: 12));
      });
    });

    test('any load failure is a PlaybackLoadException', () {
      fakeAsync((async) {
        final r = rig(
          overrides: {
            VoicePart.alto: FakeAudioPlayer(loadError: StateError('codec')),
          },
        );
        Object? thrown;
        r.engine.load(tracks()).catchError((Object e) => thrown = e);
        async.flushMicrotasks();
        expect(thrown, isA<PlaybackLoadException>());
      });
    });

    test('a factory that throws is a PlaybackLoadException too', () {
      fakeAsync((async) {
        final engine = JustAudioPlaybackEngine(
          playerFactory: () => throw StateError('no plugin'),
        );
        Object? thrown;
        engine.load(tracks()).catchError((Object e) => thrown = e);
        async.flushMicrotasks();
        expect(thrown, isA<PlaybackLoadException>());
      });
    });
  });

  group('transport', () {
    test('play, pause and seek reach all four players', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();

        unawaited(r.engine.play());
        async.flushMicrotasks();
        expect(r.players.values.every((p) => p.playing), isTrue);
        expect(r.engine.playing, isTrue);
        expect(r.playing, [true]);

        unawaited(r.engine.seek(const Duration(seconds: 4)));
        async.flushMicrotasks();
        for (final player in r.players.values) {
          expect(player.seeks.last, const Duration(seconds: 4));
        }

        unawaited(r.engine.pause());
        async.flushMicrotasks();
        expect(r.players.values.any((p) => p.playing), isFalse);
        expect(r.playing, [true, false]);
      });
    });

    test('a pause during play\'s alignment wins (no voice starts)', () {
      fakeAsync((async) {
        final r = rig(
          overrides: {
            VoicePart.bass: FakeAudioPlayer()
              ..seekDelay = const Duration(milliseconds: 80),
          },
        );
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();

        unawaited(r.engine.play());
        async.flushMicrotasks();
        unawaited(r.engine.pause());
        async.elapse(const Duration(milliseconds: 200));
        expect(r.players.values.any((p) => p.playing), isFalse);
      });
    });

    test('volume and speed go to the right players', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.setVolume(VoicePart.alto, 0));
        unawaited(r.engine.setSpeed(0.75));
        async.flushMicrotasks();
        expect(r.players[VoicePart.alto]!.volumeSet, 0);
        expect(r.players[VoicePart.soprano]!.volumeSet, 1);
        expect(r.players.values.every((p) => p.speedSet == 0.75), isTrue);
      });
    });
  });

  group('completion', () {
    test('the master ending stops everyone; Play then starts at 0', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 3));

        r.players[VoicePart.soprano]!.complete();
        async.flushMicrotasks();
        expect(r.players.values.any((p) => p.playing), isFalse);
        expect(r.playing.last, isFalse);
        expect(r.engine.position, const Duration(seconds: 10));

        unawaited(r.engine.play());
        async.flushMicrotasks();
        for (final player in r.players.values) {
          expect(player.seeks, contains(Duration.zero));
          expect(player.playing, isTrue);
        }
        expect(r.engine.position, Duration.zero);
      });
    });
  });

  group('errors', () {
    test('a follower failing is reported, silenced and skipped', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.flushMicrotasks();

        r.players[VoicePart.alto]!.raise();
        async.flushMicrotasks();
        expect(r.failures, hasLength(1));
        expect(r.failures.single.voice, VoicePart.alto);
        expect(r.failures.single.master, isFalse);
        // The others play on; the controller decides whether to stop.
        expect(r.players[VoicePart.soprano]!.playing, isTrue);

        final seeksBefore = r.players[VoicePart.alto]!.seeks.length;
        unawaited(r.engine.seek(const Duration(seconds: 2)));
        async.flushMicrotasks();
        expect(r.players[VoicePart.alto]!.seeks, hasLength(seeksBefore));
        expect(
          r.players[VoicePart.tenor]!.seeks.last,
          const Duration(seconds: 2),
        );
      });
    });

    test('the master failing stops everyone and reports it', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.flushMicrotasks();

        r.players[VoicePart.soprano]!.raise();
        async.flushMicrotasks();
        expect(r.failures.single.master, isTrue);
        expect(r.players.values.any((p) => p.playing), isFalse);
        expect(r.playing.last, isFalse);
        // No clock left: nothing further plays or drifts.
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 2));
        expect(r.players.values.any((p) => p.playing), isFalse);
      });
    });

    test('a seek that throws is a failure, not an unhandled error', () {
      fakeAsync((async) {
        final r = rig(
          overrides: {
            VoicePart.tenor: FakeAudioPlayer()..seekError = StateError('gone'),
          },
        );
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        Object? thrown;
        r.engine
            .seek(const Duration(seconds: 1))
            .catchError((Object e) => thrown = e);
        async.flushMicrotasks();
        expect(thrown, isNull);
        expect(r.failures.single.voice, VoicePart.tenor);
      });
    });
  });

  group('drift', () {
    test('voices in step are never re-seeked', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 5));
        expect(r.engine.resyncCount, 0);
      });
    });

    test('a drifting voice is pulled back to the master', () {
      fakeAsync((async) {
        final alto = FakeAudioPlayer(rate: 1.1);
        final r = rig(overrides: {VoicePart.alto: alto});
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 6));
        expect(r.engine.resyncCount, greaterThan(0));
        final drift = (alto.position - r.engine.position).abs();
        expect(
          drift,
          lessThanOrEqualTo(
            JustAudioPlaybackEngine.resyncTrigger +
                JustAudioPlaybackEngine.inStepTolerance,
          ),
        );
      });
    });

    test('one over-trigger reading alone does not re-seek (hysteresis)', () {
      fakeAsync((async) {
        final alto = FakeAudioPlayer();
        final r = rig(overrides: {VoicePart.alto: alto});
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.flushMicrotasks();

        // Jump ahead by more than the trigger, then come back in step
        // before the second check.
        alto.setRate(1.5);
        async.elapse(JustAudioPlaybackEngine.driftCheckInterval);
        // 250 ms ahead at the first check: one strike.
        alto.setRate(0.5);
        async.elapse(JustAudioPlaybackEngine.driftCheckInterval);
        // Back in step at the second: strikes reset, no re-seek.
        expect(r.engine.resyncCount, 0);
      });
    });

    test('a re-seek leads the master by the measured seek latency', () {
      fakeAsync((async) {
        final alto = FakeAudioPlayer(rate: 1.2)
          ..seekDelay = const Duration(milliseconds: 100);
        final r = rig(overrides: {VoicePart.alto: alto});
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        // play() starts the voices only once the follower's alignment seek
        // has landed.
        async.elapse(alto.seekDelay);
        final start = clock.now();
        expect(r.players[VoicePart.soprano]!.playing, isTrue);
        alto.seeks.clear();
        alto.seekTimes.clear();
        async.elapse(const Duration(seconds: 6));

        expect(alto.seeks.length, greaterThanOrEqualTo(2));
        // The master (soprano) plays at rate 1 from 0, never re-seeked, so
        // its position at any moment is the time since play.
        final masterAtSecond = alto.seekTimes[1].difference(start);
        final lead = alto.seeks[1] - masterAtSecond;
        expect(lead, greaterThan(Duration.zero));
        expect(lead, lessThanOrEqualTo(JustAudioPlaybackEngine.maxSeekLead));
      });
    });

    test('a shorter track that has ended is left at its end', () {
      fakeAsync((async) {
        final bass = FakeAudioPlayer(length: const Duration(seconds: 2));
        final r = rig(overrides: {VoicePart.bass: bass});
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.flushMicrotasks();
        bass.seeks.clear();
        async.elapse(const Duration(seconds: 6));
        expect(bass.seeks, isEmpty);
      });
    });
  });

  test('dispose releases every player and stops the drift timer', () {
    fakeAsync((async) {
      final r = rig();
      unawaited(r.engine.load(tracks()));
      async.flushMicrotasks();
      unawaited(r.engine.play());
      async.flushMicrotasks();
      unawaited(r.engine.dispose());
      async.flushMicrotasks();
      expect(r.players.values.every((p) => p.disposed), isTrue);
      expect(async.periodicTimerCount, 0);
    });
  });
}
