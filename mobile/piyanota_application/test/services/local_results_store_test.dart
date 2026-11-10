import 'dart:async';
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

  /// When set, downloads wait on it (a slow storage host).
  Completer<void>? gate;

  @override
  Future<void> download(Uri url, String savePath) async {
    calls.add(url);
    await gate?.future;
    if (url.toString().contains(expiredMarker)) {
      throw const ExpiredUrlException();
    }
    await File(savePath).writeAsString(
      url.path.contains('timing') ? '{"events": []}' : 'bytes of $url',
    );
  }
}

class _FakeApi implements ScoreResultApi, ScoreRevalidator {
  _FakeApi(this.next);

  Map<String, dynamic> next;
  bool offline = false;

  /// Thrown by fetchResult when set (e.g. an expired session).
  Object? error;
  int fetches = 0;

  /// Version sent by each revalidate call (null entry = none sent). Every
  /// revalidate call is a touch=false call.
  final List<String?> revalidations = [];

  @override
  Future<ScoreResult?> revalidate(int scoreId, {String? knownVersion}) async {
    revalidations.add(knownVersion);
    final result = await fetchResult(scoreId);
    final current = next['version'];
    return knownVersion != null && knownVersion == current ? null : result;
  }

  /// When set, fetchResult waits on it (a slow server).
  Future<void>? gate;

  @override
  Future<ScoreResult> fetchResult(int scoreId) async {
    fetches++;
    await gate;
    if (offline) throw const ScoreResultNetworkException();
    if (error != null) throw error!;
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
  bool combined = false,
}) => {
  'scoreId': _scoreId,
  'audioTracks': {'soprano': 'https://$host.example/audio/s$tag.mp3'},
  'scoreImages': ['https://$host.example/pages/p$tag.png'],
  'timingMetadataUrl': 'https://$host.example/timing/t$tag.json',
  if (withFiles) ...{
    'audioFiles': {'soprano': _file('audio/s$tag.mp3', host: host)},
    'pageFiles': [_file('pages/p$tag.png', host: host)],
    'timingFile': _file('timing/t$tag.json', host: host),
    if (combined) 'midiCombined': _file('midi/all$tag.mid', host: host),
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
    // A background refresh still writing would break the delete.
    await api.refreshIdle;
    if (root.existsSync()) await root.delete(recursive: true);
  });

  // api.fetchResult starts a background sync; wait for it.
  Future<ScoreResult> reopen() async {
    final result = await api.fetchResult(_scoreId);
    await api.refreshIdle;
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

  test(
    'a downloaded score opens locally without waiting on the server',
    () async {
      await reopen();
      final gate = Completer<void>();
      inner.gate = gate.future;
      final opened = await api
          .fetchResult(_scoreId)
          .timeout(const Duration(seconds: 2));
      expect(opened.audioTracks[VoicePart.soprano]!.scheme, 'file');
      // Let the background refresh finish before tearDown deletes the folder.
      gate.complete();
      await pumpEventQueue();
      await store.sync(_scoreId, inner.next, refetch: () async => null);
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

  test(
    'midiCombined is downloaded, localized, and pruned on new fileId',
    () async {
      inner.next = _result(combined: true);
      await reopen();
      final second = await reopen();
      expect(second.midiCombined!.url.scheme, 'file');
      expect(second.midiCombined!.fileId, 'midi/alla.mid');
      inner.next = _result(tag: 'b', combined: true);
      await reopen();
      final names = scoreDir().listSync().map((e) => e.uri.pathSegments.last);
      expect(
        names.any((n) => n.startsWith('midi_combined_') && n.contains('allb')),
        isTrue,
      );
      expect(names.any((n) => n.contains('alla')), isFalse);
    },
  );

  test('offline: a manifest without midiCombined still loads', () async {
    await reopen();
    final loaded = await store.loadOffline(_scoreId);
    expect(loaded, isNotNull);
    expect(loaded!.midiCombined, isNull);
  });

  test(
    'offline: a listed but missing midiCombined file blocks opening',
    () async {
      inner.next = _result(combined: true);
      await reopen();
      for (final e in scoreDir().listSync()) {
        if (e.path.contains('midi_combined_')) e.deleteSync();
      }
      expect(await store.loadOffline(_scoreId), isNull);
    },
  );

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

  group('background revalidation', () {
    var now = DateTime(2026, 11, 10, 8);

    setUp(() {
      now = DateTime(2026, 11, 10, 8);
      inner.next = {..._result(), 'version': 'v1'};
      api = LocalFirstScoreResultApi(inner, store, clock: () => now);
    });

    /// Opens, then waits for the background refresh it started.
    Future<void> open() async {
      await api.fetchResult(_scoreId);
      await api.refreshIdle;
    }

    Future<void> download() async {
      await api.fetchResult(_scoreId);
      await store.sync(_scoreId, inner.next, refetch: () async => null);
    }

    test('sends the stored version; unchanged skips downloads', () async {
      await download();
      final before = downloader.calls.length;
      await open();
      expect(inner.revalidations, ['v1']);
      expect(downloader.calls.length, before);
    });

    test('a second open inside the window does not call the server', () async {
      await download();
      await open();
      final calls = inner.fetches;
      now = now.add(const Duration(hours: 5));
      await open();
      expect(inner.fetches, calls);
    });

    test('after the window it asks again; a failed ask keeps asking', () async {
      await download();
      await open();
      now = now.add(LocalFirstScoreResultApi.refreshInterval);
      inner.offline = true;
      await open();
      await open();
      expect(inner.revalidations, hasLength(3));
      inner.offline = false;
      await open();
      expect(inner.revalidations, hasLength(4));
      await open();
      expect(inner.revalidations, hasLength(4));
    });

    test('a new version syncs and is stored', () async {
      await download();
      await open();
      now = now.add(const Duration(hours: 7));
      inner.next = {..._result(tag: 'b'), 'version': 'v2'};
      await open();
      expect(inner.revalidations, ['v1', 'v1']);
      expect(await store.storedVersion(_scoreId), 'v2');
      final names = scoreDir().listSync().map((e) => e.uri.pathSegments.last);
      expect(names.any((n) => n.contains('sb.mp3')), isTrue);
      expect(names.any((n) => n.contains('sa.mp3')), isFalse);
    });

    test('the throttle survives a new instance', () async {
      await download();
      await open();
      final calls = inner.fetches;
      api = LocalFirstScoreResultApi(inner, store, clock: () => now);
      await open();
      expect(inner.fetches, calls);
    });

    test('a server without version still refreshes', () async {
      inner.next = _result();
      await download();
      await open();
      inner.next = _result(tag: 'b');
      now = now.add(const Duration(hours: 7));
      await open();
      expect(inner.revalidations, [null, null]);
      final names = scoreDir().listSync().map((e) => e.uri.pathSegments.last);
      expect(names.any((n) => n.contains('sb.mp3')), isTrue);
    });
  });

  test('deleteScore and deleteAll remove the folders', () async {
    await reopen();
    expect(scoreDir().existsSync(), isTrue);
    await store.deleteScore(_scoreId);
    expect(scoreDir().existsSync(), isFalse);
    await reopen();
    await store.deleteAll();
    expect(root.existsSync(), isFalse);
  });

  test('invalidate (a re-run replaced the files) makes the next open fetch '
      'the new result even inside the throttle window (I2)', () async {
    inner.next = {..._result(tag: 'a'), 'version': 'v1'};
    await reopen();
    await reopen(); // throttled: last_checked is now
    expect(await store.lastChecked(_scoreId), isNotNull);

    inner.next = {..._result(tag: 'b'), 'version': 'v2'};
    await store.invalidate(_scoreId);
    expect(await store.loadOffline(_scoreId), isNull);
    expect(await store.lastChecked(_scoreId), isNull);

    final opened = await reopen();
    expect(opened.audioTracks.values.single.toString(), contains('sb.mp3'));
    expect(await store.storedVersion(_scoreId), 'v2');
  });

  test('an invalidate wins over a sync already in flight: the stale manifest '
      'is not written and the next open fetches the new result', () async {
    final stale = {..._result(tag: 'a'), 'version': 'v1'};
    downloader.gate = Completer<void>();
    final syncing = store.sync(_scoreId, stale, refetch: () async => null);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(downloader.calls, isNotEmpty, reason: 'sync is mid-download');

    await store.invalidate(_scoreId); // a retake finished meanwhile
    downloader.gate!.complete();
    await syncing;
    expect(
      await store.storedVersion(_scoreId),
      isNull,
      reason: 'the in-flight sync must not write the old manifest',
    );
    expect(await store.loadOffline(_scoreId), isNull);

    downloader.gate = null;
    inner.next = {..._result(tag: 'b'), 'version': 'v2'};
    final opened = await reopen();
    expect(opened.audioTracks.values.single.toString(), contains('sb.mp3'));
    expect(await store.storedVersion(_scoreId), 'v2');
  });

  test('an expired session during the background refresh leaves the local '
      'copy alone and records no check (M6, documented shortcut)', () async {
    inner.next = {..._result(tag: 'a'), 'version': 'v1'};
    await reopen();
    final checkedFile = File(
      '${scoreDir().path}${Platform.pathSeparator}last_checked',
    );
    if (checkedFile.existsSync()) await checkedFile.delete();
    inner.error = const ScoreResultSessionExpiredException();

    final opened = await api.fetchResult(_scoreId);
    await api.refreshIdle;
    expect(opened.audioTracks, isNotEmpty);
    expect(await store.storedVersion(_scoreId), 'v1');
    expect(await store.loadOffline(_scoreId), isNotNull);
    expect(await store.lastChecked(_scoreId), isNull);
  });

  test(
    'an expired session during the background refresh is reported through '
    'onSessionExpired, once per open, and nothing is signed out here',
    () async {
      inner.next = {..._result(tag: 'a'), 'version': 'v1'};
      await reopen();
      var reported = 0;
      final reporting = LocalFirstScoreResultApi(
        inner,
        store,
        onSessionExpired: () => reported++,
      );
      inner.error = const ScoreResultSessionExpiredException();

      final opened = await reporting.fetchResult(_scoreId);
      await reporting.refreshIdle;
      expect(opened.audioTracks, isNotEmpty, reason: 'the local copy opens');
      expect(reported, 1);
      expect(await store.storedVersion(_scoreId), 'v1');
    },
  );

  test('resetThrottle forgets only the check time: the saved copy stays '
      'playable and the next open asks the server at once', () async {
    inner.next = {..._result(tag: 'a'), 'version': 'v1'};
    await reopen();
    await reopen(); // the second open records a check
    expect(await store.lastChecked(_scoreId), isNotNull);

    await store.resetThrottle(_scoreId);
    expect(await store.lastChecked(_scoreId), isNull);
    expect(await store.loadOffline(_scoreId), isNotNull);
    expect(await store.storedVersion(_scoreId), 'v1');
  });

  test('a check recorded by an older generation is dropped after an '
      'invalidate (no stale throttle on the new copy)', () async {
    inner.next = {..._result(tag: 'a'), 'version': 'v1'};
    await reopen();
    final stale = store.generation(_scoreId);
    await store.invalidate(_scoreId);
    await store.markChecked(_scoreId, DateTime.now(), generation: stale);
    expect(await store.lastChecked(_scoreId), isNull);
  });
}
