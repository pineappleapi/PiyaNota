import 'package:dio/dio.dart' show RequestOptions, Response;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/screens/capture/capture_messages.dart';
import 'package:piyanota_application/screens/capture/capture_screen.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/services/fake_score_upload_api.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/state/score_library_providers.dart';

import '../auth/auth_test_harness.dart';
import 'capture_fakes.dart';

const _account = 'singer@example.com';

/// A library holding [count] scores, shared by the app and the fake upload.
class _LimitHarness extends CaptureHarness {
  _LimitHarness(int count) {
    final session = SessionStorage(
      FaultySecureStorage({'session_token': _account}),
    );
    library = FakeScoreLibraryApi(
      sessionStorage: session,
      accountForToken: (token) => token,
      latency: Duration.zero,
    );
    for (var i = library.scoreCount(_account); i < count; i++) {
      library.addSubmittedScore(
        account: _account,
        title: 'Score $i',
        pageCount: 1,
      );
    }
    fake = FakeScoreUploadApi(
      sessionStorage: session,
      accountForToken: (token) => token,
      library: library,
      latency: Duration.zero,
    );
  }

  late final FakeScoreLibraryApi library;
  late final FakeScoreUploadApi fake;

  @override
  List<Override> get overrides => [
    ...super.overrides,
    scoreLibraryApiProvider.overrideWithValue(library),
  ];
}

Future<ProviderContainer> _openWithOnePhoto(
  WidgetTester tester,
  CaptureHarness h, {
  Size size = const Size(400, 800),
  double textScale = 1,
}) async {
  await pumpCapture(tester, h, size: size, textScale: textScale);
  await tester.tap(find.bySemanticsLabel(CaptureMessages.shutter));
  await tester.pumpAndSettle();
  final container = ProviderScope.containerOf(
    tester.element(find.byType(CaptureScreen)),
  );
  // The app keeps the Library alive; stand in for that listener.
  container.listen(scoreLibraryProvider, (_, _) {});
  final loaded = container.read(scoreLibraryProvider.future);
  await tester.pump(const Duration(milliseconds: 10));
  await loaded;
  return container;
}

Future<void> _create(WidgetTester tester) async {
  await tester.ensureVisible(find.text(CaptureMessages.createScoreWith(1)));
  await tester.pumpAndSettle();
  await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
  await tester.pumpAndSettle();
}

void main() {
  test('rejectionFrom reads score_limit_reached and error.limit', () {
    final failure = HttpScoreUploadApi.rejectionFrom(
      Response<dynamic>(
        requestOptions: RequestOptions(),
        statusCode: 409,
        data: {
          'error': {'code': 'score_limit_reached', 'limit': 20},
        },
      ),
    );
    expect(failure, isA<UploadRejectedException>());
    final rejected = failure as UploadRejectedException;
    expect(rejected.isScoreLimit, isTrue);
    expect(rejected.limit, 20);
    expect(rejected.statusCode, 409);
  });

  test('fake backend: 409 at 20, succeeds after one delete', () async {
    final h = _LimitHarness(maxScoresPerUser);
    Future<SubmittedJob> submit() => h.fake.submitImages(
      details: const ScoreDetails(title: 'New'),
      imagePaths: const ['p.jpg'],
    );
    await expectLater(
      submit,
      throwsA(
        isA<UploadRejectedException>()
            .having((e) => e.statusCode, 'status', 409)
            .having((e) => e.code, 'code', scoreLimitReachedCode)
            .having((e) => e.limit, 'limit', maxScoresPerUser),
      ),
    );
    await h.library.deleteScore((await h.library.fetchLibrary()).first.scoreId);
    expect((await submit()).jobId, isNotEmpty);
  });

  group('Capture', () {
    testWidgets('pre-check at 20 shows the dialog and sends nothing', (
      tester,
    ) async {
      final h = _LimitHarness(maxScoresPerUser);
      await _openWithOnePhoto(tester, h);
      await _create(tester);
      expect(find.text(CaptureMessages.scoreLimitBody), findsOneWidget);
      expect(h.upload.imageCalls, isEmpty);
      await tester.tap(find.text(CaptureMessages.cancel));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.scoreLimitBody), findsNothing);
      expect(find.byType(CaptureScreen), findsOneWidget);
    });

    testWidgets('Library button leaves for the library', (tester) async {
      final h = _LimitHarness(maxScoresPerUser);
      await _openWithOnePhoto(tester, h);
      await _create(tester);
      await tester.tap(find.text(CaptureMessages.library));
      await tester.pumpAndSettle();
      expect(find.text(kLibraryMarker), findsOneWidget);
    });

    testWidgets('server 409 shows the same dialog, no error banner', (
      tester,
    ) async {
      final h = CaptureHarness();
      h.upload.onSubmit = () async => throw const UploadRejectedException(
        statusCode: 409,
        code: scoreLimitReachedCode,
        limit: maxScoresPerUser,
      );
      await pumpCapture(tester, h);
      await tester.tap(find.bySemanticsLabel(CaptureMessages.shutter));
      await tester.pumpAndSettle();
      await _create(tester);
      expect(h.upload.imageCalls, hasLength(1));
      expect(find.text(CaptureMessages.scoreLimitBody), findsOneWidget);
    });

    testWidgets('upload goes through after deleting one score', (tester) async {
      final h = _LimitHarness(maxScoresPerUser);
      final container = await _openWithOnePhoto(tester, h);
      await _create(tester);
      await tester.tap(find.text(CaptureMessages.cancel));
      await tester.pumpAndSettle();
      expect(h.upload.imageCalls, isEmpty);

      // What the Library does after a confirmed delete.
      container
          .read(scoreLibraryProvider.notifier)
          .removeLocally(
            container.read(scoreLibraryProvider).requireValue.first.scoreId,
          );
      await _create(tester);
      expect(find.text(CaptureMessages.scoreLimitBody), findsNothing);
      expect(h.upload.imageCalls, hasLength(1));
    });

    testWidgets('dialog fits 320 dp at 2.0x text', (tester) async {
      final h = _LimitHarness(maxScoresPerUser);
      await _openWithOnePhoto(
        tester,
        h,
        size: const Size(320, 568),
        textScale: 2,
      );
      await _create(tester);
      expect(find.text(CaptureMessages.scoreLimitBody), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
