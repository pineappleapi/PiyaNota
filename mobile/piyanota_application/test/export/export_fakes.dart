import 'dart:async';

import 'package:piyanota_application/services/export_service.dart';

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

  int pickCalls = 0;
  final List<(ExportJob, String)> exports = [];
  final List<String> opened = [];

  @override
  Future<String?> pickFolder() async {
    pickCalls++;
    if (pickFailure case final failure?) throw failure;
    return folder;
  }

  @override
  Future<ExportResult> export(ExportJob job, String treeUri) async {
    exports.add((job, treeUri));
    if (exportGate case final gate?) await gate.future;
    if (_failures.isNotEmpty) throw _failures.removeAt(0);
    return kSaved;
  }

  @override
  Future<bool> openFolder(String treeUri) async {
    opened.add(treeUri);
    return canOpen;
  }
}
