import 'dart:async';
import 'dart:io' show FileSystemException;

import 'package:flutter/gestures.dart' show kLongPressTimeout;
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/screens/capture/capture_messages.dart';
import 'package:piyanota_application/screens/capture/edit_page_screen.dart';
import 'package:piyanota_application/services/capture/capture_permissions.dart';
import 'package:piyanota_application/services/capture/device_channel.dart';
import 'package:piyanota_application/services/capture/page_picker.dart';
import 'package:piyanota_application/services/score_upload_api.dart';

import 'capture_fakes.dart';

Finder _label(String label) => find.bySemanticsLabel(label);

Future<void> _shoot(WidgetTester tester, [int times = 1]) async {
  for (var i = 0; i < times; i++) {
    await tester.tap(_label(CaptureMessages.shutter));
    await tester.pumpAndSettle();
  }
}

Future<void> _addGallery(WidgetTester tester, CaptureHarness h, int n) async {
  h.picker.gallery = [for (var i = 0; i < n; i++) 'g$i.jpg'];
  await tester.tap(find.text(CaptureMessages.gallery));
  await tester.pumpAndSettle();
}

Future<void> _pickPdf(WidgetTester tester) async {
  await tester.tap(find.text(CaptureMessages.pdf));
  await tester.pumpAndSettle();
}

ElevatedButton _submitButton(WidgetTester tester) =>
    tester.widget<ElevatedButton>(find.byType(ElevatedButton).last);

Future<void> _semanticsAction(
  WidgetTester tester,
  Finder finder,
  String customLabel,
) async {
  final node = tester.getSemantics(finder);
  node.owner!.performAction(
    node.id,
    SemanticsAction.customAction,
    CustomSemanticsAction.getIdentifier(
      CustomSemanticsAction(label: customLabel),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('inputs and camera permission (AC1, AC2)', () {
    testWidgets('three labelled inputs; camera asked once on arrival', (
      tester,
    ) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);

      expect(find.text(CaptureMessages.gallery), findsOneWidget);
      expect(find.text(CaptureMessages.pdf), findsOneWidget);
      expect(_label(CaptureMessages.shutter), findsOneWidget);
      expect(h.permissions.cameraRequests, 1);
      expect(h.camera!.initialized, isTrue);
      expect(find.text(CaptureMessages.noPagesYet), findsOneWidget);
      expect(_submitButton(tester).onPressed, isNull);
    });

    testWidgets('denied: explanation, Allow camera, Open settings', (
      tester,
    ) async {
      final h = CaptureHarness(
        permissions: FakeCapturePermissions(camera: PermissionOutcome.denied),
      );
      await pumpCapture(tester, h);

      expect(find.text(CaptureMessages.cameraNeededTitle), findsOneWidget);
      expect(find.text(CaptureMessages.allowCamera), findsOneWidget);
      expect(h.cameras, isEmpty);
      expect(
        tester.getSemantics(_label(CaptureMessages.shutter)),
        isSemantics(isEnabled: false, hasEnabledState: true),
      );

      await tester.tap(find.text(CaptureMessages.openSettings));
      await tester.pump();
      expect(h.permissions.settingsOpened, 1);

      // Gallery still works without the camera.
      await _addGallery(tester, h, 1);
      expect(find.text(CaptureMessages.pageOf(1, 1)), findsOneWidget);
    });

    testWidgets('Allow camera asks again and starts it when granted', (
      tester,
    ) async {
      final h = CaptureHarness(
        permissions: FakeCapturePermissions(camera: PermissionOutcome.denied),
      );
      await pumpCapture(tester, h);
      h.permissions.camera = PermissionOutcome.granted;
      await tester.tap(find.text(CaptureMessages.allowCamera));
      await tester.pumpAndSettle();
      expect(h.permissions.cameraRequests, 2);
      expect(h.camera!.initialized, isTrue);
      expect(find.text(CaptureMessages.cameraNeededTitle), findsNothing);
    });

    testWidgets('blocked: only Open settings is offered', (tester) async {
      final h = CaptureHarness(
        permissions: FakeCapturePermissions(camera: PermissionOutcome.blocked),
      );
      await pumpCapture(tester, h);
      expect(find.text(CaptureMessages.cameraNeededTitle), findsOneWidget);
      expect(find.text(CaptureMessages.allowCamera), findsNothing);
      expect(find.text(CaptureMessages.openSettings), findsOneWidget);
    });

    testWidgets('a grant made in Settings is picked up on resume', (
      tester,
    ) async {
      final h = CaptureHarness(
        permissions: FakeCapturePermissions(camera: PermissionOutcome.blocked),
      );
      await pumpCapture(tester, h);
      h.permissions.grantedOnResume = true;
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(h.permissions.cameraRequests, 1, reason: 'no second prompt');
      expect(h.camera!.initialized, isTrue);
    });

    testWidgets('backgrounding releases the camera; resume reopens it', (
      tester,
    ) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      final first = h.camera!;
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      expect(first.disposed, isTrue);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(h.cameras, hasLength(2));
      expect(h.camera!.initialized, isTrue);
    });

    testWidgets('no camera on the device says so', (tester) async {
      final h = CaptureHarness()..cameraFailsInit = true;
      await pumpCapture(tester, h);
      expect(find.text(CaptureMessages.noCamera), findsOneWidget);
      expect(h.camera!.disposed, isTrue);
    });
  });

  group('gallery permission and file checks (AC3, AC6, AC7)', () {
    testWidgets('denied photos explain and link to Settings', (tester) async {
      final h = CaptureHarness(
        permissions: FakeCapturePermissions(gallery: PermissionOutcome.denied),
      );
      await pumpCapture(tester, h);
      await tester.tap(find.text(CaptureMessages.gallery));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.photosNeededTitle), findsOneWidget);
      await tester.tap(find.text(CaptureMessages.openSettings).last);
      await tester.pumpAndSettle();
      expect(h.permissions.settingsOpened, 1);
      expect(find.text(CaptureMessages.noPagesYet), findsOneWidget);
    });

    testWidgets('unreadable photos are left out and counted', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      h.picker.gallery = ['ok.jpg', 'bad.heic', 'bad.txt'];
      await tester.tap(find.text(CaptureMessages.gallery));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.unreadablePhotos(2)), findsOneWidget);
      expect(find.text(CaptureMessages.pageOf(1, 1)), findsOneWidget);
    });

    testWidgets('more than 20 photos: the first 20 are kept', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _addGallery(tester, h, 23);
      expect(find.text(CaptureMessages.tooManyPhotos(20, 23)), findsOneWidget);
      expect(find.text(CaptureMessages.createScoreWith(20)), findsOneWidget);
      // Full: the shutter refuses instead of adding a 21st page.
      await _shoot(tester);
      expect(find.text(CaptureMessages.scoreFull), findsOneWidget);
      expect(h.camera!.shots, 0);
    });

    testWidgets('a 21-page PDF is rejected before upload', (tester) async {
      final h = CaptureHarness(device: FakeDeviceChannel(pages: 21));
      await pumpCapture(tester, h);
      h.picker.pdf = const PickedPdf(path: 'long.pdf', name: 'long.pdf');
      await _pickPdf(tester);
      expect(find.text(CaptureMessages.pdfTooLong(21)), findsOneWidget);
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.noPagesYet), findsOneWidget);
      expect(_submitButton(tester).onPressed, isNull);
      expect(h.upload.pdfCalls, isEmpty);
    });

    testWidgets('exactly 20 pages is accepted', (tester) async {
      final h = CaptureHarness(device: FakeDeviceChannel(pages: 20));
      await pumpCapture(tester, h);
      h.picker.pdf = const PickedPdf(path: 'ok.pdf', name: 'ok.pdf');
      await _pickPdf(tester);
      expect(find.text(CaptureMessages.pdfCard(20)), findsWidgets);
    });

    testWidgets('a file that is not a PDF is rejected at selection', (
      tester,
    ) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      h.picker.notAPdf = true;
      await _pickPdf(tester);
      expect(find.text(CaptureMessages.notAPdf), findsOneWidget);
    });

    testWidgets('encrypted and empty PDFs get their own wording', (
      tester,
    ) async {
      final h = CaptureHarness(
        device: FakeDeviceChannel(problem: PdfProblem.encrypted),
      );
      await pumpCapture(tester, h);
      h.picker.pdf = const PickedPdf(path: 'x.pdf', name: 'x.pdf');
      await _pickPdf(tester);
      expect(find.text(CaptureMessages.pdfEncrypted), findsOneWidget);
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();

      h.device
        ..problem = null
        ..pages = 0;
      await _pickPdf(tester);
      expect(find.text(CaptureMessages.pdfEmpty), findsOneWidget);
    });

    testWidgets('PDF and photos never mix: replacing asks first', (
      tester,
    ) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _shoot(tester, 2);
      h.picker.pdf = const PickedPdf(path: 'x.pdf', name: 'x.pdf');

      await _pickPdf(tester);
      expect(find.text(CaptureMessages.replacePhotosTitle(2)), findsOneWidget);
      await tester.tap(find.text(CaptureMessages.keep));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.createScoreWith(2)), findsOneWidget);

      await _pickPdf(tester);
      await tester.tap(find.text(CaptureMessages.replace));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.createScoreWith(3)), findsOneWidget);
      expect(_label(CaptureMessages.addPages), findsNothing);

      // A photo now offers to replace the PDF.
      await _shoot(tester);
      expect(find.text(CaptureMessages.replacePdfTitle), findsOneWidget);
    });
  });

  group('strip: reorder, remove, undo, arrows (AC4, AC5)', () {
    testWidgets('Move later reorders and is what gets uploaded', (
      tester,
    ) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _addGallery(tester, h, 3);
      await _semanticsAction(
        tester,
        _label(CaptureMessages.pageSemantics(1, 3)),
        CaptureMessages.moveLater,
      );
      expect(find.text(CaptureMessages.pageOf(2, 3)), findsOneWidget);

      await tester.tap(find.text(CaptureMessages.createScoreWith(3)));
      await tester.pumpAndSettle();
      expect(h.upload.imageCalls.single, [
        'prepared/g1.jpg',
        'prepared/g0.jpg',
        'prepared/g2.jpg',
      ]);
    });

    testWidgets('long-press drag moves a page', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _addGallery(tester, h, 3);
      final first = tester.getCenter(
        _label(CaptureMessages.pageSemantics(1, 3)),
      );
      final gesture = await tester.startGesture(first);
      await tester.pump(kLongPressTimeout + const Duration(milliseconds: 100));
      for (var i = 0; i < 10; i++) {
        await gesture.moveBy(const Offset(22, 0));
        await tester.pump(const Duration(milliseconds: 16));
      }
      await gesture.up();
      await tester.pumpAndSettle();

      await tester.tap(find.text(CaptureMessages.createScoreWith(3)));
      await tester.pumpAndSettle();
      expect(h.upload.imageCalls.single.first, isNot('prepared/g0.jpg'));
    });

    testWidgets('remove keeps the rest; Undo puts it back in place', (
      tester,
    ) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _addGallery(tester, h, 3);

      await tester.tap(_label(CaptureMessages.removePage(2)));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.removed(2)), findsOneWidget);
      expect(find.text(CaptureMessages.createScoreWith(2)), findsOneWidget);

      await tester.tap(find.text(CaptureMessages.undo));
      await tester.pumpAndSettle();
      await tester.tap(find.text(CaptureMessages.createScoreWith(3)));
      await tester.pumpAndSettle();
      expect(h.upload.imageCalls.single, [
        'prepared/g0.jpg',
        'prepared/g1.jpg',
        'prepared/g2.jpg',
      ]);
    });

    testWidgets('Undo of a photo is refused once a PDF took its place', (
      tester,
    ) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _shoot(tester);
      await tester.tap(_label(CaptureMessages.removePage(1)));
      await tester.pumpAndSettle();
      h.picker.pdf = const PickedPdf(path: 'x.pdf', name: 'x.pdf');
      await _pickPdf(tester);
      // The snackbar is still up; its Undo must not mix the photo in.
      final undo = find.text(CaptureMessages.undo);
      if (undo.evaluate().isNotEmpty) {
        await tester.tap(undo);
        await tester.pumpAndSettle();
      }
      expect(find.text(CaptureMessages.createScoreWith(3)), findsOneWidget);
    });

    testWidgets('arrows appear only when the strip overflows', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _addGallery(tester, h, 2);
      expect(find.byTooltip(CaptureMessages.scrollRight), findsNothing);

      await _addGallery(tester, h, 6);
      await tester.pumpAndSettle();
      final left = find.byTooltip(CaptureMessages.scrollLeft);
      final right = find.byTooltip(CaptureMessages.scrollRight);
      double opacity(Finder f) => tester
          .widget<AnimatedOpacity>(
            find.ancestor(of: f, matching: find.byType(AnimatedOpacity)),
          )
          .opacity;

      // The newest page was scrolled into view, so earlier ones are off
      // to the left; the "+" tile is still to the right.
      expect(opacity(left), 1);
      while (opacity(right) > 0) {
        await tester.tap(right);
        await tester.pumpAndSettle();
      }
      expect(_label(CaptureMessages.addPages).hitTestable(), findsOneWidget);
      // Back to the start in viewport-sized steps; the left arrow fades out.
      var taps = 0;
      while (opacity(left) > 0) {
        await tester.tap(left);
        await tester.pumpAndSettle();
        taps++;
      }
      expect(taps, inInclusiveRange(2, 4), reason: 'about a viewport a tap');
      expect(opacity(right), 1);
      expect(
        _label(CaptureMessages.pageSemantics(1, 8)).hitTestable(),
        findsOneWidget,
      );
    });

    testWidgets('tapping the preview focuses there', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await tester.tap(_label(CaptureMessages.cameraPreview));
      await tester.pump();
      final point = h.camera!.focusedAt!;
      expect(point.dx, closeTo(0.5, 0.01));
      expect(point.dy, closeTo(0.5, 0.01));
      await tester.pump(const Duration(seconds: 1)); // focus ring fades
    });

    testWidgets('a PDF shows as one card with no edit button', (tester) async {
      final h = CaptureHarness(device: FakeDeviceChannel(pages: 4));
      await pumpCapture(tester, h);
      h.picker.pdf = const PickedPdf(path: 'x.pdf', name: 'Misa.pdf');
      await _pickPdf(tester);
      expect(_label(CaptureMessages.pdfSemantics('Misa.pdf', 4)), findsOne);
      expect(find.textContaining('Edit page'), findsNothing);
      await tester.tap(_label(CaptureMessages.removePdf));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.pdfRemoved), findsOneWidget);
    });

    testWidgets('edit replaces the page file after Done', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _shoot(tester);
      await tester.tap(_label(CaptureMessages.editPage(1)));
      await tester.pumpAndSettle();
      expect(find.byType(EditPageScreen), findsOneWidget);

      await tester.tap(find.text(CaptureMessages.rotate));
      await tester.pump();
      await tester.tap(find.text(CaptureMessages.done));
      await tester.pumpAndSettle();
      expect(h.processor.edits.single.$2.quarterTurns, 1);

      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      expect(h.upload.imageCalls.single.single, endsWith('+edit1'));
    });

    testWidgets('tapping a thumbnail opens the preview', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _shoot(tester, 2);
      await tester.tap(_label(CaptureMessages.pageSemantics(2, 2)));
      await tester.pumpAndSettle();
      expect(find.byType(InteractiveViewer), findsOneWidget);
      expect(find.text(CaptureMessages.pageOf(2, 2)), findsWidgets);
    });
  });

  group('submit (AC8)', () {
    testWidgets('photos go to PIYA-101 and land on Processing', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _shoot(tester, 2);
      await tester.tap(find.text(CaptureMessages.createScoreWith(2)));
      await tester.pumpAndSettle();

      expect(h.upload.imageCalls, hasLength(1));
      expect(h.upload.pdfCalls, isEmpty);
      expect(h.upload.detailsSent.single.title, 'Ave Maria');
      expect(find.text('ROUTE:processing job-42 Ave Maria'), findsOneWidget);

      // Back from Processing returns to the library, not the sent form.
      tester.state<NavigatorState>(find.byType(Navigator)).pop();
      await tester.pumpAndSettle();
      expect(find.text(kLibraryMarker), findsOneWidget);
    });

    testWidgets('a PDF goes to PIYA-310', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      h.picker.pdf = const PickedPdf(path: 'score.pdf', name: 'score.pdf');
      await _pickPdf(tester);
      await tester.tap(find.text(CaptureMessages.createScoreWith(3)));
      await tester.pumpAndSettle();
      expect(h.upload.pdfCalls, ['score.pdf']);
      expect(h.upload.imageCalls, isEmpty);
    });

    testWidgets('a second tap while sending does nothing', (tester) async {
      final h = CaptureHarness();
      final pending = Completer<SubmittedJob>();
      h.upload.onSubmit = () => pending.future;
      await pumpCapture(tester, h);
      await _shoot(tester);
      final button = find.byType(ElevatedButton).last;
      await tester.tap(button);
      await tester.pump();
      await tester.tap(button, warnIfMissed: false);
      await tester.pump();
      expect(h.upload.imageCalls, hasLength(1));
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(_submitButton(tester).onPressed, isNull);

      // Back is blocked while sending.
      await tester.binding.handlePopRoute();
      await tester.pump();
      expect(find.text(CaptureMessages.discardTitle(1)), findsNothing);

      pending.complete(ScriptedScoreUploadApi.job);
      await tester.pumpAndSettle();
      expect(find.textContaining('ROUTE:processing'), findsOneWidget);
    });

    testWidgets('a network failure shows a banner and keeps the pages', (
      tester,
    ) async {
      final h = CaptureHarness();
      h.upload.onSubmit = () => Future.error(const UploadNetworkException());
      await pumpCapture(tester, h);
      await _shoot(tester);
      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.network), findsOneWidget);
      expect(find.text(CaptureMessages.logIn), findsNothing);

      // Trying again works without re-adding pages.
      h.upload.onSubmit = null;
      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      expect(find.textContaining('ROUTE:processing'), findsOneWidget);
    });

    testWidgets('session expiry offers Log In', (tester) async {
      final h = CaptureHarness();
      h.upload.onSubmit = () =>
          Future.error(const UploadSessionExpiredException());
      await pumpCapture(tester, h);
      await _shoot(tester);
      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.sessionExpired), findsOneWidget);
      await tester.tap(find.text(CaptureMessages.logIn));
      await tester.pumpAndSettle();
      expect(find.text(kLoginMarker), findsOneWidget);
      expect(h.secureStorage.values, isEmpty);
    });
  });

  group('leaving', () {
    testWidgets('Close with no pages leaves straight away', (tester) async {
      await pumpCapture(tester, CaptureHarness());
      await tester.tap(find.byTooltip(CaptureMessages.close));
      await tester.pumpAndSettle();
      expect(find.text(kLibraryMarker), findsOneWidget);
    });

    testWidgets('Close with pages asks before discarding', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _shoot(tester, 2);
      await tester.tap(find.byTooltip(CaptureMessages.close));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.discardTitle(2)), findsOneWidget);
      await tester.tap(find.text(CaptureMessages.keepEditing));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.createScoreWith(2)), findsOneWidget);

      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      await tester.tap(find.text(CaptureMessages.discard));
      await tester.pumpAndSettle();
      expect(find.text(kLibraryMarker), findsOneWidget);
      expect(h.camera!.disposed, isTrue);
    });
  });

  group('review fixes: failures, cancel, details, files', () {
    for (final (name, error) in [
      ('a vanished file', const FileSystemException('gone', 'p.jpg')),
      ('an unforeseen error', StateError('boom')),
    ]) {
      testWidgets('$name gives the screen back with the generic error', (
        tester,
      ) async {
        final h = CaptureHarness();
        h.upload.onSubmit = () => Future.error(error);
        await pumpCapture(tester, h);
        await _shoot(tester);
        await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
        await tester.pumpAndSettle();
        expect(find.text(CaptureMessages.generic), findsOneWidget);
        expect(find.byType(CircularProgressIndicator), findsNothing);
        expect(_submitButton(tester).onPressed, isNotNull);
        expect(find.text(CaptureMessages.cancelUpload), findsNothing);
      });
    }

    testWidgets('a missing page file says which page to retake', (
      tester,
    ) async {
      final h = CaptureHarness();
      const error = UploadFileMissingException(pageIndex: 1);
      h.upload.onSubmit = () => Future.error(error);
      await pumpCapture(tester, h);
      await _shoot(tester, 2);
      await tester.tap(find.text(CaptureMessages.createScoreWith(2)));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.uploadError(error)), findsOneWidget);
      expect(CaptureMessages.uploadError(error), contains('Page 2'));
    });

    testWidgets('Cancel sending stops the upload and keeps the pages', (
      tester,
    ) async {
      final h = CaptureHarness();
      final never = Completer<SubmittedJob>();
      h.upload.onSubmit = () => never.future;
      await pumpCapture(tester, h);
      await _shoot(tester, 2);
      await tester.tap(find.text(CaptureMessages.createScoreWith(2)));
      await tester.pump();
      expect(_submitButton(tester).onPressed, isNull);

      await tester.tap(find.text(CaptureMessages.cancelUpload));
      await tester.pump();
      await tester.pump();
      expect(h.upload.lastCancelToken!.isCancelled, isTrue);
      expect(find.text(CaptureMessages.uploadCancelled), findsOneWidget);
      expect(find.text(CaptureMessages.cancelUpload), findsNothing);
      expect(find.text(CaptureMessages.network), findsNothing);
      expect(_submitButton(tester).onPressed, isNotNull);
      expect(h.files.deleted.where((p) => p.startsWith('prepared/')), isEmpty);
    });

    testWidgets('cancelling the gallery after "Replace" keeps the PDF', (
      tester,
    ) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      h.picker.pdf = const PickedPdf(path: 'x.pdf', name: 'x.pdf');
      await _pickPdf(tester);

      h.picker.gallery = const [];
      await tester.tap(find.text(CaptureMessages.gallery));
      await tester.pumpAndSettle();
      await tester.tap(find.text(CaptureMessages.replace));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.createScoreWith(3)), findsOneWidget);
      expect(h.files.deleted, isNot(contains('x.pdf')));

      // Photos that do arrive replace it, and its copy is deleted.
      await _addGallery(tester, h, 2);
      await tester.tap(find.text(CaptureMessages.replace));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.createScoreWith(2)), findsOneWidget);
      expect(h.files.deleted, contains('x.pdf'));
    });

    testWidgets('a failed shot after "Replace" keeps the PDF', (tester) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      h.picker.pdf = const PickedPdf(path: 'x.pdf', name: 'x.pdf');
      await _pickPdf(tester);
      h.camera!.failCapture = true;
      await _shoot(tester);
      await tester.tap(find.text(CaptureMessages.replace));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.captureFailed), findsOneWidget);
      expect(find.text(CaptureMessages.createScoreWith(3)), findsOneWidget);
    });

    testWidgets('a rejected title is fixed via Edit details, pages kept', (
      tester,
    ) async {
      final h = CaptureHarness();
      h.upload.onSubmit = () => Future.error(
        const UploadRejectedException(
          statusCode: 400,
          code: 'title_too_long',
          field: 'title',
        ),
      );
      await pumpCapture(tester, h, startOnDetails: true);
      await tester.enterText(find.byType(TextField).first, 'Ave Maria');
      await tester.pump();
      await tester.tap(find.text(CaptureMessages.nextAddPages));
      await tester.pumpAndSettle();
      await _shoot(tester, 2);
      await tester.tap(find.text(CaptureMessages.createScoreWith(2)));
      await tester.pumpAndSettle();
      expect(find.textContaining('Tap Edit details'), findsOneWidget);
      expect(find.textContaining('Go back'), findsNothing);

      await tester.tap(find.text(CaptureMessages.editDetails));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.editDetailsTitle), findsOneWidget);
      expect(find.text('Ave Maria'), findsOneWidget);
      await tester.enterText(find.byType(TextField).first, 'Ave');
      await tester.pump();
      await tester.tap(find.text(CaptureMessages.saveDetails));
      await tester.pumpAndSettle();

      // Back on Capture, pages intact, banner gone.
      expect(find.text(CaptureMessages.createScoreWith(2)), findsOneWidget);
      expect(find.textContaining('Tap Edit details'), findsNothing);

      // Leaving hands the fix back to step 1.
      await tester.tap(find.byTooltip(CaptureMessages.close));
      await tester.pumpAndSettle();
      await tester.tap(find.text(CaptureMessages.discard));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.detailsTitle), findsOneWidget);
      expect(find.text('Ave'), findsOneWidget);

      // And it is what gets sent.
      await tester.tap(find.text(CaptureMessages.nextAddPages));
      await tester.pumpAndSettle();
      await _shoot(tester);
      h.upload.onSubmit = null;
      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      expect(h.upload.detailsSent.last.title, 'Ave');
      expect(find.text('ROUTE:processing job-42 Ave'), findsOneWidget);
    });

    testWidgets('edited details are sent on retry without leaving', (
      tester,
    ) async {
      final h = CaptureHarness();
      h.upload.onSubmit = () => Future.error(
        const UploadRejectedException(
          statusCode: 400,
          code: 'invalid_tempo',
          field: 'tempoBpm',
        ),
      );
      await pumpCapture(tester, h);
      await _shoot(tester);
      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      await tester.tap(find.text(CaptureMessages.editDetails));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).first, 'Salve');
      await tester.pump();
      await tester.tap(find.text(CaptureMessages.saveDetails));
      await tester.pumpAndSettle();
      h.upload.onSubmit = null;
      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      expect(h.upload.detailsSent.last.title, 'Salve');
    });

    testWidgets('Cancel on Edit details changes nothing', (tester) async {
      final h = CaptureHarness();
      h.upload.onSubmit = () => Future.error(
        const UploadRejectedException(statusCode: 400, code: 'title_invalid'),
      );
      await pumpCapture(tester, h);
      await _shoot(tester);
      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      await tester.tap(find.text(CaptureMessages.editDetails));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).first, 'Other');
      await tester.tap(find.text(CaptureMessages.cancel));
      await tester.pumpAndSettle();
      expect(find.text(CaptureMessages.createScoreWith(1)), findsOneWidget);
      h.upload.onSubmit = null;
      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      expect(h.upload.detailsSent.last.title, 'Ave Maria');
    });

    testWidgets('working files are deleted once nothing needs them', (
      tester,
    ) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      expect(h.files.staleCleared, hasLength(1));

      await _shoot(tester, 3);
      // The raw camera file goes as soon as the page is prepared.
      expect(h.files.deleted, ['raw-0.jpg', 'raw-1.jpg', 'raw-2.jpg']);

      await tester.tap(_label(CaptureMessages.removePage(3)));
      await tester.pumpAndSettle();
      expect(h.files.deleted, isNot(contains('prepared/raw-2.jpg')));
      // A newer removal supersedes the older Undo: its file goes.
      await tester.tap(_label(CaptureMessages.removePage(2)));
      await tester.pumpAndSettle();
      expect(h.files.deleted, contains('prepared/raw-2.jpg'));
      expect(h.files.deleted, isNot(contains('prepared/raw-1.jpg')));
      // Dismissing the Undo snack bar lets the last one go too.
      await tester.drag(find.byType(SnackBar), const Offset(0, 300));
      await tester.pumpAndSettle();
      expect(h.files.deleted, contains('prepared/raw-1.jpg'));
      expect(h.files.deleted, isNot(contains('prepared/raw-0.jpg')));

      // An edit deletes the pre-edit file.
      await tester.tap(_label(CaptureMessages.editPage(1)));
      await tester.pumpAndSettle();
      await tester.tap(find.text(CaptureMessages.rotate));
      await tester.pump();
      await tester.tap(find.text(CaptureMessages.done));
      await tester.pumpAndSettle();
      expect(h.files.deleted, contains('prepared/raw-0.jpg'));

      // A sent score's pages go once the server has them.
      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      expect(h.files.deleted, contains('prepared/raw-0.jpg+edit1'));
    });

    testWidgets('gallery copies and discarded pages are deleted', (
      tester,
    ) async {
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _addGallery(tester, h, 2);
      expect(h.files.deleted, unorderedEquals(['g0.jpg', 'g1.jpg']));

      await tester.tap(find.byTooltip(CaptureMessages.close));
      await tester.pumpAndSettle();
      await tester.tap(find.text(CaptureMessages.discard));
      await tester.pumpAndSettle();
      expect(
        h.files.deleted,
        containsAll(['prepared/g0.jpg', 'prepared/g1.jpg']),
      );
    });

    testWidgets('a rejected or declined PDF copy is deleted', (tester) async {
      final h = CaptureHarness(device: FakeDeviceChannel(pages: 21));
      await pumpCapture(tester, h);
      h.picker.pdf = const PickedPdf(path: 'long.pdf', name: 'long.pdf');
      await _pickPdf(tester);
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
      expect(h.files.deleted, ['long.pdf']);
    });
  });

  group('layout and accessibility (NFR-10, NFR-3)', () {
    for (final status in ['ready', 'denied']) {
      testWidgets('320x568 at 2x text fits ($status camera)', (tester) async {
        final h = CaptureHarness(
          permissions: FakeCapturePermissions(
            camera: status == 'ready'
                ? PermissionOutcome.granted
                : PermissionOutcome.denied,
          ),
        );
        await pumpCapture(tester, h, size: const Size(320, 568), textScale: 2);
        expect(tester.takeException(), isNull);
        await _addGallery(tester, h, 4);
        expect(tester.takeException(), isNull);
        await tester.scrollUntilVisible(
          find.text(CaptureMessages.createScoreWith(4)),
          100,
          scrollable: find.byType(Scrollable).first,
        );
        expect(find.text(CaptureMessages.createScoreWith(4)), findsOneWidget);
      });
    }

    testWidgets('320x568 at 2x: Edit details and Cancel sending fit', (
      tester,
    ) async {
      final h = CaptureHarness();
      h.upload.onSubmit = () => Future.error(
        const UploadRejectedException(statusCode: 400, code: 'title_invalid'),
      );
      await pumpCapture(tester, h, size: const Size(320, 568), textScale: 2);
      await _addGallery(tester, h, 2);
      // Everything is built (no lazy list), so bring it into view.
      Future<void> show(Finder finder) async {
        await tester.ensureVisible(finder);
        await tester.pump();
      }

      final create = find.text(CaptureMessages.createScoreWith(2));
      await show(create);
      await tester.tap(create);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await show(find.text(CaptureMessages.editDetails));
      expect(
        tester.getSize(find.textContaining('Tap Edit details')).width,
        greaterThan(150),
      );

      final never = Completer<SubmittedJob>();
      h.upload.onSubmit = () => never.future;
      await show(create);
      await tester.tap(create);
      await tester.pump();
      expect(tester.takeException(), isNull);
      await show(find.text(CaptureMessages.cancelUpload));
      await tester.tap(find.text(CaptureMessages.cancelUpload));
      await tester.pump();
      await tester.pump();
      expect(_submitButton(tester).onPressed, isNotNull);
    });

    testWidgets('meets tap-target, label and contrast guidelines', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      final h = CaptureHarness();
      await pumpCapture(tester, h);
      await _addGallery(tester, h, 2);
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      handle.dispose();
    });
  });
}
