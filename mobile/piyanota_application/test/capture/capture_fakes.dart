import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart' show CancelToken;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;

import 'package:piyanota_application/models/page_edit.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/capture/capture_screen.dart';
import 'package:piyanota_application/screens/capture/score_details_screen.dart';
import 'package:piyanota_application/services/capture/capture_camera.dart';
import 'package:piyanota_application/services/capture/capture_files.dart';
import 'package:piyanota_application/services/capture/capture_permissions.dart';
import 'package:piyanota_application/services/capture/device_channel.dart';
import 'package:piyanota_application/services/capture/page_image_processor.dart';
import 'package:piyanota_application/services/capture/page_image_source.dart';
import 'package:piyanota_application/services/capture/page_picker.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/services/session_storage.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/capture_providers.dart';

import '../auth/auth_test_harness.dart';

/// A real 1x1 PNG, so thumbnails decode without touching disk.
final Uint8List kTinyPng = img.encodePng(img.Image(width: 1, height: 1));

class FakeCaptureCamera implements CaptureCamera {
  FakeCaptureCamera({this.failInit = false, this.failCapture = false});

  bool failInit;
  bool failCapture;
  bool initialized = false;
  bool disposed = false;
  bool? torch;
  Offset? focusedAt;
  int shots = 0;

  @override
  Future<void> initialize() async {
    if (failInit) throw const CameraUnavailableException();
    initialized = true;
  }

  @override
  double get previewAspectRatio => 3 / 4;

  @override
  Widget buildPreview() =>
      const ColoredBox(color: Colors.grey, child: SizedBox.expand());

  @override
  Future<void> setTorch({required bool on}) async => torch = on;

  @override
  Future<void> focusAt(Offset point) async => focusedAt = point;

  @override
  Future<String> takePicture() async {
    if (failCapture) throw const CameraUnavailableException();
    return 'raw-${shots++}.jpg';
  }

  @override
  Future<void> dispose() async => disposed = true;
}

class FakeCapturePermissions implements CapturePermissions {
  FakeCapturePermissions({
    this.camera = PermissionOutcome.granted,
    this.gallery = PermissionOutcome.granted,
  });

  PermissionOutcome camera;
  PermissionOutcome gallery;

  /// What [cameraGranted] reports on resume (e.g. after Settings).
  bool? grantedOnResume;
  int cameraRequests = 0;
  int galleryRequests = 0;
  int settingsOpened = 0;

  @override
  Future<PermissionOutcome> requestCamera() async {
    cameraRequests++;
    return camera;
  }

  @override
  Future<bool> cameraGranted() async =>
      grantedOnResume ?? camera == PermissionOutcome.granted;

  @override
  Future<PermissionOutcome> requestGallery() async {
    galleryRequests++;
    return gallery;
  }

  @override
  Future<bool> openSettings() async {
    settingsOpened++;
    return true;
  }
}

class FakePagePicker implements PagePicker {
  List<String> gallery = const [];
  PickedPdf? pdf;
  bool notAPdf = false;

  @override
  Future<List<String>> pickGalleryImages() async => gallery;

  @override
  Future<PickedPdf?> pickPdf() async {
    if (notAPdf) throw const NotAPdfException();
    return pdf;
  }
}

/// Prepares by renaming; paths containing "bad" are unreadable images.
class FakePageImageProcessor implements PageImageProcessor {
  final List<String> prepared = [];
  final List<(String, PageEdit)> edits = [];
  Completer<void>? gate;

  @override
  Future<String> prepare(String sourcePath) async {
    await gate?.future;
    if (sourcePath.contains('bad')) throw const UnreadableImageException();
    prepared.add(sourcePath);
    return 'prepared/$sourcePath';
  }

  @override
  Future<String> applyEdit(String path, PageEdit edit) async {
    edits.add((path, edit));
    return '$path+edit${edits.length}';
  }
}

/// Records deletions instead of touching disk.
class FakeCaptureFileStore implements CaptureFileStore {
  final List<String> deleted = [];
  final List<DateTime> staleCleared = [];

  @override
  Future<void> delete(String path) async => deleted.add(path);

  @override
  Future<void> clearStale(DateTime before) async => staleCleared.add(before);
}

class FakePageImageSource implements PageImageSource {
  const FakePageImageSource([this.size = const Size(300, 400)]);

  final Size size;

  @override
  ImageProvider imageFor(String path) => MemoryImage(kTinyPng);

  @override
  Future<Size> sizeOf(String path) async => size;
}

class FakeDeviceChannel implements DeviceChannel {
  FakeDeviceChannel({this.pages = 3, this.problem});

  int pages;
  PdfProblem? problem;

  @override
  Future<int> sdkInt() async => 34;

  @override
  Future<int> pdfPageCount(String path) async {
    if (problem case final p?) throw PdfUnreadableException(p);
    return pages;
  }
}

class ScriptedScoreUploadApi implements ScoreUploadApi {
  Future<SubmittedJob> Function()? onSubmit;
  final List<List<String>> imageCalls = [];
  final List<String> pdfCalls = [];
  final List<ScoreDetails> detailsSent = [];

  static const job = SubmittedJob(
    jobId: 'job-42',
    pageCount: 2,
    status: 'queued',
  );

  /// The token passed with the latest submit.
  CancelToken? lastCancelToken;

  /// Like the real API, a cancel wins over a still-pending answer.
  Future<SubmittedJob> _answer(CancelToken? cancelToken) {
    lastCancelToken = cancelToken;
    final answer = onSubmit?.call() ?? Future.value(job);
    if (cancelToken == null) return answer;
    return Future.any([
      answer,
      cancelToken.whenCancel.then<SubmittedJob>(
        (_) => throw const UploadCancelledException(),
      ),
    ]);
  }

  @override
  Future<SubmittedJob> submitImages({
    required ScoreDetails details,
    required List<String> imagePaths,
    CancelToken? cancelToken,
  }) {
    detailsSent.add(details);
    imageCalls.add(imagePaths);
    return _answer(cancelToken);
  }

  @override
  Future<SubmittedJob> submitPdf({
    required ScoreDetails details,
    required String pdfPath,
    CancelToken? cancelToken,
  }) {
    detailsSent.add(details);
    pdfCalls.add(pdfPath);
    return _answer(cancelToken);
  }
}

/// Everything Capture talks to, faked, plus the overrides that install it.
class CaptureHarness {
  CaptureHarness({
    FakeCapturePermissions? permissions,
    FakeDeviceChannel? device,
  }) : permissions = permissions ?? FakeCapturePermissions(),
       device = device ?? FakeDeviceChannel();

  final FakeCapturePermissions permissions;
  final FakeDeviceChannel device;
  final picker = FakePagePicker();
  final processor = FakePageImageProcessor();
  final upload = ScriptedScoreUploadApi();
  final files = FakeCaptureFileStore();
  final secureStorage = FaultySecureStorage({'session_token': 'sess_t'});
  final List<FakeCaptureCamera> cameras = [];
  bool cameraFailsInit = false;

  FakeCaptureCamera? get camera => cameras.isEmpty ? null : cameras.last;

  List<Override> get overrides => [
    capturePermissionsProvider.overrideWithValue(permissions),
    deviceChannelProvider.overrideWithValue(device),
    pagePickerProvider.overrideWithValue(picker),
    pageImageProcessorProvider.overrideWithValue(processor),
    pageImageSourceProvider.overrideWithValue(const FakePageImageSource()),
    captureCameraFactoryProvider.overrideWithValue(() {
      final camera = FakeCaptureCamera(failInit: cameraFailsInit);
      cameras.add(camera);
      return camera;
    }),
    scoreUploadApiProvider.overrideWithValue(upload),
    captureFileStoreProvider.overrideWithValue(files),
    sessionStorageProvider.overrideWithValue(SessionStorage(secureStorage)),
  ];
}

const kDetails = ScoreDetails(title: 'Ave Maria');
const kLibraryMarker = 'ROUTE:library';
const kLoginMarker = 'ROUTE:login';

/// Pumps a library stand-in with Capture pushed on top, so Close, submit
/// and Back can be checked against a real stack.
Future<void> pumpCapture(
  WidgetTester tester,
  CaptureHarness harness, {
  ScoreDetails details = kDetails,
  Size size = const Size(400, 800),
  double textScale = 1,
  bool startOnDetails = false,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: harness.overrides,
      child: MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: TextScaler.linear(textScale)),
          child: child!,
        ),
        initialRoute: AppRoutes.scoreLibrary,
        routes: {
          AppRoutes.scoreLibrary: (_) =>
              const Scaffold(body: Text(kLibraryMarker)),
          AppRoutes.login: (_) => const Scaffold(body: Text(kLoginMarker)),
          AppRoutes.capture: (_) => const ScoreDetailsScreen(),
          AppRoutes.capturePages: (context) {
            final args =
                ModalRoute.of(context)!.settings.arguments!
                    as CapturePagesArguments;
            return CaptureScreen(details: args.details);
          },
          AppRoutes.processing: (context) {
            final args =
                ModalRoute.of(context)!.settings.arguments!
                    as ProcessingArguments;
            return Scaffold(
              body: Text('ROUTE:processing ${args.jobId} ${args.title}'),
            );
          },
        },
      ),
    ),
  );
  final navigator = tester.state<NavigatorState>(find.byType(Navigator));
  if (startOnDetails) {
    navigator.pushNamed(AppRoutes.capture);
  } else {
    navigator.pushNamed(
      AppRoutes.capturePages,
      arguments: CapturePagesArguments(details: details),
    );
  }
  await tester.pumpAndSettle();
}
