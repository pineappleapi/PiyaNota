import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

/// On-disk copy of each score's library thumbnail, keyed by score id.
///
/// `Image.network` only caches in memory and the API hands out expiring
/// signed URLs, so after an app restart (offline, or with a stale URL) the
/// tile would otherwise fall back to the placeholder. A thumbnail never
/// changes for a given score, so the file is fetched once and kept.
class ThumbnailCache {
  const ThumbnailCache._();

  static const String _folder = 'score_thumbnails';
  static const Duration _fetchTimeout = Duration(seconds: 15);

  /// Tests point this at a temp folder; production uses app support storage.
  @visibleForTesting
  static Future<Directory> Function() directoryProvider = _defaultDirectory;

  static Future<Directory> _defaultDirectory() async {
    final base = await getApplicationSupportDirectory();
    final dir = Directory('${base.path}${Platform.pathSeparator}$_folder');
    await dir.create(recursive: true);
    return dir;
  }

  // Ids come from the API; keep only filename-safe characters.
  static String _safe(String id) =>
      id.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_');

  static Future<File> _file(String scoreId) async {
    final dir = await directoryProvider();
    return File('${dir.path}${Platform.pathSeparator}${_safe(scoreId)}');
  }

  /// The saved thumbnail, or null when none is stored or storage fails.
  static Future<File?> cached(String scoreId) async {
    try {
      final file = await _file(scoreId);
      return await file.exists() && await file.length() > 0 ? file : null;
    } on Object catch (e) {
      debugPrint('Thumbnail cache read failed: $e');
      return null;
    }
  }

  /// Downloads [url] into the cache. Best effort: a failure only means the
  /// next launch tries again.
  static Future<void> fetch(String scoreId, String url) async {
    final client = HttpClient()..connectionTimeout = _fetchTimeout;
    try {
      final request = await client
          .getUrl(Uri.parse(url))
          .timeout(_fetchTimeout);
      final response = await request.close().timeout(_fetchTimeout);
      if (response.statusCode != HttpStatus.ok) return;
      final builder = BytesBuilder(copy: false);
      await for (final chunk in response.timeout(_fetchTimeout)) {
        builder.add(chunk);
      }
      final bytes = builder.takeBytes();
      if (bytes.isEmpty) return;
      final file = await _file(scoreId);
      // Write-then-rename so a killed app never leaves a half-written image.
      final temp = File('${file.path}.part');
      await temp.writeAsBytes(bytes, flush: true);
      await temp.rename(file.path);
    } on Object catch (e) {
      debugPrint('Thumbnail fetch failed: $e');
    } finally {
      client.close(force: true);
    }
  }

  /// Deletes every saved thumbnail (logout, account switch, account delete).
  static Future<void> clearAll() async {
    try {
      final dir = await directoryProvider();
      if (await dir.exists()) await dir.delete(recursive: true);
    } on Object catch (e) {
      debugPrint('Thumbnail cache not cleared: $e');
    }
  }
}
