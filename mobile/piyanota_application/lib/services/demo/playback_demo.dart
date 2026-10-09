import 'dart:convert';
import 'dart:io';
import 'dart:isolate';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:image/image.dart' as img;

import '../../models/voice_part.dart';

/// Where [PlaybackDemo.writeTo] put the demo, as the URIs a PIYA-103
/// result would carry.
@immutable
class PlaybackDemoFiles {
  const PlaybackDemoFiles({
    required this.tracks,
    required this.page,
    required this.timing,
  });

  final Map<VoicePart, Uri> tracks;
  final Uri page;
  final Uri timing;
}

/// The offline Playback demo, generated on the device at runtime: four
/// synthesized voice tracks (WAV), one drawn score page (PNG) and the
/// timing file that places the indicator on it.
///
/// Debug/fake builds only (user decision 2026-10-09). Nothing here is a
/// bundled asset, and the only caller is FakeScoreResultApi, which is built
/// only under the const `ApiConfig.useFakeAuth`, so release builds
/// tree-shake this out and ship neither the page nor the audio. The page
/// is drawn from scratch (no real, possibly copyrighted, score), and its
/// notes are the ones the audio plays, so the indicator lands on the
/// notehead being heard.
///
/// An F-major chord progression, 8 bars of 4/4 at 90 bpm, laid out as two
/// systems of four bars with one staff per voice (open score).
abstract final class PlaybackDemo {
  static const int sampleRate = 22050;
  static const int bpm = 90;
  static const int beatsPerBar = 4;
  static const int ppq = 480;
  static const double secondsPerBeat = 60 / bpm;
  static const double tailSeconds = 1.5;

  static const double _peakAmplitude = 0.35;
  static const double _attackSeconds = 0.005;
  static const double _releaseSeconds = 0.04;
  static const int _harmonicCount = 6;
  static const int _pcmMax = 32767;

  static const int pageWidth = 1300;
  static const int pageHeight = 1575;
  static const int barsPerSystem = 4;
  static const int _staffLineGap = 10;
  static const int _staffHeight = 4 * _staffLineGap;
  static const int _halfStepPx = _staffLineGap ~/ 2;
  static const int _systemPad = 20;
  static const int _barInnerPad = 24;
  static const int _staffLeft = 60;
  static const int _noteheadRadius = 5;
  static const int _stemLength = 35;

  /// Top line of each staff (S, A, T, B), per system.
  static const List<List<int>> _systemStaffTops = [
    [70, 240, 410, 580],
    [940, 1110, 1280, 1450],
  ];

  /// x of each barline, per system; the first is where bar 1's notes may
  /// start (after the clef), the last is the system's end.
  static const List<List<int>> _systemBarEdges = [
    [215, 401, 678, 954, 1219],
    [195, 415, 674, 1027, 1219],
  ];

  /// Diatonic step (octave * 7 + letter) of each staff's middle line: B4
  /// for treble; B3 for the Tenor's treble 8vb; D3 for bass.
  static const Map<VoicePart, int> _middleLineStep = {
    VoicePart.soprano: 4 * 7 + 6,
    VoicePart.alto: 4 * 7 + 6,
    VoicePart.tenor: 3 * 7 + 6,
    VoicePart.bass: 3 * 7 + 1,
  };

  /// Per voice, per bar: (pitch, beats).
  static const Map<VoicePart, List<List<(String, int)>>> _score = {
    VoicePart.soprano: [
      [('F4', 1), ('G4', 1), ('A4', 1), ('C5', 1)],
      [('Bb4', 1), ('A4', 1), ('G4', 1), ('F4', 1)],
      [('E4', 1), ('G4', 1), ('C5', 1), ('Bb4', 1)],
      [('A4', 2), ('C5', 2)],
      [('D5', 1), ('C5', 1), ('A4', 1), ('F4', 1)],
      [('D5', 1), ('Bb4', 1), ('F4', 1), ('D5', 1)],
      [('C5', 1), ('Bb4', 1), ('G4', 1), ('E4', 1)],
      [('F4', 4)],
    ],
    VoicePart.alto: [
      [('C4', 2), ('C4', 2)],
      [('D4', 2), ('D4', 2)],
      [('E4', 2), ('E4', 2)],
      [('F4', 2), ('C4', 2)],
      [('F4', 2), ('D4', 2)],
      [('F4', 2), ('D4', 2)],
      [('E4', 2), ('C4', 2)],
      [('C4', 4)],
    ],
    VoicePart.tenor: [
      [('A3', 2), ('A3', 2)],
      [('F3', 2), ('Bb3', 2)],
      [('G3', 2), ('G3', 2)],
      [('A3', 2), ('A3', 2)],
      [('A3', 2), ('A3', 2)],
      [('Bb3', 2), ('F3', 2)],
      [('G3', 2), ('Bb3', 2)],
      [('A3', 4)],
    ],
    VoicePart.bass: [
      [('F2', 4)],
      [('Bb2', 4)],
      [('C3', 4)],
      [('F2', 4)],
      [('D3', 4)],
      [('Bb2', 4)],
      [('C3', 4)],
      [('F2', 4)],
    ],
  };

  static const Map<String, int> _letterSemitone = {
    'C': 0,
    'D': 2,
    'E': 4,
    'F': 5,
    'G': 7,
    'A': 9,
    'B': 11,
  };
  static const String _letters = 'CDEFGAB';

  static int get barCount => _score[VoicePart.soprano]!.length;

  static Duration get length => Duration(
    milliseconds:
        ((barCount * beatsPerBar * secondsPerBeat + tailSeconds) * 1000)
            .round(),
  );

  /// Every note, in time order (S/A/T/B within a chord).
  static List<DemoNote> notes() {
    final notes = <DemoNote>[];
    for (final voice in VoicePart.values) {
      final bars = _score[voice]!;
      for (var bar = 0; bar < bars.length; bar++) {
        var beat = 0;
        for (final (pitch, beats) in bars[bar]) {
          notes.add(DemoNote(voice, pitch, bar + 1, beat, beats));
          beat += beats;
        }
        assert(beat == beatsPerBar, '${voice.name} bar ${bar + 1}: $beat');
      }
    }
    mergeSort(
      notes,
      compare: (a, b) {
        final byTime = a.onsetBeats.compareTo(b.onsetBeats);
        return byTime != 0 ? byTime : a.voice.index - b.voice.index;
      },
    );
    return notes;
  }

  static int midiNumber(String pitch) {
    final (letter, accidental, octave) = _split(pitch);
    return 12 * (octave + 1) + _letterSemitone[letter]! + accidental;
  }

  static int _diatonicStep(String pitch) {
    final (letter, _, octave) = _split(pitch);
    return octave * 7 + _letters.indexOf(letter);
  }

  static (String, int, int) _split(String pitch) {
    final letter = pitch[0];
    var rest = pitch.substring(1);
    var accidental = 0;
    if (rest.startsWith('b')) {
      accidental = -1;
      rest = rest.substring(1);
    } else if (rest.startsWith('#')) {
      accidental = 1;
      rest = rest.substring(1);
    }
    return (letter, accidental, int.parse(rest));
  }

  static int _system(DemoNote note) => (note.bar - 1) ~/ barsPerSystem;

  static int eventX(DemoNote note) {
    final edges = _systemBarEdges[_system(note)];
    final slot = (note.bar - 1) % barsPerSystem;
    final left = edges[slot] + _barInnerPad;
    final right = edges[slot + 1] - _barInnerPad;
    return (left + (right - left) * note.beat / beatsPerBar).round();
  }

  /// Steps above the staff's middle line (negative: below).
  static int _offset(DemoNote note) =>
      _diatonicStep(note.pitch) - _middleLineStep[note.voice]!;

  static int _staffCentre(int system, VoicePart voice) =>
      _systemStaffTops[system][voice.index] + _staffHeight ~/ 2;

  static int eventY(DemoNote note) =>
      _staffCentre(_system(note), note.voice) - _offset(note) * _halfStepPx;

  /// The timing file, in PIYA-117's shape (the same fields the server's
  /// carries, including backend-lead's optional system geometry).
  static List<Map<String, Object>> timingJson() {
    final events = <Map<String, Object>>[];
    var eventId = 0;
    for (final note in notes()) {
      final system = _system(note);
      final tops = _systemStaffTops[system];
      events.add({
        'timestampMs': (note.onsetBeats * secondsPerBeat * 1000).round(),
        'pageIndex': 0,
        'voice': note.voice.name,
        'tick': note.onsetBeats * ppq,
        'eventId': ++eventId,
        'x': eventX(note),
        'y': eventY(note),
        'bar': note.bar,
        'systemIndex': system,
        'systemTopY': tops.first - _systemPad,
        'systemBottomY': tops.last + _staffHeight + _systemPad,
      });
    }
    return events;
  }

  /// One voice as 16-bit mono PCM WAV. Additive, decaying harmonics:
  /// piano-ish enough for a demo.
  static Uint8List wav(VoicePart voice) {
    final total =
        ((barCount * beatsPerBar * secondsPerBeat + tailSeconds) * sampleRate)
            .round();
    final out = Float64List(total);
    final attack = (_attackSeconds * sampleRate).round();
    final release = (_releaseSeconds * sampleRate).round();
    for (final note in notes().where((note) => note.voice == voice)) {
      final start = (note.onsetBeats * secondsPerBeat * sampleRate).round();
      final count = (note.beats * secondsPerBeat * sampleRate).round();
      final freq = 440.0 * math.pow(2, (midiNumber(note.pitch) - 69) / 12);
      for (var i = 0; i < count && start + i < total; i++) {
        final t = i / sampleRate;
        var tone = 0.0;
        for (var n = 1; n <= _harmonicCount; n++) {
          tone +=
              math.sin(2 * math.pi * freq * n * t) *
              math.exp(-t * (1.2 + 0.7 * n)) /
              math.pow(n, 1.3);
        }
        var envelope = 1.0;
        if (i < attack) envelope = i / attack;
        if (i >= count - release) envelope *= (count - i) / release;
        out[start + i] += tone * envelope;
      }
    }
    var peak = 0.0;
    for (final sample in out) {
      peak = math.max(peak, sample.abs());
    }
    final scale = peak > 0 ? _peakAmplitude / peak : 0.0;
    final pcm = ByteData(total * 2);
    for (var i = 0; i < total; i++) {
      pcm.setInt16(i * 2, (out[i] * scale * _pcmMax).round(), Endian.little);
    }
    return _wavFile(pcm.buffer.asUint8List());
  }

  static Uint8List _wavFile(Uint8List pcm) {
    const channels = 1;
    const bytesPerSample = 2;
    const headerSize = 44;
    final header = ByteData(headerSize)
      ..setUint32(0, 0x52494646) // RIFF
      ..setUint32(4, 36 + pcm.length, Endian.little)
      ..setUint32(8, 0x57415645) // WAVE
      ..setUint32(12, 0x666d7420) // fmt
      ..setUint32(16, 16, Endian.little)
      ..setUint16(20, 1, Endian.little) // PCM
      ..setUint16(22, channels, Endian.little)
      ..setUint32(24, sampleRate, Endian.little)
      ..setUint32(28, sampleRate * channels * bytesPerSample, Endian.little)
      ..setUint16(32, channels * bytesPerSample, Endian.little)
      ..setUint16(34, bytesPerSample * 8, Endian.little)
      ..setUint32(36, 0x64617461) // data
      ..setUint32(40, pcm.length, Endian.little);
    return (BytesBuilder(copy: false)
          ..add(header.buffer.asUint8List())
          ..add(pcm))
        .takeBytes();
  }

  /// The score page: staves, clefs, barlines and the notes the audio
  /// plays, drawn from the same geometry as [timingJson].
  static img.Image page() {
    final page = img.Image(width: pageWidth, height: pageHeight);
    img.fill(page, color: img.ColorRgb8(255, 255, 255));
    final ink = img.ColorRgb8(20, 20, 20);
    img.drawString(
      page,
      'PiyaNota demo (generated, not a real score)',
      font: img.arial24,
      x: _staffLeft,
      y: 16,
      color: ink,
    );
    for (var system = 0; system < _systemStaffTops.length; system++) {
      final tops = _systemStaffTops[system];
      final edges = _systemBarEdges[system];
      for (final voice in VoicePart.values) {
        final top = tops[voice.index];
        for (var line = 0; line < 5; line++) {
          final y = top + line * _staffLineGap;
          img.drawLine(
            page,
            x1: _staffLeft,
            y1: y,
            x2: edges.last,
            y2: y,
            color: ink,
          );
        }
        final clef = voice == VoicePart.bass ? 'F' : 'G';
        img.drawString(
          page,
          voice == VoicePart.tenor ? '${clef}8' : clef,
          font: img.arial24,
          x: _staffLeft + 8,
          y: top + 8,
          color: ink,
        );
        img.drawString(
          page,
          voice.label,
          font: img.arial14,
          x: 4,
          y: top + 14,
          color: ink,
        );
      }
      // System bracket line and barlines through all four staves.
      final systemTop = tops.first;
      final systemBottom = tops.last + _staffHeight;
      for (final x in [_staffLeft, ...edges.skip(1)]) {
        img.drawLine(
          page,
          x1: x,
          y1: systemTop,
          x2: x,
          y2: systemBottom,
          color: ink,
          thickness: 2,
        );
      }
    }
    for (final note in notes()) {
      _drawNote(page, note, ink);
    }
    return page;
  }

  static void _drawNote(img.Image page, DemoNote note, img.Color ink) {
    final x = eventX(note);
    final y = eventY(note);
    final centre = _staffCentre(_system(note), note.voice);
    // Ledger lines for notes beyond the staff.
    final offset = _offset(note);
    for (var step = 6; step <= offset.abs(); step += 2) {
      final ledgerY = centre - offset.sign * step * _halfStepPx;
      img.drawLine(
        page,
        x1: x - _noteheadRadius * 2,
        y1: ledgerY,
        x2: x + _noteheadRadius * 2,
        y2: ledgerY,
        color: ink,
      );
    }
    if (note.beats >= 2) {
      img.drawCircle(page, x: x, y: y, radius: _noteheadRadius, color: ink);
    } else {
      img.fillCircle(page, x: x, y: y, radius: _noteheadRadius, color: ink);
    }
    if (note.beats < beatsPerBar) {
      // Stems up below the middle line, down from it and above.
      final up = offset < 0;
      final stemX = up ? x + _noteheadRadius : x - _noteheadRadius;
      img.drawLine(
        page,
        x1: stemX,
        y1: y,
        x2: stemX,
        y2: up ? y - _stemLength : y + _stemLength,
        color: ink,
      );
    }
    if (note.pitch.contains('b')) {
      img.drawString(
        page,
        'b',
        font: img.arial14,
        x: x - _noteheadRadius * 4,
        y: y - 10,
        color: ink,
      );
    }
  }

  static Uint8List pagePng() => img.encodePng(page());

  /// Writes the demo into [dir] (once; later calls reuse the files) and
  /// returns their URIs. Synthesis and PNG encoding run off the UI
  /// isolate.
  static Future<PlaybackDemoFiles> writeTo(Directory dir) async {
    final files = PlaybackDemoFiles(
      tracks: {
        for (final voice in VoicePart.values)
          voice: Uri.file('${dir.path}/${voice.name}.wav'),
      },
      page: Uri.file('${dir.path}/score_page_1.png'),
      timing: Uri.file('${dir.path}/timing.json'),
    );
    final marker = File('${dir.path}/$_version');
    if (marker.existsSync()) return files;
    await dir.create(recursive: true);
    await Isolate.run(() {
      for (final voice in VoicePart.values) {
        File.fromUri(files.tracks[voice]!).writeAsBytesSync(wav(voice));
      }
      File.fromUri(files.page).writeAsBytesSync(pagePng());
      File.fromUri(files.timing).writeAsStringSync(jsonEncode(timingJson()));
    });
    await marker.writeAsString('');
    return files;
  }

  /// Written last, so a half-written demo (app killed mid-write) is
  /// redone; bump it when the demo changes.
  static const String _version = '.demo-v1';
}

@immutable
class DemoNote {
  const DemoNote(this.voice, this.pitch, this.bar, this.beat, this.beats);

  final VoicePart voice;
  final String pitch;

  /// 1-based.
  final int bar;

  /// 0-based within the bar.
  final int beat;
  final int beats;

  int get onsetBeats => (bar - 1) * PlaybackDemo.beatsPerBar + beat;
}
