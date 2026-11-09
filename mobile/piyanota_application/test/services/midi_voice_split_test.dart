import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/services/midi_voice_split.dart';

Uint8List _track(List<int> body) =>
    Uint8List.fromList([0x4D, 0x54, 0x72, 0x6B, 0, 0, 0, body.length, ...body]);

Uint8List _smf(List<List<int>> tracks) => Uint8List.fromList([
  0x4D, 0x54, 0x68, 0x64, 0, 0, 0, 6, 0, 1, 0, tracks.length, 0x01, 0xE0,
  for (final t in tracks) ..._track(t),
]);

const _eot = [0x00, 0xFF, 0x2F, 0x00];
const _tempo = [0x00, 0xFF, 0x51, 0x03, 0x07, 0xA1, 0x20];

/// Per track: (absolute tick, "status:data1" or "metaTYPE:len").
List<List<(int, String)>> _events(Uint8List smf) {
  final out = <List<(int, String)>>[];
  var p = 14;
  while (p < smf.length) {
    final len =
        (smf[p + 4] << 24) | (smf[p + 5] << 16) | (smf[p + 6] << 8) | smf[p + 7];
    final end = p + 8 + len;
    var i = p + 8;
    var tick = 0;
    final evs = <(int, String)>[];
    int vlq() {
      var v = 0;
      while (true) {
        final b = smf[i++];
        v = (v << 7) | (b & 0x7F);
        if (b < 0x80) return v;
      }
    }

    while (i < end) {
      tick += vlq();
      final s = smf[i++];
      if (s == 0xFF) {
        final type = smf[i++];
        final n = vlq();
        evs.add((tick, 'meta${type.toRadixString(16)}:$n'));
        i += n;
      } else {
        evs.add((tick, '${s.toRadixString(16)}:${smf[i]}'));
        i += (s & 0xF0) == 0xC0 ? 1 : 2;
      }
    }
    out.add(evs);
    p = end;
  }
  return out;
}

void main() {
  final conductor = [..._tempo, ..._eot];
  final voice = [
    0x00, 0x90, 60, 90, // on 60 @0
    0x83, 0x60, 0x80, 60, 0, // off @480
    0x00, 0x90, 62, 90, // on 62 @480
    0x83, 0x60, 62, 0, // running status (0x90 vel 0) off @960
    ..._eot,
  ];
  final click = [0x00, 0x99, 76, 120, 0x3C, 0x99, 76, 0, ..._eot];
  final other = [0x00, 0x91, 50, 80, 0x60, 0x81, 50, 0, ..._eot];
  final smf = _smf([conductor, voice, click, other]);

  test('keeps only the channel, drops click and other voices', () {
    final ev = _events(splitVoice(smf, 0));
    expect(ev[1].map((e) => e.$2), [
      '90:60',
      '80:60',
      '90:62',
      '90:62',
      'meta2f:0',
    ]);
    expect(ev[2].where((e) => !e.$2.startsWith('meta')), isEmpty);
    expect(ev[3].where((e) => !e.$2.startsWith('meta')), isEmpty);
  });

  test('tempo preserved; absolute ticks unchanged incl. running status', () {
    final ev = _events(splitVoice(smf, 0));
    expect(ev[0].first, (0, 'meta51:3'));
    expect(ev[1].map((e) => e.$1), [0, 480, 480, 960, 960]);
  });

  test('silent range drops note-on and matching off, recomputes delta', () {
    final ev = _events(splitVoice(smf, 0, silentRanges: [(0, 480)]));
    expect(ev[1].map((e) => e.$2), ['90:62', '90:62', 'meta2f:0']);
    expect(ev[1].map((e) => e.$1), [480, 960, 960]);
  });

  test('range end is exclusive', () {
    final ev = _events(splitVoice(smf, 0, silentRanges: [(0, 480)]));
    expect(ev[1].first.$1, 480);
  });

  test('split output is stable under a second split', () {
    final once = splitVoice(smf, 0);
    expect(splitVoice(once, 0), once);
  });

  test('malformed input throws MidiFormatException', () {
    expect(
      () => splitVoice(Uint8List.fromList([1, 2, 3]), 0),
      throwsA(isA<MidiFormatException>()),
    );
    expect(
      () => splitVoice(smf.sublist(0, smf.length - 3), 0),
      throwsA(isA<MidiFormatException>()),
    );
    expect(() => splitVoice(smf, 16), throwsA(isA<MidiFormatException>()));
    final bad = _smf([
      [0x00, 0x40, 0x40, ..._eot],
    ]); // data byte, no status
    expect(() => splitVoice(bad, 0), throwsA(isA<MidiFormatException>()));
  });

  test('tempoScale divides microseconds per beat, ticks unchanged', () {
    final out = splitVoice(smf, 0, tempoScale: 2);
    // 0x07A120 = 500000 us -> 250000 us = 0x03D090
    final at = out.indexOfSub([0xFF, 0x51, 0x03]);
    expect(out.sublist(at + 3, at + 6), [0x03, 0xD0, 0x90]);
    expect(_events(out)[1], _events(splitVoice(smf, 0))[1]);
  });

  test('buildClickMidi: hi wood block on downbeat, low one otherwise, channel 10', () {
    final ev = _events(buildClickMidi([(0, true), (480, false)], 120))[0];
    expect(ev, [
      (0, 'meta51:3'),
      (0, '99:76'),
      (30, '89:76'),
      (480, '99:77'),
      (510, '89:77'),
      (510, 'meta2f:0'),
    ]);
  });
}

extension on Uint8List {
  int indexOfSub(List<int> sub) {
    for (var i = 0; i + sub.length <= length; i++) {
      var ok = true;
      for (var j = 0; j < sub.length; j++) {
        if (this[i + j] != sub[j]) {
          ok = false;
          break;
        }
      }
      if (ok) return i;
    }
    return -1;
  }
}
