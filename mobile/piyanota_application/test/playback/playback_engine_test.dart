import 'dart:async';

import 'dart:math';

import 'package:audio_session/audio_session.dart';
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
    this.loadHangs = false,
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

  /// [setAudioSource] never completes (a stalled download).
  final bool loadHangs;

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
    if (loadHangs) await Completer<void>().future;
    loadedUri = (audioSource as UriAudioSource).uri;
    return length;
  }

  @override
  Duration? get duration => length;

  /// Replays [length] by default, as just_audio's BehaviorSubject does; a
  /// test can push a null first (length not known yet) through this.
  StreamController<Duration?>? durations;

  @override
  Stream<Duration?> get durationStream =>
      durations?.stream ?? Stream.value(length);

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

  /// Reached the end of the track. Like real just_audio, `playing` stays
  /// true (only the processing state says it ended), so whatever stops the
  /// player afterwards is the engine's doing.
  void complete() {
    _anchor = length;
    if (playing) _startedAt = clock.now();
    _states.add(ProcessingState.completed);
  }

  /// Only the completed event, as a late one from before a seek arrives.
  void emitCompleted() => _states.add(ProcessingState.completed);

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
  FakeAudioPlayer click,
  List<Object> clickFailures,
})
rig({
  Map<VoicePart, FakeAudioPlayer> overrides = const {},
  FakeAudioPlayer? click,
  List<FakeAudioPlayer> laterClicks = const [],
  AudioSession? session,
}) {
  final players = {
    for (final voice in VoicePart.values)
      voice: overrides[voice] ?? FakeAudioPlayer(),
  };
  final clickPlayer = click ?? FakeAudioPlayer();
  // The click player is made last, by attachClick after load.
  final queue = [
    for (final voice in VoicePart.values) players[voice]!,
    clickPlayer,
    // Re-attached clicks after a detachClick, in order.
    ...laterClicks,
  ];
  final engine = JustAudioPlaybackEngine(
    playerFactory: queue.removeAt0,
    audioSession: session == null ? null : Future.value(session),
  );
  final playing = <bool>[];
  final failures = <PlaybackFailure>[];
  final clickFailures = <Object>[];
  engine.playingChanges.listen(playing.add);
  engine.failures.listen(failures.add);
  engine.clickFailures.listen(clickFailures.add);
  return (
    engine: engine,
    players: players,
    playing: playing,
    failures: failures,
    click: clickPlayer,
    clickFailures: clickFailures,
  );
}

final Uri _clickUri = Uri.file('/tmp/click.wav');

/// Focus and headphone events raised by hand; remembers its configuration.
class FakeAudioSession implements AudioSession {
  final StreamController<AudioInterruptionEvent> interruptions =
      StreamController.broadcast();
  final StreamController<void> noisy = StreamController.broadcast();
  AudioSessionConfiguration? configured;

  /// Every setActive call, in order; [grant] is what it answers.
  final List<bool> activeCalls = [];
  bool grant = true;

  @override
  Future<bool> setActive(
    bool active, {
    AVAudioSessionSetActiveOptions? avAudioSessionSetActiveOptions,
    AndroidAudioFocusGainType? androidAudioFocusGainType,
    AndroidAudioAttributes? androidAudioAttributes,
    bool? androidWillPauseWhenDucked,
    AudioSessionConfiguration fallbackConfiguration =
        const AudioSessionConfiguration.music(),
  }) async {
    activeCalls.add(active);
    return grant;
  }

  @override
  Stream<AudioInterruptionEvent> get interruptionEventStream =>
      interruptions.stream;

  @override
  Stream<void> get becomingNoisyEventStream => noisy.stream;

  @override
  Future<void> configure(AudioSessionConfiguration configuration) async =>
      configured = configuration;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// Every transported player's offset from the master, and whether each
/// one's playing state matches the engine's.
void expectInStep(
  JustAudioPlaybackEngine engine,
  List<FakeAudioPlayer> players, {
  Duration tolerance = JustAudioPlaybackEngine.resyncTrigger,
}) {
  for (final (i, player) in players.indexed) {
    expect(player.playing, engine.playing, reason: 'player $i playing');
    expect(
      (player.position - engine.position).abs(),
      lessThanOrEqualTo(tolerance),
      reason: 'player $i offset',
    );
  }
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

    test('one voice failing to load leaves it out; the rest play', () {
      fakeAsync((async) {
        final alto = FakeAudioPlayer(loadError: StateError('codec'));
        final r = rig(overrides: {VoicePart.alto: alto});
        Object? thrown;
        r.engine.load(tracks()).catchError((Object e) => thrown = e);
        async.flushMicrotasks();
        expect(thrown, isNull);
        expect(r.engine.unavailableVoices, {VoicePart.alto});
        expect(alto.disposed, isTrue);

        unawaited(r.engine.play());
        async.flushMicrotasks();
        expect(alto.playing, isFalse);
        for (final voice in [VoicePart.soprano, VoicePart.tenor]) {
          expect(r.players[voice]!.playing, isTrue, reason: voice.name);
        }
        unawaited(r.engine.dispose());
        async.flushMicrotasks();
        expect(r.players.values.every((p) => p.disposed), isTrue);
      });
    });

    test('a track that never loads times out into a failed voice', () {
      fakeAsync((async) {
        final alto = FakeAudioPlayer(loadHangs: true);
        final r = rig(overrides: {VoicePart.alto: alto});
        var done = false;
        unawaited(r.engine.load(tracks()).then((_) => done = true));
        async.elapse(
          JustAudioPlaybackEngine.loadTimeout - const Duration(seconds: 1),
        );
        expect(done, isFalse);
        async.elapse(const Duration(seconds: 1));
        expect(done, isTrue);
        expect(r.engine.unavailableVoices, {VoicePart.alto});
        expect(alto.disposed, isTrue);
        unawaited(r.engine.play());
        async.flushMicrotasks();
        expect(r.players[VoicePart.soprano]!.playing, isTrue);
      });
    });

    test('every track hanging is a PlaybackLoadException, not a spinner', () {
      fakeAsync((async) {
        final r = rig(
          overrides: {
            for (final voice in VoicePart.values)
              voice: FakeAudioPlayer(loadHangs: true),
          },
        );
        Object? thrown;
        r.engine.load(tracks()).catchError((Object e) => thrown = e);
        async.elapse(JustAudioPlaybackEngine.loadTimeout);
        expect(thrown, isA<PlaybackLoadException>());
      });
    });

    test('the longest track failing to load: the next longest is master', () {
      fakeAsync((async) {
        final r = rig(
          overrides: {
            VoicePart.tenor: FakeAudioPlayer(
              length: const Duration(seconds: 12),
              loadError: StateError('codec'),
            ),
            VoicePart.bass: FakeAudioPlayer(
              length: const Duration(seconds: 11),
            ),
          },
        );
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        expect(r.engine.masterVoice, VoicePart.bass);
        expect(r.engine.duration, const Duration(seconds: 11));
      });
    });

    test('every voice failing to load is a PlaybackLoadException', () {
      fakeAsync((async) {
        final r = rig(
          overrides: {
            for (final voice in VoicePart.values)
              voice: FakeAudioPlayer(loadError: StateError('codec')),
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
        // complete() leaves the master "playing", like just_audio: only the
        // engine's completion handling stops it.
        expect(r.players[VoicePart.soprano]!.playing, isTrue);
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
        expect(r.failures.single.fatal, isFalse);
        expect(r.engine.unavailableVoices, {VoicePart.alto});
        // The others play on.
        expect(r.players[VoicePart.soprano]!.playing, isTrue);
        expect(r.engine.playing, isTrue);

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

    test('the master failing mid-play hands the clock to the longest left', () {
      fakeAsync((async) {
        final r = rig(
          overrides: {
            VoicePart.tenor: FakeAudioPlayer(
              length: const Duration(seconds: 9),
            ),
          },
        );
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        expect(r.engine.masterVoice, VoicePart.soprano);
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 2));

        r.players[VoicePart.soprano]!.raise();
        async.flushMicrotasks();
        expect(r.failures.single.voice, VoicePart.soprano);
        expect(r.failures.single.fatal, isFalse);
        // Alto: 10 s like bass, and first in S/A/T/B order.
        expect(r.engine.masterVoice, VoicePart.alto);
        expect(r.engine.playing, isTrue);
        expect(r.playing, [true]);
        for (final voice in [VoicePart.alto, VoicePart.tenor, VoicePart.bass]) {
          expect(r.players[voice]!.playing, isTrue, reason: voice.name);
        }
        expect(r.engine.position, r.players[VoicePart.alto]!.position);

        // The new master drives completion and the drift check.
        final bass = r.players[VoicePart.bass]!..setRate(1.1);
        async.elapse(const Duration(seconds: 3));
        expect(r.engine.resyncCount, greaterThan(0));
        expect(bass.seeks, isNotEmpty);
        r.players[VoicePart.alto]!.complete();
        async.flushMicrotasks();
        expect(r.players.values.any((p) => p.playing), isFalse);
        expect(r.playing.last, isFalse);
      });
    });

    test('the master failing after a shorter follower ended stops there', () {
      fakeAsync((async) {
        final r = rig(
          overrides: {
            VoicePart.soprano: FakeAudioPlayer(
              length: const Duration(seconds: 10),
            ),
            for (final voice in [VoicePart.alto, VoicePart.tenor])
              voice: FakeAudioPlayer(length: const Duration(seconds: 1)),
            VoicePart.bass: FakeAudioPlayer(loadError: StateError('codec')),
          },
        );
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 2));

        r.players[VoicePart.soprano]!.raise();
        async.flushMicrotasks();
        expect(r.engine.masterVoice, VoicePart.alto);
        expect(r.players.values.any((p) => p.playing), isFalse);
        expect(r.playing.last, isFalse);
      });
    });

    test('the last voice failing is fatal and stops playback', () {
      fakeAsync((async) {
        final r = rig(
          overrides: {
            for (final voice in [
              VoicePart.soprano,
              VoicePart.alto,
              VoicePart.tenor,
            ])
              voice: FakeAudioPlayer(loadError: StateError('codec')),
          },
        );
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.flushMicrotasks();

        r.players[VoicePart.bass]!.raise();
        async.flushMicrotasks();
        expect(r.failures.single.fatal, isTrue);
        expect(r.playing.last, isFalse);
        // No clock left: nothing further plays or drifts.
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 2));
        expect(r.players.values.any((p) => p.playing), isFalse);
        expect(async.periodicTimerCount, 0);
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

    test('a steady offset between the tolerance and the trigger stays', () {
      fakeAsync((async) {
        final alto = FakeAudioPlayer();
        final r = rig(overrides: {VoicePart.alto: alto});
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.flushMicrotasks();

        // Put the alto 20 ms ahead, then keep it there.
        alto.setRate(1.2);
        async.elapse(const Duration(milliseconds: 100));
        alto.setRate(1);
        final offset = alto.position - r.engine.position;
        expect(
          offset,
          allOf(
            greaterThan(JustAudioPlaybackEngine.inStepTolerance),
            lessThan(JustAudioPlaybackEngine.resyncTrigger),
          ),
        );
        async.elapse(const Duration(seconds: 8));
        // Accepted, by design (see resyncTrigger): never corrected.
        expect(r.engine.resyncCount, 0);
        expect(alto.position - r.engine.position, offset);
      });
    });

    test('a failed re-seek does not feed the seek-latency estimate', () {
      fakeAsync((async) {
        final alto = FakeAudioPlayer(rate: 1.2)
          ..seekDelay = const Duration(milliseconds: 400);
        final tenor = FakeAudioPlayer(rate: 1.2);
        final r = rig(
          overrides: {VoicePart.alto: alto, VoicePart.tenor: tenor},
        );
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.elapse(alto.seekDelay);
        // From now on the alto's slow seeks fail.
        alto.seekError = StateError('gone');
        tenor.seeks.clear();
        final start = clock.now();
        tenor.seekTimes.clear();
        DateTime? altoFailedAt;
        r.engine.failures.listen((_) => altoFailedAt ??= clock.now());
        async.elapse(const Duration(seconds: 6));
        expect(r.failures.map((f) => f.voice), [VoicePart.alto]);
        // Only a tenor re-seek computed *after* the alto's seek failed can
        // show whether that failed 400 ms seek fed the estimate: one issued
        // in the same pass as the alto's had its lead fixed beforehand.
        final later = [
          for (var i = 0; i < tenor.seeks.length; i++)
            if (tenor.seekTimes[i].isAfter(altoFailedAt!))
              (tenor.seeks[i], tenor.seekTimes[i]),
        ];
        expect(later, isNotEmpty);
        // The tenor's seeks land instantly; had the failed seek counted,
        // these would lead the master by ~200 ms (0.5 x 400 ms x 1.0).
        for (final (target, at) in later) {
          expect(target - at.difference(start), Duration.zero);
        }
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

  group('durationKnown', () {
    test('known at load: returned at once', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        Duration? got;
        unawaited(r.engine.durationKnown().then((d) => got = d));
        async.flushMicrotasks();
        expect(got, const Duration(seconds: 10));
      });
    });

    test('reported late: waits for it', () {
      fakeAsync((async) {
        final master = FakeAudioPlayer()..durations = StreamController();
        final r = rig(overrides: {VoicePart.soprano: master});
        unawaited(r.engine.load(tracks({VoicePart.soprano})));
        async.flushMicrotasks();
        Duration? got;
        unawaited(r.engine.durationKnown().then((d) => got = d));
        master.durations!.add(null);
        async.elapse(const Duration(seconds: 2));
        expect(got, isNull);
        master.durations!.add(const Duration(seconds: 7));
        async.flushMicrotasks();
        expect(got, const Duration(seconds: 7));
      });
    });

    test('never reported: zero after the load timeout', () {
      fakeAsync((async) {
        final master = FakeAudioPlayer()..durations = StreamController();
        final r = rig(overrides: {VoicePart.soprano: master});
        unawaited(r.engine.load(tracks({VoicePart.soprano})));
        async.flushMicrotasks();
        Duration? got;
        unawaited(r.engine.durationKnown().then((d) => got = d));
        async.elapse(JustAudioPlaybackEngine.loadTimeout);
        expect(got, Duration.zero);
      });
    });
  });

  group('click track (PIYA-209/210)', () {
    test('attached mid-play: caught up, at speed and volume, then driven '
        'by the transport like a follower', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.setSpeed(1.5));
        unawaited(r.engine.setClickVolume(0.4));
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 2));

        bool? attached;
        unawaited(r.engine.attachClick(_clickUri).then((v) => attached = v));
        async.flushMicrotasks();
        expect(attached, isTrue);
        expect(r.click.loadedUri, _clickUri);
        expect(r.click.speedSet, 1.5);
        expect(r.click.volumeSet, 0.4);
        expect(r.click.seeks.single, const Duration(seconds: 3));
        expect(r.click.playing, isTrue);
        expect(r.engine.masterVoice, VoicePart.soprano);

        unawaited(r.engine.pause());
        async.flushMicrotasks();
        expect(r.click.playing, isFalse);
        unawaited(r.engine.seek(const Duration(seconds: 1)));
        unawaited(r.engine.setSpeed(0.5));
        unawaited(r.engine.setClickVolume(0.8));
        async.flushMicrotasks();
        expect(r.click.seeks.last, const Duration(seconds: 1));
        expect(r.click.speedSet, 0.5);
        expect(r.click.volumeSet, 0.8);
        unawaited(r.engine.play());
        async.flushMicrotasks();
        expect(r.click.playing, isTrue);

        unawaited(r.engine.dispose());
        async.flushMicrotasks();
        expect(r.click.disposed, isTrue);
      });
    });

    test('a seek, speed or level change during the catch-up seek reaches '
        'the click', () {
      fakeAsync((async) {
        final r = rig(click: FakeAudioPlayer());
        r.click.seekDelay = const Duration(milliseconds: 100);
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        bool? attached;
        unawaited(r.engine.attachClick(_clickUri).then((v) => attached = v));
        async.elapse(const Duration(milliseconds: 50));
        // The catch-up seek (to 0) is in flight: the transport skips the
        // click for now.
        expect(r.click.seeks, [Duration.zero]);
        unawaited(r.engine.setSpeed(1.5));
        unawaited(r.engine.setClickVolume(0.3));
        unawaited(r.engine.seek(const Duration(seconds: 4)));
        async.elapse(const Duration(milliseconds: 300));
        expect(attached, isTrue);
        expect(r.click.speedSet, 1.5);
        expect(r.click.volumeSet, 0.3);
        expect(r.click.seeks.last, const Duration(seconds: 4));
        expect(r.click.position, r.engine.position);
      });
    });

    test('a speed change in every catch-up round still reaches the click', () {
      fakeAsync((async) {
        final r = rig(click: FakeAudioPlayer());
        r.click.seekDelay = const Duration(milliseconds: 100);
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        bool? attached;
        unawaited(r.engine.attachClick(_clickUri).then((v) => attached = v));
        // One change per catch-up seek, as a slider drag would send: the
        // last lands during the final round, after its speed check.
        for (final speed in [1.2, 1.4, 1.6]) {
          async.elapse(const Duration(milliseconds: 50));
          unawaited(r.engine.setSpeed(speed));
          async.elapse(const Duration(milliseconds: 50));
        }
        async.elapse(const Duration(milliseconds: 100));
        expect(attached, isTrue);
        expect(
          r.click.seeks,
          hasLength(JustAudioPlaybackEngine.clickSettleRounds),
        );
        expect(r.click.speedSet, 1.6);
      });
    });

    test('play() while the click is attaching starts it once, aligned', () {
      fakeAsync((async) {
        // The alto's slow seek keeps play() in its alignment step while
        // the click's catch-up seek lands.
        final alto = FakeAudioPlayer()
          ..seekDelay = const Duration(milliseconds: 300);
        final r = rig(overrides: {VoicePart.alto: alto});
        r.click.seekDelay = const Duration(milliseconds: 100);
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.seek(const Duration(seconds: 2)));
        async.elapse(const Duration(milliseconds: 300));

        unawaited(r.engine.attachClick(_clickUri));
        unawaited(r.engine.play());
        async.elapse(const Duration(milliseconds: 250));
        // Ready, but play() hasn't started anything yet.
        expect(r.engine.clickAttached, isTrue);
        expect(r.click.playCalls, 0);
        expect(r.players[VoicePart.soprano]!.playing, isFalse);

        async.elapse(const Duration(milliseconds: 100));
        expect(r.players[VoicePart.soprano]!.playing, isTrue);
        expect(r.click.playCalls, 1);
        expect(r.click.position, r.engine.position);
      });
    });

    test('the master starting during the catch-up seek: the click is '
        're-seeked ahead before it starts, then started once', () {
      fakeAsync((async) {
        final r = rig();
        r.click.seekDelay = const Duration(milliseconds: 100);
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.attachClick(_clickUri));
        async.elapse(const Duration(milliseconds: 50));
        unawaited(r.engine.play());
        async.flushMicrotasks();
        // play() ran before the click was ready, so only attach starts it.
        expect(r.click.playCalls, 0);
        async.elapse(const Duration(milliseconds: 200));
        expect(r.engine.clickAttached, isTrue);
        expect(r.click.seeks, hasLength(2));
        expect(r.click.playCalls, 1);
        // Aimed ahead by the seek latency known so far (half the real 100
        // ms after one sample), so closer than an unaimed seek would land.
        expect(
          (r.click.position - r.engine.position).abs(),
          lessThan(r.click.seekDelay),
        );
        // The drift check (F8a's 25 ms trigger) finishes the job.
        async.elapse(const Duration(seconds: 2));
        expect(
          (r.click.position - r.engine.position).abs(),
          lessThanOrEqualTo(JustAudioPlaybackEngine.resyncTrigger),
        );
      });
    });

    test('PIYA-209-V2.3: a silent click attached before play runs with the '
        'voices, so raising its level mid-play is heard at once with no '
        'pause, seek or restart of any player', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        // Metronome off at load: the controller sends 0 before attaching.
        unawaited(r.engine.setClickVolume(0));
        unawaited(r.engine.attachClick(_clickUri));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 2));
        expect(r.click.playing, isTrue);
        expect(r.click.volumeSet, 0);
        final all = [...r.players.values, r.click];
        final before = [
          for (final p in all) (p.playCalls, p.pauseCalls, p.seeks.length),
        ];

        unawaited(r.engine.setClickVolume(1));
        async.flushMicrotasks();
        expect(r.click.volumeSet, 1);
        expect(r.click.playing, isTrue);
        expect(
          (r.click.position - r.players[VoicePart.soprano]!.position).abs(),
          lessThanOrEqualTo(JustAudioPlaybackEngine.inStepTolerance),
        );
        expect([
          for (final p in all) (p.playCalls, p.pauseCalls, p.seeks.length),
        ], before);

        unawaited(r.engine.setClickVolume(0));
        async.flushMicrotasks();
        expect(r.click.volumeSet, 0);
      });
    });

    test('attached while paused: placed at the position, not started', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.seek(const Duration(seconds: 4)));
        async.flushMicrotasks();
        unawaited(r.engine.attachClick(_clickUri));
        async.flushMicrotasks();
        expect(r.click.seeks.single, const Duration(seconds: 4));
        expect(r.click.playing, isFalse);
      });
    });

    test('a drifting click is pulled back, but is never the master', () {
      fakeAsync((async) {
        final r = rig(
          click: FakeAudioPlayer(
            length: const Duration(seconds: 30),
            rate: 1.1,
          ),
        );
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.attachClick(_clickUri));
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 6));
        expect(r.engine.resyncCount, greaterThan(0));
        expect(r.engine.masterVoice, VoicePart.soprano);
        expect(r.engine.duration, const Duration(seconds: 10));
        expect(
          (r.click.position - r.engine.position).abs(),
          lessThanOrEqualTo(
            JustAudioPlaybackEngine.resyncTrigger +
                JustAudioPlaybackEngine.inStepTolerance,
          ),
        );
      });
    });

    test('a click that will not load is a click failure only', () {
      fakeAsync((async) {
        final r = rig(click: FakeAudioPlayer(loadError: StateError('codec')));
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        bool? attached;
        unawaited(r.engine.attachClick(_clickUri).then((v) => attached = v));
        async.flushMicrotasks();
        expect(attached, isFalse);
        expect(r.clickFailures, hasLength(1));
        expect(r.failures, isEmpty);
        expect(r.engine.unavailableVoices, isEmpty);
        expect(r.players.values.every((p) => p.playing), isTrue);
        unawaited(r.engine.dispose());
        async.flushMicrotasks();
        expect(r.click.disposed, isTrue);
      });
    });

    test('the click failing mid-play leaves the voices playing', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.attachClick(_clickUri));
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 1));
        expect(r.click.playing, isTrue);

        r.click.raise();
        async.flushMicrotasks();
        expect(r.clickFailures, hasLength(1));
        expect(r.failures, isEmpty);
        expect(r.engine.playing, isTrue);
        expect(r.players.values.every((p) => p.playing), isTrue);
        // No longer driven: a seek leaves it alone.
        final seeks = r.click.seeks.length;
        unawaited(r.engine.seek(const Duration(seconds: 2)));
        async.flushMicrotasks();
        expect(r.click.seeks, hasLength(seeks));
      });
    });

    test('a click that never loads times out into a click failure', () {
      fakeAsync((async) {
        final r = rig(click: FakeAudioPlayer(loadHangs: true));
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        bool? attached;
        unawaited(r.engine.attachClick(_clickUri).then((v) => attached = v));
        async.elapse(JustAudioPlaybackEngine.loadTimeout);
        expect(attached, isFalse);
        expect(r.clickFailures, hasLength(1));
        expect(r.failures, isEmpty);
      });
    });

    test('detach while an attach is still loading: the attach returns '
        'false and its late failure is not reported', () {
      fakeAsync((async) {
        final r = rig(click: FakeAudioPlayer(loadHangs: true));
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        bool? attached;
        unawaited(r.engine.attachClick(_clickUri).then((v) => attached = v));
        async.flushMicrotasks();
        unawaited(r.engine.detachClick());
        async.flushMicrotasks();
        expect(r.click.disposed, isTrue);
        // The hung load times out after the detach: not a click failure.
        async.elapse(JustAudioPlaybackEngine.loadTimeout);
        expect(attached, isFalse);
        expect(r.clickFailures, isEmpty);
        expect(r.engine.clickAttached, isFalse);
      });
    });

    test('detach during the catch-up seek: the attach returns false', () {
      fakeAsync((async) {
        final click = FakeAudioPlayer()
          ..seekDelay = const Duration(milliseconds: 200);
        final r = rig(click: click);
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        async.flushMicrotasks();
        bool? attached;
        unawaited(r.engine.attachClick(_clickUri).then((v) => attached = v));
        async.elapse(const Duration(milliseconds: 50));
        expect(attached, isNull);
        unawaited(r.engine.detachClick());
        async.elapse(const Duration(seconds: 1));
        expect(attached, isFalse);
        expect(click.playing, isFalse);
        expect(r.clickFailures, isEmpty);
        expect(r.engine.clickAttached, isFalse);
      });
    });

    test('an error from the old click after a detach is ignored', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.attachClick(_clickUri));
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 1));
        expect(r.click.playing, isTrue);
        unawaited(r.engine.detachClick());
        async.flushMicrotasks();
        r.click.raise();
        async.flushMicrotasks();
        expect(r.clickFailures, isEmpty);
        expect(r.failures, isEmpty);
        expect(r.engine.playing, isTrue);
      });
    });

    test('re-attach after a detach: the new click is driven, the old one '
        'is released and no longer driven', () {
      fakeAsync((async) {
        final second = FakeAudioPlayer();
        final r = rig(laterClicks: [second]);
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.setClickVolume(0.4));
        unawaited(r.engine.attachClick(_clickUri));
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 1));

        unawaited(r.engine.detachClick());
        async.flushMicrotasks();
        expect(r.click.disposed, isTrue);
        final again = Uri.file('/tmp/click2.wav');
        bool? attached;
        unawaited(r.engine.attachClick(again).then((v) => attached = v));
        async.elapse(const Duration(milliseconds: 100));
        expect(attached, isTrue);
        expect(r.engine.clickAttached, isTrue);
        expect(second.loadedUri, again);
        expect(second.playing, isTrue);
        // The last level is kept for the next click.
        expect(second.volumeSet, 0.4);
        unawaited(r.engine.pause());
        async.flushMicrotasks();
        expect(second.playing, isFalse);
        final oldSeeks = r.click.seeks.length;
        unawaited(r.engine.seek(const Duration(seconds: 3)));
        async.flushMicrotasks();
        expect(r.click.seeks, hasLength(oldSeeks));
        expect(second.seeks.last, const Duration(seconds: 3));
        // Its failures are reported as before.
        second.raise();
        async.flushMicrotasks();
        expect(r.clickFailures, hasLength(1));
      });
    });

    test('a failed attach holds the slot until a detach; then a new '
        'attach works', () {
      fakeAsync((async) {
        final second = FakeAudioPlayer();
        final r = rig(
          click: FakeAudioPlayer(loadError: StateError('codec')),
          laterClicks: [second],
        );
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        unawaited(r.engine.play());
        final results = <bool>[];
        unawaited(r.engine.attachClick(_clickUri).then(results.add));
        async.flushMicrotasks();
        expect(r.clickFailures, hasLength(1));
        // Still held by the dead player.
        unawaited(r.engine.attachClick(_clickUri).then(results.add));
        async.flushMicrotasks();
        expect(results, [false, false]);

        unawaited(r.engine.detachClick());
        async.flushMicrotasks();
        expect(r.click.disposed, isTrue);
        unawaited(r.engine.attachClick(_clickUri).then(results.add));
        async.elapse(const Duration(milliseconds: 100));
        expect(results, [false, false, true]);
        expect(second.playing, isTrue);
        expect(r.clickFailures, hasLength(1));
      });
    });

    test('a second click is refused (one per engine)', () {
      fakeAsync((async) {
        final r = rig();
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        final results = <bool>[];
        unawaited(r.engine.attachClick(_clickUri).then(results.add));
        async.flushMicrotasks();
        unawaited(r.engine.attachClick(_clickUri).then(results.add));
        async.flushMicrotasks();
        expect(results, [true, false]);
      });
    });
  });

  group('one transport path (F8a)', () {
    /// Four voices and an attached click, all loaded, 60 s long so nothing
    /// ends mid-test; [delays] are each player's seek latency (S/A/T/B,
    /// click).
    ({
      JustAudioPlaybackEngine engine,
      List<FakeAudioPlayer> all,
      Map<VoicePart, FakeAudioPlayer> players,
      FakeAudioPlayer click,
    })
    loaded(FakeAsync async, {List<int> delays = const [0, 0, 0, 0, 0]}) {
      FakeAudioPlayer make(int ms) =>
          FakeAudioPlayer(length: const Duration(seconds: 60))
            ..seekDelay = Duration(milliseconds: ms);
      final r = rig(
        overrides: {
          for (final (i, voice) in VoicePart.values.indexed)
            voice: make(delays[i]),
        },
        click: make(delays[4]),
      );
      unawaited(r.engine.load(tracks()));
      async.flushMicrotasks();
      unawaited(r.engine.attachClick(_clickUri));
      async.elapse(const Duration(seconds: 1));
      expect(r.engine.clickAttached, isTrue);
      return (
        engine: r.engine,
        all: [...r.players.values, r.click],
        players: r.players,
        click: r.click,
      );
    }

    for (final seed in [1, 8, 21]) {
      test('50 rapid play/pause/seek/skip/speed actions leave all four voices '
          'and the click aligned (seed $seed)', () {
        fakeAsync((async) {
          final random = Random(seed);
          final r = loaded(
            async,
            delays: [for (var i = 0; i < 5; i++) random.nextInt(120)],
          );
          const speeds = [0.5, 0.75, 1.0, 1.25, 1.5];
          for (var i = 0; i < 50; i++) {
            final position = r.engine.position;
            unawaited(switch (random.nextInt(6)) {
              0 => r.engine.play(),
              1 => r.engine.pause(),
              2 => r.engine.seek(Duration(milliseconds: random.nextInt(20000))),
              3 => r.engine.seek(
                position > const Duration(seconds: 5)
                    ? position - const Duration(seconds: 5)
                    : Duration.zero,
              ),
              4 => r.engine.seek(position + const Duration(seconds: 5)),
              _ => r.engine.setSpeed(speeds[random.nextInt(speeds.length)]),
            });
            // Some actions land on top of the last one's seeks, some after.
            async.elapse(Duration(milliseconds: random.nextInt(150)));
            if (i % 10 == 9) {
              // Each batch, once settled, is aligned too, playing or not.
              async.elapse(const Duration(seconds: 1));
              expectInStep(r.engine, r.all);
            }
          }
          unawaited(r.engine.play());
          async.elapse(const Duration(seconds: 1));
          expect(r.engine.playing, isTrue);
          expectInStep(r.engine, r.all);
          final speed = r.all.first.speedSet;
          expect(r.all.every((p) => p.speedSet == speed), isTrue);
          expect(r.engine.resyncCount, 0, reason: 'aligned by transport alone');
        });
      });
    }

    test('back 5 s while playing: one set plays, from the new position', () {
      fakeAsync((async) {
        final r = loaded(async, delays: [0, 80, 0, 40, 60]);
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 8));
        final plays = [for (final p in r.all) p.playCalls];
        final target = r.engine.position - const Duration(seconds: 5);

        unawaited(r.engine.seek(target));
        async.flushMicrotasks();
        // Old audio stopped before any seek, nothing restarted yet.
        expect(r.all.any((p) => p.playing), isFalse);
        expect(r.engine.playing, isTrue);
        expect(r.engine.position, target);
        async.elapse(const Duration(milliseconds: 79));
        expect(r.all.any((p) => p.playing), isFalse);
        async.elapse(const Duration(milliseconds: 1));
        // Every player started exactly once more, all at the target.
        expect(
          [for (final p in r.all) p.playCalls],
          [for (final n in plays) n + 1],
        );
        expectInStep(r.engine, r.all, tolerance: Duration.zero);
        expect(r.engine.position, target);
      });
    });

    test('rapid skips add up from the last target, not the stale audio', () {
      fakeAsync((async) {
        final r = loaded(async, delays: [100, 100, 100, 100, 100]);
        unawaited(r.engine.seek(const Duration(seconds: 20)));
        async.elapse(const Duration(seconds: 1));
        for (var i = 0; i < 3; i++) {
          unawaited(
            r.engine.seek(r.engine.position - const Duration(seconds: 5)),
          );
          async.elapse(const Duration(milliseconds: 10));
        }
        async.elapse(const Duration(seconds: 1));
        expect(r.engine.position, const Duration(seconds: 5));
        expectInStep(r.engine, r.all, tolerance: Duration.zero);
      });
    });

    test('a speed change while playing pauses, sets every player, restarts '
        'them together', () {
      fakeAsync((async) {
        final r = loaded(async, delays: [0, 50, 0, 0, 30]);
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 2));
        unawaited(r.engine.setSpeed(1.5));
        async.flushMicrotasks();
        expect(r.all.any((p) => p.playing), isFalse);
        expect(r.all.every((p) => p.speedSet == 1.5), isTrue);
        async.elapse(const Duration(milliseconds: 50));
        expectInStep(r.engine, r.all, tolerance: Duration.zero);
        expect(r.engine.playing, isTrue);
        // The same speed again is no step at all.
        final pauses = [for (final p in r.all) p.pauseCalls];
        unawaited(r.engine.setSpeed(1.5));
        async.flushMicrotasks();
        expect([for (final p in r.all) p.pauseCalls], pauses);
      });
    });

    test('a pause during a seek wins; a completion during a step is stale', () {
      fakeAsync((async) {
        final r = loaded(async, delays: [100, 0, 0, 0, 0]);
        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 2));
        unawaited(r.engine.seek(const Duration(seconds: 30)));
        async.elapse(const Duration(milliseconds: 20));
        // The master reports its end while its seek is still landing: the
        // seek moves it on, so the completion is stale.
        r.players[VoicePart.soprano]!.complete();
        async.elapse(const Duration(milliseconds: 200));
        expect(r.engine.playing, isTrue);
        expectInStep(r.engine, r.all, tolerance: Duration.zero);

        unawaited(r.engine.seek(const Duration(seconds: 10)));
        async.elapse(const Duration(milliseconds: 20));
        unawaited(r.engine.pause());
        async.elapse(const Duration(milliseconds: 200));
        expect(r.all.any((p) => p.playing), isFalse);
        expect(r.engine.position, const Duration(seconds: 10));
      });
    });

    test('focus loss and unplugged headphones pause every player; ducking '
        'does not; the session is set to music', () {
      fakeAsync((async) {
        final session = FakeAudioSession();
        final r = rig(session: session);
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();
        expect(
          session.configured?.androidAudioAttributes?.usage,
          AndroidAudioUsage.media,
        );
        expect(
          session.configured?.avAudioSessionCategory,
          AVAudioSessionCategory.playback,
        );

        unawaited(r.engine.play());
        async.flushMicrotasks();
        session.interruptions.add(
          AudioInterruptionEvent(true, AudioInterruptionType.duck),
        );
        async.flushMicrotasks();
        expect(r.engine.playing, isTrue);
        session.interruptions.add(
          AudioInterruptionEvent(true, AudioInterruptionType.pause),
        );
        async.flushMicrotasks();
        expect(r.engine.playing, isFalse);
        expect(r.players.values.any((p) => p.playing), isFalse);
        // The interruption ending doesn't resume on its own.
        session.interruptions.add(
          AudioInterruptionEvent(false, AudioInterruptionType.pause),
        );
        async.flushMicrotasks();
        expect(r.engine.playing, isFalse);

        unawaited(r.engine.play());
        async.flushMicrotasks();
        session.noisy.add(null);
        async.flushMicrotasks();
        expect(r.engine.playing, isFalse);
        expect(r.players.values.any((p) => p.playing), isFalse);
        expect(r.playing, [true, false, true, false]);
      });
    });

    test('play holds audio focus, pause and dispose release it, and denied '
        'focus does not start', () {
      fakeAsync((async) {
        final session = FakeAudioSession()..grant = false;
        final r = rig(session: session);
        unawaited(r.engine.load(tracks()));
        async.flushMicrotasks();

        unawaited(r.engine.play());
        async.flushMicrotasks();
        expect(session.activeCalls, [true]);
        expect(r.engine.playing, isFalse);
        expect(r.players.values.any((p) => p.playCalls > 0), isFalse);

        session.grant = true;
        unawaited(r.engine.play());
        async.flushMicrotasks();
        expect(r.engine.playing, isTrue);
        expect(r.players.values.every((p) => p.playing), isTrue);
        unawaited(r.engine.pause());
        async.flushMicrotasks();
        expect(session.activeCalls, [true, true, false]);

        unawaited(r.engine.play());
        async.flushMicrotasks();
        unawaited(r.engine.dispose());
        async.flushMicrotasks();
        expect(session.activeCalls, [true, true, false, true, false]);
      });
    });

    test('a completion while paused, or a late one after a seek back, is '
        'ignored', () {
      fakeAsync((async) {
        final r = loaded(async);
        final master = r.players[VoicePart.soprano]!;
        unawaited(r.engine.seek(const Duration(seconds: 20)));
        async.elapse(const Duration(seconds: 1));
        final pauses = [for (final p in r.all) p.pauseCalls];
        master.complete();
        async.flushMicrotasks();
        expect([for (final p in r.all) p.pauseCalls], pauses);

        unawaited(r.engine.play());
        async.elapse(const Duration(seconds: 1));
        // The end event arrives after the master is already playing from
        // well before its end again.
        master.emitCompleted();
        async.flushMicrotasks();
        expect(r.engine.playing, isTrue);
        expect(r.all.every((p) => p.playing), isTrue);
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
