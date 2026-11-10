import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:audio_session/audio_session.dart';
import 'package:flutter/foundation.dart';

import '../models/voice_part.dart';
import 'live_synth.dart';
import 'midi_render_cache.dart' show kVoiceChannel;
import 'midi_synth.dart';
import 'midi_voice_split.dart' show midiTotalTicks;
import 'playback_engine.dart';

const int _kPpq = 480;
const int _kMsPerMinute = 60000;
const int _kClickChannel = 9;
const int _kMaxLevel = 127;
const Duration _kEndPoll = Duration(milliseconds: 100);

/// Plays the combined MIDI through ONE FluidSynth synth and ONE audio
/// output, so every voice and the click share a single clock: nothing can
/// drift, so nothing is ever re-seeked (the cause of the audible chops with
/// five just_audio players). Level and mute are MIDI CC7 per channel. The
/// tempo is already in the file ([bpm] is only used to turn ticks into
/// time), so changing it means a new engine on a re-planned file, never
/// time-stretching.
class LiveSynthPlaybackEngine implements PlaybackEngine {
  LiveSynthPlaybackEngine({
    required this.sf2Path,
    required this.midPath,
    required this.bpm,
    Future<AudioSession>? audioSession,
    Future<LiveSynth> Function(String sf2, String mid) open = _open,
  }) : _audioSession = audioSession,
       _openSynth = open;

  final String sf2Path;
  final String midPath;
  final int bpm;
  final Future<AudioSession>? _audioSession;
  final Future<LiveSynth> Function(String sf2, String mid) _openSynth;

  LiveSynth? _synth;
  int _totalTicks = 0;
  final _playing = StreamController<bool>.broadcast();
  final _failures = StreamController<PlaybackFailure>.broadcast();
  final _clickFailures = StreamController<Object>.broadcast();
  final List<StreamSubscription<Object?>> _subscriptions = [];
  Timer? _poll;
  bool _wantPlaying = false;
  bool _disposed = false;

  /// The open synth, for the virtual piano; null before load / after dispose.
  LiveSynth? get liveSynth => _synth;
  bool _finished = false;
  // False between play() and the native player really starting: until then
  // synth.tick is stale, so position and pause use _resumeTick.
  bool _started = false;
  bool _hasClick = false;
  int _resumeTick = 0;
  double _clickVolume = 0.5;
  final Map<VoicePart, double> _volumes = {};

  static Future<LiveSynth> _open(String sf2, String mid) =>
      LiveSynth.open(sf2Path: sf2, midPath: mid);

  Duration _toTime(int tick) =>
      Duration(microseconds: tick * _kMsPerMinute * 1000 ~/ (bpm * _kPpq));

  int _toTick(Duration d) =>
      d.inMicroseconds * bpm * _kPpq ~/ (_kMsPerMinute * 1000);

  /// The voice URIs are ignored (they only name which voices exist): the
  /// notes come from [midPath]. Throws [PlaybackLoadException] when the
  /// native synth or its audio output cannot start.
  @override
  Future<void> load(Map<VoicePart, Uri> tracks) async {
    try {
      _totalTicks = midiTotalTicks(await File(midPath).readAsBytes());
      _synth = await _openSynth(sf2Path, midPath);
    } on Object catch (e) {
      throw PlaybackLoadException(e);
    }
    if (_disposed) {
      _synth?.close();
      return;
    }
    for (final voice in VoicePart.values) {
      _applyVoice(voice);
    }
    _applyClick();
    if (_audioSession case final pending?) unawaited(_watchFocus(pending));
  }

  Future<void> _watchFocus(Future<AudioSession> pending) async {
    try {
      final session = await pending;
      if (_disposed) return;
      _subscriptions
        ..add(
          session.interruptionEventStream.listen((event) {
            if (event.begin && event.type != AudioInterruptionType.duck) {
              unawaited(pause());
            }
          }),
        )
        ..add(session.becomingNoisyEventStream.listen((_) => pause()));
      await session.configure(const AudioSessionConfiguration.music());
    } on Object catch (e) {
      debugPrint('Playback: audio session not set up: $e');
    }
  }

  @override
  Set<VoicePart> get unavailableVoices => const {};

  @override
  Duration get position {
    final synth = _synth;
    if (synth == null) return Duration.zero;
    final tick = _wantPlaying && _started && !_finished
        ? synth.tick
        : _resumeTick;
    return _toTime(math.min(tick, _totalTicks));
  }

  @override
  Duration get duration {
    final synth = _synth;
    return synth == null ? Duration.zero : _toTime(_totalTicks);
  }

  @override
  Future<Duration> durationKnown() async => duration;

  @override
  bool get playing => _wantPlaying;

  @override
  Stream<bool> get playingChanges => _playing.stream;

  @override
  Stream<PlaybackFailure> get failures => _failures.stream;

  @override
  Stream<Object> get clickFailures => _clickFailures.stream;

  void _setPlaying(bool value) {
    if (_wantPlaying == value) return;
    _wantPlaying = value;
    _playing.add(value);
  }

  @override
  Future<void> play() async {
    final synth = _synth;
    if (_disposed || synth == null || _wantPlaying) return;
    _setPlaying(true);
    if (!await _setActive(true)) {
      debugPrint('Playback: audio focus denied; not starting');
      _setPlaying(false);
      return;
    }
    if (_disposed || !_wantPlaying) return;
    // After the focus check, so a denied focus keeps the position.
    if (_finished || _resumeTick >= _totalTicks) {
      synth.reset();
      _resumeTick = 0;
      _finished = false;
    }
    synth.seekTick(_resumeTick);
    if (!synth.play()) {
      _setPlaying(false);
      unawaited(_setActive(false));
      _failures.add(
        PlaybackFailure(
          VoicePart.values.first,
          StateError('FluidSynth could not start the player'),
          fatal: true,
        ),
      );
      return;
    }
    _started = true;
    _poll?.cancel();
    _poll = Timer.periodic(_kEndPoll, (_) => _checkEnd());
  }

  void _checkEnd() {
    final synth = _synth;
    if (synth == null || !_wantPlaying) return;
    if (!synth.isPlaying) {
      _finished = true;
      _started = false;
      _resumeTick = _totalTicks;
      _poll?.cancel();
      _setPlaying(false);
      unawaited(_setActive(false));
    }
  }

  Future<bool> _setActive(bool active) async {
    final pending = _audioSession;
    if (pending == null) return true;
    try {
      return await (await pending).setActive(active);
    } on Object catch (e) {
      debugPrint('Playback: audio session setActive($active) failed: $e');
      return true;
    }
  }

  @override
  Future<void> pause() async {
    final synth = _synth;
    if (synth == null) return;
    if (_wantPlaying && _started && !_finished) _resumeTick = synth.tick;
    _started = false;
    _poll?.cancel();
    _setPlaying(false);
    synth.pause();
    unawaited(_setActive(false));
  }

  @override
  Future<void> seek(Duration position) async {
    final synth = _synth;
    if (synth == null) return;
    final tick = _toTick(position).clamp(0, _totalTicks);
    if (_finished) {
      synth.reset();
      _finished = false;
    }
    _resumeTick = tick;
    // While playing the new position takes effect at once; while paused it
    // is applied by the next play().
    if (_wantPlaying) synth.seekTick(tick);
  }

  /// CC7 is squared by the synth, so the linear level the Mixer shows maps
  /// through a square root to sound like the same loudness step.
  static int _levelFor(double volume) =>
      (math.sqrt(volume.clamp(0.0, 1.0)) * _kMaxLevel).round();

  void _applyVoice(VoicePart voice) =>
      _synth?.setLevel(kVoiceChannel[voice]!, _levelFor(_volumes[voice] ?? 0));

  void _applyClick() =>
      _synth?.setLevel(_kClickChannel, _hasClick ? _levelFor(_clickVolume) : 0);

  @override
  Future<void> setVolume(VoicePart voice, double volume) async {
    _volumes[voice] = volume;
    _applyVoice(voice);
  }

  /// The tempo is in the file; only the neutral speed is meaningful here.
  @override
  Future<void> setSpeed(double speed) async {
    if (speed != 1) debugPrint('Live synth ignores speed $speed');
  }

  /// The click is part of the file (channel 9): attached means audible.
  @override
  Future<bool> attachClick(Uri track) async {
    _hasClick = true;
    _applyClick();
    return true;
  }

  @override
  Future<void> detachClick() async {
    _hasClick = false;
    _applyClick();
  }

  @override
  Future<void> setClickVolume(double volume) async {
    _clickVolume = volume;
    _applyClick();
  }

  @override
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _poll?.cancel();
    _wantPlaying = false;
    for (final s in _subscriptions) {
      unawaited(s.cancel());
    }
    _synth?.close();
    _synth = null;
    unawaited(_setActive(false));
    await Future.wait([
      _playing.close(),
      _failures.close(),
      _clickFailures.close(),
    ]);
  }
}

/// True when [e] means the native live synth cannot be used at all (not a
/// bug worth reporting).
bool isLiveSynthUnavailable(Object e) =>
    e is MidiSynthUnavailable ||
    (e is PlaybackLoadException && e.cause is MidiSynthUnavailable);
