import 'dart:async';

import 'package:flutter/foundation.dart';

import 'package:piyanota_application/services/export_service.dart';
import 'package:piyanota_application/services/notification_permission.dart';

const String kTreeUri = 'content://tree/primary%3AMusic';
const ExportResult kSaved = ExportResult(
  fileName: 'Bituin Walang Ningning_Soprano.mp3',
  location: 'Internal storage/Music',
);

/// [ExportService] that records what the sheet asks for. [failures] are
/// thrown by the next exports, in order; [exportGate] holds an export
/// open (to see the busy state) until completed.
class FakeExportService implements ExportService {
  FakeExportService({
    this.folder = kTreeUri,
    List<ExportFailure> failures = const [],
    this.pickFailure,
    this.canOpen = true,
  }) : _failures = [...failures];

  /// What the picker returns; null is a cancel.
  String? folder;
  final ExportFailure? pickFailure;
  final bool canOpen;
  final List<ExportFailure> _failures;
  Completer<void>? exportGate;

  /// Runs while the picker is "open", before it returns: for things that
  /// happen to Playback while the user is choosing a folder.
  Future<void> Function()? onPick;

  /// Thrown by the next picks, in order, before [pickFailure] applies.
  final List<ExportFailure> pickQueue = [];

  int pickCalls = 0;
  final List<(ExportJob, String)> exports = [];
  final List<String> opened = [];

  /// The `keep` each pick was given.
  final List<Set<String>> keeps = [];
  int stopAllCalls = 0;

  @override
  Future<String?> pickFolder({Set<String> keep = const {}}) async {
    pickCalls++;
    keeps.add(keep);
    if (pickQueue.isNotEmpty) throw pickQueue.removeAt(0);
    if (pickFailure case final failure?) throw failure;
    if (onPick case final hook?) await hook();
    return folder;
  }

  /// The last export's Cancel and progress, for tests to drive.
  ExportCancelToken? lastCancel;
  ValueChanged<double>? lastOnProgress;

  @override
  Future<ExportResult> export(
    ExportJob job,
    String treeUri, {
    ExportCancelToken? cancel,
    ValueChanged<double>? onProgress,
  }) async {
    exports.add((job, treeUri));
    lastCancel = cancel;
    lastOnProgress = onProgress;
    if (exportGate case final gate?) {
      // A held export stops on Cancel the way the real one does.
      await Future.any([gate.future, ?cancel?.whenCancelled]);
    }
    cancel?.throwIfCancelled();
    // The real service writes the click inside the export (L4).
    if (job.prepare case final prepare?) prepared.add(await prepare());
    if (_failures.isNotEmpty) throw _failures.removeAt(0);
    return kSaved;
  }

  /// What each export's prepare step made.
  final List<ExportInput> prepared = [];

  @override
  Future<void> stopAll() async => stopAllCalls++;

  @override
  Future<bool> openFolder(String treeUri) async {
    opened.add(treeUri);
    return canOpen;
  }
}

/// [NotificationPermission] for tests: says "ask" once if [askFirst].
class FakeNotificationPermission implements NotificationPermission {
  FakeNotificationPermission({this.askFirst = false});

  bool askFirst;
  int asks = 0;
  int requests = 0;

  @override
  Future<bool> shouldAsk() async => askFirst;

  @override
  Future<void> markAsked() async {
    asks++;
    askFirst = false;
  }

  @override
  Future<void> request() async => requests++;
}
