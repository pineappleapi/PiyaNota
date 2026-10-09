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
    required this.timingWithoutTenor,
  });

  final Map<VoicePart, Uri> tracks;
  final Uri page;
  final Uri timing;

  /// The timing file of a result whose Tenor failed: a failed voice has no
  /// events (meter/muting gap doc item 4).
  final Uri timingWithoutTenor;
}

/// One measure of the demo: its meter and its length in ticks.
@immutable
class DemoBar {
  const DemoBar(this.numerator, this.denominator, {this.ticks});

  final int numerator;
  final int denominator;

  /// Shorter than the meter only for the pickup.
  final int? ticks;

  int get fullTicks => numerator * PlaybackDemo.ppq * 4 ~/ denominator;
  int get durTicks => ticks ?? fullTicks;
}

/// The offline Playback demo, generated on the device at runtime: four
/// synthesized voice tracks (WAV), one drawn score page (PNG) and the
/// timing file (events and measure table) that places the indicator on it
/// and lays out the metronome click.
///
/// Debug/fake builds only (user decision 2026-10-09). Nothing here is a
/// bundled asset, and the only caller is FakeScoreResultApi, which is built
/// only under the const `ApiConfig.useFakeAuth`, so release builds
/// tree-shake this out and ship neither the page nor the audio. The page
/// is drawn from scratch (no real, possibly copyrighted, score), and its
/// notes are the ones the audio plays, so the indicator lands on the
/// notehead being heard.
///
/// An F-major progression at quarter = 90 that exercises the per-measure
/// click (PIYA-210): a one-quarter pickup in 3/4, then consecutive meter
/// changes 3/4, 3/4, 5/8, 2/4, 6/8, 6/8, 4/4, 4/4. Two systems, one staff
/// per voice (open score). The Bass is silent in bar [mutedBar] (its notes
/// are drawn and timed, as a muted measure's are, but not heard), to
/// exercise PIYA-103 `mutedMeasures`.
abstract final class PlaybackDemo {
  static const int sampleRate = 22050;
  static const int bpm = 90;
  static const int ppq = 480;
  static const double tailSeconds = 1.5;

  /// Index = printed bar number; bar 0 is the pickup and carries bar 1's
  /// meter, as PIYA-117 AC9 has it.
  static const List<DemoBar> bars = [
    DemoBar(3, 4, ticks: ppq),
    DemoBar(3, 4),
    DemoBar(3, 4),
    DemoBar(5, 8),
    DemoBar(2, 4),
    DemoBar(6, 8),
    DemoBar(6, 8),
    DemoBar(4, 4),
    DemoBar(4, 4),
  ];

  /// The measure the Bass is muted in (PIYA-109 AC8 silence).
  static const int mutedBar = 4;
  static const VoicePart mutedVoice = VoicePart.bass;

  static const double _peakAmplitude = 0.35;
  static const double _attackSeconds = 0.005;
  static const double _releaseSeconds = 0.04;
  static const int _harmonicCount = 6;
  static const int _pcmMax = 32767;

  static const int pageWidth = 1300;
  static const int pageHeight = 1575;
  static const int _staffLineGap = 10;
  static const int _staffHeight = 4 * _staffLineGap;
  static const int _halfStepPx = _staffLineGap ~/ 2;
  static const int _systemPad = 20;
  static const int _barInnerPad = 24;
  static const int _staffLeft = 60;
  static const int _firstBarX = 200;
  static const int _systemRight = 1219;
  static const int _noteheadRadius = 5;
  static const int _stemLength = 35;

  /// Top line of each staff (S, A, T, B), per system.
  static const List<List<int>> _systemStaffTops = [
    [70, 240, 410, 580],
    [940, 1110, 1280, 1450],
  ];

  /// The first bar of each system after the first.
  static const List<int> _systemStarts = [0, 5];

  /// Diatonic step (octave * 7 + letter) of each staff's middle line: B4
  /// for treble; B3 for the Tenor's treble 8vb; D3 for bass.
  static const Map<VoicePart, int> _middleLineStep = {
    VoicePart.soprano: 4 * 7 + 6,
    VoicePart.alto: 4 * 7 + 6,
    VoicePart.tenor: 3 * 7 + 6,
    VoicePart.bass: 3 * 7 + 1,
  };

  static const int _q = ppq;
  static const int _e = ppq ~/ 2;

  /// Per voice, per bar (from the pickup): (pitch, ticks).
  static const Map<VoicePart, List<List<(String, int)>>> _score = {
    VoicePart.soprano: [
      [('C5', _q)],
      [('A4', _q), ('G4', _q), ('F4', _q)],
      [('A4', 2 * _q), ('C5', _q)],
      [('Bb4', 3 * _e), ('A4', 2 * _e)],
      [('G4', _q), ('E4', _q)],
      [('F4', 3 * _e), ('A4', 3 * _e)],
      [('C5', 3 * _e), ('Bb4', 3 * _e)],
      [('A4', _q), ('C5', _q), ('Bb4', _q), ('G4', _q)],
      [('F4', 4 * _q)],
    ],
    VoicePart.alto: [
      [('C4', _q)],
      [('C4', 3 * _q)],
      [('F4', 2 * _q), ('E4', _q)],
      [('D4', 3 * _e), ('F4', 2 * _e)],
      [('E4', _q), ('C4', _q)],
      [('C4', 6 * _e)],
      [('F4', 3 * _e), ('D4', 3 * _e)],
      [('C4', 2 * _q), ('E4', 2 * _q)],
      [('C4', 4 * _q)],
    ],
    VoicePart.tenor: [
      [('A3', _q)],
      [('A3', 3 * _q)],
      [('A3', 2 * _q), ('G3', _q)],
      [('F3', 3 * _e), ('C4', 2 * _e)],
      [('C4', _q), ('G3', _q)],
      [('A3', 6 * _e)],
      [('A3', 3 * _e), ('Bb3', 3 * _e)],
      [('A3', 2 * _q), ('G3', 2 * _q)],
      [('A3', 4 * _q)],
    ],
    VoicePart.bass: [
      [('C3', _q)],
      [('F2', 3 * _q)],
      [('F2', 2 * _q), ('C3', _q)],
      [('Bb2', 3 * _e), ('F2', 2 * _e)],
      [('C3', _q), ('C3', _q)],
      [('F2', 6 * _e)],
      [('F2', 3 * _e), ('Bb2', 3 * _e)],
      [('C3', 2 * _q), ('C3', 2 * _q)],
      [('F2', 4 * _q)],
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

  static int get barCount => bars.length;

  static int barStartTick(int bar) {
    var tick = 0;
    for (var i = 0; i < bar; i++) {
      tick += bars[i].durTicks;
    }
    return tick;
  }

  static int get totalTicks => barStartTick(bars.length);

  /// [tick] in ms at [bpm]: the rendered tracks' clock.
  static int tickMs(int tick) => (tick * 60000 / (ppq * bpm)).round();

  static Duration get length =>
      Duration(milliseconds: tickMs(totalTicks) + (tailSeconds * 1000).round());

  /// Every note, in time order (S/A/T/B within a chord).
  static List<DemoNote> notes() {
    final notes = <DemoNote>[];
    for (final voice in VoicePart.values) {
      final ofVoice = _score[voice]!;
      assert(ofVoice.length == bars.length, voice.name);
      for (var bar = 0; bar < ofVoice.length; bar++) {
        var tick = 0;
        for (final (pitch, ticks) in ofVoice[bar]) {
          notes.add(DemoNote(voice, pitch, bar, tick, ticks));
          tick += ticks;
        }
        assert(tick == bars[bar].durTicks, '${voice.name} bar $bar: $tick');
      }
    }
    mergeSort(
      notes,
      compare: (a, b) {
        final byTime = a.onsetTick.compareTo(b.onsetTick);
        return byTime != 0 ? byTime : a.voice.index - b.voice.index;
      },
    );
    return notes;
  }

  /// A muted measure is silent but still drawn and timed (gap doc item 4).
  static bool isMuted(DemoNote note) =>
      note.voice == mutedVoice && note.bar == mutedBar;

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

  static int systemOf(int bar) {
    var system = 0;
    while (system + 1 < _systemStarts.length &&
        bar >= _systemStarts[system + 1]) {
      system++;
    }
    return system;
  }

  /// x of each barline of [system]: the first is where its first bar's
  /// notes may start (after the clef), the last its end. Widths follow
  /// each bar's length, so the notes are spaced by time.
  static List<int> barEdges(int system) {
    final first = _systemStarts[system];
    final end = system + 1 < _systemStarts.length
        ? _systemStarts[system + 1]
        : bars.length;
    final total = barStartTick(end) - barStartTick(first);
    final edges = [_firstBarX];
    var ticks = 0;
    for (var bar = first; bar < end; bar++) {
      ticks += bars[bar].durTicks;
      edges.add(
        (_firstBarX + (_systemRight - _firstBarX) * ticks / total).round(),
      );
    }
    return edges;
  }

  static int eventX(DemoNote note) {
    final system = systemOf(note.bar);
    final edges = barEdges(system);
    final slot = note.bar - _systemStarts[system];
    final left = edges[slot] + _barInnerPad;
    final right = edges[slot + 1] - _barInnerPad;
    return (left + (right - left) * note.tick / bars[note.bar].durTicks)
        .round();
  }

  /// Steps above the staff's middle line (negative: below).
  static int _offset(DemoNote note) =>
      _diatonicStep(note.pitch) - _middleLineStep[note.voice]!;

  static int _staffCentre(int system, VoicePart voice) =>
      _systemStaffTops[system][voice.index] + _staffHeight ~/ 2;

  static int eventY(DemoNote note) =>
      _staffCentre(systemOf(note.bar), note.voice) -
      _offset(note) * _halfStepPx;

  /// The timing file in PIYA-117's shape, `{"events": [...], "bars":
  /// [...]}` (AC9), with backend-lead's optional system geometry. Voices
  /// in [failed] have no events (gap doc item 4); the measure table is
  /// unaffected.
  static Map<String, Object> timingJson({Set<VoicePart> failed = const {}}) {
    final events = <Map<String, Object>>[];
    var eventId = 0;
    for (final note in notes()) {
      if (failed.contains(note.voice)) continue;
      final system = systemOf(note.bar);
      final tops = _systemStaffTops[system];
      events.add({
        'timestampMs': tickMs(note.onsetTick),
        'pageIndex': 0,
        'voice': note.voice.label,
        'tick': note.onsetTick,
        'eventId': ++eventId,
        'x': eventX(note),
        'y': eventY(note),
        'bar': note.bar,
        'systemIndex': system,
        'systemTopY': tops.first - _systemPad,
        'systemBottomY': tops.last + _staffHeight + _systemPad,
      });
    }
    return {'events': events, 'bars': barsJson()};
  }

  /// PIYA-117 AC9's measure table. `durMs` is the next bar's `startMs`
  /// minus this one's, so rounding never opens a gap.
  static List<Map<String, Object?>> barsJson() => [
    for (var bar = 0; bar < bars.length; bar++)
      {
        'bar': bar,
        'startMs': tickMs(barStartTick(bar)),
        'durMs': tickMs(barStartTick(bar + 1)) - tickMs(barStartTick(bar)),
        'startTick': barStartTick(bar),
        'durTicks': bars[bar].durTicks,
        'numerator': bars[bar].numerator,
        'denominator': bars[bar].denominator,
        'meterSource': bar <= 1 || _meterChanges(bar)
            ? 'detected'
            : 'inherited',
        'pickup': bar == 0,
        'groups': null,
      },
  ];

  static bool _meterChanges(int bar) =>
      bar > 0 &&
      (bars[bar].numerator != bars[bar - 1].numerator ||
          bars[bar].denominator != bars[bar - 1].denominator);

  /// PIYA-103 AC9's entry for the muted Bass measure.
  static Map<String, Object> mutedMeasureJson() => {
    'voice': mutedVoice.name,
    'bar': mutedBar,
    'pageIndex': 0,
    'systemIndex': systemOf(mutedBar),
    'startMs': tickMs(barStartTick(mutedBar)),
    'endMs': tickMs(barStartTick(mutedBar + 1)),
    'reason': 'bar_overflow_clipped',
  };

  /// One voice as 16-bit mono PCM WAV. Additive, decaying harmonics:
  /// piano-ish enough for a demo. A muted measure is left silent.
  static Uint8List wav(VoicePart voice) {
    final total = (length.inMicroseconds * sampleRate / 1e6).round();
    final out = Float64List(total);
    final attack = (_attackSeconds * sampleRate).round();
    final release = (_releaseSeconds * sampleRate).round();
    final samplesPerTick = 60 * sampleRate / (ppq * bpm);
    for (final note in notes().where((note) => note.voice == voice)) {
      if (isMuted(note)) continue;
      final start = (note.onsetTick * samplesPerTick).round();
      final count = (note.ticks * samplesPerTick).round();
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

  /// The score page: staves, clefs, meters, barlines and the notes the
  /// audio plays, drawn from the same geometry as [timingJson].
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
      final edges = barEdges(system);
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
      // A meter, above the system, at each bar whose meter differs from
      // the one before (and at the first bar).
      final first = _systemStarts[system];
      for (var slot = 0; slot < edges.length - 1; slot++) {
        final bar = first + slot;
        if (bar != 0 && !_meterChanges(bar)) continue;
        img.drawString(
          page,
          '${bars[bar].numerator}/${bars[bar].denominator}',
          font: img.arial14,
          x: edges[slot] + 4,
          y: tops.first - 18,
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
    final centre = _staffCentre(systemOf(note.bar), note.voice);
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
    // Half notes and longer are hollow.
    if (note.ticks >= 2 * ppq) {
      img.drawCircle(page, x: x, y: y, radius: _noteheadRadius, color: ink);
    } else {
      img.fillCircle(page, x: x, y: y, radius: _noteheadRadius, color: ink);
    }
    // Dotted values: a dotted quarter or dotted half.
    if (note.ticks == 3 * ppq ~/ 2 || note.ticks == 3 * ppq) {
      img.fillCircle(
        page,
        x: x + _noteheadRadius * 2 + 2,
        y: y,
        radius: 2,
        color: ink,
      );
    }
    if (note.ticks < 4 * ppq) {
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
      timingWithoutTenor: Uri.file('${dir.path}/timing_failed_tenor.json'),
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
      File.fromUri(files.timingWithoutTenor)
          .writeAsStringSync(jsonEncode(timingJson(failed: {VoicePart.tenor})));
    });
    await marker.writeAsString('');
    return files;
  }

  /// Written last, so a half-written demo (app killed mid-write) is
  /// redone; bump it when the demo changes.
  static const String _version = '.demo-v2';
}

@immutable
class DemoNote {
  const DemoNote(this.voice, this.pitch, this.bar, this.tick, this.ticks);

  final VoicePart voice;
  final String pitch;

  /// The printed bar number; 0 is the pickup.
  final int bar;

  /// Offset from the bar's barline, in ticks.
  final int tick;

  /// Length in ticks.
  final int ticks;

  int get onsetTick => PlaybackDemo.barStartTick(bar) + tick;
}
