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
import 'package:piyanota_application/state/work_owner.dart';

import '../auth/auth_test_harness.dart';
import '../export/export_fakes.dart';
import '../processing/processing_fakes.dart';

/// H1: logging out, or another account logging in, stops and forgets the
/// last account's exports, also on the device (service and notifications),
/// and takes the scans' background service and notifications away
/// (PIYA-218). The same account logging in again (every cold start, no
/// auto-login yet) keeps all of it (review H1).
void main() {
  late FakeExportService exports;
  late FakeScanTrackingService scans;
  late MemoryWorkOwnerStore owners;
  late MemoryScanJobStore scanStore;
  late WidgetRef ref;
  late ProviderContainer container;

  Future<void> pump(WidgetTester tester, {int? owner}) async {
    exports = FakeExportService();
    scans = FakeScanTrackingService();
    owners = MemoryWorkOwnerStore(owner);
    scanStore = MemoryScanJobStore();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          exportServiceProvider.overrideWithValue(exports),
          sessionStorageProvider.overrideWithValue(
            SessionStorage(FaultySecureStorage({})),
          ),
          scanJobStoreProvider.overrideWithValue(scanStore),
          processingApiProvider.overrideWithValue(
            ScriptedProcessingApi([running(10)]),
          ),
          scanTrackingServiceProvider.overrideWithValue(scans),
          workOwnerStoreProvider.overrideWithValue(owners),
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

  /// A running export: its token and the future that ends it.
  (ExportCancelToken? Function(), Completer<ExportResult>) startRunning() {
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
    return (() => token, running);
  }

  final other = testSession().userId + 1;
  for (final (name, owner, act) in <(String, int?, Future<void> Function())>[
    ('endLocalSession', testSession().userId, () => endLocalSession(ref)),
    (
      'startSession as another account',
      other,
      () => startSession(ref, testSession()),
    ),
    (
      'startSession with no known owner',
      null,
      () => startSession(ref, testSession()),
    ),
  ]) {
    testWidgets('$name cancels the running export, forgets the history '
        'and stops the device side', (tester) async {
      await pump(tester, owner: owner);
      seed();
      await tester.pump();
      container.read(processingJobsProvider.notifier).track('scan-1');
      await tester.pump();
      final (token, running) = startRunning();
      expect(container.read(exportJobsProvider), hasLength(2));

      await act();
      await tester.pump();

      expect(token()!.isCancelled, isTrue);
      expect(container.read(exportJobsProvider), isEmpty);
      expect(exports.stopAllCalls, 1);
      // PIYA-218: the scans' background service and notifications too.
      expect(scans.stopAllCalls, 1);
      expect(container.read(processingJobsProvider), isEmpty);
      expect(scanStore.storedJobs, isEmpty);

      // The cancelled export ending late adds nothing back.
      running.completeError(const Cancelled());
      await tester.pump();
      expect(container.read(exportJobsProvider), isEmpty);
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('endLocalSession forgets the owner and signs out', (
    tester,
  ) async {
    await pump(tester, owner: testSession().userId);
    container.read(signedInProvider.notifier).set(true);
    await endLocalSession(ref);
    expect(owners.owner, isNull);
    expect(container.read(signedInProvider), isFalse);
  });

  testWidgets('startSession as the same account keeps the export, the '
      'history and the scans, and records the owner', (tester) async {
    await pump(tester, owner: testSession().userId);
    seed();
    await tester.pump();
    container.read(processingJobsProvider.notifier).track('scan-1');
    await tester.pump();
    final (token, running) = startRunning();

    await startSession(ref, testSession());
    await tester.pump();

    expect(token()!.isCancelled, isFalse);
    expect(container.read(exportJobsProvider), hasLength(2));
    expect(exports.stopAllCalls, 0);
    expect(scans.stopAllCalls, 0);
    expect(container.read(processingJobsProvider), contains('scan-1'));
    expect(scanStore.storedJobs.map((j) => j.jobId), contains('scan-1'));
    expect(owners.owner, testSession().userId);
    expect(container.read(signedInProvider), isTrue);

    running.complete(kSaved);
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('startSession as another account records the new owner', (
    tester,
  ) async {
    await pump(tester, owner: other);
    await startSession(ref, testSession());
    expect(owners.owner, testSession().userId);
    expect(container.read(signedInProvider), isTrue);
  });
}
