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
/// partial file and temp files are gone, unless [partialFileLeft].
final class Cancelled extends ExportFailure {
  const Cancelled({this.partialFileLeft = false});

  /// The save was stopped part-way and the phone would not let the
  /// unfinished file be removed, so it may still be in the folder. The
  /// sheet must not say "Nothing was saved" then.
  final bool partialFileLeft;
}

/// The picked folder is not on this phone (Drive, another app's storage,
/// the cloud). Exports are saved only to the phone's own storage (user
/// decision 2026-10-21), so the user is asked to pick again.
final class NotLocalFolder extends ExportFailure {
  const NotLocalFolder();
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

/// Folder providers that keep files on this phone (user decision
/// 2026-10-21). Mirrors `LocalFolders.kt`, which refuses the rest before
/// any permission is kept; checked here too in case a picker ignores
/// EXTRA_LOCAL_ONLY and the native check is ever bypassed.
///  - externalstorage: internal storage and SD cards.
///  - downloads: only the phone's own Download folder, no cloud backing.
const Set<String> localFolderAuthorities = {
  'com.android.externalstorage.documents',
  'com.android.providers.downloads.documents',
};

/// [treeUri] is a folder on this phone.
bool isLocalFolder(String treeUri) {
  final uri = Uri.tryParse(treeUri);
  return uri != null &&
      uri.scheme == 'content' &&
      localFolderAuthorities.contains(uri.host);
}

abstract interface class ExportService {
  /// The folder the user picked (AC10), or null if they cancelled (AC11).
  /// Throws [NotLocalFolder] for a folder that is not on this phone.
  Future<String?> pickFolder();

  /// Makes the MP3 and saves it in [treeUri]. Throws [ExportFailure];
  /// [Cancelled] once [cancel] is cancelled, unless the file was already
  /// saved by then (it is then reported as saved, because it is).
  /// [onProgress] gets the whole export's 0..1 (download, render, save;
  /// see [ExportProgress]), never going back, ending at 1.0 on success.
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

  /// Called by the native side during render and save (ExportChannel.kt).
  static const String _renderProgressMethod = 'progress';
  static const String _saveProgressMethod = 'saveProgress';

  /// errno for "No space left on device" on Linux/Android.
  static const int _enospc = 28;

  /// Prefix of each export's work folder in the cache.
  static const String _workPrefix = 'export_';

  @override
  Future<String?> pickFolder() async {
    final tree = await _call(() => _channel.invokeMethod<String>('pickFolder'));
    if (tree != null && !isLocalFolder(tree)) {
      debugPrint('Export: refused a folder that is not on this phone');
      throw const NotLocalFolder();
    }
    return tree;
  }

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
    final remote = job.inputs.where((i) => _isRemote(i.track)).length;
    final progress = ExportProgress(onProgress, downloads: remote > 0);
    var finished = false;
    Directory? dir;
    // Everything from here is inside the try (L7), so the finally always
    // removes the handler and whatever work folder was made.
    try {
      unawaited(
        token.whenCancelled.then((_) async {
          if (finished) return;
          downloads.cancel();
          await _sendCancel();
        }),
      );
      _channel.setMethodCallHandler((call) async {
        switch (call.method) {
          case _renderProgressMethod:
            progress.report(ExportPhase.render, call.arguments);
          case _saveProgressMethod:
            progress.report(ExportPhase.save, call.arguments);
        }
      });
      progress.report(ExportPhase.download, 0);
      final base = await _workDir();
      await _clearStaleWork(base);
      final work = dir = await base.createTemp(_workPrefix);
      final inputs = <Map<String, Object>>[];
      var downloaded = 0;
      for (final (index, input) in job.inputs.indexed) {
        final before = downloaded;
        inputs.add({
          'path': await _localPath(
            input.track,
            work,
            index,
            downloads,
            token,
            // Each remote track is an equal share of the download phase;
            // a server that sends no length moves it only per track.
            onReceive: (received, total) {
              if (total <= 0) return;
              progress.report(
                ExportPhase.download,
                (before + received / total) / remote,
              );
            },
          ),
          'gain': input.gain,
        });
        if (_isRemote(input.track)) {
          downloaded++;
          progress.report(ExportPhase.download, downloaded / remote);
        }
      }
      final out = '${work.path}${Platform.pathSeparator}export.mp3';
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
      progress.finish();
      return ExportResult(fileName: fileName, location: location);
    } on ExportFailure catch (e) {
      // L9: once the user has cancelled, whatever a stopped step fails
      // with (a closed stream, a dropped download) is their Cancel, not
      // an error to retry.
      if (token.isCancelled && e is! Cancelled) throw const Cancelled();
      rethrow;
    } finally {
      finished = true;
      _channel.setMethodCallHandler(null);
      try {
        await dir?.delete(recursive: true);
      } on FileSystemException catch (e) {
        // The OS clears the cache eventually; not worth failing a saved
        // export over.
        debugPrint('Export: temp files not removed: $e');
      }
    }
  }

  static bool _isRemote(Uri track) =>
      track.scheme == 'https' || track.scheme == 'http';

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
    ExportCancelToken token, {
    required ProgressCallback onReceive,
  }) async {
    if (track.scheme == 'file') return track.toFilePath();
    if (!_isRemote(track)) {
      debugPrint('Export: unsupported track scheme ${track.scheme}');
      throw const GenerationFailed();
    }
    final path = '${dir.path}${Platform.pathSeparator}track_$index';
    try {
      await _dio.downloadUri(
        track,
        path,
        cancelToken: downloads,
        onReceiveProgress: onReceive,
      );
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
        'cancelled_partial' => const Cancelled(partialFileLeft: true),
        'no_folder_picker' => const NoFolderPicker(),
        'not_local_folder' => const NotLocalFolder(),
        _ => const GenerationFailed(),
      };
    } on MissingPluginException catch (e) {
      debugPrint('Export: channel unavailable: $e');
      throw const GenerationFailed();
    }
  }
}

/// The parts of an export, in the order they run.
enum ExportPhase { download, render, save }

/// The whole export's progress as the sheet shows it (user decision
/// 2026-10-21: determinate from download to save). Each phase reports its
/// own 0..1, which lands in that phase's share of the bar. The result is
/// clamped to 0..1 and never moves back, whatever order or values the
/// channel delivers; [finish] makes it exactly 1.0.
class ExportProgress {
  /// [downloads] false when every track is already on the phone: the
  /// download phase then takes no share of the bar.
  ExportProgress(this._onProgress, {bool downloads = true})
    : _weights = {
        ExportPhase.download: downloads ? downloadShare : 0,
        ExportPhase.render: renderShare,
        ExportPhase.save: saveShare,
      };

  // Rough shares of a typical export's time on a mid-range phone: the
  // render (decode, two mixer passes, encode) is most of it.
  static const double downloadShare = 0.2;
  static const double renderShare = 0.7;
  static const double saveShare = 0.1;

  final ValueChanged<double>? _onProgress;
  final Map<ExportPhase, double> _weights;
  double _last = 0;
  bool _started = false;

  double get value => _last;

  void report(ExportPhase phase, Object? raw) {
    if (raw is! num || raw.isNaN) {
      debugPrint('Export: ignored progress value $raw');
      return;
    }
    final total = _weights.values.fold(0.0, (a, b) => a + b);
    var start = 0.0;
    for (final earlier in ExportPhase.values.takeWhile((p) => p != phase)) {
      start += _weights[earlier]!;
    }
    final within = raw.toDouble().clamp(0.0, 1.0);
    _emit((start + _weights[phase]! * within) / total);
  }

  /// The file is saved.
  void finish() => _emit(1);

  void _emit(double raw) {
    final next = raw.clamp(0.0, 1.0);
    if (_started && next <= _last) return;
    _started = true;
    _last = next;
    _onProgress?.call(next);
  }
}
