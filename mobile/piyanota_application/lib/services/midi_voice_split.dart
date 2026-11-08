import 'dart:typed_data';

/// The input is not a Standard MIDI File this splitter can read.
class MidiFormatException extends FormatException {
  const MidiFormatException(super.message, [super.source, super.offset]);
}

const int _kStatusMin = 0x80;
const int _kNoteOff = 0x80;
const int _kNoteOn = 0x90;
const int _kMeta = 0xFF;
const int _kSysex = 0xF0;
const int _kSysexEscape = 0xF7;
const int _kChannelMask = 0x0F;
const int _kMaxChannel = 15;
const int _kVlqMaxBytes = 4;
const int _kProgramChange = 0xC0;
const int _kChannelPressure = 0xD0;
const int _kHeaderChunkBytes = 14;
const int _kHeaderDataLength = 6;
const int _kMetaTempo = 0x51;
const int _kTempoBytes = 3;
const int _kMaxTempoUs = 0xFFFFFF;
const int _kMsPerMinuteUs = 60000000;
const int _kPpq = 480;
const int _kPercussionChannel = 9; // GM channel 10
/// Downbeat only slightly louder than the other clicks: a soft accent.
const int kClickDownbeatVelocity = 105;
const int kClickVelocity = 80;
// Percussion is one-shot; the note-off only has to precede the next click.
const int _kClickNoteTicks = 30;

/// GM percussion keys of the metronome: hi / low wood block, which
/// piano.sf2's Standard 1 kit covers (keys 76 and 77); soft and barely
/// pitched, unlike the bell (34) that was too distracting.
const int kClickDownbeatKey = 76;
const int kClickKey = 77;

class _Reader {
  _Reader(this.data, this.pos, this.end);
  final Uint8List data;
  int pos;
  final int end;

  int u8() {
    if (pos >= end) throw MidiFormatException('Truncated MIDI', null, pos);
    return data[pos++];
  }

  int vlq() {
    var v = 0;
    for (var i = 0; i < _kVlqMaxBytes; i++) {
      final b = u8();
      v = (v << 7) | (b & 0x7F);
      if (b < 0x80) return v;
    }
    throw MidiFormatException('Variable-length value too long', null, pos);
  }

  Uint8List bytes(int n) {
    if (n < 0 || pos + n > end) {
      throw MidiFormatException('Truncated MIDI', null, pos);
    }
    final out = Uint8List.sublistView(data, pos, pos + n);
    pos += n;
    return out;
  }
}

void _putVlq(BytesBuilder out, int value) {
  final parts = <int>[value & 0x7F];
  var v = value >> 7;
  while (v > 0) {
    parts.add((v & 0x7F) | 0x80);
    v >>= 7;
  }
  out.add(parts.reversed.toList());
}

int _be32(Uint8List d, int o) =>
    (d[o] << 24) | (d[o + 1] << 16) | (d[o + 2] << 8) | d[o + 3];

bool _isSilent(int tick, List<(int, int)> ranges) {
  for (final (start, end) in ranges) {
    if (tick >= start && tick < end) return true;
  }
  return false;
}

/// Returns a Standard MIDI File holding only [channel]'s notes: every meta
/// and sysex event is kept (tempo, time signature), every other channel is
/// dropped, and a note whose onset tick falls in a [silentRanges] entry
/// (start inclusive, end exclusive) loses both its note-on and its note-off.
/// Kept events stay at their original absolute ticks.
///
/// [tempoScale] multiplies the playback speed: every tempo event's
/// microseconds-per-beat is divided by it, so ticks (and [silentRanges])
/// are unaffected while the render comes out faster or slower. This
/// replaces time-stretching the audio, which chops at extreme speeds.
///
/// Throws [MidiFormatException] for anything that is not a well-formed SMF.
Uint8List splitVoice(
  Uint8List smf,
  int channel, {
  List<(int, int)> silentRanges = const [],
  double tempoScale = 1,
}) {
  if (tempoScale <= 0) throw MidiFormatException('Bad tempo scale $tempoScale');
  if (channel < 0 || channel > _kMaxChannel) {
    throw MidiFormatException('Bad channel $channel');
  }
  if (smf.length < _kHeaderChunkBytes ||
      String.fromCharCodes(smf.sublist(0, 4)) != 'MThd' ||
      _be32(smf, 4) != _kHeaderDataLength) {
    throw const MidiFormatException('Not a MIDI file (bad header)');
  }
  final trackCount = (smf[10] << 8) | smf[11];
  var pos = _kHeaderChunkBytes;
  final out = BytesBuilder()..add(smf.sublist(0, _kHeaderChunkBytes));
  for (var t = 0; t < trackCount; t++) {
    if (pos + 8 > smf.length ||
        String.fromCharCodes(smf.sublist(pos, pos + 4)) != 'MTrk') {
      throw MidiFormatException('Missing track $t', null, pos);
    }
    final end = pos + 8 + _be32(smf, pos + 4);
    if (end > smf.length) {
      throw MidiFormatException('Track $t is truncated', null, pos);
    }
    final body = _splitTrack(
      _Reader(smf, pos + 8, end),
      channel,
      silentRanges,
      tempoScale,
    );
    out
      ..add([0x4D, 0x54, 0x72, 0x6B]) // MTrk
      ..add([
        (body.length >> 24) & 0xFF,
        (body.length >> 16) & 0xFF,
        (body.length >> 8) & 0xFF,
        body.length & 0xFF,
      ])
      ..add(body);
    pos = end;
  }
  return out.toBytes();
}

Uint8List _splitTrack(
  _Reader r,
  int channel,
  List<(int, int)> silent,
  double tempoScale,
) {
  final out = BytesBuilder();
  final dropOff = <int, int>{}; // pitch -> note-offs still to drop
  var tick = 0;
  var lastKept = 0;
  int? running;
  void emit(List<int> event) {
    _putVlq(out, tick - lastKept);
    lastKept = tick;
    out.add(event);
  }

  while (r.pos < r.end) {
    tick += r.vlq();
    var status = r.u8();
    if (status == _kMeta) {
      running = null;
      final type = r.u8();
      var data = r.bytes(r.vlq());
      if (type == _kMetaTempo && data.length == _kTempoBytes) {
        final us = (data[0] << 16) | (data[1] << 8) | data[2];
        final scaled = (us / tempoScale).round().clamp(1, _kMaxTempoUs);
        data = Uint8List.fromList([
          (scaled >> 16) & 0xFF,
          (scaled >> 8) & 0xFF,
          scaled & 0xFF,
        ]);
      }
      final ev = BytesBuilder()
        ..addByte(_kMeta)
        ..addByte(type);
      _putVlq(ev, data.length);
      ev.add(data);
      emit(ev.toBytes());
      continue;
    }
    if (status == _kSysex || status == _kSysexEscape) {
      running = null;
      final data = r.bytes(r.vlq());
      final ev = BytesBuilder()..addByte(status);
      _putVlq(ev, data.length);
      ev.add(data);
      emit(ev.toBytes());
      continue;
    }
    int? firstData;
    if (status < _kStatusMin) {
      final prev = running;
      if (prev == null) {
        throw MidiFormatException('Data byte without status', null, r.pos);
      }
      firstData = status;
      status = prev;
    } else if (status >= 0xF0) {
      throw MidiFormatException('Unsupported status $status', null, r.pos);
    }
    running = status;
    final kind = status & 0xF0;
    final d1 = firstData ?? r.u8();
    final twoData = kind != _kProgramChange && kind != _kChannelPressure;
    final d2 = twoData ? r.u8() : null;
    if ((status & _kChannelMask) != channel) continue;
    final isOn = kind == _kNoteOn && (d2 ?? 0) > 0;
    final isOff = kind == _kNoteOff || (kind == _kNoteOn && !isOn);
    if (isOn && _isSilent(tick, silent)) {
      dropOff[d1] = (dropOff[d1] ?? 0) + 1;
      continue;
    }
    if (isOff && (dropOff[d1] ?? 0) > 0) {
      dropOff[d1] = dropOff[d1]! - 1;
      continue;
    }
    emit([status, d1, ?d2]);
  }
  return out.toBytes();
}

/// A format-0 Standard MIDI File at [bpm] with one percussion note per
/// entry of [clicks] ((tick, isDownbeat)): the high wood block on downbeats,
/// the low one elsewhere. Rendered to its own WAV so the metronome can be toggled.
Uint8List buildClickMidi(List<(int, bool)> clicks, int bpm) {
  final events = <(int, int, List<int>)>[]; // tick, order (off first), bytes
  for (final (tick, down) in clicks) {
    final key = down ? kClickDownbeatKey : kClickKey;
    final vel = down ? kClickDownbeatVelocity : kClickVelocity;
    events
      ..add((tick, 1, [0x90 | _kPercussionChannel, key, vel]))
      ..add((tick + _kClickNoteTicks, 0, [0x80 | _kPercussionChannel, key, 0]));
  }
  events.sort((a, b) => a.$1 != b.$1 ? a.$1 - b.$1 : a.$2 - b.$2);
  final body = BytesBuilder();
  final us = _kMsPerMinuteUs ~/ bpm;
  body.add([
    0x00, _kMeta, _kMetaTempo, _kTempoBytes, //
    (us >> 16) & 0xFF, (us >> 8) & 0xFF, us & 0xFF,
  ]);
  var last = 0;
  for (final (tick, _, bytes) in events) {
    _putVlq(body, tick - last);
    last = tick;
    body.add(bytes);
  }
  body.add([0x00, _kMeta, 0x2F, 0x00]);
  final b = body.toBytes();
  return (BytesBuilder()
        ..add([0x4D, 0x54, 0x68, 0x64, 0, 0, 0, _kHeaderDataLength, 0, 0, 0, 1])
        ..add([_kPpq >> 8, _kPpq & 0xFF])
        ..add([0x4D, 0x54, 0x72, 0x6B])
        ..add([
          (b.length >> 24) & 0xFF,
          (b.length >> 16) & 0xFF,
          (b.length >> 8) & 0xFF,
          b.length & 0xFF,
        ])
        ..add(b))
      .toBytes();
}
