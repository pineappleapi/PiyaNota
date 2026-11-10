import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../models/measure_table.dart';
import '../models/score_result.dart';
import 'score_result_api.dart';

/// A signed URL the storage refused because it ran out (401, 403 or 410).
class ExpiredUrlException implements Exception {
  const ExpiredUrlException();
}

/// Fetches one URL to a path. Injected so tests need no network.
abstract interface class FileDownloader {
  /// Throws [ExpiredUrlException] when the signed URL has expired.
  Future<void> download(Uri url, String savePath);
}

class DioFileDownloader implements FileDownloader {
  DioFileDownloader(this._dio);

  final Dio _dio;

  static const Set<int> _expiredStatuses = {401, 403, 410};

  @override
  Future<void> download(Uri url, String savePath) async {
    try {
      // No Authorization header: the URLs are pre-signed and the session
      // token must not reach the storage host.
      await _dio.downloadUri(url, savePath);
    } on DioException catch (e) {
      if (_expiredStatuses.contains(e.response?.statusCode)) {
        throw const ExpiredUrlException();
      }
      rethrow;
    }
  }
}

typedef _Remote = ({Uri url, String fileId, int sizeBytes});

/// F10 / J4: one folder per score id holding the MP3s, MIDI files, pages and
/// timing JSON of a converted score, so it plays offline.
///
/// Files are named `<slot>_<fileId>`, so a changed fileId is a different
/// name and downloads again; the old file is pruned. `manifest.json` (the
/// last `/result` data) is written last: its presence means the folder is
/// complete enough to open without the server.
class LocalResultsStore {
  LocalResultsStore({required this._rootProvider, required this._downloader});

  final Future<Directory> Function() _rootProvider;
  final FileDownloader _downloader;
  final Map<int, Future<void>> _running = {};

  /// Bumped by [invalidate]. A sync or refresh that started under an older
  /// number must not write its (stale) manifest or check time.
  final Map<int, int> _generation = {};
  final Map<int, int> _runningGeneration = {};

  int generation(int scoreId) => _generation[scoreId] ?? 0;

  /// Serialises every write to a score's manifest and check time with
  /// [invalidate]'s delete, so a stale sync can never put a manifest back
  /// after an invalidate removed it: each writer re-checks the generation
  /// inside the lock.
  final Map<int, Future<void>> _manifestLocks = {};

  Future<T> _withManifestLock<T>(int scoreId, Future<T> Function() body) {
    final previous = _manifestLocks[scoreId] ?? Future<void>.value();
    final run = previous.then((_) => body());
    final tail = run.then<void>((_) {}, onError: (Object _) {});
    _manifestLocks[scoreId] = tail;
    unawaited(
      tail.whenComplete(() {
        if (identical(_manifestLocks[scoreId], tail)) {
          _manifestLocks.remove(scoreId);
        }
      }),
    );
    return run;
  }

  static const String _manifestName = 'manifest.json';
  static const String _checkedName = 'last_checked';
  static const String _partSuffix = '.part';
  static final RegExp _unsafeNameChars = RegExp(r'[^A-Za-z0-9._-]');

  /// Download slots of a `/result` body: the J4 `audioFiles`, `midiTracks`
  /// (null on old scores), `pageFiles`, `timingFile` and `midiCombined`.
  static Map<String, _Remote> _entries(Map<String, dynamic> data) {
    final out = <String, _Remote>{};
    void add(String slot, Object? value) {
      if (value is! Map) return;
      final url = value['url'];
      final fileId = value['fileId'];
      if (url is! String || fileId is! String || fileId.isEmpty) return;
      final uri = Uri.tryParse(url);
      if (uri == null || (uri.scheme != 'http' && uri.scheme != 'https')) {
        return;
      }
      final size = value['sizeBytes'];
      out[slot] = (url: uri, fileId: fileId, sizeBytes: size is int ? size : 0);
    }

    for (final (prefix, key) in [
      ('audio', 'audioFiles'),
      ('midi', 'midiTracks'),
    ]) {
      final group = data[key];
      if (group is! Map) continue;
      group.forEach((name, value) {
        final voice = parseVoicePart(name);
        if (voice != null) add('${prefix}_${voice.name}', value);
      });
    }
    final pages = data['pageFiles'];
    if (pages is List) {
      for (var i = 0; i < pages.length; i++) {
        add('page_$i', pages[i]);
      }
    }
    add('timing', data['timingFile']);
    add('midi_combined', data['midiCombined']);
    return out;
  }

  /// True when [data] carries J4 files (a server before B6 sends none).
  bool hasFiles(Map<String, dynamic> data) => _entries(data).isNotEmpty;

  // Prefixed by the slot so a hostile fileId (".." or similar) can never be
  // the whole name.
  static String _fileName(String slot, _Remote remote) =>
      '${slot}_${remote.fileId.replaceAll(_unsafeNameChars, '_')}';

  Future<Directory> _dir(int scoreId) async {
    final root = await _rootProvider();
    // Not created here: only a download makes the folder (see _sync).
    return Directory('${root.path}${Platform.pathSeparator}$scoreId');
  }

  static String _path(Directory dir, String name) =>
      '${dir.path}${Platform.pathSeparator}$name';

  /// [remote] with every already-downloaded file pointing at the local
  /// copy, or null when none is local yet.
  Future<ScoreResult?> localize(ScoreResult remote) async {
    final data = remote.rawJson;
    if (data == null) return null;
    return _localize(remote.scoreId, data);
  }

  Future<ScoreResult?> _localize(int scoreId, Map<String, dynamic> data) async {
    final dir = await _dir(scoreId);
    final local = <String, String>{};
    for (final MapEntry(:key, :value) in _entries(data).entries) {
      final file = File(_path(dir, _fileName(key, value)));
      if (await file.exists()) local[key] = file.uri.toString();
    }
    if (local.isEmpty) return null;

    final out = Map<String, dynamic>.of(data);
    final tracks = data['audioTracks'];
    if (tracks is Map) {
      out['audioTracks'] = {
        for (final MapEntry(:key, :value) in tracks.entries)
          key: local['audio_${parseVoicePart(key)?.name}'] ?? value,
      };
    }
    final images = data['scoreImages'];
    if (images is List) {
      out['scoreImages'] = [
        for (var i = 0; i < images.length; i++) local['page_$i'] ?? images[i],
      ];
    }
    out['timingMetadataUrl'] = local['timing'] ?? data['timingMetadataUrl'];
    final combined = data['midiCombined'];
    if (combined is Map && local['midi_combined'] != null) {
      out['midiCombined'] = {...combined, 'url': local['midi_combined']};
    }

    final result = ScoreResult.fromJson(out, allowLocalFiles: true);
    // allowLocalFiles must not let a server-sent file: URL through.
    final dirUri = dir.uri.toString();
    bool ours(Uri? u) =>
        u == null || u.scheme != 'file' || u.toString().startsWith(dirUri);
    final safe =
        result.audioTracks.values.every(ours) &&
        result.scoreImages.every(ours) &&
        ours(result.timingMetadataUrl) &&
        ours(result.midiCombined?.url);
    return safe ? result : null;
  }

  /// The last saved `/result` for opening with no connection, or null when
  /// the score was never fully downloaded.
  Future<ScoreResult?> loadOffline(int scoreId) async {
    try {
      final dir = await _dir(scoreId);
      final manifest = File(_path(dir, _manifestName));
      if (!await manifest.exists()) return null;
      final data = jsonDecode(await manifest.readAsString());
      if (data is! Map<String, dynamic>) return null;
      for (final MapEntry(:key, :value) in _entries(data).entries) {
        // Per-voice MIDI has no reader, so a missing one must not block
        // opening. midi_combined is required only when this manifest lists
        // it (an older download has no such entry, so it still loads and
        // playback falls back to the MP3s); sync writes the manifest only
        // after every listed file is downloaded.
        if (key.startsWith('midi_') && key != 'midi_combined') continue;
        if (!await File(_path(dir, _fileName(key, value))).exists()) {
          return null;
        }
      }
      return await _localize(scoreId, data);
    } on Object catch (e) {
      debugPrint('Local results: offline load failed for $scoreId: $e');
      return null;
    }
  }

  /// The server `version` of the saved manifest, or null (no manifest, or a
  /// server that sends none).
  Future<String?> storedVersion(int scoreId) async {
    try {
      final manifest = File(_path(await _dir(scoreId), _manifestName));
      final data = jsonDecode(await manifest.readAsString());
      final v = data is Map ? data['version'] : null;
      return v is String && v.isNotEmpty ? v : null;
    } on Object {
      return null;
    }
  }

  /// When the server last answered a background revalidation of [scoreId].
  /// Kept in the score folder so it survives restarts and dies with the score.
  Future<DateTime?> lastChecked(int scoreId) async {
    try {
      final text = await File(_path(await _dir(scoreId), _checkedName))
          .readAsString();
      final ms = int.tryParse(text);
      return ms == null ? null : DateTime.fromMillisecondsSinceEpoch(ms);
    } on Object {
      return null;
    }
  }

  /// Never throws; no folder (score never downloaded) means nothing to mark.
  Future<void> markChecked(int scoreId, DateTime at, {int? generation}) async {
    try {
      await _withManifestLock(scoreId, () async {
        // A check that began before invalidate() answered about the old
        // files.
        if (generation != null && generation != this.generation(scoreId)) {
          return;
        }
        final dir = await _dir(scoreId);
        if (!await dir.exists()) return;
        await File(_path(dir, _checkedName))
            .writeAsString('${at.millisecondsSinceEpoch}');
      });
    } on Object catch (e) {
      debugPrint('Local results: could not save check time for $scoreId: $e');
    }
  }

  /// Forgets only the check time, so the next open revalidates at once. For
  /// a score the server is known to have changed whose files could not be
  /// fetched yet; the saved copy stays playable. Never throws.
  Future<void> resetThrottle(int scoreId) async {
    try {
      await _withManifestLock(scoreId, () async {
        final file = File(_path(await _dir(scoreId), _checkedName));
        if (await file.exists()) await file.delete();
      });
    } on Object catch (e) {
      debugPrint('Local results: throttle reset of $scoreId failed: $e');
    }
  }

  /// Downloads whatever [data] names that is not local yet, then saves the
  /// manifest and prunes files an older fileId left behind. Never throws.
  /// On an expired URL, [refetch] gets fresh `/result` data once and the
  /// rest is retried with it. One sync per score at a time.
  Future<void> sync(
    int scoreId,
    Map<String, dynamic> data, {
    required Future<Map<String, dynamic>?> Function() refetch,
  }) {
    final gen = generation(scoreId);
    final running = _running[scoreId];
    if (running != null && _runningGeneration[scoreId] == gen) return running;
    // A sync begun before an invalidate carries the old files: let it end
    // (it writes no manifest), then run this one, never two at once on the
    // same .part files.
    late final Future<void> tracked;
    tracked = (running ?? Future<void>.value())
        .then((_) => _sync(scoreId, data, refetch, gen))
        .whenComplete(() {
          if (identical(_running[scoreId], tracked)) {
            _running.remove(scoreId);
            _runningGeneration.remove(scoreId);
          }
        });
    _running[scoreId] = tracked;
    _runningGeneration[scoreId] = gen;
    return tracked;
  }

  Future<void> _sync(
    int scoreId,
    Map<String, dynamic> data,
    Future<Map<String, dynamic>?> Function() refetch,
    int gen,
  ) async {
    try {
      final dir = await (await _dir(scoreId)).create(recursive: true);
      var current = data;
      try {
        await _fill(dir, current);
      } on ExpiredUrlException {
        final fresh = await refetch();
        if (fresh == null) return;
        current = fresh;
        await _fill(dir, current);
      }
      // invalidate() ran while this downloaded: its data is the old copy.
      // Checked again inside the lock, where nothing can slip in between the
      // check and the rename.
      final committed = await _withManifestLock(scoreId, () async {
        if (gen != generation(scoreId)) return false;
        final part = File(_path(dir, '$_manifestName$_partSuffix'));
        await part.writeAsString(jsonEncode(current));
        await part.rename(_path(dir, _manifestName));
        return true;
      });
      if (!committed) return;
      final keep = {
        _manifestName,
        _checkedName,
        for (final MapEntry(:key, :value) in _entries(current).entries)
          _fileName(key, value),
      };
      await for (final entity in dir.list()) {
        final name = entity.uri.pathSegments.lastWhere((s) => s.isNotEmpty);
        if (entity is File && !keep.contains(name)) await entity.delete();
      }
    } on Object catch (e) {
      debugPrint('Local results: download for $scoreId failed: $e');
    }
  }

  Future<void> _fill(Directory dir, Map<String, dynamic> data) async {
    for (final MapEntry(:key, :value) in _entries(data).entries) {
      final path = _path(dir, _fileName(key, value));
      if (await File(path).exists()) continue;
      // A download cut short must never sit at the final name.
      final part = File('$path$_partSuffix');
      try {
        await _downloader.download(value.url, part.path);
        // A truncated body must not be kept under the fileId's name.
        if (value.sizeBytes > 0 && await part.length() != value.sizeBytes) {
          throw const FileSystemException(
            'Downloaded size differs from sizeBytes',
          );
        }
        await part.rename(path);
      } on Object {
        if (await part.exists()) await part.delete();
        rethrow;
      }
    }
  }

  /// The files of [scoreId] changed on the server (a re-run replaced them):
  /// forget the manifest and check time, so the next open fetches `/result`
  /// instead of playing the old audio. The old files are pruned by the next
  /// sync. Never throws.
  Future<void> invalidate(int scoreId) async {
    // Bumped before the lock is taken: a writer already inside finishes
    // first and is then deleted; any later one sees the new number.
    _generation[scoreId] = generation(scoreId) + 1;
    try {
      await _withManifestLock(scoreId, () async {
        final dir = await _dir(scoreId);
        for (final name in [_manifestName, _checkedName]) {
          final file = File(_path(dir, name));
          if (await file.exists()) await file.delete();
        }
      });
    } on Object catch (e) {
      debugPrint('Local results: invalidate of $scoreId failed: $e');
    }
  }

  /// Removes [scoreId]'s folder (score deleted). Never throws.
  Future<void> deleteScore(int scoreId) async {
    try {
      final root = await _rootProvider();
      final dir = Directory('${root.path}${Platform.pathSeparator}$scoreId');
      // Delete first so a swiped-away app still wiped; the wait then
      // removes what a running download recreated.
      if (await dir.exists()) await dir.delete(recursive: true);
      final running = _running[scoreId];
      if (running != null) {
        await running;
        if (await dir.exists()) await dir.delete(recursive: true);
      }
    } on Object catch (e) {
      debugPrint('Local results: delete of $scoreId failed: $e');
    }
  }

  /// Removes every score's folder (account deleted). Never throws.
  Future<void> deleteAll() async {
    try {
      final root = await _rootProvider();
      final running = _running.values.toList();
      // Delete first so a swiped-away app still wiped; the wait then
      // removes what a running download recreated.
      if (await root.exists()) await root.delete(recursive: true);
      if (running.isNotEmpty) {
        await Future.wait(running);
        if (await root.exists()) await root.delete(recursive: true);
      }
    } on Object catch (e) {
      debugPrint('Local results: wipe failed: $e');
    }
  }
}

/// Wraps the real [ScoreResultApi]: a result with J4 files is opened from the
/// local copy where it exists, downloaded in the background where it does
/// not, and opened from the saved manifest when there is no connection.
class LocalFirstScoreResultApi implements ScoreResultApi {
  LocalFirstScoreResultApi(
    this._inner,
    this._store, {
    this._clock = DateTime.now,
    this.onSessionExpired,
  });

  final ScoreResultApi _inner;
  final LocalResultsStore _store;
  final DateTime Function() _clock;

  /// Told when a background refresh got a 401. It only raises a flag: local
  /// copies and rows stay, and nothing is paused.
  final void Function()? onSessionExpired;

  /// At most one background revalidation per score per window. A score with
  /// no recorded check (first open after download) is revalidated at once.
  static const Duration refreshInterval = Duration(hours: 6);

  /// The latest background refresh, so tests can wait for it.
  @visibleForTesting
  Future<void> refreshIdle = Future.value();

  @override
  Future<ScoreResult> fetchResult(int scoreId) async {
    // A fully downloaded score opens at once from the phone, wifi or not;
    // the server is only asked afterwards. Waiting on it first made every
    // open depend on the connection and sent the audio over the network
    // whenever a download had not finished at open time.
    final cached = await _store.loadOffline(scoreId);
    if (cached != null) {
      refreshIdle = _refreshInBackground(scoreId);
      return cached;
    }
    final ScoreResult remote;
    try {
      remote = await _inner.fetchResult(scoreId);
    } on ScoreResultNetworkException {
      final offline = await _store.loadOffline(scoreId);
      if (offline == null) rethrow;
      return offline;
    }
    final data = remote.rawJson;
    if (data == null || !_store.hasFiles(data)) return remote;
    // Never awaited: opening must not wait for the download.
    unawaited(
      _store.sync(
        scoreId,
        data,
        refetch: () async => (await _inner.fetchResult(scoreId)).rawJson,
      ),
    );
    try {
      return await _store.localize(remote) ?? remote;
    } on Object catch (e) {
      debugPrint('Local results: using server copy: $e');
      return remote;
    }
  }

  /// `/result` without a last-access touch when the inner API can.
  Future<ScoreResult?> _revalidate(int scoreId, {String? knownVersion}) {
    final Object inner = _inner;
    return inner is ScoreRevalidator
        ? inner.revalidate(scoreId, knownVersion: knownVersion)
        : _inner.fetchResult(scoreId);
  }

  /// Asks the server for the current `/result` after a local open and
  /// downloads whatever changed (a new fileId), so the NEXT open is current.
  /// This open keeps the copy it already has. Never throws: no connection,
  /// an expired session or a deleted score just leaves the local copy as is.
  ///
  /// Throttled to [refreshInterval] per score; only an answered check resets
  /// it. Sends the stored `version`, so "unchanged" skips signing and file
  /// work. The server's version ignores title/arranger edits (the library
  /// list carries those) and review/mutedMeasures/failedVoices edits; those
  /// three are written by the pipeline together with the files, so a re-run
  /// changes the version anyway. Old servers send no version: full payload,
  /// same as before.
  ///
  /// A 401 is reported through [onSessionExpired] (the foreground shows the
  /// Login prompt) but never signs the app out here: a stray 401 must not
  /// pause reconcile or touch the local copy.
  Future<void> _refreshInBackground(int scoreId) async {
    final gen = _store.generation(scoreId);
    try {
      final last = await _store.lastChecked(scoreId);
      if (last != null && _clock().difference(last) < refreshInterval) return;
      final remote = await _revalidate(
        scoreId,
        knownVersion: await _store.storedVersion(scoreId),
      );
      if (remote == null) {
        await _store.markChecked(scoreId, _clock(), generation: gen);
        return;
      }
      final data = remote.rawJson;
      if (data == null || !_store.hasFiles(data)) return;
      await _store.sync(
        scoreId,
        data,
        refetch: () async => (await _revalidate(scoreId))?.rawJson,
      );
      // A sync that failed part-way keeps the old manifest: stay unthrottled.
      if (await _store.storedVersion(scoreId) == data['version']) {
        await _store.markChecked(scoreId, _clock(), generation: gen);
      }
    } on ScoreResultSessionExpiredException {
      onSessionExpired?.call();
    } on Object catch (e) {
      debugPrint('Local results: background refresh for $scoreId skipped: $e');
    }
  }

  @override
  Future<TimingFile> fetchTiming(Uri url) async {
    if (url.scheme != 'file') return _inner.fetchTiming(url);
    try {
      final text = await File.fromUri(url).readAsString();
      return TimingFile.parse(jsonDecode(text));
    } on Object catch (e) {
      debugPrint('Local results: timing file unreadable: $e');
      throw const ScoreResultServerException();
    }
  }
}
