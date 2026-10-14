import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/processing_status.dart';
import 'processing_providers.dart';

/// Keeps the tracker's jobs and bell items on the device (PIYA-218 AC8),
/// so processing cards, bell rows and a running retake's block on its old
/// score (`retakeOfScoreId`, PIYA-207 AC12) survive an app restart.
///
/// SharedPreferences rather than secure storage: nothing here is a secret
/// (job ids are useless without the session token), and the session end
/// clears it with the rest of the tracker. Every call swallows and logs
/// storage errors: a phone that can't save this must still run scans,
/// it just forgets them on restart.
class ScanJobStore {
  const ScanJobStore();

  @visibleForTesting
  static const String storageKey = 'scan_jobs_v1';

  Future<List<TrackedJob>> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(storageKey);
      return raw == null ? const [] : decodeJobs(raw);
    } on Object catch (e) {
      debugPrint('Scan jobs not restored: $e');
      return const [];
    }
  }

  Future<void> save(String encoded) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(storageKey, encoded);
    } on Object catch (e) {
      debugPrint('Scan jobs not saved: $e');
    }
  }

  Future<void> clear() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(storageKey);
    } on Object catch (e) {
      debugPrint('Scan jobs not cleared: $e');
    }
  }

  /// Phases worth restoring. A cancelled or vanished job has no card and no
  /// bell row, and an expired session is cleared on the way to Login.
  static bool isStored(TrackedPhase phase) =>
      phase != TrackedPhase.cancelled &&
      phase != TrackedPhase.notFound &&
      phase != TrackedPhase.sessionExpired;

  static String encodeJobs(Iterable<TrackedJob> jobs) => jsonEncode([
    for (final job in jobs)
      if (isStored(job.phase)) _encodeJob(job),
  ]);

  /// Drops any entry it can't read rather than failing the whole restore.
  static List<TrackedJob> decodeJobs(String raw) {
    final Object? list;
    try {
      list = jsonDecode(raw);
    } on FormatException catch (e) {
      debugPrint('Stored scan jobs unreadable: $e');
      return const [];
    }
    if (list is! List) return const [];
    return [
      for (final entry in list)
        if (entry is Map<String, dynamic>) ?_decodeJob(entry),
    ];
  }

  static Map<String, Object?> _encodeJob(TrackedJob job) => {
    'jobId': job.jobId,
    'title': job.title,
    'scoreId': job.scoreId,
    'retakeOfScoreId': job.retakeOfScoreId,
    'phase': job.phase.name,
    'percent': job.percent,
    'createdAt': job.createdAt?.toUtc().toIso8601String(),
    'finishedAt': job.finishedAt?.toUtc().toIso8601String(),
    'read': job.read,
    'dismissed': job.dismissed,
    if (job.status case final status?) 'status': _encodeStatus(status),
  };

  /// The PIYA-102 fields the card, the bell and the failure view read, in
  /// PIYA-102's own shape so [ProcessingStatus.fromJson] reads them back.
  static Map<String, Object?> _encodeStatus(ProcessingStatus status) => {
    'status': status.stage.apiValue,
    'currentPage': status.currentPage,
    'totalPages': status.totalPages,
    'percentComplete': status.percentComplete,
    'failureReason': status.failureReason?.apiValue,
    'pageIndex': status.failedPageIndex,
    'scoreId': status.scoreId,
    'failedVoices': [for (final voice in status.failedVoices) voice.name],
    'failedVoiceCauses': {
      for (final entry in status.failedVoiceCauses.entries)
        entry.key.name: entry.value.apiValue,
    },
  };

  static TrackedJob? _decodeJob(Map<String, dynamic> json) {
    final jobId = json['jobId'];
    final phaseName = json['phase'];
    if (jobId is! String || jobId.isEmpty || phaseName is! String) return null;
    final phase = TrackedPhase.values
        .where((p) => p.name == phaseName)
        .firstOrNull;
    if (phase == null || !isStored(phase)) return null;
    final rawStatus = json['status'];
    ProcessingStatus? status;
    if (rawStatus is Map<String, dynamic>) {
      try {
        status = ProcessingStatus.fromJson(rawStatus);
      } on FormatException {
        status = null;
      }
    }
    final percent = json['percent'];
    final title = json['title'];
    return TrackedJob(
      jobId: jobId,
      title: title is String ? title : null,
      scoreId: _id(json['scoreId']),
      retakeOfScoreId: _id(json['retakeOfScoreId']),
      // A job that was waiting for connectivity or a Retry is followed
      // again from scratch; the restore re-polls it at once.
      phase: phase.isFinal ? phase : TrackedPhase.active,
      status: status,
      percent: percent is int ? percent.clamp(0, 100) : 0,
      createdAt: _time(json['createdAt']),
      finishedAt: _time(json['finishedAt']),
      read: json['read'] == true,
      dismissed: json['dismissed'] == true,
    );
  }

  static int? _id(Object? value) => value is int && value > 0 ? value : null;

  static DateTime? _time(Object? value) =>
      value is String ? DateTime.tryParse(value) : null;
}
