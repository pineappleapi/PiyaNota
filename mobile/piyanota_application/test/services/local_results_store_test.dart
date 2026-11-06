import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/services/local_results_store.dart';
import 'package:piyanota_application/services/score_result_api.dart';

const int _scoreId = 7;

class _FakeDownloader implements FileDownloader {
  final List<Uri> calls = [];

  /// URLs containing this text answer as expired.
  String expiredMarker = 'stale';

  @override
  Future<void> download(Uri url, String savePath) async {
    calls.add(url);
    if (url.toString().contains(expiredMarker)) {
      throw const ExpiredUrlException();
    }
    await File(savePath).writeAsString(
      url.path.contains('timing') ? '{"events": []}' : 'bytes of $url',
    );
  }
}

class _FakeApi implements ScoreResultApi {
  _FakeApi(this.next);

  Map<String, dynamic> next;
  bool offline = false;
  int fetches = 0;

  @override
  Future<ScoreResult> fetchResult(int scoreId) async {
    fetches++;
    if (offline) throw const ScoreResultNetworkException();
    return ScoreResult.fromJson(next);
  }

  @override
  Future<TimingFile> fetchTiming(Uri url) async => TimingFile.empty;
}

Map<String, dynamic> _file(String id, {String host = 'good'}) => {
  'url': 'https://$host.example/$id',
  'fileId': id,
  'sizeBytes': 0,
};

Map<String, dynamic> _result({
  String tag = 'a',
  String host = 'good',
  bool midi = true,
  bool withFiles = true,
}) => {
  'scoreId': _scoreId,
  'audioTracks': {'soprano': 'https://$host.example/audio/s$tag.mp3'},
  'scoreImages': ['https://$host.example/pages/p$tag.png'],
  'timingMetadataUrl': 'https://$host.example/timing/t$tag.json',
  if (withFiles) ...{
    'audioFiles': {'soprano': _file('audio/s$tag.mp3', host: host)},
    'pageFiles': [_file('pages/p$tag.png', host: host)],
    'timingFile': _file('timing/t$tag.json', host: host),
    'midiTracks': midi
        ? {'soprano': _file('midi/s$tag.mid', host: host)}
        : null,
  },
};

void main() {
  late Directory root;
  late _FakeDownloader downloader;
  late LocalResultsStore store;
  late _FakeApi inner;
  late LocalFirstScoreResultApi api;

  setUp(() async {
    root = await Directory.systemTemp.createTemp('results_test');
    downloader = _FakeDownloader();
    store = LocalResultsStore(
      rootProvider: () async => root,
      downloader: downloader,
    );
    inner = _FakeApi(_result());
    api = LocalFirstScoreResultApi(inner, store);
  });

  tearDown(() async {
    if (root.existsSync()) await root.delete(recursive: true);
  });

  // api.fetchResult starts a background sync; wait for it.
  Future<ScoreResult> reopen() async {
    final result = await api.fetchResult(_scoreId);
    await store.sync(_scoreId, inner.next, refetch: () async => null);
    return result;
  }

  Directory scoreDir() =>
      Directory('${root.path}${Platform.pathSeparator}$_scoreId');

  test(
    'first open streams, second open plays local files incl. MIDI',
    () async {
      final first = await reopen();
      expect(first.audioTracks[VoicePart.soprano]!.scheme, 'https');

      final second = await reopen();
      expect(second.audioTracks[VoicePart.soprano]!.scheme, 'file');
      expect(second.scoreImages.single!.scheme, 'file');
      expect(second.timingMetadataUrl!.scheme, 'file');
      final names = scoreDir().listSync().map((e) => e.uri.pathSegments.last);
      expect(names.where((n) => n.endsWith('.mid')), hasLength(1));
      expect(names, contains('manifest.json'));
      expect(names.where((n) => n.endsWith('.part')), isEmpty);
    },
  );

  test('a changed fileId downloads again and prunes the old file', () async {
    await reopen();
    final before = downloader.calls.length;
    inner.next = _result(tag: 'b');
    await reopen();
    expect(downloader.calls.length - before, 4);
    final names = scoreDir().listSync().map((e) => e.uri.pathSegments.last);
    expect(names.any((n) => n.contains('sa.mp3')), isFalse);
    expect(names.any((n) => n.contains('sb.mp3')), isTrue);
  });

  test('midiTracks null opens normally and saves no MIDI', () async {
    inner.next = _result(midi: false);
    final result = await reopen();
    expect(result.audioTracks, isNotEmpty);
    final names = scoreDir().listSync().map((e) => e.uri.pathSegments.last);
    expect(names.where((n) => n.endsWith('.mid')), isEmpty);
  });

  test('an old score with no file fields passes through untouched', () async {
    inner.next = _result(withFiles: false);
    final result = await api.fetchResult(_scoreId);
    expect(result.audioTracks[VoicePart.soprano]!.scheme, 'https');
    expect(downloader.calls, isEmpty);
  });

  test(
    'expired URL: /result is fetched again and the download retried',
    () async {
      inner.next = _result(host: 'good');
      await store.sync(
        _scoreId,
        _result(host: 'stale'),
        refetch: () async => (await inner.fetchResult(_scoreId)).rawJson,
      );
      final second = await reopen();
      expect(second.audioTracks[VoicePart.soprano]!.scheme, 'file');
    },
  );

  test('a failed download leaves no final file and does not throw', () async {
    inner.next = _result(host: 'stale');
    await reopen();
    final names = scoreDir().listSync().map((e) => e.uri.pathSegments.last);
    expect(names, isEmpty);
  });

  test('offline: opens from the saved manifest, else rethrows', () async {
    inner.offline = true;
    await expectLater(
      api.fetchResult(_scoreId),
      throwsA(isA<ScoreResultNetworkException>()),
    );
    inner.offline = false;
    await reopen();
    inner.offline = true;
    final result = await api.fetchResult(_scoreId);
    expect(result.audioTracks[VoicePart.soprano]!.scheme, 'file');
    final timing = await api.fetchTiming(result.timingMetadataUrl!);
    expect(timing, isA<TimingFile>());
  });

  test('offline: a missing MIDI file does not block opening', () async {
    await reopen();
    for (final e in scoreDir().listSync()) {
      if (e.path.endsWith('.mid') || e.path.contains('midi_')) e.deleteSync();
    }
    expect(await store.loadOffline(_scoreId), isNotNull);
  });

  test('timing read from a local file', () async {
    final file = File('${root.path}${Platform.pathSeparator}t.json');
    await file.writeAsString(jsonEncode({'events': [], 'bars': []}));
    final timing = await api.fetchTiming(file.uri);
    expect(timing.events, isEmpty);
  });

  test(
    'a size mismatch is a failed download: nothing kept, no manifest',
    () async {
      final data = _result();
      (data['audioFiles'] as Map)['soprano']['sizeBytes'] = 999;
      inner.next = data;
      await reopen();
      final names = scoreDir().listSync().map((e) => e.uri.pathSegments.last);
      expect(names.where((n) => n.contains('audio_soprano')), isEmpty);
      expect(names, isNot(contains('manifest.json')));
    },
  );

  test(
    'opening never creates the folder; a server file: URL is refused',
    () async {
      expect(await store.loadOffline(_scoreId), isNull);
      expect(scoreDir().existsSync(), isFalse);
      await reopen();
      final data = _result()
        ..remove('pageFiles')
        ..['scoreImages'] = ['file:///etc/hosts'];
      final remote = ScoreResult.fromJson(data, allowLocalFiles: true);
      expect(await store.localize(remote), isNull);
    },
  );

  test('deleteScore and deleteAll remove the folders', () async {
    await reopen();
    expect(scoreDir().existsSync(), isTrue);
    await store.deleteScore(_scoreId);
    expect(scoreDir().existsSync(), isFalse);
    await reopen();
    await store.deleteAll();
    expect(root.existsSync(), isFalse);
  });
}
