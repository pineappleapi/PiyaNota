import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/models/export_selection.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/score_timeline.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/services/export_service.dart';
import 'package:piyanota_application/services/midi_render_cache.dart';
import 'package:piyanota_application/state/export_providers.dart';
import 'package:piyanota_application/state/playback_providers.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'playback_fakes.dart';

ScoreResult _withMidi(ScoreResult r) => ScoreResult(
  scoreId: r.scoreId,
  audioTracks: r.audioTracks,
  scoreImages: r.scoreImages,
  review: r.review,
  tempoBpm: r.tempoBpm,
  timingMetadataUrl: r.timingMetadataUrl,
  midiCombined: MidiCombinedFile(
    url: Uri.parse('https://cdn.test/c.mid'),
    fileId: 'f1',
  ),
);

Future<(PlaybackState, PlaybackHarness)> _open(
  ScoreResult result,
  Future<Map<VoicePart, Uri>?> Function() render,
) async {
  SharedPreferences.setMockInitialValues({'onboarding_completed': true});
  final harness = PlaybackHarness(ScriptedScoreResultApi([result]));
  final container = ProviderContainer(
    overrides: [
      ...harness.overrides,
      midiVoiceRendererProvider.overrideWithValue((r, bars, bpm) async {
        final v = await render();
        return v == null ? null : (voices: v, click: null);
      }),
    ],
  );
  addTearDown(container.dispose);
  final sub = container.listen(playbackControllerProvider(kScoreId), (_, _) {});
  addTearDown(sub.close);
  for (var i = 0; i < 50; i++) {
    await Future<void>.delayed(const Duration(milliseconds: 10));
    if (sub.read().phase != PlaybackPhase.loading) break;
  }
  return (sub.read(), harness);
}

void main() {
  final wavs = {
    for (final v in VoicePart.values) v: Uri.parse('file:///r/${v.name}.wav'),
  };

  test('no midiCombined -> mp3, renderer not called', () async {
    var called = false;
    final (s, h) = await _open(testResult(), () async {
      called = true;
      return wavs;
    });
    expect(s.phase, PlaybackPhase.ready);
    expect(s.source, PlaybackSource.mp3);
    expect(called, isFalse);
    expect(h.engine.loaded!.values.first.scheme, 'https');
  });

  test('render success -> wav uris loaded', () async {
    final (s, h) = await _open(_withMidi(testResult()), () async => wavs);
    expect(s.source, PlaybackSource.midi);
    expect(h.engine.loaded, wavs);
  });

  test('render returns null -> mp3 fallback', () async {
    final (s, h) = await _open(_withMidi(testResult()), () async => null);
    expect(s.phase, PlaybackPhase.ready);
    expect(s.source, PlaybackSource.mp3);
    expect(h.engine.loaded!.values.first.scheme, 'https');
  });

  test('render throws -> mp3 fallback', () async {
    final (s, _) = await _open(
      _withMidi(testResult()),
      () async => throw StateError('x'),
    );
    expect(s.source, PlaybackSource.mp3);
  });

  group('tempo change on the MIDI path', () {
    Future<(ProviderContainer, PlaybackHarness, List<int>)> open(
      Future<MidiRender?> Function(int bpm) render,
    ) async {
      SharedPreferences.setMockInitialValues({'onboarding_completed': true});
      final h = PlaybackHarness(
        ScriptedScoreResultApi([_withMidi(testResult())])
          ..timing = testTiming(),
      );
      final bpms = <int>[];
      final c = ProviderContainer(
        overrides: [
          ...h.overrides,
          midiVoiceRendererProvider.overrideWithValue((r, bars, bpm) {
            bpms.add(bpm);
            return render(bpm);
          }),
        ],
      );
      addTearDown(c.dispose);
      final sub = c.listen(playbackControllerProvider(kScoreId), (_, _) {});
      addTearDown(sub.close);
      for (var i = 0; i < 50; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
        if (sub.read().phase != PlaybackPhase.loading) break;
      }
      return (c, h, bpms);
    }

    test('release re-renders at the chosen bpm, speed stays 1', () async {
      final (c, h, bpms) = await open((_) async => (voices: wavs, click: null));
      final ctl = c.read(playbackControllerProvider(kScoreId).notifier);
      ctl.setBpm(150);
      expect(bpms.length, 1, reason: 'dragging alone must not render');
      ctl.commitBpm();
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(bpms.last, 150);
      expect(h.engines.length, 2);
      expect(h.engines.every((e) => e.speed == 1), isTrue);
      expect(h.engines.first.disposed, isTrue);
      expect(
        c.read(playbackControllerProvider(kScoreId)).source,
        PlaybackSource.midi,
      );
    });

    test(
      'playing: paused during the re-render, resumes on the new one',
      () async {
        final (c, h, _) = await open((_) async {
          await Future<void>.delayed(const Duration(milliseconds: 30));
          return (voices: wavs, click: null);
        });
        final ctl = c.read(playbackControllerProvider(kScoreId).notifier);
        await ctl.play();
        await Future<void>.delayed(const Duration(milliseconds: 10));
        ctl.setBpm(150);
        ctl.commitBpm();
        await Future<void>.delayed(const Duration(milliseconds: 10));
        expect(
          h.engines.first.playing,
          isFalse,
          reason: 'paused while rendering',
        );
        await Future<void>.delayed(const Duration(milliseconds: 100));
        expect(h.engines.length, 2);
        expect(h.engines.last.playing, isTrue);
      },
    );

    test('failed re-render falls back to stretched mp3', () async {
      var first = true;
      final (c, h, _) = await open((_) async {
        if (first) {
          first = false;
          return (voices: wavs, click: null);
        }
        return null;
      });
      final ctl = c.read(playbackControllerProvider(kScoreId).notifier);
      ctl.setBpm(150);
      ctl.commitBpm();
      await Future<void>.delayed(const Duration(milliseconds: 50));
      final s = c.read(playbackControllerProvider(kScoreId));
      expect(s.source, PlaybackSource.mp3);
      expect(h.engine.speed, s.speed);
    });

    for (final bpm in [35, 170]) {
      test(
        'indicator maps audio rendered at $bpm bpm back to score time',
        () async {
          final (c, h, _) = await open(
            (_) async => (voices: wavs, click: null),
          );
          final ctl = c.read(playbackControllerProvider(kScoreId).notifier);
          final timeline = c
              .read(playbackControllerProvider(kScoreId))
              .timeline!;
          expect(
            timeline.audioToScore,
            1,
            reason: 'rendered at the score tempo',
          );
          ctl.setBpm(bpm);
          ctl.commitBpm();
          await Future<void>.delayed(const Duration(milliseconds: 50));
          // testResult's score tempo is 90: audio is 90/bpm times longer.
          expect(timeline.audioToScore, closeTo(bpm / 90, 1e-9));
          final reference = ScoreTimeline(testTiming());
          // Score time 1500 ms (second onset) sounds at 1500 * 90 / bpm ms.
          final audio = Duration(
            microseconds: (1500 * 1000 * 90 / bpm).round(),
          );
          expect(
            timeline.positionAt(audio)!.x,
            reference.positionAt(const Duration(milliseconds: 1500))!.x,
          );
          // Skip targets are score time; the seek must be in audio time.
          await ctl.skipToEnd();
          expect(
            h.engine.seeks.last.inMicroseconds,
            closeTo(3500 * 1000 * 90 / bpm, 1),
          );
        },
      );
    }

    test('export uses the rendered WAVs at the chosen bpm, speed 1', () async {
      final dir = Directory.systemTemp.createTempSync('midi_export_test');
      addTearDown(() => dir.deleteSync(recursive: true));
      final clickFile = File('${dir.path}/click.wav')..writeAsBytesSync([1]);
      final (c, _, bpms) = await open(
        (_) async => (voices: wavs, click: clickFile.uri),
      );
      final ctl = c.read(playbackControllerProvider(kScoreId).notifier);
      ctl.setBpm(150);
      ctl.commitBpm();
      await Future<void>.delayed(const Duration(milliseconds: 50));
      final state = c.read(playbackControllerProvider(kScoreId));
      final service = _RecordingExportService();
      await runExport(
        service: service,
        writeClick: () async => throw StateError('server click used'),
        renderMidi: ctl.exportMidiRenderer(),
        state: state,
        selection: ExportSelection.empty(state.available)
            .toggleVoice(VoicePart.soprano)
            .toggleClick(),
        title: 'T',
        treeUri: 'tree',
      );
      final job = service.job!;
      expect(bpms.last, 150);
      expect(job.speed, 1);
      expect(job.inputs.map((i) => i.track), [wavs[VoicePart.soprano]]);
      final click = (await job.prepare!()).track;
      expect(click, isNot(clickFile.uri), reason: 'cache file is copied');
      expect(job.fileName, endsWith('.mp3'));
      expect(clickFile.existsSync(), isTrue);
    });

    test(
      'export of a MIDI score whose render fails does not use mp3',
      () async {
        final (c, _, _) = await open((_) async => (voices: wavs, click: null));
        final ctl = c.read(playbackControllerProvider(kScoreId).notifier);
        final state = c.read(playbackControllerProvider(kScoreId));
        final service = _RecordingExportService();
        await expectLater(
          runExport(
            service: service,
            writeClick: () async => Uri.parse('file:///x.wav'),
            renderMidi: () async => null,
            state: state,
            selection: ExportSelection.empty(state.available)
                .toggleVoice(VoicePart.soprano),
            title: 'T',
            treeUri: 'tree',
          ),
          throwsA(isA<GenerationFailed>()),
        );
        expect(service.job, isNull);
        expect(ctl.exportMidiRenderer(), isNotNull);
      },
    );
  });
}

class _RecordingExportService implements ExportService {
  ExportJob? job;

  @override
  Future<ExportResult> export(
    ExportJob job,
    String treeUri, {
    ExportCancelToken? cancel,
    ValueChanged<double>? onProgress,
  }) async {
    this.job = job;
    return const ExportResult(fileName: 'f.mp3', location: 'l');
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
