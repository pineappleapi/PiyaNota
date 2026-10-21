import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../models/export_selection.dart';

/// One track in the export mix: a voice (or the click) and the gain the
/// Voice Mixer plays it at.
typedef ExportInput = ({Uri track, double gain});

/// The words of the export's system notifications (user decision
/// 2026-10-22), built from the same strings the bell and the banner use
/// (ExportMessages.notice) so they never disagree. The device fills in the
/// percent, the file and the folder.
@immutable
class ExportNoticeText {
  const ExportNoticeText({
    required this.exporting,
    required this.cancel,
    required this.saved,
    required this.failedTitle,
    required this.failures,
    required this.fallbackFailure,
  });

  /// Where [saved] names the file and the folder.
  static const String fileSlot = '{file}';
  static const String folderSlot = '{folder}';

  /// Used only if a caller passes none; the sheet always does.
  static const ExportNoticeText plain = ExportNoticeText(
    exporting: 'Exporting audio…',
    cancel: 'Cancel',
    saved: 'Saved $fileSlot to $folderSlot',
    failedTitle: 'The audio wasn’t exported',
    failures: {},
    fallbackFailure: 'Open Export Audio to try again.',
  );

  /// "Exporting <title>…"; the device adds " n%".
  final String exporting;
  final String cancel;

  /// "Saved [fileSlot] to [folderSlot]".
  final String saved;

  /// "<title> wasn't exported".
  final String failedTitle;

  /// What to do next, by the channel's error code.
  final Map<String, String> failures;
  final String fallbackFailure;

  Map<String, Object> toMap() => {
    'exporting': exporting,
    'cancel': cancel,
    'saved': saved,
    'failedTitle': failedTitle,
    'failures': failures,
    'fallbackFailure': fallbackFailure,
  };
}

/// Everything the device needs to make the export file (PIYA-211).
@immutable
class ExportJob {
  const ExportJob({
    required this.inputs,
    required this.speed,
    required this.fileName,
    this.prepare,
    this.notice = ExportNoticeText.plain,
  });

  final List<ExportInput> inputs;

  /// Makes one more input before the downloads (the click track, L4), so
  /// writing it is part of the export's progress, notification and Cancel
  /// rather than a silent wait before 0%. Its input goes after [inputs].
  final Future<ExportInput> Function()? prepare;

  /// Playback rate, chosen BPM / the score's tempo; pitch is kept (FR-9).
  final double speed;

  /// Before the clash check (AC15); the saved name may gain " (n)".
  final String fileName;

  final ExportNoticeText notice;
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

/// An export started before the app was closed is still being made on the
/// phone (it keeps going in the background, user decision 2026-10-22), so
/// this run of the app does not know of it and cannot start another until
/// it ends.
final class StillExporting extends ExportFailure {
  const StillExporting();
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

/// Folder providers that keep files on this phone or a drive attached to
/// it (user decisions 2026-10-21 and 2026-10-22). The same list and the
/// same exact check as `LocalFolders.kt`, which refuses the rest before any
/// permission is kept; checked here too in case a picker ignores
/// EXTRA_LOCAL_ONLY and the native check is ever bypassed.
///  - externalstorage: internal storage, SD cards and USB-OTG drives. A
///    local folder a sync app happens to watch is allowed too: the file is
///    written to the phone, and the sync app copies it on its own.
///  - downloads: only the phone's own Download folder, no cloud backing.
const Set<String> localFolderAuthorities = {
  'com.android.externalstorage.documents',
  'com.android.providers.downloads.documents',
};

/// [treeUri] is a folder on this phone: a content Uri whose authority is
/// exactly one of [localFolderAuthorities], case and all, with no user
/// info or port, as Android (and `LocalFolders.isLocal`) match it. Not
/// [Uri.host], which is lower-cased and drops those parts.
bool isLocalFolder(String treeUri) {
  const prefix = 'content://';
  if (!treeUri.startsWith(prefix)) return false;
  final rest = treeUri.substring(prefix.length);
  final end = rest.indexOf(RegExp('[/?#]'));
  final authority = end < 0 ? rest : rest.substring(0, end);
  return localFolderAuthorities.contains(authority);
}

abstract interface class ExportService {
  /// The folder the user picked (AC10), or null if they cancelled (AC11).
  /// Throws [NotLocalFolder] for a folder that is not on this phone. Every
  /// folder permission kept from earlier picks is given back, except the
  /// new folder's and those in [keep] (folders an export row or Retry
  /// still uses; user decision 2026-10-22).
  Future<String?> pickFolder({Set<String> keep = const {}});

  /// Makes the MP3 and saves it in [treeUri]. Throws [ExportFailure];
  /// [Cancelled] once [cancel] is cancelled, unless the file was already
  /// saved by then (it is then reported as saved, because it is).
  /// [onProgress] gets the whole export's 0..1 (prepare, download, render,
  /// save; see [ExportProgress]), never going back, ending at 1.0 on
  /// success. The export carries on if the user leaves the app, under a
  /// notification showing the same progress (user decision 2026-10-22).
  Future<ExportResult> export(
    ExportJob job,
    String treeUri, {
    ExportCancelToken? cancel,
    ValueChanged<double>? onProgress,
  });

  /// Opens [treeUri] in a file manager; false when none can (AC16).
  Future<bool> openFolder(String treeUri);

  /// Logout (H1): stops any export, also one this run of the app no longer
  /// knows of, and removes its notifications without a word. Never throws.
  Future<void> stopAll();
}

/// The Android side is `export/ExportChannel.kt`, which hands the render
/// and save to `ExportWorker.kt` under a foreground service.
class MethodChannelExportService implements ExportService {
  MethodChannelExportService({required this._dio, required this._workDir});

  static const MethodChannel _channel = MethodChannel('piyanota/export');

  final Dio _dio;
  final Future<Directory> Function() _workDir;

  /// Called by the native side during render and save (ExportChannel.kt).
  static const String _renderProgressMethod = 'progress';
  static const String _saveProgressMethod = 'saveProgress';

  /// The notification's Cancel was pressed.
  static const String _cancelRequestedMethod = 'cancelRequested';

  /// errno for "No space left on device" on Linux/Android.
  static const int _enospc = 28;

  /// Prefix of each export's work folder in the cache.
  static const String _workPrefix = 'export_';

  @override
  Future<String?> pickFolder({Set<String> keep = const {}}) async {
    final tree = await _call(
      () =>
          _channel.invokeMethod<String>('pickFolder', {'keep': keep.toList()}),
    );
    if (tree != null && !isLocalFolder(tree)) {
      debugPrint('Export: refused a folder that is not on this phone');
      // The native side kept its permission; nothing will use it.
      await _quietly('releaseFolder', {'treeUri': tree});
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
  Future<void> stopAll() => _quietly('stopAll');

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
    // Up to the hand-over the notification's bar is fed from here; after
    // it the device feeds it from the render and save themselves.
    var handedOff = false;
    var notified = -1;
    final progress = ExportProgress(
      (value) {
        onProgress?.call(value);
        final percent = (value * 100).floor();
        if (!handedOff && percent > notified) {
          notified = percent;
          unawaited(_quietly('notifyProgress', {'fraction': value}));
        }
      },
      downloads: remote > 0,
      prepare: job.prepare != null,
    );
    var finished = false;
    var begun = false;
    Object? failure;
    Directory? dir;
    // Everything from here is inside the try (L7), so the finally always
    // removes the handler, ends the notification and the work folder.
    try {
      unawaited(
        token.whenCancelled.then((_) async {
          if (finished) return;
          downloads.cancel();
          await _quietly('cancel');
        }),
      );
      _channel.setMethodCallHandler((call) async {
        switch (call.method) {
          case _renderProgressMethod:
            progress.report(ExportPhase.render, call.arguments);
          case _saveProgressMethod:
            progress.report(ExportPhase.save, call.arguments);
          case _cancelRequestedMethod:
            token.cancel();
        }
      });
      await _call(
        () => _channel.invokeMethod<void>('begin', {
          'notice': job.notice.toMap(),
        }),
      );
      begun = true;
      // The bar is determinate from the start: 0% now, not when the first
      // phase first reports.
      progress.report(ExportPhase.download, 0);
      final base = await _workDir();
      // After begin, which refuses while an earlier export's work folder
      // may still be in use on the device.
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
      if (job.prepare case final prepare?) {
        token.throwIfCancelled();
        progress.report(ExportPhase.prepare, 0);
        final ExportInput extra;
        try {
          extra = await prepare();
        } on ExportFailure {
          rethrow;
        } on Object catch (e, stack) {
          debugPrint('Export: extra track not made: $e\n$stack');
          throw const GenerationFailed();
        }
        inputs.add({
          'path': await _localPath(
            await _intoWork(extra.track, work),
            work,
            job.inputs.length,
            downloads,
            token,
            onReceive: (_, _) {},
          ),
          'gain': extra.gain,
        });
        progress.report(ExportPhase.prepare, 1);
      }
      token.throwIfCancelled();
      // Before the render, so the device can save on its own once it has
      // the file. A file appearing meanwhile is renamed by the folder.
      final names = await _call(
        () => _channel.invokeListMethod<String>('listNames', {
          'treeUri': treeUri,
        }),
      );
      token.throwIfCancelled();
      final out = '${work.path}${Platform.pathSeparator}export.mp3';
      handedOff = true;
      final saved = await _call(
        () => _channel.invokeMapMethod<String, String>('run', {
          'inputs': inputs,
          'speed': job.speed,
          'outPath': out,
          'workDir': work.path,
          'treeUri': treeUri,
          'fileName': uniqueFileName(job.fileName, {...?names}),
          'from': progress.startOf(ExportPhase.render),
          'renderShare': progress.shareOf(ExportPhase.render),
          'saveShare': progress.shareOf(ExportPhase.save),
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
      failure = token.isCancelled && e is! Cancelled ? const Cancelled() : e;
      throw failure;
    } on Object catch (e) {
      failure = e;
      rethrow;
    } finally {
      finished = true;
      _channel.setMethodCallHandler(null);
      // Before the hand-over the device waits for this side to say how
      // it ended; after it, the device ends the notification itself.
      if (begun && !handedOff) {
        await _quietly('end', switch (failure) {
          Cancelled() => {'outcome': 'cancelled'},
          final ExportFailure f => {'outcome': 'failed', 'code': _codeOf(f)},
          _ => {'outcome': 'failed', 'code': 'generation_failed'},
        });
      }
      try {
        await dir?.delete(recursive: true);
      } on FileSystemException catch (e) {
        // The OS clears the cache eventually; not worth failing a saved
        // export over. The device deletes it too once it is done.
        debugPrint('Export: temp files not removed: $e');
      }
    }
  }

  /// Moves a file the export made for itself (the click) into its work
  /// folder, so every clean-up of that folder takes it too: this run's,
  /// the device's after the render, and [_clearStaleWork] after a killed
  /// run. A file that cannot be moved is used where it is.
  static Future<Uri> _intoWork(Uri track, Directory work) async {
    if (track.scheme != 'file') return track;
    final file = File.fromUri(track);
    final name = file.uri.pathSegments.last;
    try {
      final moved = await file.rename(
        '${work.path}${Platform.pathSeparator}$name',
      );
      return moved.uri;
    } on FileSystemException catch (e) {
      debugPrint('Export: extra track left in place: $e');
      return track;
    }
  }

  static bool _isRemote(Uri track) =>
      track.scheme == 'https' || track.scheme == 'http';

  /// Removes work folders an earlier export left when the app was killed
  /// mid-export (the finally below never ran). Only one export runs at a
  /// time (`begin` refuses a second), so none of these is in use.
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

  /// A call whose failure changes nothing for the user.
  static Future<void> _quietly(
    String method, [
    Map<String, Object?>? arguments,
  ]) async {
    try {
      await _channel.invokeMethod<void>(method, arguments);
    } on PlatformException catch (e) {
      debugPrint('Export: $method failed: ${e.code} ${e.message}');
    } on MissingPluginException catch (e) {
      debugPrint('Export: $method unavailable: $e');
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

  /// The channel's error code for [failure], for the notification's words.
  static String _codeOf(ExportFailure failure) => switch (failure) {
    StorageFull() => 'storage_full',
    PermissionDenied() => 'permission_denied',
    GenerationFailed() => 'generation_failed',
    Interrupted() => 'interrupted',
    Cancelled(:final partialFileLeft) =>
      partialFileLeft ? 'cancelled_partial' : 'cancelled',
    NotLocalFolder() => 'not_local_folder',
    NoFolderPicker() => 'no_folder_picker',
    StillExporting() => 'busy',
  };

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
        'busy' => const StillExporting(),
        _ => const GenerationFailed(),
      };
    } on MissingPluginException catch (e) {
      debugPrint('Export: channel unavailable: $e');
      throw const GenerationFailed();
    }
  }
}

/// The parts of an export, in the order they run.
enum ExportPhase { download, prepare, render, save }

/// The whole export's progress as the sheet shows it (user decision
/// 2026-10-21: determinate from download to save). Each phase reports its
/// own 0..1, which lands in that phase's share of the bar. The result is
/// clamped to 0..1 and never moves back, whatever order or values the
/// channel delivers; [finish] makes it exactly 1.0.
class ExportProgress {
  /// [downloads] false when every track is already on the phone, and
  /// [prepare] false when there is no click to write: those phases then
  /// take no share of the bar.
  ExportProgress(
    this._onProgress, {
    bool downloads = true,
    bool prepare = false,
  }) : _weights = {
         ExportPhase.download: downloads ? downloadShare : 0,
         ExportPhase.prepare: prepare ? prepareShare : 0,
         ExportPhase.render: renderShare,
         ExportPhase.save: saveShare,
       };

  // Rough shares of a typical export's time on a mid-range phone: the
  // render (decode, two mixer passes, encode) is most of it, and writing
  // the click a few seconds at most.
  static const double downloadShare = 0.2;
  static const double prepareShare = 0.05;
  static const double renderShare = 0.7;
  static const double saveShare = 0.1;

  final ValueChanged<double>? _onProgress;
  final Map<ExportPhase, double> _weights;
  double _last = 0;
  bool _started = false;

  double get value => _last;

  double get _total => _weights.values.fold(0.0, (a, b) => a + b);

  /// Where [phase] starts on the 0..1 bar.
  double startOf(ExportPhase phase) {
    var start = 0.0;
    for (final earlier in ExportPhase.values.takeWhile((p) => p != phase)) {
      start += _weights[earlier]!;
    }
    return start / _total;
  }

  /// How much of the 0..1 bar [phase] fills.
  double shareOf(ExportPhase phase) => _weights[phase]! / _total;

  void report(ExportPhase phase, Object? raw) {
    if (raw is! num || raw.isNaN) {
      debugPrint('Export: ignored progress value $raw');
      return;
    }
    final within = raw.toDouble().clamp(0.0, 1.0);
    _emit(startOf(phase) + shareOf(phase) * within);
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
