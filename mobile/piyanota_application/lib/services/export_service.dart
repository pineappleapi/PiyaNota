import 'dart:async';
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

/// The user pressed Cancel. Not an error: nothing was saved, and the
/// partial file and temp files are gone.
final class Cancelled extends ExportFailure {
  const Cancelled();
}

/// The phone has no app for choosing a folder (some stripped-down ROMs
/// ship without one). Kept apart from [PermissionDenied]: "choose another
/// folder" is advice the user cannot follow here.
final class NoFolderPicker extends ExportFailure {
  const NoFolderPicker();
}

/// One export's Cancel button. Single use: a new export gets a new one,
/// so a late tap on an old sheet can never stop the next export.
class ExportCancelToken {
  final Completer<void> _cancelled = Completer<void>();

  bool get isCancelled => _cancelled.isCompleted;

  /// Completes when [cancel] is called; never errors.
  Future<void> get whenCancelled => _cancelled.future;

  void cancel() {
    if (!_cancelled.isCompleted) _cancelled.complete();
  }

  /// Between steps, so a cancel during one step stops the next.
  void throwIfCancelled() {
    if (isCancelled) throw const Cancelled();
  }
}

abstract interface class ExportService {
  /// The folder the user picked (AC10), or null if they cancelled (AC11).
  Future<String?> pickFolder();

  /// Makes the MP3 and saves it in [treeUri]. Throws [ExportFailure];
  /// [Cancelled] once [cancel] is cancelled, unless the file was already
  /// saved by then (it is then reported as saved, because it is).
  /// [onProgress] gets the render's 0..1, never going back.
  Future<ExportResult> export(
    ExportJob job,
    String treeUri, {
    ExportCancelToken? cancel,
    ValueChanged<double>? onProgress,
  });

  /// Opens [treeUri] in a file manager; false when none can (AC16).
  Future<bool> openFolder(String treeUri);
}

/// The Android side is `export/ExportChannel.kt`.
class MethodChannelExportService implements ExportService {
  MethodChannelExportService({required this._dio, required this._workDir});

  static const MethodChannel _channel = MethodChannel('piyanota/export');

  final Dio _dio;
  final Future<Directory> Function() _workDir;

  /// Called by the native side during render (ExportChannel.kt).
  static const String _progressMethod = 'progress';

  /// errno for "No space left on device" on Linux/Android.
  static const int _enospc = 28;

  /// Prefix of each export's work folder in the cache.
  static const String _workPrefix = 'export_';

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
  Future<ExportResult> export(
    ExportJob job,
    String treeUri, {
    ExportCancelToken? cancel,
    ValueChanged<double>? onProgress,
  }) async {
    final token = cancel ?? ExportCancelToken();
    token.throwIfCancelled();
    final downloads = CancelToken();
    var finished = false;
    unawaited(
      token.whenCancelled.then((_) async {
        if (finished) return;
        downloads.cancel();
        await _sendCancel();
      }),
    );
    final progress = ExportProgress(onProgress);
    _channel.setMethodCallHandler((call) async {
      if (call.method == _progressMethod) progress.report(call.arguments);
    });
    final base = await _workDir();
    await _clearStaleWork(base);
    final dir = await base.createTemp(_workPrefix);
    try {
      final inputs = <Map<String, Object>>[];
      for (final (index, input) in job.inputs.indexed) {
        inputs.add({
          'path': await _localPath(input.track, dir, index, downloads, token),
          'gain': input.gain,
        });
      }
      final out = '${dir.path}${Platform.pathSeparator}export.mp3';
      // Checked here, not left to the native flag: render resets that
      // flag when it starts, so a cancel from before it would be lost.
      token.throwIfCancelled();
      await _call(
        () => _channel.invokeMethod<void>('render', {
          'inputs': inputs,
          'speed': job.speed,
          'outPath': out,
        }),
      );
      token.throwIfCancelled();
      final names = await _call(
        () => _channel.invokeListMethod<String>('listNames', {
          'treeUri': treeUri,
        }),
      );
      token.throwIfCancelled();
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
      finished = true;
      _channel.setMethodCallHandler(null);
      try {
        await dir.delete(recursive: true);
      } on FileSystemException catch (e) {
        // The OS clears the cache eventually; not worth failing a saved
        // export over.
        debugPrint('Export: temp files not removed: $e');
      }
    }
  }

  /// Removes work folders an earlier export left when the app was killed
  /// mid-render (the finally below never ran). Only one export runs at a
  /// time (the sheet is busy throughout), so none of these is in use.
  static Future<void> _clearStaleWork(Directory base) async {
    try {
      await for (final entry in base.list(followLinks: false)) {
        final name = entry.uri.pathSegments.lastWhere(
          (segment) => segment.isNotEmpty,
          orElse: () => '',
        );
        if (entry is Directory && name.startsWith(_workPrefix)) {
          await entry.delete(recursive: true);
        }
      }
    } on FileSystemException catch (e) {
      // Only reclaims cache space; this export can still go ahead.
      debugPrint('Export: stale work folders not removed: $e');
    }
  }

  /// Tells the native side to stop the render or save under way; the
  /// reply to that call then fails with `cancelled`.
  static Future<void> _sendCancel() async {
    try {
      await _channel.invokeMethod<void>('cancel');
    } on PlatformException catch (e) {
      debugPrint('Export: cancel not delivered: ${e.code} ${e.message}');
    } on MissingPluginException catch (e) {
      debugPrint('Export: cancel unavailable: $e');
    }
  }

  /// The track as a local file: a `file:` Uri as it is, an http(s) one
  /// downloaded into [dir] first (the native side reads files only).
  Future<String> _localPath(
    Uri track,
    Directory dir,
    int index,
    CancelToken downloads,
    ExportCancelToken token,
  ) async {
    if (track.scheme == 'file') return track.toFilePath();
    if (track.scheme != 'https' && track.scheme != 'http') {
      debugPrint('Export: unsupported track scheme ${track.scheme}');
      throw const GenerationFailed();
    }
    final path = '${dir.path}${Platform.pathSeparator}track_$index';
    try {
      await _dio.downloadUri(track, path, cancelToken: downloads);
      return path;
    } on DioException catch (e) {
      if (token.isCancelled) throw const Cancelled();
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
        'cancelled' => const Cancelled(),
        'no_folder_picker' => const NoFolderPicker(),
        _ => const GenerationFailed(),
      };
    } on MissingPluginException catch (e) {
      debugPrint('Export: channel unavailable: $e');
      throw const GenerationFailed();
    }
  }
}

/// The render's progress as the sheet shows it: clamped to 0..1, and
/// never moving back, whatever order or values the channel delivers.
class ExportProgress {
  ExportProgress(this._onProgress);

  final ValueChanged<double>? _onProgress;
  double _last = 0;
  bool _started = false;

  double get value => _last;

  void report(Object? raw) {
    if (raw is! num || raw.isNaN) {
      debugPrint('Export: ignored progress value $raw');
      return;
    }
    final next = raw.toDouble().clamp(0.0, 1.0);
    if (_started && next <= _last) return;
    _started = true;
    _last = next;
    _onProgress?.call(next);
  }
}
