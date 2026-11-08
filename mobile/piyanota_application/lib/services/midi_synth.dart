import 'dart:ffi';
import 'dart:io';
import 'dart:isolate';
import 'dart:typed_data';

import 'package:ffi/ffi.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:path_provider/path_provider.dart';

/// Native FluidSynth is only shipped for arm64-v8a (or the library failed to
/// load), so callers must fall back to another playback path.
class MidiSynthUnavailable implements Exception {
  const MidiSynthUnavailable(this.reason);
  final String reason;
  @override
  String toString() => 'MidiSynthUnavailable: $reason';
}

/// Non-zero return from `piya_render` (see piyanota_synth.c ERR_* codes:
/// 1 settings, 2 synth, 3 sfload, 4 player, 5 player add, 6 file open,
/// 7 write).
class MidiSynthError implements Exception {
  const MidiSynthError(this.code);
  final int code;
  @override
  String toString() => 'MidiSynthError($code)';
}

const String _kSynthLib = 'libpiyanota_synth.so';
const String _kSoundfontAsset = 'assets/soundfont/piano.sf2';
const String _kSoundfontFile = 'piano.sf2';

/// Size of assets/soundfont/piano.sf2; update with the asset. Lets a warm
/// start skip loading the 32 MB asset into memory.
const int kSoundfontBytes = 32319396;
const int _kWavHeaderBytes = 44;
const int _kInt16Max = 32767;
const int _kInt16Min = -32768;

typedef _RenderC = Int32 Function(
    Pointer<Utf8>, Pointer<Utf8>, Pointer<Utf8>, Pointer<Int32>);
typedef _RenderDart = int Function(
    Pointer<Utf8>, Pointer<Utf8>, Pointer<Utf8>, Pointer<Int32>);

/// Renders [midPath] to a mono 22050 Hz 16-bit WAV at [wavPath]; returns the
/// peak absolute sample. Runs in an isolate because rendering blocks for
/// seconds. Throws [MidiSynthUnavailable] / [MidiSynthError].
Future<int> renderMidiToWav({
  required String sf2Path,
  required String midPath,
  required String wavPath,
}) {
  // The library is opened inside the isolate: DynamicLibrary handles are
  // per-isolate, and opening there keeps the failure catchable in one place.
  return Isolate.run<int>(() {
    if (!Platform.isAndroid) {
      throw const MidiSynthUnavailable('not Android');
    }
    final DynamicLibrary lib;
    try {
      lib = DynamicLibrary.open(_kSynthLib);
    } on ArgumentError catch (e) {
      throw MidiSynthUnavailable('$e');
    }
    final _RenderDart render =
        lib.lookupFunction<_RenderC, _RenderDart>('piya_render');
    final Pointer<Utf8> sf2 = sf2Path.toNativeUtf8();
    final Pointer<Utf8> mid = midPath.toNativeUtf8();
    final Pointer<Utf8> wav = wavPath.toNativeUtf8();
    final Pointer<Int32> peak = calloc<Int32>();
    try {
      final int rc = render(sf2, mid, wav, peak);
      if (rc != 0) throw MidiSynthError(rc);
      return peak.value;
    } finally {
      calloc.free(sf2);
      calloc.free(mid);
      calloc.free(wav);
      calloc.free(peak);
    }
  });
}

/// Multiplies every int16 sample of the WAV at [wavPath] by [factor] in place,
/// clamping to the int16 range. One common gain across voices keeps their
/// relative balance, which per-file normalisation would destroy.
Future<void> scaleWav(String wavPath, double factor) {
  return Isolate.run<void>(() {
    final File file = File(wavPath);
    final Uint8List bytes = file.readAsBytesSync();
    final int n = (bytes.length - _kWavHeaderBytes) ~/ 2;
    final ByteData bd = ByteData.sublistView(bytes);
    for (int i = 0; i < n; i++) {
      final int off = _kWavHeaderBytes + 2 * i;
      final int v = (bd.getInt16(off, Endian.little) * factor)
          .round()
          .clamp(_kInt16Min, _kInt16Max);
      bd.setInt16(off, v, Endian.little);
    }
    file.writeAsBytesSync(bytes, flush: true);
  });
}

/// Copies the bundled soundfont to app support storage once (FluidSynth needs
/// a real file path, not an asset) and returns its path. A size mismatch
/// (interrupted copy or updated asset) triggers a re-copy.
Future<String> ensureSoundfont() async {
  final Directory dir = await getApplicationSupportDirectory();
  final File out = File('${dir.path}/$_kSoundfontFile');
  if (out.existsSync() && out.lengthSync() == kSoundfontBytes) {
    return out.path;
  }
  final ByteData data = await rootBundle.load(_kSoundfontAsset);
  await out.writeAsBytes(
    data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes),
    flush: true,
  );
  return out.path;
}
