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

  static const String _manifestName = 'manifest.json';
  static const String _partSuffix = '.part';
  static final RegExp _unsafeNameChars = RegExp(r'[^A-Za-z0-9._-]');

  /// Download slots of a `/result` body: the J4 `audioFiles`, `midiTracks`
  /// (null on old scores), `pageFiles` and `timingFile`.
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

    final result = ScoreResult.fromJson(out, allowLocalFiles: true);
    // allowLocalFiles must not let a server-sent file: URL through.
    final dirUri = dir.uri.toString();
    bool ours(Uri? u) =>
        u == null || u.scheme != 'file' || u.toString().startsWith(dirUri);
    final safe =
        result.audioTracks.values.every(ours) &&
        result.scoreImages.every(ours) &&
        ours(result.timingMetadataUrl);
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

  /// Downloads whatever [data] names that is not local yet, then saves the
  /// manifest and prunes files an older fileId left behind. Never throws.
  /// On an expired URL, [refetch] gets fresh `/result` data once and the
  /// rest is retried with it. One sync per score at a time.
  Future<void> sync(
    int scoreId,
    Map<String, dynamic> data, {
    required Future<Map<String, dynamic>?> Function() refetch,
  }) => _running[scoreId] ??= _sync(scoreId, data, refetch).whenComplete(() {
    _running.remove(scoreId);
  });

  Future<void> _sync(
    int scoreId,
    Map<String, dynamic> data,
    Future<Map<String, dynamic>?> Function() refetch,
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
      final part = File(_path(dir, '$_manifestName$_partSuffix'));
      await part.writeAsString(jsonEncode(current));
      await part.rename(_path(dir, _manifestName));
      final keep = {
        _manifestName,
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

  /// Removes [scoreId]'s folder (score deleted). Never throws.
  Future<void> deleteScore(int scoreId) async {
    try {
      await _running[scoreId];
      final root = await _rootProvider();
      final dir = Directory('${root.path}${Platform.pathSeparator}$scoreId');
      if (await dir.exists()) await dir.delete(recursive: true);
    } on Object catch (e) {
      debugPrint('Local results: delete of $scoreId failed: $e');
    }
  }

  /// Removes every score's folder (account deleted). Never throws.
  Future<void> deleteAll() async {
    try {
      await Future.wait(_running.values);
      final root = await _rootProvider();
      if (await root.exists()) await root.delete(recursive: true);
    } on Object catch (e) {
      debugPrint('Local results: wipe failed: $e');
    }
  }
}

/// Wraps the real [ScoreResultApi]: a result with J4 files is opened from the
/// local copy where it exists, downloaded in the background where it does
/// not, and opened from the saved manifest when there is no connection.
class LocalFirstScoreResultApi implements ScoreResultApi {
  LocalFirstScoreResultApi(this._inner, this._store);

  final ScoreResultApi _inner;
  final LocalResultsStore _store;

  @override
  Future<ScoreResult> fetchResult(int scoreId) async {
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
