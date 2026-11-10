import 'dart:ffi';
import 'dart:io';
import 'dart:isolate';

import 'package:ffi/ffi.dart';

import 'midi_synth.dart';

const String _kSynthLib = 'libpiyanota_synth.so';
const int kLiveErrDriver = 8;
const int _kFluidOk = 0;

typedef _OpenC = Pointer<Void> Function(
    Pointer<Utf8>, Pointer<Utf8>, Pointer<Int32>);
typedef _HandleIntC = Int32 Function(Pointer<Void>);
typedef _HandleInt = int Function(Pointer<Void>);
typedef _SeekC = Int32 Function(Pointer<Void>, Int32);
typedef _Seek = int Function(Pointer<Void>, int);
typedef _LevelC = Void Function(Pointer<Void>, Int32, Int32);
typedef _Level = void Function(Pointer<Void>, int, int);
typedef _NoteC = Void Function(Pointer<Void>, Int32, Int32, Int32);
typedef _Note = void Function(Pointer<Void>, int, int, int);
typedef _CloseC =Void Function(Pointer<Void>);
typedef _Close = void Function(Pointer<Void>);

DynamicLibrary _openLib() {
  if (!Platform.isAndroid) throw const MidiSynthUnavailable('not Android');
  try {
    return DynamicLibrary.open(_kSynthLib);
  } on ArgumentError catch (e) {
    throw MidiSynthUnavailable('$e');
  }
}

/// One FluidSynth synth + player + audio output (the native `piya_live`).
/// A single audio clock for all voices; see piyanota_synth.c.
class LiveSynth {
  LiveSynth._(DynamicLibrary lib, this._h)
    : _play = lib.lookupFunction<_HandleIntC, _HandleInt>('piya_live_play'),
      _reset = lib.lookupFunction<_HandleIntC, _HandleInt>('piya_live_reset'),
      _pause = lib.lookupFunction<_HandleIntC, _HandleInt>('piya_live_pause'),
      _seek = lib.lookupFunction<_SeekC, _Seek>('piya_live_seek'),
      _tick = lib.lookupFunction<_HandleIntC, _HandleInt>('piya_live_tick'),
      _total = lib.lookupFunction<_HandleIntC, _HandleInt>(
        'piya_live_total_ticks',
      ),
      _isPlaying = lib.lookupFunction<_HandleIntC, _HandleInt>(
        'piya_live_is_playing',
      ),
      _level = lib.lookupFunction<_LevelC, _Level>('piya_live_set_level'),
      _note = lib.lookupFunction<_NoteC, _Note>('piya_live_note'),
      _notesOff = lib.lookupFunction<_NoteC, _Note>('piya_live_notes_off'),
      _close = lib.lookupFunction<_CloseC, _Close>('piya_live_close');

  final Pointer<Void> _h;
  final _HandleInt _play, _pause, _reset, _tick, _total, _isPlaying;
  final _Seek _seek;
  final _Level _level;
  final _Note _note, _notesOff;
  final _Close _close;
  bool _closed = false;

  /// Opens off the UI isolate (loading the 32 MB soundfont blocks for a
  /// while). The native handle is plain memory, so its address crosses
  /// isolates. Throws [MidiSynthUnavailable] / [MidiSynthError].
  static Future<LiveSynth> open({
    required String sf2Path,
    required String midPath,
  }) async {
    final int address = await Isolate.run<int>(() {
      final DynamicLibrary lib = _openLib();
      final open = lib.lookupFunction<_OpenC, _OpenC>('piya_live_open');
      final sf2 = sf2Path.toNativeUtf8();
      final mid = midPath.toNativeUtf8();
      final err = calloc<Int32>();
      try {
        final Pointer<Void> h = open(sf2, mid, err);
        if (h == nullptr) throw MidiSynthError(err.value);
        return h.address;
      } finally {
        calloc.free(sf2);
        calloc.free(mid);
        calloc.free(err);
      }
    });
    return LiveSynth._(_openLib(), Pointer<Void>.fromAddress(address));
  }

  /// False when FluidSynth refused to start the player (FLUID_FAILED).
  bool play() => _play(_h) == _kFluidOk;
  void pause() => _pause(_h);

  /// Rewinds a finished player (see piya_live_reset).
  void reset() => _reset(_h);
  void seekTick(int tick) => _seek(_h, tick);
  int get tick => _tick(_h);
  int get totalTicks => _total(_h);
  bool get isPlaying => _isPlaying(_h) != 0;

  /// [level] 0..127 on MIDI [channel].
  void setLevel(int channel, int level) => _level(_h, channel, level);

  /// [velocity] 0 is note-off.
  void note(int channel, int key, int velocity) =>
      _note(_h, channel, key, velocity);

  void allNotesOff(int channel) => _notesOff(_h, channel, 0, 0);

  void close() {
    if (_closed) return;
    _closed = true;
    _close(_h);
  }
}
