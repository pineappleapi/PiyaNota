import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../models/export_selection.dart';

/// One track in the export mix: a voice (or the click) and the gain the
/// Voice Mixer plays it at.
typedef ExportInput = ({Uri track, double gain});

/// Everything the device needs to make the export file (PIYA-211).
@immutable
class ExportJob {
  const ExportJob({
    required this.inputs,
    required this.speed,
    required this.fileName,
  });

  final List<ExportInput> inputs;

  /// Playback rate, chosen BPM / the score's tempo; pitch is kept (FR-9).
  final double speed;

  /// Before the clash check (AC15); the saved name may gain " (n)".
  final String fileName;
}

@immutable
class ExportResult {
  const ExportResult({required this.fileName, required this.location});

  /// The name the file was actually saved under.
  final String fileName;

  /// A readable folder path for the success dialog (AC16).
  final String location;
}

/// Why an export failed (AC18). Each has its own message and the same
/// Retry, so the sheet can tell them apart without parsing strings.
sealed class ExportFailure implements Exception {
  const ExportFailure();
}

final class StorageFull extends ExportFailure {
  const StorageFull();
}

final class PermissionDenied extends ExportFailure {
  const PermissionDenied();
}

final class GenerationFailed extends ExportFailure {
  const GenerationFailed();
}

final class Interrupted extends ExportFailure {
  const Interrupted();
}

abstract interface class ExportService {
  /// The folder the user picked (AC10), or null if they cancelled (AC11).
  Future<String?> pickFolder();

  /// Makes the MP3 and saves it in [treeUri]. Throws [ExportFailure].
  Future<ExportResult> export(ExportJob job, String treeUri);

  /// Opens [treeUri] in a file manager; false when none can (AC16).
  Future<bool> openFolder(String treeUri);
}

/// The Android side is `export/ExportChannel.kt`.
class MethodChannelExportService implements ExportService {
  MethodChannelExportService({required this._dio, required this._workDir});

  static const MethodChannel _channel = MethodChannel('piyanota/export');

  final Dio _dio;
  final Future<Directory> Function() _workDir;

  /// errno for "No space left on device" on Linux/Android.
  static const int _enospc = 28;

  @override
  Future<String?> pickFolder() =>
      _call(() => _channel.invokeMethod<String>('pickFolder'));

  @override
  Future<bool> openFolder(String treeUri) async {
    try {
      return await _channel.invokeMethod<bool>('openFolder', {
            'treeUri': treeUri,
          }) ??
          false;
    } on PlatformException catch (e) {
      // Only hides the "Open folder" button; the file is already saved.
      debugPrint('Export: open folder failed: ${e.code} ${e.message}');
      return false;
    } on MissingPluginException catch (e) {
      debugPrint('Export: open folder unavailable: $e');
      return false;
    }
  }

  @override
  Future<ExportResult> export(ExportJob job, String treeUri) async {
    final base = await _workDir();
    final dir = await base.createTemp('export_');
    try {
      final inputs = <Map<String, Object>>[];
      for (final (index, input) in job.inputs.indexed) {
        inputs.add({
          'path': await _localPath(input.track, dir, index),
          'gain': input.gain,
        });
      }
      final out = '${dir.path}${Platform.pathSeparator}export.mp3';
      await _call(
        () => _channel.invokeMethod<void>('render', {
          'inputs': inputs,
          'speed': job.speed,
          'outPath': out,
        }),
      );
      final names = await _call(
        () => _channel.invokeListMethod<String>('listNames', {
          'treeUri': treeUri,
        }),
      );
      final saved = await _call(
        () => _channel.invokeMapMethod<String, String>('save', {
          'treeUri': treeUri,
          'fileName': uniqueFileName(job.fileName, {...?names}),
          'srcPath': out,
        }),
      );
      final fileName = saved?['fileName'];
      final location = saved?['location'];
      if (fileName == null || location == null) {
        throw const GenerationFailed();
      }
      return ExportResult(fileName: fileName, location: location);
    } finally {
      try {
        await dir.delete(recursive: true);
      } on FileSystemException catch (e) {
        // The OS clears the cache eventually; not worth failing a saved
        // export over.
        debugPrint('Export: temp files not removed: $e');
      }
    }
  }

  /// The track as a local file: a `file:` Uri as it is, an http(s) one
  /// downloaded into [dir] first (the native side reads files only).
  Future<String> _localPath(Uri track, Directory dir, int index) async {
    if (track.scheme == 'file') return track.toFilePath();
    if (track.scheme != 'https' && track.scheme != 'http') {
      debugPrint('Export: unsupported track scheme ${track.scheme}');
      throw const GenerationFailed();
    }
    final path = '${dir.path}${Platform.pathSeparator}track_$index';
    try {
      await _dio.downloadUri(track, path);
      return path;
    } on DioException catch (e) {
      debugPrint('Export: track download failed: ${e.type} ${e.message}');
      throw switch (e.type) {
        // The connection dropped or never came (AC18 "Download
        // interrupted").
        DioExceptionType.connectionTimeout ||
        DioExceptionType.sendTimeout ||
        DioExceptionType.receiveTimeout ||
        DioExceptionType.connectionError ||
        DioExceptionType.cancel => const Interrupted(),
        DioExceptionType.unknown when _isOutOfSpace(e.error) =>
          const StorageFull(),
        DioExceptionType.unknown when e.error is SocketException =>
          const Interrupted(),
        // A 4xx/5xx or a bad certificate: retrying the same URL will not
        // help, so it is reported as the file not being made.
        _ => const GenerationFailed(),
      };
    } on FileSystemException catch (e) {
      debugPrint('Export: track not written: $e');
      throw _isOutOfSpace(e) ? const StorageFull() : const GenerationFailed();
    }
  }

  static bool _isOutOfSpace(Object? error) =>
      error is FileSystemException && error.osError?.errorCode == _enospc;

  /// Maps the channel's error codes to [ExportFailure].
  static Future<T> _call<T>(Future<T> Function() call) async {
    try {
      return await call();
    } on PlatformException catch (e) {
      debugPrint('Export: native step failed: ${e.code} ${e.message}');
      throw switch (e.code) {
        'storage_full' => const StorageFull(),
        'permission_denied' => const PermissionDenied(),
        'interrupted' => const Interrupted(),
        _ => const GenerationFailed(),
      };
    } on MissingPluginException catch (e) {
      debugPrint('Export: channel unavailable: $e');
      throw const GenerationFailed();
    }
  }
}
