import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/export_service.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/export_jobs.dart';
import 'package:piyanota_application/state/export_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/session_actions.dart';

import '../auth/auth_test_harness.dart';
import '../export/export_fakes.dart';
import '../processing/processing_fakes.dart';

/// H1: logging out, or logging in as someone, stops and forgets the last
/// account's exports, also on the device (service and notifications), and
/// takes the scans' background service and notifications away (PIYA-218).
void main() {
  late FakeExportService exports;
  late FakeScanTrackingService scans;
  late WidgetRef ref;
  late ProviderContainer container;

  Future<void> pump(WidgetTester tester) async {
    exports = FakeExportService();
    scans = FakeScanTrackingService();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          exportServiceProvider.overrideWithValue(exports),
          sessionStorageProvider.overrideWithValue(
            SessionStorage(FaultySecureStorage({})),
          ),
          scanJobStoreProvider.overrideWithValue(MemoryScanJobStore()),
          processingApiProvider.overrideWithValue(ScriptedProcessingApi([])),
          scanTrackingServiceProvider.overrideWithValue(scans),
        ],
        child: MaterialApp(
          home: Consumer(
            builder: (context, r, _) {
              ref = r;
              container = ProviderScope.containerOf(context);
              return const SizedBox();
            },
          ),
        ),
      ),
    );
  }

  /// A finished export in the history.
  void seed() => container
      .read(exportJobsProvider.notifier)
      .start(
        scoreId: 1,
        title: 'A',
        treeUri: kTreeUri,
        run: (_, _) async => kSaved,
      );

  for (final (name, act) in <(String, Future<void> Function())>[
    ('endLocalSession', () => endLocalSession(ref)),
    ('startSession', () => startSession(ref, testSession())),
  ]) {
    testWidgets('$name cancels the running export, forgets the history '
        'and stops the device side', (tester) async {
      await pump(tester);
      seed();
      await tester.pump();
      ExportCancelToken? token;
      final running = Completer<ExportResult>();
      container
          .read(exportJobsProvider.notifier)
          .start(
            scoreId: 2,
            title: 'B',
            treeUri: kTreeUri,
            run: (cancel, _) {
              token = cancel;
              return running.future;
            },
          );
      expect(container.read(exportJobsProvider), hasLength(2));

      await act();
      await tester.pump();

      expect(token!.isCancelled, isTrue);
      expect(container.read(exportJobsProvider), isEmpty);
      expect(exports.stopAllCalls, 1);
      // PIYA-218: the scans' background service and notifications too.
      expect(scans.stopAllCalls, 1);

      // The cancelled export ending late adds nothing back.
      running.completeError(const Cancelled());
      await tester.pump();
      expect(container.read(exportJobsProvider), isEmpty);
    });
  }
}
